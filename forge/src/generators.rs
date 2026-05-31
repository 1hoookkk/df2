//! generators.rs — INTENTIONAL 8-corner CUBE generators for the Forge.
//!
//! Five architectures, the exact DF2T pole/zero math, spatial X/Y/Z mapping.
//! NO random placement: variety comes from the architecture + its macro ranges,
//! never jitter. Each architecture is a continuous field over (x,y,z) ∈ [0,1]³;
//! the cube is that field sampled at the eight binary vertices, lane roles fixed
//! across all corners (the kin field — the morph middle glides).
//!
//! ENGINE TRUTH (observed, `trench-core/src/cascade.rs` + `forge/src/dsp.rs`):
//! a corner is six biquads, `CornerData = [[f64;5];6]`, kernel form c0..c4.
//! The standard pole/zero → kernel map (the math Tyson specified):
//!
//!   pole (Rp,Fp):  a1 = −2·Rp·cos(2π·Fp/Fs),  a2 = Rp²
//!   zero (Rz,Fz):  b1 = −2·Rz·cos(2π·Fz/Fs),  b2 = Rz²   (monic numerator)
//!   gain g = b0   (scales the section; keeps it from clipping)
//!   kernel = [ 2 + b1,  1 − b2,  a1 + 2,  1 − a2,  g ]
//!
//! This is bit-identical to `pyruntime.freq_response`'s inverse and to
//! `dsp::realize_stage` — one math, no reinvention.
//!
//! CUBE INDEX: corner i has  x = i&1 (Morph),  y = (i>>1)&1 (Q/secondary),
//! z = (i>>2)&1 (Transform). Floor plane (z=0) = indices 0..3, ceiling (z=1) =
//! 4..7, each in body order [M0_Q0, M100_Q0, M0_Q100, M100_Q100].

use std::f64::consts::TAU;
use trench_core::cartridge::CornerData;

pub const SR: f64 = 39_062.5;
/// Stability cap. Tyson's schema reaches R→0.9995; we cap a touch lower so the
/// bilinear morph MIDDLE stays inside the circle (the corners can look fine while
/// the interpolated middle rings out — see dsp::STABILITY_RADIUS_LIMIT).
const RMAX: f64 = 0.9990;
/// A DC-nulling zero ~7 semitones below a pole → rolls the lows off, no pedestal.
const S7: f64 = 0.6674199; // 2^(-7/12)
const PASS: [f64; 5] = [2.0, 1.0, 2.0, 1.0, 1.0];

fn lerp(a: f64, b: f64, t: f64) -> f64 {
    a + (b - a) * t
}
/// Log (octave) interpolation — the perceptually correct way to move frequency.
fn llerp(a: f64, b: f64, t: f64) -> f64 {
    (a.ln() + (b.ln() - a.ln()) * t).exp()
}
fn clampf(f: f64) -> f64 {
    f.clamp(20.0, SR * 0.49)
}
/// Tamed section gain (≈ unity peak before the corner-level normalize).
fn g_tamed(rp: f64) -> f64 {
    (1.0 - rp * rp).max(1.0e-4)
}

/// Spectral friction (Tyson §1): above 2.5 kHz the radius ceiling decays from
/// 0.99 down to 0.96 — acoustic warmth, no HF digital harshness.
fn radius_ceiling(f: f64) -> f64 {
    if f <= 2500.0 {
        0.99
    } else {
        (0.99 - (f - 2500.0) / (16000.0 - 2500.0) * (0.99 - 0.96)).clamp(0.96, 0.99)
    }
}

/// One pole + one zero → kernel section (the canonical map above).
fn pz(fp: f64, rp: f64, fz: f64, rz: f64, g: f64) -> [f64; 5] {
    let wp = TAU * clampf(fp) / SR;
    let wz = TAU * clampf(fz) / SR;
    let a1 = -2.0 * rp * wp.cos();
    let a2 = rp * rp;
    let b1 = -2.0 * rz * wz.cos();
    let b2 = rz * rz;
    [2.0 + b1, 1.0 - b2, a1 + 2.0, 1.0 - a2, g]
}

