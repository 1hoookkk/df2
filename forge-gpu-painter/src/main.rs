// TRENCH FORGE — Z-plane filter designer (GPU, eframe/wgpu, fully custom painted).
//
// Six second-order IIR sections; each section is a conjugate pole pair and a
// conjugate zero pair, stored per corner (M0Q0, M100Q0, M0Q100, M100Q100).
// Bytes are packed through trench_core::compiler::pack_body — the same forward
// compiler the shipped engine uses — and every curve on screen is computed from
// the packed words through the engine's own interpolation (lerp on u16 words,
// morph first, then Q). The plot is the engine or it is nothing.
//
// All chrome is custom painted: chips, menus, sliders, value fields, band
// cards, maps. egui supplies only the window, input and the painter.
// UI register is textbook DSP: Hz, pole radius r, zero radius r_z, gain dB,
// morph, Q. Type-family seeds cover the classic taxonomy (LPF / HPF / BPF /
// EQ / notch comb / resonant peaks / vowel formants / tube / metal).

mod gpu_plot;
mod model;
mod painter;
mod sources;

use painter::theme::{
    with_alpha, BG, EDGE, EMBER, FAULT, GHOST_HI, GHOST_LO, ICE, PANEL, PANEL_HI, TEXT, TEXT_DIM,
    TRUTH,
};

use eframe::egui::{
    self, Align2, Color32, Event, FontId, Key, Pos2, Rect, Sense, Stroke, TextureHandle,
    TextureOptions, Vec2,
};
use eframe::egui_wgpu;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::f32::consts::TAU as TAU32;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

// ── audio (cpal output: source → FilterEngine (AGC + saturation) → device) ───

#[derive(Clone, Copy, PartialEq, Eq)]
enum AudioSrc {
    Noise,
    Saw,
    Pad,
}

impl AudioSrc {
    fn label(self) -> &'static str {
        match self {
            Self::Noise => "NOISE",
            Self::Saw => "SAW",
            Self::Pad => "PAD",
        }
    }
}

struct AudioCtl {
    playing: bool,
    morph: f64,
    q: f64,
    src: AudioSrc,
    // parsed on the UI thread — the audio callback only swaps it in
    pending_cart: Option<trench_core::cartridge::Cartridge>,
}

struct AudioHandle {
    _stream: cpal::Stream, // kept alive; drops = silence
    ctl: Arc<Mutex<AudioCtl>>,
}

struct SourceState {
    rng: u32,
    phase: [f32; 4],
}

impl SourceState {
    fn fill(&mut self, src: AudioSrc, sr: f32, out: &mut [f32]) {
        match src {
            AudioSrc::Noise => {
                for v in out.iter_mut() {
                    // xorshift32 white noise
                    self.rng ^= self.rng << 13;
                    self.rng ^= self.rng >> 17;
                    self.rng ^= self.rng << 5;
                    *v = (self.rng as f32 / u32::MAX as f32 - 0.5) * 0.5;
                }
            }
            AudioSrc::Saw => {
                let f = 55.0 / sr; // A1 bass saw
                for v in out.iter_mut() {
                    self.phase[0] = (self.phase[0] + f).fract();
                    *v = (self.phase[0] * 2.0 - 1.0) * 0.35;
                }
            }
            AudioSrc::Pad => {
                // sustained A chord: detuned saws at 110 / 164.81 / 220 Hz
                let fs = [110.0 / sr, 164.81 / sr, 220.0 / sr, 110.6 / sr];
                for v in out.iter_mut() {
                    let mut acc = 0.0;
                    for (k, f) in fs.iter().enumerate() {
                        self.phase[k] = (self.phase[k] + f).fract();
                        acc += self.phase[k] * 2.0 - 1.0;
                    }
                    *v = acc * 0.09;
                }
            }
        }
    }
}

// ── compute worker (solver + heat + audit off the UI thread) ─────────────────

struct SolveReq {
    sections: Vec<Section>,
    corner: usize,
    scope: Vec<usize>,
    f_center: f32,
    finger_db: f32,
    sigma: f32,
    follow: f32,
    fine: f32,
    morph: f32,
    q: f32,
}

struct SolveResp {
    sections: Vec<Section>,
    stages: Vec<usize>,
    residual: f32,
    f_center: f32,
    sigma: f32,
}

enum Job {
    Solve(SolveReq),
    Optimize(OptReq),
    Heat {
        words: [[[u16; 5]; STAGES]; CORNERS],
        q: f32,
    },
    Audit {
        words: [[[u16; 5]; STAGES]; CORNERS],
    },
}

enum Resp {
    Solve(SolveResp),
    Optimize(OptResp),
    Heat(Vec<Color32>),
    Audit {
        levels: Vec<f32>,
        maxr: f32,
        unstable: usize,
        pixels: Vec<Color32>,
    },
}

fn spawn_worker() -> (
    std::sync::mpsc::Sender<Job>,
    std::sync::mpsc::Receiver<Resp>,
) {
    let (job_tx, job_rx) = std::sync::mpsc::channel::<Job>();
    let (resp_tx, resp_rx) = std::sync::mpsc::channel::<Resp>();
    std::thread::spawn(move || {
        loop {
            let Ok(first) = job_rx.recv() else { return };
            // coalesce: keep only the newest job of each kind
            let (mut solve, mut optimize, mut heat, mut audit) = (None, None, None, None);
            let mut stash = |job: Job| match job {
                Job::Solve(r) => solve = Some(r),
                Job::Optimize(r) => optimize = Some(r),
                Job::Heat { words, q } => heat = Some((words, q)),
                Job::Audit { words } => audit = Some(words),
            };
            stash(first);
            while let Ok(job) = job_rx.try_recv() {
                stash(job);
            }
            if let Some(req) = solve {
                let _ = resp_tx.send(Resp::Solve(solve_grip(req)));
            }
            if let Some(req) = optimize {
                let _ = resp_tx.send(Resp::Optimize(solve_goal(req)));
            }
            if let Some((words, q)) = heat {
                let _ = resp_tx.send(Resp::Heat(compute_heat(&words, q)));
            }
            if let Some(words) = audit {
                let (levels, maxr, unstable, pixels) = compute_audit(&words);
                let _ = resp_tx.send(Resp::Audit {
                    levels,
                    maxr,
                    unstable,
                    pixels,
                });
            }
        }
    });
    (job_tx, resp_rx)
}

fn params168_of(sections: &[Section]) -> Vec<f64> {
    let mut out = Vec::with_capacity(168);
    for key in CornerKey::ALL {
        for section in sections {
            let c = section.corners[key.idx()];
            out.push(if section.on { 1.0 } else { 0.0 });
            out.push(c.pole_hz as f64);
            out.push(c.pole_r as f64);
            out.push(db_to_lin(c.gain_db) as f64);
            out.push(if c.zero_r > 0.0001 { 1.0 } else { 0.0 });
            out.push(c.zero_hz as f64);
            out.push(c.zero_r as f64);
        }
    }
    out
}

fn words_of(body: &[u8; 240]) -> [[[u16; 5]; STAGES]; CORNERS] {
    let mut words = [[[0u16; 5]; STAGES]; CORNERS];
    let mut i = 0;
    for corner in &mut words {
        for stage in corner {
            for word in stage {
                *word = u16::from_le_bytes([body[i], body[i + 1]]);
                i += 2;
            }
        }
    }
    words
}

/// True-runtime forward model: sections → pack_body → word lerp → |H| dB.
/// EVERY optimizer loss evaluation (grip and goal pins) goes through here —
/// never a continuous-filter surrogate.
fn eval_packed_goal(sections: &[Section], morph: f32, q: f32, wfreqs: &[f32]) -> Vec<f32> {
    let trig: Vec<(f64, f64)> = wfreqs.iter().map(|&f| trig_of(f)).collect();
    eval_packed_goal_t(sections, morph, q, &trig)
}

/// same forward model with the window's trig precomputed — the solvers call
/// this ~26× per step on one fixed window, so cos() leaves the inner loop
fn eval_packed_goal_t(sections: &[Section], morph: f32, q: f32, wtrig: &[(f64, f64)]) -> Vec<f32> {
    let body = trench_core::compiler::pack_body(&params168_of(sections));
    let stages = live_biquads(&words_of(&body), morph, q);
    wtrig
        .iter()
        .map(|&(c1, c2)| cascade_db_c(&stages, c1, c2))
        .collect()
}

fn grip_params_of(sections: &[Section], stages: &[usize], corner: usize) -> Vec<f32> {
    let mut out = Vec::with_capacity(stages.len() * 3);
    for &s in stages {
        let c = sections[s].corners[corner];
        out.push(c.pole_hz.log2());
        out.push((1.0 - c.pole_r).ln());
        out.push(c.gain_db);
    }
    out
}

fn grip_apply_to(sections: &mut [Section], stages: &[usize], scope: &[usize], p: &[f32]) {
    for (k, &s) in stages.iter().enumerate() {
        let f = 2f32.powf(p[k * 3]).clamp(F_MIN, F_MAX);
        let r = (1.0 - p[k * 3 + 1].exp()).clamp(RP_MIN, RP_MAX);
        let g = p[k * 3 + 2].clamp(GAIN_DB_MIN, GAIN_DB_MAX);
        for &ci in scope {
            let c = &mut sections[s].corners[ci];
            c.pole_hz = f;
            c.pole_r = r;
            c.gain_db = g;
        }
    }
}

fn recruit_in(sections: &[Section], f_center: f32, sigma: f32, corner: usize) -> Vec<(usize, f32)> {
    // sigma and distances in BARK: the brush grabs an audible region
    let reach = 1.5 * sigma + 0.5;
    let soft = sigma * 0.9 + 0.3;
    let zc = bark_z(f_center);
    let mut cand: Vec<(f32, usize)> = sections
        .iter()
        .enumerate()
        .filter(|(_, s)| s.on && !s.locked)
        .map(|(k, s)| ((bark_z(s.corners[corner].pole_hz) - zc).abs(), k))
        .collect();
    cand.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
    let mut out: Vec<(usize, f32)> = cand
        .iter()
        .filter(|(d, _)| *d <= reach)
        .take(4)
        .map(|(d, k)| (*k, (-d * d / (2.0 * soft * soft)).exp().max(0.02)))
        .collect();
    if out.is_empty() {
        if let Some((_, k)) = cand.first() {
            out.push((*k, 1.0));
        }
    }
    out
}

const GRIP_BINS: usize = 40;

/// One viscous moulding step: damped Gauss-Newton against the true packed
/// runtime, minimum-motion toward the step start, brush-weighted stiffness.
fn solve_grip(req: SolveReq) -> SolveResp {
    let mut sections = req.sections;
    let recruited = recruit_in(&sections, req.f_center, req.sigma, req.corner);
    let stages: Vec<usize> = recruited.iter().map(|(k, _)| *k).collect();
    let grip_w: Vec<f32> = recruited.iter().map(|(_, w)| *w).collect();
    if stages.is_empty() {
        return SolveResp {
            sections,
            stages,
            residual: 0.0,
            f_center: req.f_center,
            sigma: req.sigma,
        };
    }
    // window + Gaussian brush shape in BARK (sigma is critical-band units)
    let zc = bark_z(req.f_center);
    let half = 2.2 * req.sigma + 0.5;
    let m = GRIP_BINS;
    let wfreqs: Vec<f32> = (0..m)
        .map(|k| bark_f(zc - half + 2.0 * half * k as f32 / (m - 1) as f32))
        .collect();
    let dzc = |f: f32| bark_z(f) - zc;
    let shape: Vec<f32> = wfreqs
        .iter()
        .map(|&f| (-dzc(f).powi(2) / (2.0 * req.sigma * req.sigma)).exp())
        .collect();
    let weights = &shape;
    // one window, ~26 forward passes per step — trig leaves the loop
    let wtrig: Vec<(f64, f64)> = wfreqs.iter().map(|&f| trig_of(f)).collect();

    let cur0 = eval_packed_goal_t(&sections, req.morph, req.q, &wtrig);
    let center_db = cur0[(m - 1) / 2]; // the Bark window is centered on the brush
    let step_db = ((req.finger_db - center_db) * req.follow * req.fine).clamp(-4.0, 4.0);
    let target: Vec<f32> = cur0
        .iter()
        .zip(&shape)
        .map(|(c, s)| c + step_db * s)
        .collect();

    let n = stages.len() * 3;
    const EPS: [f32; 3] = [0.02, 0.05, 0.25];
    const LAM: [f32; 3] = [6.0, 2.0, 0.4];
    let mut p = grip_params_of(&sections, &stages, req.corner);
    let p0 = p.clone();
    for _ in 0..2 {
        grip_apply_to(&mut sections, &stages, &req.scope, &p);
        let cur = eval_packed_goal_t(&sections, req.morph, req.q, &wtrig);
        let mut r = vec![0.0f32; m];
        for i in 0..m {
            r[i] = weights[i] * (cur[i] - target[i]);
        }
        let mut jac = vec![0.0f32; m * n];
        for j in 0..n {
            let eps = EPS[j % 3];
            let mut pj = p.clone();
            pj[j] += eps;
            grip_apply_to(&mut sections, &stages, &req.scope, &pj);
            let cj = eval_packed_goal_t(&sections, req.morph, req.q, &wtrig);
            for i in 0..m {
                jac[i * n + j] = weights[i] * (cj[i] - cur[i]) / eps;
            }
        }
        let mut a = vec![0.0f32; n * n];
        let mut b = vec![0.0f32; n];
        for j in 0..n {
            for k in 0..n {
                let mut acc = 0.0;
                for i in 0..m {
                    acc += jac[i * n + j] * jac[i * n + k];
                }
                a[j * n + k] = acc;
            }
            let mut acc = 0.0;
            for i in 0..m {
                acc += jac[i * n + j] * r[i];
            }
            let lam = LAM[j % 3] / grip_w[j / 3].max(0.05);
            a[j * n + j] += lam * lam + 1e-3;
            b[j] = -acc - lam * lam * (p[j] - p0[j]);
        }
        if let Some(d) = solve_linear(&mut a, &mut b, n) {
            for j in 0..n {
                p[j] += d[j].clamp(-0.25, 0.25);
            }
        }
        for k in 0..stages.len() {
            p[k * 3] = p[k * 3].clamp(F_MIN.log2(), F_MAX.log2());
            p[k * 3 + 1] = p[k * 3 + 1].clamp((1.0 - RP_MAX).ln(), (1.0 - RP_MIN).ln());
            p[k * 3 + 2] = p[k * 3 + 2].clamp(GAIN_DB_MIN, GAIN_DB_MAX);
        }
    }
    grip_apply_to(&mut sections, &stages, &req.scope, &p);
    let cur = eval_packed_goal_t(&sections, req.morph, req.q, &wtrig);
    let mut rms = 0.0;
    let mut wsum = 0.0;
    for i in 0..m {
        rms += weights[i] * (cur[i] - target[i]).powi(2);
        wsum += weights[i];
    }
    SolveResp {
        sections,
        stages,
        residual: (rms / wsum.max(1e-9)).sqrt(),
        f_center: req.f_center,
        sigma: req.sigma,
    }
}

// ── goal pins: declarative targets solved through the packed runtime ─────────

#[derive(Clone, Copy, PartialEq, Eq)]
enum PinKind {
    Target,
    Anchor,
}

// the UI only places Peak pins today; the solver vocabulary keeps the rest
#[allow(dead_code)]
#[derive(Clone, Copy, PartialEq, Eq)]
enum PinShape {
    Point,
    Peak,
    Notch,
    LowShelf,
    HighShelf,
}

impl PinShape {
    fn label(self) -> &'static str {
        match self {
            Self::Point => "POINT",
            Self::Peak => "PEAK",
            Self::Notch => "NOTCH",
            Self::LowShelf => "SHELF◀",
            Self::HighShelf => "SHELF▶",
        }
    }
}

#[derive(Clone, Copy)]
struct GoalPin {
    kind: PinKind,
    shape: PinShape,
    freq_hz: f32,
    target_db: f32,
    width_bark: f32,
}

struct GoalSample {
    freq: f32,
    target_db: f32,
    weight: f32,
}

/// Sample every pin into (freq Hz, target dB, weight) bins. Point/peak/notch
/// and anchors are RELATIVE shapes: their per-bin targets are frozen against
/// `eval0` (the packed response at solve start), a Gaussian footprint pulling
/// the center toward target_db while the skirt follows the current curve.
/// Shelves are ABSOLUTE bands on one side of freq_hz. Corridor is deferred.
fn goal_samples(pins: &[GoalPin], eval0: &dyn Fn(f32) -> f32) -> Vec<GoalSample> {
    let mut out = Vec::new();
    for pin in pins {
        let f0 = pin.freq_hz.clamp(F_MIN, F_MAX);
        let kw = if pin.kind == PinKind::Anchor {
            1.5
        } else {
            1.0
        };
        match pin.shape {
            PinShape::Point => {
                out.push(GoalSample {
                    freq: f0,
                    target_db: pin.target_db,
                    weight: 2.0 * kw,
                });
            }
            PinShape::Peak | PinShape::Notch => {
                // Gaussian footprint in BARK: the pin is an audible feature
                // (a critical-band-wide region), not a mathematically thin spike
                let sigma = pin.width_bark.max(0.25);
                let nb = (5 + (sigma * 3.0) as usize).clamp(5, 13);
                let step = pin.target_db - eval0(f0);
                let z0 = bark_z(f0);
                for k in 0..nb {
                    let dz = -2.0 * sigma + 4.0 * sigma * k as f32 / (nb - 1) as f32;
                    let f = bark_f(z0 + dz);
                    let g = (-dz * dz / (2.0 * sigma * sigma)).exp();
                    out.push(GoalSample {
                        freq: f,
                        target_db: eval0(f) + step * g,
                        weight: g.max(0.05) * kw,
                    });
                }
            }
            PinShape::LowShelf | PinShape::HighShelf => {
                let (lo, hi) = if pin.shape == PinShape::LowShelf {
                    (F_MIN, f0.max(F_MIN * 1.01))
                } else {
                    (f0.min(F_MAX * 0.99), F_MAX)
                };
                let nb = 9;
                let (zlo, zhi) = (bark_z(lo), bark_z(hi));
                for k in 0..nb {
                    let f = bark_f(zlo + (zhi - zlo) * k as f32 / (nb - 1) as f32);
                    out.push(GoalSample {
                        freq: f,
                        target_db: pin.target_db,
                        weight: 0.6 * kw,
                    });
                }
            }
        }
    }
    out
}

/// THE goal loss: weighted RMS of (current dB − target dB) over the pin
/// samples. Samples are laid out in BARK, so this is a PERCEPTUAL residual —
/// equal weight per critical band, not per Hz or per octave. `eval` must come
/// from the packed runtime (pack_body → word lerp → cascade_db) — never
/// direct continuous params.
fn residual_goal_packed(samples: &[GoalSample], eval: &dyn Fn(f32) -> f32) -> f32 {
    let mut acc = 0.0f32;
    let mut wsum = 0.0f32;
    for s in samples {
        let r = s.weight * (eval(s.freq) - s.target_db);
        acc += r * r;
        wsum += s.weight * s.weight;
    }
    (acc / wsum.max(1e-9)).sqrt()
}

/// Packed evaluator for a candidate section set at one (morph, q).
fn packed_eval_of(sections: &[Section], morph: f32, q: f32) -> impl Fn(f32) -> f32 {
    let body = trench_core::compiler::pack_body(&params168_of(sections));
    let stages = live_biquads(&words_of(&body), morph, q);
    move |f: f32| cascade_db(&stages, f)
}

struct OptReq {
    sections: Vec<Section>,
    pins: Vec<GoalPin>,
    scope: Vec<usize>,
    selected_stage: usize,
    morph: f32,
    q: f32,
    corner: usize,
    allow_zero_freq: bool,
    allow_zero_radius: bool,
    /// true while a pin is being dragged: 2 light iterations with small step
    /// clamps so the curve FLOWS toward the pin (viscous, like the grip);
    /// false = the full polish solve on release / placement.
    fast: bool,
}

struct OptResp {
    sections: Vec<Section>,
    stages: Vec<usize>,
    accepted: bool,
    before: f32,
    after: f32,
    message: String,
}

/// Recruit unlocked enabled stages whose pole OR zero frequency falls within
/// max(pin.width_bark, 1.0) BARK of the pin (anchors reach twice as wide to
/// protect the existing response). Selected stage is always recruited when
/// legal. Capped at 4 stages. Locked sections never enter the vector.
fn recruit_goal(
    sections: &[Section],
    pins: &[GoalPin],
    corner: usize,
    selected: usize,
) -> Vec<usize> {
    let mut stages: Vec<usize> = Vec::new();
    if sections[selected].on && !sections[selected].locked {
        stages.push(selected);
    }
    let mut cand: Vec<(f32, usize)> = Vec::new();
    for (k, s) in sections.iter().enumerate() {
        if !s.on || s.locked || stages.contains(&k) {
            continue;
        }
        let c = s.corners[corner];
        let mut best = f32::INFINITY;
        for pin in pins {
            let reach = pin.width_bark.max(1.0)
                * if pin.kind == PinKind::Anchor {
                    2.0
                } else {
                    1.0
                };
            let zp = bark_z(pin.freq_hz);
            let dp = (bark_z(c.pole_hz) - zp).abs();
            let dz = (bark_z(c.zero_hz) - zp).abs();
            let d = dp.min(dz);
            if d <= reach {
                best = best.min(d);
            }
        }
        if best.is_finite() {
            cand.push((best, k));
        }
    }
    cand.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
    for (_, k) in cand {
        if stages.len() >= 4 {
            break;
        }
        stages.push(k);
    }
    stages
}

/// Apply the goal parameter vector as DELTAS from the solve-start state, to
/// every corner in scope: log2 pole Hz, ln(1−r) pole radius, gain dB, then
/// (when enabled) log2 zero Hz and ln(1−r) zero radius. Delta form preserves
/// each corner's own values, so frame/all scope keeps morph and Q travel.
fn goal_apply(
    sections: &mut [Section],
    start: &[Section],
    stages: &[usize],
    scope: &[usize],
    zf: bool,
    zr: bool,
    p: &[f32],
) {
    let stride = 3 + zf as usize + zr as usize;
    for (k, &s) in stages.iter().enumerate() {
        let d = &p[k * stride..(k + 1) * stride];
        for &ci in scope {
            let s0 = start[s].corners[ci];
            let c = &mut sections[s].corners[ci];
            c.pole_hz = (s0.pole_hz * 2f32.powf(d[0])).clamp(F_MIN, F_MAX);
            c.pole_r = (1.0 - (1.0 - s0.pole_r) * d[1].exp()).clamp(RP_MIN, RP_MAX);
            c.gain_db = (s0.gain_db + d[2]).clamp(GAIN_DB_MIN, GAIN_DB_MAX);
            let mut j = 3;
            if zf {
                c.zero_hz = (s0.zero_hz * 2f32.powf(d[j])).clamp(F_MIN, F_MAX);
                j += 1;
            }
            if zr {
                c.zero_r = (1.0 - (1.0 - s0.zero_r) * d[j].exp()).clamp(0.0, RZ_MAX);
            }
        }
    }
}

/// Residual vector + scalar cost for a candidate, all through the packed
/// runtime. Appends one soft penalty row for excessive max |H|. None when the
/// candidate evaluates non-finite anywhere (treated as worse by backtracking).
fn goal_residual_vec(
    sections: &[Section],
    morph: f32,
    q: f32,
    samples: &[GoalSample],
) -> Option<(Vec<f32>, f32, f32)> {
    let eval = packed_eval_of(sections, morph, q);
    let mut r = Vec::with_capacity(samples.len() + 1);
    for s in samples {
        let e = eval(s.freq);
        if !e.is_finite() {
            return None;
        }
        r.push(s.weight * (e - s.target_db));
    }
    let (zlo, zhi) = (bark_z(F_MIN), bark_z(F_MAX));
    let mut mx = f32::NEG_INFINITY;
    for b in 0..48 {
        mx = mx.max(eval(bark_f(zlo + (zhi - zlo) * b as f32 / 47.0)));
    }
    if !mx.is_finite() {
        return None;
    }
    r.push(0.4 * (mx - 54.0).max(0.0));
    let cost = r.iter().map(|x| x * x).sum();
    let rms = residual_goal_packed(samples, &eval);
    Some((r, cost, rms))
}

/// Surgical goal solve: damped Gauss-Newton on the recruited stages against
/// the packed runtime, minimum-motion (Tikhonov toward the start state) with
/// per-parameter stiffness — frequency motion expensive, radius medium, gain
/// cheap, zero motion most expensive and only present when enabled.
/// Accept only on meaningful residual improvement AND a stable candidate;
/// otherwise the ORIGINAL sections come back with accepted = false.
fn solve_goal(req: OptReq) -> OptResp {
    let original = req.sections.clone();
    let reject = |message: String, before: f32, after: f32| OptResp {
        sections: original.clone(),
        stages: Vec::new(),
        accepted: false,
        before,
        after,
        message,
    };
    if req.pins.is_empty() {
        return reject("no goal pins".into(), 0.0, 0.0);
    }
    let stages = recruit_goal(&req.sections, &req.pins, req.corner, req.selected_stage);
    if stages.is_empty() {
        return reject(
            "no unlocked enabled stage near any target (and selected stage is locked or off)"
                .into(),
            0.0,
            0.0,
        );
    }
    let samples = {
        let eval0 = packed_eval_of(&req.sections, req.morph, req.q);
        goal_samples(&req.pins, &eval0)
    };
    let before = {
        let eval0 = packed_eval_of(&req.sections, req.morph, req.q);
        residual_goal_packed(&samples, &eval0)
    };

    let (zf, zr) = (req.allow_zero_freq, req.allow_zero_radius);
    let stride = 3 + zf as usize + zr as usize;
    let n = stages.len() * stride;
    let mut slot_lam = vec![6.0f32, 2.5, 0.7];
    let mut slot_eps = vec![0.02f32, 0.05, 0.25];
    if zf {
        slot_lam.push(8.0);
        slot_eps.push(0.02);
    }
    if zr {
        slot_lam.push(4.0);
        slot_eps.push(0.05);
    }

    let start = req.sections.clone();
    let mut sections = req.sections;
    let mut p = vec![0.0f32; n];
    let mut cost_now = match goal_residual_vec(&sections, req.morph, req.q, &samples) {
        Some((_, cost, _)) => cost,
        None => {
            return reject(
                "current state evaluates non-finite — fix the body first".into(),
                before,
                before,
            )
        }
    };

    let (iters, step_clamp) = if req.fast { (2, 0.12f32) } else { (10, 0.3f32) };
    for _ in 0..iters {
        goal_apply(&mut sections, &start, &stages, &req.scope, zf, zr, &p);
        let Some((r, _, _)) = goal_residual_vec(&sections, req.morph, req.q, &samples) else {
            break;
        };
        let m = r.len();
        let mut jac = vec![0.0f32; m * n];
        for j in 0..n {
            let eps = slot_eps[j % stride];
            let mut pj = p.clone();
            pj[j] += eps;
            goal_apply(&mut sections, &start, &stages, &req.scope, zf, zr, &pj);
            let Some((rj, _, _)) = goal_residual_vec(&sections, req.morph, req.q, &samples) else {
                continue;
            };
            for i in 0..m {
                jac[i * n + j] = (rj[i] - r[i]) / eps;
            }
        }
        let mut a = vec![0.0f32; n * n];
        let mut b = vec![0.0f32; n];
        for j in 0..n {
            for k in 0..n {
                let mut acc = 0.0;
                for i in 0..m {
                    acc += jac[i * n + j] * jac[i * n + k];
                }
                a[j * n + k] = acc;
            }
            let mut acc = 0.0;
            for i in 0..m {
                acc += jac[i * n + j] * r[i];
            }
            let lam = slot_lam[j % stride];
            a[j * n + j] += lam * lam + 1e-3;
            b[j] = -acc - lam * lam * p[j]; // minimum motion: pull deltas toward 0
        }
        let Some(d) = solve_linear(&mut a, &mut b, n) else {
            break;
        };
        // backtracking damping: shrink the step until the cost improves
        let mut t = 1.0f32;
        let mut improved = false;
        for _ in 0..4 {
            let mut pt = p.clone();
            for j in 0..n {
                pt[j] += (d[j] * t).clamp(-step_clamp, step_clamp);
            }
            goal_apply(&mut sections, &start, &stages, &req.scope, zf, zr, &pt);
            if let Some((_, cost_t, _)) = goal_residual_vec(&sections, req.morph, req.q, &samples) {
                if cost_t < cost_now {
                    p = pt;
                    cost_now = cost_t;
                    improved = true;
                    break;
                }
            }
            t *= 0.4;
        }
        if !improved {
            break;
        }
    }

    goal_apply(&mut sections, &start, &stages, &req.scope, zf, zr, &p);
    let Some((_, _, after)) = goal_residual_vec(&sections, req.morph, req.q, &samples) else {
        return reject(
            "candidate evaluates non-finite — rejected".into(),
            before,
            before,
        );
    };

    // stability audit through the packed words at all four corners + here
    let body = trench_core::compiler::pack_body(&params168_of(&sections));
    let words = words_of(&body);
    for (m, q) in [
        (0.0, 0.0),
        (1.0, 0.0),
        (0.0, 1.0),
        (1.0, 1.0),
        (req.morph, req.q),
    ] {
        let live = live_biquads(&words, m, q);
        let r = stages_max_pole_radius(&live);
        if !(r < 1.0) {
            return reject(
                format!(
                    "unstable candidate (pole reached the edge at M{:.0} Q{:.0}) — rejected",
                    m * 100.0,
                    q * 100.0
                ),
                before,
                after,
            );
        }
    }

    // while dragging, accept any improvement at all — smooth following beats
    // ceremony; the release solve applies the meaningful-improvement bar
    let tol = if req.fast {
        0.0
    } else {
        0.02f32.max(before * 0.02)
    };
    if after >= before - tol {
        return reject(
            format!(
                "no meaningful improvement: residual {before:.2} → {after:.2} dB (kept original)"
            ),
            before,
            after,
        );
    }
    OptResp {
        sections,
        stages,
        accepted: true,
        before,
        after,
        message: String::new(),
    }
}

fn compute_heat(words: &[[[u16; 5]; STAGES]; CORNERS], q: f32) -> Vec<Color32> {
    let mut pixels = Vec::with_capacity(HEAT_W * HEAT_H);
    let trig = grid_trig(HEAT_W);
    for y in 0..HEAT_H {
        let morph = 1.0 - y as f32 / (HEAT_H - 1) as f32;
        let stages = live_biquads(words, morph, q);
        for x in 0..HEAT_W {
            pixels.push(heat_color(cascade_db_c(&stages, trig[x].0, trig[x].1)));
        }
    }
    pixels
}

fn compute_audit(words: &[[[u16; 5]; STAGES]; CORNERS]) -> (Vec<f32>, f32, usize, Vec<Color32>) {
    let mut levels = vec![f32::NAN; AUDIT_N * AUDIT_N];
    let mut maxr = 0.0f32;
    let mut unstable = 0;
    for j in 0..AUDIT_N {
        let q = j as f32 / (AUDIT_N - 1) as f32;
        for i in 0..AUDIT_N {
            let m = i as f32 / (AUDIT_N - 1) as f32;
            let stages = live_biquads(words, m, q);
            let trig = grid_trig(AUDIT_BINS);
            let mut mx = f32::NEG_INFINITY;
            for b in 0..AUDIT_BINS {
                mx = mx.max(cascade_db_c(&stages, trig[b].0, trig[b].1));
            }
            levels[j * AUDIT_N + i] = mx;
            let r = stages_max_pole_radius(&stages);
            if !(r < 1.0) {
                unstable += 1;
            }
            maxr = maxr.max(r);
        }
    }
    let mut pixels = Vec::with_capacity(AUDIT_N * AUDIT_N);
    for j in (0..AUDIT_N).rev() {
        for i in 0..AUDIT_N {
            let k = j * AUDIT_N + i;
            let stable = levels[k].is_finite();
            pixels.push(if stable { heat_color(levels[k]) } else { FAULT });
        }
    }
    (levels, maxr, unstable, pixels)
}

fn start_audio(body: [u8; 240], morph: f64, q: f64, src: AudioSrc) -> Result<AudioHandle, String> {
    use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
    let host = cpal::default_host();
    let device = host
        .default_output_device()
        .ok_or("no audio output device")?;
    let config = device.default_output_config().map_err(|e| e.to_string())?;
    let sr = config.sample_rate().0 as f64;
    let channels = config.channels() as usize;

    let cart = trench_core::cartridge::Cartridge::from_body_bytes("forge", &body, 1.0)
        .map_err(|e| format!("cartridge: {e}"))?;
    let ctl = Arc::new(Mutex::new(AudioCtl {
        playing: true,
        morph,
        q,
        src,
        pending_cart: Some(cart),
    }));
    let ctl_cb = ctl.clone();

    let mut engine = trench_core::engine::FilterEngine::new();
    engine.prepare(sr);
    let mut source = SourceState {
        rng: 0x1234_5678,
        phase: [0.0; 4],
    };
    let mut left = vec![0.0f32; 256];
    let mut right = vec![0.0f32; 256];

    let stream = device
        .build_output_stream(
            &config.into(),
            move |data: &mut [f32], _| {
                let (playing, morph, q, src, cart) = {
                    let mut c = ctl_cb.lock().unwrap();
                    (c.playing, c.morph, c.q, c.src, c.pending_cart.take())
                };
                if let Some(cart) = cart {
                    engine.load_cartridge(cart);
                }
                if !playing {
                    data.fill(0.0);
                    return;
                }
                let frames = data.len() / channels;
                let mut done = 0;
                while done < frames {
                    let n = (frames - done).min(256);
                    source.fill(src, sr as f32, &mut left[..n]);
                    right[..n].copy_from_slice(&left[..n]);
                    engine.process_block(&mut left[..n], &mut right[..n], morph, q);
                    for i in 0..n {
                        let base = (done + i) * channels;
                        data[base] = left[i];
                        if channels > 1 {
                            data[base + 1] = right[i];
                        }
                        for ch in 2..channels {
                            data[base + ch] = 0.0;
                        }
                    }
                    done += n;
                }
            },
            |err| eprintln!("audio stream error: {err}"),
            None,
        )
        .map_err(|e| e.to_string())?;
    stream.play().map_err(|e| e.to_string())?;
    Ok(AudioHandle {
        _stream: stream,
        ctl,
    })
}

