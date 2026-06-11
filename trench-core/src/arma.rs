//! Deterministic ARMA (pole-zero) corner fit.
//!
//! Fits a 6-biquad cascade — numerator `B(z)` and denominator `A(z)`, each order
//! 12 — to a dropped sound's spectral envelope by frequency-domain least squares
//! (Sanathanan–Koerner / Steiglitz–McBride iteration against a *minimum-phase*
//! target built from the magnitude). Unlike all-pole LPC, the moving-average part
//! places real **zeros**: the anti-formant notches and bitey upper teeth of
//! E-mu/X3 frames (DJ Alkaline et al.) that an all-pole fit physically cannot
//! carve.
//!
//! It is a *deterministic translator*: each iteration is one weighted linear
//! solve (the source's envelope → coefficients). No penalty search, no per-stage
//! constraints, no internal energy shaping — pick a source, the fit reflects it.
//!
//! Pure Rust, no deps. The Forge calls [`fit_corner_arma`]; on any non-finite or
//! degenerate result the caller falls back to the LPC path, so the ARMA fit can
//! only improve on it, never regress below it.

use crate::cartridge::CornerData;
use crate::cascade::{NUM_COEFFS, NUM_STAGES};
use std::f64::consts::PI;

#[cfg(test)]
const ANALYSIS_SR: f64 = 22_050.0;
const ORDER: usize = 2 * NUM_STAGES; // 12 → six biquads
const N_FFT: usize = 4096;
const N_FIT: usize = 256; // log-spaced fit frequencies
const SK_ITERS: usize = 6;
const F_MIN: f64 = 55.0;
const F_MAX: f64 = 10_500.0;
const PASSTHROUGH: [f64; NUM_COEFFS] = [2.0, 1.0, 2.0, 1.0, 1.0];

// ── minimal complex ───────────────────────────────────────────────────────────
#[derive(Clone, Copy)]
struct Cx {
    re: f64,
    im: f64,
}
impl Cx {
    const ZERO: Cx = Cx { re: 0.0, im: 0.0 };
    fn new(re: f64, im: f64) -> Self {
        Cx { re, im }
    }
    /// e^{jθ}
    fn expj(theta: f64) -> Self {
        Cx::new(theta.cos(), theta.sin())
    }
    fn add(self, o: Cx) -> Cx {
        Cx::new(self.re + o.re, self.im + o.im)
    }
    fn sub(self, o: Cx) -> Cx {
        Cx::new(self.re - o.re, self.im - o.im)
    }
    fn mul(self, o: Cx) -> Cx {
        Cx::new(
            self.re * o.re - self.im * o.im,
            self.re * o.im + self.im * o.re,
        )
    }
    fn scale(self, s: f64) -> Cx {
        Cx::new(self.re * s, self.im * s)
    }
    fn conj(self) -> Cx {
        Cx::new(self.re, -self.im)
    }
    fn abs(self) -> f64 {
        self.re.hypot(self.im)
    }
    fn abs2(self) -> f64 {
        self.re * self.re + self.im * self.im
    }
    fn div(self, o: Cx) -> Cx {
        let d = o.abs2().max(1e-300);
        Cx::new(
            (self.re * o.re + self.im * o.im) / d,
            (self.im * o.re - self.re * o.im) / d,
        )
    }
    fn cexp(self) -> Cx {
        // e^{re + j im}
        Cx::expj(self.im).scale(self.re.exp())
    }
}

// ── iterative radix-2 FFT (in place) ───────────────────────────────────────────
fn fft(buf: &mut [Cx], inverse: bool) {
    let n = buf.len();
    if n < 2 {
        return;
    }
    // bit reversal
    let mut j = 0usize;
    for i in 1..n {
        let mut bit = n >> 1;
        while j & bit != 0 {
            j ^= bit;
            bit >>= 1;
        }
        j ^= bit;
        if i < j {
            buf.swap(i, j);
        }
    }
    let mut len = 2;
    while len <= n {
        let ang = if inverse {
            2.0 * PI / len as f64
        } else {
            -2.0 * PI / len as f64
        };
        let wlen = Cx::expj(ang);
        let half = len / 2;
        let mut i = 0;
        while i < n {
            let mut w = Cx::new(1.0, 0.0);
            for k in 0..half {
                let u = buf[i + k];
                let v = buf[i + k + half].mul(w);
                buf[i + k] = u.add(v);
                buf[i + k + half] = u.sub(v);
                w = w.mul(wlen);
            }
            i += len;
        }
        len <<= 1;
    }
    if inverse {
        let inv = 1.0 / n as f64;
        for x in buf.iter_mut() {
            *x = x.scale(inv);
        }
    }
}