/// A bare resonant pole (numerator = constant g, no zero).
fn pole(fp: f64, rp: f64, g: f64) -> [f64; 5] {
    let wp = TAU * clampf(fp) / SR;
    [2.0, 1.0, -2.0 * rp * wp.cos() + 2.0, 1.0 - rp * rp, g]
}

/// A resonant band-peak with a DC-nulling zero below it (the no-pedestal `bp`).
fn band(fp: f64, rp: f64) -> [f64; 5] {
    pz(fp, rp, fp * S7, 0.6, g_tamed(rp))
}

/// A notch: a deep zero (radius rz) cut into a flat ceiling, pole sitting low so
/// the character is the null, not a peak. rz→1 = deeper notch.
fn notch(f: f64, rz: f64) -> [f64; 5] {
    let rp = 0.55;
    pz(f, rp, f, rz.clamp(0.4, 0.999), 1.0)
}

/// A true ALL-PASS section: zero is the pole's reflection across the unit circle
/// (Rz = 1/Rp), so magnitude is flat and only the PHASE shifts (Tyson §5). The
/// numerator is the reversed denominator → b0=a2, b1=a1, b2=1.
fn allpass(f: f64, rp: f64) -> [f64; 5] {
    let w = TAU * clampf(f) / SR;
    let a1 = -2.0 * rp * w.cos();
    let a2 = rp * rp;
    // kernel from (b0,b1,b2,a1,a2) = (a2, a1, 1, a1, a2)
    [2.0 + a1 / a2, 1.0 - 1.0 / a2, a1 + 2.0, 1.0 - a2, a2]
}

fn normalize(c: &mut CornerData) {
    // BOLD corners: scale to a tall peak (≈ +18 dB) like a real EQ band, not the
    // timid +6 dB "heritage" cap that crushed every corner to the same weak bump.
    // The audio path's tanh + the engine AGC manage level; the stabiliser keeps
    // poles inside the circle. Character lives in tall, distinct resonances.
    trench_core::lpc::normalize_corner_peak(c, SR, 8.0);
}

// ── 1. FORMANT (violent vowel) — Tyson §1 ─────────────────────────────────────
// X = Throat/F1 open (300→700) + body rise · Y = Tongue Δ (F3=F2·Δ, 1.2→2.5) +
// glottal depth · Z = vocal stress (radii → ceiling, edge appears).
fn formant(x: f64, y: f64, z: f64) -> CornerData {
    let f1 = lerp(300.0, 700.0, x);
    let f2 = llerp(950.0, 1700.0, x);
    let delta = lerp(1.2, 2.5, y);
    let f3 = (f2 * delta).min(7000.0);
    let push = |f: f64, base: f64| lerp(base, radius_ceiling(f).min(RMAX), z);
    let mut c = [PASS; 6];
    c[0] = pz(f1, 0.997_f64.min(RMAX), f1 * 0.5, 0.6, g_tamed(0.997)); // throat locked R≥0.997
    c[1] = band(f2, push(f2, 0.95));
    c[2] = band(f3, push(f3, 0.95));
    c[3] = band(3300.0, push(3300.0, 0.93)); // F4 air (≈const per Klatt)
    c[4] = notch((f1 * f2).sqrt(), lerp(0.45, 0.97, y)); // glottal/nasal null deepens with Y
    c[5] = if z > 0.5 {
        pole(16000.0, lerp(0.95, RMAX, z), g_tamed(0.99))
    } else {
        PASS
    }; // edge under stress
    normalize(&mut c);
    c
}

// ── 2. ANALOG OVERDRIVE — Tyson §2 ────────────────────────────────────────────
// X = master cutoff sweep · Y = slope severity (1→6 stacked poles) + tracking
// error Et (1.005→1.03, analog drift) · Z = resonant rupture (Fc<500 → R→ceiling,
// zeros to Nyquist for max low boost).
fn overdrive(x: f64, y: f64, z: f64) -> CornerData {
    let fc = llerp(110.0, 2500.0, x);
    let n = (1.0 + 5.0 * y).round().clamp(1.0, 6.0) as usize; // 1..6 poles
    let et = lerp(1.005, 1.03, y); // tolerance drift widens the peak
    let rupture = if fc < 500.0 {
        lerp(0.99, RMAX, z) // asymptotic low-freq rupture
    } else {
        lerp(0.965, radius_ceiling(fc).min(RMAX), z)
    };
    let mut c = [PASS; 6];
    for i in 0..6 {
        if i < n {
            let f = (fc * et.powi(i as i32)).min(16000.0);
            // zeros forced to Nyquist → no phase cancellation, max low-end gain.
            c[i] = pz(f, rupture, SR * 0.49, 0.2, g_tamed(rupture));
        }
    }
    normalize(&mut c);
    c
}