const F_MIN: f32 = 30.0;
const F_MAX: f32 = 16_000.0;
const DB_MIN: f32 = -36.0;
const DB_MAX: f32 = 48.0;
const FREQ_BINS: usize = 480;
const HEAT_W: usize = 320;
const HEAT_H: usize = 130;
const AUDIT_N: usize = 17;
const AUDIT_BINS: usize = 96;
const STAGES: usize = 6;
const CORNERS: usize = 4;
const SR: f32 = 39_062.5;

const RP_MIN: f32 = 0.5;
const RP_MAX: f32 = 0.9992;
const RZ_MAX: f32 = 0.9995;
const GAIN_DB_MIN: f32 = -26.0;
const GAIN_DB_MAX: f32 = 12.0;

// ── palette ───────────────────────────────────────────────────────────────────
// the physical_mountains mini-plot language — see painter::theme

fn section_color(index: usize) -> Color32 {
    // six sections, drawn from the corner family hues so the strip reads as
    // one instrument, not a parade
    match index {
        0 => Color32::from_rgb(230, 161, 59),
        1 => Color32::from_rgb(86, 237, 112),
        2 => Color32::from_rgb(52, 168, 158),
        3 => Color32::from_rgb(217, 84, 62),
        4 => Color32::from_rgb(255, 221, 118),
        _ => Color32::from_rgb(47, 200, 204),
    }
}

// ── enums ─────────────────────────────────────────────────────────────────────

#[derive(Clone, Copy, PartialEq, Eq)]
enum CornerKey {
    M0Q0,
    M100Q0,
    M0Q100,
    M100Q100,
}

impl CornerKey {
    const ALL: [Self; 4] = [Self::M0Q0, Self::M100Q0, Self::M0Q100, Self::M100Q100];

    fn idx(self) -> usize {
        match self {
            Self::M0Q0 => 0,
            Self::M100Q0 => 1,
            Self::M0Q100 => 2,
            Self::M100Q100 => 3,
        }
    }