// ── linear resample ─────────────────────────────────────────────────────────
fn resample(x: &[f64], sr_in: f64, sr_out: f64) -> Vec<f64> {
    if (sr_in - sr_out).abs() < 1.0 || x.len() < 2 {
        return x.to_vec();
    }
    let ratio = sr_in / sr_out;
    let n = ((x.len() as f64) / ratio).floor() as usize;
    (0..n)
        .map(|i| {
            let pos = i as f64 * ratio;
            let i0 = pos.floor() as usize;
            let f = pos - i0 as f64;
            let a = x[i0];
            let b = if i0 + 1 < x.len() { x[i0 + 1] } else { a };
            a + (b - a) * f
        })
        .collect()
}

// ── solve a small real linear system (Gaussian elimination, partial pivot) ─────
fn solve(mut a: Vec<Vec<f64>>, mut b: Vec<f64>) -> Option<Vec<f64>> {
    let n = b.len();
    for col in 0..n {
        let mut piv = col;
        let mut best = a[col][col].abs();
        for r in (col + 1)..n {
            if a[r][col].abs() > best {
                best = a[r][col].abs();
                piv = r;
            }
        }
        if best < 1e-18 {
            return None;
        }
        a.swap(col, piv);
        b.swap(col, piv);
        let d = a[col][col];
        for r in (col + 1)..n {
            let f = a[r][col] / d;
            if f != 0.0 {
                for c in col..n {
                    a[r][c] -= f * a[col][c];
                }
                b[r] -= f * b[col];
            }
        }
    }
    let mut x = vec![0.0; n];
    for i in (0..n).rev() {
        let mut s = b[i];
        for c in (i + 1)..n {
            s -= a[i][c] * x[c];
        }
        x[i] = s / a[i][i];
    }
    Some(x)
}

// ── roots of a real polynomial, coeffs high→low (Durand-Kerner) ────────────────
fn roots(coeffs: &[f64]) -> Vec<Cx> {
    // strip leading zeros
    let mut c = coeffs;
    while c.len() > 1 && c[0].abs() < 1e-15 {
        c = &c[1..];
    }
    let p = c.len() - 1;
    if p == 0 {
        return vec![];
    }
    let lead = c[0];
    let monic: Vec<Cx> = c.iter().map(|&v| Cx::new(v / lead, 0.0)).collect();
    let eval = |z: Cx| -> Cx {
        let mut acc = Cx::ZERO;
        for cc in &monic {
            acc = acc.mul(z).add(*cc);
        }
        acc
    };
    let seed = Cx::new(0.4, 0.9);
    let mut zs = Vec::with_capacity(p);
    let mut cur = Cx::new(1.0, 0.0);
    for _ in 0..p {
        zs.push(cur);
        cur = cur.mul(seed);
    }
    for _ in 0..500 {
        let mut maxd = 0.0f64;
        for i in 0..p {
            let zi = zs[i];
            let mut den = Cx::new(1.0, 0.0);
            for (j, &zj) in zs.iter().enumerate() {
                if j != i {
                    den = den.mul(zi.sub(zj));
                }
            }
            if den.abs() < 1e-300 {
                continue;
            }
            let step = eval(zi).div(den);
            zs[i] = zi.sub(step);
            maxd = maxd.max(step.abs());
        }
        if maxd < 1e-13 {
            break;
        }
    }
    zs
}

/// Whether a root list is poles (denominator) or zeros (numerator): the two are
/// brought inside the unit circle differently — see [`to_quadratics`].
#[derive(Clone, Copy, PartialEq)]
enum RootKind {
    Pole,
    Zero,
}