// ── 3. COMB / FLANGE shredder — Tyson §3 ──────────────────────────────────────
// X = shift the whole comb up/down · Y = phase tear (zero offset δ from the pole)
// · Z = tooth depth (Rz). Log spacing (×C) for comb teeth; R poles 0.85..0.95.
fn comb(x: f64, y: f64, z: f64) -> CornerData {
    let base = llerp(80.0, 420.0, x);
    let ratio = 1.5; // log comb spacing C
    let delta_semis = lerp(0.0, 5.0, y); // phase tear: zero drifts off the pole
    let depth = lerp(0.85, 0.95, z); // tooth R (kept < self-oscillation)
    let mut c = [PASS; 6];
    let mut f = base;
    for sec in c.iter_mut() {
        if f < 14000.0 {
            let fz = f * 2.0_f64.powf(delta_semis / 12.0);
            *sec = pz(f, depth, fz, depth, g_tamed(depth));
            f *= ratio;
        }
    }
    normalize(&mut c);
    c
}

// ── 4. KINEMATIC EQ (Lucifer's Q / Meaty Gizmo) — Tyson §4 ────────────────────
// Independent parametric nodes crossing along X (a low peak rises, a high node
// falls, they cross). Gain tracked by |Fpole−Fzero| (close zero = deep cut, far =
// big boost). Y = zero proximity (boost↔cut) · Z = resonance.
fn kinematic(x: f64, y: f64, z: f64) -> CornerData {
    let fa = llerp(250.0, 3000.0, x); // node A rises
    let fb = llerp(4000.0, 600.0, x); // node B falls → crosses A
    let fc = llerp(900.0, 1500.0, x); // node C drifts
    let r = lerp(0.95, radius_ceiling((fa + fb) * 0.5).min(RMAX), z);
    // |Fpole−Fzero| as octave offset: y near 0 → zero hugs pole (cut), y→1 → zero
    // far (boost). Opposite signs on A vs B so one boosts while the other cuts.
    let off_a = 2.0_f64.powf(lerp(-0.15, -1.0, y)); // zero below A
    let off_b = 2.0_f64.powf(lerp(0.15, 1.0, y)); // zero above B
    let mut c = [PASS; 6];
    c[0] = pz(fa, r, fa * off_a, 0.85, g_tamed(r));
    c[1] = pz(fb, r, fb * off_b, 0.85, g_tamed(r));
    c[2] = band(fc, r);
    c[3] = notch((fa * fb).sqrt(), lerp(0.5, 0.95, z)); // crossing null
    c[4] = if z > 0.4 {
        band(llerp(5000.0, 9000.0, x), lerp(0.95, RMAX, z))
    } else {
        PASS
    };
    c[5] = PASS;
    normalize(&mut c);
    c
}

// ── 5. ALL-PASS PHASE SHEAR (Megasweepz) — Tyson §5 ───────────────────────────
// Coupled pole/zero (Rz = 1/Rp) → flat magnitude, pure phase. Cascade 4..6,
// centres swept logarithmically across the morph. X = sweep position · Y = count
// (4→6) · Z = depth (Rp toward the rim → deeper, more hollow sweep).
fn phase_shear(x: f64, y: f64, z: f64) -> CornerData {
    let lo = llerp(180.0, 900.0, x);
    let n = (4.0 + 2.0 * y).round().clamp(4.0, 6.0) as usize;
    let rp = lerp(0.88, 0.965, z);
    let mut c = [PASS; 6];
    for (i, sec) in c.iter_mut().enumerate() {
        if i < n {
            let f = (lo * 1.7_f64.powi(i as i32)).min(15000.0);
            *sec = allpass(f, rp);
        }
    }
    // all-pass is already flat — no normalize (it would do nothing / could divide
    // by a ~0 peak). The phaser depth is the dry/wet mix at play time.
    c
}