    fn label(self) -> &'static str {
        match self {
            Self::M0Q0 => "M0 Q0",
            Self::M100Q0 => "M100 Q0",
            Self::M0Q100 => "M0 Q100",
            Self::M100Q100 => "M100 Q100",
        }
    }

    fn plain_label(self) -> &'static str {
        match self {
            Self::M0Q0 => "low",
            Self::M100Q0 => "high",
            Self::M0Q100 => "low + Q",
            Self::M100Q100 => "high + Q",
        }
    }

    fn code(self) -> &'static str {
        match self {
            Self::M0Q0 => "C0",
            Self::M100Q0 => "C1",
            Self::M0Q100 => "C2",
            Self::M100Q100 => "C3",
        }
    }

    fn morph_q(self) -> (f32, f32) {
        match self {
            Self::M0Q0 => (0.0, 0.0),
            Self::M100Q0 => (1.0, 0.0),
            Self::M0Q100 => (0.0, 1.0),
            Self::M100Q100 => (1.0, 1.0),
        }
    }

    /// the other morph frame, same Q row — the travel partner
    fn morph_mirror(self) -> CornerKey {
        match self {
            CornerKey::M0Q0 => CornerKey::M100Q0,
            CornerKey::M100Q0 => CornerKey::M0Q0,
            CornerKey::M0Q100 => CornerKey::M100Q100,
            CornerKey::M100Q100 => CornerKey::M0Q100,
        }
    }

    /// the other Q row, same morph frame
    fn q_mirror(self) -> CornerKey {
        match self {
            CornerKey::M0Q0 => CornerKey::M0Q100,
            CornerKey::M0Q100 => CornerKey::M0Q0,
            CornerKey::M100Q0 => CornerKey::M100Q100,
            CornerKey::M100Q100 => CornerKey::M100Q0,
        }
    }

    fn scope_corners(self, scope: EditScope) -> Vec<usize> {
        match scope {
            EditScope::Corner => vec![self.idx()],
            EditScope::Frame => match self {
                Self::M0Q0 | Self::M0Q100 => vec![0, 2],
                Self::M100Q0 | Self::M100Q100 => vec![1, 3],
            },
            EditScope::All => vec![0, 1, 2, 3],
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum EditScope {
    Corner,
    Frame,
    All,
}

impl EditScope {
    fn label(self) -> &'static str {
        match self {
            Self::Corner => "this corner",
            Self::Frame => "this frame",
            Self::All => "all corners",
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Quantize {
    Measured,
    Tet,
    Off,
}

impl Quantize {
    fn label(self) -> &'static str {
        match self {
            Self::Measured => "measured resonances",
            Self::Tet => "12-TET in key",
            Self::Off => "off",
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum HandleKind {
    Pole,
    Zero,
}

#[allow(dead_code)]
#[derive(Clone, Copy, PartialEq, Eq)]
enum Menu {
    Seed,
    Corners,
    Quantize,
    Scope,
    Overlay,
    View,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum ValueField {
    PoleHz,
    PoleR,
    ZeroHz,
    ZeroR,
    GainDb,
}

/// front-surface frame controls (Peak/Shelf Morph): horizontal sliders, value
/// set from the pointer's position inside the slider rect
#[derive(Clone, Copy, PartialEq, Eq)]
enum FrontSlider {
    LowFreq,
    LowShelf,
    LowPeak,
    HighFreq,
    HighShelf,
    HighPeak,
    Master,
}

// ── model ─────────────────────────────────────────────────────────────────────

#[derive(Clone, Copy, Serialize, Deserialize)]
struct CornerStage {
    pole_hz: f32,
    pole_r: f32,
    zero_hz: f32,
    zero_r: f32,
    gain_db: f32,
}

#[derive(Clone, Serialize, Deserialize)]
struct Section {
    on: bool,
    locked: bool,
    /// textbook role stamped by the seed ("chest", "F1", "p3", …) — display
    /// only, cleared on re-seed; never read by DSP
    #[serde(default)]
    role: String,
    corners: [CornerStage; CORNERS],
}

#[derive(Serialize)]
struct SaveSidecar<'a> {
    note: &'a str,
    sections: &'a [Section],
    /// present iff the body was authored by the Peak/Shelf frame controls and
    /// is still linked to them — the editable source state
    #[serde(skip_serializing_if = "Option::is_none")]
    peak_shelf_patch: Option<&'a model::peak_shelf::PeakShelfPatch>,
}

/// owned mirror of SaveSidecar for loading autosaves / baked source.json
#[derive(Deserialize)]
struct SidecarOwned {
    sections: Vec<Section>,
    #[serde(default)]
    peak_shelf_patch: Option<model::peak_shelf::PeakShelfPatch>,
}

#[derive(Deserialize)]
struct LawStageRow {
    pole_hz: f32,
    #[serde(default)]
    pole_r: Option<f32>,
    #[serde(default)]
    pole_radius: Option<f32>,
    zero_hz: f32,
    #[serde(default)]
    zero_r: Option<f32>,
    #[serde(default)]
    zero_radius: Option<f32>,
    #[serde(default)]
    gain: Option<f32>,
    #[serde(default)]
    gain_db: Option<f32>,
    #[serde(default)]
    role: Option<String>,
}

fn load_law_stage_sections(path: &str) -> Result<Vec<Section>, String> {
    let text = fs::read_to_string(repo_root().join(path)).map_err(|e| e.to_string())?;
    let map: HashMap<String, Vec<LawStageRow>> =
        serde_json::from_str(&text).map_err(|e| e.to_string())?;
    let keys = ["M0_S0", "M1_S0", "M0_S1", "M1_S1"];
    let mut sections = scratch_sections();
    for (ci, key) in keys.iter().enumerate() {
        let rows = map
            .get(*key)
            .ok_or_else(|| format!("missing corner rows {key}"))?;
        for (si, row) in rows.iter().take(STAGES).enumerate() {
            let sec = &mut sections[si];
            sec.on = true;
            sec.locked = false;
            if ci == 0 {
                sec.role = row.role.clone().unwrap_or_default();
            }
            let c = &mut sec.corners[ci];
            c.pole_hz = row.pole_hz.clamp(F_MIN, F_MAX);
            c.pole_r = row
                .pole_r
                .or(row.pole_radius)
                .unwrap_or(0.92)
                .clamp(RP_MIN, RP_MAX);
            c.zero_hz = row.zero_hz.clamp(F_MIN, F_MAX);
            c.zero_r = row
                .zero_r
                .or(row.zero_radius)
                .unwrap_or(0.0)
                .clamp(0.0, RZ_MAX);
            c.gain_db = row
                .gain_db
                .unwrap_or_else(|| lin_to_db(row.gain.unwrap_or(1.0)))
                .clamp(GAIN_DB_MIN, GAIN_DB_MAX);
        }
    }
    Ok(sections)
}

#[derive(Clone, Copy)]
enum Drag {
    Handle {
        stage: usize,
        kind: HandleKind,
        gain: bool,
        start_pos: Pos2,
        start: [CornerStage; CORNERS],
        /// which corner this gesture edits (the mirror corner for travel dots)
        corner: CornerKey,
    },
    Morph,
    Q,
    Front(FrontSlider),
    Value {
        field: ValueField,
        start_y: f32,
        start: [CornerStage; CORNERS],
    },
    SurfaceMap,
    SweepMap,
    Curve,
    /// hold D + drag: paint a target stroke; released, it becomes dense
    /// Bark-spaced target pins and the goal optimizer fits (SPEC item 5,
    /// draw-the-target)
    Draw,
    Pin {
        idx: usize,
    },
}

/// Outcome of the last goal optimize, for the plot overlay.
struct OptOutcome {
    stages: Vec<usize>,
    before: f32,
    after: f32,
    accepted: bool,
    at: Instant,
}

/// The display never snaps to solver output. Solves set this TARGET; every
/// frame the visible sections move toward it critically damped (the solver
/// follows the hand, the display follows the solver). Motion is always at
/// frame rate regardless of solve latency.
fn sections_close(a: &[Section], b: &[Section]) -> bool {
    a.iter().zip(b).all(|(sa, sb)| {
        sa.corners.iter().zip(&sb.corners).all(|(ca, cb)| {
            (ca.pole_hz / cb.pole_hz).log2().abs() < 0.002
                && (ca.zero_hz / cb.zero_hz).log2().abs() < 0.002
                && (ca.pole_r - cb.pole_r).abs() < 0.0005
                && (ca.zero_r - cb.zero_r).abs() < 0.0005
                && (ca.gain_db - cb.gain_db).abs() < 0.02
        })
    })
}

fn lerp_sections(a: &[Section], b: &[Section], t: f32) -> Vec<Section> {
    let lerp_r =
        |ra: f32, rb: f32| 1.0 - (1.0 - ra).max(1e-6).powf(1.0 - t) * (1.0 - rb).max(1e-6).powf(t);
    a.iter()
        .zip(b)
        .map(|(sa, sb)| {
            let mut s = sb.clone();
            for ci in 0..CORNERS {
                let ca = sa.corners[ci];
                let c = &mut s.corners[ci];
                c.pole_hz = ca.pole_hz * (c.pole_hz / ca.pole_hz).powf(t);
                c.zero_hz = ca.zero_hz * (c.zero_hz / ca.zero_hz).powf(t);
                c.pole_r = lerp_r(ca.pole_r, c.pole_r);
                c.zero_r = lerp_r(ca.zero_r, c.zero_r);
                c.gain_db = ca.gain_db + (c.gain_db - ca.gain_db) * t;
            }
            s
        })
        .collect()
}

/// State of a combined-curve grab — the pottery grip. Viscous: every frame the
/// material under the brush takes a small step toward the finger from where it
/// is NOW (no frozen grab-time target, no spring-back). Sections are recruited
/// under the brush each frame. Evaluated through the TRUE packed runtime
/// (pack_body → word lerp → |H|), never a continuous surrogate.
struct CurveGrip {
    plot: Rect,
    residual_rms: f32,
}

struct Tables {
    resonances: Vec<f32>,
    vowels: Vec<(String, f32, f32, f32, f32, f32, f32)>,
    metal_ratios: Vec<f32>,
    skeletons: Vec<SkeletonSeed>,
    skeleton_verification_loaded: bool,
}

/// closed-form optimal filter skeleton (tables/exact_skeletons.json, computed
/// by tools/make_exact_skeletons.py — formulas as provenance, level-trimmed
/// and self-checked against the unprojected reference)
#[derive(Clone, Deserialize)]
struct SkeletonSeed {
    #[allow(dead_code)]
    key: String,
    label: String,
    f_lo: f32,
    f_hi: f32,
    sections: Vec<SkeletonSection>,
    #[serde(default)]
    verified: bool,
    #[serde(default)]
    verify_note: String,
}

#[derive(Clone, Copy, Deserialize)]
struct SkeletonSection {
    pole_hz_lo: f32,
    pole_r_lo: f32,
    zero_hz_lo: f32,
    zero_r_lo: f32,
    gain_db_lo: f32,
    pole_hz_hi: f32,
    pole_r_hi: f32,
    zero_hz_hi: f32,
    zero_r_hi: f32,
    gain_db_hi: f32,
}

/// One executed menu action (id strings keep the hit-test table flat).
#[derive(Clone, Copy, PartialEq, Eq)]
enum MenuAction {
    SeedPeakShelf,
    /// a START manifest row: (lane index, row index)
    StartRow(usize, usize),
    SeedDefault,
    SeedLowpass,
    SeedHighpass,
    SeedBandpass,
    SeedNotchComb,
    SeedParametric,
    SeedPeaks,
    SeedVowel(usize),
    SeedTube(usize),
    SeedMetal(usize),
    SeedExact(usize),
    SeedScratch,
    RestoreAutosave,
    CopyCornerAll,
    DeriveQ,
    QuantSet(Quantize),
    KeySet(usize),
    ScopeSet(EditScope),
    OverlaySet(Option<usize>),
    ToggleGhosts,
    ToggleBark,
}

#[derive(Clone, PartialEq)]
#[allow(dead_code)] // shape previews remain for non-manifest rows
enum StartPreview {
    None,
    Flat,
    Lowpass,
    Highpass,
    Bandpass,
    Notch,
    Peak,
    Peaks,
    Vowel,
    Modal,
    Body(String),
    Curves(String),
    Exact(usize),
}

struct StartEntry {
    label: String,
    note: String,
    action: Option<MenuAction>,
    preview: StartPreview,
    /// provenance badge: COMPILE EXACT · IMPORT EXACT · OVERLAY · APPROX
    badge: Option<&'static str>,
    /// quarantine rows: visible with their reason, never actionable
    quarantined: bool,
}

const VOWEL_PAIRS: [(&str, &str, &str); 4] = [
    ("aa", "iy", "vowel  ah > ee"),
    ("uw", "iy", "vowel  oo > ee"),
    ("aa", "uw", "vowel  ah > oo"),
    ("ae", "uh", "vowel  a > u"),
];
const TUBE_F0: [f32; 3] = [55.0, 110.0, 220.0];
const METAL_F0: [f32; 3] = [110.0, 220.0, 440.0];
const NOTES: [&str; 12] = [
    "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
];

// ── app state ─────────────────────────────────────────────────────────────────

struct App {
    sections: Vec<Section>,
    selected_stage: usize,
    selected_corner: CornerKey,
    scope: EditScope,
    quantize: Quantize,
    key_root: usize,
    morph: f32,
    q: f32,
    sweep: bool,
    sweep_t0: Instant,
    body: [u8; 240],
    response: Vec<f32>,
    ghost_low: Vec<f32>,
    ghost_high: Vec<f32>,
    stage_db: [[f32; FREQ_BINS]; STAGES],
    heat_texture: Option<TextureHandle>,
    heat_dirty: bool,
    show_ghosts: bool,
    bark: bool,
    overlay_vowel: Option<usize>,
    show_rail: bool,
    audit_levels: [f32; AUDIT_N * AUDIT_N],
    audit_maxr: f32,
    audit_unstable: usize,
    audit_dirty: bool,
    audit_texture: Option<TextureHandle>,
    audio: Option<AudioHandle>,
    playing: bool,
    audio_src: AudioSrc,
    brush_bark: f32, // curve-grip / pin brush half-width (Gaussian σ, BARK)
    pins: Vec<GoalPin>,
    selected_pin: Option<usize>,
    optimize_inflight: bool,
    last_opt: Option<OptOutcome>,
    solve_target: Option<Vec<Section>>,
    last_frame: Instant,
    frame_ms_avg: f32,   // EMA of frame-to-frame time — the jank meter
    frame_ms_peak: f32,  // decaying max, catches hitches the average hides
    metered_frame: bool, // last frame requested an immediate repaint → meter the gap
    hint: Option<(String, Pos2, Instant)>, // refusal/help text at the cursor, short-lived
    gpu_plot: bool,      // custom WGSL plot pipeline registered (egui fallback if false)
    qcompare: Option<Vec<f32>>, // hold C: the opposite-Q cascade (desk-sheet view)
    boot_qcompare: bool, // validation flag: hold the Q-compare overlay on
    draw_stroke: Option<Vec<(f32, f32)>>, // (freq, dB) points while painting a target (hold D)
    show_help: bool,     // hold H: the controls card
    boot_help: bool,     // validation flag: hold the card open
    autosaved_at: Instant, // last autosave write; sections re-save 30 s after an edit
    /// frames are the working unit: while linked, Q100 corners derive from the
    /// Q0 rows (pole radius toward the rim, zeros held — the measured Tier-2
    /// rule). Editing a Q100 corner directly breaks the link (deliberate act).
    q_link: bool,
    /// the Peak/Shelf Morph front surface: LOW/HIGH frame × FREQ/SHELF/PEAK
    /// + MASTER. While linked, the patch compiler owns all four corners; any
    /// direct section edit detaches (push_undo is the chokepoint).
    patch: model::peak_shelf::PeakShelfPatch,
    patch_linked: bool,
    job_tx: std::sync::mpsc::Sender<Job>,
    resp_rx: std::sync::mpsc::Receiver<Resp>,
    solve_inflight: bool,
    heat_inflight: bool,
    audit_inflight: bool,
    table_gen_idx: usize,
    hand: Option<(f32, f32, f32)>, // (f_center, finger_db, fine) — latest moulding hand state
    last_dispatch: Instant,
    drag: Option<Drag>,
    curve_grip: Option<CurveGrip>,
    hover: Option<Pos2>,
    open_menu: Option<Menu>,
    menu_opened_at: Option<Instant>,
    name_active: bool,
    body_name: String,
    undo: Vec<Vec<Section>>,
    redo: Vec<Vec<Section>>,
    tables: Tables,
    /// the START manifest: four provenance lanes (COMPILE EXACT · IMPORT
    /// EXACT · OVERLAY · APPROX) + quarantine, built by
    /// tools/build_forge_start_manifest.py
    start_manifest: Option<sources::manifest::StartManifest>,
    source_bodies: HashMap<String, [u8; 240]>,
    overlay_curves: HashMap<String, sources::manifest::OverlayCurves>,
    /// spectral centroid (Hz, at M0 Q0) per body/curves path — the START
    /// list sorts every lane low → high by this
    centroids: HashMap<String, f32>,
    /// active reference overlay (curves path) drawn on the hero plot
    overlay_ref: Option<String>,
    /// a packed body seeded verbatim for listening/plotting — sections do not
    /// describe it; any edit recompiles from sections and drops the preview
    packed_preview: Option<String>,
    status: String,
    last_edit: Instant,
}

fn main() -> eframe::Result {
    if std::env::args().any(|arg| arg == "--patch-test") {
        use model::peak_shelf::{compile_peak_shelf, shelf_weights, PeakShelfPatch};
        // 1 · SHELF crossfade partitions to exactly 1 across the domain
        let mut worst = 0.0f32;
        for i in -64..=63 {
            let (a, b, c) = shelf_weights(i as f32);
            worst = worst.max((a + b + c - 1.0).abs());
        }
        println!("patch-test weights: partition error {worst:.6} (must be 0)");
        assert!(worst < 1e-5, "shelf weights must partition to 1");

        // 2 · raising FREQ never moves any lane's pole down (monotone map)
        let mut prev: Option<Vec<f32>> = None;
        let mut monotone = true;
        for f in [60.0f32, 120.0, 320.0, 800.0, 2400.0, 6000.0, 12000.0] {
            let mut p = PeakShelfPatch::default();
            p.low.freq_hz = f;
            let poles: Vec<f32> = compile_peak_shelf(&p)
                .iter()
                .map(|s| s.corners[0].pole_hz)
                .collect();
            if let Some(prev) = &prev {
                monotone &= poles.iter().zip(prev).all(|(now, was)| now >= was);
            }
            prev = Some(poles);
        }
        println!("patch-test monotone: pole Hz nondecreasing in FREQ = {monotone}");
        assert!(monotone, "freq map must be monotone");

        // 3 · format limits hold pre-pack at the extremes
        let mut extreme = PeakShelfPatch::default();
        extreme.low.peak_db = 12.0;
        extreme.high.peak_db = 12.0;
        extreme.pressure = 1.0;
        let sections = compile_peak_shelf(&extreme);
        let mut r_ok = true;
        for s in &sections {
            for c in &s.corners {
                r_ok &= c.pole_r <= RP_MAX && c.zero_r <= RZ_MAX;
                r_ok &= (F_MIN..=F_MAX).contains(&c.pole_hz);
            }
        }
        println!("patch-test limits: pole r ≤ {RP_MAX}, zero r ≤ {RZ_MAX}, Hz in range = {r_ok}");
        assert!(r_ok, "format limits must hold pre-pack");

        // 4 · golden patch packs to a byte-stable body (regression pin)
        let golden = PeakShelfPatch::default();
        let body = trench_core::compiler::pack_body(&params168_of(&compile_peak_shelf(&golden)));
        let sha = {
            use sha2::{Digest, Sha256};
            let mut h = Sha256::new();
            h.update(body);
            format!("{:x}", h.finalize())
        };
        println!("patch-test golden body240 sha256 = {sha}");
        // regression pin: the default patch must keep packing to these bytes;
        // re-pin deliberately when the lane constants are re-tuned by ear
        // re-pinned 2026-06-11: default patch pressure 0.35 → 1.0 (full baked
        // Q contrast; the runtime PRESSURE axis sweeps into it)
        const GOLDEN_SHA: &str = "f7da8138776eb1c959ffc1d5a0233bce56050940808ced394550095c31cca4ca";
        assert_eq!(sha, GOLDEN_SHA, "golden patch body240 drifted");

        // 5 · the extreme patch is AUDITED, never silently rescued — report
        // the 17×17 packed verdict for pressure 1, peak +12
        let (_, maxr, unstable, _) = compute_audit(&words_of(&body));
        let (_, maxr_x, unstable_x, _) = compute_audit(&words_of(
            &trench_core::compiler::pack_body(&params168_of(&sections)),
        ));
        println!(
            "patch-test audit: golden max pole r {maxr:.6}, unstable cells {unstable} · extreme max pole r {maxr_x:.6}, unstable cells {unstable_x}"
        );
        println!("patch-test: OK");
        return Ok(());
    }
    if std::env::args().any(|arg| arg == "--inventory-test") {
        let root = repo_root();
        let Some(manifest) = sources::manifest::load(&root) else {
            println!(
                "inventory-test: FAILED — no manifest at {} (run tools/build_forge_start_manifest.py)",
                sources::manifest::MANIFEST_PATH
            );
            std::process::exit(1);
        };
        let bodies = sources::manifest::load_bodies(&root, &manifest);
        let overlays = sources::manifest::load_overlays(&root, &manifest);
        let mut missing = 0;
        for lane in &manifest.lanes {
            let body_refs = lane.rows.iter().filter(|r| r.body.is_some()).count();
            let loaded = lane
                .rows
                .iter()
                .filter(|r| r.body.as_ref().map_or(false, |p| bodies.contains_key(p)))
                .count();
            missing += body_refs - loaded;
            println!(
                "inventory-test: {} [{}] rows {} · bodies {}/{}",
                lane.id,
                lane.badge,
                lane.rows.len(),
                loaded,
                body_refs,
            );
        }
        println!(
            "inventory-test: overlays loaded {} · quarantine {} rows",
            overlays.len(),
            manifest.quarantine.len()
        );
        assert_eq!(manifest.lanes.len(), 4, "expected four provenance lanes");
        assert_eq!(missing, 0, "every referenced .body240 must load");
        assert!(!manifest.quarantine.is_empty(), "quarantine must be visible");
        println!("inventory-test: OK");
        return Ok(());
    }
    if std::env::args().any(|arg| arg == "--bake-once") {
        let mut app = App::default_state();
        app.bake();
        println!("{}", app.status);
        return Ok(());
    }
    if std::env::args().any(|arg| arg == "--goal-test") {
        // headless proof of the goal optimizer: a peak target +10 dB above the
        // current packed response at 1 kHz, solved through solve_goal.
        let app = App::default_state();
        let eval0 = packed_eval_of(&app.sections, 0.0, 0.0);
        let base = eval0(1000.0);
        drop(eval0);
        let pins = vec![GoalPin {
            kind: PinKind::Target,
            shape: PinShape::Peak,
            freq_hz: 1000.0,
            target_db: base + 10.0,
            width_bark: 1.0,
        }];
        let resp = solve_goal(OptReq {
            sections: app.sections.clone(),
            pins,
            scope: vec![0],
            selected_stage: 1,
            morph: 0.0,
            q: 0.0,
            corner: 0,
            allow_zero_freq: false,
            allow_zero_radius: false,
            fast: false,
        });
        let stages: Vec<String> = resp.stages.iter().map(|s| format!("S{}", s + 1)).collect();
        println!(
            "goal-test: accepted={} residual {:.3} → {:.3} dB on {} {}",
            resp.accepted,
            resp.before,
            resp.after,
            stages.join("+"),
            resp.message,
        );
        // locked stages must never move: lock everything and expect a reject
        let mut locked = app.sections.clone();
        for s in &mut locked {
            s.locked = true;
        }
        let resp2 = solve_goal(OptReq {
            sections: locked,
            pins: vec![GoalPin {
                kind: PinKind::Target,
                shape: PinShape::Point,
                freq_hz: 1000.0,
                target_db: base + 10.0,
                width_bark: 1.0,
            }],
            scope: vec![0],
            selected_stage: 1,
            morph: 0.0,
            q: 0.0,
            corner: 0,
            allow_zero_freq: false,
            allow_zero_radius: false,
            fast: false,
        });
        println!(
            "goal-test locked: accepted={} ({})",
            resp2.accepted, resp2.message
        );
        return Ok(());
    }
    if std::env::args().any(|arg| arg == "--interior-test") {
        // headless proof of the interior grip (SPEC item 4): pull the
        // interpolated middle (M45/Q30) up 6 dB at 900 Hz — the corner solver
        // must land it there through the true packed word-lerp.
        let mut app = App::default_state();
        app.seed_vowel_pair(0);
        app.rebuild_body();
        let (morph, q) = (0.45f32, 0.30f32);
        let probe = |sections: &[Section]| eval_packed_goal(sections, morph, q, &[900.0])[0];
        let base = probe(&app.sections);
        let target = base + 6.0;
        let corner = CornerKey::M0Q0; // largest interpolation weight at M45/Q30
        for _ in 0..40 {
            let resp = solve_grip(SolveReq {
                sections: app.sections.clone(),
                corner: corner.idx(),
                scope: vec![corner.idx()],
                f_center: 900.0,
                finger_db: target,
                sigma: 1.0,
                follow: 0.35,
                fine: 1.0,
                morph,
                q,
            });
            app.sections = resp.sections;
        }
        let after = probe(&app.sections);
        let moved = after - base;
        println!(
            "interior-test: 900 Hz @ M45/Q30: {:.2} → {:.2} dB (target {:.2}, moved {:+.2}) {}",
            base,
            after,
            target,
            moved,
            if moved > 4.0 { "OK" } else { "FAILED" }
        );
        return Ok(());
    }
    if std::env::args().any(|arg| arg == "--mag-test") {
        // equivalence + speed of the cos-form magnitude path vs the old
        // complex form, on a real seeded body at an interior point
        let mut app = App::default_state();
        app.seed_vowel_pair(0);
        app.rebuild_body();
        let live = live_biquads(&app.words(), 0.37, 0.42);
        // f64 complex evaluation = ground truth; arbitrate both f32 forms
        let truth = |b: [f32; 5], f: f32| -> f64 {
            let w = (TAU32 as f64) * (f as f64) / (SR as f64);
            let (c1, s1, c2, s2) = (w.cos(), w.sin(), (2.0 * w).cos(), (2.0 * w).sin());
            let (b0, b1, b2, a1, a2) = (
                b[0] as f64,
                b[1] as f64,
                b[2] as f64,
                b[3] as f64,
                b[4] as f64,
            );
            let nr = b0 + b1 * c1 + b2 * c2;
            let ni = -(b1 * s1 + b2 * s2);
            let dr = 1.0 + a1 * c1 + a2 * c2;
            let di = -(a1 * s1 + a2 * s2);
            20.0 * (nr.hypot(ni) / dr.hypot(di).max(1e-24)).max(1e-24).log10()
        };
        let (mut d_new, mut d_old) = (0.0f64, 0.0f64);
        for i in 0..FREQ_BINS {
            let f = freq_at(i, FREQ_BINS);
            let t = live.iter().map(|b| truth(*b, f)).sum::<f64>().max(-90.0);
            let new = (live.iter().map(|b| biquad_db(*b, f)).sum::<f32>() as f64).max(-90.0);
            let old = (live.iter().map(|b| biquad_db_ref(*b, f)).sum::<f32>() as f64).max(-90.0);
            d_new = d_new.max((new - t).abs());
            d_old = d_old.max((old - t).abs());
        }
        let max_d = d_new;
        let reps = 500;
        let t0 = Instant::now();
        let mut acc = 0.0f32;
        for _ in 0..reps {
            for i in 0..FREQ_BINS {
                let f = freq_at(i, FREQ_BINS);
                acc += live.iter().map(|b| biquad_db_ref(*b, f)).sum::<f32>();
            }
        }
        let old_ms = t0.elapsed().as_secs_f64() * 1000.0;
        let trig = grid_trig(FREQ_BINS);
        let t1 = Instant::now();
        for _ in 0..reps {
            for i in 0..FREQ_BINS {
                acc += cascade_db_c(&live, trig[i].0, trig[i].1);
            }
        }
        let new_ms = t1.elapsed().as_secs_f64() * 1000.0;
        println!(
            "mag-test: vs f64 truth (clamped −90 dB): new {:.6} dB · old {:.6} dB ({}) · {} reps: old {:.1} ms → new {:.1} ms ({:.1}×)  [{acc:.1}]",
            d_new,
            d_old,
            if max_d < 1e-3 { "NEW EXACT" } else { "CHECK" },
            reps,
            old_ms,
            new_ms,
            old_ms / new_ms.max(1e-9),
        );
        return Ok(());
    }
    if std::env::args().any(|arg| arg == "--keep-once") {
        // headless KEEP: stage the default body's bank bundle and report
        let mut app = App::default_state();
        app.seed_vowel_pair(0);
        app.rebuild_body();
        app.body_name = "keep_smoke".into();
        app.keep_to_staging();
        println!("{}", app.status);
        return Ok(());
    }
    if std::env::args().any(|arg| arg == "--table-gen-test") {
        let mut app = App::default_state();
        let n = app.tables.skeletons.len();
        if n == 0 {
            eprintln!("table-gen-test: no exact skeletons loaded");
            std::process::exit(2);
        }
        for _ in 0..n {
            app.generate_table_body(false);
            println!("{}", app.status);
            if app.audit_unstable > 0 {
                eprintln!("table-gen-test: {} has unstable audit cells", app.body_name);
                std::process::exit(2);
            }
        }
        return Ok(());
    }
    if std::env::args().any(|arg| arg == "--draw-test") {
        // headless draw-the-target: a painted +6 dB ridge over the scratch
        // flat becomes Bark-binned pins; the goal solver must take it.
        let mut app = App::default_state();
        let stroke: Vec<(f32, f32)> = (0..60)
            .map(|i| {
                let t = i as f32 / 59.0;
                let f = 300.0 * 8.0f32.powf(t); // 300 → 2400 Hz sweep
                let db = if (700.0..=1400.0).contains(&f) {
                    6.0
                } else {
                    0.0
                };
                (f, db)
            })
            .collect();
        app.draw_stroke = Some(stroke);
        app.drag = Some(Drag::Draw);
        app.finish_draw_stroke();
        let resp = solve_goal(OptReq {
            sections: app.sections.clone(),
            pins: app.pins.clone(),
            scope: vec![app.selected_corner.idx()],
            selected_stage: app.selected_stage,
            morph: app.morph,
            q: app.q,
            corner: app.selected_corner.idx(),
            allow_zero_freq: false,
            allow_zero_radius: false,
            fast: false,
        });
        println!(
            "draw-test: {} pins, error {:.2} → {:.2} dB, accepted={}",
            app.pins.len(),
            resp.before,
            resp.after,
            resp.accepted
        );
        return Ok(());
    }
    if std::env::args().any(|arg| arg == "--audio-test") {
        // headless proof: open the device stream, render 1 s through the
        // engine, report. Also run one block offline to check for output.
        let app = App::default_state();
        let mut engine = trench_core::engine::FilterEngine::new();
        engine.prepare(48000.0);
        let cart = trench_core::cartridge::Cartridge::from_body_bytes("t", &app.body, 1.0)
            .expect("cartridge from body");
        engine.load_cartridge(cart);
        let mut src = SourceState {
            rng: 0x1234_5678,
            phase: [0.0; 4],
        };
        let mut l = vec![0.0f32; 4096];
        let mut r = vec![0.0f32; 4096];
        src.fill(AudioSrc::Noise, 48000.0, &mut l);
        r.copy_from_slice(&l);
        engine.process_block(&mut l, &mut r, 0.5, 0.5);
        let rms = (l.iter().map(|v| v * v).sum::<f32>() / l.len() as f32).sqrt();
        println!(
            "offline block rms: {rms:.4} ({})",
            if rms > 1e-5 && rms.is_finite() {
                "OK"
            } else {
                "SILENT/BAD"
            }
        );
        match start_audio(app.body, 0.5, 0.5, AudioSrc::Noise) {
            Ok(_h) => {
                std::thread::sleep(Duration::from_millis(1200));
                println!("device stream ran 1.2 s: OK");
            }
            Err(e) => println!("device stream FAILED: {e}"),
        }
        return Ok(());
    }
    let options = eframe::NativeOptions {
        renderer: eframe::Renderer::Wgpu,
        viewport: egui::ViewportBuilder::default()
            .with_title("TRENCH FORGE — Z-plane filter designer")
            .with_inner_size([1420.0, 880.0])
            .with_min_inner_size([1020.0, 620.0]),
        ..Default::default()
    };
    eframe::run_native(
        "TRENCH FORGE",
        options,
        Box::new(|cc| Ok(Box::new(App::new(cc)))),
    )
}

// ── tables (measured values only) ─────────────────────────────────────────────

fn repo_root() -> PathBuf {
    let mut dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    for _ in 0..4 {
        if dir.join("tables").join("vowel_formants.json").exists() {
            return dir;
        }
        if !dir.pop() {
            break;
        }
    }
    PathBuf::from(".")
}

fn load_tables() -> Tables {
    let mut t = Tables {
        resonances: Vec::new(),
        vowels: Vec::new(),
        metal_ratios: Vec::new(),
        skeletons: Vec::new(),
        skeleton_verification_loaded: false,
    };
    let dir = repo_root().join("tables");
    #[derive(Deserialize)]
    struct VerificationFile {
        skeletons: Vec<VerifiedSkeleton>,
    }
    #[derive(Deserialize)]
    struct VerifiedSkeleton {
        key: String,
        verdict: String,
        passband_max_db: f32,
        body_max_db: f32,
    }
    let verification: HashMap<String, VerifiedSkeleton> =
        match fs::read_to_string(dir.join("exact_skeletons.verification.json"))
            .ok()
            .and_then(|text| serde_json::from_str::<VerificationFile>(&text).ok())
        {
            Some(file) => {
                t.skeleton_verification_loaded = true;
                file.skeletons
                    .into_iter()
                    .map(|item| (item.key.clone(), item))
                    .collect()
            }
            None => HashMap::new(),
        };
    if let Ok(text) = fs::read_to_string(dir.join("exact_skeletons.json")) {
        #[derive(Deserialize)]
        struct File {
            skeletons: Vec<SkeletonSeed>,
        }
        if let Ok(f) = serde_json::from_str::<File>(&text) {
            let verification_loaded = t.skeleton_verification_loaded;
            t.skeletons = f
                .skeletons
                .into_iter()
                .filter_map(|mut s| {
                    if s.sections.is_empty() {
                        return None;
                    }
                    if let Some(v) = verification.get(&s.key) {
                        s.verified = v.verdict == "PASS";
                        s.verify_note = format!(
                            "verified: passband {:.2} dB, body {:.2} dB",
                            v.passband_max_db, v.body_max_db
                        );
                    }
                    if verification_loaded && !s.verified {
                        return None;
                    }
                    Some(s)
                })
                .collect();
        }
    }
    if let Ok(text) = fs::read_to_string(dir.join("vowel_formants.json")) {
        if let Ok(v) = serde_json::from_str::<serde_json::Value>(&text) {
            if let Some(vowels) = v["vowels"].as_array() {
                for vw in vowels {
                    let g = |k: &str| vw[k].as_f64().unwrap_or(0.0) as f32;
                    let key = vw["key"].as_str().unwrap_or("?").to_string();
                    let (f1, f2, f3) = (g("f1"), g("f2"), g("f3"));
                    if f1 > 0.0 {
                        for f in [f1, f2, f3] {
                            if (F_MIN..=F_MAX).contains(&f) {
                                t.resonances.push(f);
                            }
                        }
                        t.vowels.push((
                            key,
                            f1,
                            f2,
                            f3,
                            g("bw1").max(40.0),
                            g("bw2").max(60.0),
                            g("bw3").max(100.0),
                        ));
                    }
                }
            }
        }
    }
    if let Ok(text) = fs::read_to_string(dir.join("metallic_modes.json")) {
        if let Ok(v) = serde_json::from_str::<serde_json::Value>(&text) {
            fn find_ratios(v: &serde_json::Value, out: &mut Vec<f32>) {
                if !out.is_empty() {
                    return;
                }
                match v {
                    serde_json::Value::Object(m) => {
                        if let Some(r) = m.get("ratios").and_then(|r| r.as_array()) {
                            for x in r {
                                if let Some(f) = x.as_f64() {
                                    out.push(f as f32);
                                }
                            }
                            return;
                        }
                        for x in m.values() {
                            find_ratios(x, out);
                        }
                    }
                    serde_json::Value::Array(a) => {
                        for x in a {
                            find_ratios(x, out);
                        }
                    }
                    _ => {}
                }
            }
            find_ratios(&v, &mut t.metal_ratios);
        }
    }
    t.resonances.sort_by(|a, b| a.partial_cmp(b).unwrap());
    t.resonances.dedup_by(|a, b| (*a - *b).abs() < 0.5);
    t
}

// ── default template ─────────────────────────────────────────────────────────

fn default_sections() -> Vec<Section> {
    fn sec(pf0: f32, pf1: f32, pr0: f32, pr1: f32, zf: f32, zr: f32, g0: f32, g1: f32) -> Section {
        Section {
            on: true,
            locked: false,
            role: String::new(),
            corners: [
                CornerStage {
                    pole_hz: pf0,
                    pole_r: pr0,
                    zero_hz: zf,
                    zero_r: zr,
                    gain_db: g0,
                },
                CornerStage {
                    pole_hz: pf1,
                    pole_r: pr0,
                    zero_hz: zf,
                    zero_r: zr,
                    gain_db: g1,
                },
                CornerStage {
                    pole_hz: pf0,
                    pole_r: pr1,
                    zero_hz: zf,
                    zero_r: zr,
                    gain_db: g0,
                },
                CornerStage {
                    pole_hz: pf1,
                    pole_r: pr1,
                    zero_hz: zf,
                    zero_r: zr,
                    gain_db: g1,
                },
            ],
        }
    }
    vec![
        sec(134.0, 134.0, 0.985, 0.996, 4130.0, 0.85, 0.0, 0.0),
        sec(780.0, 2840.0, 0.960, 0.995, 4130.0, 0.90, 0.0, 3.0),
        sec(1090.0, 3790.0, 0.960, 0.995, 8250.0, 0.90, 0.0, 0.0),
        sec(5450.0, 1420.0, 0.900, 0.990, 16000.0, 0.95, 0.0, 0.0),
        sec(3790.0, 5450.0, 0.970, 0.997, 4440.0, 0.95, 0.0, 0.0),
        sec(9000.0, 9000.0, 0.600, 0.700, 16000.0, 0.98, 0.0, -3.0),
    ]
}

/// Blank slate: six pole-zero pairs sharing frequency and radius, so every
/// section is ~flat and the cascade boots at 0 dB. Sculpt from nothing —
/// pins, the grip, or a table seed.
fn scratch_sections() -> Vec<Section> {
    [80.0f32, 250.0, 700.0, 1800.0, 4500.0, 10000.0]
        .iter()
        .map(|&f| Section {
            on: true,
            locked: false,
            role: String::new(),
            corners: [CornerStage {
                pole_hz: f,
                pole_r: 0.7,
                zero_hz: f,
                zero_r: 0.7,
                gain_db: 0.0,
            }; CORNERS],
        })
        .collect()
}

#[derive(Clone, Copy)]
struct BiquadUse {
    pole_used: bool,
    zero_used: bool,
    label: &'static str,
}

fn biquad_use(section: &Section, corner: usize) -> BiquadUse {
    if !section.on {
        return BiquadUse {
            pole_used: false,
            zero_used: false,
            label: "unused",
        };
    }
    let c = section.corners[corner];
    let sep = (c.zero_hz / c.pole_hz).log2().abs();
    let cancels = sep < 0.08 && (c.zero_r - c.pole_r).abs() < 0.05 && c.gain_db.abs() < 0.6;
    if cancels {
        return BiquadUse {
            pole_used: false,
            zero_used: false,
            label: "flat",
        };
    }
    let pole_used = c.pole_r >= 0.68 || c.gain_db.abs() >= 1.0;
    let zero_used = c.zero_r >= 0.18 && !cancels;
    let label = match (pole_used, zero_used) {
        (true, true) => "pole+zero",
        (true, false) => "pole only",
        (false, true) => "zero only",
        (false, false) => "weak",
    };
    BiquadUse {
        pole_used,
        zero_used,
        label,
    }
}

// ── app impl: state + DSP plumbing ───────────────────────────────────────────

impl App {
    fn new(cc: &eframe::CreationContext<'_>) -> Self {
        cc.egui_ctx.set_pixels_per_point(1.0);
        let mut app = Self::default_state();
        // --no-gpu-plot: jank-probe experiment — egui-painted plot, same app
        if !std::env::args().any(|a| a == "--no-gpu-plot") {
            if let Some(rs) = cc.wgpu_render_state.as_ref() {
                app.gpu_plot = gpu_plot::register(rs, FREQ_BINS as u32);
            }
        }
        // validation-only boot state (screenshot harness) — scratch boot is the law
        if std::env::args().any(|a| a == "--boot-seed") {
            app.seed_vowel_pair(0);
            app.show_ghosts = true;
            app.morph = 0.5;
            app.rebuild_body();
        }
        if std::env::args().any(|a| a == "--boot-bark") {
            BARK.store(true, std::sync::atomic::Ordering::Relaxed);
            app.bark = true;
        }
        if std::env::args().any(|a| a == "--boot-sweep") {
            app.sweep = true;
        }
        if std::env::args().any(|a| a == "--boot-qcompare") {
            app.boot_qcompare = true;
        }
        if std::env::args().any(|a| a == "--boot-help") {
            app.boot_help = true;
        }
        if std::env::args().any(|a| a == "--boot-exact") {
            let last = app.tables.skeletons.len().saturating_sub(1);
            app.seed_exact(last); // the elliptic — the headline skeleton
            app.show_ghosts = true;
            app.morph = 0.0;
            app.rebuild_body();
        }
        if std::env::args().any(|a| a == "--boot-start") {
            app.open_menu = Some(Menu::Seed);
        }
        app
    }

    fn default_state() -> Self {
        let (job_tx, resp_rx) = spawn_worker();
        let mut app = Self {
            job_tx,
            resp_rx,
            solve_inflight: false,
            heat_inflight: false,
            audit_inflight: false,
            table_gen_idx: 0,
            hand: None,
            last_dispatch: Instant::now(),
            sections: scratch_sections(),
            selected_stage: 1,
            selected_corner: CornerKey::M0Q0,
            scope: EditScope::Corner,
            quantize: Quantize::Measured,
            key_root: 9,
            morph: 0.0,
            q: 0.0,
            sweep: false,
            sweep_t0: Instant::now(),
            body: [0; 240],
            response: vec![0.0; FREQ_BINS],
            ghost_low: vec![0.0; FREQ_BINS],
            ghost_high: vec![0.0; FREQ_BINS],
            stage_db: [[0.0; FREQ_BINS]; STAGES],
            heat_texture: None,
            heat_dirty: true,
            show_ghosts: false,
            bark: false,
            overlay_vowel: None,
            show_rail: false,
            audit_levels: [f32::NAN; AUDIT_N * AUDIT_N],
            audit_maxr: 0.0,
            audit_unstable: 0,
            audit_dirty: true,
            audit_texture: None,
            audio: None,
            playing: false,
            audio_src: AudioSrc::Noise,
            brush_bark: 1.0,
            pins: Vec::new(),
            selected_pin: None,
            optimize_inflight: false,
            last_opt: None,
            solve_target: None,
            last_frame: Instant::now(),
            frame_ms_avg: 0.0,
            frame_ms_peak: 0.0,
            metered_frame: false,
            hint: None,
            gpu_plot: false,
            qcompare: None,
            boot_qcompare: false,
            draw_stroke: None,
            show_help: false,
            boot_help: false,
            autosaved_at: Instant::now(),
            q_link: true,
            patch: model::peak_shelf::PeakShelfPatch::default(),
            patch_linked: false,
            drag: None,
            curve_grip: None,
            hover: None,
            open_menu: None,
            menu_opened_at: None,
            name_active: false,
            body_name: String::new(),
            undo: Vec::new(),
            redo: Vec::new(),
            tables: load_tables(),
            start_manifest: sources::manifest::load(&repo_root()),
            source_bodies: HashMap::new(),
            overlay_curves: HashMap::new(),
            centroids: HashMap::new(),
            overlay_ref: None,
            packed_preview: None,
            status: "ready — six biquads pack to one 240-byte body".into(),
            last_edit: Instant::now(),
        };
        if let Some(manifest) = &app.start_manifest {
            let root = repo_root();
            app.source_bodies = sources::manifest::load_bodies(&root, manifest);
            app.overlay_curves = sources::manifest::load_overlays(&root, manifest);
            for (path, body) in &app.source_bodies {
                app.centroids.insert(path.clone(), body_centroid_hz(body));
            }
            for (path, ov) in &app.overlay_curves {
                if let Some(c) = ov.curves.first() {
                    app.centroids.insert(path.clone(), spectral_centroid_hz(&c.db));
                }
            }
        }
        app.rebuild_body();
        app
    }

    /// Editing a Q100 corner directly is the deliberate break-out from the
    /// derived Q rule — unlink before the gesture lands so it isn't clobbered.
    fn ensure_q_free(&mut self, corner: CornerKey) {
        if self.q_link && corner.morph_q().1 > 0.5 {
            self.q_link = false;
            self.status =
                "Q rows are separate now — use LINK Q or CORNERS to rebuild them".into();
        }
    }

    /// A short-lived explanation at the point of action — refusals must never
    /// be silent or only whispered in the far-away status bar.
    fn show_hint(&mut self, text: &str, pos: Pos2) {
        self.hint = Some((text.to_string(), pos, Instant::now()));
        self.status = text.to_string();
    }

    /// Land the follower target instantly (called before any new edit gesture
    /// so the smoothing never fights the hand).
    fn finish_anim(&mut self) {
        if let Some(t) = self.solve_target.take() {
            self.sections = t;
            self.rebuild_body();
        }
    }

    fn push_undo(&mut self) {
        self.finish_anim();
        self.undo.push(self.sections.clone());
        if self.undo.len() > 120 {
            self.undo.remove(0);
        }
        self.redo.clear();
        // any edit gesture detaches the Peak/Shelf patch; apply_patch (the
        // front sliders) immediately re-links after this chokepoint
        self.patch_linked = false;
    }

    fn do_undo(&mut self) {
        if let Some(prev) = self.undo.pop() {
            self.redo.push(self.sections.clone());
            self.sections = prev;
            self.patch_linked = false;
            self.rebuild_body();
            self.status = "undo".into();
        }
    }

    fn do_redo(&mut self) {
        if let Some(next) = self.redo.pop() {
            self.undo.push(self.sections.clone());
            self.sections = next;
            self.patch_linked = false;
            self.rebuild_body();
            self.status = "redo".into();
        }
    }

    fn params168(&self) -> Vec<f64> {
        params168_of(&self.sections)
    }

    fn active_sections(&self) -> usize {
        self.sections.iter().filter(|s| s.on).count()
    }

    #[allow(dead_code)]
    fn locked_sections(&self) -> usize {
        self.sections.iter().filter(|s| s.locked).count()
    }

    fn response_peak_db(&self) -> f32 {
        self.response
            .iter()
            .copied()
            .filter(|v| v.is_finite())
            .fold(f32::NEG_INFINITY, f32::max)
    }

    fn docked_corner(&self) -> Option<CornerKey> {
        let m0 = self.morph < 0.02;
        let m1 = self.morph > 0.98;
        let q0 = self.q < 0.02;
        let q1 = self.q > 0.98;
        match (m0, m1, q0, q1) {
            (true, false, true, false) => Some(CornerKey::M0Q0),
            (false, true, true, false) => Some(CornerKey::M100Q0),
            (true, false, false, true) => Some(CornerKey::M0Q100),
            (false, true, false, true) => Some(CornerKey::M100Q100),
            _ => None,
        }
    }

    fn target_label(&self) -> String {
        if let Some(corner) = self.docked_corner() {
            format!("{} — {}", corner.plain_label(), corner.code())
        } else {
            format!(
                "inside the grid — M{:02} Q{:02}",
                (self.morph * 100.0).round() as i32,
                (self.q * 100.0).round() as i32
            )
        }
    }

    #[allow(dead_code)]
    fn selected_stage_label(&self) -> String {
        let section = &self.sections[self.selected_stage];
        format!(
            "S{} {}{}",
            self.selected_stage + 1,
            if section.on { "ON" } else { "OFF" },
            if section.locked { " LOCKED" } else { "" }
        )
    }

    fn drag_focus_stage(&self) -> Option<usize> {
        match self.drag {
            Some(Drag::Handle { stage, .. }) => Some(stage),
            Some(Drag::Value { .. }) => Some(self.selected_stage),
            Some(Drag::Curve) => Some(self.selected_stage),
            _ => None,
        }
    }

    fn rebuild_body(&mut self) {
        // any recompile from sections supersedes a verbatim packed preview
        self.packed_preview = None;
        // frames-as-working-unit: Q100 rows are derived state while linked
        if self.q_link {
            for s in &mut self.sections {
                for (lo, hi) in [(0usize, 2usize), (1, 3)] {
                    let mut c = s.corners[lo];
                    c.pole_r = (1.0 - (1.0 - c.pole_r) * 0.35).clamp(RP_MIN, RP_MAX);
                    s.corners[hi] = c;
                }
            }
        }
        let params = self.params168();
        self.body = trench_core::compiler::pack_body(&params);
        self.recompute_response();
        self.heat_dirty = true;
        self.audit_dirty = true;
        self.last_edit = Instant::now();
        if let Some(audio) = &self.audio {
            // parse here (UI thread), never in the stream callback
            if let Ok(cart) =
                trench_core::cartridge::Cartridge::from_body_bytes("forge", &self.body, 1.0)
            {
                if let Ok(mut c) = audio.ctl.lock() {
                    c.pending_cart = Some(cart);
                }
            }
        }
    }

    fn toggle_play(&mut self) {
        self.playing = !self.playing;
        if self.playing && self.audio.is_none() {
            match start_audio(self.body, self.morph as f64, self.q as f64, self.audio_src) {
                Ok(handle) => {
                    self.audio = Some(handle);
                    self.status =
                        "audio: source → AGC + saturation chain (the product chain) → output"
                            .into();
                }
                Err(e) => {
                    self.playing = false;
                    self.status = format!("audio failed: {e}");
                }
            }
        }
        self.sync_audio();
    }

    fn sync_audio(&self) {
        if let Some(audio) = &self.audio {
            if let Ok(mut c) = audio.ctl.lock() {
                c.playing = self.playing;
                c.morph = self.morph as f64;
                c.q = self.q as f64;
                c.src = self.audio_src;
            }
        }
    }

    fn words(&self) -> [[[u16; 5]; STAGES]; CORNERS] {
        words_of(&self.body)
    }

    fn recompute_response(&mut self) {
        let words = self.words();
        let live = live_biquads(&words, self.morph, self.q);
        // ghosts always fresh — trench-core runs at full opt now and the GPU
        // plot uploads all rows every frame
        let selected_only_stage =
            matches!(self.drag, Some(Drag::Handle { .. } | Drag::Value { .. }));
        let ghosts = Some((
            live_biquads(&words, 0.0, self.q),
            live_biquads(&words, 1.0, self.q),
        ));
        let trig = grid_trig(FREQ_BINS);
        for i in 0..FREQ_BINS {
            let (c1, c2) = trig[i];
            self.response[i] = cascade_db_c(&live, c1, c2);
            if let Some((lo, hi)) = &ghosts {
                self.ghost_low[i] = cascade_db_c(lo, c1, c2);
                self.ghost_high[i] = cascade_db_c(hi, c1, c2);
            }
            for s in 0..STAGES {
                if !selected_only_stage || s == self.selected_stage {
                    self.stage_db[s][i] = biquad_db_c(live[s], c1, c2);
                }
            }
        }
    }

    fn stage_db_at(&self, stage: usize, freq: f32) -> f32 {
        let t = (freq / F_MIN).log2() / (F_MAX / F_MIN).log2();
        let i = (t.clamp(0.0, 1.0) * (FREQ_BINS - 1) as f32).round() as usize;
        self.stage_db[stage][i]
    }

    /// Pump worker responses: apply solves, upload textures. Non-blocking.
    fn pump_worker(&mut self, ctx: &egui::Context) {
        while let Ok(resp) = self.resp_rx.try_recv() {
            match resp {
                Resp::Solve(r) => {
                    self.solve_inflight = false;
                    self.solve_target = Some(r.sections);
                    if let Some(grip) = &mut self.curve_grip {
                        grip.residual_rms = r.residual;
                    }
                    let names: Vec<String> =
                        r.stages.iter().map(|s| format!("S{}", s + 1)).collect();
                    self.status = format!(
                        "shaping {} at {} · width {:.2} (wheel) · error {:.2} dB",
                        names.join("+"),
                        format_freq(r.f_center),
                        r.sigma,
                        r.residual,
                    );
                    // still holding? keep the ping-pong going with the newest hand state
                    if matches!(self.drag, Some(Drag::Curve)) {
                        self.dispatch_solve();
                    }
                }
                Resp::Optimize(r) => {
                    self.optimize_inflight = false;
                    // undo was pushed at gesture start (pin add / drag begin),
                    // so the result just lands — magic, but Ctrl+Z still reverts
                    let names: Vec<String> =
                        r.stages.iter().map(|s| format!("S{}", s + 1)).collect();
                    let dragging = matches!(self.drag, Some(Drag::Pin { .. }));
                    if r.accepted {
                        self.solve_target = Some(r.sections);
                        self.status = format!(
                            "fit: error {:.2} → {:.2} dB on {} · Ctrl+Z reverts",
                            r.before,
                            r.after,
                            names.join("+"),
                        );
                    } else if !r.message.is_empty() {
                        self.status = r.message;
                    }
                    self.last_opt = Some(OptOutcome {
                        stages: r.stages,
                        before: r.before,
                        after: r.after,
                        accepted: r.accepted,
                        at: Instant::now(),
                    });
                    // still dragging a pin? keep the light-solve ping-pong going
                    if dragging {
                        self.dispatch_optimize(true);
                    }
                }
                Resp::Heat(pixels) => {
                    self.heat_inflight = false;
                    let image = egui::ColorImage {
                        size: [HEAT_W, HEAT_H],
                        pixels,
                    };
                    match &mut self.heat_texture {
                        Some(tex) => tex.set(image, TextureOptions::LINEAR),
                        None => {
                            self.heat_texture =
                                Some(ctx.load_texture("morph_sweep", image, TextureOptions::LINEAR))
                        }
                    }
                }
                Resp::Audit {
                    levels,
                    maxr,
                    unstable,
                    pixels,
                } => {
                    self.audit_inflight = false;
                    self.audit_levels.copy_from_slice(&levels);
                    self.audit_maxr = maxr;
                    self.audit_unstable = unstable;
                    let image = egui::ColorImage {
                        size: [AUDIT_N, AUDIT_N],
                        pixels,
                    };
                    match &mut self.audit_texture {
                        Some(tex) => tex.set(image, TextureOptions::NEAREST),
                        None => {
                            self.audit_texture = Some(ctx.load_texture(
                                "surface_map",
                                image,
                                TextureOptions::NEAREST,
                            ))
                        }
                    }
                }
            }
        }
    }

    /// Current-state goal residual through the packed runtime (the live words
    /// of self.body — same bytes the engine plays). Cheap; recomputed per frame.
    fn goal_residual_now(&self) -> Option<f32> {
        if self.pins.is_empty() {
            return None;
        }
        let stages = live_biquads(&self.words(), self.morph, self.q);
        let eval = |f: f32| cascade_db(&stages, f);
        let samples = goal_samples(&self.pins, &eval);
        Some(residual_goal_packed(&samples, &eval))
    }

    /// Combined packed response at one frequency (current morph/Q).
    fn response_db_at(&self, freq: f32) -> f32 {
        let t = (freq / F_MIN).log2() / (F_MAX / F_MIN).log2();
        let i = (t.clamp(0.0, 1.0) * (FREQ_BINS - 1) as f32).round() as usize;
        self.response[i]
    }

    /// Fire the goal solve. Silent plumbing: pins call this on add / drag /
    /// width change; the worker coalesces, the accepted result just appears.
    /// Zeros are always in the vector but heavily regularized — they only
    /// move when poles and gain can't reach the target.
    fn dispatch_optimize(&mut self, fast: bool) {
        if self.optimize_inflight || self.pins.is_empty() {
            return;
        }
        let req = OptReq {
            sections: self.sections.clone(),
            pins: self.pins.clone(),
            scope: self.selected_corner.scope_corners(self.scope),
            selected_stage: self.selected_stage,
            morph: self.morph,
            q: self.q,
            corner: self.selected_corner.idx(),
            allow_zero_freq: true,
            allow_zero_radius: true,
            fast,
        };
        if self.job_tx.send(Job::Optimize(req)).is_ok() {
            self.optimize_inflight = true;
        }
    }

    /// Drop a goal pin in empty plot space and immediately fire the solver —
    /// the curve chases the pin. Shift = hold pin: it captures the current
    /// packed response and protects it while other pins pull. Returns false
    /// when the press was on the combined curve (that's the grip's territory).
    /// Draw-the-target landing: the painted stroke becomes dense Bark-spaced
    /// target pins (0.5 Bark bins, dB averaged per bin) and the goal optimizer
    /// fits — through the packed runtime like every other solve.
    fn finish_draw_stroke(&mut self) {
        let Some(stroke) = self.draw_stroke.take() else {
            return;
        };
        self.drag = None;
        if stroke.len() < 3 {
            self.status = "target stroke too short — hold D and draw across the plot".into();
            return;
        }
        let mut bins: std::collections::BTreeMap<i32, (f32, f32, usize)> =
            std::collections::BTreeMap::new();
        for (f, db) in stroke {
            let k = (bark_z(f) / 0.5).round() as i32;
            let e = bins.entry(k).or_insert((0.0, 0.0, 0));
            e.0 += bark_z(f);
            e.1 += db;
            e.2 += 1;
        }
        self.pins = bins
            .values()
            .take(24)
            .map(|&(zsum, dbsum, n)| GoalPin {
                kind: PinKind::Target,
                shape: PinShape::Point,
                freq_hz: bark_f(zsum / n as f32),
                target_db: dbsum / n as f32,
                width_bark: 0.6,
            })
            .collect();
        self.selected_pin = None;
        self.ensure_q_free(self.selected_corner);
        self.status = format!(
            "target drawn — fitting {} points (Esc clears)",
            self.pins.len()
        );
        self.dispatch_optimize(false);
    }

    fn add_goal_pin(&mut self, pos: Pos2, plot: Rect, hold: bool) -> bool {
        let n = self.response.len();
        let tx = ((pos.x - plot.left()) / plot.width()).clamp(0.0, 1.0);
        let f = axis_f(tx);
        if (pos.y - y_for_db(plot, self.response[bin_for_freq(f, n)])).abs() < 12.0 {
            return false;
        }
        self.ensure_q_free(self.selected_corner); // pin solves edit this corner's rows
        let pin = if hold {
            GoalPin {
                kind: PinKind::Anchor,
                shape: PinShape::Peak,
                freq_hz: f,
                target_db: self.response_db_at(f),
                width_bark: 1.5,
            }
        } else {
            let db = DB_MIN
                + (1.0 - (pos.y - plot.top()) / plot.height()).clamp(0.0, 1.0) * (DB_MAX - DB_MIN);
            GoalPin {
                kind: PinKind::Target,
                shape: PinShape::Peak,
                freq_hz: self.snap(f, false),
                target_db: db,
                width_bark: self.brush_bark,
            }
        };
        self.push_undo();
        self.pins.push(pin);
        self.selected_pin = Some(self.pins.len() - 1);
        self.dispatch_optimize(true);
        self.status = format!(
            "{} {} {:+.1} dB — fitting now (drag it · right-click removes · Ctrl+Z reverts)",
            if hold { "hold point at" } else { "target at" },
            format_freq(pin.freq_hz),
            pin.target_db,
        );
        true
    }

    fn dispatch_solve(&mut self) {
        if self.solve_inflight {
            return;
        }
        let Some((f_center, finger_db, fine)) = self.hand else {
            return;
        };
        let dt = self.last_dispatch.elapsed().as_secs_f32().min(0.1);
        self.last_dispatch = Instant::now();
        let follow = 1.0 - (-dt * 10.0).exp();
        let req = SolveReq {
            sections: self.sections.clone(),
            corner: self.selected_corner.idx(),
            scope: self.selected_corner.scope_corners(self.scope),
            f_center,
            finger_db,
            sigma: self.brush_bark,
            follow,
            fine,
            morph: self.morph,
            q: self.q,
        };
        if self.job_tx.send(Job::Solve(req)).is_ok() {
            self.solve_inflight = true;
        }
    }

    #[allow(dead_code)]
    fn audit_at(&self, m: f32, q: f32) -> f32 {
        let i = (m * (AUDIT_N - 1) as f32).round() as usize;
        let j = (q * (AUDIT_N - 1) as f32).round() as usize;
        self.audit_levels[j * AUDIT_N + i]
    }

    fn select_corner(&mut self, corner: CornerKey) {
        self.selected_corner = corner;
        let (m, q) = corner.morph_q();
        let q_changed = (self.q - q).abs() > f32::EPSILON;
        self.morph = m;
        self.q = q;
        self.recompute_response();
        if q_changed {
            self.heat_dirty = true;
        }
    }

    fn grid(&self) -> Option<Vec<f32>> {
        match self.quantize {
            Quantize::Off => None,
            Quantize::Measured => {
                (!self.tables.resonances.is_empty()).then(|| self.tables.resonances.clone())
            }
            Quantize::Tet => {
                const MINOR: [i32; 7] = [0, 2, 3, 5, 7, 8, 10];
                let mut out = Vec::new();
                for midi in 12..=120i32 {
                    let deg = (midi - self.key_root as i32).rem_euclid(12);
                    if !MINOR.contains(&deg) {
                        continue;
                    }
                    let f = 440.0 * 2f32.powf((midi as f32 - 69.0) / 12.0);
                    if (F_MIN..=F_MAX).contains(&f) {
                        out.push(f);
                    }
                }
                Some(out)
            }
        }
    }

    fn snap(&self, freq: f32, fine: bool) -> f32 {
        if fine {
            return freq;
        }
        let Some(grid) = self.grid() else { return freq };
        let mut best = freq;
        let mut bd = f32::INFINITY;
        for g in grid {
            let d = (g / freq).log2().abs();
            if d < bd {
                bd = d;
                best = g;
            }
        }
        let threshold = 0.030;
        if bd < threshold {
            let pull = (1.0 - bd / threshold).clamp(0.0, 1.0).powf(1.7);
            (freq * (best / freq).powf(pull)).clamp(F_MIN, F_MAX)
        } else {
            freq
        }
    }

    // ── seeds: type-family templates + table-driven material ────────────────

    fn set_all(&mut self, rows: &[(bool, f32, f32, f32, f32, f32, f32, f32, f32)]) {
        self.q_link = true; // fresh seed: Q rows derived again
                            // (on, pf_low, pf_high, pr_q0, pr_q1, zf_low, zf_high, zr, gain_db)
        for (s, row) in rows.iter().enumerate().take(STAGES) {
            let (on, pf0, pf1, pr0, pr1, zf0, zf1, zr, g) = *row;
            let sec = &mut self.sections[s];
            sec.on = on;
            sec.locked = false;
            sec.role.clear();
            for (ci, key) in CornerKey::ALL.iter().enumerate() {
                let (m, q) = key.morph_q();
                let c = &mut sec.corners[ci];
                c.pole_hz = (if m > 0.5 { pf1 } else { pf0 }).clamp(F_MIN, F_MAX);
                c.pole_r = (if q > 0.5 { pr1 } else { pr0 }).clamp(RP_MIN, RP_MAX);
                c.zero_hz = (if m > 0.5 { zf1 } else { zf0 }).clamp(F_MIN, F_MAX);
                c.zero_r = zr.clamp(0.0, RZ_MAX);
                c.gain_db = g;
            }
        }
        self.rebuild_body();
    }

    fn restore_autosave(&mut self) {
        let path = repo_root().join("dev/tmp/forge_gpu_painter/autosave.source.json");
        let Ok(bytes) = fs::read(&path) else {
            self.status = "no autosave yet — it writes every 30 s once you edit".into();
            return;
        };
        match serde_json::from_slice::<SidecarOwned>(&bytes) {
            Ok(mut side) if !side.sections.is_empty() => {
                side.sections.truncate(STAGES);
                while side.sections.len() < STAGES {
                    side.sections
                        .push(scratch_sections()[side.sections.len()].clone());
                }
                self.push_undo();
                self.sections = side.sections;
                self.q_link = false; // restored Q rows are as saved, not derived
                if let Some(patch) = side.peak_shelf_patch {
                    // the autosave was patch-authored — re-link the frame controls
                    self.patch = patch;
                    self.patch_linked = true;
                }
                self.rebuild_body();
                self.status = "restored last autosave (Q rows separate — rows as saved)".into();
            }
            _ => self.status = "autosave unreadable — not restored".into(),
        }
    }

    /// Dispatch a START manifest row by its provenance kind.
    fn start_manifest_row(&mut self, lane: usize, row: usize) {
        let Some(manifest) = &self.start_manifest else {
            return;
        };
        let Some(row) = manifest
            .lanes
            .get(lane)
            .and_then(|l| l.rows.get(row))
            .cloned()
        else {
            self.status = "start row unavailable".into();
            return;
        };
        match row.kind.as_str() {
            "peak_shelf" => self.run_action(MenuAction::SeedPeakShelf),
            "law" => {
                let Some(stages) = &row.stages else {
                    self.status = format!("{}: no stages sidecar", row.label);
                    return;
                };
                match load_law_stage_sections(stages) {
                    Ok(sections) => {
                        self.push_undo();
                        self.sections = sections;
                        self.pins.clear();
                        self.selected_pin = None;
                        self.q_link = false;
                        self.body_name = slugify(&row.label);
                        self.morph = 0.0;
                        self.q = 0.0;
                        self.selected_stage = 0;
                        self.selected_corner = CornerKey::M0Q0;
                        self.rebuild_body();
                        self.status =
                            format!("START: {} — compiled law, editable", row.label);
                    }
                    Err(err) => {
                        self.status = format!("could not start from {}: {err}", row.label)
                    }
                }
            }
            "exact_skeleton" => {
                let idx = self
                    .tables
                    .skeletons
                    .iter()
                    .position(|sk| Some(&sk.key) == row.exact_key.as_ref());
                match idx {
                    Some(i) => self.seed_exact(i),
                    None => {
                        self.status = format!(
                            "{}: not in the verified skeleton tables — run tools/verify_exact_skeletons.py",
                            row.label
                        )
                    }
                }
            }
            "overlay" => {
                let Some(path) = &row.curves else {
                    self.status = format!("{}: no curves file", row.label);
                    return;
                };
                if self.overlay_ref.as_ref() == Some(path) {
                    self.overlay_ref = None;
                    self.status = format!("overlay off: {}", row.label);
                } else if self.overlay_curves.contains_key(path) {
                    self.overlay_ref = Some(path.clone());
                    self.status = format!(
                        "overlay: {} — exact reference curves (study, not shipping source)",
                        row.label
                    );
                } else {
                    self.status = format!("{}: curves file missing on disk", row.label);
                }
            }
            _ => {
                // packed: verbatim bytes for listening/plotting only
                let Some(body) = row.body.as_ref().and_then(|p| self.source_bodies.get(p)).copied()
                else {
                    self.status = format!("{}: body bytes missing on disk", row.label);
                    return;
                };
                self.seed_packed_preview(&row.label, body);
            }
        }
    }

    /// A packed body loaded verbatim: the plot, MORPH/PRESSURE and audio run
    /// from the real bytes; the six editable sections do NOT describe it.
    /// Any edit recompiles from sections and drops the preview — and BAKE /
    /// KEEP refuse while previewing (clean-room: reference bytes never ship).
    fn seed_packed_preview(&mut self, label: &str, body: [u8; 240]) {
        self.finish_anim();
        self.body = body;
        self.packed_preview = Some(label.to_string());
        self.patch_linked = false;
        self.pins.clear();
        self.selected_pin = None;
        self.morph = 0.0;
        self.q = 0.0;
        self.recompute_response();
        self.heat_dirty = true;
        self.audit_dirty = true;
        self.last_edit = Instant::now();
        if let Some(audio) = &self.audio {
            if let Ok(cart) =
                trench_core::cartridge::Cartridge::from_body_bytes("forge", &self.body, 1.0)
            {
                if let Ok(mut c) = audio.ctl.lock() {
                    c.pending_cart = Some(cart);
                }
            }
        }
        self.status = format!(
            "packed preview: {label} — sweep/listen; editing returns to your sections"
        );
    }

    fn seed_scratch(&mut self) {
        self.push_undo();
        self.sections = scratch_sections();
        self.pins.clear();
        self.selected_pin = None;
        self.q_link = true;
        self.rebuild_body();
        self.status =
            "scratch: six flat pole-zero pairs at 0 dB — sculpt with pins, the grip, or a seed"
                .into();
    }

    fn seed_default(&mut self) {
        self.push_undo();
        self.sections = default_sections();
        self.rebuild_body();
        self.status = "seed: default template".into();
    }

    /// Resonant low-pass sweep: stacked poles at the cutoff travelling up the
    /// band under morph, zeros parked high. Q sharpens the corner.
    fn seed_lowpass(&mut self) {
        self.push_undo();
        self.set_all(&[
            (
                true, 110.0, 3520.0, 0.97, 0.996, 14000.0, 14000.0, 0.85, 0.0,
            ),
            (true, 110.0, 3520.0, 0.93, 0.99, 14000.0, 14000.0, 0.85, 0.0),
            (true, 110.0, 3520.0, 0.88, 0.95, 14000.0, 14000.0, 0.85, 0.0),
            (true, 55.0, 55.0, 0.94, 0.96, 14000.0, 14000.0, 0.8, 0.0),
            (false, 880.0, 880.0, 0.8, 0.85, 14000.0, 14000.0, 0.8, 0.0),
            (false, 880.0, 880.0, 0.8, 0.85, 14000.0, 14000.0, 0.8, 0.0),
        ]);
        self.status = "seed: resonant low-pass sweep (110 Hz → 3.5 kHz, zeros parked high)".into();
    }

    /// High-pass: deep zeros pinned at the bottom of the band, poles at the
    /// moving cutoff giving the corner its resonance.
    fn seed_highpass(&mut self) {
        self.push_undo();
        self.set_all(&[
            (true, 110.0, 1760.0, 0.95, 0.993, 30.0, 30.0, 0.995, 0.0),
            (true, 110.0, 1760.0, 0.9, 0.97, 42.0, 42.0, 0.99, 0.0),
            (true, 110.0, 1760.0, 0.85, 0.92, 60.0, 60.0, 0.99, 0.0),
            (false, 880.0, 880.0, 0.8, 0.85, 30.0, 30.0, 0.9, 0.0),
            (false, 880.0, 880.0, 0.8, 0.85, 30.0, 30.0, 0.9, 0.0),
            (false, 880.0, 880.0, 0.8, 0.85, 30.0, 30.0, 0.9, 0.0),
        ]);
        self.status = "seed: high-pass (zeros pinned low, resonant moving corner)".into();
    }

    /// Band-pass: one strong resonator riding the morph, zeros guarding both
    /// edges of the band.
    fn seed_bandpass(&mut self) {
        self.push_undo();
        self.set_all(&[
            (true, 220.0, 3520.0, 0.985, 0.996, 30.0, 30.0, 0.99, 0.0),
            (true, 220.0, 3520.0, 0.97, 0.99, 14000.0, 14000.0, 0.95, 0.0),
            (true, 220.0, 3520.0, 0.9, 0.95, 30.0, 30.0, 0.9, 0.0),
            (false, 880.0, 880.0, 0.8, 0.85, 14000.0, 14000.0, 0.9, 0.0),
            (false, 880.0, 880.0, 0.8, 0.85, 14000.0, 14000.0, 0.9, 0.0),
            (false, 880.0, 880.0, 0.8, 0.85, 14000.0, 14000.0, 0.9, 0.0),
        ]);
        self.status = "seed: band-pass (resonator sweep, zeros at both band edges)".into();
    }

    /// Notch comb: deep zero series at odd harmonics, near-allpass poles —
    /// the classic phaser construction. Morph shifts the whole comb.
    fn seed_notch_comb(&mut self) {
        self.push_undo();
        let f0_lo = 220.0;
        let f0_hi = 880.0;
        let mut rows = Vec::new();
        for k in 0..STAGES {
            let n = (2 * k + 1) as f32;
            rows.push((
                true,
                f0_lo * n * 0.97,
                f0_hi * n * 0.97,
                0.88f32,
                0.93f32,
                f0_lo * n,
                f0_hi * n,
                0.99f32,
                0.0f32,
            ));
        }
        self.set_all(&rows);
        self.status =
            "seed: notch comb / phase-shifter (zeros at odd multiples, near-allpass poles)".into();
    }

    /// Parametric boost: two strong peaking sections over a held low shelf —
    /// the EQ family. Morph slides the boost up the band.
    fn seed_parametric(&mut self) {
        self.push_undo();
        self.set_all(&[
            (true, 88.0, 88.0, 0.985, 0.992, 350.0, 350.0, 0.7, 3.0),
            (true, 220.0, 1760.0, 0.985, 0.996, 700.0, 3520.0, 0.9, 4.0),
            (true, 440.0, 3520.0, 0.98, 0.995, 1400.0, 7040.0, 0.9, 2.0),
            (false, 880.0, 880.0, 0.8, 0.85, 14000.0, 14000.0, 0.9, 0.0),
            (false, 880.0, 880.0, 0.8, 0.85, 14000.0, 14000.0, 0.9, 0.0),
            (false, 880.0, 880.0, 0.8, 0.85, 14000.0, 14000.0, 0.9, 0.0),
        ]);
        self.status = "seed: parametric boost over a held low shelf (EQ family)".into();
    }

    /// Resonant peaks: all six sections hot, spread across the band — the
    /// aggressive high-Q family. Q drives every radius to the rim.
    fn seed_peaks(&mut self) {
        self.push_undo();
        self.set_all(&[
            (true, 110.0, 165.0, 0.985, 0.997, 30.0, 30.0, 0.9, 0.0),
            (true, 330.0, 495.0, 0.985, 0.997, 14000.0, 14000.0, 0.9, 0.0),
            (
                true, 700.0, 1050.0, 0.985, 0.997, 14000.0, 14000.0, 0.9, 0.0,
            ),
            (
                true, 1400.0, 2100.0, 0.985, 0.997, 14000.0, 14000.0, 0.9, 0.0,
            ),
            (
                true, 2800.0, 4200.0, 0.985, 0.997, 14000.0, 14000.0, 0.9, 0.0,
            ),
            (
                true, 5600.0, 8400.0, 0.985, 0.997, 14000.0, 14000.0, 0.9, 0.0,
            ),
        ]);
        self.status = "seed: six resonant peaks, radius to the rim under Q".into();
    }

    fn seed_vowel_pair(&mut self, pair: usize) {
        let (low_key, high_key, label) = VOWEL_PAIRS[pair];
        let find = |k: &str| self.tables.vowels.iter().find(|v| v.0 == k).cloned();
        let (Some(lo), Some(hi)) = (find(low_key), find(high_key)) else {
            self.status = "vowel table not loaded (tables/vowel_formants.json)".into();
            return;
        };
        self.push_undo();
        let r_of = |bw: f32| {
            (-std::f32::consts::PI * bw / SR)
                .exp()
                .clamp(RP_MIN, RP_MAX)
        };
        let mut rows: Vec<(bool, f32, f32, f32, f32, f32, f32, f32, f32)> = vec![
            (true, 134.0, 134.0, 0.985, 0.996, 4130.0, 4130.0, 0.85, 0.0), // low anchor held
        ];
        for (f_lo, f_hi, bw_lo, bw_hi) in [
            (lo.1, hi.1, lo.4, hi.4),
            (lo.2, hi.2, lo.5, hi.5),
            (lo.3, hi.3, lo.6, hi.6),
        ] {
            let r0 = r_of(bw_lo.max(bw_hi));
            let r1 = (1.0 - (1.0 - r0) * 0.35).clamp(RP_MIN, RP_MAX);
            rows.push((true, f_lo, f_hi, r0, r1, f_lo * 4.0, f_hi * 4.0, 0.9, 0.0));
        }
        rows.push((false, 880.0, 880.0, 0.8, 0.85, 14000.0, 14000.0, 0.9, 0.0));
        rows.push((false, 880.0, 880.0, 0.8, 0.85, 14000.0, 14000.0, 0.9, 0.0));
        self.set_all(&rows);
        self.sections[0].locked = true; // the anchor boots locked
        for (i, role) in ["chest", "F1", "F2", "F3", "", ""].iter().enumerate() {
            self.sections[i].role = role.to_string();
        }
        self.status =
            format!("seed: {label} (Peterson-Barney formants, r from bandwidth; S1 anchor locked)");
    }

    fn seed_tube(&mut self, which: usize) {
        self.push_undo();
        let f0 = TUBE_F0[which % TUBE_F0.len()];
        let mut rows = Vec::new();
        for s in 0..STAGES {
            let n = (s + 1) as f32;
            let f = f0 * n;
            rows.push((
                true,
                f,
                f * 1.5,
                0.99f32,
                0.997f32,
                f * 3.0,
                f * 4.5,
                0.9f32,
                0.0f32,
            ));
        }
        self.set_all(&rows);
        for i in 0..STAGES {
            self.sections[i].role = format!("p{}", i + 1);
        }
        self.status = format!("seed: tube partials 1,2,3… × {f0:.0} Hz (morph stretches the tube)");
    }

    fn seed_metal(&mut self, which: usize) {
        if self.tables.metal_ratios.len() < 2 {
            self.status = "metallic_modes table not loaded".into();
            return;
        }
        self.push_undo();
        let f0 = METAL_F0[which % METAL_F0.len()];
        let ratios = self.tables.metal_ratios.clone();
        let mut rows = Vec::new();
        for s in 0..STAGES {
            let ratio = ratios.get(s).copied().unwrap_or(*ratios.last().unwrap());
            let f = f0 * ratio;
            rows.push((
                true,
                f,
                f * 1.26,
                0.985f32,
                0.997f32,
                f * 3.0,
                f * 3.78,
                0.9f32,
                0.0f32,
            ));
        }
        self.set_all(&rows);
        for i in 0..STAGES {
            self.sections[i].role = format!("mode {}", i + 1);
        }
        self.status = format!("seed: inharmonic modal series × {f0:.0} Hz (metallic_modes ratios)");
    }

    // ── LPC fit (drop a WAV on the window) ───────────────────────────────────

    /// Exact skeleton: a closed-form optimal order-12 design at two note-grid
    /// cutoffs — the low and high morph frames. The travel is an exact musical
    /// interval; Q LINK supplies the Q rows; the ear takes it from here.
    fn seed_exact(&mut self, which: usize) {
        let Some(sk) = self.tables.skeletons.get(which).cloned() else {
            self.status = if self.tables.skeleton_verification_loaded {
                "no verified tables — run tools/verify_exact_skeletons.py and fix failing rows".into()
            } else {
                "tables not verified — run python tools/verify_exact_skeletons.py".into()
            };
            return;
        };
        self.push_undo();
        for (i, sec) in self.sections.iter_mut().enumerate() {
            sec.role.clear();
            sec.locked = false;
            match sk.sections.get(i) {
                Some(row) => {
                    sec.on = true;
                    for (ci, key) in CornerKey::ALL.iter().enumerate() {
                        let hi = key.morph_q().0 > 0.5;
                        let c = &mut sec.corners[ci];
                        c.pole_hz =
                            (if hi { row.pole_hz_hi } else { row.pole_hz_lo }).clamp(F_MIN, F_MAX);
                        c.pole_r =
                            (if hi { row.pole_r_hi } else { row.pole_r_lo }).clamp(RP_MIN, RP_MAX);
                        c.zero_hz =
                            (if hi { row.zero_hz_hi } else { row.zero_hz_lo }).clamp(F_MIN, F_MAX);
                        c.zero_r =
                            (if hi { row.zero_r_hi } else { row.zero_r_lo }).clamp(0.0, RZ_MAX);
                        c.gain_db = (if hi { row.gain_db_hi } else { row.gain_db_lo })
                            .clamp(GAIN_DB_MIN, GAIN_DB_MAX);
                    }
                }
                None => sec.on = false,
            }
        }
        self.q_link = true;
        self.rebuild_body();
        self.status = format!(
            "seed: {} — {:.0} → {:.0} Hz · {}",
            sk.label,
            sk.f_lo,
            sk.f_hi,
            if sk.verified {
                sk.verify_note.as_str()
            } else {
                "not independently verified"
            }
        );
    }

    fn generate_table_body(&mut self, publish: bool) {
        let n = self.tables.skeletons.len();
        if n == 0 {
            self.status = if self.tables.skeleton_verification_loaded {
                "verified start unavailable — no source rows passed".into()
            } else {
                "verified start unavailable — run python tools/verify_exact_skeletons.py first".into()
            };
            return;
        }
        let idx = self.table_gen_idx % n;
        self.table_gen_idx = (idx + 1) % n;
        self.seed_exact(idx);

        let sk = self.tables.skeletons[idx].clone();
        self.body_name = format!("table_{}", slugify(&sk.key));
        self.morph = 0.0;
        self.q = 0.0;
        self.sweep = true;
        self.sweep_t0 = Instant::now();
        self.selected_stage = 0;
        self.selected_corner = CornerKey::M0Q0;

        let (levels, maxr, unstable, _) = compute_audit(&self.words());
        self.audit_levels.copy_from_slice(&levels);
        self.audit_maxr = maxr;
        self.audit_unstable = unstable;
        self.audit_dirty = false;
        self.audit_inflight = false;

        let pub_note = if publish {
            match self.write_audition_slot() {
                Ok(path) => format!(" · audition {}", path.display()),
                Err(err) => format!(" · audition failed: {err}"),
            }
        } else {
            String::new()
        };
        self.status = format!(
            "verified start {}/{}: {} → 240-byte body · grid {} · max pole {:.4}{}",
            idx + 1,
            n,
            sk.label,
            if unstable == 0 { "stable" } else { "UNSTABLE" },
            maxr,
            pub_note
        );
    }

    fn fit_wav(&mut self, path: &Path, into_high_frame: bool) {
        let Ok(bytes) = fs::read(path) else {
            self.status = format!("could not read {}", path.display());
            return;
        };
        let Some((samples, sr)) = parse_wav(&bytes) else {
            self.status = "not a readable WAV (PCM 16/24/32 or float32)".into();
            return;
        };
        let take = samples.len().min((sr * 4.0) as usize);
        let (mut poles, valleys) =
            trench_core::lpc::extract_poles_and_valleys(&samples[..take], sr);
        if poles.is_empty() {
            self.status = "LPC fit found no resonant poles in that file".into();
            return;
        }
        self.push_undo();
        poles.sort_by(|a, b| a.freq_hz.partial_cmp(&b.freq_hz).unwrap());
        let corner_ids: [usize; 2] = if into_high_frame { [1, 3] } else { [0, 2] };
        for s in 0..STAGES {
            if self.sections[s].locked {
                continue;
            }
            if let Some(p) = poles.get(s) {
                let f = (p.freq_hz as f32).clamp(F_MIN, F_MAX);
                let r = (p.radius as f32).clamp(RP_MIN, RP_MAX);
                let zf = valleys
                    .get(s)
                    .map(|v| (*v as f32).clamp(F_MIN, F_MAX))
                    .unwrap_or((f * 3.0).clamp(F_MIN, F_MAX));
                self.sections[s].on = true;
                for ci in corner_ids {
                    let q_hi = ci >= 2;
                    let rr = if q_hi {
                        (1.0 - (1.0 - r) * 0.35).clamp(RP_MIN, RP_MAX)
                    } else {
                        r
                    };
                    let c = &mut self.sections[s].corners[ci];
                    c.pole_hz = f;
                    c.pole_r = rr;
                    c.zero_hz = zf;
                    c.zero_r = 0.9;
                }
            }
        }
        self.rebuild_body();
        self.status = format!(
            "LPC fit: {} poles + {} valleys from {} → {} frame (locked sections held)",
            poles.len().min(STAGES),
            valleys.len().min(STAGES),
            path.file_name()
                .map(|f| f.to_string_lossy().to_string())
                .unwrap_or_default(),
            if into_high_frame {
                "high (M100)"
            } else {
                "low (M0)"
            },
        );
    }

    // ── corner tools / bake / audition ───────────────────────────────────────

    fn copy_corner_to_all(&mut self) {
        self.push_undo();
        let src = self.selected_corner.idx();
        for s in &mut self.sections {
            if s.locked {
                continue;
            }
            let c = s.corners[src];
            for ci in 0..CORNERS {
                s.corners[ci] = c;
            }
        }
        self.rebuild_body();
        self.status = format!(
            "copied {} to all corners (locked sections held)",
            self.selected_corner.label()
        );
    }

    fn derive_q_corners(&mut self) {
        self.push_undo();
        for s in &mut self.sections {
            if s.locked {
                continue;
            }
            for (lo, hi) in [(0usize, 2usize), (1, 3)] {
                let mut c = s.corners[lo];
                c.pole_r = (1.0 - (1.0 - c.pole_r) * 0.35).clamp(RP_MIN, RP_MAX);
                s.corners[hi] = c;
            }
        }
        self.q_link = true; // re-linked: Q rows stay derived until broken out again
        self.rebuild_body();
        self.status =
            "Q100 corners derived & linked: pole radius toward the rim, zeros held".into();
    }

    fn bake(&mut self) {
        if let Some(label) = &self.packed_preview {
            self.status = format!(
                "BAKE refused — {label} is a packed preview (reference bytes never ship); edit or START an editable source"
            );
            return;
        }
        let slug = if self.body_name.trim().is_empty() {
            "forge_design".to_string()
        } else {
            slugify(self.body_name.trim())
        };
        let out = repo_root().join("dev/tmp/forge_gpu_painter");
        let body_path = out.join(format!("{slug}.body240"));
        let json_path = out.join(format!("{slug}.source.json"));
        let _ = fs::create_dir_all(&out);
        if let Err(err) = fs::write(&body_path, self.body) {
            self.status = format!("bake failed: {err}");
            return;
        }
        let sidecar = SaveSidecar {
            note:
                "TRENCH FORGE source. Body bytes packed through trench_core::compiler::pack_body.",
            sections: &self.sections,
            peak_shelf_patch: self.patch_linked.then_some(&self.patch),
        };
        let _ = serde_json::to_vec_pretty(&sidecar).map(|json| fs::write(&json_path, json));
        self.status = format!("baked {} (240 bytes)", body_path.display());
    }

    /// SPEC item 6: KEEP → bank staging. Assembles a keeper's evidence bundle
    /// — bytes, compiled cartridge, source sections, a fresh synchronous
    /// 17×17 audit, byte provenance (SHA-256) — into desk/bank/v1/staging/.
    /// The verdict and the BANK.md row remain the producer's; an unstable
    /// audit refuses outright.
    fn keep_to_staging(&mut self) {
        use sha2::Digest;
        if let Some(label) = &self.packed_preview {
            self.status = format!(
                "KEEP refused — {label} is a packed preview (reference bytes never ship); edit or START an editable source"
            );
            return;
        }
        let words = self.words();
        let (levels, maxr, unstable, _) = compute_audit(&words);
        if unstable > 0 {
            self.status = format!("KEEP refused — {unstable} unstable cells in the 17×17 audit");
            return;
        }
        let slug = if self.body_name.trim().is_empty() {
            let h = sha2::Sha256::digest(self.body);
            format!("keep_{:02x}{:02x}{:02x}{:02x}", h[0], h[1], h[2], h[3])
        } else {
            slugify(self.body_name.trim())
        };
        let dir = repo_root().join("desk/bank/v1/staging").join(&slug);
        if let Err(err) = fs::create_dir_all(&dir) {
            self.status = format!("KEEP failed: {err}");
            return;
        }
        if let Err(err) = fs::write(dir.join(format!("{slug}.body240")), self.body) {
            self.status = format!("KEEP failed: {err}");
            return;
        }
        // compiled-v1 cartridge — same shape the audition slot publishes
        let labels = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];
        let keyframes: Vec<serde_json::Value> = (0..CORNERS)
            .map(|ci| {
                serde_json::json!({
                    "label": labels[ci],
                    "boost": 1.0,
                    "stages": [],
                    "packedWords": words[ci].iter().map(|row| row.to_vec()).collect::<Vec<_>>(),
                })
            })
            .collect();
        let cart = serde_json::json!({
            "format": "compiled-v1",
            "name": slug,
            "sampleRate": SR,
            "keyframes": keyframes,
        });
        let _ = serde_json::to_vec_pretty(&cart)
            .map(|j| fs::write(dir.join(format!("{slug}.cart.json")), j));
        let sidecar = SaveSidecar {
            note:
                "TRENCH FORGE keeper source. Bytes packed through trench_core::compiler::pack_body.",
            sections: &self.sections,
            peak_shelf_patch: self.patch_linked.then_some(&self.patch),
        };
        let _ = serde_json::to_vec_pretty(&sidecar)
            .map(|j| fs::write(dir.join(format!("{slug}.source.json")), j));
        let audit = serde_json::json!({
            "grid": AUDIT_N,
            "max_abs_pole": maxr,
            "unstable_cells": unstable,
            "levels_db": levels,
            "note": "17×17 Morph×Q max |H| dB through the packed word-lerp (rows Q, cols Morph)",
        });
        let _ = serde_json::to_vec_pretty(&audit)
            .map(|j| fs::write(dir.join(format!("{slug}.audit.json")), j));
        let sha: String = sha2::Sha256::digest(self.body)
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect();
        let created_unix = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let provenance = serde_json::json!({
            "sha256_body240": sha,
            "created_unix": created_unix,
            "encoder": "trench_core::compiler::pack_body",
            "surface": "forge-gpu-painter",
            "format": "240 bytes = 4 corners × 6 second-order sections × 5 packed u16",
            "q_link": self.q_link,
            "pending": "Tyson's verdict + BANK.md row complete the bank entry",
        });
        let _ = serde_json::to_vec_pretty(&provenance)
            .map(|j| fs::write(dir.join(format!("{slug}.provenance.json")), j));
        self.status = format!(
            "KEEP staged → {} (stable, max pole {:.4}) — verdict + BANK.md row are the producer's",
            dir.display(),
            maxr
        );
    }

    fn write_audition_slot(&self) -> Result<PathBuf, String> {
        let words = self.words();
        let labels = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];
        let keyframes: Vec<serde_json::Value> = (0..CORNERS)
            .map(|ci| {
                serde_json::json!({
                    "label": labels[ci],
                    "boost": 1.0,
                    "stages": [],
                    "packedWords": words[ci].iter().map(|row| row.to_vec()).collect::<Vec<_>>(),
                })
            })
            .collect();
        let cart = serde_json::json!({
            "format": "compiled-v1",
            "name": if self.body_name.trim().is_empty() { "forge audition" } else { self.body_name.trim() },
            "sampleRate": SR,
            "keyframes": keyframes,
        });
        let docs = std::env::var("USERPROFILE")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("."))
            .join("Documents")
            .join("TRENCH");
        fs::create_dir_all(&docs).map_err(|e| e.to_string())?;
        let path = docs.join("authoring_slot.json");
        let json = serde_json::to_vec_pretty(&cart).map_err(|e| e.to_string())?;
        fs::write(&path, json).map_err(|e| e.to_string())?;
        Ok(path)
    }

    fn publish_audition_slot(&mut self) {
        match self.write_audition_slot() {
            Ok(path) => {
                self.status = format!(
                    "audition slot published → {} — select Forge Audition in the plugin",
                    path.display()
                );
            }
            Err(err) => self.status = format!("audition publish failed: {err}"),
        }
    }

    fn run_action(&mut self, action: MenuAction) {
        match action {
            MenuAction::SeedPeakShelf => {
                self.push_undo();
                self.patch = model::peak_shelf::PeakShelfPatch::default();
                self.apply_patch();
                self.status =
                    "Peak/Shelf Morph — set the LOW and HIGH frames, sweep MORPH, raise PRESSURE"
                        .into();
            }
            MenuAction::StartRow(lane, row) => self.start_manifest_row(lane, row),
            MenuAction::SeedDefault => self.seed_default(),
            MenuAction::SeedLowpass => self.seed_lowpass(),
            MenuAction::SeedHighpass => self.seed_highpass(),
            MenuAction::SeedBandpass => self.seed_bandpass(),
            MenuAction::SeedNotchComb => self.seed_notch_comb(),
            MenuAction::SeedParametric => self.seed_parametric(),
            MenuAction::SeedPeaks => self.seed_peaks(),
            MenuAction::SeedVowel(i) => self.seed_vowel_pair(i),
            MenuAction::SeedTube(i) => self.seed_tube(i),
            MenuAction::SeedMetal(i) => self.seed_metal(i),
            MenuAction::SeedExact(i) => self.seed_exact(i),
            MenuAction::CopyCornerAll => self.copy_corner_to_all(),
            MenuAction::DeriveQ => self.derive_q_corners(),
            MenuAction::QuantSet(q) => self.quantize = q,
            MenuAction::KeySet(k) => self.key_root = k,
            MenuAction::ScopeSet(s) => self.scope = s,
            MenuAction::SeedScratch => self.seed_scratch(),
            MenuAction::RestoreAutosave => self.restore_autosave(),
            MenuAction::OverlaySet(v) => self.overlay_vowel = v,
            MenuAction::ToggleGhosts => self.show_ghosts = !self.show_ghosts,
            MenuAction::ToggleBark => self.bark = !self.bark,
        }
    }

    // ── input ─────────────────────────────────────────────────────────────────

    fn key_input(&mut self, ctx: &egui::Context) {
        // name field captures typing
        if self.name_active {
            let events = ctx.input(|i| i.events.clone());
            for ev in events {
                match ev {
                    Event::Text(s) => {
                        if self.body_name.len() < 48 {
                            self.body_name.push_str(&s);
                        }
                    }
                    Event::Key {
                        key: Key::Backspace,
                        pressed: true,
                        ..
                    } => {
                        self.body_name.pop();
                    }
                    Event::Key {
                        key: Key::Enter | Key::Escape,
                        pressed: true,
                        ..
                    } => {
                        self.name_active = false;
                    }
                    _ => {}
                }
            }
            return;
        }
        ctx.input(|i| {
            if i.modifiers.ctrl && i.key_pressed(Key::Z) {
                if i.modifiers.shift {
                    self.do_redo();
                } else {
                    self.do_undo();
                }
            }
            if i.modifiers.ctrl && i.key_pressed(Key::Y) {
                self.do_redo();
            }
            if i.key_pressed(Key::Num1) {
                self.select_corner(CornerKey::M0Q0);
            }
            if i.key_pressed(Key::Num2) {
                self.select_corner(CornerKey::M100Q0);
            }
            if i.key_pressed(Key::Num3) {
                self.select_corner(CornerKey::M0Q100);
            }
            if i.key_pressed(Key::Num4) {
                self.select_corner(CornerKey::M100Q100);
            }
            if i.key_pressed(Key::Space) {
                self.sweep = !self.sweep;
                self.sweep_t0 = Instant::now();
            }
            if i.key_pressed(Key::P) {
                self.toggle_play();
            }
            if i.key_pressed(Key::L) {
                let s = self.selected_stage;
                self.sections[s].locked = !self.sections[s].locked;
                self.status = format!(
                    "S{} {}",
                    s + 1,
                    if self.sections[s].locked {
                        "locked — edits and fits hold it"
                    } else {
                        "unlocked"
                    }
                );
            }
            if i.key_pressed(Key::E) {
                let s = self.selected_stage;
                self.push_undo();
                self.sections[s].on = !self.sections[s].on;
                self.rebuild_body();
            }
            if i.key_pressed(Key::Delete) {
                if let Some(k) = self.selected_pin {
                    if k < self.pins.len() {
                        self.pins.remove(k);
                        self.selected_pin = None;
                        self.status = "target removed".into();
                    }
                }
            }
            if i.key_pressed(Key::Escape) && self.open_menu.is_none() && !self.pins.is_empty() {
                self.pins.clear();
                self.selected_pin = None;
                self.status = "all targets cleared".into();
            }
            if i.key_pressed(Key::ArrowRight) {
                self.selected_stage = (self.selected_stage + 1) % STAGES;
            }
            if i.key_pressed(Key::ArrowLeft) {
                self.selected_stage = (self.selected_stage + STAGES - 1) % STAGES;
            }
            // frames are the working unit: Tab flips low ⇄ high morph frame,
            // Shift+Tab flips the Q row
            if i.key_pressed(Key::Tab) {
                let target = if i.modifiers.shift {
                    self.selected_corner.q_mirror()
                } else {
                    self.selected_corner.morph_mirror()
                };
                self.select_corner(target);
                self.status = format!(
                    "editing {} {} — Tab: other frame · Shift+Tab: other Q row",
                    target.code(),
                    target.label()
                );
            }
        });
        let dropped = ctx.input(|i| i.raw.dropped_files.clone());
        if !dropped.is_empty() {
            let shift = ctx.input(|i| i.modifiers.shift);
            if let Some(path) = dropped[0].path.clone() {
                self.fit_wav(&path, shift);
            }
        }
    }
}

// ── layout ────────────────────────────────────────────────────────────────────

struct Layout {
    bar1: Rect,
    bar2: Rect,
    plot: Rect,
    rail: Option<Rect>,
    strip: Rect,
    values: Rect,
    front: Rect,
    statusbar: Rect,
}

fn layout(rect: Rect, show_rail: bool) -> Layout {
    let bar1_h = 34.0;
    let bar2_h = 26.0;
    let strip_h = if show_rail { 70.0 } else { 0.0 };
    // front mode: the values row becomes the Peak/Shelf band (global row +
    // LOW frame row + HIGH frame row)
    let values_h = if show_rail { 30.0 } else { 104.0 };
    let status_h = if show_rail { 22.0 } else { 0.0 };
    let rail_w = 220.0;
    let bar1 = Rect::from_min_max(rect.min, Pos2::new(rect.right(), rect.top() + bar1_h));
    let bar2 = Rect::from_min_max(
        bar1.left_bottom(),
        Pos2::new(rect.right(), bar1.bottom() + bar2_h),
    );
    let work_top = bar2.bottom();
    let statusbar = if show_rail {
        Rect::from_min_max(Pos2::new(rect.left(), rect.bottom() - status_h), rect.max)
    } else {
        Rect::NOTHING
    };
    let values = Rect::from_min_max(
        Pos2::new(rect.left(), rect.bottom() - status_h - values_h),
        Pos2::new(rect.right(), rect.bottom() - status_h),
    );
    let strip = if show_rail {
        Rect::from_min_max(
            Pos2::new(rect.left(), values.top() - strip_h),
            Pos2::new(rect.right(), values.top()),
        )
    } else {
        Rect::NOTHING
    };
    let work_bottom = if show_rail { strip.top() } else { values.top() };
    let work = Rect::from_min_max(
        Pos2::new(rect.left() + 8.0, work_top + 6.0),
        Pos2::new(rect.right() - 8.0, work_bottom - 6.0),
    );
    let (plot, rail) = if show_rail {
        (
            Rect::from_min_max(
                work.min,
                Pos2::new(work.right() - rail_w - 6.0, work.bottom()),
            ),
            Some(Rect::from_min_max(
                Pos2::new(work.right() - rail_w, work.top()),
                work.max,
            )),
        )
    } else {
        (work, None)
    };
    Layout {
        bar1,
        bar2,
        plot,
        rail,
        strip,
        front: values, // same band; front mode paints frames, details mode values
        values,
        statusbar,
    }
}

// ── custom widget hit lists ───────────────────────────────────────────────────

struct Hit<T> {
    rect: Rect,
    value: T,
}

struct Frame {
    corner_chips: Vec<Hit<CornerKey>>,
    menu_chips: Vec<Hit<Menu>>,
    menu_items: Vec<Hit<MenuAction>>,
    menu_rect: Option<Rect>,
    morph_rect: Rect,
    q_rect: Rect,
    sweep_rect: Rect,
    name_rect: Rect,
    bake_rect: Rect,
    audition_rect: Rect,
    handles: Vec<(Pos2, usize, HandleKind)>,
    travel_handles: Vec<(Pos2, usize, HandleKind)>, // the other morph frame's dots
    cards: Vec<Hit<usize>>,
    locks: Vec<Hit<usize>>,
    value_fields: Vec<Hit<ValueField>>,
    on_rect: Rect,
    lock_rect: Rect,
    play_rect: Rect,
    qlink_rect: Rect,
    panels_rect: Rect,
    keep_rect: Rect,
    src_chips: Vec<Hit<AudioSrc>>,
    front_sliders: Vec<Hit<FrontSlider>>,
    surface_rect: Option<Rect>,
    sweepmap_rect: Option<Rect>,
    pin_handles: Vec<(Pos2, usize)>,
}

impl Default for Frame {
    fn default() -> Self {
        let z = Rect::NOTHING;
        Self {
            corner_chips: Vec::new(),
            menu_chips: Vec::new(),
            menu_items: Vec::new(),
            menu_rect: None,
            morph_rect: z,
            q_rect: z,
            sweep_rect: z,
            name_rect: z,
            bake_rect: z,
            audition_rect: z,
            handles: Vec::new(),
            travel_handles: Vec::new(),
            cards: Vec::new(),
            locks: Vec::new(),
            value_fields: Vec::new(),
            on_rect: z,
            lock_rect: z,
            play_rect: z,
            qlink_rect: z,
            panels_rect: z,
            keep_rect: z,
            src_chips: Vec::new(),
            front_sliders: Vec::new(),
            surface_rect: None,
            sweepmap_rect: None,
            pin_handles: Vec::new(),
        }
    }
}

// ── update loop ───────────────────────────────────────────────────────────────

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        BARK.store(self.bark, std::sync::atomic::Ordering::Relaxed);
        self.key_input(ctx);

        if self.sweep {
            let t = self.sweep_t0.elapsed().as_secs_f32();
            let phase = (t / 4.0).fract();
            self.morph = if phase < 0.5 {
                phase * 2.0
            } else {
                2.0 - phase * 2.0
            };
            self.recompute_response();
            ctx.request_repaint();
            self.metered_frame = true;
        }
        self.pump_worker(ctx);
        // display follower: visible sections chase the latest solved state,
        // critically damped — motion at frame rate, solver only sets the target
        let raw_dt = self.last_frame.elapsed().as_secs_f32();
        let dt = raw_dt.clamp(0.0, 0.05);
        self.last_frame = Instant::now();
        // jank meter — only frames we *asked* for (continuous animation) count;
        // idle event-driven gaps are legitimately long and would poison it
        if self.metered_frame && raw_dt < 0.25 {
            let ms = raw_dt * 1000.0;
            self.frame_ms_avg = if self.frame_ms_avg == 0.0 {
                ms
            } else {
                self.frame_ms_avg * 0.95 + ms * 0.05
            };
            self.frame_ms_peak = (self.frame_ms_peak * 0.995).max(ms);
        }
        self.metered_frame = false;
        if let Some((_, _, t0)) = &self.hint {
            if t0.elapsed().as_secs_f32() > 1.8 {
                self.hint = None;
            } else {
                ctx.request_repaint();
                self.metered_frame = true;
            }
        }
        if let Some(target) = self.solve_target.clone() {
            // while the hand is down the material model (the solver's own viscous
            // follow) is the only smoothing that should read as lag — chase fast.
            let rate = if self.drag.is_some() { 60.0 } else { 25.0 };
            let alpha = 1.0 - (-dt * rate).exp();
            self.sections = lerp_sections(&self.sections, &target, alpha);
            if sections_close(&self.sections, &target) {
                self.sections = target;
                self.solve_target = None;
            }
            self.rebuild_body();
            ctx.request_repaint();
            self.metered_frame = true;
        }
        if self.drag.is_some() {
            ctx.request_repaint();
            self.metered_frame = true;
        }
        let pointer_down = ctx.input(|i| i.pointer.primary_down());
        let idle = !pointer_down && self.last_edit.elapsed() > Duration::from_millis(140);
        if self.heat_dirty && !self.heat_inflight && (self.heat_texture.is_none() || idle) {
            if self
                .job_tx
                .send(Job::Heat {
                    words: self.words(),
                    q: self.q,
                })
                .is_ok()
            {
                self.heat_inflight = true;
                self.heat_dirty = false;
            }
        }
        if self.audit_dirty && !self.audit_inflight && (self.audit_texture.is_none() || idle) {
            if self
                .job_tx
                .send(Job::Audit {
                    words: self.words(),
                })
                .is_ok()
            {
                self.audit_inflight = true;
                self.audit_dirty = false; // re-set by any later edit; lamp watches inflight too
            }
        }
        if self.heat_dirty
            || self.audit_dirty
            || self.solve_inflight
            || self.heat_inflight
            || self.audit_inflight
            || self.optimize_inflight
        {
            ctx.request_repaint();
            self.metered_frame = true;
        }
        self.sync_audio(); // morph/Q follow live, including during sweep

        // hold C: overlay the opposite-Q cascade (the desk sheets' right plot,
        // Q0 vs Q100 at the current morph) — recomputed live, dropped on release
        let qhold = self.boot_qcompare || (!self.name_active && ctx.input(|i| i.key_down(Key::C)));
        if qhold {
            let words = self.words();
            let q_other = if self.q < 0.5 { 1.0 } else { 0.0 };
            let live = live_biquads(&words, self.morph, q_other);
            let trig = grid_trig(FREQ_BINS);
            let row: Vec<f32> = (0..FREQ_BINS)
                .map(|i| cascade_db_c(&live, trig[i].0, trig[i].1))
                .collect();
            self.qcompare = Some(row);
            ctx.request_repaint();
            self.metered_frame = true;
        } else if self.qcompare.is_some() {
            self.qcompare = None;
        }

        // hold H: the controls card
        self.show_help = self.boot_help || (!self.name_active && ctx.input(|i| i.key_down(Key::H)));
        if self.show_help {
            ctx.request_repaint();
            self.metered_frame = true;
        }

        // autosave 30 s after an edit — cheap insurance; scratch boot stays
        // the law, restore lives in SEED ▸ restore last autosave
        if self.last_edit > self.autosaved_at
            && self.autosaved_at.elapsed() > Duration::from_secs(30)
        {
            let dir = repo_root().join("dev/tmp/forge_gpu_painter");
            let _ = fs::create_dir_all(&dir);
            let sidecar = SaveSidecar {
                note: "autosave",
                sections: &self.sections,
                peak_shelf_patch: self.patch_linked.then_some(&self.patch),
            };
            if let Ok(json) = serde_json::to_vec_pretty(&sidecar) {
                let _ = fs::write(dir.join("autosave.source.json"), json);
            }
            self.autosaved_at = Instant::now();
        }

        egui::CentralPanel::default()
            .frame(egui::Frame::none().fill(BG))
            .show(ctx, |ui| {
                let rect = ui.max_rect();
                let resp = ui.allocate_rect(rect, Sense::click_and_drag());
                let p = ui.painter().clone();
                let lay = layout(rect, self.show_rail);

                let mut frame = Frame::default();
                self.draw_bar1(&p, lay.bar1, &mut frame);
                self.draw_bar2(&p, lay.bar2, &mut frame);
                self.draw_plot(&p, lay.plot, &mut frame);
                if self.show_rail {
                    if let Some(rail) = lay.rail {
                        self.draw_rail(&p, rail, &mut frame);
                    }
                    self.draw_strip(&p, lay.strip, &mut frame);
                    self.draw_status(&p, lay.statusbar);
                    self.draw_values(&p, lay.values, &mut frame);
                } else {
                    self.draw_front(&p, lay.front, &mut frame);
                }
                self.draw_hint(&p, lay.plot);
                self.draw_help(&p, lay.plot);
                // menu popup last (over everything)
                if self.open_menu.is_some() {
                    self.draw_menu(&p, &mut frame);
                }

                self.interact(ctx, &resp, lay, frame);
            });
    }
}

impl App {
    // ── bar 1: title · corners · morph/q · sweep · name · bake/audition · lamp ─

    fn draw_bar1(&self, p: &egui::Painter, bar: Rect, frame: &mut Frame) {
        p.rect_filled(bar, 0.0, PANEL);
        p.line_segment(
            [bar.left_bottom(), bar.right_bottom()],
            Stroke::new(1.0, EDGE),
        );
        let cy = bar.center().y;
        let x = bar.left() + 14.0;
        p.text(
            Pos2::new(x, cy),
            Align2::LEFT_CENTER,
            "TRENCH FORGE",
            FontId::monospace(14.0),
            TRUTH,
        );
        p.text(
            Pos2::new(x + 142.0, cy),
            Align2::LEFT_CENTER,
            "six filters -> one body",
            FontId::monospace(9.5),
            TEXT_DIM,
        );

        // right side, packed right-to-left
        let mut rx = bar.right() - 14.0;
        // lamp + audit text
        let (lcol, ltext) = if self.audit_dirty || self.audit_inflight {
            (EMBER, "checking…".to_string())
        } else if self.audit_unstable > 0 {
            (FAULT, "unstable".to_string())
        } else {
            (painter::theme::GOOD, "stable".to_string())
        };
        let galley_w = ltext.len() as f32 * 6.4;
        p.text(
            Pos2::new(rx, cy),
            Align2::RIGHT_CENTER,
            &ltext,
            FontId::monospace(10.5),
            lcol,
        );
        rx -= galley_w + 12.0;
        p.circle_filled(Pos2::new(rx, cy), 5.0, lcol);
        rx -= 18.0;

        let keep_r = Rect::from_min_size(Pos2::new(rx - 58.0, cy - 11.0), Vec2::new(58.0, 22.0));
        chip(p, keep_r, "KEEP", false, TRUTH);
        frame.keep_rect = keep_r;
        rx -= 66.0;
        let aud_r = Rect::from_min_size(Pos2::new(rx - 86.0, cy - 11.0), Vec2::new(86.0, 22.0));
        chip(
            p,
            aud_r,
            "AUDITION",
            false,
            Color32::from_rgb(127, 225, 180),
        );
        frame.audition_rect = aud_r;
        rx -= 94.0;
        let bake_r = Rect::from_min_size(Pos2::new(rx - 60.0, cy - 11.0), Vec2::new(60.0, 22.0));
        chip(p, bake_r, "BAKE", false, section_color(0));
        frame.bake_rect = bake_r;
        rx -= 68.0;
        let name_r = Rect::from_min_size(Pos2::new(rx - 150.0, cy - 11.0), Vec2::new(150.0, 22.0));
        p.rect_filled(name_r, 4.0, Color32::from_rgb(12, 12, 15));
        p.rect_stroke(
            name_r,
            4.0,
            Stroke::new(1.0, if self.name_active { ICE } else { EDGE }),
        );
        let shown = if self.body_name.is_empty() && !self.name_active {
            "body name".to_string()
        } else {
            format!(
                "{}{}",
                self.body_name,
                if self.name_active { "_" } else { "" }
            )
        };
        p.text(
            name_r.left_center() + Vec2::new(7.0, 0.0),
            Align2::LEFT_CENTER,
            shown,
            FontId::monospace(11.0),
            if self.body_name.is_empty() && !self.name_active {
                TEXT_DIM
            } else {
                TEXT
            },
        );
        frame.name_rect = name_r;
    }

    // ── bar 2: menus + quick readouts ─────────────────────────────────────────

    fn draw_bar2(&self, p: &egui::Painter, bar: Rect, frame: &mut Frame) {
        p.rect_filled(bar, 0.0, Color32::from_rgb(17, 18, 22));
        p.line_segment(
            [bar.left_bottom(), bar.right_bottom()],
            Stroke::new(1.0, EDGE),
        );
        let cy = bar.center().y;
        let mut x = bar.left() + 14.0;

        // ── tools cluster: the five menus
        let quant_short = match self.quantize {
            Quantize::Measured => "measured",
            Quantize::Tet => "12-TET",
            Quantize::Off => "off",
        };
        let menus: Vec<(Menu, String)> = if self.show_rail {
            vec![
                (Menu::Seed, "START ▾".into()),
                (Menu::Corners, "CORNERS ▾".into()),
                (Menu::Quantize, format!("SNAP: {quant_short} ▾")),
                (Menu::Scope, format!("EDIT: {} ▾", self.scope.label())),
            ]
        } else {
            vec![(Menu::Seed, "START ▾".into())]
        };
        for (menu, label) in menus {
            let w = label.chars().count() as f32 * 6.6 + 18.0;
            let r = Rect::from_min_size(Pos2::new(x, cy - 10.0), Vec2::new(w, 20.0));
            chip(p, r, &label, self.open_menu == Some(menu), TEXT);
            frame.menu_chips.push(Hit {
                rect: r,
                value: menu,
            });
            x += w + 8.0;
        }
        if self.quantize == Quantize::Tet {
            let label = format!("{} minor", NOTES[self.key_root]);
            p.text(
                Pos2::new(x, cy),
                Align2::LEFT_CENTER,
                &label,
                FontId::monospace(10.5),
                TEXT_DIM,
            );
            x += label.chars().count() as f32 * 6.6 + 10.0;
        }
        if self.show_rail {
            // Q LINK: while lit, Q100 corners derive from the Q0 rows (the measured
            // radius rule); editing a Q100 corner breaks it out automatically
            let ql_r = Rect::from_min_size(Pos2::new(x, cy - 10.0), Vec2::new(62.0, 20.0));
            chip(p, ql_r, "LINK Q", self.q_link, ICE);
            frame.qlink_rect = ql_r;
        }

        let mut rx = bar.right() - 14.0;
        let panels_r =
            Rect::from_min_size(Pos2::new(rx - 74.0, cy - 10.0), Vec2::new(74.0, 20.0));
        chip(p, panels_r, "DETAILS", self.show_rail, TEXT);
        frame.panels_rect = panels_r;
        rx -= 82.0;

        // front mode owns MORPH/PRESSURE in the frame band below — bar2 only
        // carries them in the details workbench
        if self.show_rail {
            let q_r =
                Rect::from_min_size(Pos2::new(rx - 112.0, cy - 10.0), Vec2::new(112.0, 20.0));
            slider_chip(p, q_r, "Q", self.q, ICE);
            frame.q_rect = q_r;
            rx -= 120.0;

            let morph_r =
                Rect::from_min_size(Pos2::new(rx - 142.0, cy - 10.0), Vec2::new(142.0, 20.0));
            slider_chip(p, morph_r, "MORPH", self.morph, section_color(0));
            frame.morph_rect = morph_r;
        }

        // no right-side readout chips: the live point is announced once (canvas
        // top-left), the selected section once (the value row below the strip).
    }

    // ── front band: the Peak/Shelf Morph surface ──────────────────────────────
    // global row: SWEEP · PLAY · source · MORPH · PRESSURE · MASTER
    // LOW FRAME:  FREQ | SHELF | PEAK        HIGH FRAME: FREQ | SHELF | PEAK

    fn draw_front(&self, p: &egui::Painter, band: Rect, frame: &mut Frame) {
        use painter::theme::{CORNER, GOOD};
        p.rect_filled(band, 0.0, PANEL);
        p.line_segment(
            [band.left_top(), band.right_top()],
            Stroke::new(1.0, EDGE),
        );
        let row_h = 22.0;
        let pad = 14.0;
        let gap = (band.height() - 3.0 * row_h) / 4.0;
        let row_y = |i: f32| band.top() + gap * (i + 1.0) + row_h * i;

        // ── global row
        let y = row_y(0.0);
        let mut x = band.left() + pad;
        let sweep_r = Rect::from_min_size(Pos2::new(x, y), Vec2::new(62.0, row_h));
        chip(p, sweep_r, "SWEEP", self.sweep, ICE);
        frame.sweep_rect = sweep_r;
        x += 70.0;
        let play_r = Rect::from_min_size(Pos2::new(x, y), Vec2::new(56.0, row_h));
        chip(p, play_r, if self.playing { "PAUSE" } else { "PLAY" }, self.playing, GOOD);
        frame.play_rect = play_r;
        x += 64.0;
        for (src, label) in [
            (AudioSrc::Noise, "NOISE"),
            (AudioSrc::Saw, "SAW"),
            (AudioSrc::Pad, "PAD"),
        ] {
            let w = label.len() as f32 * 6.6 + 14.0;
            let r = Rect::from_min_size(Pos2::new(x, y), Vec2::new(w, row_h));
            chip(p, r, label, self.audio_src == src, TEXT_DIM);
            frame.src_chips.push(Hit { rect: r, value: src });
            x += w + 6.0;
        }
        x += 10.0;
        // MORPH · PRESSURE · MASTER fill the rest of the row
        let right = band.right() - pad;
        let remaining = right - x;
        let s_gap = 12.0;
        let morph_w = (remaining - 2.0 * s_gap) * 0.42;
        let press_w = (remaining - 2.0 * s_gap) * 0.42;
        let master_w = (remaining - 2.0 * s_gap) * 0.16;
        let morph_r = Rect::from_min_size(Pos2::new(x, y), Vec2::new(morph_w, row_h));
        slider_chip(p, morph_r, "MORPH", self.morph, CORNER[0]);
        frame.morph_rect = morph_r;
        x += morph_w + s_gap;
        let press_r = Rect::from_min_size(Pos2::new(x, y), Vec2::new(press_w, row_h));
        slider_chip(p, press_r, "PRESSURE", self.q, CORNER[3]);
        frame.q_rect = press_r;
        x += press_w + s_gap;
        let master_t = ((self.patch.master_peak_db + 12.0) / 24.0).clamp(0.0, 1.0);
        let master_r = Rect::from_min_size(Pos2::new(x, y), Vec2::new(master_w, row_h));
        front_slider(
            p,
            master_r,
            "MASTER",
            &format!("{:+.1} dB", self.patch.master_peak_db),
            master_t,
            TEXT,
        );
        frame.front_sliders.push(Hit {
            rect: master_r,
            value: FrontSlider::Master,
        });

        // ── frame rows
        for (i, (tag, fc, color, sliders)) in [
            (
                "LOW",
                &self.patch.low,
                CORNER[0],
                [FrontSlider::LowFreq, FrontSlider::LowShelf, FrontSlider::LowPeak],
            ),
            (
                "HIGH",
                &self.patch.high,
                CORNER[1],
                [
                    FrontSlider::HighFreq,
                    FrontSlider::HighShelf,
                    FrontSlider::HighPeak,
                ],
            ),
        ]
        .into_iter()
        .enumerate()
        {
            let y = row_y(i as f32 + 1.0);
            let mut x = band.left() + pad;
            p.text(
                Pos2::new(x, y + row_h * 0.5),
                Align2::LEFT_CENTER,
                format!("{tag} FRAME"),
                FontId::monospace(10.5),
                color,
            );
            x += 92.0;
            let right = band.right() - pad;
            let w = (right - x - 2.0 * 12.0) / 3.0;
            let freq_t = (fc.freq_hz / F_MIN).ln() / (F_MAX / F_MIN).ln();
            let shelf_t = (fc.shelf + 64.0) / 127.0;
            let peak_t = (fc.peak_db + 12.0) / 24.0;
            let shelf_word = if fc.shelf < -21.0 {
                "low-pass"
            } else if fc.shelf > 21.0 {
                "high-pass"
            } else {
                "mid shelf"
            };
            let cells = [
                ("FREQ", fmt_hz(fc.freq_hz), freq_t),
                ("SHELF", format!("{:+.0} {shelf_word}", fc.shelf), shelf_t),
                ("PEAK", format!("{:+.1} dB", fc.peak_db), peak_t),
            ];
            for (j, (label, value, t)) in cells.into_iter().enumerate() {
                let r = Rect::from_min_size(Pos2::new(x, y), Vec2::new(w, row_h));
                front_slider(p, r, label, &value, t.clamp(0.0, 1.0), color);
                frame.front_sliders.push(Hit {
                    rect: r,
                    value: sliders[j],
                });
                x += w + 12.0;
            }
        }

        // link state, terse, bottom-right above the band
        let note = if self.patch_linked {
            "frame controls drive the body"
        } else {
            "detached — touch a frame control to take over"
        };
        p.text(
            Pos2::new(band.right() - pad, band.top() + 3.0),
            Align2::RIGHT_TOP,
            note,
            FontId::monospace(8.5),
            TEXT_DIM,
        );
    }

    /// A FREQ/SHELF/PEAK/MASTER move recompiles the whole patch through
    /// compile_peak_shelf → params168 → pack_body. The compiler owns all four
    /// corners while linked (q_link stays off so the derived-Q rule never
    /// clobbers the pressurized C2/C3 postures).
    fn apply_front_slider(&mut self, s: FrontSlider, t: f32) {
        let t = t.clamp(0.0, 1.0);
        let freq = F_MIN * (F_MAX / F_MIN).powf(t);
        let shelf = -64.0 + t * 127.0;
        let peak = -12.0 + t * 24.0;
        match s {
            FrontSlider::LowFreq => self.patch.low.freq_hz = freq,
            FrontSlider::LowShelf => self.patch.low.shelf = shelf,
            FrontSlider::LowPeak => self.patch.low.peak_db = peak,
            FrontSlider::HighFreq => self.patch.high.freq_hz = freq,
            FrontSlider::HighShelf => self.patch.high.shelf = shelf,
            FrontSlider::HighPeak => self.patch.high.peak_db = peak,
            FrontSlider::Master => self.patch.master_peak_db = peak,
        }
        self.apply_patch();
    }

    fn apply_patch(&mut self) {
        self.q_link = false;
        self.sections = model::peak_shelf::compile_peak_shelf(&self.patch);
        self.patch_linked = true;
        self.rebuild_body();
    }

    // ── menu popup ────────────────────────────────────────────────────────────

    fn start_header(label: &str) -> StartEntry {
        StartEntry {
            label: label.to_string(),
            note: String::new(),
            action: None,
            preview: StartPreview::None,
            badge: None,
            quarantined: false,
        }
    }

    fn start_row(
        label: impl Into<String>,
        note: impl Into<String>,
        action: Option<MenuAction>,
        preview: StartPreview,
    ) -> StartEntry {
        StartEntry {
            label: label.into(),
            note: note.into(),
            action,
            preview,
            badge: None,
            quarantined: false,
        }
    }

    /// The four provenance lanes from the START manifest (built by
    /// tools/build_forge_start_manifest.py). Every row carries one badge:
    /// COMPILE EXACT · IMPORT EXACT · OVERLAY · APPROX. Quarantined rows
    /// stay visible with their reason — never silently hidden.
    fn start_menu_columns(&self) -> Vec<Vec<StartEntry>> {
        let Some(manifest) = &self.start_manifest else {
            return vec![vec![
                Self::start_header("no start manifest"),
                Self::start_row(
                    "Two-frame Peak/Shelf",
                    "FREQ · SHELF · PEAK per frame",
                    Some(MenuAction::SeedPeakShelf),
                    StartPreview::Peak,
                ),
                Self::start_row(
                    "Scratch",
                    "flat six-biquad body",
                    Some(MenuAction::SeedScratch),
                    StartPreview::Flat,
                ),
                Self::start_row(
                    "run tools/build_forge_start_manifest.py",
                    "builds the four provenance lanes",
                    None,
                    StartPreview::Flat,
                ),
            ]];
        };
        let mut columns: Vec<Vec<StartEntry>> = Vec::new();
        for (li, lane) in manifest.lanes.iter().enumerate() {
            let badge: &'static str = match lane.badge.as_str() {
                "COMPILE EXACT" => "COMPILE EXACT",
                "IMPORT EXACT" => "IMPORT EXACT",
                "OVERLAY" => "OVERLAY",
                _ => "APPROX",
            };
            let compact_lane = lane.id == "approx_starters";
            let mut col = vec![Self::start_header(&lane.title)];
            let mut sorted: Vec<(f32, StartEntry)> = Vec::new();
            for (ri, row) in lane.rows.iter().enumerate() {
                let preview = if compact_lane {
                    StartPreview::Flat // compact rows draw no mini plot
                } else {
                    match row.kind.as_str() {
                        "peak_shelf" => StartPreview::Peak,
                        "exact_skeleton" => self
                            .tables
                            .skeletons
                            .iter()
                            .position(|sk| Some(&sk.key) == row.exact_key.as_ref())
                            .map(StartPreview::Exact)
                            .unwrap_or(StartPreview::Flat),
                        "overlay" => row
                            .curves
                            .clone()
                            .map(StartPreview::Curves)
                            .unwrap_or(StartPreview::Flat),
                        _ => row
                            .body
                            .clone()
                            .map(StartPreview::Body)
                            .unwrap_or(StartPreview::Flat),
                    }
                };
                let mut entry = Self::start_row(
                    row.label.clone(),
                    row.note.clone(),
                    Some(MenuAction::StartRow(li, ri)),
                    preview,
                );
                entry.badge = Some(badge);
                // sort key: spectral centroid (low → high); sourceless rows
                // (templates) lead their lane
                let key = row
                    .body
                    .as_ref()
                    .or(row.curves.as_ref())
                    .and_then(|p| self.centroids.get(p))
                    .copied()
                    .unwrap_or(-1.0);
                sorted.push((key, entry));
            }
            sorted.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
            col.extend(sorted.into_iter().map(|(_, e)| e));
            // quarantine is listed under the imports lane — visible, reasoned
            if lane.id == "exact_imports" {
                col.push(Self::start_header("quarantine"));
                for q in &manifest.quarantine {
                    let mut e = Self::start_row(
                        q.label.clone(),
                        q.reason.clone(),
                        None,
                        StartPreview::Flat,
                    );
                    e.quarantined = true;
                    col.push(e);
                }
                col.push(Self::start_header("blank"));
                col.push(Self::start_row(
                    "Scratch",
                    "flat six-biquad body",
                    Some(MenuAction::SeedScratch),
                    StartPreview::Flat,
                ));
                col.push(Self::start_row(
                    "Restore autosave",
                    "last editable source",
                    Some(MenuAction::RestoreAutosave),
                    StartPreview::None,
                ));
            }
            columns.push(col);
        }
        columns
    }

    fn menu_entries(&self, menu: Menu) -> Vec<(String, Option<MenuAction>)> {
        match menu {
            Menu::Seed => {
                let mut v: Vec<(String, Option<MenuAction>)> = vec![
                    (
                        "start from scratch (flat)".into(),
                        Some(MenuAction::SeedScratch),
                    ),
                    (
                        "restore last autosave".into(),
                        Some(MenuAction::RestoreAutosave),
                    ),
                    ("— template —".into(), None),
                    ("default template".into(), Some(MenuAction::SeedDefault)),
                    ("— type families —".into(), None),
                    (
                        "low-pass sweep (resonant)".into(),
                        Some(MenuAction::SeedLowpass),
                    ),
                    (
                        "high-pass (zeros pinned low)".into(),
                        Some(MenuAction::SeedHighpass),
                    ),
                    (
                        "band-pass (guarded resonator)".into(),
                        Some(MenuAction::SeedBandpass),
                    ),
                    (
                        "notch comb / phase-shifter".into(),
                        Some(MenuAction::SeedNotchComb),
                    ),
                    (
                        "parametric boost (EQ)".into(),
                        Some(MenuAction::SeedParametric),
                    ),
                    ("six resonant peaks".into(), Some(MenuAction::SeedPeaks)),
                    ("— vowel formants (measured) —".into(), None),
                ];
                for (i, (_, _, label)) in VOWEL_PAIRS.iter().enumerate() {
                    v.push(((*label).into(), Some(MenuAction::SeedVowel(i))));
                }
                v.push(("— physical series —".into(), None));
                for (i, f0) in TUBE_F0.iter().enumerate() {
                    v.push((
                        format!("tube partials × {f0:.0} Hz"),
                        Some(MenuAction::SeedTube(i)),
                    ));
                }
                for (i, f0) in METAL_F0.iter().enumerate() {
                    v.push((
                        format!("struck metal × {f0:.0} Hz"),
                        Some(MenuAction::SeedMetal(i)),
                    ));
                }
                if !self.tables.skeletons.is_empty() {
                    v.push(("— verified starts —".into(), None));
                    for (i, s) in self.tables.skeletons.iter().enumerate() {
                        v.push((s.label.clone(), Some(MenuAction::SeedExact(i))));
                    }
                }
                v.push(("— fit —".into(), None));
                v.push(("LPC fit: drop a WAV on the window".into(), None));
                v.push(("(plain = low frame · Shift = high frame)".into(), None));
                v
            }
            Menu::Corners => vec![
                (
                    "copy this corner → all corners".into(),
                    Some(MenuAction::CopyCornerAll),
                ),
                (
                    "derive Q100 from Q0 (radius → rim)".into(),
                    Some(MenuAction::DeriveQ),
                ),
            ],
            Menu::Quantize => {
                let mut v: Vec<(String, Option<MenuAction>)> =
                    [Quantize::Measured, Quantize::Tet, Quantize::Off]
                        .iter()
                        .map(|q| {
                            (
                                format!(
                                    "{}{}",
                                    if *q == self.quantize { "● " } else { "  " },
                                    q.label()
                                ),
                                Some(MenuAction::QuantSet(*q)),
                            )
                        })
                        .collect();
                if self.quantize == Quantize::Tet {
                    v.push(("— key —".into(), None));
                    for (i, n) in NOTES.iter().enumerate() {
                        v.push((
                            format!(
                                "{}{} minor",
                                if i == self.key_root { "● " } else { "  " },
                                n
                            ),
                            Some(MenuAction::KeySet(i)),
                        ));
                    }
                }
                v
            }
            Menu::Scope => [EditScope::Corner, EditScope::Frame, EditScope::All]
                .iter()
                .map(|s| {
                    (
                        format!(
                            "{}{}",
                            if *s == self.scope { "● " } else { "  " },
                            s.label()
                        ),
                        Some(MenuAction::ScopeSet(*s)),
                    )
                })
                .collect(),
            Menu::Overlay => {
                let mut v: Vec<(String, Option<MenuAction>)> = vec![
                    (
                        format!(
                            "{}off",
                            if self.overlay_vowel.is_none() {
                                "● "
                            } else {
                                "  "
                            }
                        ),
                        Some(MenuAction::OverlaySet(None)),
                    ),
                    ("— vowel formants (Peterson-Barney) —".into(), None),
                ];
                for (i, vw) in self.tables.vowels.iter().enumerate() {
                    v.push((
                        format!(
                            "{}{}   {:.0} / {:.0} / {:.0} Hz",
                            if self.overlay_vowel == Some(i) {
                                "● "
                            } else {
                                "  "
                            },
                            vw.0,
                            vw.1,
                            vw.2,
                            vw.3,
                        ),
                        Some(MenuAction::OverlaySet(Some(i))),
                    ));
                }
                v
            }
            Menu::View => vec![
                (
                    format!(
                        "{}ear-spaced frequency axis",
                        if self.bark { "● " } else { "  " }
                    ),
                    Some(MenuAction::ToggleBark),
                ),
                (
                    format!(
                        "{}morph frame ghosts",
                        if self.show_ghosts { "● " } else { "  " }
                    ),
                    Some(MenuAction::ToggleGhosts),
                ),
            ],
        }
    }

    fn skeleton_preview_body(&self, which: usize) -> Option<[u8; 240]> {
        let sk = self.tables.skeletons.get(which)?;
        let mut params = Vec::with_capacity(CORNERS * STAGES * 7);
        for key in CornerKey::ALL {
            let hi = key.morph_q().0 > 0.5;
            for si in 0..STAGES {
                if let Some(row) = sk.sections.get(si) {
                    let pole_hz = if hi { row.pole_hz_hi } else { row.pole_hz_lo };
                    let pole_r = if hi { row.pole_r_hi } else { row.pole_r_lo };
                    let zero_hz = if hi { row.zero_hz_hi } else { row.zero_hz_lo };
                    let zero_r = if hi { row.zero_r_hi } else { row.zero_r_lo };
                    let gain_db = if hi { row.gain_db_hi } else { row.gain_db_lo };
                    params.extend_from_slice(&[
                        1.0,
                        pole_hz as f64,
                        pole_r as f64,
                        db_to_lin(gain_db) as f64,
                        if zero_r > 0.0001 { 1.0 } else { 0.0 },
                        zero_hz as f64,
                        zero_r as f64,
                    ]);
                } else {
                    params.extend_from_slice(&[0.0, 1000.0, 0.5, 1.0, 0.0, 1000.0, 0.0]);
                }
            }
        }
        Some(trench_core::compiler::pack_body(&params))
    }

    fn body_preview_response(&self, body: &[u8; 240]) -> Vec<f32> {
        let words = words_of(body);
        let live = live_biquads(&words, self.morph, self.q);
        let trig = grid_trig(AUDIT_BINS);
        (0..AUDIT_BINS)
            .map(|i| cascade_db_c(&live, trig[i].0, trig[i].1))
            .collect()
    }

    fn start_preview_values(&self, preview: &StartPreview) -> Option<Vec<f32>> {
        match preview {
            StartPreview::None => None,
            StartPreview::Body(path) => self
                .source_bodies
                .get(path)
                .map(|body| self.body_preview_response(body)),
            StartPreview::Curves(path) => self
                .overlay_curves
                .get(path)
                .and_then(|ov| ov.curves.first())
                .map(|c| c.db.clone()),
            StartPreview::Exact(which) => self
                .skeleton_preview_body(*which)
                .map(|body| self.body_preview_response(&body)),
            shape => Some(shape_preview_values(shape, AUDIT_BINS)),
        }
    }

    /// START is a quiet index, not a card wall: two monospace text columns
    /// grouped by provenance lane, every lane sorted low → high (spectral
    /// centroid), ONE preview curve at a time (the hovered row).
    fn draw_start_menu(&self, p: &egui::Painter, chip: Rect, frame: &mut Frame) {
        let entries: Vec<StartEntry> =
            self.start_menu_columns().into_iter().flatten().collect();
        let row_h = 18.0;
        let header_h = 26.0;
        let pad = 14.0;
        let col_w = 300.0;
        let preview_w = 250.0;
        let is_header = |e: &StartEntry| {
            e.preview == StartPreview::None && e.action.is_none() && !e.quarantined
        };
        let eh = |e: &StartEntry| if is_header(e) { header_h } else { row_h };
        let total: f32 = entries.iter().map(eh).sum();
        // split into two columns at a lane boundary near the midpoint
        let mut split = entries.len();
        let mut acc = 0.0;
        for (i, e) in entries.iter().enumerate() {
            if acc >= total * 0.5 && is_header(e) {
                split = i;
                break;
            }
            acc += eh(e);
        }
        let cols = [&entries[..split], &entries[split..]];
        let col_h = cols
            .iter()
            .map(|c| c.iter().map(eh).sum::<f32>())
            .fold(0.0, f32::max);
        let w = pad * 4.0 + col_w * 2.0 + preview_w;
        let h = col_h + pad * 2.0;
        let clip = p.clip_rect();
        let mut origin = Pos2::new(chip.left(), chip.bottom() + 4.0);
        if origin.x + w > clip.right() - 8.0 {
            origin.x = (clip.right() - w - 8.0).max(clip.left() + 8.0);
        }
        if origin.y + h > clip.bottom() - 8.0 {
            origin.y = (clip.bottom() - h - 8.0).max(clip.top() + 8.0);
        }
        let rect = Rect::from_min_size(origin, Vec2::new(w, h));
        p.rect_filled(
            rect.expand(2.0),
            7.0,
            Color32::from_rgba_unmultiplied(0, 0, 0, 150),
        );
        p.rect_filled(rect, 7.0, BG);
        p.rect_stroke(rect, 7.0, Stroke::new(1.0, EDGE));

        let hover = self.hover;
        let mut hovered: Option<&StartEntry> = None;
        for (ci, col) in cols.iter().enumerate() {
            let x = rect.left() + pad + ci as f32 * (col_w + pad);
            let mut y = rect.top() + pad;
            for entry in *col {
                if is_header(entry) {
                    let cy = y + header_h - 9.0;
                    p.text(
                        Pos2::new(x, cy),
                        Align2::LEFT_BOTTOM,
                        entry.label.to_ascii_uppercase(),
                        FontId::monospace(8.5),
                        if entry.label == "quarantine" {
                            with_alpha(FAULT, 170)
                        } else {
                            TEXT_DIM
                        },
                    );
                    p.line_segment(
                        [Pos2::new(x, cy + 3.0), Pos2::new(x + col_w, cy + 3.0)],
                        Stroke::new(1.0, with_alpha(EDGE, 140)),
                    );
                    y += header_h;
                    continue;
                }
                let row = Rect::from_min_size(Pos2::new(x, y), Vec2::new(col_w, row_h));
                let clickable = entry.action.is_some();
                if let Some(action) = entry.action {
                    frame.menu_items.push(Hit {
                        rect: row,
                        value: action,
                    });
                }
                let is_hover = hover.map_or(false, |hp| row.contains(hp));
                if is_hover {
                    p.rect_filled(row, 3.0, with_alpha(ICE, 16));
                    hovered = Some(entry);
                }
                // an active overlay keeps a small lit dot
                let overlay_active = matches!(
                    (&entry.preview, &self.overlay_ref),
                    (StartPreview::Curves(path), Some(active)) if path == active
                );
                if overlay_active {
                    p.circle_filled(Pos2::new(x + 4.0, row.center().y), 2.0, ICE);
                }
                p.text(
                    Pos2::new(x + 12.0, row.center().y),
                    Align2::LEFT_CENTER,
                    &entry.label,
                    FontId::monospace(10.0),
                    if entry.quarantined {
                        with_alpha(FAULT, 140)
                    } else if clickable {
                        TEXT
                    } else {
                        TEXT_DIM
                    },
                );
                // right: the sort key, terse (centroid Hz) — quarantine rows
                // show nothing inline; their reason lives in the preview pane
                if let Some(hz) = self.entry_centroid(entry) {
                    p.text(
                        Pos2::new(x + col_w - 4.0, row.center().y),
                        Align2::RIGHT_CENTER,
                        fmt_hz(hz),
                        FontId::monospace(8.5),
                        with_alpha(TEXT_DIM, 180),
                    );
                }
                y += row_h;
            }
        }

        // one preview at a time — the hovered row
        let pv = Rect::from_min_size(
            Pos2::new(rect.right() - pad - preview_w, rect.top() + pad),
            Vec2::new(preview_w, rect.height() - pad * 2.0),
        );
        p.line_segment(
            [pv.left_top(), pv.left_bottom()],
            Stroke::new(1.0, with_alpha(EDGE, 140)),
        );
        if let Some(entry) = hovered {
            let plot_r = Rect::from_min_size(
                Pos2::new(pv.left() + pad, pv.top() + 4.0),
                Vec2::new(preview_w - pad * 2.0, 120.0),
            );
            if let Some(values) = self.start_preview_values(&entry.preview) {
                draw_mini_plot(p, plot_r, &values, TRUTH);
            }
            let mut ty = plot_r.bottom() + 14.0;
            p.text(
                Pos2::new(plot_r.left(), ty),
                Align2::LEFT_TOP,
                &entry.label,
                FontId::monospace(10.5),
                TEXT,
            );
            ty += 18.0;
            p.text(
                Pos2::new(plot_r.left(), ty),
                Align2::LEFT_TOP,
                &entry.note,
                FontId::monospace(9.0),
                if entry.quarantined {
                    with_alpha(FAULT, 180)
                } else {
                    TEXT_DIM
                },
            );
            ty += 18.0;
            if let Some(badge) = entry.badge {
                let badge_color = match badge {
                    _ if entry.quarantined => FAULT,
                    "COMPILE EXACT" => painter::theme::GOOD,
                    "IMPORT EXACT" => ICE,
                    "OVERLAY" => EMBER,
                    _ => TEXT_DIM,
                };
                p.text(
                    Pos2::new(plot_r.left(), ty),
                    Align2::LEFT_TOP,
                    if entry.quarantined { "QUARANTINE" } else { badge },
                    FontId::monospace(8.5),
                    badge_color,
                );
            }
        } else {
            p.text(
                pv.center(),
                Align2::CENTER_CENTER,
                "hover to preview · click to start",
                FontId::monospace(9.5),
                TEXT_DIM,
            );
        }
        frame.menu_rect = Some(rect);
    }

    fn entry_centroid(&self, entry: &StartEntry) -> Option<f32> {
        match &entry.preview {
            StartPreview::Body(path) | StartPreview::Curves(path) => {
                self.centroids.get(path).copied()
            }
            _ => None,
        }
    }

    fn draw_menu(&self, p: &egui::Painter, frame: &mut Frame) {
        let Some(menu) = self.open_menu else { return };
        let Some(chip) = frame.menu_chips.iter().find(|h| h.value == menu) else {
            return;
        };
        if menu == Menu::Seed {
            self.draw_start_menu(p, chip.rect, frame);
            return;
        }
        let entries = self.menu_entries(menu);
        let row_h = 20.0;
        let w = entries.iter().map(|(s, _)| s.len()).max().unwrap_or(10) as f32 * 6.6 + 26.0;
        let h = entries.len() as f32 * row_h + 10.0;
        let origin = Pos2::new(chip.rect.left(), chip.rect.bottom() + 4.0);
        let rect = Rect::from_min_size(origin, Vec2::new(w.max(180.0), h));
        p.rect_filled(
            rect.expand(2.0),
            6.0,
            Color32::from_rgba_unmultiplied(0, 0, 0, 110),
        );
        p.rect_filled(rect, 6.0, PANEL_HI);
        p.rect_stroke(rect, 6.0, Stroke::new(1.0, EDGE));
        let mut y = rect.top() + 5.0;
        for (label, action) in entries {
            let row =
                Rect::from_min_size(Pos2::new(rect.left(), y), Vec2::new(rect.width(), row_h));
            if let Some(a) = action {
                frame.menu_items.push(Hit {
                    rect: row,
                    value: a,
                });
                p.text(
                    Pos2::new(rect.left() + 12.0, row.center().y),
                    Align2::LEFT_CENTER,
                    label,
                    FontId::monospace(11.0),
                    TEXT,
                );
            } else {
                p.text(
                    Pos2::new(rect.left() + 12.0, row.center().y),
                    Align2::LEFT_CENTER,
                    label,
                    FontId::monospace(9.5),
                    TEXT_DIM,
                );
            }
            y += row_h;
        }
        frame.menu_rect = Some(rect);
    }

    // ── the plot (Pro-Q style) ────────────────────────────────────────────────

    fn draw_plot(&self, p: &egui::Painter, rect: Rect, frame: &mut Frame) {
        p.rect_filled(rect, 6.0, Color32::from_rgb(16, 17, 21));
        p.rect_stroke(rect, 6.0, Stroke::new(1.0, EDGE));
        draw_grid(p, rect);
        let fast_drag = self.drag.is_some();
        let stride = if fast_drag { 2 } else { 1 };
        let focus_stage = self.drag_focus_stage();

        let peak = self.response_peak_db();
        p.text(
            rect.left_top() + Vec2::new(12.0, 10.0),
            Align2::LEFT_TOP,
            self.target_label(),
            FontId::monospace(12.0),
            ICE,
        );
        p.text(
            rect.left_top() + Vec2::new(12.0, 27.0),
            Align2::LEFT_TOP,
            format!(
                "{} filters on · peak {:+.1} dB",
                self.active_sections(),
                if peak.is_finite() { peak } else { 0.0 },
            ),
            FontId::monospace(10.0),
            TEXT_DIM,
        );

        // reference overlay: measured vowel formant lines (table data, dim)
        if let Some(vi) = self.overlay_vowel {
            if let Some(v) = self.tables.vowels.get(vi) {
                let (key, f1, f2, f3) = (v.0.clone(), v.1, v.2, v.3);
                for (name, f) in [("F1", f1), ("F2", f2), ("F3", f3)] {
                    if !(F_MIN..=F_MAX).contains(&f) {
                        continue;
                    }
                    let x = x_for_freq(rect, f);
                    p.add(egui::Shape::dashed_line(
                        &[Pos2::new(x, rect.top() + 40.0), Pos2::new(x, rect.bottom())],
                        Stroke::new(1.0, with_alpha(ICE, 70)),
                        4.0,
                        5.0,
                    ));
                    p.text(
                        Pos2::new(x + 3.0, rect.top() + 42.0),
                        Align2::LEFT_TOP,
                        format!("{name} {:.0}", f),
                        FontId::monospace(9.0),
                        with_alpha(ICE, 150),
                    );
                }
                p.text(
                    Pos2::new(rect.right() - 12.0, rect.top() + 10.0),
                    Align2::RIGHT_TOP,
                    format!("overlay: vowel {key} (Peterson-Barney)"),
                    FontId::monospace(9.5),
                    with_alpha(ICE, 150),
                );
            }
        }

        // reference overlay: exact measured curves (X3 blocks / P2K refs) —
        // four corner curves in the corner identity colors, thin, dim
        if let Some(path) = &self.overlay_ref {
            if let Some(ov) = self.overlay_curves.get(path) {
                for (ci, curve) in ov.curves.iter().enumerate().take(4) {
                    let color = painter::theme::CORNER[ci];
                    let points: Vec<Pos2> = ov
                        .freqs
                        .iter()
                        .zip(&curve.db)
                        .filter(|(f, db)| f.is_finite() && db.is_finite())
                        .map(|(&f, &db)| {
                            Pos2::new(
                                x_for_freq(rect, f.clamp(F_MIN, F_MAX)),
                                y_for_db(rect, db.clamp(DB_MIN, DB_MAX)),
                            )
                        })
                        .collect();
                    if points.len() > 1 {
                        p.add(egui::Shape::line(
                            points,
                            Stroke::new(1.0, with_alpha(color, 130)),
                        ));
                    }
                }
                p.text(
                    Pos2::new(rect.right() - 12.0, rect.top() + 24.0),
                    Align2::RIGHT_TOP,
                    format!("overlay: {} — exact reference", ov.label),
                    FontId::monospace(9.5),
                    with_alpha(EMBER, 170),
                );
            }
        }

        // verbatim packed preview: announce it — sections do not describe it
        if let Some(label) = &self.packed_preview {
            p.text(
                rect.left_top() + Vec2::new(12.0, 44.0),
                Align2::LEFT_TOP,
                format!("packed preview: {label} — editing returns to your sections"),
                FontId::monospace(10.0),
                EMBER,
            );
        }

        // THE plot: the combined packed-runtime response — the one hero object.
        // GPU path: one WGSL pass draws underfill + ghosts + glow + core + the
        // brush footprint from the same dB rows. egui path is the fallback.
        let n = self.response.len();
        let gripping_now = matches!(self.drag, Some(Drag::Curve));
        if self.gpu_plot {
            let mut rows = Vec::with_capacity(4 * n);
            rows.extend_from_slice(&self.response);
            rows.extend_from_slice(&self.ghost_low);
            rows.extend_from_slice(&self.ghost_high);
            match &self.qcompare {
                Some(q) if q.len() == n => rows.extend_from_slice(q),
                _ => rows.resize(4 * n, 0.0),
            }
            let mut hand = match (gripping_now, self.hand) {
                (true, Some((f_h, _, _))) => {
                    let x0 = axis_t(bark_f(bark_z(f_h) - self.brush_bark));
                    let x1 = axis_t(bark_f(bark_z(f_h) + self.brush_bark));
                    [axis_t(f_h), ((x1 - x0) * 0.5).max(0.001), 1.0, 0.0]
                }
                _ => [0.0, 0.0, 0.0, 0.0],
            };
            hand[3] = if self.qcompare.is_some() { 1.0 } else { 0.0 };
            let ppp = p.ctx().pixels_per_point();
            p.add(egui_wgpu::Callback::new_paint_callback(
                rect,
                gpu_plot::PlotCallback {
                    rows,
                    uni: gpu_plot::PlotUniforms {
                        rect_px: [rect.width() * ppp, rect.height() * ppp],
                        db_min_max: [DB_MIN, DB_MAX],
                        hand,
                        flags: [
                            if self.show_ghosts { 1.0 } else { 0.0 },
                            n as f32,
                            if BARK.load(std::sync::atomic::Ordering::Relaxed) {
                                1.0
                            } else {
                                0.0
                            },
                            ppp,
                        ],
                    },
                },
            ));
        } else {
            // frame ghosts (reference, off by default — VIEW menu)
            if self.show_ghosts && !fast_drag {
                for (arr, color) in [(&self.ghost_low, GHOST_LO), (&self.ghost_high, GHOST_HI)] {
                    let pts: Vec<Pos2> = (0..FREQ_BINS)
                        .map(|i| {
                            Pos2::new(
                                x_for_freq(rect, freq_at(i, FREQ_BINS)),
                                y_for_db(rect, arr[i]),
                            )
                        })
                        .collect();
                    p.add(egui::Shape::dashed_line(
                        &pts,
                        Stroke::new(1.0, with_alpha(color, 60)),
                        5.0,
                        4.0,
                    ));
                }
            }
            if !fast_drag {
                let mut mesh = egui::epaint::Mesh::default();
                let base = y_for_db(rect, DB_MIN);
                for i in 0..n {
                    let x = x_for_freq(rect, freq_at(i, n));
                    let y = y_for_db(rect, self.response[i]);
                    mesh.colored_vertex(Pos2::new(x, y), with_alpha(TRUTH, 22));
                    mesh.colored_vertex(Pos2::new(x, base), with_alpha(TRUTH, 0));
                }
                for i in 0..(n - 1) as u32 {
                    let a = i * 2;
                    mesh.add_triangle(a, a + 1, a + 2);
                    mesh.add_triangle(a + 1, a + 3, a + 2);
                }
                p.add(egui::Shape::mesh(mesh));
            }
            let pts: Vec<Pos2> = (0..n)
                .step_by(stride)
                .map(|i| {
                    Pos2::new(
                        x_for_freq(rect, freq_at(i, n)),
                        y_for_db(rect, self.response[i]),
                    )
                })
                .collect();
            p.add(egui::Shape::line(pts, Stroke::new(2.0, TRUTH)));
            if let Some(qrow) = &self.qcompare {
                let pts: Vec<Pos2> = (0..n)
                    .map(|i| Pos2::new(x_for_freq(rect, freq_at(i, n)), y_for_db(rect, qrow[i])))
                    .collect();
                p.add(egui::Shape::dashed_line(
                    &pts,
                    Stroke::new(1.2, with_alpha(FAULT, 150)),
                    5.0,
                    4.0,
                ));
            }
        }

        // brush affordance: contact ring on the curve; width band only while gripping
        let gripping = matches!(self.drag, Some(Drag::Curve));
        if gripping || self.drag.is_none() {
            if let Some(h) = self.hover {
                if rect.contains(h) {
                    let f_h = axis_f(((h.x - rect.left()) / rect.width()).clamp(0.0, 1.0));
                    let cy = y_for_db(rect, self.response[bin_for_freq(f_h, n)]);
                    if gripping || (h.y - cy).abs() < 12.0 {
                        if gripping && !self.gpu_plot {
                            // egui fallback only — the shader draws the footprint
                            let x0 = x_for_freq(rect, bark_f(bark_z(f_h) - self.brush_bark));
                            let x1 = x_for_freq(rect, bark_f(bark_z(f_h) + self.brush_bark));
                            p.rect_filled(
                                Rect::from_min_max(
                                    Pos2::new(x0, rect.top()),
                                    Pos2::new(x1, rect.bottom()),
                                ),
                                0.0,
                                with_alpha(ICE, 12),
                            );
                        }
                        p.circle_stroke(
                            Pos2::new(h.x, cy),
                            if gripping { 7.0 } else { 6.0 },
                            Stroke::new(1.2, with_alpha(ICE, if gripping { 230 } else { 150 })),
                        );
                    }
                }
            }
        }

        // draw-the-target stroke, live while painting (hold D)
        if let Some(stroke) = &self.draw_stroke {
            let pts: Vec<Pos2> = stroke
                .iter()
                .map(|&(f, db)| Pos2::new(x_for_freq(rect, f), y_for_db(rect, db)))
                .collect();
            if pts.len() > 1 {
                p.add(egui::Shape::line(
                    pts,
                    Stroke::new(1.6, with_alpha(EMBER, 220)),
                ));
            }
            p.text(
                rect.left_top() + Vec2::new(12.0, 44.0),
                Align2::LEFT_TOP,
                "drawing target — release to fit",
                FontId::monospace(10.0),
                EMBER,
            );
        }

        // tether: finger ↔ material gap while moulding — resistance made
        // visible (locks, trust region and format limits all read as stiffness)
        if gripping {
            if let Some((f_h, finger_db, _)) = self.hand {
                let hx = x_for_freq(rect, f_h);
                let fy = y_for_db(rect, finger_db);
                let my = y_for_db(rect, self.response_db_at(f_h));
                if (fy - my).abs() > 3.0 {
                    p.line_segment(
                        [Pos2::new(hx, fy), Pos2::new(hx, my)],
                        Stroke::new(1.0, with_alpha(ICE, 140)),
                    );
                }
                p.circle_filled(Pos2::new(hx, fy), 2.5, with_alpha(ICE, 230));
            }
        }

        // the selected section's own contribution curve — the line both its
        // handles actually sit on (the cascade sums these curves in dB). Without
        // it the handle heights read as arbitrary; with it they read as "this
        // section's peak / this section's notch".
        if let Some(sec) = self.sections.get(self.selected_stage) {
            if sec.on {
                let hue = section_color(self.selected_stage);
                let pts: Vec<Pos2> = (0..FREQ_BINS)
                    .step_by(stride)
                    .map(|i| {
                        Pos2::new(
                            x_for_freq(rect, freq_at(i, FREQ_BINS)),
                            y_for_db(rect, self.stage_db[self.selected_stage][i]),
                        )
                    })
                    .collect();
                p.add(egui::Shape::line(
                    pts,
                    Stroke::new(1.1, with_alpha(hue, 120)),
                ));
            }
        }

        // handles: only the selected section's pole + zero live on the canvas —
        // the strip cards below are the section selector. One curve, two dots.
        let corner = self.selected_corner.idx();
        // the other morph frame, for the travel arcs (same Q row as selected)
        let mirror = self.selected_corner.morph_mirror();
        let mirror_bq = live_biquads(
            &self.words(),
            mirror.morph_q().0,
            self.selected_corner.morph_q().1,
        );
        for (i, section) in self.sections.iter().enumerate() {
            if !section.on || i != self.selected_stage {
                continue;
            }
            let selected = true;
            let color = section_color(i);
            let inactive_drag = fast_drag && focus_stage != Some(i);
            let dimmed = if inactive_drag {
                with_alpha(color, 46)
            } else if section.locked {
                with_alpha(color, 110)
            } else {
                color
            };
            let c = section.corners[corner];

            let pole = Pos2::new(
                x_for_freq(rect, c.pole_hz),
                y_for_db(rect, self.stage_db_at(i, c.pole_hz)),
            );
            frame.handles.push((pole, i, HandleKind::Pole));
            let r = if inactive_drag {
                3.5
            } else if selected {
                7.0
            } else {
                5.0
            };
            p.circle_filled(pole, r, dimmed);
            if selected && !inactive_drag {
                p.circle_stroke(pole, r + 2.5, Stroke::new(1.4, TRUTH));
            }
            if section.locked && !inactive_drag {
                draw_padlock(p, pole + Vec2::new(9.0, -9.0), dimmed);
            }

            let zero = Pos2::new(
                x_for_freq(rect, c.zero_hz),
                y_for_db(rect, self.stage_db_at(i, c.zero_hz)),
            );
            frame.handles.push((zero, i, HandleKind::Zero));
            let rz = if inactive_drag {
                3.0
            } else if selected {
                6.0
            } else {
                4.5
            };
            p.circle_stroke(
                zero,
                rz,
                Stroke::new(if selected { 2.0 } else { 1.4 }, dimmed),
            );
            if selected && !inactive_drag {
                p.circle_stroke(zero, rz + 2.5, Stroke::new(1.0, with_alpha(TRUTH, 160)));
            }

            // the travel: this section's position in the OTHER morph frame —
            // hollow dots, joined by a thin arc. The one long arc on a body is
            // the leader move; held sections stay short or have none. Dragging
            // the hollow dot authors the other frame without switching corners.
            if !inactive_drag && !section.locked {
                let mc = section.corners[mirror.idx()];
                if (mc.pole_hz / c.pole_hz).log2().abs() > 0.02 {
                    let pole2 = Pos2::new(
                        x_for_freq(rect, mc.pole_hz),
                        y_for_db(rect, biquad_db(mirror_bq[i], mc.pole_hz)),
                    );
                    travel_arc(p, pole, pole2, with_alpha(color, 85));
                    p.circle_stroke(pole2, 5.0, Stroke::new(1.6, with_alpha(color, 165)));
                    frame.travel_handles.push((pole2, i, HandleKind::Pole));
                }
                if (mc.zero_hz / c.zero_hz).log2().abs() > 0.02 {
                    let zero2 = Pos2::new(
                        x_for_freq(rect, mc.zero_hz),
                        y_for_db(rect, biquad_db(mirror_bq[i], mc.zero_hz)),
                    );
                    travel_arc(p, zero, zero2, with_alpha(color, 60));
                    p.circle_stroke(zero2, 4.0, Stroke::new(1.1, with_alpha(color, 120)));
                    frame.travel_handles.push((zero2, i, HandleKind::Zero));
                }
            }
        }
        self.draw_goal(p, rect, frame);
        self.draw_surgical_overlay(p, rect);
    }

    // ── goal pins: chips, pin glyphs, residual + optimize overlay ────────────

    fn draw_goal(&self, p: &egui::Painter, rect: Rect, frame: &mut Frame) {
        if self.pins.is_empty() {
            return;
        }

        // residual readout — always through the packed runtime
        if let Some(res) = self.goal_residual_now() {
            p.text(
                rect.left_top() + Vec2::new(12.0, 44.0),
                Align2::LEFT_TOP,
                format!(
                    "target error {res:.2} dB · {} pin{}",
                    self.pins.len(),
                    if self.pins.len() == 1 { "" } else { "s" }
                ),
                FontId::monospace(10.0),
                EMBER,
            );
        }
        if self.optimize_inflight {
            p.text(
                rect.left_top() + Vec2::new(12.0, 58.0),
                Align2::LEFT_TOP,
                "fitting the target…",
                FontId::monospace(10.0),
                FAULT,
            );
        } else if let Some(o) = &self.last_opt {
            if o.at.elapsed() < Duration::from_secs(5) {
                let names: Vec<String> = o.stages.iter().map(|s| format!("S{}", s + 1)).collect();
                p.text(
                    rect.left_top() + Vec2::new(12.0, 58.0),
                    Align2::LEFT_TOP,
                    format!(
                        "{}: error {:.2} → {:.2} dB{}",
                        if o.accepted { "accepted" } else { "rejected" },
                        o.before,
                        o.after,
                        if names.is_empty() {
                            String::new()
                        } else {
                            format!(" on {}", names.join("+"))
                        },
                    ),
                    FontId::monospace(10.0),
                    if o.accepted { ICE } else { FAULT },
                );
                // ring the moved stages' pole handles
                if o.accepted {
                    let corner = self.selected_corner.idx();
                    for &s in &o.stages {
                        let c = self.sections[s].corners[corner];
                        let pos = Pos2::new(
                            x_for_freq(rect, c.pole_hz),
                            y_for_db(rect, self.stage_db_at(s, c.pole_hz)),
                        );
                        p.circle_stroke(pos, 12.0, Stroke::new(1.3, with_alpha(EMBER, 200)));
                    }
                }
            }
        }

        // pins
        for (i, pin) in self.pins.iter().enumerate() {
            let pos = Pos2::new(x_for_freq(rect, pin.freq_hz), y_for_db(rect, pin.target_db));
            frame.pin_handles.push((pos, i));
            let col = if pin.kind == PinKind::Anchor {
                ICE
            } else {
                EMBER
            };
            let selected = self.selected_pin == Some(i);
            if selected {
                let x0 = x_for_freq(rect, bark_f(bark_z(pin.freq_hz) - pin.width_bark));
                let x1 = x_for_freq(rect, bark_f(bark_z(pin.freq_hz) + pin.width_bark));
                p.rect_filled(
                    Rect::from_min_max(Pos2::new(x0, rect.top()), Pos2::new(x1, rect.bottom())),
                    0.0,
                    with_alpha(col, 7),
                );
            }
            if pin.kind == PinKind::Anchor {
                p.rect_stroke(
                    Rect::from_center_size(pos, Vec2::splat(8.0)),
                    1.0,
                    Stroke::new(1.6, col),
                );
            } else {
                match pin.shape {
                    PinShape::Point => {
                        p.circle_filled(pos, 4.0, col);
                    }
                    PinShape::Peak => {
                        p.add(egui::Shape::convex_polygon(
                            vec![
                                pos + Vec2::new(0.0, -5.5),
                                pos + Vec2::new(5.0, 3.5),
                                pos + Vec2::new(-5.0, 3.5),
                            ],
                            col,
                            Stroke::NONE,
                        ));
                    }
                    PinShape::Notch => {
                        p.add(egui::Shape::convex_polygon(
                            vec![
                                pos + Vec2::new(0.0, 5.5),
                                pos + Vec2::new(5.0, -3.5),
                                pos + Vec2::new(-5.0, -3.5),
                            ],
                            col,
                            Stroke::NONE,
                        ));
                    }
                    PinShape::LowShelf => {
                        p.circle_filled(pos, 3.5, col);
                        p.line_segment([pos, pos + Vec2::new(-16.0, 0.0)], Stroke::new(2.0, col));
                    }
                    PinShape::HighShelf => {
                        p.circle_filled(pos, 3.5, col);
                        p.line_segment([pos, pos + Vec2::new(16.0, 0.0)], Stroke::new(2.0, col));
                    }
                }
            }
            if selected {
                p.circle_stroke(pos, 8.5, Stroke::new(1.4, TRUTH));
                p.text(
                    pos + Vec2::new(9.0, -9.0),
                    Align2::LEFT_BOTTOM,
                    format!(
                        "{}{} {:+.1} dB",
                        if pin.kind == PinKind::Anchor {
                            "hold "
                        } else {
                            ""
                        },
                        format_freq(pin.freq_hz),
                        pin.target_db,
                    ),
                    FontId::monospace(9.0),
                    with_alpha(col, 220),
                );
            }
        }
    }

    fn draw_surgical_overlay(&self, p: &egui::Painter, rect: Rect) {
        let Some(drag) = self.drag else { return };
        let cursor = self.hover.unwrap_or(rect.center());
        let cursor = Pos2::new(
            cursor.x.clamp(rect.left(), rect.right()),
            cursor.y.clamp(rect.top(), rect.bottom()),
        );
        let stage = self.drag_focus_stage().unwrap_or(self.selected_stage);
        let color = section_color(stage);

        p.rect_stroke(
            rect.shrink(1.0),
            6.0,
            Stroke::new(2.0, with_alpha(color, 220)),
        );
        p.line_segment(
            [
                Pos2::new(cursor.x, rect.top()),
                Pos2::new(cursor.x, rect.bottom()),
            ],
            Stroke::new(1.0, with_alpha(color, 105)),
        );
        p.line_segment(
            [
                Pos2::new(rect.left(), cursor.y),
                Pos2::new(rect.right(), cursor.y),
            ],
            Stroke::new(1.0, with_alpha(color, 105)),
        );

        let corner = self.selected_corner.idx();
        let (focus, label) = match drag {
            Drag::Handle {
                stage,
                kind,
                gain,
                start_pos,
                start,
                corner: hc,
            } => {
                let c = self.sections[stage].corners[hc.idx()];
                let s0 = start[hc.idx()];
                let (kind_label, hz, radius, hz0, radius0, focus) = match kind {
                    HandleKind::Pole => (
                        "POLE",
                        c.pole_hz,
                        c.pole_r,
                        s0.pole_hz,
                        s0.pole_r,
                        Pos2::new(
                            x_for_freq(rect, c.pole_hz),
                            y_for_db(rect, self.stage_db_at(stage, c.pole_hz)),
                        ),
                    ),
                    HandleKind::Zero => (
                        "ZERO",
                        c.zero_hz,
                        c.zero_r,
                        s0.zero_hz,
                        s0.zero_r,
                        Pos2::new(
                            x_for_freq(rect, c.zero_hz),
                            y_for_db(rect, self.stage_db_at(stage, c.zero_hz)),
                        ),
                    ),
                };
                p.line_segment([start_pos, focus], Stroke::new(1.2, with_alpha(color, 160)));
                p.circle_stroke(focus, 14.0, Stroke::new(1.6, color));
                p.circle_stroke(focus, 25.0, Stroke::new(1.0, with_alpha(color, 82)));
                let oct = (hz / hz0.max(1.0)).log2();
                let gain_delta = c.gain_db - s0.gain_db;
                (
                    focus,
                    format!(
                        "SURGICAL S{} {}{}  {}  r {:.4}  Δ {:+.2} oct  {:+.4} r  {:+.1} dB",
                        stage + 1,
                        kind_label,
                        if gain { "+GAIN" } else { "" },
                        format_freq(hz),
                        radius,
                        oct,
                        radius - radius0,
                        gain_delta
                    ),
                )
            }
            Drag::Value { field, start, .. } => {
                let c = self.sections[self.selected_stage].corners[corner];
                let s0 = start[corner];
                let (name, now, delta) = match field {
                    ValueField::PoleHz => (
                        "POLE HZ",
                        format_freq(c.pole_hz),
                        format!("{:+.2} oct", (c.pole_hz / s0.pole_hz.max(1.0)).log2()),
                    ),
                    ValueField::PoleR => (
                        "POLE R",
                        format!("{:.4}", c.pole_r),
                        format!("{:+.4}", c.pole_r - s0.pole_r),
                    ),
                    ValueField::ZeroHz => (
                        "ZERO HZ",
                        format_freq(c.zero_hz),
                        format!("{:+.2} oct", (c.zero_hz / s0.zero_hz.max(1.0)).log2()),
                    ),
                    ValueField::ZeroR => (
                        "ZERO R",
                        format!("{:.4}", c.zero_r),
                        format!("{:+.4}", c.zero_r - s0.zero_r),
                    ),
                    ValueField::GainDb => (
                        "GAIN",
                        format!("{:+.1} dB", c.gain_db),
                        format!("{:+.1} dB", c.gain_db - s0.gain_db),
                    ),
                };
                (
                    cursor,
                    format!(
                        "SURGICAL S{} {}  {}  Δ {}",
                        self.selected_stage + 1,
                        name,
                        now,
                        delta
                    ),
                )
            }
            Drag::Curve => {
                let tx = ((cursor.x - rect.left()) / rect.width()).clamp(0.0, 1.0);
                let f = axis_f(tx);
                let db = DB_MIN
                    + (1.0 - (cursor.y - rect.top()) / rect.height()).clamp(0.0, 1.0)
                        * (DB_MAX - DB_MIN);
                (
                    cursor,
                    format!(
                        "SHAPE CURVE  {}  {:+.1} dB  width {:.2}",
                        format_freq(f),
                        db,
                        self.brush_bark
                    ),
                )
            }
            Drag::Draw => {
                let tx = ((cursor.x - rect.left()) / rect.width()).clamp(0.0, 1.0);
                let f = axis_f(tx);
                let db = DB_MIN
                    + (1.0 - (cursor.y - rect.top()) / rect.height()).clamp(0.0, 1.0)
                        * (DB_MAX - DB_MIN);
                (
                    cursor,
                    format!(
                        "DRAW TARGET  {}  {:+.1} dB — release to fit",
                        format_freq(f),
                        db
                    ),
                )
            }
            Drag::Pin { idx } => {
                let label = self
                    .pins
                    .get(idx)
                    .map(|pin| {
                        format!(
                            "TARGET {}{} {} {:+.1} dB · width {:.2}",
                            if pin.kind == PinKind::Anchor {
                                "ANCHOR "
                            } else {
                                ""
                            },
                            pin.shape.label(),
                            format_freq(pin.freq_hz),
                            pin.target_db,
                            pin.width_bark,
                        )
                    })
                    .unwrap_or_else(|| "TARGET".into());
                (cursor, label)
            }
            Drag::Morph | Drag::Q | Drag::SurfaceMap | Drag::SweepMap => (
                cursor,
                format!(
                    "M{:02} Q{:02}",
                    (self.morph * 100.0).round() as i32,
                    (self.q * 100.0).round() as i32
                ),
            ),
            Drag::Front(s) => {
                let (frame_word, fc) = match s {
                    FrontSlider::LowFreq | FrontSlider::LowShelf | FrontSlider::LowPeak => {
                        ("LOW", &self.patch.low)
                    }
                    FrontSlider::HighFreq | FrontSlider::HighShelf | FrontSlider::HighPeak => {
                        ("HIGH", &self.patch.high)
                    }
                    FrontSlider::Master => ("MASTER", &self.patch.low),
                };
                let label = match s {
                    FrontSlider::Master => {
                        format!("MASTER  {:+.1} dB", self.patch.master_peak_db)
                    }
                    FrontSlider::LowFreq | FrontSlider::HighFreq => {
                        format!("{frame_word} FREQ  {}", fmt_hz(fc.freq_hz))
                    }
                    FrontSlider::LowShelf | FrontSlider::HighShelf => {
                        format!("{frame_word} SHELF  {:+.0}", fc.shelf)
                    }
                    FrontSlider::LowPeak | FrontSlider::HighPeak => {
                        format!("{frame_word} PEAK  {:+.1} dB", fc.peak_db)
                    }
                };
                (cursor, label)
            }
        };

        let w = (label.len() as f32 * 6.45 + 18.0).clamp(220.0, rect.width() - 24.0);
        let x = (focus.x + 16.0)
            .min(rect.right() - w - 10.0)
            .max(rect.left() + 10.0);
        let y = (focus.y - 42.0)
            .max(rect.top() + 48.0)
            .min(rect.bottom() - 34.0);
        let hud = Rect::from_min_size(Pos2::new(x, y), Vec2::new(w, 26.0));
        p.rect_filled(
            hud.expand(3.0),
            7.0,
            Color32::from_rgba_unmultiplied(0, 0, 0, 150),
        );
        p.rect_filled(hud, 6.0, Color32::from_rgb(9, 10, 13));
        p.rect_stroke(hud, 6.0, Stroke::new(1.2, color));
        p.text(
            hud.left_center() + Vec2::new(9.0, 0.0),
            Align2::LEFT_CENTER,
            label,
            FontId::monospace(10.5),
            TRUTH,
        );
    }

    // ── analysis rail ────────────────────────────────────────────────────────

    fn draw_biquad_budget(&self, p: &egui::Painter, rect: Rect) {
        let corner = self.selected_corner.idx();
        let uses: Vec<BiquadUse> = self
            .sections
            .iter()
            .map(|section| biquad_use(section, corner))
            .collect();
        let poles = uses.iter().filter(|u| u.pole_used).count();
        let zeros = uses.iter().filter(|u| u.zero_used).count();
        let free_poles = STAGES - poles;
        let free_zeros = STAGES - zeros;

        p.rect_filled(rect, 4.0, Color32::from_rgb(13, 14, 17));
        p.rect_stroke(rect, 4.0, Stroke::new(1.0, EDGE));
        p.text(
            rect.left_top() + Vec2::new(10.0, 8.0),
            Align2::LEFT_TOP,
            "FILTER BUDGET",
            FontId::monospace(12.0),
            TRUTH,
        );
        p.text(
            rect.left_top() + Vec2::new(10.0, 28.0),
            Align2::LEFT_TOP,
            format!("{poles}/6 poles used  ·  {zeros}/6 zeros used"),
            FontId::monospace(9.5),
            TEXT,
        );
        p.text(
            rect.left_top() + Vec2::new(10.0, 44.0),
            Align2::LEFT_TOP,
            format!("{free_poles} poles free  ·  {free_zeros} zeros free"),
            FontId::monospace(9.5),
            TEXT_DIM,
        );
        p.text(
            rect.right_top() + Vec2::new(-10.0, 8.0),
            Align2::RIGHT_TOP,
            self.selected_corner.plain_label(),
            FontId::monospace(9.0),
            TEXT_DIM,
        );

        let start = rect.left_top() + Vec2::new(10.0, 68.0);
        for (i, usage) in uses.iter().enumerate() {
            let y = start.y + i as f32 * 18.0;
            let color = if usage.pole_used && usage.zero_used {
                section_color(i)
            } else if usage.pole_used {
                with_alpha(section_color(i), 190)
            } else if usage.zero_used {
                ICE
            } else {
                TEXT_DIM
            };
            p.circle_filled(Pos2::new(start.x + 4.0, y + 7.0), 3.0, color);
            p.text(
                Pos2::new(start.x + 14.0, y),
                Align2::LEFT_TOP,
                format!("S{} {}", i + 1, usage.label),
                FontId::monospace(9.5),
                if i == self.selected_stage { TEXT } else { TEXT_DIM },
            );
        }
    }

    fn draw_rail(&self, p: &egui::Painter, rail: Rect, frame: &mut Frame) {
        p.rect_filled(rail, 6.0, PANEL);
        p.rect_stroke(rail, 6.0, Stroke::new(1.0, EDGE));
        let pad = 10.0;
        let mut y = rail.top() + pad;

        p.text(
            Pos2::new(rail.left() + pad, y),
            Align2::LEFT_TOP,
            "CORNERS",
            FontId::monospace(10.5),
            TEXT_DIM,
        );
        y += 18.0;

        let cw = (rail.width() - pad * 2.0 - 6.0) / 2.0;
        for (row, pair) in [
            [CornerKey::M0Q100, CornerKey::M100Q100],
            [CornerKey::M0Q0, CornerKey::M100Q0],
        ]
        .iter()
        .enumerate()
        {
            for (col, &corner) in pair.iter().enumerate() {
                let r = Rect::from_min_size(
                    Pos2::new(
                        rail.left() + pad + col as f32 * (cw + 6.0),
                        y + row as f32 * 26.0,
                    ),
                    Vec2::new(cw, 22.0),
                );
                let active = corner == self.selected_corner;
                // Q100 chips dim while linked — those rows are derived
                let colr = if self.q_link && corner.morph_q().1 > 0.5 {
                    with_alpha(ICE, 110)
                } else {
                    ICE
                };
                chip(
                    p,
                    r,
                    corner.plain_label(),
                    active,
                    colr,
                );
                frame.corner_chips.push(Hit {
                    rect: r,
                    value: corner,
                });
            }
        }
        y += 2.0 * 26.0 + 6.0;

        let budget_r = Rect::from_min_size(
            Pos2::new(rail.left() + pad, y),
            Vec2::new(rail.width() - pad * 2.0, 184.0),
        );
        self.draw_biquad_budget(p, budget_r);
        y += budget_r.height() + 12.0;

        p.text(
            Pos2::new(rail.left() + pad, y),
            Align2::LEFT_TOP,
            "POSITION",
            FontId::monospace(10.5),
            TEXT_DIM,
        );
        y += 18.0;
        let map_size = (rail.width() - pad * 2.0).min(154.0);
        let map = Rect::from_min_size(Pos2::new(rail.left() + pad, y), Vec2::splat(map_size));
        p.rect_filled(map, 3.0, Color32::from_rgb(12, 13, 16));
        p.rect_stroke(map, 3.0, Stroke::new(1.0, EDGE));
        p.line_segment(
            [
                Pos2::new(map.left(), map.center().y),
                Pos2::new(map.right(), map.center().y),
            ],
            Stroke::new(1.0, with_alpha(TEXT_DIM, 45)),
        );
        p.line_segment(
            [
                Pos2::new(map.center().x, map.top()),
                Pos2::new(map.center().x, map.bottom()),
            ],
            Stroke::new(1.0, with_alpha(TEXT_DIM, 45)),
        );
        let corner_labels = [
            (
                CornerKey::M0Q0,
                Pos2::new(map.left() + 4.0, map.bottom() - 4.0),
                Align2::LEFT_BOTTOM,
            ),
            (
                CornerKey::M100Q0,
                Pos2::new(map.right() - 4.0, map.bottom() - 4.0),
                Align2::RIGHT_BOTTOM,
            ),
            (
                CornerKey::M0Q100,
                Pos2::new(map.left() + 4.0, map.top() + 4.0),
                Align2::LEFT_TOP,
            ),
            (
                CornerKey::M100Q100,
                Pos2::new(map.right() - 4.0, map.top() + 4.0),
                Align2::RIGHT_TOP,
            ),
        ];
        for (corner, pos, align) in corner_labels {
            p.text(
                pos,
                align,
                corner.plain_label(),
                FontId::monospace(8.5),
                with_alpha(TEXT_DIM, 180),
            );
        }
        let ph = Pos2::new(
            map.left() + self.morph * map.width(),
            map.bottom() - self.q * map.height(),
        );
        p.circle_filled(ph, 5.0, ICE);
        p.circle_stroke(ph, 8.0, Stroke::new(1.0, with_alpha(ICE, 130)));
        frame.surface_rect = Some(map);
        y += map_size + 10.0;

        let sw = rail.width() - pad * 2.0;
        let morph_r = Rect::from_min_size(Pos2::new(rail.left() + pad, y), Vec2::new(sw, 20.0));
        slider_chip(p, morph_r, "MORPH", self.morph, section_color(0));
        frame.morph_rect = morph_r;
        y += 26.0;
        let q_r = Rect::from_min_size(Pos2::new(rail.left() + pad, y), Vec2::new(sw, 20.0));
        slider_chip(p, q_r, "Q", self.q, ICE);
        frame.q_rect = q_r;
        y += 28.0;

        let play_r = Rect::from_min_size(
            Pos2::new(rail.left() + pad, y),
            Vec2::new(sw, 22.0),
        );
        chip(
            p,
            play_r,
            if self.playing {
                "❚❚ PAUSE"
            } else {
                "► PLAY"
            },
            self.playing,
            Color32::from_rgb(127, 225, 180),
        );
        frame.play_rect = play_r;
        y += 28.0;
        let src_w = (sw - 12.0) / 3.0;
        for (i, src) in [AudioSrc::Noise, AudioSrc::Saw, AudioSrc::Pad]
            .into_iter()
            .enumerate()
        {
            let r = Rect::from_min_size(
                Pos2::new(rail.left() + pad + i as f32 * (src_w + 6.0), y),
                Vec2::new(src_w, 20.0),
            );
            chip(p, r, src.label(), self.audio_src == src, GHOST_HI);
            frame.src_chips.push(Hit {
                rect: r,
                value: src,
            });
        }
    }

    // ── band strip + value row ───────────────────────────────────────────────

    fn draw_strip(&self, p: &egui::Painter, strip: Rect, frame: &mut Frame) {
        p.rect_filled(strip, 0.0, Color32::from_rgb(17, 18, 22));
        p.line_segment(
            [strip.left_top(), strip.right_top()],
            Stroke::new(1.0, EDGE),
        );
        let pad = 8.0;
        let gap = 6.0;
        let w = (strip.width() - pad * 2.0 - gap * (STAGES as f32 - 1.0)) / STAGES as f32;
        let corner = self.selected_corner.idx();
        // while moulding, show which sections the brush is holding (mirrors the
        // worker's recruitment — same fn, same inputs)
        let recruited: Vec<(usize, f32)> = match (&self.drag, self.hand) {
            (Some(Drag::Curve), Some((f_h, _, _))) => {
                recruit_in(&self.sections, f_h, self.brush_bark, corner)
            }
            _ => Vec::new(),
        };
        for (i, section) in self.sections.iter().enumerate() {
            let x = strip.left() + pad + i as f32 * (w + gap);
            let cell = Rect::from_min_size(
                Pos2::new(x, strip.top() + 6.0),
                Vec2::new(w, strip.height() - 12.0),
            );
            let selected = i == self.selected_stage;
            let color = section_color(i);
            p.rect_filled(
                cell,
                5.0,
                if selected {
                    PANEL_HI
                } else {
                    Color32::from_rgb(23, 24, 29)
                },
            );
            p.rect_stroke(
                cell,
                5.0,
                Stroke::new(
                    if selected { 1.4 } else { 1.0 },
                    if selected { color } else { EDGE },
                ),
            );
            if let Some((_, wgt)) = recruited.iter().find(|(k, _)| *k == i) {
                let a = (110.0 + wgt * 120.0).min(235.0) as u8;
                p.rect_stroke(cell.expand(1.5), 6.0, Stroke::new(1.6, with_alpha(ICE, a)));
            }
            p.rect_filled(
                Rect::from_min_max(
                    cell.left_top() + Vec2::new(2.0, 2.0),
                    Pos2::new(cell.right() - 2.0, cell.top() + 5.0),
                ),
                3.0,
                if section.on {
                    color
                } else {
                    with_alpha(color, 60)
                },
            );
            let c = section.corners[corner];
            let usage = biquad_use(section, corner);
            let title = if section.on {
                format!("S{}  {}  {}", i + 1, usage.label, format_freq(c.pole_hz))
            } else {
                format!("S{}  off", i + 1)
            };
            p.text(
                cell.left_top() + Vec2::new(8.0, 7.0),
                Align2::LEFT_TOP,
                title,
                FontId::monospace(10.5),
                if section.on { TEXT } else { TEXT_DIM },
            );
            if section.on {
                p.text(
                    cell.left_top() + Vec2::new(8.0, 21.0),
                    Align2::LEFT_TOP,
                    format!("zero {}", format_freq(c.zero_hz)),
                    FontId::monospace(9.0),
                    if usage.zero_used { TEXT_DIM } else { with_alpha(TEXT_DIM, 95) },
                );
                p.text(
                    cell.left_top() + Vec2::new(8.0, 35.0),
                    Align2::LEFT_TOP,
                    format!("gain {:+.1} dB", c.gain_db),
                    FontId::monospace(9.0),
                    TEXT_DIM,
                );
            } else {
                p.text(
                    cell.center() + Vec2::new(0.0, 8.0),
                    Align2::CENTER_CENTER,
                    "bypass",
                    FontId::monospace(9.0),
                    TEXT_DIM,
                );
            }
            // lock badge (click target)
            let lock_r = Rect::from_min_size(
                cell.right_top() + Vec2::new(-24.0, 8.0),
                Vec2::new(18.0, 18.0),
            );
            if section.locked {
                draw_padlock(p, lock_r.center(), color);
            } else {
                p.circle_stroke(
                    lock_r.center(),
                    4.0,
                    Stroke::new(1.0, with_alpha(TEXT_DIM, 110)),
                );
            }
            frame.locks.push(Hit {
                rect: lock_r,
                value: i,
            });
            frame.cards.push(Hit {
                rect: cell,
                value: i,
            });
        }
    }

    fn draw_values(&self, p: &egui::Painter, row: Rect, frame: &mut Frame) {
        p.rect_filled(row, 0.0, Color32::from_rgb(15, 16, 20));
        let corner = self.selected_corner.idx();
        let s = &self.sections[self.selected_stage];
        let c = s.corners[corner];
        let cy = row.center().y;
        let mut x = row.left() + 14.0;
        let color = section_color(self.selected_stage);

        p.text(
            Pos2::new(x, cy),
            Align2::LEFT_CENTER,
            format!("S{}", self.selected_stage + 1),
            FontId::monospace(12.0),
            color,
        );
        x += 36.0;

        // on / lock toggles
        let on_r = Rect::from_min_size(Pos2::new(x, cy - 9.0), Vec2::new(40.0, 18.0));
        chip(p, on_r, if s.on { "ON" } else { "OFF" }, s.on, color);
        frame.on_rect = on_r;
        x += 48.0;
        let lock_r = Rect::from_min_size(Pos2::new(x, cy - 9.0), Vec2::new(52.0, 18.0));
        chip(
            p,
            lock_r,
            if s.locked { "LOCKED" } else { "LOCK" },
            s.locked,
            EMBER,
        );
        frame.lock_rect = lock_r;
        x += 64.0;

        let mut field = |label: &str, value: String, field_id: ValueField, x: &mut f32| {
            p.text(
                Pos2::new(*x, cy),
                Align2::LEFT_CENTER,
                label,
                FontId::monospace(9.5),
                TEXT_DIM,
            );
            *x += label.len() as f32 * 6.0 + 6.0;
            let w = value.len() as f32 * 7.0 + 14.0;
            let r = Rect::from_min_size(Pos2::new(*x, cy - 9.0), Vec2::new(w, 18.0));
            p.rect_filled(r, 3.0, Color32::from_rgb(11, 11, 14));
            p.rect_stroke(r, 3.0, Stroke::new(1.0, EDGE));
            p.text(
                r.center(),
                Align2::CENTER_CENTER,
                value,
                FontId::monospace(11.0),
                TEXT,
            );
            frame.value_fields.push(Hit {
                rect: r,
                value: field_id,
            });
            *x += w + 12.0;
        };
        field(
            "pole",
            format!("{:.0} Hz", c.pole_hz),
            ValueField::PoleHz,
            &mut x,
        );
        field("r", format!("{:.4}", c.pole_r), ValueField::PoleR, &mut x);
        field(
            "zero",
            format!("{:.0} Hz", c.zero_hz),
            ValueField::ZeroHz,
            &mut x,
        );
        field("r", format!("{:.4}", c.zero_r), ValueField::ZeroR, &mut x);
        field(
            "gain",
            format!("{:+.1} dB", c.gain_db),
            ValueField::GainDb,
            &mut x,
        );

        p.text(
            Pos2::new(row.right() - 14.0, cy),
            Align2::RIGHT_CENTER,
            format!(
                "edit {} · snap {}",
                self.scope.label(),
                self.quantize.label()
            ),
            FontId::monospace(9.0),
            TEXT_DIM,
        );
    }

    fn draw_hint(&self, p: &egui::Painter, plot: Rect) {
        let Some((text, pos, t0)) = &self.hint else {
            return;
        };
        let age = t0.elapsed().as_secs_f32();
        if age > 1.8 {
            return;
        }
        let a = ((1.8 - age) / 0.4).clamp(0.0, 1.0);
        let alpha = (a * 235.0) as u8;
        let galley = p.layout_no_wrap(
            text.clone(),
            FontId::monospace(11.0),
            with_alpha(EMBER, alpha),
        );
        let anchor = Pos2::new(
            pos.x.clamp(
                plot.left() + galley.size().x / 2.0 + 12.0,
                plot.right() - galley.size().x / 2.0 - 12.0,
            ),
            (pos.y - 24.0).clamp(plot.top() + 12.0, plot.bottom() - 12.0),
        );
        let r = Rect::from_center_size(anchor, galley.size() + Vec2::new(14.0, 8.0));
        p.rect_filled(r, 4.0, with_alpha(PANEL, alpha.min(215)));
        p.galley(
            Pos2::new(r.left() + 7.0, r.top() + 4.0),
            galley,
            with_alpha(EMBER, alpha),
        );
    }

    /// hold H: the controls card — every gesture and key, plain language
    fn draw_help(&self, p: &egui::Painter, plot: Rect) {
        if !self.show_help {
            return;
        }
        let rows: [(&str, &str); 12] = [
            (
                "drag a dot",
                "move pole / zero — 1:1 on the axis · Shift = fine",
            ),
            (
                "drag a hollow dot",
                "place it in the other morph frame (the travel)",
            ),
            (
                "Alt + drag curve",
                "shape the whole curve under your hand",
            ),
            (
                "grip at any morph/q",
                "nearest corner moves so this spot follows",
            ),
            (
                "Ctrl + drag",
                "target pin · right-click removes · Esc clears",
            ),
            ("hold D + drag", "draw a target curve — release to fit"),
            ("hold C", "overlay the other Q row (red)"),
            ("Tab / Shift+Tab", "other morph frame / other Q row"),
            ("1 2 3 4", "corners · ←/→ section · E on/off · L lock"),
            ("Space / P", "morph sweep / play audio"),
            ("Ctrl+Z / Ctrl+Y", "undo / redo"),
            ("wheel on MORPH / Q", "nudge the slider · Shift = fine"),
        ];
        let w = 640.0_f32.min(plot.width() - 40.0);
        let h = rows.len() as f32 * 21.0 + 52.0;
        let r = Rect::from_center_size(plot.center(), Vec2::new(w, h));
        p.rect_filled(
            r.expand(3.0),
            9.0,
            Color32::from_rgba_unmultiplied(0, 0, 0, 140),
        );
        p.rect_filled(r, 8.0, with_alpha(PANEL, 244));
        p.rect_stroke(r, 8.0, Stroke::new(1.0, EDGE));
        p.text(
            Pos2::new(r.left() + 18.0, r.top() + 14.0),
            Align2::LEFT_TOP,
            "controls — release H to close",
            FontId::monospace(11.0),
            ICE,
        );
        let mut y = r.top() + 42.0;
        for (key, what) in rows {
            p.text(
                Pos2::new(r.left() + 18.0, y),
                Align2::LEFT_TOP,
                key,
                FontId::monospace(10.5),
                TEXT,
            );
            p.text(
                Pos2::new(r.left() + 210.0, y),
                Align2::LEFT_TOP,
                what,
                FontId::monospace(10.5),
                TEXT_DIM,
            );
            y += 21.0;
        }
    }

    fn draw_status(&self, p: &egui::Painter, bar: Rect) {
        p.rect_filled(bar, 0.0, PANEL);
        p.line_segment([bar.left_top(), bar.right_top()], Stroke::new(1.0, EDGE));
        p.text(
            Pos2::new(bar.left() + 14.0, bar.center().y),
            Align2::LEFT_CENTER,
            &self.status,
            FontId::monospace(10.5),
            TEXT_DIM,
        );
        p.text(
            Pos2::new(bar.right() - 14.0, bar.center().y),
            Align2::RIGHT_CENTER,
            "6 biquads · 240 bytes",
            FontId::monospace(10.0),
            TEXT_DIM,
        );
    }

    // ── interaction ───────────────────────────────────────────────────────────

    fn interact(&mut self, ctx: &egui::Context, resp: &egui::Response, lay: Layout, frame: Frame) {
        let pointer = resp.interact_pointer_pos();
        let hover = ctx.input(|i| i.pointer.hover_pos());
        let (shift, alt, ctrl) =
            ctx.input(|i| (i.modifiers.shift, i.modifiers.alt, i.modifiers.command));

        // clicks
        if resp.clicked() {
            if let Some(pos) = pointer {
                // open menu popup eats clicks first
                if let Some(menu_rect) = frame.menu_rect {
                    if menu_rect.contains(pos) {
                        for item in &frame.menu_items {
                            if item.rect.contains(pos) {
                                self.run_action(item.value);
                                break;
                            }
                        }
                        self.open_menu = None;
                        return;
                    }
                    self.open_menu = None;
                }
                for h in &frame.menu_chips {
                    if h.rect.contains(pos) {
                        self.open_menu = if self.open_menu == Some(h.value) {
                            None
                        } else {
                            Some(h.value)
                        };
                        self.menu_opened_at = Some(Instant::now());
                        return;
                    }
                }
                if frame.panels_rect.contains(pos) {
                    self.show_rail = !self.show_rail;
                    self.status = if self.show_rail {
                        "details shown".into()
                    } else {
                        "details hidden".into()
                    };
                    return;
                }
                self.name_active = frame.name_rect.contains(pos);
                for h in &frame.corner_chips {
                    if h.rect.contains(pos) {
                        self.select_corner(h.value);
                        return;
                    }
                }
                if frame.sweep_rect.contains(pos) {
                    self.sweep = !self.sweep;
                    self.sweep_t0 = Instant::now();
                    return;
                }
                if let Some(h) = frame.front_sliders.iter().find(|h| h.rect.contains(pos)) {
                    self.push_undo();
                    let t = (pos.x - h.rect.left()) / h.rect.width();
                    self.apply_front_slider(h.value, t);
                    return;
                }
                if frame.qlink_rect.contains(pos) {
                    self.q_link = !self.q_link;
                    if self.q_link {
                        self.push_undo();
                        self.rebuild_body();
                        self.status = "Q rows linked — high-Q corners follow the low-Q rows".into();
                    } else {
                        self.status = "Q rows separate — all four corners are hand-authored".into();
                    }
                    return;
                }
                if frame.play_rect.contains(pos) {
                    self.toggle_play();
                    return;
                }
                for h in &frame.src_chips {
                    if h.rect.contains(pos) {
                        self.audio_src = h.value;
                        self.sync_audio();
                        return;
                    }
                }
                if frame.bake_rect.contains(pos) {
                    self.bake();
                    return;
                }
                if frame.audition_rect.contains(pos) {
                    self.publish_audition_slot();
                    return;
                }
                if frame.keep_rect.contains(pos) {
                    self.keep_to_staging();
                    return;
                }
                if frame.on_rect.contains(pos) {
                    self.push_undo();
                    let s = self.selected_stage;
                    self.sections[s].on = !self.sections[s].on;
                    self.rebuild_body();
                    return;
                }
                if frame.lock_rect.contains(pos) {
                    let s = self.selected_stage;
                    self.sections[s].locked = !self.sections[s].locked;
                    return;
                }
                for h in &frame.locks {
                    if h.rect.contains(pos) {
                        self.sections[h.value].locked = !self.sections[h.value].locked;
                        self.status = format!(
                            "S{} {}",
                            h.value + 1,
                            if self.sections[h.value].locked {
                                "locked"
                            } else {
                                "unlocked"
                            }
                        );
                        return;
                    }
                }
                for h in &frame.cards {
                    if h.rect.contains(pos) {
                        self.selected_stage = h.value;
                        return;
                    }
                }
                if lay.plot.contains(pos) {
                    if let Some(i) = nearest_pin(pos, &frame.pin_handles) {
                        self.selected_pin = Some(i);
                        return;
                    }
                    if let Some((stage, _)) = nearest_handle(pos, &frame.handles) {
                        self.selected_stage = stage;
                        return;
                    }
                    // empty space: just deselect — pins are placed by DRAG only
                    self.selected_pin = None;
                }
            }
        }

        // right click: delete the pin under the cursor
        if resp.secondary_clicked() {
            if let Some(pos) = ctx.input(|i| i.pointer.interact_pos()) {
                if lay.plot.contains(pos) {
                    if let Some(i) = nearest_pin(pos, &frame.pin_handles) {
                        self.pins.remove(i);
                        self.selected_pin = None;
                        self.status = "target removed".into();
                    }
                }
            }
        }

        // double click: card on/off
        if resp.double_clicked() {
            if let Some(pos) = pointer {
                for h in &frame.cards {
                    if h.rect.contains(pos) {
                        self.push_undo();
                        self.sections[h.value].on = !self.sections[h.value].on;
                        self.rebuild_body();
                        return;
                    }
                }
            }
        }

        // drags
        if resp.drag_started() {
            if let Some(pos) = pointer {
                if frame.menu_rect.map_or(false, |r| r.contains(pos)) {
                    // no drags inside menus
                } else if frame.morph_rect.contains(pos) {
                    self.sweep = false;
                    self.drag = Some(Drag::Morph);
                } else if frame.q_rect.contains(pos) {
                    self.drag = Some(Drag::Q);
                } else if let Some(h) = frame.front_sliders.iter().find(|h| h.rect.contains(pos)) {
                    self.push_undo();
                    self.drag = Some(Drag::Front(h.value));
                    let t = (pos.x - h.rect.left()) / h.rect.width();
                    self.apply_front_slider(h.value, t);
                } else if frame.surface_rect.map_or(false, |r| r.contains(pos)) {
                    self.sweep = false;
                    self.drag = Some(Drag::SurfaceMap);
                } else if frame.sweepmap_rect.map_or(false, |r| r.contains(pos)) {
                    self.sweep = false;
                    self.drag = Some(Drag::SweepMap);
                } else {
                    let mut grabbed = false;
                    for h in &frame.value_fields {
                        if h.rect.contains(pos) {
                            let s = self.selected_stage;
                            if self.sections[s].locked {
                                self.show_hint(
                                    &format!("S{} is locked — unlock to edit (L)", s + 1),
                                    pos,
                                );
                            } else {
                                self.ensure_q_free(self.selected_corner);
                                self.push_undo();
                                self.drag = Some(Drag::Value {
                                    field: h.value,
                                    start_y: pos.y,
                                    start: self.sections[s].corners,
                                });
                            }
                            grabbed = true;
                            break;
                        }
                    }
                    let d_held = !self.name_active && ctx.input(|i| i.key_down(Key::D));
                    if !grabbed && lay.plot.contains(pos) && d_held {
                        // draw-the-target: paint the curve you want, release to fit
                        let tx = ((pos.x - lay.plot.left()) / lay.plot.width()).clamp(0.0, 1.0);
                        let db = DB_MIN
                            + (1.0 - (pos.y - lay.plot.top()) / lay.plot.height()).clamp(0.0, 1.0)
                                * (DB_MAX - DB_MIN);
                        self.draw_stroke = Some(vec![(axis_f(tx), db)]);
                        self.drag = Some(Drag::Draw);
                    } else if !grabbed && lay.plot.contains(pos) {
                        if let Some(i) = nearest_pin(pos, &frame.pin_handles) {
                            // existing pin: drag it — the solver chases live
                            self.selected_pin = Some(i);
                            self.ensure_q_free(self.selected_corner);
                            self.push_undo();
                            self.drag = Some(Drag::Pin { idx: i });
                            self.dispatch_optimize(true);
                        } else if let Some((stage, kind)) = nearest_handle(pos, &frame.handles) {
                            self.selected_stage = stage;
                            if self.sections[stage].locked {
                                self.show_hint(
                                    &format!("S{} is locked — unlock to drag (L)", stage + 1),
                                    pos,
                                );
                            } else {
                                self.ensure_q_free(self.selected_corner);
                                self.push_undo();
                                self.drag = Some(Drag::Handle {
                                    stage,
                                    kind,
                                    gain: alt,
                                    start_pos: pos,
                                    start: self.sections[stage].corners,
                                    corner: self.selected_corner,
                                });
                            }
                        } else if let Some((stage, kind)) =
                            nearest_handle(pos, &frame.travel_handles)
                        {
                            // hollow dot: author the OTHER morph frame in place
                            self.selected_stage = stage;
                            if self.sections[stage].locked {
                                self.show_hint(
                                    &format!("S{} is locked — unlock to drag (L)", stage + 1),
                                    pos,
                                );
                            } else {
                                self.ensure_q_free(self.selected_corner.morph_mirror());
                                self.push_undo();
                                self.drag = Some(Drag::Handle {
                                    stage,
                                    kind,
                                    gain: alt,
                                    start_pos: pos,
                                    start: self.sections[stage].corners,
                                    corner: self.selected_corner.morph_mirror(),
                                });
                            }
                        } else if ctrl {
                            // pins are deliberate targets; they win over the curve grip.
                            if self.add_goal_pin(pos, lay.plot, shift) {
                                self.drag = Some(Drag::Pin {
                                    idx: self.pins.len() - 1,
                                });
                            }
                        } else if alt {
                            // The curve grip is an inverse solve, so keep it out of the
                            // default drag path. Handles and target drawing are the 1:1
                            // authoring gestures; this remains available for experiments.
                            if !self.try_start_curve_grip(pos, lay.plot) {
                                self.show_hint("Alt-drag must start on the white curve", pos);
                            }
                        } else {
                            self.show_hint("drag dots for 1:1 edits · hold D to draw a target · Alt-drag curve to experiment", pos);
                        }
                    }
                }
            }
        }
        if resp.dragged() {
            if let (Some(pos), Some(drag)) = (pointer, self.drag) {
                match drag {
                    Drag::Morph => {
                        self.morph = ((pos.x - frame.morph_rect.left()) / frame.morph_rect.width())
                            .clamp(0.0, 1.0);
                        self.recompute_response();
                    }
                    Drag::Q => {
                        self.q =
                            ((pos.x - frame.q_rect.left()) / frame.q_rect.width()).clamp(0.0, 1.0);
                        self.recompute_response();
                        self.heat_dirty = true;
                    }
                    Drag::Front(slider) => {
                        if let Some(h) =
                            frame.front_sliders.iter().find(|h| h.value == slider)
                        {
                            let t = (pos.x - h.rect.left()) / h.rect.width();
                            self.apply_front_slider(slider, t);
                        }
                    }
                    Drag::SurfaceMap => {
                        if let Some(map) = frame.surface_rect {
                            self.morph = ((pos.x - map.left()) / map.width()).clamp(0.0, 1.0);
                            let new_q = (1.0 - (pos.y - map.top()) / map.height()).clamp(0.0, 1.0);
                            if (new_q - self.q).abs() > 0.002 {
                                self.q = new_q;
                                self.heat_dirty = true;
                            }
                            self.recompute_response();
                        }
                    }
                    Drag::SweepMap => {
                        if let Some(map) = frame.sweepmap_rect {
                            self.morph = (1.0 - (pos.y - map.top()) / map.height()).clamp(0.0, 1.0);
                            self.recompute_response();
                        }
                    }
                    Drag::Value {
                        field,
                        start_y,
                        start,
                    } => {
                        self.apply_value_drag(field, start_y - pos.y, start, shift);
                    }
                    Drag::Handle {
                        stage,
                        kind,
                        gain,
                        start_pos,
                        start,
                        corner,
                    } => {
                        self.apply_handle_drag(
                            stage, kind, gain, start_pos, pos, start, shift, lay.plot, corner,
                        );
                    }
                    Drag::Pin { idx } => {
                        let plot = lay.plot;
                        let tx = ((pos.x - plot.left()) / plot.width()).clamp(0.0, 1.0);
                        let f = axis_f(tx);
                        let db = DB_MIN
                            + (1.0 - (pos.y - plot.top()) / plot.height()).clamp(0.0, 1.0)
                                * (DB_MAX - DB_MIN);
                        let captured = self.response_db_at(f);
                        if let Some(pin) = self.pins.get_mut(idx) {
                            pin.freq_hz = f;
                            pin.target_db = match pin.kind {
                                PinKind::Target => db,
                                // hold pins re-capture the packed response at the new frequency
                                PinKind::Anchor => captured,
                            };
                        }
                        // the worker coalesces; light solves chase the pin live
                        self.dispatch_optimize(true);
                    }
                    Drag::Draw => {
                        let plot = lay.plot;
                        let tx = ((pos.x - plot.left()) / plot.width()).clamp(0.0, 1.0);
                        let db = DB_MIN
                            + (1.0 - (pos.y - plot.top()) / plot.height()).clamp(0.0, 1.0)
                                * (DB_MAX - DB_MIN);
                        if let Some(stroke) = &mut self.draw_stroke {
                            stroke.push((axis_f(tx), db));
                        }
                    }
                    Drag::Curve => {
                        // record the hand; the worker ping-pongs solves at its own rate
                        if let Some(grip) = &self.curve_grip {
                            let plot = grip.plot;
                            let tx = ((pos.x - plot.left()) / plot.width()).clamp(0.0, 1.0);
                            let f_center = axis_f(tx);
                            let finger_db = DB_MIN
                                + (1.0 - (pos.y - plot.top()) / plot.height()).clamp(0.0, 1.0)
                                    * (DB_MAX - DB_MIN);
                            self.hand = Some((f_center, finger_db, if shift { 0.3 } else { 1.0 }));
                            self.dispatch_solve();
                        }
                    }
                }
            }
        }
        if resp.drag_stopped() {
            if matches!(self.drag, Some(Drag::Draw)) {
                self.finish_draw_stroke();
            }
            if matches!(self.drag, Some(Drag::Pin { .. })) {
                // release: one full polish solve, eased in
                self.drag = None;
                self.dispatch_optimize(false);
            }
            if matches!(self.drag, Some(Drag::Curve)) {
                if let Some(grip) = &self.curve_grip {
                    self.status = format!(
                        "curve shaping released — error {:.2} dB vs target",
                        grip.residual_rms
                    );
                }
            }
            self.drag = None;
            self.curve_grip = None;
            self.hand = None;
            self.recompute_response(); // refresh the frame ghosts skipped while moulding
        }
        self.hover = hover;

        // wheel over plot: brush width while moulding / hovering the curve,
        // otherwise selected section pole radius
        if let Some(pos) = hover {
            if lay.plot.contains(pos) && self.open_menu.is_none() {
                let scroll = ctx.input(|i| {
                    let raw = i.raw_scroll_delta.y;
                    if raw.abs() > 0.0 {
                        raw
                    } else {
                        i.smooth_scroll_delta.y
                    }
                });
                if scroll.abs() >= 0.5 && nearest_pin(pos, &frame.pin_handles).is_some() {
                    // wheel over a pin: footprint width, then quietly re-solve
                    let steps = (scroll / 120.0).clamp(-6.0, 6.0);
                    if let Some(i) = nearest_pin(pos, &frame.pin_handles) {
                        if let Some(pin) = self.pins.get_mut(i) {
                            pin.width_bark =
                                (pin.width_bark * 2f32.powf(steps * 0.12)).clamp(0.3, 4.0);
                            self.status = format!("target width {:.2}", pin.width_bark);
                        }
                        self.dispatch_optimize(false);
                    }
                } else if scroll.abs() >= 0.5 {
                    let steps = (scroll / 120.0).clamp(-6.0, 6.0);
                    let gripping = matches!(self.drag, Some(Drag::Curve));
                    let on_curve = gripping || {
                        let n = self.response.len();
                        let f =
                            axis_f(((pos.x - lay.plot.left()) / lay.plot.width()).clamp(0.0, 1.0));
                        (pos.y - y_for_db(lay.plot, self.response[bin_for_freq(f, n)])).abs() < 12.0
                            && nearest_handle(pos, &frame.handles).is_none()
                    };
                    if on_curve {
                        self.brush_bark =
                            (self.brush_bark * 2f32.powf(steps * 0.12)).clamp(0.3, 3.0);
                        if !gripping {
                            self.status = format!(
                                "curve width {:.2} — fingertip 0.3 … palm 3.0",
                                self.brush_bark
                            );
                        }
                    } else {
                        let stage = self.selected_stage;
                        if self.sections[stage].locked {
                            self.show_hint(&format!("S{} is locked (L unlocks)", stage + 1), pos);
                        } else {
                            let step = if shift { 0.00045 } else { 0.0018 };
                            self.ensure_q_free(self.selected_corner);
                            self.push_undo();
                            for ci in self.selected_corner.scope_corners(self.scope) {
                                let c = &mut self.sections[stage].corners[ci];
                                c.pole_r = (c.pole_r + steps * step).clamp(RP_MIN, RP_MAX);
                            }
                            self.rebuild_body();
                        }
                    }
                }
            } else if self.open_menu.is_none()
                && (frame.morph_rect.contains(pos) || frame.q_rect.contains(pos))
            {
                // wheel on the MORPH / Q sliders: precise nudge without a drag
                let scroll = ctx.input(|i| {
                    let raw = i.raw_scroll_delta.y;
                    if raw.abs() > 0.0 {
                        raw
                    } else {
                        i.smooth_scroll_delta.y
                    }
                });
                if scroll.abs() >= 0.5 {
                    let step = (scroll / 120.0).clamp(-6.0, 6.0) * if shift { 0.002 } else { 0.02 };
                    if frame.morph_rect.contains(pos) {
                        self.sweep = false;
                        self.morph = (self.morph + step).clamp(0.0, 1.0);
                    } else {
                        self.q = (self.q + step).clamp(0.0, 1.0);
                        self.heat_dirty = true;
                    }
                    self.recompute_response();
                    self.sync_audio();
                }
            }
        }
    }

    fn apply_handle_drag(
        &mut self,
        stage: usize,
        kind: HandleKind,
        gain: bool,
        start_pos: Pos2,
        pos: Pos2,
        start: [CornerStage; CORNERS],
        shift: bool,
        plot: Rect,
        corner: CornerKey,
    ) {
        let dy = pos.y - start_pos.y;
        let fine = if shift { 0.15 } else { 0.55 };
        // horizontal is 1:1 on the plot's own log axis — the handle stays under
        // the cursor (Shift = 1:4 fine). Cursor octave delta → same pole/zero
        // octave delta, applied as a ratio so scoped corners keep their offsets.
        let t0 = ((start_pos.x - plot.left()) / plot.width()).clamp(0.0, 1.0);
        let t1 = ((pos.x - plot.left()) / plot.width()).clamp(0.0, 1.0);
        let doct = (axis_f(t1) / axis_f(t0)).log2() * if shift { 0.25 } else { 1.0 };
        let freq_ratio = 2.0_f32.powf(doct);
        for ci in corner.scope_corners(self.scope) {
            let s = start[ci];
            let snapped_pole = self.snap((s.pole_hz * freq_ratio).clamp(F_MIN, F_MAX), shift);
            let snapped_zero = self.snap((s.zero_hz * freq_ratio).clamp(F_MIN, F_MAX), shift);
            let c = &mut self.sections[stage].corners[ci];
            match kind {
                HandleKind::Pole => {
                    c.pole_hz = snapped_pole;
                    if gain {
                        c.gain_db = (s.gain_db - dy * fine / 13.0).clamp(GAIN_DB_MIN, GAIN_DB_MAX);
                    } else {
                        c.pole_r = (1.0 - (1.0 - s.pole_r) * 2.0_f32.powf(dy * fine / 150.0))
                            .clamp(RP_MIN, RP_MAX);
                    }
                }
                HandleKind::Zero => {
                    c.zero_hz = snapped_zero;
                    if gain {
                        c.gain_db = (s.gain_db - dy * fine / 13.0).clamp(GAIN_DB_MIN, GAIN_DB_MAX);
                    } else {
                        c.zero_r = (1.0 - (1.0 - s.zero_r) * 2.0_f32.powf(-dy * fine / 150.0))
                            .clamp(0.0, RZ_MAX);
                    }
                }
            }
        }
        self.rebuild_body();
    }

    // ── curve grip: edit the combined response, the stages follow ─────────────
    //
    // Damped Gauss-Newton over [log2 f_p, ln(1-r_p), gain dB] of the K nearest
    // unlocked sections, minimum-motion (Tikhonov toward the grab state),
    // forward model = the REAL packed runtime. Zeros are never touched; locked
    // sections are never touched; what moved is visible as moved handles.

    fn try_start_curve_grip(&mut self, pos: Pos2, plot: Rect) -> bool {
        // grab only the combined curve, and only docked at a corner
        let n = self.response.len();
        let f_press = axis_f(((pos.x - plot.left()) / plot.width()).clamp(0.0, 1.0));
        let curve_y = y_for_db(plot, self.response[bin_for_freq(f_press, n)]);
        if (pos.y - curve_y).abs() > 12.0 {
            return false;
        }
        let docked = (self.morph < 0.02 || self.morph > 0.98) && (self.q < 0.02 || self.q > 0.98);
        let corner = match (self.morph > 0.5, self.q > 0.5) {
            (false, false) => CornerKey::M0Q0,
            (true, false) => CornerKey::M100Q0,
            (false, true) => CornerKey::M0Q100,
            (true, true) => CornerKey::M100Q100,
        };
        if docked {
            // snap exactly onto the corner
            self.morph = if self.morph > 0.5 { 1.0 } else { 0.0 };
            self.q = if self.q > 0.5 { 1.0 } else { 0.0 };
        } else {
            // SPEC item 4 — the interior grip: hold the live (morph, q) and
            // mould the *interpolated middle*; the solver moves the nearest
            // corner (largest interpolation weight) and every evaluation runs
            // through the packed word-lerp at this exact interior point, so
            // the emergent interior is gripped directly, never a surrogate.
            self.status = format!(
                "interior grip at M{:.0} Q{:.0} — moulding through {}",
                self.morph * 100.0,
                self.q * 100.0,
                corner.code()
            );
        }
        self.selected_corner = corner;
        self.ensure_q_free(corner);
        self.push_undo();
        self.recompute_response();
        self.curve_grip = Some(CurveGrip {
            plot,
            residual_rms: 0.0,
        });
        self.drag = Some(Drag::Curve);
        true
    }

    fn apply_value_drag(
        &mut self,
        field: ValueField,
        dy: f32,
        start: [CornerStage; CORNERS],
        shift: bool,
    ) {
        let fine = if shift { 0.12 } else { 0.48 };
        let stage = self.selected_stage;
        for ci in self.selected_corner.scope_corners(self.scope) {
            let s = start[ci];
            let c = &mut self.sections[stage].corners[ci];
            match field {
                ValueField::PoleHz => {
                    c.pole_hz = (s.pole_hz * 2.0_f32.powf(dy * fine / 140.0)).clamp(F_MIN, F_MAX)
                }
                ValueField::PoleR => {
                    c.pole_r = (1.0 - (1.0 - s.pole_r) * 2.0_f32.powf(-dy * fine / 100.0))
                        .clamp(RP_MIN, RP_MAX)
                }
                ValueField::ZeroHz => {
                    c.zero_hz = (s.zero_hz * 2.0_f32.powf(dy * fine / 140.0)).clamp(F_MIN, F_MAX)
                }
                ValueField::ZeroR => {
                    c.zero_r = (1.0 - (1.0 - s.zero_r) * 2.0_f32.powf(-dy * fine / 100.0))
                        .clamp(0.0, RZ_MAX)
                }
                ValueField::GainDb => {
                    c.gain_db = (s.gain_db + dy * fine / 10.0).clamp(GAIN_DB_MIN, GAIN_DB_MAX)
                }
            }
        }
        self.rebuild_body();
    }
}