/// Group ALL roots of a polynomial into monic second-order sections `[1, q1, q2]`
/// — conjugate pairs become `[1, -2Re, |z|²]`, leftover real roots are paired two
/// at a time. Using every root means the product of the sections equals the
/// original polynomial (up to its leading gain), so the realized cascade response
/// is `B/A` exactly — no dropped poles or zeros.
///
/// Roots are brought inside the unit circle so the kernel coefficients land in the
/// packable minifloat box (`c1=1-|z|²∈[0,1]`, `c3=1-|pole|²∈[0,1]`):
/// - **Poles** on/outside the circle are scaled just inside (`0.999/r`) — a
///   stability fix (a pole outside diverges).
/// - **Zeros** outside the circle are reflected to their min-phase image
///   `1/conj(z) = z/|z|²`. This is *magnitude-preserving* up to a constant gain
///   (absorbed by `normalize_peak`): the LS solve for `B(z)` can land spurious
///   roots outside the circle even though the fit target is minimum-phase, and an
///   order-12 numerator over-modelling a simpler source invents huge real zeros
///   (|z|≫1) that otherwise blow `c0/c1` far past [0,1]. Reflecting restores the
///   min-phase realisation the target intended — not character shaping.
fn to_quadratics(rs: &[Cx], kind: RootKind) -> Vec<[f64; 3]> {
    let fix = |z: Cx| -> Cx {
        match kind {
            RootKind::Pole => {
                let r = z.abs();
                // Authoring resonance cap. 0.999 ≈ 12 Hz bandwidth — a runaway
                // whistle that transient/noisy sources fit invents (the ~100 dB
                // over-reach). 0.995 ≈ 60 Hz — a musical formant. The captured
                // corner must not start as a scream at Morph0/Q0; the Q axis
                // sharpens it from here when the player wants it.
                const RMAX: f64 = 0.999; // match talking_hedz's razor Q100 poles (0.999)
                if r >= RMAX {
                    z.scale(RMAX / r.max(1e-12))
                } else {
                    z
                }
            }
            RootKind::Zero => {
                let r2 = z.abs2();
                if r2 > 1.0 {
                    z.scale(1.0 / r2) // 1/conj(z): reflect inside, |z|→1/|z|
                } else {
                    z
                }
            }
        }
    };
    let mut taken = vec![false; rs.len()];
    let mut out = Vec::new();
    for i in 0..rs.len() {
        if taken[i] {
            continue;
        }
        taken[i] = true;
        let zi = fix(rs[i]);
        if zi.im.abs() > 1e-7 {
            // complex → consume its nearest unused conjugate as the pair
            let conj = zi.conj();
            let mut bestj = None;
            let mut bestd = f64::INFINITY;
            for (j, &zj) in rs.iter().enumerate() {
                if taken[j] {
                    continue;
                }
                let d = zj.sub(conj).abs();
                if d < bestd {
                    bestd = d;
                    bestj = Some(j);
                }
            }
            if let Some(j) = bestj {
                taken[j] = true;
            }
            out.push([1.0, -2.0 * zi.re, zi.abs2()]);
        } else {
            // real → pair with the next unused real root
            let mut r2 = 0.0;
            for (j, &zj) in rs.iter().enumerate() {
                if taken[j] || zj.im.abs() > 1e-7 {
                    continue;
                }
                taken[j] = true;
                r2 = fix(zj).re;
                break;
            }
            let r1 = zi.re;
            out.push([1.0, -(r1 + r2), r1 * r2]);
        }
    }
    out
}

/// A section's resonant angle (∝ frequency) — for ordering sections only.
fn quad_freq(q: &[f64; 3]) -> f64 {
    let r = q[2].max(0.0).sqrt();
    if r <= 1e-9 {
        return 0.0;
    }
    (-q[1] / (2.0 * r)).clamp(-1.0, 1.0).acos()
}

/// Fit a recorded sound to one corner as a six-section pole-zero cascade, in
/// kernel form. `samples` is the already-windowed slice the Forge wants fit.
/// Returns `None` if the fit is degenerate (caller falls back to LPC).
pub fn fit_corner_arma(samples: &[f64], sr_in: f64, runtime_sr: f64) -> Option<CornerData> {
    if samples.len() < 64 {
        return None;
    }
    // Author in the runtime z-plane (the E-mu rate the cartridge plays at), NOT a
    // separate analysis rate — otherwise every pole/zero warps by runtime/analysis
    // when played. (LPC already places poles at runtime_sr; this matches it.)
    let x = resample(samples, sr_in, runtime_sr);
    if x.len() < 32 {
        return None;
    }

    // ── magnitude spectrum (zero-padded FFT of the conditioned slice) ──
    let mut buf = vec![Cx::ZERO; N_FFT];
    for (i, &v) in x.iter().take(N_FFT).enumerate() {
        buf[i] = Cx::new(v, 0.0);
    }
    fft(&mut buf, false);
    let mut logmag = vec![0.0f64; N_FFT];
    for k in 0..N_FFT {
        logmag[k] = (buf[k].abs() + 1e-9).ln();
    }
    arma_fit_from_logmag(&logmag, runtime_sr)
}