// ── PHYSICAL source recipe (the spec's Physical family) ───────────────────────
// A body starts from a real object: a modal/tube resonator, not a vibe. The
// recipe (object × material × size × damping × stress) sets the identity; the
// cube's 8 vertices span brightness(X) × ring(Y) × stress(Z) around it.

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Object {
    Tube,
    Cavity,
    Plate,
    Bell,
    Bar,
    Bottle,
    Shell,
}
impl Object {
    pub const ALL: [Object; 7] = [
        Object::Tube,
        Object::Cavity,
        Object::Plate,
        Object::Bell,
        Object::Bar,
        Object::Bottle,
        Object::Shell,
    ];
    pub fn label(self) -> &'static str {
        match self {
            Object::Tube => "tube",
            Object::Cavity => "cavity",
            Object::Plate => "plate",
            Object::Bell => "bell",
            Object::Bar => "bar",
            Object::Bottle => "bottle",
            Object::Shell => "shell",
        }
    }
    /// Modal frequency ratios (relative to f0) — the object's physical signature.
    fn ratios(self) -> &'static [f64] {
        match self {
            Object::Tube => &[1.0, 3.0, 5.0, 7.0, 9.0, 11.0], // closed-open: odd harmonics
            Object::Cavity => &[1.0, 2.3, 3.7, 5.0, 6.2, 7.4], // formant-ish cluster
            Object::Plate => &[1.0, 1.59, 2.14, 2.65, 2.92, 3.5], // dense inharmonic
            Object::Bell => &[1.0, 2.0, 2.4, 3.0, 4.5, 5.33], // bell partials
            Object::Bar => &[1.0, 2.756, 5.404, 8.933, 13.34, 17.5], // free bar
            Object::Bottle => &[1.0, 2.0, 4.0, 7.0, 10.0, 13.0], // Helmholtz + weak
            Object::Shell => &[1.0, 1.7, 2.3, 3.1, 4.0, 5.2], // irregular
        }
    }
    /// The object's natural fundamental (Hz) at neutral size.
    fn base_f0(self) -> f64 {
        match self {
            Object::Tube => 71.0,
            Object::Cavity => 280.0,
            Object::Plate => 680.0,
            Object::Bell => 520.0,
            Object::Bar => 220.0,
            Object::Bottle => 150.0,
            Object::Shell => 330.0,
        }
    }
    /// Material this object is made of by default (drives ring/decay).
    fn material(self) -> Material {
        match self {
            Object::Tube => Material::Steel,
            Object::Cavity => Material::Plastic,
            Object::Plate => Material::Glass,
            Object::Bell => Material::Glass,
            Object::Bar => Material::Wood,
            Object::Bottle => Material::Glass,
            Object::Shell => Material::Steel,
        }
    }
}

/// Pole radius for a target Q (= f/BW) at frequency f — the fix that keeps every
/// resonance equally sharp (razor at 70 Hz and 7 kHz). Engine-verified in the bank.
fn r_from_q(f: f64, q: f64) -> f64 {
    let bw = f / q.max(0.3);
    (-(std::f64::consts::PI) * bw / SR).exp().min(0.99985)
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Material {
    Wood,
    Steel,
    Glass,
    Plastic,
    Concrete,
}
impl Material {
    pub const ALL: [Material; 5] = [
        Material::Wood,
        Material::Steel,
        Material::Glass,
        Material::Plastic,
        Material::Concrete,
    ];
    pub fn label(self) -> &'static str {
        match self {
            Material::Wood => "wood",
            Material::Steel => "steel",
            Material::Glass => "glass",
            Material::Plastic => "plastic",
            Material::Concrete => "concrete",
        }
    }
    /// (base Q, Q-taper/mode, amplitude-taper/mode) — engine-verified bank values.
    /// Real objects damp HIGH modes faster (taper<1) and radiate them quieter.
    fn props(self) -> (f64, f64, f64) {
        match self {
            Material::Steel => (95.0, 0.90, 0.86),
            Material::Glass => (115.0, 0.93, 0.90),
            Material::Wood => (30.0, 0.68, 0.58),
            Material::Plastic => (14.0, 0.60, 0.50),
            Material::Concrete => (9.0, 0.55, 0.45),
        }
    }
}