// ── painted primitives ───────────────────────────────────────────────────────

fn slugify(s: &str) -> String {
    let mut out = String::new();
    let mut last_us = false;
    for ch in s.chars() {
        if ch.is_ascii_alphanumeric() {
            out.push(ch.to_ascii_lowercase());
            last_us = false;
        } else if !last_us && !out.is_empty() {
            out.push('_');
            last_us = true;
        }
    }
    while out.ends_with('_') {
        out.pop();
    }
    if out.is_empty() {
        "body".into()
    } else {
        out
    }
}

fn shape_preview_values(preview: &StartPreview, n: usize) -> Vec<f32> {
    (0..n)
        .map(|i| {
            let t = i as f32 / (n - 1) as f32;
            let bump = |c: f32, w: f32, g: f32| g * (-((t - c) / w).powi(2)).exp();
            match preview {
                StartPreview::Flat | StartPreview::None => 0.0,
                StartPreview::Lowpass => 7.0 - 34.0 * t.powf(1.6),
                StartPreview::Highpass => 7.0 - 34.0 * (1.0 - t).powf(1.6),
                StartPreview::Bandpass => -20.0 + bump(0.48, 0.18, 31.0),
                StartPreview::Notch => -2.0 - bump(0.56, 0.055, 27.0),
                StartPreview::Peak => bump(0.52, 0.13, 16.0) - 2.0,
                StartPreview::Peaks => {
                    bump(0.20, 0.045, 12.0)
                        + bump(0.38, 0.04, 15.0)
                        + bump(0.62, 0.05, 12.0)
                        - 8.0
                }
                StartPreview::Vowel => {
                    bump(0.24, 0.055, 18.0)
                        + bump(0.48, 0.045, 14.0)
                        + bump(0.70, 0.055, 9.0)
                        - 10.0
                }
                StartPreview::Modal => {
                    bump(0.18, 0.025, 17.0)
                        + bump(0.33, 0.025, 15.0)
                        + bump(0.50, 0.026, 13.0)
                        + bump(0.68, 0.028, 10.0)
                        - 14.0
                }
                StartPreview::Body(_) | StartPreview::Curves(_) | StartPreview::Exact(_) => 0.0,
            }
        })
        .collect()
}