/// Factorize a clean TARGET magnitude curve (sorted `(freq_hz, db)` points) into
/// one corner — the response-first path. The SAME ARMA solver, fed an audited
/// target instead of messy audio: the taste lives in the curve, the fit stays
/// dumb (no anatomy heuristics, no per-stage roles). This is how a "Target
/// Template" becomes a 6-stage cascade.
pub fn fit_corner_from_magnitude(curve: &[(f64, f64)], runtime_sr: f64) -> Option<CornerData> {
    if curve.len() < 2 {
        return None;
    }
    let half = N_FFT / 2;
    let bin_hz = runtime_sr / N_FFT as f64;
    let mut logmag = vec![0.0f64; N_FFT];
    for k in 0..N_FFT {
        let kk = if k <= half { k } else { N_FFT - k }; // symmetric spectrum
        logmag[k] = interp_db(curve, kk as f64 * bin_hz) * std::f64::consts::LN_10 / 20.0;
    }
    arma_fit_from_logmag(&logmag, runtime_sr)
}

fn interp_db(curve: &[(f64, f64)], f: f64) -> f64 {
    if f <= curve[0].0 {
        return curve[0].1;
    }
    let last = curve.len() - 1;
    if f >= curve[last].0 {
        return curve[last].1;
    }
    for w in curve.windows(2) {
        if f >= w[0].0 && f <= w[1].0 {
            let t = if w[1].0 > w[0].0 {
                (f - w[0].0) / (w[1].0 - w[0].0)
            } else {
                0.0
            };
            return w[0].1 + (w[1].1 - w[0].1) * t;
        }
    }
    curve[last].1
}