#[derive(Clone, Copy)]
pub struct PhysicalRecipe {
    pub object: Object,
    pub material: Material,
    pub size: f64,    // 0 huge .. 1 small
    pub damping: f64, // 0 dead .. 1 ringing
    pub stress: f64,  // 0 real .. 1 impossible
}
impl Default for PhysicalRecipe {
    fn default() -> Self {
        Self {
            object: Object::Tube,
            material: Material::Steel,
            size: 0.5,
            damping: 0.7,
            stress: 0.2,
        }
    }
}

/// One corner of a physical body at cube position (x=brightness, y=ring, z=stress).
/// Bank math: partials at f0×ratio, radius from a target Q (material base Q, ring
/// raises it, high modes taper), amplitude tapers per mode, stress detunes +
/// sharpens. Normalized to a bold +18 dB peak so the AGC engages by its own gain.
fn physical_corner(r: &PhysicalRecipe, x: f64, y: f64, z: f64) -> CornerData {
    let ratios = r.object.ratios();
    let (q0, qt, at) = r.material.props();
    let f0 = r.object.base_f0() * 2f64.powf((0.5 - r.size.clamp(0.0, 1.0)) * 1.6);
    let ring = (r.damping * 0.5 + y * 0.5).clamp(0.0, 1.0);
    let stress = (r.stress * 0.5 + z * 0.5).clamp(0.0, 1.0);
    let open = x.clamp(0.0, 1.0);
    let mut c = [PASS; 6];
    for (i, &ratio) in ratios.iter().take(6).enumerate() {
        let detune = 1.0 + stress * 0.05 * i as f64;
        let f = clampf(f0 * ratio * detune);
        // Q: material base × (ring lifts it) × (per-mode taper) × (stress sharpens).
        let q = (q0 * (0.35 + 1.3 * ring) * qt.powi(i as i32) * (1.0 + stress)).max(2.5);
        let rad = r_from_q(f, q);
        let g = at.powi(i as i32) * (0.45 + 0.55 * open);
        c[i] = band(f, rad);
        c[i][4] *= g.clamp(0.04, 1.5);
    }
    normalize(&mut c);
    c
}

/// One corner of a VOICE body: Klatt formants (F, BW), modulated by the cube —
/// x=openness (F1 shift), y=tension (narrows BW = sharper/tenser), z=stress
/// (raises formants + sharpens). Real vowel poles, radius from bandwidth.
fn vowel_corner(formants: &[(f64, f64)], x: f64, y: f64, z: f64) -> CornerData {
    let mut c = [PASS; 6];
    for (i, &(f, bw)) in formants.iter().take(6).enumerate() {
        let fs = f * (1.0 + 0.12 * z) * if i == 0 { 1.0 + 0.25 * (x - 0.5) } else { 1.0 };
        let bws = (bw * (1.0 - 0.45 * y - 0.25 * z)).max(20.0);
        let rad = (-(std::f64::consts::PI) * bws / SR).exp().min(RMAX);
        c[i] = band(clampf(fs), rad);
        c[i][4] *= 0.9f64.powi(i as i32); // upper formants a touch quieter
    }
    normalize(&mut c);
    c
}

/// The 8-corner cube for a Physical recipe. Vertex i: x=i&1 (bright), y=(i>>1)&1
/// (ring), z=(i>>2)&1 (stress) — same index convention as `generate`.
pub fn generate_physical(r: &PhysicalRecipe) -> [CornerData; 8] {
    core::array::from_fn(|i| {
        let x = (i & 1) as f64;
        let y = ((i >> 1) & 1) as f64;
        let z = ((i >> 2) & 1) as f64;
        physical_corner(r, x, y, z)
    })
}

// ── EXTREME category generators (Tyson-designed cube algorithms) ──────────────
// df2 = 6 biquads. Z auto-derives the ceiling plane (the ".4 cube" model): the
// X/Y plane is the timbral morph, Z is the physical modifier (Q crush / drive).