fn draw_mini_plot(p: &egui::Painter, rect: Rect, values: &[f32], color: Color32) {
    if values.len() < 2 {
        return;
    }
    p.rect_filled(rect, 4.0, Color32::from_rgb(12, 13, 17));
    p.rect_stroke(rect, 4.0, Stroke::new(1.0, with_alpha(EDGE, 180)));
    let y0 = mini_y_for_db(rect, 0.0);
    p.line_segment(
        [Pos2::new(rect.left(), y0), Pos2::new(rect.right(), y0)],
        Stroke::new(1.0, with_alpha(TEXT_DIM, 55)),
    );
    let pts: Vec<Pos2> = values
        .iter()
        .enumerate()
        .map(|(i, db)| {
            let t = i as f32 / (values.len() - 1) as f32;
            Pos2::new(
                rect.left() + t * rect.width(),
                mini_y_for_db(rect, *db),
            )
        })
        .collect();
    p.add(egui::Shape::line(pts, Stroke::new(1.25, color)));
}

fn mini_y_for_db(rect: Rect, db: f32) -> f32 {
    let min = -36.0;
    let max = 24.0;
    let t = ((db.clamp(min, max) - min) / (max - min)).clamp(0.0, 1.0);
    rect.bottom() - t * rect.height()
}

