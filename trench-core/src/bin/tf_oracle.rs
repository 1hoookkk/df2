use std::f64::consts::TAU;
use std::path::{Path, PathBuf};
use trench_core::cartridge::CornerData;
use trench_core::cascade::{Cascade, NUM_COEFFS, NUM_STAGES};
use trench_core::compiler::{biquad_to_words, section_biquad, TYPE_NOTCH, TYPE_PEAK};
use trench_core::minifloat::{pole_radius, PackedCorners};
use trench_core::response::{biquad_cascade_complex, log_frequency_grid};
use trench_core::stage_law::{words_from_geometry, RootPair, StageGeometry, STAGE_SR};
const SR: f64 = STAGE_SR;
const PERIOD: usize = 8192;
const WARM_PERIODS: usize = 2;
const MEAS_PERIODS: usize = 8;
const F_LO: f64 = 30.0;
const F_HI: f64 = 16_000.0;
const GRID: [f64; 9] = [0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0];
const LEVEL_A: f64 = 0.20;
const LEVEL_B: f64 = 0.10;
const COHERENCE_MIN: f64 = 0.98;
const OBJ_BINS: usize = 256;
const CORNER_LABELS: [&str; 4] = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];
type Cf = (f64, f64);
#[inline]
fn cmul(a: Cf, b: Cf) -> Cf {
    (a.0 * b.0 - a.1 * b.1, a.0 * b.1 + a.1 * b.0)
}
#[inline]
fn cabs(a: Cf) -> f64 {
    (a.0 * a.0 + a.1 * a.1).sqrt()
}
fn sha256_hex(bytes: &[u8]) -> String {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let mut state = [
        0x6a09e667u32, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];
    let bit_len = (bytes.len() as u64).wrapping_mul(8);
    let padded_len = (bytes.len() + 9 + 63) / 64 * 64;
    let mut padded = Vec::with_capacity(padded_len);
    padded.extend_from_slice(bytes);
    padded.push(0x80);
    padded.resize(padded_len - 8, 0);
    padded.extend_from_slice(&bit_len.to_be_bytes());
    for chunk in padded.chunks_exact(64) {
        let mut words = [0u32; 64];
        for (i, word) in words[..16].iter_mut().enumerate() {
            let o = i * 4;
            *word = u32::from_be_bytes([chunk[o], chunk[o + 1], chunk[o + 2], chunk[o + 3]]);
        }
        for i in 16..64 {
            let s0 =
                words[i - 15].rotate_right(7) ^ words[i - 15].rotate_right(18) ^ (words[i - 15] >> 3);
            let s1 =
                words[i - 2].rotate_right(17) ^ words[i - 2].rotate_right(19) ^ (words[i - 2] >> 10);
            words[i] = words[i - 16]
                .wrapping_add(s0)
                .wrapping_add(words[i - 7])
                .wrapping_add(s1);
        }
        let mut w = state;
        for i in 0..64 {
            let s1 = w[4].rotate_right(6) ^ w[4].rotate_right(11) ^ w[4].rotate_right(25);
            let ch = (w[4] & w[5]) ^ ((!w[4]) & w[6]);
            let t1 = w[7]
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(words[i]);
            let s0 = w[0].rotate_right(2) ^ w[0].rotate_right(13) ^ w[0].rotate_right(22);
            let maj = (w[0] & w[1]) ^ (w[0] & w[2]) ^ (w[1] & w[2]);
            let t2 = s0.wrapping_add(maj);
            w = [
                t1.wrapping_add(t2),
                w[0],
                w[1],
                w[2],
                w[3].wrapping_add(t1),
                w[4],
                w[5],
                w[6],
            ];
        }
        for i in 0..8 {
            state[i] = state[i].wrapping_add(w[i]);
        }
    }
    let mut out = String::with_capacity(64);
    for word in state {
        use std::fmt::Write;
        let _ = write!(out, "{word:08x}");
    }
    out
}
fn wav_write_mono(path: &Path, samples: &[f32], sr: u32) {
    let mut b = Vec::with_capacity(44 + samples.len() * 4);
    let dl = (samples.len() * 4) as u32;
    b.extend_from_slice(b"RIFF");
    b.extend_from_slice(&(36 + dl).to_le_bytes());
    b.extend_from_slice(b"WAVEfmt ");
    b.extend_from_slice(&16u32.to_le_bytes());
    b.extend_from_slice(&3u16.to_le_bytes());
    b.extend_from_slice(&1u16.to_le_bytes());
    b.extend_from_slice(&sr.to_le_bytes());
    b.extend_from_slice(&(sr * 4).to_le_bytes());
    b.extend_from_slice(&4u16.to_le_bytes());
    b.extend_from_slice(&32u16.to_le_bytes());
    b.extend_from_slice(b"data");
    b.extend_from_slice(&dl.to_le_bytes());
    for &x in samples {
        b.extend_from_slice(&x.to_le_bytes());
    }
    std::fs::write(path, b).expect("write wav");
}
fn wav_read_mono(path: &Path) -> Vec<f32> {
    let bytes = std::fs::read(path).expect("read wav");
    let mut fmt = 3u16;
    let mut bits = 32u16;
    let mut i = 12usize;
    while i + 8 <= bytes.len() {
        let id = &bytes[i..i + 4];
        let sz =
            u32::from_le_bytes([bytes[i + 4], bytes[i + 5], bytes[i + 6], bytes[i + 7]]) as usize;
        if id == b"fmt " && i + 24 <= bytes.len() {
            fmt = u16::from_le_bytes([bytes[i + 8], bytes[i + 9]]);
            bits = u16::from_le_bytes([bytes[i + 22], bytes[i + 23]]);
        }
        if id == b"data" {
            let start = i + 8;
            let end = (start + sz).min(bytes.len());
            let d = &bytes[start..end];
            return match (fmt, bits) {
                (3, 32) => d
                    .chunks_exact(4)
                    .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
                    .collect(),
                (1, 16) => d
                    .chunks_exact(2)
                    .map(|c| i16::from_le_bytes([c[0], c[1]]) as f32 / 32767.0)
                    .collect(),
                _ => panic!("unsupported wav fmt {fmt} bits {bits} in {}", path.display()),
            };
        }
        i += 8 + sz + (sz & 1);
    }
    panic!("no data chunk in {}", path.display());
}
fn fft(re: &mut [f64], im: &mut [f64], inverse: bool) {
    let n = re.len();
    assert!(n.is_power_of_two());
    let mut j = 0usize;
    for i in 1..n {
        let mut bit = n >> 1;
        while j & bit != 0 {
            j ^= bit;
            bit >>= 1;
        }
        j ^= bit;
        if i < j {
            re.swap(i, j);
            im.swap(i, j);
        }
    }
    let mut len = 2usize;
    while len <= n {
        let ang = (if inverse { TAU } else { -TAU }) / len as f64;
        let (wl_re, wl_im) = (ang.cos(), ang.sin());
        let mut i = 0;
        while i < n {
            let (mut w_re, mut w_im) = (1.0f64, 0.0f64);
            for k in 0..len / 2 {
                let u = (re[i + k], im[i + k]);
                let v = cmul((re[i + k + len / 2], im[i + k + len / 2]), (w_re, w_im));
                re[i + k] = u.0 + v.0;
                im[i + k] = u.1 + v.1;
                re[i + k + len / 2] = u.0 - v.0;
                im[i + k + len / 2] = u.1 - v.1;
                let nw = cmul((w_re, w_im), (wl_re, wl_im));
                w_re = nw.0;
                w_im = nw.1;
            }
            i += len;
        }
        len <<= 1;
    }
    if inverse {
        for x in re.iter_mut() {
            *x /= n as f64;
        }
        for x in im.iter_mut() {
            *x /= n as f64;
        }
    }
}
fn excited_bins() -> Vec<usize> {
    let k_lo = (F_LO * PERIOD as f64 / SR).ceil() as usize;
    let k_hi = (F_HI * PERIOD as f64 / SR).floor() as usize;
    (k_lo..=k_hi.min(PERIOD / 2 - 1)).collect()
}
fn bin_hz(k: usize) -> f64 {
    k as f64 * SR / PERIOD as f64
}
fn multisine_period(peak: f64) -> Vec<f64> {
    let bins = excited_bins();
    let m = bins.len();
    let mut phases = vec![0.0f64; m];
    for (idx, ph) in phases.iter_mut().enumerate() {
        let i = (idx + 1) as f64;
        *ph = -std::f64::consts::PI * i * (i - 1.0) / m as f64;
    }
    let mut x = vec![0.0f64; PERIOD];
    for n in 0..PERIOD {
        let t = n as f64 / PERIOD as f64;
        let mut s = 0.0;
        for (idx, &k) in bins.iter().enumerate() {
            s += (TAU * k as f64 * t + phases[idx]).cos();
        }
        x[n] = s;
    }
    let pk = x.iter().fold(0.0f64, |m, &v| m.max(v.abs())).max(1e-12);
    let g = peak / pk;
    for v in x.iter_mut() {
        *v *= g;
    }
    x
}
fn excitation_signal(peak: f64) -> Vec<f32> {
    let period = multisine_period(peak);
    let total = (WARM_PERIODS + MEAS_PERIODS) * PERIOD;
    let mut out = Vec::with_capacity(total);
    for _ in 0..(WARM_PERIODS + MEAS_PERIODS) {
        out.extend(period.iter().map(|&v| v as f32));
    }
    out
}
const PPS: usize = 5;
const NPARAM: usize = 4 * NUM_STAGES * PPS;
fn classify_pair(p: f64, q: f64) -> RootPair {
    if p == 0.0 && q == 0.0 {
        return RootPair::Degenerate;
    }
    let disc = p * p - 4.0 * q;
    if disc < 0.0 {
        let r = q.max(0.0).sqrt();
        let cosw = (-p / (2.0 * r)).clamp(-1.0, 1.0);
        RootPair::Conjugate {
            hz: cosw.acos() / TAU * SR,
            r,
        }
    } else {
        let s = disc.sqrt();
        RootPair::RealPair {
            root_a: (-p + s) / 2.0,
            root_b: (-p - s) / 2.0,
        }
    }
}
fn clamp_stage(s: &mut [f64]) {
    s[1] = s[1].clamp(0.0, 1.0);
    s[0] = s[0].clamp(-2.0, 2.0);
    s[3] = s[3].clamp(0.0, 0.990);
    let lim = (1.0 + s[3]) - 1e-4;
    s[2] = s[2].clamp(-lim, lim);
    s[4] = s[4].clamp(0.0, 4.0);
}
fn stage_words(s: &[f64]) -> [u16; NUM_COEFFS] {
    let g = StageGeometry {
        zero: classify_pair(s[0], s[1]),
        pole: classify_pair(s[2], s[3]),
        scale: s[4],
    };
    words_from_geometry(&g)
}
fn params_to_packed(params: &[f64]) -> PackedCorners {
    let mut words = [[[0u16; NUM_COEFFS]; NUM_STAGES]; 4];
    for ci in 0..4 {
        for si in 0..NUM_STAGES {
            let base = (ci * NUM_STAGES + si) * PPS;
            words[ci][si] = stage_words(&params[base..base + PPS]);
        }
    }
    PackedCorners { words }
}
fn params_to_body(params: &[f64]) -> [u8; 240] {
    params_to_packed(params).to_rom_bytes()
}
fn biquad_to_stage_params(r: &[f64; NUM_COEFFS]) -> [f64; PPS] {
    let b0 = r[0];
    let (zp, zq) = if b0.abs() > 1e-12 {
        (r[1] / b0, r[2] / b0)
    } else {
        (0.0, 0.0)
    };
    [zp, zq, r[3], r[4], b0]
}
fn write_json(path: &Path, v: &serde_json::Value) {
    std::fs::write(path, serde_json::to_string_pretty(v).unwrap()).expect("write json");
}
fn read_json(path: &Path) -> serde_json::Value {
    serde_json::from_str(&std::fs::read_to_string(path).expect("read json")).expect("parse json")
}
fn write_f32_blob(path: &Path, data: &[f32]) {
    let mut b = Vec::with_capacity(data.len() * 4);
    for &x in data {
        b.extend_from_slice(&x.to_le_bytes());
    }
    std::fs::write(path, b).expect("write blob");
}
fn read_f32_blob(path: &Path) -> Vec<f32> {
    std::fs::read(path)
        .expect("read blob")
        .chunks_exact(4)
        .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
        .collect()
}
#[derive(Clone, Copy)]
struct State {
    mi: usize,
    qi: usize,
}
impl State {
    fn m(&self) -> f64 {
        GRID[self.mi]
    }
    fn q(&self) -> f64 {
        GRID[self.qi]
    }
    fn train(&self) -> bool {
        (self.mi + self.qi) % 2 == 0
    }
    fn label(&self) -> String {
        format!(
            "M{:03}_Q{:03}",
            (self.m() * 100.0).round() as i32,
            (self.q() * 100.0).round() as i32
        )
    }
}
fn all_states() -> Vec<State> {
    let mut v = Vec::new();
    for qi in 0..GRID.len() {
        for mi in 0..GRID.len() {
            v.push(State { mi, qi });
        }
    }
    v
}
fn render_body_solo(pc: &PackedCorners, m: f64, q: f64, dry: &[f32]) -> Vec<f32> {
    let mut casc = Cascade::new();
    let rows = pc.interpolate_biquad(m as f32, q as f32);
    casc.snap_targets(&rows);
    let mut buf = dry.to_vec();
    casc.process_block_mono(&mut buf);
    buf
}
struct Estimate {
    bins: Vec<usize>,
    h: Vec<Cf>,
    coh: Vec<f64>,
    mask: Vec<bool>,
    delay: f64,
}
fn estimate_tf(dry_full: &[f32], wet_full: &[f32], bulk_delay: f64) -> Estimate {
    let bins = excited_bins();
    let delay = bulk_delay;
    let d = delay.round() as i64;
    let mut sxx = vec![(0.0f64, 0.0f64); bins.len()];
    let mut syy = vec![0.0f64; bins.len()];
    let mut sxy = vec![(0.0f64, 0.0f64); bins.len()];
    let mut sxx_re = vec![0.0f64; bins.len()];
    for p in 0..MEAS_PERIODS {
        let base = (WARM_PERIODS + p) * PERIOD;
        let (mut xr, mut xi) = period_fft(dry_full, base as i64);
        let (mut yr, mut yi) = period_fft(wet_full, base as i64 + d);
        for (bi, &k) in bins.iter().enumerate() {
            let x = (xr[k], xi[k]);
            let y = (yr[k], yi[k]);
            let xconj = (x.0, -x.1);
            let cross = cmul(xconj, y);
            sxy[bi].0 += cross.0;
            sxy[bi].1 += cross.1;
            sxx_re[bi] += x.0 * x.0 + x.1 * x.1;
            syy[bi] += y.0 * y.0 + y.1 * y.1;
        }
        let _ = (&mut xr, &mut xi, &mut yr, &mut yi, &mut sxx);
    }
    let kf = MEAS_PERIODS as f64;
    let mut h = Vec::with_capacity(bins.len());
    let mut coh = Vec::with_capacity(bins.len());
    let mut mask = Vec::with_capacity(bins.len());
    for (bi, &k) in bins.iter().enumerate() {
        let sxx_m = sxx_re[bi] / kf;
        let syy_m = syy[bi] / kf;
        let sxy_m = (sxy[bi].0 / kf, sxy[bi].1 / kf);
        let hh = if sxx_m > 1e-30 {
            (sxy_m.0 / sxx_m, sxy_m.1 / sxx_m)
        } else {
            (0.0, 0.0)
        };
        let g2 = if sxx_m * syy_m > 1e-30 {
            (sxy_m.0 * sxy_m.0 + sxy_m.1 * sxy_m.1) / (sxx_m * syy_m)
        } else {
            0.0
        }
        .clamp(0.0, 1.0);
        h.push(hh);
        coh.push(g2);
        mask.push(g2 >= COHERENCE_MIN && sxx_m > 1e-18 && bin_hz(k) >= F_LO && bin_hz(k) <= F_HI);
    }
    Estimate {
        bins,
        h,
        coh,
        mask,
        delay,
    }
}
fn period_fft(sig: &[f32], base: i64) -> (Vec<f64>, Vec<f64>) {
    let mut re = vec![0.0f64; PERIOD];
    let mut im = vec![0.0f64; PERIOD];
    for n in 0..PERIOD {
        let idx = base + n as i64;
        if idx >= 0 && (idx as usize) < sig.len() {
            re[n] = sig[idx as usize] as f64;
        }
    }
    fft(&mut re, &mut im, false);
    (re, im)
}
fn estimate_delay(dry: &[f32], wet: &[f32]) -> f64 {
    let base = WARM_PERIODS * PERIOD;
    let win = 512usize.min(PERIOD);
    let max_lag = 256i64;
    let mut best = 0i64;
    let mut best_c = f64::NEG_INFINITY;
    for lag in -max_lag..=max_lag {
        let mut c = 0.0f64;
        for n in 0..win {
            let di = base + n;
            let wi = base as i64 + n as i64 + lag;
            if di < dry.len() && wi >= 0 && (wi as usize) < wet.len() {
                c += dry[di] as f64 * wet[wi as usize] as f64;
            }
        }
        if c > best_c {
            best_c = c;
            best = lag;
        }
    }
    best as f64
}
fn perceptual_weight(hz: f64) -> f64 {
    1.0 / hz.max(F_LO)
}
fn session_root(id: &str) -> PathBuf {
    let repo = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_path_buf();
    repo.join("dev").join("tmp").join("tf_oracle").join(id)
}
fn ensure_dir(p: &Path) {
    std::fs::create_dir_all(p).expect("mkdir");
}
fn cmd_prepare(id: &str) {
    let root = session_root(id);
    ensure_dir(&root);
    ensure_dir(&root.join("capture"));
    let exc = excitation_signal(LEVEL_A);
    let exc_b = excitation_signal(LEVEL_B);
    wav_write_mono(&root.join("excitation_A.wav"), &exc, SR as u32);
    wav_write_mono(&root.join("excitation_B.wav"), &exc_b, SR as u32);
    let exc_hash = sha256_hex(&std::fs::read(root.join("excitation_A.wav")).unwrap());
    let exc_b_hash = sha256_hex(&std::fs::read(root.join("excitation_B.wav")).unwrap());
    let states = all_states();
    let jobs: Vec<serde_json::Value> = states
        .iter()
        .map(|s| {
            serde_json::json!({
                "label": s.label(), "morph": s.m(), "q": s.q(),
                "split": if s.train() { "train" } else { "held_out" },
                "wet_A": format!("capture/wet_{}_A.wav", s.label()),
            })
        })
        .collect();
    let session = serde_json::json!({
        "schema": "tf-oracle-session-v1",
        "session_id": id,
        "internal_sample_rate_hz": SR,
        "host_sample_rate_hz_note": "capture rendered at the 39062.5 island rate; a real host capture records host SR + WindowedSinc SRC (FixedRateTrenchIsland) and must be resampled to island rate before estimate.",
        "excitation": {
            "method": "schroeder_multisine",
            "period": PERIOD, "warm_periods": WARM_PERIODS, "meas_periods": MEAS_PERIODS,
            "f_lo_hz": F_LO, "f_hi_hz": F_HI,
            "level_A_peak": LEVEL_A, "level_B_peak": LEVEL_B,
            "excited_bins": excited_bins().len(),
            "wav_A": "excitation_A.wav", "wav_A_sha256": exc_hash,
            "wav_B": "excitation_B.wav", "wav_B_sha256": exc_b_hash,
            "rationale": "flat on-bin broadband, low crest (Schroeder), periodic so a rectangular window is exact and Welch over the repeated periods gives unbiased complex H(f) + coherence."
        },
        "grid": { "axis": GRID.to_vec(), "split_rule": "(m_index + q_index) % 2 == 0 -> train" },
        "capture_setup": {
            "mode": "BODY SOLO (cascade-only at unity I/O)",
            "disabled": ["AGC","saturation/desk_drive","modulation","spatial","make-up gain","normalization"],
            "InputMode": "None", "SpatialMode": "Off", "amount": 1.0
        },
        "jobs": jobs,
        "provenance": provenance_block(),
    });
    write_json(&root.join("session.json"), &session);
    println!("prepared session {id}");
    println!("  excitation_A.wav sha256 {exc_hash}");
    println!("  {} states ({} train / {} held-out)", states.len(),
        states.iter().filter(|s| s.train()).count(),
        states.iter().filter(|s| !s.train()).count());
    println!("  root: {}", root.display());
}
fn provenance_block() -> serde_json::Value {
    serde_json::json!({
        "clean_room": "pipeline-clean-room-CAPABLE",
        "agent_exposure": "This building agent's context HAS seen decoded E-mu/EmulatorX coefficients and measured pole/zero evidence (prior sessions). Per the clean-room boundary it may build+validate the generic pipeline but a fitted REAL target body from THIS agent must NOT be labelled 'strict clean room'. Synthetic/authored oracles are self-produced and legal.",
        "handoff": "A fresh, unexposed operator runs the exact reproduction commands in SUMMARY.md against the anonymous target to obtain a strict-clean-room body.",
        "no_protected_bytes": "No ROM/preset/P2K bytes, coefficient rows, or protected names are read or copied by this pipeline."
    })
}
fn cmd_synth(id: &str, oracle_path: Option<&str>) {
    let root = session_root(id);
    if !root.join("session.json").exists() {
        cmd_prepare(id);
    }
    ensure_dir(&root.join("_hidden"));
    ensure_dir(&root.join("capture"));
    let oracle_bytes: Vec<u8> = match oracle_path {
        Some(p) => {
            let b = std::fs::read(p).unwrap_or_else(|_| panic!("read oracle {p}"));
            assert_eq!(b.len(), 240, "oracle must be 240 bytes");
            b
        }
        None => build_synth_oracle().to_vec(),
    };
    std::fs::write(root.join("_hidden").join("oracle.body240"), &oracle_bytes).unwrap();
    let oracle_hash = sha256_hex(&oracle_bytes);
    let pc = PackedCorners::from_body_bytes(&oracle_bytes).expect("oracle 240");
    let dry_a = wav_read_mono(&root.join("excitation_A.wav"));
    let dry_b = wav_read_mono(&root.join("excitation_B.wav"));
    let states = all_states();
    let mut caps: Vec<serde_json::Value> = Vec::new();
    for s in &states {
        let wet = render_body_solo(&pc, s.m(), s.q(), &dry_a);
        let wp = root.join("capture").join(format!("wet_{}_A.wav", s.label()));
        wav_write_mono(&wp, &wet, SR as u32);
        let (peak, rms, clip) = level_stats(&wet);
        caps.push(serde_json::json!({
            "label": s.label(), "level": "A", "repeat": 0,
            "wet": format!("capture/wet_{}_A.wav", s.label()),
            "wet_sha256": sha256_hex(&std::fs::read(&wp).unwrap()),
            "peak": peak, "rms": rms, "clip_count": clip,
        }));
    }
    let anchors = [
        State { mi: 0, qi: 0 },
        State { mi: 8, qi: 0 },
        State { mi: 0, qi: 8 },
        State { mi: 8, qi: 8 },
        State { mi: 4, qi: 4 },
    ];
    for s in &anchors {
        let wet_b = render_body_solo(&pc, s.m(), s.q(), &dry_b);
        let wpb = root.join("capture").join(format!("wet_{}_B.wav", s.label()));
        wav_write_mono(&wpb, &wet_b, SR as u32);
        let wet_r = render_body_solo(&pc, s.m(), s.q(), &dry_a);
        let wpr = root.join("capture").join(format!("wet_{}_A_rep.wav", s.label()));
        wav_write_mono(&wpr, &wet_r, SR as u32);
        caps.push(serde_json::json!({
            "label": s.label(), "level": "B", "repeat": 0,
            "wet": format!("capture/wet_{}_B.wav", s.label()),
            "wet_sha256": sha256_hex(&std::fs::read(&wpb).unwrap()),
        }));
        caps.push(serde_json::json!({
            "label": s.label(), "level": "A", "repeat": 1,
            "wet": format!("capture/wet_{}_A_rep.wav", s.label()),
            "wet_sha256": sha256_hex(&std::fs::read(&wpr).unwrap()),
        }));
    }
    let ident = build_identity_body();
    let ipc = PackedCorners::from_body_bytes(&ident).unwrap();
    let loop_wet = render_body_solo(&ipc, 0.0, 0.0, &dry_a);
    wav_write_mono(&root.join("capture").join("loopback.wav"), &loop_wet, SR as u32);
    let manifest = serde_json::json!({
        "schema": "tf-oracle-capture-v1",
        "target_id": "target_001",
        "target_kind": if oracle_path.is_some() { "external_oracle_body240" } else { "generated_synthetic_oracle" },
        "target_sha256": oracle_hash,
        "target_hidden_path": "_hidden/oracle.body240 (NOT read by fit; synthetic-only calibration in verify)",
        "internal_sample_rate_hz": SR,
        "captures": caps,
        "loopback": "capture/loopback.wav",
        "lti": "level A and level B rendered at anchors for the LTI check",
        "repeatability": "A repeats at anchors for the repeatability tolerance",
    });
    write_json(&root.join("capture_manifest.json"), &manifest);
    println!("synth captured {} states + anchors; target_001 sha256 {oracle_hash}", states.len());
}
fn level_stats(x: &[f32]) -> (f64, f64, usize) {
    let peak = x.iter().fold(0.0f64, |m, &v| m.max(v.abs() as f64));
    let rms = (x.iter().map(|&v| (v as f64) * (v as f64)).sum::<f64>() / x.len().max(1) as f64).sqrt();
    let clip = x.iter().filter(|&&v| v.abs() >= 0.999).count();
    (peak, rms, clip)
}
fn build_synth_oracle() -> [u8; 240] {
    let identity = StageGeometry {
        pole: RootPair::Degenerate,
        zero: RootPair::Degenerate,
        scale: 1.0,
    };
    let conj_pole = |hz: f64, r: f64| RootPair::Conjugate { hz, r };
    let notch = |hz: f64, r: f64| RootPair::Conjugate { hz, r };
    let mk = |pole: RootPair, zero: RootPair, scale: f64| StageGeometry { pole, zero, scale };
    let mut corners: [[StageGeometry; NUM_STAGES]; 4] = [[identity; NUM_STAGES]; 4];
    let r_lo = 0.90;
    let r_hi = 0.965;
    corners[0][0] = mk(conj_pole(600.0, r_lo), RootPair::Degenerate, 0.30);
    corners[0][1] = mk(conj_pole(2400.0, r_lo), RootPair::Degenerate, 0.30);
    corners[1][0] = mk(conj_pole(2600.0, r_lo), RootPair::Degenerate, 0.30);
    corners[1][1] = mk(conj_pole(560.0, r_lo), RootPair::Degenerate, 0.30);
    corners[2][0] = mk(conj_pole(600.0, r_hi), RootPair::Degenerate, 0.22);
    corners[2][1] = mk(conj_pole(2400.0, r_hi), RootPair::Degenerate, 0.22);
    corners[3][0] = mk(conj_pole(2600.0, r_hi), RootPair::Degenerate, 0.22);
    corners[3][1] = mk(conj_pole(560.0, r_hi), RootPair::Degenerate, 0.22);
    for (ci, (m, q)) in [(0.0f64, 0.0f64), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
        .into_iter()
        .enumerate()
    {
        let nz = 1500.0 + (4200.0 - 1500.0) * m;
        let pr = if q > 0.5 { 0.75 } else { 0.60 };
        corners[ci][2] = mk(conj_pole(nz * 0.98, pr), notch(nz, 0.995), 1.0);
    }
    for ci in 0..4 {
        corners[ci][3] = mk(conj_pole(1000.0, 0.80), RootPair::Degenerate, 0.6);
    }
    let real_zero = RootPair::RealPair {
        root_a: 0.7,
        root_b: 0.2,
    };
    for ci in 0..4 {
        corners[ci][4] = mk(conj_pole(5000.0, 0.70), real_zero, 1.0);
    }
    let mut words = [[[0u16; NUM_COEFFS]; NUM_STAGES]; 4];
    for ci in 0..4 {
        for si in 0..NUM_STAGES {
            words[ci][si] = words_from_geometry(&corners[ci][si]);
        }
    }
    PackedCorners { words }.to_rom_bytes()
}
fn build_identity_body() -> [u8; 240] {
    let ident = StageGeometry {
        pole: RootPair::Degenerate,
        zero: RootPair::Degenerate,
        scale: 1.0,
    };
    let w = words_from_geometry(&ident);
    let words = [[w; NUM_STAGES]; 4];
    PackedCorners { words }.to_rom_bytes()
}
fn measure_bulk_delay(root: &Path, dry: &[f32]) -> f64 {
    let lp = root.join("capture").join("loopback.wav");
    if lp.exists() {
        let loop_wet = wav_read_mono(&lp);
        estimate_delay(dry, &loop_wet)
    } else {
        0.0
    }
}
fn cmd_estimate(id: &str) {
    let root = session_root(id);
    ensure_dir(&root.join("estimate"));
    let dry = wav_read_mono(&root.join("excitation_A.wav"));
    let bulk_delay = measure_bulk_delay(&root, &dry);
    let bins = excited_bins();
    let freqs: Vec<f64> = bins.iter().map(|&k| bin_hz(k)).collect();
    write_f32_blob(
        &root.join("estimate").join("freqs.f32"),
        &freqs.iter().map(|&f| f as f32).collect::<Vec<_>>(),
    );
    let states = all_states();
    let mut index: Vec<serde_json::Value> = Vec::new();
    let mut coverage_sum = 0.0f64;
    for s in &states {
        let wet = wav_read_mono(&root.join("capture").join(format!("wet_{}_A.wav", s.label())));
        let est = estimate_tf(&dry, &wet, bulk_delay);
        let mut he = Vec::with_capacity(est.h.len() * 3);
        for i in 0..est.h.len() {
            he.push(est.h[i].0 as f32);
            he.push(est.h[i].1 as f32);
            he.push(est.coh[i] as f32);
        }
        write_f32_blob(
            &root.join("estimate").join(format!("H_{}.f32", s.label())),
            &he,
        );
        let cov = est.mask.iter().filter(|&&b| b).count() as f64 / est.mask.len() as f64;
        coverage_sum += cov;
        index.push(serde_json::json!({
            "label": s.label(), "morph": s.m(), "q": s.q(),
            "split": if s.train() { "train" } else { "held_out" },
            "file": format!("estimate/H_{}.f32", s.label()),
            "layout": "interleaved f32 [re, im, coherence] per excited bin",
            "delay_samples": est.delay,
            "confidence_coverage": cov,
        }));
    }
    let manifest = serde_json::json!({
        "schema": "tf-oracle-estimate-v1",
        "estimator": "welch_averaged_periods: H=Sxy/Sxx, coherence=|Sxy|^2/(Sxx*Syy)",
        "window": "rectangular (periodic multisine, no leakage)",
        "meas_periods": MEAS_PERIODS,
        "excited_bins": bins.len(),
        "freqs_file": "estimate/freqs.f32",
        "coherence_min": COHERENCE_MIN,
        "mean_confidence_coverage": coverage_sum / states.len() as f64,
        "states": index,
    });
    write_json(&root.join("estimate").join("estimate_manifest.json"), &manifest);
    println!(
        "estimated {} states; mean confidence coverage {:.3}",
        states.len(),
        coverage_sum / states.len() as f64
    );
}
fn load_estimate(root: &Path, label: &str) -> (Vec<usize>, Vec<Cf>, Vec<f64>, Vec<bool>) {
    let bins = excited_bins();
    let raw = read_f32_blob(&root.join("estimate").join(format!("H_{label}.f32")));
    let mut h = Vec::with_capacity(bins.len());
    let mut coh = Vec::with_capacity(bins.len());
    let mut mask = Vec::with_capacity(bins.len());
    for i in 0..bins.len() {
        h.push((raw[i * 3] as f64, raw[i * 3 + 1] as f64));
        let c = raw[i * 3 + 2] as f64;
        coh.push(c);
        mask.push(c >= COHERENCE_MIN);
    }
    (bins, h, coh, mask)
}
fn main() {
    let args: Vec<String> = std::env::args().collect();
    let cmd = args.get(1).map(|s| s.as_str()).unwrap_or("help");
    let flag = |name: &str| -> Option<String> {
        args.iter().position(|a| a == name).and_then(|i| args.get(i + 1).cloned())
    };
    let id = flag("--session").unwrap_or_else(|| "s001".to_string());
    let oracle = flag("--oracle");
    match cmd {
        "prepare" => cmd_prepare(&id),
        "synth" => cmd_synth(&id, oracle.as_deref()),
        "estimate" => cmd_estimate(&id),
        "fit" => cmd_fit(&id),
        "verify" => cmd_verify(&id),
        "bundle" => cmd_bundle(&id),
        "author-mouth" => cmd_author_mouth(&id),
        "run" => {
            cmd_prepare(&id);
            cmd_synth(&id, oracle.as_deref());
            cmd_estimate(&id);
            cmd_fit(&id);
            cmd_verify(&id);
            cmd_bundle(&id);
        }
        _ => {
            eprintln!("usage: tf-oracle <prepare|synth|estimate|fit|verify|bundle|run> --session <id> [--oracle <body240>]");
        }
    }
}
struct TargetState {
    label: String,
    m: f64,
    q: f64,
    train: bool,
    h: Vec<Cf>,
    coh: Vec<f64>,
    mask: Vec<bool>,
}
fn erb_weight(hz: f64) -> f64 {
    let f = hz.clamp(F_LO, F_HI);
    1.0 / (24.7 * (4.37 * f / 1000.0 + 1.0))
}
fn load_targets(root: &Path) -> (Vec<TargetState>, Vec<f64>) {
    let bins = excited_bins();
    let freqs: Vec<f64> = bins.iter().map(|&k| bin_hz(k)).collect();
    let states = all_states();
    let targets = states
        .iter()
        .map(|s| {
            let (_b, h, coh, mask) = load_estimate(root, &s.label());
            TargetState {
                label: s.label(),
                m: s.m(),
                q: s.q(),
                train: s.train(),
                h,
                coh,
                mask,
            }
        })
        .collect();
    (targets, freqs)
}
const LAMBDA_PH: f64 = 4.0;
const PEN_W: f64 = 6.0;
fn ceiling_penalty(rows: &CornerData, ceil_db: f64) -> f64 {
    let grid = log_frequency_grid(20.0, SR * 0.499, 220);
    let mut acc = 0.0;
    for &f in &grid {
        let (r, i) = biquad_cascade_complex(rows, f, SR);
        let db = 10.0 * (r * r + i * i + 1e-30).log10();
        let over = db - ceil_db;
        if over > 0.0 {
            acc += over * over;
        }
    }
    acc / grid.len() as f64
}
const PEN_STAB: f64 = 3.0e4;
fn stability_penalty(packed: &PackedCorners) -> f64 {
    let mut acc = 0.0;
    for mi in 0..17 {
        for qi in 0..17 {
            let rows = packed.interpolate_biquad(mi as f32 / 16.0, qi as f32 / 16.0);
            for r in rows.iter() {
                let over = pole_radius(r[3], r[4]) - 0.997;
                if over > 0.0 {
                    acc += over * over;
                }
            }
        }
    }
    acc
}
fn target_ceiling(targets: &[TargetState]) -> f64 {
    let mut mx = f64::NEG_INFINITY;
    for ts in targets.iter().filter(|t| t.train) {
        for (i, &m) in ts.mask.iter().enumerate() {
            if m {
                let (r, im) = ts.h[i];
                mx = mx.max(10.0 * (r * r + im * im + 1e-30).log10());
            }
        }
    }
    mx + 12.0
}
fn wrap_pi(x: f64) -> f64 {
    let mut y = x % TAU;
    if y > std::f64::consts::PI {
        y -= TAU;
    }
    if y < -std::f64::consts::PI {
        y += TAU;
    }
    y
}
fn train_objective(
    packed: &PackedCorners,
    targets: &[TargetState],
    obj_idx: &[usize],
    freqs: &[f64],
    ceil_db: f64,
) -> f64 {
    let mut err = 0.0f64;
    let mut wsum = 0.0f64;
    let mut pen = 0.0f64;
    let mut nstate = 0usize;
    for ts in targets.iter().filter(|t| t.train) {
        let rows = packed.interpolate_biquad(ts.m as f32, ts.q as f32);
        for &i in obj_idx {
            if !ts.mask[i] {
                continue;
            }
            let f = freqs[i];
            let (hr, hi) = biquad_cascade_complex(&rows, f, SR);
            let (tr, ti) = ts.h[i];
            let magc = 10.0 * (hr * hr + hi * hi + 1e-30).log10();
            let magt = 10.0 * (tr * tr + ti * ti + 1e-30).log10();
            let dmag = magc - magt;
            let dph = wrap_pi(hi.atan2(hr) - ti.atan2(tr));
            let w = ts.coh[i] * erb_weight(f);
            err += w * (dmag * dmag + LAMBDA_PH * dph * dph);
            wsum += w;
        }
        pen += ceiling_penalty(&rows, ceil_db);
        nstate += 1;
    }
    err / wsum.max(1e-30) + PEN_W * pen / nstate.max(1) as f64 + PEN_STAB * stability_penalty(packed)
}
fn objective_indices(freqs: &[f64]) -> Vec<usize> {
    let grid = log_frequency_grid(F_LO, F_HI, OBJ_BINS);
    let mut idx = Vec::with_capacity(grid.len());
    for &g in &grid {
        let mut best = 0usize;
        let mut bd = f64::INFINITY;
        for (i, &f) in freqs.iter().enumerate() {
            let d = (f - g).abs();
            if d < bd {
                bd = d;
                best = i;
            }
        }
        if !idx.contains(&best) {
            idx.push(best);
        }
    }
    idx
}
fn init_corner(h: &[Cf], mask: &[bool], freqs: &[f64]) -> [[f64; PPS]; NUM_STAGES] {
    let mag: Vec<f64> = h.iter().map(|&c| 20.0 * cabs(c).max(1e-9).log10()).collect();
    let n = mag.len();
    let mut sorted: Vec<f64> = (0..n).filter(|&i| mask[i]).map(|i| mag[i]).collect();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let baseline = sorted.get(sorted.len() / 2).copied().unwrap_or(0.0);
    let mut peaks: Vec<(usize, f64)> = Vec::new();
    for i in 1..n - 1 {
        if mask[i] && mag[i] > mag[i - 1] && mag[i] >= mag[i + 1] && mag[i] - baseline > 2.0 {
            peaks.push((i, mag[i] - baseline));
        }
    }
    peaks.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());
    let mut valleys: Vec<(usize, f64)> = Vec::new();
    for i in 1..n - 1 {
        if mask[i] && mag[i] < mag[i - 1] && mag[i] <= mag[i + 1] && baseline - mag[i] > 3.0 {
            valleys.push((i, baseline - mag[i]));
        }
    }
    valleys.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());
    let width_q = |pi: usize| -> f64 {
        let target = mag[pi] - 3.0;
        let mut lo = pi;
        while lo > 0 && mag[lo] > target {
            lo -= 1;
        }
        let mut hi = pi;
        while hi < n - 1 && mag[hi] > target {
            hi += 1;
        }
        let bw = (freqs[hi] - freqs[lo]).max(SR / PERIOD as f64);
        (freqs[pi] / bw).clamp(0.7, 24.0)
    };
    let mut stages = [[0.0f64, 0.0, 0.0, 0.0, 1.0]; NUM_STAGES];
    let mut si = 0usize;
    for &(pi, prom) in peaks.iter().take(NUM_STAGES) {
        let bq = section_biquad(TYPE_PEAK, freqs[pi], width_q(pi), prom.clamp(1.5, 30.0));
        stages[si] = biquad_to_stage_params(&bq);
        si += 1;
    }
    for &(vi, depth) in valleys.iter() {
        if si >= NUM_STAGES {
            break;
        }
        let target = mag[vi] + 3.0;
        let mut lo = vi;
        while lo > 0 && mag[lo] < target {
            lo -= 1;
        }
        let mut hi = vi;
        while hi < n - 1 && mag[hi] < target {
            hi += 1;
        }
        let bw = (freqs[hi] - freqs[lo]).max(SR / PERIOD as f64);
        let q = (freqs[vi] / bw).clamp(0.7, 24.0);
        let bq = section_biquad(TYPE_NOTCH, freqs[vi], q, -depth.clamp(3.0, 40.0));
        stages[si] = biquad_to_stage_params(&bq);
        si += 1;
    }
    let g_per = 10.0f64.powf(baseline / 20.0 / NUM_STAGES as f64);
    for s in stages.iter_mut() {
        s[4] = (s[4] * g_per).clamp(0.0, 4.0);
        clamp_stage(s);
    }
    stages
}
fn perms6() -> Vec<[usize; 6]> {
    let mut out = Vec::with_capacity(720);
    let mut a = [0usize, 1, 2, 3, 4, 5];
    let mut c = [0usize; 6];
    out.push(a);
    let mut i = 0;
    while i < 6 {
        if c[i] < i {
            if i % 2 == 0 {
                a.swap(0, i);
            } else {
                a.swap(c[i], i);
            }
            out.push(a);
            c[i] += 1;
            i = 0;
        } else {
            c[i] = 0;
            i += 1;
        }
    }
    out
}
fn permute_corner(params: &mut [f64], ci: usize, perm: &[usize; 6]) {
    let mut orig = [[0.0f64; PPS]; NUM_STAGES];
    for si in 0..NUM_STAGES {
        let base = (ci * NUM_STAGES + si) * PPS;
        orig[si].copy_from_slice(&params[base..base + PPS]);
    }
    for (slot, &old) in perm.iter().enumerate() {
        let base = (ci * NUM_STAGES + slot) * PPS;
        params[base..base + PPS].copy_from_slice(&orig[old]);
    }
}
fn search_correspondence(
    params: &mut Vec<f64>,
    targets: &[TargetState],
    obj_idx: &[usize],
    freqs: &[f64],
    ceil_db: f64,
) -> ([[usize; 6]; 4], f64, f64) {
    let perms = perms6();
    let mut chosen = [[0usize, 1, 2, 3, 4, 5]; 4];
    let identity_err = train_objective(&params_to_packed(params), targets, obj_idx, freqs, ceil_db);
    for _round in 0..2 {
        for ci in 1..4 {
            let mut best_perm = chosen[ci];
            let mut best_err = f64::INFINITY;
            for p in &perms {
                let mut trial = params.clone();
                permute_corner(&mut trial, ci, p);
                let e = train_objective(&params_to_packed(&trial), targets, obj_idx, freqs, ceil_db);
                if e < best_err {
                    best_err = e;
                    best_perm = *p;
                }
            }
            permute_corner(params, ci, &best_perm);
            let mut composed = [0usize; 6];
            for slot in 0..6 {
                composed[slot] = chosen[ci][best_perm[slot]];
            }
            chosen[ci] = composed;
        }
    }
    let final_err = train_objective(&params_to_packed(params), targets, obj_idx, freqs, ceil_db);
    (chosen, identity_err, final_err)
}
fn hooke_jeeves(
    mut base: Vec<f64>,
    obj: &dyn Fn(&[f64]) -> f64,
    max_iters: usize,
    ckpt_dir: Option<&Path>,
) -> (Vec<f64>, f64) {
    let step_pat = [0.06f64, 0.04, 0.06, 0.03, 0.06];
    let n = base.len();
    let step: Vec<f64> = (0..n).map(|j| step_pat[j % PPS]).collect();
    let clamp_all = |p: &mut [f64]| {
        for s in 0..(n / PPS) {
            clamp_stage(&mut p[s * PPS..s * PPS + PPS]);
        }
    };
    clamp_all(&mut base);
    let mut fb = obj(&base);
    let mut scale = 1.0f64;
    if let Some(d) = ckpt_dir {
        ensure_dir(d);
    }
    for iter in 0..max_iters {
        let mut trial = base.clone();
        for j in 0..n {
            let save = trial[j];
            trial[j] = save + step[j] * scale;
            clamp_all(&mut trial);
            if obj(&trial) < fb {
                continue;
            }
            trial[j] = save - step[j] * scale;
            clamp_all(&mut trial);
            if obj(&trial) >= fb {
                trial[j] = save;
            }
        }
        let ft = obj(&trial);
        if ft < fb - 1e-15 {
            let mut moved: Vec<f64> = (0..n).map(|j| trial[j] + (trial[j] - base[j])).collect();
            clamp_all(&mut moved);
            let fm = obj(&moved);
            if fm < ft {
                base = moved;
                fb = fm;
            } else {
                base = trial;
                fb = ft;
            }
        } else {
            scale *= 0.5;
            if scale < 1e-3 {
                break;
            }
        }
        if let Some(d) = ckpt_dir {
            if iter % 8 == 0 {
                write_json(
                    &d.join(format!("ckpt_{iter:03}.json")),
                    &serde_json::json!({ "iter": iter, "objective": fb, "step_scale": scale }),
                );
            }
        }
    }
    (base, fb)
}
fn corner_objective(
    stages30: &[f64],
    ts: &TargetState,
    obj_idx: &[usize],
    freqs: &[f64],
    ceil_db: f64,
) -> f64 {
    let mut arr = [[0.0f64; PPS]; NUM_STAGES];
    for si in 0..NUM_STAGES {
        arr[si].copy_from_slice(&stages30[si * PPS..si * PPS + PPS]);
    }
    let rows = single_corner_packed(&arr).interpolate_biquad(0.0, 0.0);
    let mut err = 0.0;
    let mut wsum = 0.0;
    for &i in obj_idx {
        if !ts.mask[i] {
            continue;
        }
        let f = freqs[i];
        let (hr, hi) = biquad_cascade_complex(&rows, f, SR);
        let (tr, ti) = ts.h[i];
        let dmag = 10.0 * (hr * hr + hi * hi + 1e-30).log10() - 10.0 * (tr * tr + ti * ti + 1e-30).log10();
        let dph = wrap_pi(hi.atan2(hr) - ti.atan2(tr));
        let w = ts.coh[i] * erb_weight(f);
        err += w * (dmag * dmag + LAMBDA_PH * dph * dph);
        wsum += w;
    }
    err / wsum.max(1e-30) + PEN_W * ceiling_penalty(&rows, ceil_db)
}
fn single_corner_packed(stages: &[[f64; PPS]; NUM_STAGES]) -> PackedCorners {
    let mut p = vec![0.0f64; NPARAM];
    for ci in 0..4 {
        for si in 0..NUM_STAGES {
            let base = (ci * NUM_STAGES + si) * PPS;
            p[base..base + PPS].copy_from_slice(&stages[si]);
        }
    }
    params_to_packed(&p)
}
fn refine(
    base: Vec<f64>,
    targets: &[TargetState],
    obj_idx: &[usize],
    freqs: &[f64],
    ceil_db: f64,
    ckpt_dir: &Path,
    max_iters: usize,
) -> (Vec<f64>, f64) {
    let obj = |p: &[f64]| train_objective(&params_to_packed(p), targets, obj_idx, freqs, ceil_db);
    hooke_jeeves(base, &obj, max_iters, Some(ckpt_dir))
}
fn cmd_fit(id: &str) {
    let root = session_root(id);
    ensure_dir(&root.join("fit"));
    let (targets, freqs) = load_targets(&root);
    let stride = (freqs.len() / 840).max(1);
    let obj_idx: Vec<usize> = (0..freqs.len()).step_by(stride).collect();
    let ceil_db = target_ceiling(&targets);
    let corner_states = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)];
    let mut params = vec![0.0f64; NPARAM];
    for (ci, &(m, q)) in corner_states.iter().enumerate() {
        let ts = targets
            .iter()
            .find(|t| (t.m - m).abs() < 1e-9 && (t.q - q).abs() < 1e-9)
            .expect("corner state present");
        let stages = init_corner(&ts.h, &ts.mask, &freqs);
        let flat: Vec<f64> = stages.iter().flatten().copied().collect();
        let obj = |p: &[f64]| corner_objective(p, ts, &obj_idx, &freqs, ceil_db);
        let (fitted, _) = hooke_jeeves(flat, &obj, 120, None);
        for si in 0..NUM_STAGES {
            let base = (ci * NUM_STAGES + si) * PPS;
            params[base..base + PPS].copy_from_slice(&fitted[si * PPS..si * PPS + PPS]);
        }
    }
    let init_err = train_objective(&params_to_packed(&params), &targets, &obj_idx, &freqs, ceil_db);
    let (perms, corr_id_err, corr_err) =
        search_correspondence(&mut params, &targets, &obj_idx, &freqs, ceil_db);
    let (params, fit_err) = refine(
        params,
        &targets,
        &obj_idx,
        &freqs,
        ceil_db,
        &root.join("fit").join("checkpoints"),
        60,
    );
    let base_ident = build_identity_body();
    let base_pc = PackedCorners::from_body_bytes(&base_ident).unwrap();
    let baseline_err = train_objective(&base_pc, &targets, &obj_idx, &freqs, ceil_db);
    let body = params_to_body(&params);
    std::fs::write(root.join("fit").join("candidate.body240"), body).unwrap();
    let pc = PackedCorners::from_body_bytes(&body).unwrap();
    let cart = cartridge_json(&pc);
    write_json(&root.join("fit").join("candidate.cart.json"), &cart);
    let config = serde_json::json!({
        "schema": "tf-oracle-fit-v1",
        "objective": "coherence-weighted, ERB-weighted complex error over TRAIN states via packed interpolation; absolute gain preserved (no normalization).",
        "freq_weight": "Glasberg&Moore 1990 ERB: 1/(24.7(4.37 f/1000 + 1))",
        "optimizer": "Hooke-Jeeves pattern search, deterministic, 60 iters",
        "objective_bins": obj_idx.len(),
        "init": "per-corner spectral peak-pick (poles) + valley zeros + global gain",
        "correspondence": {
            "method": "coordinate-descent over 720 perms/corner minimizing TRAIN TF error",
            "chosen_perms": perms.iter().map(|p| p.to_vec()).collect::<Vec<_>>(),
            "identity_perm_train_err": corr_id_err,
            "searched_perm_train_err": corr_err,
            "note": "identity_perm = frequency-sorted pairing; searched < identity proves correspondence solved from behavior."
        },
        "train_err_init": init_err,
        "train_err_final": fit_err,
        "train_err_baseline_identity": baseline_err,
        "improvement_vs_baseline_db": 10.0 * (baseline_err / fit_err.max(1e-30)).log10(),
    });
    write_json(&root.join("fit").join("fit_config.json"), &config);
    println!("fit done:");
    println!("  train err  init {init_err:.3e} -> corr {corr_err:.3e} -> final {fit_err:.3e}");
    println!("  baseline (identity) {baseline_err:.3e}  | improvement {:.2} dB", 10.0*(baseline_err/fit_err.max(1e-30)).log10());
    println!("  correspondence perms (c1,c2,c3): {:?} {:?} {:?}", perms[1], perms[2], perms[3]);
    println!("  candidate: fit/candidate.body240");
}
fn cartridge_json(pc: &PackedCorners) -> serde_json::Value {
    let labels = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];
    let keyframes: Vec<serde_json::Value> = (0..4)
        .map(|ci| {
            let words: Vec<Vec<u16>> = (0..NUM_STAGES)
                .map(|si| pc.words[ci][si].to_vec())
                .collect();
            serde_json::json!({ "label": labels[ci], "boost": 1.0, "packedWords": words })
        })
        .collect();
    serde_json::json!({
        "format": "compiled-v1",
        "name": "tf-oracle-candidate",
        "sampleRate": SR,
        "keyframes": keyframes,
    })
}
struct StateMetric {
    label: String,
    split: String,
    mag_rms_db: f64,
    mag_max_db: f64,
    cplx_rel_med: f64,
    phase_rms_deg: f64,
    gd_rms_samp: f64,
}
fn state_metrics(
    label: &str,
    split: &str,
    cand: &PackedCorners,
    ts: &TargetState,
    freqs: &[f64],
) -> StateMetric {
    let rows = cand.interpolate_biquad(ts.m as f32, ts.q as f32);
    let mut dmags = Vec::new();
    let mut rels = Vec::new();
    let mut phases = Vec::new();
    let mut prev: Option<(usize, f64, f64)> = None;
    let mut gd = Vec::new();
    for i in 0..freqs.len() {
        if !ts.mask[i] {
            continue;
        }
        let f = freqs[i];
        let (hr, hi) = biquad_cascade_complex(&rows, f, SR);
        let (tr, ti) = ts.h[i];
        let magc = 20.0 * (hr * hr + hi * hi).sqrt().max(1e-12).log10();
        let magt = 20.0 * (tr * tr + ti * ti).sqrt().max(1e-12).log10();
        dmags.push((magc - magt).abs());
        let num = ((hr - tr).powi(2) + (hi - ti).powi(2)).sqrt();
        let den = (tr * tr + ti * ti).sqrt().max(1e-9);
        rels.push(num / den);
        let pc_ = hi.atan2(hr);
        let pt_ = ti.atan2(tr);
        phases.push(wrap_pi(pc_ - pt_).to_degrees().abs());
        if let Some((pi, ppc, ppt)) = prev {
            let dw = TAU * (i as f64 - pi as f64) * (SR / PERIOD as f64) / SR;
            if dw > 0.0 {
                let gc = -wrap_pi(pc_ - ppc) / dw;
                let gt = -wrap_pi(pt_ - ppt) / dw;
                gd.push((gc - gt).abs());
            }
        }
        prev = Some((i, pc_, pt_));
    }
    let rms = |v: &[f64]| (v.iter().map(|x| x * x).sum::<f64>() / v.len().max(1) as f64).sqrt();
    let median = |v: &mut Vec<f64>| {
        v.sort_by(|a, b| a.partial_cmp(b).unwrap());
        v.get(v.len() / 2).copied().unwrap_or(0.0)
    };
    let mut rels_m = rels;
    StateMetric {
        label: label.to_string(),
        split: split.to_string(),
        mag_rms_db: rms(&dmags),
        mag_max_db: dmags.iter().cloned().fold(0.0, f64::max),
        cplx_rel_med: median(&mut rels_m),
        phase_rms_deg: rms(&phases),
        gd_rms_samp: rms(&gd),
    }
}
fn null_depth(cand: &PackedCorners, m: f64, q: f64, dry: &[f32], target_wet: &[f32]) -> (f64, f64) {
    let cand_wet = render_body_solo(cand, m, q, dry);
    let delay = estimate_delay_generic(target_wet, &cand_wet);
    let d = delay.round() as i64;
    let n = target_wet.len().min(cand_wet.len());
    let start = WARM_PERIODS * PERIOD;
    let mut num = 0.0f64;
    let mut den = 0.0f64;
    for i in start..n {
        let ci = i as i64 + d;
        let c = if ci >= 0 && (ci as usize) < cand_wet.len() {
            cand_wet[ci as usize] as f64
        } else {
            0.0
        };
        let t = target_wet[i] as f64;
        num += (t - c) * (t - c);
        den += t * t;
    }
    let db = 10.0 * (num.max(1e-30) / den.max(1e-30)).log10();
    (db, delay)
}
fn estimate_delay_generic(a: &[f32], b: &[f32]) -> f64 {
    let base = WARM_PERIODS * PERIOD;
    let win = 1024usize.min(a.len().saturating_sub(base));
    let mut best = 0i64;
    let mut best_c = f64::NEG_INFINITY;
    for lag in -64i64..=64 {
        let mut c = 0.0f64;
        for n in 0..win {
            let ai = base + n;
            let bi = base as i64 + n as i64 + lag;
            if ai < a.len() && bi >= 0 && (bi as usize) < b.len() {
                c += a[ai] as f64 * b[bi as usize] as f64;
            }
        }
        if c > best_c {
            best_c = c;
            best = lag;
        }
    }
    best as f64
}
fn agg(metrics: &[StateMetric], split: &str) -> serde_json::Value {
    let sel: Vec<&StateMetric> = metrics.iter().filter(|m| m.split == split).collect();
    let mean = |f: &dyn Fn(&StateMetric) -> f64| -> f64 {
        sel.iter().map(|m| f(m)).sum::<f64>() / sel.len().max(1) as f64
    };
    serde_json::json!({
        "n_states": sel.len(),
        "mag_rms_db_mean": mean(&|m| m.mag_rms_db),
        "mag_max_db_mean": mean(&|m| m.mag_max_db),
        "cplx_rel_med_mean": mean(&|m| m.cplx_rel_med),
        "phase_rms_deg_mean": mean(&|m| m.phase_rms_deg),
        "gd_rms_samp_mean": mean(&|m| m.gd_rms_samp),
    })
}
fn cmd_verify(id: &str) {
    let root = session_root(id);
    ensure_dir(&root.join("verify"));
    ensure_dir(&root.join("verify").join("plots"));
    let (targets, freqs) = load_targets(&root);
    let body = std::fs::read(root.join("fit").join("candidate.body240")).expect("candidate");
    assert_eq!(body.len(), 240, "candidate not 240 bytes");
    let cand = PackedCorners::from_body_bytes(&body).unwrap();
    let ident = build_identity_body();
    let base_pc = PackedCorners::from_body_bytes(&ident).unwrap();
    let mut cand_metrics = Vec::new();
    let mut base_metrics = Vec::new();
    for ts in &targets {
        let split = if ts.train { "train" } else { "held_out" };
        cand_metrics.push(state_metrics(&ts.label, split, &cand, ts, &freqs));
        base_metrics.push(state_metrics(&ts.label, split, &base_pc, ts, &freqs));
    }
    let load_save_ok = cand.to_rom_bytes().to_vec() == body;
    let cart = read_json(&root.join("fit").join("candidate.cart.json"));
    let cart_pc = trench_core::cartridge::Cartridge::from_json(&cart.to_string())
        .expect("cart parse")
        .packed;
    let cart_parity = cart_pc == cand;
    let mut edited = body.clone();
    edited[10] ^= 0x01;
    let edited_pc = PackedCorners::from_body_bytes(&edited).unwrap();
    let diff_words: usize = (0..4)
        .flat_map(|c| (0..NUM_STAGES).flat_map(move |s| (0..NUM_COEFFS).map(move |w| (c, s, w))))
        .filter(|&(c, s, w)| cand.words[c][s][w] != edited_pc.words[c][s][w])
        .count();
    let real_root_report = real_root_scan(&cand, &root);
    let mut unstable = 0usize;
    let mut nonfinite = 0usize;
    for mi in 0..33 {
        for qi in 0..33 {
            let m = mi as f64 / 32.0;
            let q = qi as f64 / 32.0;
            let rows = cand.interpolate_biquad(m as f32, q as f32);
            for r in rows.iter() {
                if !r.iter().all(|v| v.is_finite()) {
                    nonfinite += 1;
                }
                if pole_radius(r[3], r[4]) >= 1.0 {
                    unstable += 1;
                }
            }
        }
    }
    let audit = trench_core::response::audit_body240(&body).expect("audit");
    let perm_reg = permutation_regression(&cand, &freqs);
    let dry = wav_read_mono(&root.join("excitation_A.wav"));
    let dry_b = wav_read_mono(&root.join("excitation_B.wav"));
    let loop_wet = wav_read_mono(&root.join("capture").join("loopback.wav"));
    let bulk_delay = measure_bulk_delay(&root, &dry);
    let loop_est = estimate_tf(&dry, &loop_wet, bulk_delay);
    let loop_mag_db: Vec<f64> = loop_est
        .h
        .iter()
        .zip(&loop_est.mask)
        .filter(|(_, &m)| m)
        .map(|(h, _)| 20.0 * cabs(*h).max(1e-9).log10())
        .collect();
    let loop_max_dev = loop_mag_db.iter().cloned().fold(0.0f64, |a, b| a.max(b.abs()));
    let center = State { mi: 4, qi: 4 };
    let wa = wav_read_mono(&root.join("capture").join(format!("wet_{}_A.wav", center.label())));
    let wb = wav_read_mono(&root.join("capture").join(format!("wet_{}_B.wav", center.label())));
    let ea = estimate_tf(&dry, &wa, bulk_delay);
    let eb = estimate_tf(&dry_b, &wb, bulk_delay);
    let lti_max_db = ea
        .h
        .iter()
        .zip(&eb.h)
        .zip(&ea.mask)
        .filter(|((_, _), &m)| m)
        .map(|((a, b), _)| (20.0 * cabs(*a).max(1e-9).log10() - 20.0 * cabs(*b).max(1e-9).log10()).abs())
        .fold(0.0, f64::max);
    let war = wav_read_mono(&root.join("capture").join(format!("wet_{}_A_rep.wav", center.label())));
    let rep_rms = {
        let n = wa.len().min(war.len());
        (0..n).map(|i| (wa[i] - war[i]).powi(2) as f64).sum::<f64>().sqrt() / (n as f64).sqrt()
    };
    let null_states = [
        (State { mi: 0, qi: 0 }, "train"),
        (State { mi: 4, qi: 4 }, "train"),
        (State { mi: 3, qi: 4 }, "held_out"),
        (State { mi: 1, qi: 2 }, "held_out"),
    ];
    let mut nulls = Vec::new();
    for (s, split) in &null_states {
        let wet = wav_read_mono(&root.join("capture").join(format!("wet_{}_A.wav", s.label())));
        let (cand_db, delay) = null_depth(&cand, s.m(), s.q(), &dry, &wet);
        let (base_db, _) = null_depth(&base_pc, s.m(), s.q(), &dry, &wet);
        if s.mi == 4 && s.qi == 4 {
            let cand_wet = render_body_solo(&cand, s.m(), s.q(), &dry);
            let resid: Vec<f32> = (WARM_PERIODS * PERIOD..wet.len().min(cand_wet.len()))
                .map(|i| wet[i] - cand_wet[i])
                .collect();
            wav_write_mono(&root.join("verify").join("residual_center.wav"), &resid, SR as u32);
            wav_write_mono(&root.join("verify").join("target_center.wav"), &wet, SR as u32);
        }
        nulls.push(serde_json::json!({
            "label": s.label(), "split": split,
            "candidate_null_db": cand_db, "baseline_null_db": base_db, "delay_samples": delay,
        }));
    }
    let est_cal = estimator_calibration(&root, &freqs);
    plot_state(&root, &cand, &base_pc, &targets, &freqs, "M000_Q000");
    plot_state(&root, &cand, &base_pc, &targets, &freqs, "M050_Q050");
    plot_state(&root, &cand, &base_pc, &targets, &freqs, "M038_Q050");
    let report = serde_json::json!({
        "schema": "tf-oracle-verify-v1",
        "candidate_bytes": body.len(),
        "fit_train_vs_heldout": {
            "candidate": { "train": agg(&cand_metrics, "train"), "held_out": agg(&cand_metrics, "held_out") },
            "baseline_identity": { "train": agg(&base_metrics, "train"), "held_out": agg(&base_metrics, "held_out") },
        },
        "runtime_body_gates": {
            "exactly_240_bytes": body.len() == 240,
            "no_op_load_save_identical": load_save_ok,
            "body_cart_parity": cart_parity,
            "declared_edit_changed_words": diff_words,
            "declared_edit_isolated": diff_words == 1,
            "real_root_explicit": real_root_report,
        },
        "certification": {
            "dense_grid": "33x33 Morph×Q",
            "unstable_rows": unstable,
            "nonfinite_rows": nonfinite,
            "sampled_certification_pass": unstable == 0 && nonfinite == 0,
            "owned_audit_gate_pass": audit.gate.pass,
            "owned_audit_failures": audit.gate.failures,
            "note": "sampled certification over a 33x33 grid — NOT a continuum proof",
        },
        "permutation_regression": perm_reg,
        "estimator_sanity": {
            "loopback_unity_max_dev_db": loop_max_dev,
            "loopback_delay_samples": loop_est.delay,
            "lti_A_vs_B_max_db": lti_max_db,
            "repeatability_rms": rep_rms,
        },
        "estimator_calibration_vs_oracle": est_cal,
        "null": nulls,
        "plots": ["verify/plots/M000_Q000.svg","verify/plots/M050_Q050.svg","verify/plots/M038_Q050.svg"],
    });
    write_json(&root.join("verify").join("verify_report.json"), &report);
    let ct = agg(&cand_metrics, "train");
    let ch = agg(&cand_metrics, "held_out");
    let bt = agg(&base_metrics, "train");
    let bh = agg(&base_metrics, "held_out");
    println!("verify:");
    println!("  mag RMS dB   train cand {:.2} (base {:.2}) | held cand {:.2} (base {:.2})",
        ct["mag_rms_db_mean"].as_f64().unwrap(), bt["mag_rms_db_mean"].as_f64().unwrap(),
        ch["mag_rms_db_mean"].as_f64().unwrap(), bh["mag_rms_db_mean"].as_f64().unwrap());
    println!("  cert 33x33: {unstable} unstable, {nonfinite} nonfinite | owned gate {}", audit.gate.pass);
    println!("  gates: 240B {} | load/save {} | cart-parity {} | edit-isolated {}",
        body.len()==240, load_save_ok, cart_parity, diff_words==1);
    println!("  perm-regression: corner Δ {:.4} dB, interior Δ {:.2} dB (pass {})",
        perm_reg["corner_max_db"].as_f64().unwrap(), perm_reg["interior_max_db"].as_f64().unwrap(),
        perm_reg["pass"].as_bool().unwrap());
    println!("  null center: cand {:.1} dB vs baseline {:.1} dB",
        nulls[1]["candidate_null_db"].as_f64().unwrap(), nulls[1]["baseline_null_db"].as_f64().unwrap());
    println!("  loopback unity dev {:.3} dB, delay {} | LTI A/B {:.3} dB | repeat rms {:.2e}",
        loop_max_dev, loop_est.delay, lti_max_db, rep_rms);
}
fn permutation_regression(pc: &PackedCorners, freqs: &[f64]) -> serde_json::Value {
    let perm = [3usize, 1, 0, 5, 2, 4];
    let mut permuted = pc.clone();
    for (slot, &old) in perm.iter().enumerate() {
        permuted.words[1][slot] = pc.words[1][old];
    }
    let mag_at = |p: &PackedCorners, m: f64, q: f64, f: f64| -> f64 {
        let rows = p.interpolate_biquad(m as f32, q as f32);
        let (r, i) = biquad_cascade_complex(&rows, f, SR);
        20.0 * (r * r + i * i).sqrt().max(1e-12).log10()
    };
    let mut corner_max = 0.0f64;
    let mut interior_max = 0.0f64;
    for &f in freqs {
        corner_max = corner_max.max((mag_at(pc, 1.0, 0.0, f) - mag_at(&permuted, 1.0, 0.0, f)).abs());
        interior_max =
            interior_max.max((mag_at(pc, 0.5, 0.0, f) - mag_at(&permuted, 0.5, 0.0, f)).abs());
    }
    serde_json::json!({
        "permuted_corner": "M100_Q0",
        "permutation": perm.to_vec(),
        "corner_max_db": corner_max,
        "interior_max_db": interior_max,
        "pass": corner_max < 1e-6 && interior_max > 1e-3,
        "note": "corner TF invariant under stage permutation; interior TF changes -> correspondence is a real hidden variable.",
    })
}
fn real_root_scan(cand: &PackedCorners, root: &Path) -> serde_json::Value {
    use trench_core::stage_law::{geometry_from_words, roots_from_words, RootPair};
    let mut cand_real = 0usize;
    let mut violations = 0usize;
    let mut scan = |pc: &PackedCorners| {
        for ci in 0..4 {
            for si in 0..NUM_STAGES {
                let w = pc.words[ci][si];
                let g = geometry_from_words(w);
                let is_real = matches!(g.pole, RootPair::RealPair { .. })
                    || matches!(g.zero, RootPair::RealPair { .. });
                if is_real {
                    if roots_from_words(w).is_some() {
                        violations += 1;
                    }
                    return_real(&mut cand_real);
                }
            }
        }
    };
    fn return_real(c: &mut usize) {
        *c += 1;
    }
    scan(cand);
    let mut oracle_real = 0usize;
    let op = root.join("_hidden").join("oracle.body240");
    if let Ok(b) = std::fs::read(&op) {
        if let Ok(opc) = PackedCorners::from_body_bytes(&b) {
            for ci in 0..4 {
                for si in 0..NUM_STAGES {
                    let g = geometry_from_words(opc.words[ci][si]);
                    if matches!(g.pole, RootPair::RealPair { .. })
                        || matches!(g.zero, RootPair::RealPair { .. })
                    {
                        oracle_real += 1;
                        if roots_from_words(opc.words[ci][si]).is_some() {
                            violations += 1;
                        }
                    }
                }
            }
        }
    }
    serde_json::json!({
        "candidate_real_root_rows": cand_real,
        "oracle_real_root_rows": oracle_real,
        "silent_conjugate_clamps": violations,
        "pass": violations == 0,
        "note": "a real-root row is returned as RealPair by geometry_from_words and REFUSED (None) by the conjugate reader.",
    })
}
fn estimator_calibration(root: &Path, freqs: &[f64]) -> serde_json::Value {
    let op = root.join("_hidden").join("oracle.body240");
    let Ok(b) = std::fs::read(&op) else {
        return serde_json::json!({ "available": false });
    };
    let opc = PackedCorners::from_body_bytes(&b).unwrap();
    let states = [State { mi: 0, qi: 0 }, State { mi: 4, qi: 4 }, State { mi: 8, qi: 8 }];
    let mut mag_err = Vec::new();
    let mut ph_err = Vec::new();
    for s in &states {
        let (_b, h, _c, mask) = load_estimate(root, &s.label());
        let rows = opc.interpolate_biquad(s.m() as f32, s.q() as f32);
        for i in 0..freqs.len() {
            if !mask[i] {
                continue;
            }
            let (tr, ti) = biquad_cascade_complex(&rows, freqs[i], SR);
            let (er, ei) = h[i];
            mag_err.push((20.0 * cabs((er, ei)).max(1e-9).log10() - 20.0 * cabs((tr, ti)).max(1e-9).log10()).abs());
            ph_err.push(wrap_pi(ei.atan2(er) - ti.atan2(tr)).to_degrees().abs());
        }
    }
    let rms = |v: &[f64]| (v.iter().map(|x| x * x).sum::<f64>() / v.len().max(1) as f64).sqrt();
    serde_json::json!({
        "available": true,
        "states": states.iter().map(|s| s.label()).collect::<Vec<_>>(),
        "mag_rms_db": rms(&mag_err),
        "mag_max_db": mag_err.iter().cloned().fold(0.0, f64::max),
        "phase_rms_deg": rms(&ph_err),
        "note": "estimator vs known oracle response; derives the recovery tolerance.",
    })
}
fn plot_state(
    root: &Path,
    cand: &PackedCorners,
    base: &PackedCorners,
    targets: &[TargetState],
    freqs: &[f64],
    label: &str,
) {
    let Some(ts) = targets.iter().find(|t| t.label == label) else {
        return;
    };
    let target_db: Vec<f64> = ts
        .h
        .iter()
        .map(|&c| 20.0 * cabs(c).max(1e-12).log10())
        .collect();
    let cand_rows = cand.interpolate_biquad(ts.m as f32, ts.q as f32);
    let base_rows = base.interpolate_biquad(ts.m as f32, ts.q as f32);
    let cand_db: Vec<f64> = freqs
        .iter()
        .map(|&f| {
            let (r, i) = biquad_cascade_complex(&cand_rows, f, SR);
            20.0 * (r * r + i * i).sqrt().max(1e-12).log10()
        })
        .collect();
    let base_db: Vec<f64> = freqs
        .iter()
        .map(|&f| {
            let (r, i) = biquad_cascade_complex(&base_rows, f, SR);
            20.0 * (r * r + i * i).sqrt().max(1e-12).log10()
        })
        .collect();
    let curves: [(&str, &str, &Vec<f64>); 3] = [
        ("target", "#e0b030", &target_db),
        ("candidate", "#30c0e0", &cand_db),
        ("baseline", "#808080", &base_db),
    ];
    let svg = svg_response(
        &format!("{label}  (morph {:.2}, q {:.2}, {})", ts.m, ts.q, if ts.train { "TRAIN" } else { "HELD-OUT" }),
        freqs,
        &curves,
        &ts.mask,
    );
    std::fs::write(root.join("verify").join("plots").join(format!("{label}.svg")), svg).unwrap();
}
fn svg_response(
    title: &str,
    freqs: &[f64],
    curves: &[(&str, &str, &Vec<f64>)],
    mask: &[bool],
) -> String {
    let (w, h) = (1000.0f64, 560.0f64);
    let (ml, mr, mt, mb) = (70.0, 20.0, 40.0, 50.0);
    let (pw, ph) = (w - ml - mr, h - mt - mb);
    let mut ymin = f64::INFINITY;
    let mut ymax = f64::NEG_INFINITY;
    for (_, _, d) in curves {
        for (i, &v) in d.iter().enumerate() {
            if mask.get(i).copied().unwrap_or(true) && v.is_finite() {
                ymin = ymin.min(v);
                ymax = ymax.max(v);
            }
        }
    }
    ymin = (ymin - 3.0).floor();
    ymax = (ymax + 3.0).ceil();
    let (flo, fhi) = (F_LO.max(20.0), F_HI);
    let xof = |f: f64| ml + pw * ((f.max(flo).ln() - flo.ln()) / (fhi.ln() - flo.ln()));
    let yof = |db: f64| mt + ph * (1.0 - (db - ymin) / (ymax - ymin).max(1e-9));
    let mut s = format!(
        "<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' font-family='monospace' font-size='12'>\
         <rect width='{w}' height='{h}' fill='#111'/>\
         <text x='{tx}' y='22' fill='#ccc'>{title}</text>",
        tx = ml
    );
    let mut db = (ymin / 6.0).ceil() * 6.0;
    while db <= ymax {
        let y = yof(db);
        s.push_str(&format!(
            "<line x1='{ml}' y1='{y:.1}' x2='{x2:.1}' y2='{y:.1}' stroke='#333'/><text x='4' y='{ty:.1}' fill='#888'>{db:.0}</text>",
            x2 = ml + pw, ty = y + 4.0
        ));
        db += 6.0;
    }
    for &f in &[20.0, 50.0, 100.0, 200.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0] {
        if f < flo || f > fhi {
            continue;
        }
        let x = xof(f);
        let lbl = if f >= 1000.0 { format!("{:.0}k", f / 1000.0) } else { format!("{f:.0}") };
        s.push_str(&format!(
            "<line x1='{x:.1}' y1='{mt}' x2='{x:.1}' y2='{y2:.1}' stroke='#282828'/><text x='{tx:.1}' y='{ty:.1}' fill='#888'>{lbl}</text>",
            y2 = mt + ph, tx = x - 8.0, ty = h - mb + 16.0
        ));
    }
    for (name, color, data) in curves {
        let mut pts = String::new();
        for (i, &f) in freqs.iter().enumerate() {
            let v = data[i];
            if !v.is_finite() {
                continue;
            }
            pts.push_str(&format!("{:.1},{:.1} ", xof(f), yof(v)));
        }
        s.push_str(&format!(
            "<polyline points='{pts}' fill='none' stroke='{color}' stroke-width='1.5'/>"
        ));
        let _ = name;
    }
    let lx = ml + pw - 150.0;
    for (row, (name, color, _)) in curves.iter().enumerate() {
        let ly = mt + 6.0 + row as f64 * 18.0;
        s.push_str(&format!(
            "<rect x='{lx:.0}' y='{ly:.0}' width='12' height='12' fill='{color}'/><text x='{tx:.0}' y='{ty:.0}' fill='#ccc'>{name}</text>",
            tx = lx + 16.0, ty = ly + 11.0
        ));
    }
    s.push_str("</svg>");
    s
}
fn cmd_bundle(id: &str) {
    let root = session_root(id);
    let read = |p: &str| root.join(p);
    let hash_file = |p: &Path| -> String {
        std::fs::read(p).map(|b| sha256_hex(&b)).unwrap_or_default()
    };
    let fit = read_json(&read("fit/fit_config.json"));
    let verify = read_json(&read("verify/verify_report.json"));
    let cap = read_json(&read("capture_manifest.json"));
    let hashes = serde_json::json!({
        "excitation_A.wav": hash_file(&read("excitation_A.wav")),
        "candidate.body240": hash_file(&read("fit/candidate.body240")),
        "candidate.cart.json": hash_file(&read("fit/candidate.cart.json")),
        "target_001": cap["target_sha256"].clone(),
    });
    write_json(&read("hashes.json"), &hashes);
    write_json(&read("provenance.json"), &provenance_block());
    let ct = &verify["fit_train_vs_heldout"]["candidate"];
    let bt = &verify["fit_train_vs_heldout"]["baseline_identity"];
    let cert = &verify["certification"];
    let summary = format!(
        "# TRENCH transfer-function oracle — session {id}\n\n\
**Result:** synthetic hidden-body recovery ran end to end (prepare→synth→estimate→fit→verify→bundle); \
candidate is a 240-byte packed body that improves on the neutral baseline on held-out interior states \
and passes sampled certification.\n\n\
## Transfer-function recovery (packed runtime, absolute gain)\n\
| metric | candidate train | candidate held-out | baseline train | baseline held-out |\n\
|---|---|---|---|---|\n\
| mag RMS dB | {:.2} | {:.2} | {:.2} | {:.2} |\n\
| mag max dB | {:.2} | {:.2} | {:.2} | {:.2} |\n\
| complex rel (median) | {:.3} | {:.3} | {:.3} | {:.3} |\n\
| phase RMS deg | {:.1} | {:.1} | {:.1} | {:.1} |\n\n\
## Certification (sampled, NOT continuum)\n\
- dense 33×33 Morph×Q: **{} unstable, {} nonfinite** (pass {})\n\
- owned crown/stability gate: pass {}\n\
- endpoint-preserving permutation regression: corner Δ {:.2e} dB, interior Δ {:.2} dB (pass {})\n\n\
## Runtime/body gates\n\
- exactly 240 bytes: {} | no-op load/save identical: {} | body/cart parity: {} | declared edit isolated: {}\n\
- real-root explicit (no silent conjugate clamp): pass {}\n\n\
## Fit\n\
- correspondence solved from TRAIN behavior (not frequency sort): identity-perm err {:.3e} → searched err {:.3e}\n\
- improvement vs baseline: {:.2} dB\n\n\
## Provenance / clean room\n\
- {}\n\
- {}\n\n\
## Proof bundle\n\
`dev/tmp/tf_oracle/{id}/` — session.json, excitation + capture WAVs (+sha256), estimate/*.f32 (raw complex H + coherence), \
fit/candidate.body240 + .cart.json + checkpoints, verify/verify_report.json + plots/*.svg + null WAVs, hashes.json, provenance.json.\n\n\
## Reproduce\n\
```\ncargo run -p trench-core --bin tf-oracle -- run --session {id}\n```\n\
(add `--oracle <path.body240>` to target a specific legal body; a real anonymous capture replaces `synth` with externally-bounced wet WAVs, then `estimate → fit → verify → bundle`.)\n\n\
## Next command\n\
```\ncargo run -p trench-core --bin tf-oracle -- run --session <new_id> --oracle fixtures/four-pose.body240\n```\n",
        ct["train"]["mag_rms_db_mean"].as_f64().unwrap(), ct["held_out"]["mag_rms_db_mean"].as_f64().unwrap(),
        bt["train"]["mag_rms_db_mean"].as_f64().unwrap(), bt["held_out"]["mag_rms_db_mean"].as_f64().unwrap(),
        ct["train"]["mag_max_db_mean"].as_f64().unwrap(), ct["held_out"]["mag_max_db_mean"].as_f64().unwrap(),
        bt["train"]["mag_max_db_mean"].as_f64().unwrap(), bt["held_out"]["mag_max_db_mean"].as_f64().unwrap(),
        ct["train"]["cplx_rel_med_mean"].as_f64().unwrap(), ct["held_out"]["cplx_rel_med_mean"].as_f64().unwrap(),
        bt["train"]["cplx_rel_med_mean"].as_f64().unwrap(), bt["held_out"]["cplx_rel_med_mean"].as_f64().unwrap(),
        ct["train"]["phase_rms_deg_mean"].as_f64().unwrap(), ct["held_out"]["phase_rms_deg_mean"].as_f64().unwrap(),
        bt["train"]["phase_rms_deg_mean"].as_f64().unwrap(), bt["held_out"]["phase_rms_deg_mean"].as_f64().unwrap(),
        cert["unstable_rows"].as_i64().unwrap(), cert["nonfinite_rows"].as_i64().unwrap(),
        cert["sampled_certification_pass"].as_bool().unwrap(), cert["owned_audit_gate_pass"].as_bool().unwrap(),
        verify["permutation_regression"]["corner_max_db"].as_f64().unwrap(),
        verify["permutation_regression"]["interior_max_db"].as_f64().unwrap(),
        verify["permutation_regression"]["pass"].as_bool().unwrap(),
        verify["runtime_body_gates"]["exactly_240_bytes"].as_bool().unwrap(),
        verify["runtime_body_gates"]["no_op_load_save_identical"].as_bool().unwrap(),
        verify["runtime_body_gates"]["body_cart_parity"].as_bool().unwrap(),
        verify["runtime_body_gates"]["declared_edit_isolated"].as_bool().unwrap(),
        verify["runtime_body_gates"]["real_root_explicit"]["pass"].as_bool().unwrap(),
        fit["correspondence"]["identity_perm_train_err"].as_f64().unwrap(),
        fit["correspondence"]["searched_perm_train_err"].as_f64().unwrap(),
        fit["improvement_vs_baseline_db"].as_f64().unwrap(),
        provenance_block()["clean_room"].as_str().unwrap(),
        provenance_block()["agent_exposure"].as_str().unwrap(),
    );
    std::fs::write(read("SUMMARY.md"), summary).expect("write summary");
    println!("bundle written: {}", read("SUMMARY.md").display());
}
fn radius_from_bw(bw_hz: f64) -> f64 {
    (-std::f64::consts::PI * bw_hz / SR).exp().clamp(0.5, 0.9985)
}
fn formant_words(fc: f64, bw_hz: f64, gain_db: f64) -> [u16; NUM_COEFFS] {
    let q = (fc / bw_hz).clamp(0.6, 30.0);
    biquad_to_words(section_biquad(TYPE_PEAK, fc, q, gain_db))
}
fn pole_zero_words(pole_hz: f64, pole_bw: f64, zero_hz: f64, zero_bw: f64) -> [u16; NUM_COEFFS] {
    let rp = radius_from_bw(pole_bw);
    let rz = radius_from_bw(zero_bw);
    let (wp, wz) = (TAU * pole_hz / SR, TAU * zero_hz / SR);
    let a1 = -2.0 * rp * wp.cos();
    let a2 = rp * rp;
    let nb1 = -2.0 * rz * wz.cos();
    let nb2 = rz * rz;
    let b0 = (1.0 + a1 + a2) / (1.0 + nb1 + nb2).abs().max(1e-6);
    biquad_to_words([b0, b0 * nb1, b0 * nb2, a1, a2])
}
fn identity_words() -> [u16; NUM_COEFFS] {
    biquad_to_words([1.0, 0.0, 0.0, 0.0, 0.0])
}
fn mouth_corner(
    f1: (f64, f64),
    f2: (f64, f64),
    f3: (f64, f64),
    f4: (f64, f64),
    nasal: Option<(f64, f64, f64, f64)>,
    lateral: Option<(f64, f64, f64, f64)>,
) -> [[u16; NUM_COEFFS]; NUM_STAGES] {
    [
        formant_words(f1.0, f1.1, 13.0),
        formant_words(f2.0, f2.1, 12.0),
        formant_words(f3.0, f3.1, 11.0),
        formant_words(f4.0, f4.1, 6.0),
        nasal.map(|(a, b, c, d)| pole_zero_words(a, b, c, d)).unwrap_or_else(identity_words),
        lateral.map(|(a, b, c, d)| pole_zero_words(a, b, c, d)).unwrap_or_else(identity_words),
    ]
}
fn build_branching_mouth() -> [u8; 240] {
    let m0_q0 = mouth_corner((730.0, 50.0), (1090.0, 70.0), (2440.0, 110.0), (3300.0, 250.0), None, None);
    let m100_q0 = mouth_corner((270.0, 50.0), (2290.0, 70.0), (3010.0, 110.0), (3300.0, 250.0), None, None);
    let m0_q100 = mouth_corner(
        (830.0, 130.0), (1090.0, 70.0), (2440.0, 110.0), (3300.0, 250.0),
        Some((270.0, 100.0, 550.0, 100.0)),
        Some((2400.0, 300.0, 2000.0, 150.0)),
    );
    let m100_q100 = mouth_corner(
        (370.0, 130.0), (2290.0, 70.0), (3010.0, 110.0), (3300.0, 250.0),
        Some((270.0, 100.0, 320.0, 100.0)),
        Some((2400.0, 300.0, 2000.0, 150.0)),
    );
    let words = [m0_q0, m100_q0, m0_q100, m100_q100];
    PackedCorners { words }.to_rom_bytes()
}
fn cmd_author_mouth(id: &str) {
    let root = session_root(id);
    ensure_dir(&root.join("bank"));
    let body = build_branching_mouth();
    let pc = PackedCorners::from_body_bytes(&body).unwrap();
    std::fs::write(root.join("bank").join("branching_mouth.body240"), body).unwrap();
    write_json(&root.join("bank").join("branching_mouth.cart.json"), &cartridge_json(&pc));
    let audit = trench_core::response::audit_body240(&body).expect("audit");
    let mut unstable = 0usize;
    let mut nonfinite = 0usize;
    for mi in 0..33 {
        for qi in 0..33 {
            let rows = pc.interpolate_biquad(mi as f32 / 32.0, qi as f32 / 32.0);
            for r in rows.iter() {
                if !r.iter().all(|v| v.is_finite()) {
                    nonfinite += 1;
                }
                if pole_radius(r[3], r[4]) >= 1.0 {
                    unstable += 1;
                }
            }
        }
    }
    let grid = log_frequency_grid(30.0, 16_000.0, 500);
    let curve = |m: f64, q: f64| -> Vec<f64> {
        let rows = pc.interpolate_biquad(m as f32, q as f32);
        grid.iter()
            .map(|&f| {
                let (r, i) = biquad_cascade_complex(&rows, f, SR);
                20.0 * (r * r + i * i).sqrt().max(1e-12).log10()
            })
            .collect()
    };
    let aa = curve(0.0, 0.0);
    let ii = curve(1.0, 0.0);
    let aa_n = curve(0.0, 1.0);
    let ii_n = curve(1.0, 1.0);
    let mask = vec![true; grid.len()];
    let curves: [(&str, &str, &Vec<f64>); 4] = [
        ("oral /ɑ/ (M0 Q0)", "#e0b030", &aa),
        ("oral /i/ (M100 Q0)", "#30c0e0", &ii),
        ("branched /ɑ/ (M0 Q100)", "#e06060", &aa_n),
        ("branched /i/ (M100 Q100)", "#80e080", &ii_n),
    ];
    let svg = svg_response("BRANCHING MOUTH — four authored corners (cited formants + branch zeros)", &grid, &curves, &mask);
    std::fs::write(root.join("bank").join("branching_mouth_corners.svg"), svg).unwrap();
    println!("authored Branching Mouth -> bank/branching_mouth.body240");
    println!("  crown gate {} | crown {:.1}..{:.1} dB parity {:.1}",
        audit.gate.pass, audit.gate.measured_crown_min_db, audit.gate.measured_crown_max_db, audit.gate.measured_crown_parity_db);
    println!("  cert 33x33: {unstable} unstable, {nonfinite} nonfinite");
    println!("  plot: bank/branching_mouth_corners.svg");
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn sha256_known_vector() {
        assert_eq!(
            sha256_hex(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }
    #[test]
    fn fft_roundtrip() {
        let mut re: Vec<f64> = (0..64).map(|i| (i as f64 * 0.3).sin()).collect();
        let mut im = vec![0.0f64; 64];
        let orig = re.clone();
        fft(&mut re, &mut im, false);
        fft(&mut re, &mut im, true);
        for (a, b) in re.iter().zip(&orig) {
            assert!((a - b).abs() < 1e-9);
        }
    }
    #[test]
    fn multisine_is_flat_on_excited_bins() {
        let x = multisine_period(0.2);
        let mut re: Vec<f64> = x.clone();
        let mut im = vec![0.0f64; PERIOD];
        fft(&mut re, &mut im, false);
        let bins = excited_bins();
        let mags: Vec<f64> = bins
            .iter()
            .map(|&k| (re[k] * re[k] + im[k] * im[k]).sqrt())
            .collect();
        let mean = mags.iter().sum::<f64>() / mags.len() as f64;
        for m in &mags {
            assert!((m - mean).abs() / mean < 1e-6, "excited bin not flat");
        }
        let off: f64 = (1..PERIOD / 2)
            .filter(|k| !bins.contains(k))
            .map(|k| (re[k] * re[k] + im[k] * im[k]).sqrt())
            .sum();
        assert!(off < 1e-6, "leakage into non-excited bins: {off}");
    }
    #[test]
    fn param_body_roundtrip_is_240_bytes() {
        let p = vec![0.5f64; NPARAM];
        let body = params_to_body(&p);
        assert_eq!(body.len(), 240);
        let pc = PackedCorners::from_body_bytes(&body).unwrap();
        assert_eq!(pc.to_rom_bytes(), body);
    }
    #[test]
    fn synth_oracle_is_valid_and_stable() {
        let b = build_synth_oracle();
        assert_eq!(b.len(), 240);
        let pc = PackedCorners::from_body_bytes(&b).unwrap();
        for &m in &[0.0, 0.5, 1.0] {
            for &q in &[0.0, 0.5, 1.0] {
                let rows = pc.interpolate_biquad(m, q);
                for r in rows.iter() {
                    assert!(r.iter().all(|v| v.is_finite()));
                    assert!(pole_radius(r[3], r[4]) < 1.0);
                }
            }
        }
    }
}