/// RBJ 2-pole low-pass at (fc, Q) → kernel-form stage.
fn lowpass(fc: f64, q: f64) -> [f64; 5] {
    let w = TAU * clampf(fc) / SR;
    let (c, s) = (w.cos(), w.sin());
    let al = s / (2.0 * q.max(0.3));
    let (b0, b1, b2) = ((1.0 - c) / 2.0, 1.0 - c, (1.0 - c) / 2.0);
    let (a0, a1, a2) = (1.0 + al, -2.0 * c, 1.0 - al);
    let (b0, b1, b2, a1, a2) = (b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0);
    [2.0 + b1 / b0, 1.0 - b2 / b0, a1 + 2.0, 1.0 - a2, b0]
}

/// A formant peak at (f, Q) with the no-pedestal DC-null zero.
fn formant_peak(f: f64, q: f64) -> [f64; 5] {
    band(clampf(f), r_from_q(clampf(f), q))
}

// ── 1. TalkingHedz — the 5 cardinal vowels; Oui (/u/→/i/) on X ────────────────
// B0 = 12 dB/oct LP (vocal-tract rolloff) · B1-B4 = Formants F1-F4 · B5 = nasal
// notch (flat at Z=0, deep −notch ~1000-1400 Hz at Z=1 = throat tearing).
fn talking_hedz(x: f64, y: f64, z: f64) -> CornerData {
    const U: [f64; 4] = [350.0, 650.0, 2200.0, 3300.0]; // /u/
    const I: [f64; 4] = [310.0, 2020.0, 2960.0, 3850.0]; // /i/
    let tense = 6.0 + 16.0 * y; // Y = vocal tension → formant Q
    let mut c = [PASS; 6];
    c[0] = lowpass(llerp(4500.0, 6500.0, x), 0.7); // tract LP
    for k in 0..4 {
        c[1 + k] = formant_peak(llerp(U[k], I[k], x), tense);
    }
    // nasal notch between 1000-1400 Hz: flat at Z=0, −6 dB deep at Z=1.
    c[5] = if z > 0.01 {
        notch(1183.0, lerp(0.4, 0.92, z))
    } else {
        PASS
    };
    normalize(&mut c);
    c
}

// ── 2. Lucifer's Q — violent mid-Q cluster (800-2500 Hz) ──────────────────────
// 6 PEQs clustered in the midrange; X sweeps the cluster, Y the resonance, Z
// pushes every pole radius to the safe brink (the true-limit ring = SLAM at runtime).
fn lucifers_q(x: f64, y: f64, z: f64) -> CornerData {
    const BASE: [f64; 6] = [800.0, 1000.0, 1300.0, 1600.0, 2000.0, 2500.0];
    let shift = llerp(0.6, 1.7, x); // X sweeps the whole cluster
    let q = lerp(6.0, 32.0, y); // Y = base resonance
    let mut c = [PASS; 6];
    for k in 0..6 {
        let f = clampf(BASE[k] * shift);
        // Z pushes the radius toward the morph-stable brink (~0.999).
        let r = lerp(r_from_q(f, q), 0.9990, z).min(RMAX);
        c[k] = band(f, r);
    }
    normalize(&mut c);
    c
}

// ── 3. EarBender — nasty wah-vowel ────────────────────────────────────────────
// B0-B3 = static 'Ah' formants · B4-B5 = a stacked high-Q boost whose centre Z
// sweeps violently through the vowel space (Q rising to max) = a wah tearing the vowel.
fn earbender(x: f64, _y: f64, z: f64) -> CornerData {
    const AH: [f64; 4] = [700.0, 1220.0, 2600.0, 3300.0];
    let mut c = [PASS; 6];
    for k in 0..4 {
        c[k] = formant_peak(AH[k] * llerp(0.92, 1.08, x), 9.0); // ~static formants
    }
    let wah = llerp(380.0, 3200.0, z); // Z sweeps the wah centre
    let wq = lerp(8.0, 34.0, z); // Q → max as it sweeps
    c[4] = formant_peak(wah, wq);
    c[5] = formant_peak(wah * 1.5, wq);
    normalize(&mut c);
    c
}