fn chip(p: &egui::Painter, rect: Rect, text: &str, active: bool, color: Color32) {
    let fill = if active {
        with_alpha(color, 42)
    } else {
        Color32::from_rgb(24, 24, 30)
    };
    let stroke = if active {
        Stroke::new(1.3, color)
    } else {
        Stroke::new(1.0, EDGE)
    };
    p.rect_filled(rect, 5.0, fill);
    p.rect_stroke(rect, 5.0, stroke);
    p.text(
        rect.center(),
        Align2::CENTER_CENTER,
        text,
        FontId::monospace(10.5),
        if active {
            color
        } else {
            Color32::from_rgb(168, 162, 154)
        },
    );
}

#[allow(dead_code)]
fn vsep(p: &egui::Painter, x: f32, cy: f32) {
    p.line_segment(
        [Pos2::new(x, cy - 8.0), Pos2::new(x, cy + 8.0)],
        Stroke::new(1.0, EDGE),
    );
}

#[allow(dead_code)]
fn readout_chip(p: &egui::Painter, rect: Rect, text: &str, color: Color32) {
    p.rect_filled(rect, 5.0, with_alpha(color, 22));
    p.rect_stroke(rect, 5.0, Stroke::new(1.0, with_alpha(color, 120)));
    p.text(
        rect.left_center() + Vec2::new(8.0, 0.0),
        Align2::LEFT_CENTER,
        text,
        FontId::monospace(10.5),
        color,
    );
}