/// The ARMA solve from a log-magnitude spectrum onward — shared by the audio fit
/// (`fit_corner_arma`) and the target-curve factorizer (`fit_corner_from_magnitude`).
fn arma_fit_from_logmag(logmag: &[f64], runtime_sr: f64) -> Option<CornerData> {
    let half = N_FFT / 2;
    let bin_hz = runtime_sr / N_FFT as f64;

    // ── minimum-phase FORMANT-ENVELOPE target via cepstral liftering ──
    // Real cepstrum of the raw log-magnitude, keep only the LOW quefrencies (the
    // formant envelope), drop the high quefrencies (the pitch comb). A low-pitched
    // voice has dense harmonics the old 1/24-oct smoothing couldn't bridge, so ARMA
    // fit the loud harmonics + HF junk instead of the formants. The lifter hands it
    // the envelope to fit — the same liftering that surfaces formants cleanly.
    let mut cep = vec![Cx::ZERO; N_FFT];
    for k in 0..N_FFT {
        cep[k] = Cx::new(logmag[k], 0.0); // |buf[k]| is already symmetric (real input)
    }
    fft(&mut cep, true); // real cepstrum
    let lifter = 64usize.min(half - 1); // keep formant envelope, cut the pitch comb
    let mut mp = vec![Cx::ZERO; N_FFT];
    mp[0] = Cx::new(cep[0].re, 0.0);
    for n in 1..lifter {
        mp[n] = Cx::new(2.0 * cep[n].re, 0.0); // min-phase fold, low-quefrency only
    }
    fft(&mut mp, false); // = log of the min-phase envelope
    let hmin: Vec<Cx> = (0..N_FFT).map(|k| mp[k].cexp()).collect();

    // ── log-spaced fit frequencies + sampled target ──
    let mut omega = vec![0.0f64; N_FIT];
    let mut htarget = vec![Cx::ZERO; N_FIT];
    let mut weight = vec![0.0f64; N_FIT];
    for i in 0..N_FIT {
        let t = i as f64 / (N_FIT - 1) as f64;
        let f = F_MIN * (F_MAX / F_MIN).powf(t);
        let w = 2.0 * PI * f / runtime_sr;
        omega[i] = w;
        // sample hmin at bin position (linear interp)
        let pos = f / bin_hz;
        let k0 = pos.floor() as usize;
        let frac = pos - k0 as f64;
        let h = if k0 + 1 <= half {
            hmin[k0].scale(1.0 - frac).add(hmin[k0 + 1].scale(frac))
        } else {
            hmin[half]
        };
        htarget[i] = h;
        // TRANSPARENCY weighting (audit 2026-05-24): weight the LS by the SOURCE's
        // own magnitude, so the loud body/formants are matched and the quiet high
        // band stops dominating the equation-error solve. Uniform log weighting
        // (formerly here) was measured tilting bodied sources +20..+60 dB BRIGHT and
        // discarding the low body — the opposite of transparent. The bright tilt the
        // old comment feared comes from over-weighting the QUIET highs, not from
        // honouring energy; weighting toward the source envelope is what matches it.
        // A small floor keeps notches/valleys represented.
        weight[i] = h.abs().max(1e-4);
    }

    // ── Sanathanan–Koerner iteration: solve for a[1..=ORDER], b[0..=ORDER] ──
    // Model H(w) ≈ B(w)/A(w); each iter minimises Σ_k W_k |B - H·A|² with
    // W_k = weight_k / |A_prev(w_k)|² (A_prev = 1 on the first pass = Levi).
    let p = (ORDER + 1) + ORDER; // unknowns: b_0..b_ORDER, a_1..a_ORDER
                                 // precompute e^{-jwl} for each freq and lag
    let mut ejw = vec![vec![Cx::ZERO; ORDER + 1]; N_FIT];
    for i in 0..N_FIT {
        for l in 0..=ORDER {
            ejw[i][l] = Cx::expj(-omega[i] * l as f64);
        }
    }
    let mut a_prev = vec![0.0f64; ORDER + 1]; // a_prev[0]=1
    a_prev[0] = 1.0;
    let mut best: Option<(Vec<f64>, Vec<f64>)> = None;
    for _iter in 0..SK_ITERS {
        let mut ata = vec![vec![0.0f64; p]; p];
        let mut atb = vec![0.0f64; p];
        for i in 0..N_FIT {
            // A_prev(w_i)
            let mut ap = Cx::ZERO;
            for m in 0..=ORDER {
                ap = ap.add(ejw[i][m].scale(a_prev[m]));
            }
            let wk = weight[i] / ap.abs2().max(1e-12);
            let sw = wk.sqrt();
            // complex design row R (len p) and rhs
            let mut row = vec![Cx::ZERO; p];
            for l in 0..=ORDER {
                row[l] = ejw[i][l].scale(sw); // b_l
            }
            let h = htarget[i];
            for m in 1..=ORDER {
                row[ORDER + m] = h.mul(ejw[i][m]).scale(-sw); // a_m
            }
            let rhs = h.scale(sw);
            // accumulate Re(R^H R) and Re(R^H rhs)
            for r in 0..p {
                let rr = row[r].conj();
                atb[r] += rr.mul(rhs).re;
                for cc in r..p {
                    let v = rr.mul(row[cc]).re;
                    ata[r][cc] += v;
                    if cc != r {
                        ata[cc][r] += v;
                    }
                }
            }
        }
        for d in 0..p {
            ata[d][d] += 1e-7; // tiny ridge for conditioning
        }
        let Some(sol) = solve(ata, atb) else { break };
        let mut bco = vec![0.0f64; ORDER + 1];
        let mut aco = vec![0.0f64; ORDER + 1];
        aco[0] = 1.0;
        for l in 0..=ORDER {
            bco[l] = sol[l];
        }
        for m in 1..=ORDER {
            aco[m] = sol[ORDER + m];
        }
        if !bco.iter().chain(aco.iter()).all(|v| v.is_finite()) {
            break;
        }
        a_prev = aco.clone();
        best = Some((bco, aco));
    }
    let (bco, aco) = best?;

    // ── faithful 6-biquad realization of B(z)/A(z) ──
    // Group EVERY denominator root and EVERY numerator root into second-order
    // sections, so the cascade response equals B/A exactly (no dropped poles or
    // zeros). Order both lists by resonant frequency (conditioning only — the
    // overall response is invariant to section ordering), then section i = the
    // i-th numerator over the i-th denominator. The overall gain (B's leading
    // coeff) is absorbed by the peak normalisation below.
    let mut den = to_quadratics(&roots(&aco), RootKind::Pole);
    let mut num = to_quadratics(&roots(&bco), RootKind::Zero);
    if den.is_empty() {
        return None;
    }
    den.sort_by(|a, b| quad_freq(a).partial_cmp(&quad_freq(b)).unwrap());
    num.sort_by(|a, b| quad_freq(a).partial_cmp(&quad_freq(b)).unwrap());
    while den.len() < NUM_STAGES {
        den.push([1.0, 0.0, 0.0]);
    }
    while num.len() < NUM_STAGES {
        num.push([1.0, 0.0, 0.0]);
    }
    den.truncate(NUM_STAGES);
    num.truncate(NUM_STAGES);

    let mut corner: CornerData = [PASSTHROUGH; NUM_STAGES];
    for i in 0..NUM_STAGES {
        let [_, a1, a2] = den[i];
        let [_, b1, b2] = num[i]; // monic numerator (b0 = 1); level set below
                                  // kernel form: c0 = 2 + b1/b0, c1 = 1 - b2/b0, c2 = a1 + 2, c3 = 1 - a2, c4 = b0
        corner[i] = [2.0 + b1, 1.0 - b2, a1 + 2.0, 1.0 - a2, 1.0];
    }
    normalize_peak(&mut corner, runtime_sr, 0.5);
    if corner.iter().flatten().all(|v| v.is_finite()) {
        Some(corner)
    } else {
        None
    }
}