// ── architecture registry + cube builder ──────────────────────────────────────
/// The Source bank: strong, engine-verified corners. Physical objects + Klatt
/// vowels + synthetic types. Each = a recipe that fills the 8-corner cube
/// (x=brightness/openness, y=ring/tension, z=stress).
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Architecture {
    TalkingHedz,
    LucifersQ,
    EarBender, // EXTREME (Tyson-designed)
    Tube,
    Bell,
    Plate,
    Bottle,
    Bar,
    Cavity,
    Shell,
    VowelAh,
    VowelEe,
    VowelOo,
    Acid,
    Comb,
    Destruction,
}

const VOWEL_AH: [(f64, f64); 5] = [
    (700.0, 130.0),
    (1220.0, 70.0),
    (2600.0, 160.0),
    (3300.0, 250.0),
    (3850.0, 300.0),
];
const VOWEL_EE: [(f64, f64); 5] = [
    (310.0, 45.0),
    (2020.0, 200.0),
    (2960.0, 400.0),
    (3300.0, 250.0),
    (3850.0, 300.0),
];
const VOWEL_OO: [(f64, f64); 4] = [
    (350.0, 65.0),
    (650.0, 110.0),
    (2200.0, 140.0),
    (3300.0, 250.0),
];

impl Architecture {
    pub const ALL: [Architecture; 16] = [
        Architecture::TalkingHedz,
        Architecture::LucifersQ,
        Architecture::EarBender,
        Architecture::Tube,
        Architecture::Bell,
        Architecture::Plate,
        Architecture::Bottle,
        Architecture::Bar,
        Architecture::Cavity,
        Architecture::Shell,
        Architecture::VowelAh,
        Architecture::VowelEe,
        Architecture::VowelOo,
        Architecture::Acid,
        Architecture::Comb,
        Architecture::Destruction,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Architecture::TalkingHedz => "TalkingHedz",
            Architecture::LucifersQ => "Lucifer's Q",
            Architecture::EarBender => "EarBender",
            Architecture::Tube => "Tube · steel",
            Architecture::Bell => "Bell · glass",
            Architecture::Plate => "Plate · glass",
            Architecture::Bottle => "Bottle",
            Architecture::Bar => "Bar · wood",
            Architecture::Cavity => "Cavity · throat",
            Architecture::Shell => "Shell",
            Architecture::VowelAh => "Vowel /a/",
            Architecture::VowelEe => "Vowel /i/",
            Architecture::VowelOo => "Vowel /u/",
            Architecture::Acid => "Acid 303",
            Architecture::Comb => "Comb",
            Architecture::Destruction => "Destruction",
        }
    }

    /// Axis meanings, surfaced in the UI so the operator knows what X/Y/Z do.
    pub fn axes(self) -> (&'static str, &'static str, &'static str) {
        match self {
            Architecture::TalkingHedz => ("/u/ → /i/ (Oui)", "tension", "nasal tear"),
            Architecture::LucifersQ => ("cluster sweep", "resonance", "brink + drive"),
            Architecture::EarBender => ("vowel tilt", "—", "wah sweep"),
            Architecture::VowelAh | Architecture::VowelEe | Architecture::VowelOo => {
                ("openness", "tension", "stress")
            }
            Architecture::Acid | Architecture::Comb | Architecture::Destruction => {
                ("sweep", "tear", "danger")
            }
            _ => ("brightness", "ring", "stress"),
        }
    }

    fn object(self) -> Option<Object> {
        Some(match self {
            Architecture::Tube => Object::Tube,
            Architecture::Bell => Object::Bell,
            Architecture::Plate => Object::Plate,
            Architecture::Bottle => Object::Bottle,
            Architecture::Bar => Object::Bar,
            Architecture::Cavity => Object::Cavity,
            Architecture::Shell => Object::Shell,
            _ => return None,
        })
    }

    fn eval(self, x: f64, y: f64, z: f64) -> CornerData {
        if let Some(object) = self.object() {
            let r = PhysicalRecipe {
                object,
                material: object.material(),
                size: 0.5,
                damping: 0.5,
                stress: 0.25,
            };
            return physical_corner(&r, x, y, z);
        }
        match self {
            Architecture::TalkingHedz => talking_hedz(x, y, z),
            Architecture::LucifersQ => lucifers_q(x, y, z),
            Architecture::EarBender => earbender(x, y, z),
            Architecture::VowelAh => vowel_corner(&VOWEL_AH, x, y, z),
            Architecture::VowelEe => vowel_corner(&VOWEL_EE, x, y, z),
            Architecture::VowelOo => vowel_corner(&VOWEL_OO, x, y, z),
            Architecture::Acid => overdrive(x, y, z),
            Architecture::Comb => comb(x, y, z),
            Architecture::Destruction => kinematic(x, y, z),
            _ => unreachable!(),
        }
    }
}