/// Spectral centroid on the log-frequency axis (Hz) from a dB row over the
/// geometric F_MIN..F_MAX grid — power-weighted mean of log f.
fn spectral_centroid_hz(db: &[f32]) -> f32 {
    if db.len() < 2 {
        return 1000.0;
    }
    let (mut num, mut den) = (0.0f64, 0.0f64);
    let n = db.len();
    for (i, &d) in db.iter().enumerate() {
        if !d.is_finite() {
            continue;
        }
        let t = i as f64 / (n - 1) as f64;
        let logf = (F_MIN as f64).ln() + t * ((F_MAX / F_MIN) as f64).ln();
        let w = 10f64.powf(d as f64 / 10.0); // power weight
        num += w * logf;
        den += w;
    }
    if den <= 0.0 {
        return 1000.0;
    }
    ((num / den).exp() as f32).clamp(F_MIN, F_MAX)
}

/// Centroid of a packed body at M0 Q0 — the START list sort key.
fn body_centroid_hz(body: &[u8; 240]) -> f32 {
    let live = live_biquads(&words_of(body), 0.0, 0.0);
    let trig = grid_trig(AUDIT_BINS);
    let db: Vec<f32> = (0..AUDIT_BINS)
        .map(|i| cascade_db_c(&live, trig[i].0, trig[i].1))
        .collect();
    spectral_centroid_hz(&db)
}