/// Scale the cascade so its peak magnitude ≈ `target`. The scalar gain is spread
/// evenly across the active sections (`g^(1/n)` per stage) rather than dumped on
/// one — the cascade is a product, so this is the *same* transfer function with
/// the gain merely relocated, but it keeps every `c4` inside the packable [0,4]
/// box instead of letting one stage's gain underflow/overflow the minifloat.
fn normalize_peak(corner: &mut CornerData, sr: f64, target: f64) {
    let mag_at = |k: &[f64; NUM_COEFFS], w: f64| -> f64 {
        let (c0, c1, c2, c3, c4) = (k[0], k[1], k[2], k[3], k[4]);
        let (b0, b1, b2, a1, a2) = (c4, (c0 - 2.0) * c4, (1.0 - c1) * c4, c2 - 2.0, 1.0 - c3);
        let (cw, c2w, sw, s2w) = (w.cos(), (2.0 * w).cos(), w.sin(), (2.0 * w).sin());
        let nr = b0 + b1 * cw + b2 * c2w;
        let ni = -b1 * sw - b2 * s2w;
        let dr = 1.0 + a1 * cw + a2 * c2w;
        let di = -a1 * sw - a2 * s2w;
        ((nr * nr + ni * ni) / (dr * dr + di * di + 1e-30)).sqrt()
    };
    let mut peak = 1e-9f64;
    for i in 0..128 {
        let f = 40.0 * (16_000.0f64 / 40.0).powf(i as f64 / 127.0);
        let w = 2.0 * PI * f / sr;
        let mut mag = 1.0;
        for k in corner.iter() {
            mag *= mag_at(k, w);
        }
        peak = peak.max(mag);
    }
    let g = target / peak;
    let passth = |k: &[f64; NUM_COEFFS]| {
        (k[0] - 2.0).abs() < 1e-9
            && (k[1] - 1.0).abs() < 1e-9
            && (k[2] - 2.0).abs() < 1e-9
            && (k[3] - 1.0).abs() < 1e-9
            && (k[4] - 1.0).abs() < 1e-9
    };
    let n_active = corner.iter().filter(|k| !passth(k)).count();
    if n_active == 0 {
        return;
    }
    let per = g.powf(1.0 / n_active as f64);
    for k in corner.iter_mut() {
        if !passth(k) {
            k[4] *= per;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // magnitude (dB) of a kernel-form cascade at one frequency
    fn cascade_db(corner: &CornerData, f: f64, sr: f64) -> f64 {
        let w = 2.0 * PI * f / sr;
        let mut mag = 1.0;
        for k in corner.iter() {
            let (c0, c1, c2, c3, c4) = (k[0], k[1], k[2], k[3], k[4]);
            let (b0, b1, b2, a1, a2) = (c4, (c0 - 2.0) * c4, (1.0 - c1) * c4, c2 - 2.0, 1.0 - c3);
            let (cw, c2w, sw, s2w) = (w.cos(), (2.0 * w).cos(), w.sin(), (2.0 * w).sin());
            let nr = b0 + b1 * cw + b2 * c2w;
            let ni = -b1 * sw - b2 * s2w;
            let dr = 1.0 + a1 * cw + a2 * c2w;
            let di = -a1 * sw - a2 * s2w;
            mag *= ((nr * nr + ni * ni) / (dr * dr + di * di + 1e-30)).sqrt();
        }
        20.0 * (mag + 1e-12).log10()
    }

    // impulse response of a known pole/zero cascade (DF2T biquads)
    fn ir(biquads: &[[f64; 5]], n: usize) -> Vec<f64> {
        let mut state = vec![[0.0f64; 2]; biquads.len()];
        (0..n)
            .map(|idx| {
                let mut s = if idx == 0 { 1.0 } else { 0.0 };
                for (i, &[b0, b1, b2, a1, a2]) in biquads.iter().enumerate() {
                    let y = b0 * s + state[i][0];
                    state[i][0] = b1 * s - a1 * y + state[i][1];
                    state[i][1] = b2 * s - a2 * y;
                    s = y;
                }
                s
            })
            .collect()
    }

    fn biquad(fp: f64, rp: f64, fz: f64, rz: f64, sr: f64) -> [f64; 5] {
        let tp = 2.0 * PI * fp / sr;
        let tz = 2.0 * PI * fz / sr;
        [
            1.0,
            -2.0 * rz * tz.cos(),
            rz * rz,
            -2.0 * rp * tp.cos(),
            rp * rp,
        ]
    }

    #[test]
    fn fft_roundtrip() {
        let mut buf: Vec<Cx> = (0..64)
            .map(|i| Cx::new((i as f64 * 0.3).sin(), 0.0))
            .collect();
        let orig = buf.clone();
        fft(&mut buf, false);
        fft(&mut buf, true);
        for (a, b) in orig.iter().zip(&buf) {
            assert!((a.re - b.re).abs() < 1e-9, "fft roundtrip drift");
        }
    }

    #[test]
    fn recovers_notch_and_peaks() {
        // a body resonance, a high resonance, and a DEEP notch between them.
        let sr = ANALYSIS_SR;
        let truth = [
            biquad(500.0, 0.95, 0.0, 0.0, sr),      // body pole
            biquad(3200.0, 0.92, 0.0, 0.0, sr),     // upper pole
            biquad(1500.0, 0.5, 1500.0, 0.985, sr), // sharp notch at 1500
        ];
        let src = ir(&truth, 4096);
        let corner = fit_corner_arma(&src, sr, sr).expect("arma fit");

        // truth response (normalised peak) vs fit, sampled across the band
        let truth_corner: CornerData = {
            let mut c = [PASSTHROUGH; NUM_STAGES];
            for (i, bq) in truth.iter().enumerate() {
                let [b0, b1, b2, a1, a2] = *bq;
                c[i] = [2.0 + b1 / b0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0];
            }
            normalize_peak(&mut c, sr, 0.5);
            c
        };

        for f in [
            200.0, 500.0, 800.0, 1100.0, 1500.0, 2000.0, 2600.0, 3200.0, 4500.0, 7000.0,
        ] {
            println!(
                "  {f:6.0}Hz  fit {:7.1}  truth {:7.1}",
                cascade_db(&corner, f, sr),
                cascade_db(&truth_corner, f, sr)
            );
        }
        // 1) the fit must carve a notch near 1500 Hz: a local min clearly below the
        //    two resonances that flank it (the 500 body and the 3200 upper peak).
        let n = cascade_db(&corner, 1500.0, sr);
        let body = cascade_db(&corner, 500.0, sr);
        let upper = cascade_db(&corner, 3200.0, sr);
        assert!(
            n < body - 8.0 && n < upper - 8.0,
            "no notch at 1500: notch={n:.1} body={body:.1} upper={upper:.1}"
        );

        // 2) broad SHAPE agreement with truth (gain-independent — the product
        //    normalises level separately, so align the means and measure contour).
        let diffs: Vec<f64> = (0..60)
            .map(|i| {
                let f = 100.0 * (9000.0f64 / 100.0).powf(i as f64 / 59.0);
                cascade_db(&corner, f, sr) - cascade_db(&truth_corner, f, sr)
            })
            .collect();
        let mean = diffs.iter().sum::<f64>() / diffs.len() as f64;
        let rms =
            (diffs.iter().map(|d| (d - mean).powi(2)).sum::<f64>() / diffs.len() as f64).sqrt();
        assert!(
            rms < 4.0,
            "envelope shape RMS too high (gain-independent): {rms:.2} dB"
        );
    }
}