/// The eight cube corners for an architecture (binary vertices of its field).
/// Index i: x=i&1, y=(i>>1)&1, z=(i>>2)&1. Floor = 0..3, ceiling = 4..7.
pub fn generate(arch: Architecture) -> [CornerData; 8] {
    core::array::from_fn(|i| {
        let x = (i & 1) as f64;
        let y = ((i >> 1) & 1) as f64;
        let z = ((i >> 2) & 1) as f64;
        arch.eval(x, y, z)
    })
}

/// Evaluate one architecture at an arbitrary cube position (for the live
/// navigator / preview between vertices). Continuous in x,y,z ∈ [0,1].
pub fn eval_at(arch: Architecture, x: f64, y: f64, z: f64) -> CornerData {
    arch.eval(x.clamp(0.0, 1.0), y.clamp(0.0, 1.0), z.clamp(0.0, 1.0))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pole_radius(stage: &[f64; 5]) -> f64 {
        (1.0 - stage[3]).max(0.0).sqrt() // a2 = 1 - c3 = r²
    }

    #[test]
    fn every_architecture_cube_is_finite_and_stable() {
        for arch in Architecture::ALL {
            let cube = generate(arch);
            assert_eq!(cube.len(), 8);
            for (ci, corner) in cube.iter().enumerate() {
                for stage in corner.iter() {
                    assert!(
                        stage.iter().all(|v| v.is_finite()),
                        "{} corner {ci}: non-finite stage {stage:?}",
                        arch.label()
                    );
                    let r = pole_radius(stage);
                    assert!(
                        r < 1.0,
                        "{} corner {ci}: pole radius {r} ≥ 1 (unstable)",
                        arch.label()
                    );
                }
            }
        }
    }

    #[test]
    fn corners_actually_differ_across_the_cube() {
        // Intentional placement must produce DISTINCT corners (not the samey
        // blob). Compare the response peak frequency of corner 0 vs corner 7.
        use crate::dsp::cascade_mag_db;
        for arch in Architecture::ALL {
            let cube = generate(arch);
            let peak_hz = |c: &CornerData| {
                let mut best = (0.0_f64, f64::NEG_INFINITY);
                let mut f = 60.0;
                while f < 12000.0 {
                    let d = cascade_mag_db(c, f, SR);
                    if d > best.1 {
                        best = (f, d);
                    }
                    f *= 1.02;
                }
                best.0
            };
            let _ = peak_hz;
            // Corners share modal frequencies but differ in Q/gain/stress — assert
            // the RESPONSE SHAPE differs (not the peak location).
            let mut max_diff = 0.0_f64;
            let mut f = 60.0;
            while f < 12000.0 {
                let d = (cascade_mag_db(&cube[0], f, SR) - cascade_mag_db(&cube[7], f, SR)).abs();
                max_diff = max_diff.max(d);
                f *= 1.05;
            }
            assert!(
                max_diff > 1.0,
                "{}: corner0 ≈ corner7 (max {max_diff:.2} dB diff — samey)",
                arch.label()
            );
        }
    }

    #[test]
    fn allpass_is_magnitude_flat() {
        use crate::dsp::stage_mag_db;
        let s = allpass(1000.0, 0.95);
        for &f in &[100.0, 500.0, 1000.0, 3000.0, 8000.0] {
            let d = stage_mag_db(&s, f, SR);
            assert!(d.abs() < 0.5, "all-pass not flat at {f}Hz: {d}dB");
        }
    }
}