fn fmt_hz(f: f32) -> String {
    if f >= 1000.0 {
        format!("{:.2} kHz", f / 1000.0)
    } else {
        format!("{f:.0} Hz")
    }
}

/// front-band slider, mini-plot quiet: label · hairline track · thumb ·
/// value. No box, no fill mass — the track is one line.
fn front_slider(p: &egui::Painter, rect: Rect, label: &str, value: &str, t: f32, color: Color32) {
    let cy = rect.center().y;
    let label_w = label.len() as f32 * 6.2 + 10.0;
    let value_w = 64.0;
    let track_l = rect.left() + label_w;
    let track_r = rect.right() - value_w;
    p.text(
        Pos2::new(rect.left(), cy),
        Align2::LEFT_CENTER,
        label,
        FontId::monospace(9.5),
        TEXT_DIM,
    );
    p.line_segment(
        [Pos2::new(track_l, cy), Pos2::new(track_r, cy)],
        Stroke::new(1.0, with_alpha(EDGE, 200)),
    );
    let tx = track_l + (track_r - track_l) * t.clamp(0.0, 1.0);
    p.line_segment(
        [Pos2::new(track_l, cy), Pos2::new(tx, cy)],
        Stroke::new(1.0, with_alpha(color, 170)),
    );
    p.circle_filled(Pos2::new(tx, cy), 3.0, color);
    p.text(
        Pos2::new(rect.right(), cy),
        Align2::RIGHT_CENTER,
        value,
        FontId::monospace(9.5),
        color,
    );
}

fn slider_chip(p: &egui::Painter, rect: Rect, label: &str, value: f32, color: Color32) {
    // quiet: label · hairline track · thumb · value — no box mass
    let cy = rect.center().y;
    let label_w = label.len() as f32 * 6.2 + 10.0;
    let value_w = 38.0;
    let track_l = rect.left() + label_w;
    let track_r = rect.right() - value_w;
    p.text(
        Pos2::new(rect.left(), cy),
        Align2::LEFT_CENTER,
        label,
        FontId::monospace(9.5),
        TEXT_DIM,
    );
    p.line_segment(
        [Pos2::new(track_l, cy), Pos2::new(track_r, cy)],
        Stroke::new(1.0, with_alpha(EDGE, 200)),
    );
    let tx = track_l + (track_r - track_l) * value.clamp(0.0, 1.0);
    p.line_segment(
        [Pos2::new(track_l, cy), Pos2::new(tx, cy)],
        Stroke::new(1.0, with_alpha(color, 170)),
    );
    p.circle_filled(Pos2::new(tx, cy), 3.0, color);
    p.text(
        Pos2::new(rect.right(), cy),
        Align2::RIGHT_CENTER,
        format!("{value:.2}"),
        FontId::monospace(9.5),
        color,
    );
}

/// thin bowed line from a section's position in this frame to its position in
/// the other — the morph move, made visible
fn travel_arc(p: &egui::Painter, a: Pos2, b: Pos2, color: Color32) {
    let bow = 10.0 + (b.x - a.x).abs() * 0.06;
    let mid = Pos2::new((a.x + b.x) * 0.5, (a.y + b.y) * 0.5 - bow);
    p.add(egui::Shape::QuadraticBezier(
        egui::epaint::QuadraticBezierShape::from_points_stroke(
            [a, mid, b],
            false,
            Color32::TRANSPARENT,
            Stroke::new(1.0, color),
        ),
    ));
}

fn draw_padlock(p: &egui::Painter, center: Pos2, color: Color32) {
    let body = Rect::from_center_size(center + Vec2::new(0.0, 1.5), Vec2::new(7.0, 5.5));
    p.rect_filled(body, 1.0, color);
    // shackle: small arc approximated by a circle stroke clipped above the body
    p.circle_stroke(center + Vec2::new(0.0, -2.5), 2.6, Stroke::new(1.2, color));
}

fn draw_grid(p: &egui::Painter, rect: Rect) {
    let major = Color32::from_rgba_unmultiplied(110, 105, 118, 34);
    let minor = Color32::from_rgba_unmultiplied(110, 105, 118, 16);
    for f in [100.0, 200.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0] {
        let x = x_for_freq(rect, f);
        p.line_segment(
            [Pos2::new(x, rect.top()), Pos2::new(x, rect.bottom())],
            Stroke::new(1.0, major),
        );
        let label = if f >= 1000.0 {
            format!("{}k", (f / 1000.0) as i32)
        } else {
            format!("{}", f as i32)
        };
        p.text(
            Pos2::new(x + 3.0, rect.bottom() - 4.0),
            Align2::LEFT_BOTTOM,
            label,
            FontId::monospace(9.5),
            Color32::from_rgb(110, 106, 116),
        );
    }
    for db in [-24.0, -12.0, 0.0, 12.0, 24.0] {
        let y = y_for_db(rect, db);
        let col = if db == 0.0 {
            Color32::from_rgba_unmultiplied(110, 105, 118, 70)
        } else {
            minor
        };
        p.line_segment(
            [Pos2::new(rect.left(), y), Pos2::new(rect.right(), y)],
            Stroke::new(1.0, col),
        );
        p.text(
            Pos2::new(rect.right() - 4.0, y - 2.0),
            Align2::RIGHT_BOTTOM,
            format!("{db:+.0}"),
            FontId::monospace(9.5),
            Color32::from_rgb(110, 106, 116),
        );
    }
}

/// Gaussian elimination with partial pivoting for the n×n normal equations.
fn solve_linear(a: &mut [f32], b: &mut [f32], n: usize) -> Option<Vec<f32>> {
    for col in 0..n {
        let mut piv = col;
        for row in (col + 1)..n {
            if a[row * n + col].abs() > a[piv * n + col].abs() {
                piv = row;
            }
        }
        if a[piv * n + col].abs() < 1e-12 {
            return None;
        }
        if piv != col {
            for k in 0..n {
                a.swap(col * n + k, piv * n + k);
            }
            b.swap(col, piv);
        }
        let d = a[col * n + col];
        for row in (col + 1)..n {
            let f = a[row * n + col] / d;
            if f == 0.0 {
                continue;
            }
            for k in col..n {
                a[row * n + k] -= f * a[col * n + k];
            }
            b[row] -= f * b[col];
        }
    }
    let mut x = vec![0.0f32; n];
    for col in (0..n).rev() {
        let mut acc = b[col];
        for k in (col + 1)..n {
            acc -= a[col * n + k] * x[k];
        }
        x[col] = acc / a[col * n + col];
    }
    Some(x)
}

fn nearest_pin(pos: Pos2, hits: &[(Pos2, usize)]) -> Option<usize> {
    let mut best = None;
    let mut bd = 13.0;
    for (hp, idx) in hits {
        let d = hp.distance(pos);
        if d < bd {
            bd = d;
            best = Some(*idx);
        }
    }
    best
}

fn nearest_handle(pos: Pos2, hits: &[(Pos2, usize, HandleKind)]) -> Option<(usize, HandleKind)> {
    let mut best = None;
    let mut bd = 18.0;
    for (hp, stage, kind) in hits {
        let d = hp.distance(pos);
        if d < bd {
            bd = d;
            best = Some((*stage, *kind));
        }
    }
    best
}

// ── DSP (mirrors trench-core packed interpolation; bytes from pack_body) ─────

fn live_biquads(words: &[[[u16; 5]; STAGES]; CORNERS], morph: f32, q: f32) -> [[f32; 5]; STAGES] {
    let mut out = [[0.0; 5]; STAGES];
    for stage in 0..STAGES {
        let mut w = [0u16; 5];
        for k in 0..5 {
            let low = lerp_word(words[0][stage][k], words[1][stage][k], morph);
            let high = lerp_word(words[2][stage][k], words[3][stage][k], morph);
            w[k] = lerp_word(low, high, q);
        }
        out[stage] = words_to_biquad(w);
    }
    out
}

fn lerp_word(a: u16, b: u16, t: f32) -> u16 {
    let product = (b as i32 - a as i32) as f32 * t;
    let trunc = product.trunc() as i32;
    let delta = (trunc + 0x8000).rem_euclid(0x1_0000) - 0x8000;
    ((a as i32 + delta) & 0xffff) as u16
}

fn words_to_biquad(w: [u16; 5]) -> [f32; 5] {
    let d = w.map(|x| trench_core::minifloat::decode(x) as f32);
    let c0 = 4.0 * d[0] + d[1];
    let c1 = d[1];
    let c2 = 4.0 * d[2] + d[3];
    let c3 = d[3];
    let c4 = 4.0 * d[4];
    [c4, (c0 - 2.0) * c4, (1.0 - c1) * c4, c2 - 2.0, 1.0 - c3]
}

fn cascade_db(stages: &[[f32; 5]; STAGES], freq: f32) -> f32 {
    let (c1, c2) = trig_of(freq);
    cascade_db_c(stages, c1, c2)
}

fn cascade_db_c(stages: &[[f32; 5]; STAGES], c1: f64, c2: f64) -> f32 {
    stages.iter().map(|bq| biquad_db_c(*bq, c1, c2)).sum()
}

/// (cos ω, cos 2ω) for a frequency — all the magnitude math ever needs.
/// f64 throughout: the power form cancels catastrophically at notches, so
/// both the trig and the accumulation need the full mantissa.
fn trig_of(freq: f32) -> (f64, f64) {
    let c1 = (std::f64::consts::TAU * freq as f64 / SR as f64).cos();
    (c1, 2.0 * c1 * c1 - 1.0)
}

/// (cos ω, cos 2ω) for the fixed log grids, computed once per size — the
/// display plot (480), the heat map (320) and the 17×17 audit (96) all reuse
/// these every frame/job instead of recomputing transcendentals.
fn grid_trig(n: usize) -> &'static [(f64, f64)] {
    use std::sync::OnceLock;
    static G_PLOT: OnceLock<Vec<(f64, f64)>> = OnceLock::new();
    static G_HEAT: OnceLock<Vec<(f64, f64)>> = OnceLock::new();
    static G_AUDIT: OnceLock<Vec<(f64, f64)>> = OnceLock::new();
    let cell = match n {
        FREQ_BINS => &G_PLOT,
        HEAT_W => &G_HEAT,
        AUDIT_BINS => &G_AUDIT,
        _ => unreachable!("grid_trig: unregistered grid size {n}"),
    };
    cell.get_or_init(|| (0..n).map(|i| trig_of(freq_at(i, n))).collect())
}

/// |H| dB from cos ω / cos 2ω only — the sin terms cancel:
/// |b0 + b1 e^{-jω} + b2 e^{-j2ω}|² = b0²+b1²+b2² + 2(b0b1+b1b2)cos ω + 2 b0b2 cos 2ω
fn biquad_db_c(b: [f32; 5], c1: f64, c2: f64) -> f32 {
    let (b0, b1, b2) = (b[0] as f64, b[1] as f64, b[2] as f64);
    let (a1, a2) = (b[3] as f64, b[4] as f64);
    let num = b0 * b0 + b1 * b1 + b2 * b2 + 2.0 * (b0 * b1 + b1 * b2) * c1 + 2.0 * b0 * b2 * c2;
    let den = 1.0 + a1 * a1 + a2 * a2 + 2.0 * (a1 + a1 * a2) * c1 + 2.0 * a2 * c2;
    (10.0 * (num.max(1e-24) / den.max(1e-24)).log10()) as f32
}

fn biquad_db(b: [f32; 5], freq: f32) -> f32 {
    let (c1, c2) = trig_of(freq);
    biquad_db_c(b, c1, c2)
}

/// reference implementation (the old 4-transcendental complex form) — kept
/// only for the --mag-test equivalence proof
#[allow(dead_code)]
fn biquad_db_ref(b: [f32; 5], freq: f32) -> f32 {
    let w = TAU32 * freq / SR;
    let c1 = w.cos();
    let s1 = w.sin();
    let c2 = (2.0 * w).cos();
    let s2 = (2.0 * w).sin();
    let nr = b[0] + b[1] * c1 + b[2] * c2;
    let ni = -(b[1] * s1 + b[2] * s2);
    let dr = 1.0 + b[3] * c1 + b[4] * c2;
    let di = -(b[3] * s1 + b[4] * s2);
    20.0 * (nr.hypot(ni) / dr.hypot(di).max(1e-9)).max(1e-9).log10()
}

fn stages_max_pole_radius(stages: &[[f32; 5]; STAGES]) -> f32 {
    let mut worst = 0.0f32;
    for bq in stages {
        let (a1, a2) = (bq[3], bq[4]);
        let disc = a1 * a1 - 4.0 * a2;
        let r = if disc < 0.0 {
            a2.max(0.0).sqrt()
        } else {
            let sq = disc.sqrt();
            ((-a1 + sq) / 2.0).abs().max(((-a1 - sq) / 2.0).abs())
        };
        if !r.is_finite() {
            return f32::INFINITY;
        }
        worst = worst.max(r);
    }
    worst
}

fn freq_at(i: usize, n: usize) -> f32 {
    F_MIN * (F_MAX / F_MIN).powf(i as f32 / (n - 1) as f32)
}

// ── display frequency axis: log (default) or Bark (Traunmüller 1990) ─────────
// DSP bins stay log-spaced; only the screen mapping warps.

static BARK: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

fn bark_z(f: f32) -> f32 {
    26.81 * f / (1960.0 + f) - 0.53
}

/// frequency → 0..1 position on the display axis
fn axis_t(f: f32) -> f32 {
    if BARK.load(std::sync::atomic::Ordering::Relaxed) {
        (bark_z(f) - bark_z(F_MIN)) / (bark_z(F_MAX) - bark_z(F_MIN))
    } else {
        (f / F_MIN).log2() / (F_MAX / F_MIN).log2()
    }
}

/// Bark → frequency (inverse of bark_z), clamped to the working band
fn bark_f(z: f32) -> f32 {
    (1960.0 * (z + 0.53) / (26.28 - z)).clamp(F_MIN, F_MAX)
}

/// 0..1 display position → frequency
fn axis_f(t: f32) -> f32 {
    if BARK.load(std::sync::atomic::Ordering::Relaxed) {
        bark_f(bark_z(F_MIN) + t.clamp(0.0, 1.0) * (bark_z(F_MAX) - bark_z(F_MIN)))
    } else {
        F_MIN * (F_MAX / F_MIN).powf(t.clamp(0.0, 1.0))
    }
}

/// frequency → index into a log-spaced bin array (independent of display axis)
fn bin_for_freq(f: f32, n: usize) -> usize {
    let t = (f / F_MIN).log2() / (F_MAX / F_MIN).log2();
    (t.clamp(0.0, 1.0) * (n - 1) as f32).round() as usize
}

fn db_to_lin(db: f32) -> f32 {
    10.0_f32.powf(db / 20.0)
}

fn lin_to_db(lin: f32) -> f32 {
    20.0 * lin.max(1.0e-6).log10()
}

fn format_freq(freq: f32) -> String {
    if freq >= 1000.0 {
        format!("{:.1}k", freq / 1000.0)
    } else {
        format!("{:.0} Hz", freq)
    }
}

fn x_for_freq(rect: Rect, freq: f32) -> f32 {
    rect.left() + axis_t(freq).clamp(0.0, 1.0) * rect.width()
}

fn y_for_db(rect: Rect, db: f32) -> f32 {
    let t = ((db.clamp(DB_MIN, DB_MAX) - DB_MIN) / (DB_MAX - DB_MIN)).clamp(0.0, 1.0);
    rect.bottom() - t * rect.height()
}

/// Absolute heat ramp: ≤−12 dB → background · 0 → violet · +20 → rust ·
/// +33 → amber · +44 → pale; holds hot above. Never autoscaled.
fn heat_color(db: f32) -> Color32 {
    let stops = [
        (-12.0, [11.0, 11.0, 13.0]),
        (0.0, [52.0, 27.0, 77.0]),
        (20.0, [138.0, 61.0, 42.0]),
        (33.0, [199.0, 116.0, 31.0]),
        (44.0, [246.0, 232.0, 200.0]),
    ];
    if db <= stops[0].0 {
        return Color32::from_rgb(
            stops[0].1[0] as u8,
            stops[0].1[1] as u8,
            stops[0].1[2] as u8,
        );
    }
    for i in 1..stops.len() {
        if db <= stops[i].0 {
            let (d0, c0) = stops[i - 1];
            let (d1, c1) = stops[i];
            let t = ((db - d0) / (d1 - d0)).clamp(0.0, 1.0);
            return Color32::from_rgb(
                (c0[0] + (c1[0] - c0[0]) * t) as u8,
                (c0[1] + (c1[1] - c0[1]) * t) as u8,
                (c0[2] + (c1[2] - c0[2]) * t) as u8,
            );
        }
    }
    Color32::from_rgb(250, 245, 235)
}

// ── minimal WAV reader (PCM 16/24/32 + float32, first channel) ────────────────

fn parse_wav(bytes: &[u8]) -> Option<(Vec<f64>, f64)> {
    if bytes.len() < 44 || &bytes[0..4] != b"RIFF" || &bytes[8..12] != b"WAVE" {
        return None;
    }
    let mut pos = 12;
    let mut format = 0u16;
    let mut channels = 1u16;
    let mut sample_rate = 0u32;
    let mut bits = 0u16;
    let mut data: Option<&[u8]> = None;
    while pos + 8 <= bytes.len() {
        let id = &bytes[pos..pos + 4];
        let size = u32::from_le_bytes(bytes[pos + 4..pos + 8].try_into().ok()?) as usize;
        let body = bytes.get(pos + 8..pos + 8 + size)?;
        match id {
            b"fmt " if size >= 16 => {
                format = u16::from_le_bytes([body[0], body[1]]);
                channels = u16::from_le_bytes([body[2], body[3]]).max(1);
                sample_rate = u32::from_le_bytes([body[4], body[5], body[6], body[7]]);
                bits = u16::from_le_bytes([body[14], body[15]]);
            }
            b"data" => data = Some(body),
            _ => {}
        }
        pos += 8 + size + (size & 1);
    }
    let data = data?;
    if sample_rate == 0 {
        return None;
    }
    let ch = channels as usize;
    let mut out = Vec::new();
    match (format, bits) {
        (1, 16) => {
            for frame in data.chunks_exact(2 * ch) {
                out.push(i16::from_le_bytes([frame[0], frame[1]]) as f64 / 32768.0);
            }
        }
        (1, 24) => {
            for frame in data.chunks_exact(3 * ch) {
                let v =
                    ((frame[2] as i32) << 24 | (frame[1] as i32) << 16 | (frame[0] as i32) << 8)
                        >> 8;
                out.push(v as f64 / 8_388_608.0);
            }
        }
        (1, 32) => {
            for frame in data.chunks_exact(4 * ch) {
                out.push(
                    i32::from_le_bytes([frame[0], frame[1], frame[2], frame[3]]) as f64
                        / 2_147_483_648.0,
                );
            }
        }
        (3, 32) => {
            for frame in data.chunks_exact(4 * ch) {
                out.push(f32::from_le_bytes([frame[0], frame[1], frame[2], frame[3]]) as f64);
            }
        }
        _ => return None,
    }
    if out.is_empty() {
        return None;
    }
    Some((out, sample_rate as f64))
}
