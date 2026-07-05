//! df2 forge — bench.
//!
//! A dev tool, drawn like a wiring schematic. Plain words on screen, real machinery underneath.
//! Sound in -> THE SHAPE (six parts, four corner slots) -> THE PUNCH -> out, with the result drawn.
//!
//! The packed/blend math is a faithful port of the DLL-verified `pyruntime/packed_interp.py`
//! (encode/decode minifloat + wrap-lerp). The saved file is the real 240-byte body.

use eframe::egui::{self, Align2, Color32, FontId, Pos2, Rect, Rounding, Sense, Stroke};
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use serde::Deserialize;
use trench_core::{Cartridge, FilterEngine, InputMode, SpatialMode};

mod letters;

const SR: f64 = 39_062.5;
const TAU: f64 = std::f64::consts::PI * 2.0;

// ---------------------------------------------------------------------------
// minifloat codec — delegate to trench-core's CANONICAL encode/decode (the
// single owner). The plot, the audio, and the bake all encode through the same
// function the shipped DLL uses, so they can never disagree on a word's value.
// kernel<->biquad below is pure arithmetic over these two codecs.
// ---------------------------------------------------------------------------
fn decode(word: u16) -> f64 {
    trench_core::minifloat::decode(word)
}

fn encode(v: f64) -> u16 {
    trench_core::minifloat::encode(v)
}

fn lerp_u16(a: u16, b: u16, frac: f32) -> u16 {
    trench_core::minifloat::lerp_u16(a, b, frac)
}

// kernel <-> biquad (faithful)
fn words_to_biquad(w: [u16; 5]) -> [f64; 5] {
    let d: Vec<f64> = w.iter().map(|&x| decode(x)).collect();
    let c0 = 4.0 * d[0] + d[1];
    let c1 = d[1];
    let c2 = 4.0 * d[2] + d[3];
    let c3 = d[3];
    let c4 = 4.0 * d[4];
    // (b0, b1, b2, a1, a2)
    [c4, (c0 - 2.0) * c4, (1.0 - c1) * c4, c2 - 2.0, 1.0 - c3]
}

fn biquad_to_words(b: [f64; 5]) -> [u16; 5] {
    let (b0, b1, b2, a1, a2) = (b[0], b[1], b[2], b[3], b[4]);
    let c4 = b0;
    let c0 = if c4 != 0.0 { b1 / c4 + 2.0 } else { 2.0 };
    let c1 = if c4 != 0.0 { 1.0 - b2 / c4 } else { 1.0 };
    let c2 = a1 + 2.0;
    let c3 = 1.0 - a2;
    [
        encode((c0 - c1) / 4.0),
        encode(c1),
        encode((c2 - c3) / 4.0),
        encode(c3),
        encode(c4 / 4.0),
    ]
}

fn biquad_mag_db(b: [f64; 5], f: f64) -> f64 {
    let w = TAU * f / SR;
    let (c1, c2, s1, s2) = (w.cos(), (2.0 * w).cos(), w.sin(), (2.0 * w).sin());
    let nr = b[0] + b[1] * c1 + b[2] * c2;
    let ni = -(b[1] * s1 + b[2] * s2);
    let dr = 1.0 + b[3] * c1 + b[4] * c2;
    let di = -(b[3] * s1 + b[4] * s2);
    10.0 * ((nr * nr + ni * ni) / (dr * dr + di * di + 1e-12)).log10()
}

// ---------------------------------------------------------------------------
// raw-word body: 4 corners x 6 parts x 5 packed words. This is what a `.body240`
// IS on disk and what the engine runs. The authored `Body` (Parts) bakes DOWN to
// this; a loaded body comes back UP as these words (no lossy Part inversion).
// All plotting/blending goes through ONE lerp path so author and cull can never
// disagree on a word's value — see [[packed-math-triplicated]].
// ---------------------------------------------------------------------------
type CornerWords = [[[u16; 5]; 6]; 4];

fn words_from_body_bytes(b: &[u8]) -> Option<CornerWords> {
    if b.len() != 240 {
        return None;
    }
    let mut c = [[[0u16; 5]; 6]; 4];
    let mut i = 0;
    for corner in c.iter_mut() {
        for part in corner.iter_mut() {
            for w in part.iter_mut() {
                *w = u16::from_le_bytes([b[i], b[i + 1]]);
                i += 2;
            }
        }
    }
    Some(c)
}

fn words_to_body_bytes(c: &CornerWords) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(240);
    for corner in c {
        for part in corner {
            for &w in part {
                bytes.extend_from_slice(&w.to_le_bytes());
            }
        }
    }
    bytes
}

// live coeffs at (morph, q): faithful per-part wrap-lerp of the four corners in
// packed space. THE single blend implementation.
fn live_words(c: &CornerWords, morph: f32, q: f32) -> [[f64; 5]; 6] {
    let mut out = [[0.0; 5]; 6];
    for p in 0..6 {
        let (a, b, cc, d) = (c[0][p], c[1][p], c[2][p], c[3][p]);
        let mut w = [0u16; 5];
        for k in 0..5 {
            let e0 = lerp_u16(a[k], b[k], morph);
            let e1 = lerp_u16(cc[k], d[k], morph);
            w[k] = lerp_u16(e0, e1, q);
        }
        out[p] = words_to_biquad(w);
    }
    out
}

fn stages_mag(stages: &[[f64; 5]; 6], f: f64) -> f64 {
    stages.iter().map(|s| biquad_mag_db(*s, f)).sum()
}

// worst pole radius across the live stages (≥1 = will blow up)
fn stages_worst_radius(stages: &[[f64; 5]; 6]) -> f64 {
    stages
        .iter()
        .map(|s| {
            let (a1, a2) = (s[3], s[4]);
            let disc = a1 * a1 - 4.0 * a2;
            if disc < 0.0 {
                a2.max(0.0).sqrt()
            } else {
                let sq = disc.sqrt();
                ((-a1 + sq) / 2.0).abs().max(((-a1 - sq) / 2.0).abs())
            }
        })
        .fold(0.0, f64::max)
}

// ---------------------------------------------------------------------------
// the body
// ---------------------------------------------------------------------------
#[derive(Clone, Copy, PartialEq)]
enum Cut {
    None,
    Hug,
    Tear,
    /// Deep notch hugging just below the pole — a steep valley beside the
    /// resonance. SEED value (pole×0.9, depth 0.95); judge by plot, tune freely.
    Canyon,
    SubKill,
    AirCap,
    AirKill,
    /// FOUNDATION null: a TRUE unit-circle zero (r = 1.0 exactly) at its own
    /// absolute frequency (`Part::zspot`) — the stage-6 letter all three
    /// studied iconics carry at every corner (STATE.md dossier; observed zero
    /// travel ~6.4k-18k Hz).
    Null,
    /// Bake-only: an explicit zero authored relative to the pole.
    /// `absolute` → zero_hz = ratio (Hz); else zero_hz = pole_hz * ratio.
    Custom { ratio: f64, depth: f64, absolute: bool },
}
impl Cut {
    // the clean-room per-lane articulation set (one-row zeros). Order = chip order.
    const ALL: [Cut; 8] = [Cut::None, Cut::Hug, Cut::Tear, Cut::Canyon, Cut::AirCap, Cut::SubKill, Cut::AirKill, Cut::Null];
    // short chip face — minimal text on screen
    fn chip(self) -> &'static str {
        match self {
            Cut::None => "—",
            Cut::Hug => "hug",
            Cut::Tear => "tear",
            Cut::Canyon => "canyon",
            Cut::AirCap => "cap",
            Cut::SubKill => "sub",
            Cut::AirKill => "airk",
            Cut::Null => "null",
            Cut::Custom { .. } => "·",
        }
    }
}

#[derive(Clone, Copy)]
struct Part {
    on: bool,   // active pole, or parked (flat passthrough)
    spot: f64,  // where it sits (Hz)
    sharp: f64, // how sharp (pole radius 0.5..0.9999)
    loud: f64,  // how loud (section gain mult)
    cut: Cut,   // where it scoops
    zspot: f64, // absolute zero Hz — read by Cut::Null only
}
impl Part {
    fn biquad(&self) -> [f64; 5] {
        // parked row = identity (flat). You build a body by ADDING poles, not by
        // starting from six. Zeros stay parked (Cut::None) until you carve.
        if !self.on {
            return [1.0, 0.0, 0.0, 0.0, 0.0];
        }
        let fp = self.spot.clamp(20.0, SR * 0.49);
        let rp = self.sharp.clamp(0.5, 0.9999);
        let wp = TAU * fp / SR;
        let a1 = -2.0 * rp * wp.cos();
        let a2 = rp * rp;
        // zero from the cut rule
        let (fz, rz) = match self.cut {
            Cut::None => (fp, 0.0),
            Cut::Hug => (fp * 0.6674, 0.60),
            Cut::Tear => (fp * 1.15, 0.92),
            Cut::Canyon => (fp * 0.9, 0.95),
            Cut::SubKill => (fp * 0.25, 0.85),
            Cut::AirCap => (fp * 4.0, 0.60),
            Cut::AirKill => (12000.0, 0.70),
            Cut::Null => (self.zspot, 1.0),
            Cut::Custom { ratio, depth, absolute } => {
                (if absolute { ratio } else { fp * ratio }, depth)
            }
        };
        if rz == 0.0 {
            // pure resonator, tamed to ~unity peak
            let g = (1.0 - rp * rp).max(1e-4) * self.loud;
            return [g, 0.0, 0.0, a1, a2];
        }
        let wz = TAU * fz.clamp(20.0, SR * 0.49) / SR;
        let nb1 = -2.0 * rz * wz.cos();
        let nb2 = rz * rz;
        let g = if self.cut == Cut::Null {
            // FOUNDATION law: anchor at the geometric mid between pole and zero
            // (neutral mids). DC weight + top kill then follow from the pole,
            // as in the measured stage-6 anatomy. DC-normalizing this letter
            // slides the whole descent down and buries the other lanes
            // (Tyson-caught 2026-07-05).
            let fr = (fp * fz.clamp(20.0, SR * 0.49)).sqrt();
            let mid = 10f64.powf(biquad_mag_db([1.0, nb1, nb2, a1, a2], fr) / 20.0);
            self.loud / mid.max(1e-9)
        } else {
            // unity-DC gain so cuts shape without exploding level, scaled by loud
            (1.0 + a1 + a2) / (1.0 + nb1 + nb2).max(1e-9) * self.loud
        };
        [g, g * nb1, g * nb2, a1, a2]
    }
    fn words(&self) -> [u16; 5] {
        biquad_to_words(self.biquad())
    }
}

struct Body {
    name: String,
    corners: [[Part; 6]; 4], // 4 saved versions x 6 parts
}

#[derive(Clone, Copy, PartialEq)]
enum PresetKind {
    Vowel,
    Comb,
    Canyon,
    Cliff,
}

fn part(on: bool, spot: f64, sharp: f64, loud: f64, cut: Cut) -> Part {
    // zspot default sits mid the observed foundation-zero travel band (6.4k-18k)
    Part { on, spot, sharp, loud, cut, zspot: 8000.0 }
}

// foundation lane: the stage-6 letter every musical ROM body carries (33/33) —
// a TRUE unit-circle zero at `zspot`, per-corner so the null travels with morph.
fn fpart(spot: f64, sharp: f64, loud: f64, zspot: f64) -> Part {
    Part { on: true, spot, sharp, loud, cut: Cut::Null, zspot }
}

impl Body {
    fn starter() -> Self {
        Body::preset(PresetKind::Vowel)
    }

    fn preset(kind: PresetKind) -> Self {
        match kind {
            PresetKind::Vowel => Body {
                name: "vowel_canyons_01".into(),
                corners: [
                    [
                        part(true, 220.0, 0.9978, 1.05, Cut::Canyon),
                        part(true, 620.0, 0.9820, 0.92, Cut::Hug),
                        part(true, 1450.0, 0.9880, 0.86, Cut::Canyon),
                        part(true, 3200.0, 0.9750, 0.58, Cut::Tear),
                        part(true, 7800.0, 0.8800, 0.34, Cut::AirKill),
                        fpart(4200.0, 0.7200, 0.62, 9000.0),
                    ],
                    [
                        part(true, 260.0, 0.9975, 1.00, Cut::Canyon),
                        part(true, 840.0, 0.9860, 0.88, Cut::Hug),
                        part(true, 2050.0, 0.9900, 0.92, Cut::Canyon),
                        part(true, 4100.0, 0.9820, 0.66, Cut::Tear),
                        part(true, 9200.0, 0.8600, 0.30, Cut::AirKill),
                        fpart(5200.0, 0.7400, 0.58, 12500.0),
                    ],
                    [
                        part(true, 220.0, 0.9999, 1.18, Cut::Canyon),
                        part(true, 620.0, 0.9975, 1.02, Cut::Hug),
                        part(true, 1450.0, 0.9984, 0.94, Cut::Canyon),
                        part(true, 3200.0, 0.9940, 0.64, Cut::Tear),
                        part(true, 7800.0, 0.9300, 0.30, Cut::AirKill),
                        fpart(4200.0, 0.7800, 0.70, 9000.0),
                    ],
                    [
                        part(true, 260.0, 0.9999, 1.14, Cut::Canyon),
                        part(true, 840.0, 0.9980, 1.03, Cut::Hug),
                        part(true, 2050.0, 0.9988, 1.02, Cut::Canyon),
                        part(true, 4100.0, 0.9960, 0.70, Cut::Tear),
                        part(true, 9200.0, 0.9300, 0.28, Cut::AirKill),
                        fpart(5200.0, 0.8000, 0.68, 12500.0),
                    ],
                ],
            },
            PresetKind::Comb => Body {
                name: "six_comb_field_01".into(),
                corners: [
                    [
                        part(true, 180.0, 0.9600, 0.90, Cut::SubKill),
                        part(true, 410.0, 0.9720, 0.62, Cut::Canyon),
                        part(true, 820.0, 0.9780, 0.74, Cut::Tear),
                        part(true, 1640.0, 0.9820, 0.52, Cut::Canyon),
                        part(true, 3280.0, 0.9860, 0.58, Cut::Tear),
                        fpart(6560.0, 0.9800, 0.38, 11000.0),
                    ],
                    [
                        part(true, 240.0, 0.9580, 0.82, Cut::SubKill),
                        part(true, 545.0, 0.9780, 0.72, Cut::Tear),
                        part(true, 1090.0, 0.9840, 0.54, Cut::Canyon),
                        part(true, 2180.0, 0.9890, 0.70, Cut::Tear),
                        part(true, 4360.0, 0.9920, 0.46, Cut::Canyon),
                        fpart(8720.0, 0.9820, 0.34, 14500.0),
                    ],
                    [
                        part(true, 180.0, 0.9920, 0.98, Cut::SubKill),
                        part(true, 410.0, 0.9970, 0.68, Cut::Canyon),
                        part(true, 820.0, 0.9978, 0.82, Cut::Tear),
                        part(true, 1640.0, 0.9984, 0.58, Cut::Canyon),
                        part(true, 3280.0, 0.9990, 0.64, Cut::Tear),
                        fpart(6560.0, 0.9960, 0.36, 11000.0),
                    ],
                    [
                        part(true, 240.0, 0.9920, 0.92, Cut::SubKill),
                        part(true, 545.0, 0.9975, 0.80, Cut::Tear),
                        part(true, 1090.0, 0.9982, 0.58, Cut::Canyon),
                        part(true, 2180.0, 0.9990, 0.76, Cut::Tear),
                        part(true, 4360.0, 0.9995, 0.50, Cut::Canyon),
                        fpart(8720.0, 0.9960, 0.32, 14500.0),
                    ],
                ],
            },
            PresetKind::Canyon => Body {
                name: "remote_canyon_01".into(),
                corners: [
                    [
                        part(true, 190.0, 0.9970, 1.04, Cut::Canyon),
                        part(true, 450.0, 0.9300, 0.74, Cut::Custom { ratio: 134.0, depth: 0.94, absolute: true }),
                        part(true, 780.0, 0.9700, 0.76, Cut::Custom { ratio: 4130.0, depth: 0.96, absolute: true }),
                        part(true, 2220.0, 0.9500, 0.52, Cut::Custom { ratio: 545.0, depth: 0.96, absolute: true }),
                        part(true, 3790.0, 0.9440, 0.44, Cut::Custom { ratio: 9650.0, depth: 0.98, absolute: true }),
                        fpart(8250.0, 0.8300, 0.28, 13500.0),
                    ],
                    [
                        part(true, 320.0, 0.9965, 1.00, Cut::Canyon),
                        part(true, 545.0, 0.9400, 0.62, Cut::Custom { ratio: 200.0, depth: 0.95, absolute: true }),
                        part(true, 1090.0, 0.9750, 0.82, Cut::Custom { ratio: 780.0, depth: 0.94, absolute: true }),
                        part(true, 2840.0, 0.9600, 0.50, Cut::Custom { ratio: 8250.0, depth: 0.98, absolute: true }),
                        part(true, 5450.0, 0.9500, 0.40, Cut::Custom { ratio: 8875.0, depth: 0.98, absolute: true }),
                        fpart(11200.0, 0.8200, 0.24, 17000.0),
                    ],
                    [
                        part(true, 190.0, 0.9999, 1.20, Cut::Canyon),
                        part(true, 450.0, 0.9650, 0.82, Cut::Custom { ratio: 110.0, depth: 0.985, absolute: true }),
                        part(true, 780.0, 0.9940, 0.84, Cut::Custom { ratio: 4130.0, depth: 0.99, absolute: true }),
                        part(true, 2220.0, 0.9820, 0.56, Cut::Custom { ratio: 545.0, depth: 0.99, absolute: true }),
                        part(true, 3790.0, 0.9780, 0.48, Cut::Custom { ratio: 9650.0, depth: 0.99, absolute: true }),
                        fpart(8250.0, 0.8800, 0.24, 13500.0),
                    ],
                    [
                        part(true, 320.0, 0.9999, 1.16, Cut::Canyon),
                        part(true, 545.0, 0.9680, 0.70, Cut::Custom { ratio: 180.0, depth: 0.985, absolute: true }),
                        part(true, 1090.0, 0.9950, 0.90, Cut::Custom { ratio: 780.0, depth: 0.98, absolute: true }),
                        part(true, 2840.0, 0.9860, 0.54, Cut::Custom { ratio: 8250.0, depth: 0.99, absolute: true }),
                        part(true, 5450.0, 0.9820, 0.44, Cut::Custom { ratio: 8875.0, depth: 0.99, absolute: true }),
                        fpart(11200.0, 0.8800, 0.22, 17000.0),
                    ],
                ],
            },
            PresetKind::Cliff => Body {
                name: "slope_cliff_01".into(),
                corners: [
                    [
                        part(true, 240.0, 0.9970, 1.08, Cut::Canyon),
                        part(true, 520.0, 0.9100, 0.80, Cut::Hug),
                        part(true, 1100.0, 0.7800, 0.58, Cut::AirCap),
                        part(true, 2400.0, 0.7200, 0.40, Cut::AirKill),
                        part(true, 5200.0, 0.6800, 0.28, Cut::AirKill),
                        fpart(14000.0, 0.6200, 0.20, 17500.0),
                    ],
                    [
                        part(true, 360.0, 0.9960, 1.02, Cut::Canyon),
                        part(true, 760.0, 0.9300, 0.70, Cut::Hug),
                        part(true, 1500.0, 0.8200, 0.48, Cut::AirCap),
                        part(true, 3300.0, 0.7600, 0.36, Cut::AirKill),
                        part(true, 7200.0, 0.7000, 0.24, Cut::AirKill),
                        fpart(16000.0, 0.6400, 0.18, 18000.0),
                    ],
                    [
                        part(true, 240.0, 0.9999, 1.22, Cut::Canyon),
                        part(true, 520.0, 0.9720, 0.84, Cut::Hug),
                        part(true, 1100.0, 0.9000, 0.54, Cut::AirCap),
                        part(true, 2400.0, 0.8600, 0.34, Cut::AirKill),
                        part(true, 5200.0, 0.8200, 0.22, Cut::AirKill),
                        fpart(14000.0, 0.7600, 0.16, 17500.0),
                    ],
                    [
                        part(true, 360.0, 0.9999, 1.18, Cut::Canyon),
                        part(true, 760.0, 0.9760, 0.74, Cut::Hug),
                        part(true, 1500.0, 0.9200, 0.46, Cut::AirCap),
                        part(true, 3300.0, 0.8800, 0.30, Cut::AirKill),
                        part(true, 7200.0, 0.8400, 0.20, Cut::AirKill),
                        fpart(16000.0, 0.7800, 0.14, 18000.0),
                    ],
                ],
            },
        }
    }

    // the four corners as raw packed words — the bake-down shared with cull.
    fn words_all(&self) -> CornerWords {
        std::array::from_fn(|c| std::array::from_fn(|p| self.corners[c][p].words()))
    }

    // live coeffs at (morph, q): delegate to the single shared blend path.
    fn live(&self, morph: f32, q: f32) -> [[f64; 5]; 6] {
        live_words(&self.words_all(), morph, q)
    }

    fn worst_radius(&self, stages: &[[f64; 5]; 6]) -> f64 {
        stages_worst_radius(stages)
    }

    fn pack_240(&self) -> Vec<u8> {
        words_to_body_bytes(&self.words_all())
    }
}

// ---------------------------------------------------------------------------
// audio — play through the SHARED trench-core engine (real AGC + grit + wide),
// never a bare filter. The engine runs at the body's native 39062.5 so what you
// hear lands where the plot draws it; we linearly resample to the device rate.
// ---------------------------------------------------------------------------
struct Shared {
    playing: AtomicBool,
    morph: AtomicU32, // f32 bits
    q: AtomicU32,
    tame: AtomicU32, // -> agc_drive 1..8 (the E-mu compression character)
    grit: AtomicU32, // -> Mackie desk slam 0..1
    wide: AtomicU32, // -> QSound space 0..1
    src: AtomicUsize,
    body_gen: AtomicU64,    // bumped whenever the body bytes change
    body: Mutex<[u8; 240]>, // latest packed body for the audio thread to load
}
impl Shared {
    fn new() -> Self {
        Shared {
            playing: AtomicBool::new(false),
            morph: AtomicU32::new(0.33f32.to_bits()),
            q: AtomicU32::new(0.0f32.to_bits()),
            tame: AtomicU32::new(0.5f32.to_bits()),
            grit: AtomicU32::new(0.3f32.to_bits()),
            wide: AtomicU32::new(0.4f32.to_bits()),
            src: AtomicUsize::new(0),
            body_gen: AtomicU64::new(0),
            body: Mutex::new([0u8; 240]),
        }
    }
    fn set_f(&self, a: &AtomicU32, v: f32) {
        a.store(v.to_bits(), Ordering::Relaxed);
    }
    fn get_f(a: &AtomicU32) -> f32 {
        f32::from_bits(a.load(Ordering::Relaxed))
    }
    fn publish_body(&self, bytes: &[u8]) {
        self.body.lock().unwrap().copy_from_slice(bytes);
        self.body_gen.fetch_add(1, Ordering::Release);
    }
}

// one source sample in the engine domain (39062.5 Hz)
fn gen_source(src: usize, phase: &mut f64, kick_t: &mut f64, rng: &mut u32, sr: f64) -> f32 {
    match src {
        1 => {
            // white noise (xorshift)
            *rng ^= *rng << 13;
            *rng ^= *rng >> 17;
            *rng ^= *rng << 5;
            (*rng as f32 / u32::MAX as f32 * 2.0 - 1.0) * 0.4
        }
        2 => {
            // 808: retriggering pitch-drop sine
            if *kick_t >= 0.6 {
                *kick_t = 0.0;
            }
            let t = *kick_t;
            let f = 46.0 + 44.0 * (-t * 16.0).exp();
            *phase += f / sr;
            if *phase >= 1.0 {
                *phase -= 1.0;
            }
            let env = (-t * 4.5).exp();
            *kick_t += 1.0 / sr;
            (*phase * TAU).sin() as f32 * env as f32 * 0.7
        }
        3 => {
            // voice excitation — a buzz the body shapes into a vowel
            *phase += 110.0 / sr;
            if *phase >= 1.0 {
                *phase -= 1.0;
            }
            (2.0 * *phase as f32 - 1.0) * 0.4
        }
        _ => {
            // saw bass
            *phase += 55.0 / sr;
            if *phase >= 1.0 {
                *phase -= 1.0;
            }
            (2.0 * *phase as f32 - 1.0) * 0.5
        }
    }
}

fn build_stream<T>(
    device: &cpal::Device,
    config: &cpal::StreamConfig,
    shared: Arc<Shared>,
) -> Result<cpal::Stream, cpal::BuildStreamError>
where
    T: cpal::SizedSample + cpal::FromSample<f32>,
{
    let channels = config.channels.max(1) as usize;
    let device_rate = config.sample_rate.0 as f64;
    let step = SR / device_rate; // engine samples consumed per output sample

    let mut engine = FilterEngine::new();
    engine.prepare(SR);
    engine.debug.agc_enabled = true;

    let mut last_gen = u64::MAX;
    let mut phase = 0.0f64;
    let mut kick_t = 1.0e9f64;
    let mut rng = 0x9E37_79B9u32;
    let mut il = vec![0.0f32; 256];
    let mut ir = vec![0.0f32; 256];
    let mut ql: Vec<f32> = Vec::with_capacity(2048); // processed engine-domain L
    let mut qr: Vec<f32> = Vec::with_capacity(2048); // processed engine-domain R
    let mut frac = 0.0f64; // fractional read position into ql/qr

    device.build_output_stream(
        config,
        move |out: &mut [T], _: &cpal::OutputCallbackInfo| {
            let frames = out.len() / channels;
            if !shared.playing.load(Ordering::Relaxed) {
                for s in out.iter_mut() {
                    *s = T::from_sample(0.0f32);
                }
                ql.clear();
                qr.clear();
                frac = 0.0;
                return;
            }

            // reload the body when it changed in the UI
            let gen = shared.body_gen.load(Ordering::Acquire);
            if gen != last_gen {
                let bytes = *shared.body.lock().unwrap();
                if let Ok(cart) = Cartridge::from_body_bytes("bench", &bytes, 1.0) {
                    engine.load_cartridge(cart);
                }
                last_gen = gen;
            }

            // live params -> the driven chain (never a bare filter)
            let morph = Shared::get_f(&shared.morph) as f64;
            let q = Shared::get_f(&shared.q) as f64;
            engine.set_agc_drive(1.0 + Shared::get_f(&shared.tame) * 7.0);
            let grit = Shared::get_f(&shared.grit);
            engine.set_slam_drive(grit);
            engine.set_input_mode(if grit > 0.02 {
                InputMode::MackieDeskSlam
            } else {
                InputMode::None
            });
            engine.set_space(Shared::get_f(&shared.wide));
            engine.set_spatial_mode(SpatialMode::QSound);
            let src = shared.src.load(Ordering::Relaxed);

            // generate + process enough engine-domain samples for this callback
            let need = (frac + frames as f64 * step).ceil() as usize + 2;
            while ql.len() < need {
                for i in 0..256 {
                    let s = gen_source(src, &mut phase, &mut kick_t, &mut rng, SR);
                    il[i] = s;
                    ir[i] = s;
                }
                engine.process_block(&mut il, &mut ir, morph, q);
                ql.extend_from_slice(&il);
                qr.extend_from_slice(&ir);
            }

            // linear-resample to the device rate
            let master = 0.6f32;
            for f in 0..frames {
                let idx = frac.floor() as usize;
                let t = (frac - idx as f64) as f32;
                let l = (ql[idx] + (ql[idx + 1] - ql[idx]) * t) * master;
                let r = (qr[idx] + (qr[idx + 1] - qr[idx]) * t) * master;
                for ch in 0..channels {
                    let v = if channels == 1 {
                        (l + r) * 0.5
                    } else if ch == 0 {
                        l
                    } else if ch == 1 {
                        r
                    } else {
                        0.0
                    };
                    out[f * channels + ch] = T::from_sample(v.clamp(-1.0, 1.0));
                }
                frac += step;
            }

            // drop the engine samples we consumed
            let consumed = (frac.floor() as usize).min(ql.len());
            if consumed > 0 {
                ql.drain(0..consumed);
                qr.drain(0..consumed);
                frac -= consumed as f64;
            }
        },
        move |err| eprintln!("forge audio: {err}"),
        None,
    )
}

fn start_audio(shared: Arc<Shared>) -> Option<cpal::Stream> {
    let host = cpal::default_host();
    let device = host.default_output_device()?;
    let supported = device.default_output_config().ok()?;
    let fmt = supported.sample_format();
    let config: cpal::StreamConfig = supported.into();
    let stream = match fmt {
        cpal::SampleFormat::F32 => build_stream::<f32>(&device, &config, shared),
        cpal::SampleFormat::I16 => build_stream::<i16>(&device, &config, shared),
        cpal::SampleFormat::U16 => build_stream::<u16>(&device, &config, shared),
        _ => return None,
    }
    .ok()?;
    stream.play().ok()?;
    Some(stream)
}

// ---------------------------------------------------------------------------
// palette (60:30:10 — dark ground, grey structure, one accent)
// ---------------------------------------------------------------------------
const GROUND: Color32 = Color32::from_rgb(14, 16, 19);
const PANEL: Color32 = Color32::from_rgb(20, 23, 27);
const LINE: Color32 = Color32::from_rgb(35, 40, 46);
const DIM: Color32 = Color32::from_rgb(86, 96, 105);
const MID: Color32 = Color32::from_rgb(124, 133, 141);
const INK: Color32 = Color32::from_rgb(185, 192, 198);
const ACCENT: Color32 = Color32::from_rgb(224, 118, 46);
const WARN: Color32 = Color32::from_rgb(214, 86, 76);
const GOOD: Color32 = Color32::from_rgb(96, 170, 110);
const TRACK: Color32 = Color32::from_rgb(30, 34, 39);
// premultiplied translucent amber — the bloom under the live trace
const GLOW: Color32 = Color32::from_rgba_premultiplied(40, 21, 8, 46);

// ---------------------------------------------------------------------------
// hand-drawn control toolkit — the whole bench is painted, no egui widgets.
// Each control hit-tests an explicit rect and draws itself.
// ---------------------------------------------------------------------------
fn lerp_col(a: Color32, b: Color32, t: f32) -> Color32 {
    let f = |x: u8, y: u8| (x as f32 + (y as f32 - x as f32) * t).round() as u8;
    Color32::from_rgb(f(a.r(), b.r()), f(a.g(), b.g()), f(a.b(), b.b()))
}

// horizontal fader; returns Some(new t in 0..1) when the user moved it.
fn fader(ui: &mut egui::Ui, p: &egui::Painter, rect: Rect, id: &str, t: f32) -> Option<f32> {
    // hit target slightly taller than the drawn rail — easier to grab, still
    // clear of the neighbouring row (rows sit 16px apart).
    let resp = ui.interact(rect.expand2(egui::vec2(0.0, 2.0)), egui::Id::new(id), Sense::click_and_drag());
    let mut out = None;
    if resp.dragged() || resp.clicked() {
        if let Some(pos) = resp.interact_pointer_pos() {
            out = Some(((pos.x - rect.left()) / rect.width().max(1.0)).clamp(0.0, 1.0));
        }
    }
    let tt = out.unwrap_or(t).clamp(0.0, 1.0);
    let mid = rect.center().y;
    p.rect_filled(Rect::from_min_max(Pos2::new(rect.left(), mid - 1.5), Pos2::new(rect.right(), mid + 1.5)), Rounding::same(1.5), TRACK);
    let fillx = rect.left() + tt * rect.width();
    p.rect_filled(Rect::from_min_max(Pos2::new(rect.left(), mid - 1.5), Pos2::new(fillx, mid + 1.5)), Rounding::same(1.5), lerp_col(ACCENT, GROUND, 0.25));
    let knob = Rect::from_center_size(Pos2::new(fillx, mid), egui::vec2(5.0, rect.height().min(13.0)));
    p.rect_filled(knob, Rounding::same(1.0), if resp.hovered() || resp.dragged() { ACCENT } else { INK });
    out
}

// filled button; returns true on click.
fn ibutton(ui: &mut egui::Ui, p: &egui::Painter, rect: Rect, id: &str, label: &str, fill: Color32, fg: Color32, size: f32) -> bool {
    let resp = ui.interact(rect, egui::Id::new(id), Sense::click());
    let bg = if resp.hovered() { lerp_col(fill, INK, 0.14) } else { fill };
    p.rect(rect, Rounding::same(3.0), bg, Stroke::new(1.0, LINE));
    p.text(rect.center(), Align2::CENTER_CENTER, label, FontId::monospace(size), fg);
    resp.clicked()
}

// selectable tab/chip; returns true on click.
fn tab(ui: &mut egui::Ui, p: &egui::Painter, rect: Rect, id: &str, label: &str, sel: bool, size: f32) -> bool {
    let resp = ui.interact(rect, egui::Id::new(id), Sense::click());
    let bg = if sel { ACCENT } else if resp.hovered() { LINE } else { PANEL };
    let fg = if sel { GROUND } else { MID };
    p.rect_filled(rect, Rounding::same(2.0), bg);
    if !sel {
        p.rect_stroke(rect, Rounding::same(2.0), Stroke::new(1.0, LINE));
    }
    p.text(rect.center(), Align2::CENTER_CENTER, label, FontId::monospace(size), fg);
    resp.clicked()
}

// action chip — the zero rules. Gray selection so "vandalism" reads distinct
// from the orange "bone" (Hz/radius) controls above it.
fn chip(ui: &mut egui::Ui, p: &egui::Painter, rect: Rect, id: &str, label: &str, sel: bool, size: f32) -> bool {
    let resp = ui.interact(rect, egui::Id::new(id), Sense::click());
    let bg = if sel { MID } else if resp.hovered() { LINE } else { PANEL };
    let fg = if sel { GROUND } else { DIM };
    p.rect_filled(rect, Rounding::same(2.0), bg);
    if !sel {
        p.rect_stroke(rect, Rounding::same(2.0), Stroke::new(1.0, LINE));
    }
    p.text(rect.center(), Align2::CENTER_CENTER, label, FontId::monospace(size), fg);
    resp.clicked()
}

// one-line text slot with its own caret + keyboard capture (no egui TextEdit).
fn textbox(ui: &mut egui::Ui, p: &egui::Painter, rect: Rect, slot: u8, text: &mut String, focus: &mut Option<u8>, hint: &str) {
    let resp = ui.interact(rect, egui::Id::new(("tb", slot)), Sense::click());
    if resp.clicked() {
        *focus = Some(slot);
    }
    let active = *focus == Some(slot);
    if active {
        let events = ui.input(|i| i.events.clone());
        for e in events {
            match e {
                egui::Event::Text(s) => text.push_str(&s),
                egui::Event::Key { key: egui::Key::Backspace, pressed: true, .. } => {
                    text.pop();
                }
                egui::Event::Key { key: egui::Key::Enter, pressed: true, .. }
                | egui::Event::Key { key: egui::Key::Escape, pressed: true, .. } => {
                    *focus = None;
                }
                _ => {}
            }
        }
    }
    p.rect(rect, Rounding::same(2.0), GROUND, Stroke::new(1.0, if active { ACCENT } else { LINE }));
    let empty = text.is_empty();
    let shown = if empty && !active { hint } else { text.as_str() };
    let col = if empty && !active { DIM } else { INK };
    let g = p.text(Pos2::new(rect.left() + 6.0, rect.center().y), Align2::LEFT_CENTER, shown, FontId::monospace(12.0), col);
    if active {
        let cx = (g.right() + 1.0).min(rect.right() - 4.0);
        p.line_segment([Pos2::new(cx, rect.top() + 4.0), Pos2::new(cx, rect.bottom() - 4.0)], Stroke::new(1.0, ACCENT));
    }
}

// ---------------------------------------------------------------------------
// cull: load a folder of `.body240`, scrub + hear each through the shared
// engine, send each to _keep/ or _kill/. Verdicts are file moves (reversible,
// nothing deleted); the survivors are whatever stays in the folder.
// ---------------------------------------------------------------------------
#[derive(Clone, Copy, PartialEq)]
enum Mode {
    Author,
    Cull,
}

#[derive(Clone)]
struct CullEntry {
    name: String,                      // file stem
    body_path: std::path::PathBuf,     // the .body240
    cart_path: Option<std::path::PathBuf>, // sibling .cartridge.json if present
}

struct Cull {
    dir: std::path::PathBuf,
    entries: Vec<CullEntry>,
    idx: usize,
    words: CornerWords, // the currently loaded body's raw words
    kept: usize,
    killed: usize,
}
impl Cull {
    // scan a folder for `.body240` (skipping the _keep/_kill sinks), newest first
    // by name so a fresh batch reads in order.
    fn scan(dir: &std::path::Path) -> Result<Vec<CullEntry>, String> {
        let mut out = Vec::new();
        let rd = std::fs::read_dir(dir).map_err(|e| format!("read {}: {e}", dir.display()))?;
        for ent in rd.flatten() {
            let p = ent.path();
            if p.extension().and_then(|s| s.to_str()) != Some("body240") {
                continue;
            }
            let stem = p.file_stem().and_then(|s| s.to_str()).unwrap_or("").to_string();
            if stem.is_empty() {
                continue;
            }
            let cart = p.with_extension("cartridge.json");
            let cart = if cart.exists() { Some(cart) } else { None };
            out.push(CullEntry { name: stem, body_path: p, cart_path: cart });
        }
        out.sort_by(|a, b| a.name.cmp(&b.name));
        Ok(out)
    }

    fn open(dir: std::path::PathBuf) -> Result<Self, String> {
        let entries = Self::scan(&dir)?;
        if entries.is_empty() {
            return Err(format!("no .body240 in {}", dir.display()));
        }
        let words = load_words(&entries[0].body_path)?;
        Ok(Cull { dir, entries, idx: 0, words, kept: 0, killed: 0 })
    }

    fn current(&self) -> Option<&CullEntry> {
        self.entries.get(self.idx)
    }

    // load entry at idx into `words`; clamp idx into range.
    fn select(&mut self, idx: usize) -> Result<(), String> {
        if self.entries.is_empty() {
            return Err("nothing left to cull".into());
        }
        self.idx = idx.min(self.entries.len() - 1);
        self.words = load_words(&self.entries[self.idx].body_path)?;
        Ok(())
    }

    // move the current body (+ its cartridge) into a sink subfolder, drop it from
    // the list, and load whatever now sits at the same index (the next one).
    fn verdict(&mut self, sink: &str) -> Result<String, String> {
        let entry = self.current().cloned().ok_or("nothing to judge")?;
        let dest = self.dir.join(sink);
        std::fs::create_dir_all(&dest).map_err(|e| format!("mkdir {}: {e}", dest.display()))?;
        move_into(&entry.body_path, &dest)?;
        if let Some(c) = &entry.cart_path {
            move_into(c, &dest)?;
        }
        self.entries.remove(self.idx);
        if sink == "_keep" {
            self.kept += 1;
        } else {
            self.killed += 1;
        }
        if self.entries.is_empty() {
            return Ok(format!("{} -> {sink}  ·  folder clear", entry.name));
        }
        let idx = self.idx.min(self.entries.len() - 1);
        self.select(idx)?;
        Ok(format!("{} -> {sink}", entry.name))
    }
}

fn load_words(path: &std::path::Path) -> Result<CornerWords, String> {
    let bytes = std::fs::read(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    words_from_body_bytes(&bytes)
        .ok_or_else(|| format!("{} is {} bytes, expected 240", path.display(), bytes.len()))
}

fn move_into(file: &std::path::Path, dir: &std::path::Path) -> Result<(), String> {
    let name = file.file_name().ok_or("bad filename")?;
    let dest = dir.join(name);
    std::fs::rename(file, &dest).map_err(|e| format!("move {} -> {}: {e}", file.display(), dest.display()))
}

// ---------------------------------------------------------------------------
// the bench
// ---------------------------------------------------------------------------
struct Forge {
    mode: Mode,
    body: Body,
    corner: usize, // which saved version you edit
    cull: Option<Cull>,
    cull_dir: String,       // folder to load for culling
    focus: Option<u8>,      // which hand-drawn text slot has the keyboard (0 name, 1 folder)
    cull_scroll: f32,       // list scroll offset (px) for the hand-drawn body list
    morph: f32,
    q: f32,
    snap: bool, // rail-snap frequencies to the grounded table
    src: usize,
    tame: f32, // PUNCH: agc compression amount
    grit: f32, // PUNCH: desk slam
    wide: f32, // PUNCH: spatial width
    status: String,
    shared: Arc<Shared>,
    last_body: Vec<u8>,
    _audio: Option<cpal::Stream>, // kept alive; dropping it stops the stream
}
impl Forge {
    fn new() -> Self {
        let shared = Arc::new(Shared::new());
        let body = Body::starter();
        let init = body.pack_240();
        shared.publish_body(&init);
        let audio = start_audio(shared.clone());
        Forge {
            mode: Mode::Author,
            body,
            corner: 0,
            cull: None,
            cull_dir: "recipes/auto".into(),
            focus: None,
            cull_scroll: 0.0,
            morph: 0.33,
            q: 0.0,
            snap: true,
            src: 0,
            tame: 0.5,
            grit: 0.3,
            wide: 0.4,
            status: if audio.is_some() {
                String::new()
            } else {
                "no audio device".into()
            },
            shared,
            last_body: init,
            _audio: audio,
        }
    }

    // -- header band: wordmark, the two modes, and the one thing you type --
    fn draw_header(&mut self, ui: &mut egui::Ui, p: &egui::Painter, b: Rect) {
        let cy = b.center().y;
        p.text(Pos2::new(b.left() + 14.0, cy), Align2::LEFT_CENTER, "df2", FontId::proportional(17.0), ACCENT);

        let mut x = b.left() + 58.0;
        for (m, lab) in [(Mode::Author, "edit"), (Mode::Cull, "cull")] {
            let r = Rect::from_min_size(Pos2::new(x, cy - 11.0), egui::vec2(48.0, 22.0));
            if tab(ui, p, r, &format!("mode{lab}"), lab, self.mode == m, 11.0) {
                self.mode = m;
                self.focus = None;
            }
            x += 52.0;
        }

        match self.mode {
            Mode::Author => {
                x += 12.0;
                for (i, lab) in ["C0", "C1", "C2", "C3"].iter().enumerate() {
                    let r = Rect::from_min_size(Pos2::new(x, cy - 10.0), egui::vec2(34.0, 20.0));
                    if tab(ui, p, r, &format!("corner{i}"), lab, self.corner == i, 10.0) {
                        self.corner = i;
                    }
                    x += 38.0;
                }
                let snr = Rect::from_min_size(Pos2::new(x + 6.0, cy - 10.0), egui::vec2(52.0, 20.0));
                if tab(ui, p, snr, "snaptoggle", "snap", self.snap, 10.0) {
                    self.snap = !self.snap;
                }
                let save = Rect::from_min_size(Pos2::new(b.right() - 56.0, cy - 11.0), egui::vec2(46.0, 22.0));
                if ibutton(ui, p, save, "save", "save", LINE, INK, 11.0) {
                    let bytes = self.body.pack_240();
                    let path = format!("{}.body240", sanitize(&self.body.name));
                    self.status = match std::fs::write(&path, &bytes) {
                        Ok(_) => {
                            let abs = std::fs::canonicalize(&path)
                                .map(|p| p.display().to_string().trim_start_matches(r"\\?\").to_string())
                                .unwrap_or_else(|_| path.clone());
                            format!("saved {abs}")
                        }
                        Err(e) => format!("save failed: {e}"),
                    };
                }
                let nb = Rect::from_min_size(Pos2::new(b.right() - 200.0, cy - 11.0), egui::vec2(132.0, 22.0));
                textbox(ui, p, nb, 0, &mut self.body.name, &mut self.focus, "name");
            }
            Mode::Cull => {
                let load = Rect::from_min_size(Pos2::new(b.right() - 56.0, cy - 11.0), egui::vec2(46.0, 22.0));
                if ibutton(ui, p, load, "load", "load", LINE, INK, 11.0) {
                    match Cull::open(std::path::PathBuf::from(self.cull_dir.trim())) {
                        Ok(c) => {
                            self.status = format!("{} loaded", c.entries.len());
                            self.cull = Some(c);
                            self.cull_scroll = 0.0;
                        }
                        Err(e) => self.status = format!("{e}"),
                    }
                }
                let fb = Rect::from_min_size(Pos2::new(b.right() - 260.0, cy - 11.0), egui::vec2(192.0, 22.0));
                textbox(ui, p, fb, 1, &mut self.cull_dir, &mut self.focus, "folder");
            }
        }
    }

    // -- the hero: the shape it makes, drawn as a glowing trace on a graticule --
    fn draw_plot(&mut self, _ui: &mut egui::Ui, p: &egui::Painter, area: Rect) {
        let plot = Rect::from_min_max(
            Pos2::new(area.left() + 34.0, area.top() + 22.0),
            Pos2::new(area.right() - 14.0, area.bottom() - 24.0),
        );

        let fx = |f: f64| plot.left() + ((f.max(F_LO).log10() - F_LO.log10()) / (f_hi().log10() - F_LO.log10())) as f32 * plot.width();
        let (db_lo, db_hi) = (-30.0_f64, 36.0_f64);
        let fy = |db: f64| plot.bottom() - ((db.clamp(db_lo, db_hi) - db_lo) / (db_hi - db_lo)) as f32 * plot.height();

        // graticule — real units, dim, so the schematic reads in Hz and dB
        for (f, lab) in [(100.0, "100"), (1000.0, "1k"), (10000.0, "10k")] {
            let x = fx(f);
            p.line_segment([Pos2::new(x, plot.top()), Pos2::new(x, plot.bottom())], Stroke::new(1.0, Color32::from_rgb(26, 30, 35)));
            p.text(Pos2::new(x, plot.bottom() + 3.0), Align2::CENTER_TOP, lab, FontId::monospace(9.0), DIM);
        }
        for db in [24.0, 12.0, 0.0, -12.0, -24.0] {
            let y = fy(db);
            let s = if db == 0.0 { Stroke::new(1.0, Color32::from_rgb(34, 39, 45)) } else { Stroke::new(1.0, Color32::from_rgb(22, 26, 30)) };
            p.line_segment([Pos2::new(plot.left(), y), Pos2::new(plot.right(), y)], s);
            let lab = if db > 0.0 { format!("+{db:.0}") } else { format!("{db:.0}") };
            p.text(Pos2::new(plot.left() - 5.0, y), Align2::RIGHT_CENTER, &lab, FontId::monospace(9.0), DIM);
        }
        p.rect_stroke(plot, Rounding::ZERO, Stroke::new(1.0, LINE));

        // rail grid — the grounded snap targets, faint verticals so you see
        // where a pole/null will land when you drag it.
        if self.snap {
            for &r in RAILS.iter() {
                if r >= F_LO && r <= f_hi() {
                    let x = fx(r);
                    p.line_segment([Pos2::new(x, plot.top()), Pos2::new(x, plot.bottom())],
                        Stroke::new(1.0, Color32::from_rgba_premultiplied(46, 34, 14, 40)));
                }
            }
        }

        // the body's name — the one label worth showing, sat on the hero
        let name = match self.mode {
            Mode::Cull => self.cull.as_ref().and_then(|c| c.current()).map(|e| e.name.clone()),
            Mode::Author => (!self.body.name.is_empty()).then(|| self.body.name.clone()),
        };
        if let Some(n) = &name {
            p.text(Pos2::new(plot.left() + 4.0, area.top() + 4.0), Align2::LEFT_TOP, n, FontId::monospace(12.0), MID);
        }

        let active = match self.mode {
            Mode::Author => Some(self.body.words_all()),
            Mode::Cull => self.cull.as_ref().map(|c| c.words),
        };
        let Some(words) = active else {
            return;
        };

        let n = 240usize;
        let curve = |m: f32, qq: f32, col: Color32, w: f32| {
            let stages = live_words(&words, m, qq);
            let mut prev: Option<Pos2> = None;
            for i in 0..n {
                let t = i as f64 / (n as f64 - 1.0);
                let f = 10f64.powf(F_LO.log10() + t * (f_hi().log10() - F_LO.log10()));
                let pt = Pos2::new(fx(f), fy(stages_mag(&stages, f)));
                if let Some(pv) = prev {
                    p.line_segment([pv, pt], Stroke::new(w, col));
                }
                prev = Some(pt);
            }
        };
        // the four corners, faint ghosts
        for &(m, qq) in &[(0.0f32, 0.0f32), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)] {
            curve(m, qq, Color32::from_rgb(42, 48, 54), 1.0);
        }

        // pole pillars — the bones standing under the live blend. A vertical at
        // each of the six pole frequencies, floor up to the curve: poles anchor,
        // zeros (the trace dips) rip the curve apart between them.
        let stages = live_words(&words, self.morph, self.q);
        for s in &stages {
            let (a1, a2) = (s[3], s[4]);
            let r = a2.max(0.0).sqrt();
            if r <= 1e-6 {
                continue;
            }
            let cth = (-a1 / (2.0 * r)).clamp(-1.0, 1.0);
            let f = cth.acos() * SR / TAU;
            if f < F_LO || f > f_hi() {
                continue;
            }
            let x = fx(f);
            let ytop = fy(stages_mag(&stages, f));
            p.line_segment([Pos2::new(x, plot.bottom()), Pos2::new(x, ytop)], Stroke::new(1.0, Color32::from_rgba_premultiplied(56, 29, 11, 64)));
        }

        // the live blend — amber bloom under a bright amber core
        curve(self.morph, self.q, GLOW, 5.0);
        curve(self.morph, self.q, ACCENT, 2.0);

        // stability tell — a colored dot, no words unless it's bad
        let wr = stages_worst_radius(&stages);
        let (col, warn) = if wr >= 1.0 { (WARN, Some("blows")) } else if wr >= 0.999 { (WARN, Some("edge")) } else { (GOOD, None) };
        let dot = Pos2::new(plot.right() - 10.0, area.top() + 10.0);
        p.circle_filled(dot, 4.0, col);
        if let Some(w) = warn {
            p.text(Pos2::new(dot.x - 8.0, dot.y), Align2::RIGHT_CENTER, w, FontId::monospace(10.0), col);
        }
    }

    // -- author rack: the six pole/zero rows. Hz + radius + level (bone) split
    //    from the zero rule (action). No windows, no types — nothing decorative. --
    fn draw_shape(&mut self, ui: &mut egui::Ui, p: &egui::Painter, rack: Rect) {
        let inner = rack.shrink(10.0);
        let preset = Rect::from_min_size(inner.min, egui::vec2(inner.width(), 30.0));
        let presets = [
            (PresetKind::Vowel, "vowel"),
            (PresetKind::Comb, "comb"),
            (PresetKind::Canyon, "canyon"),
            (PresetKind::Cliff, "cliff"),
        ];
        let bw = (preset.width() - 18.0) / presets.len() as f32;
        for (i, (kind, label)) in presets.iter().enumerate() {
            let r = Rect::from_min_size(
                Pos2::new(preset.left() + i as f32 * (bw + 6.0), preset.top()),
                egui::vec2(bw, 22.0),
            );
            if tab(ui, p, r, &format!("preset{i}"), label, false, 10.0) {
                self.body = Body::preset(*kind);
                self.corner = 0;
                self.status = format!("stamped {label}");
            }
        }

        let lanes = Rect::from_min_max(Pos2::new(inner.left(), inner.top() + 34.0), inner.max);
        let lane_h = (lanes.height() / 6.0).min(86.0);
        for i in 0..6 {
            let card = Rect::from_min_size(Pos2::new(lanes.left(), lanes.top() + i as f32 * lane_h), egui::vec2(lanes.width(), lane_h - 5.0));
            self.draw_lane(ui, p, card, i);
        }
    }

    fn draw_lane(&mut self, ui: &mut egui::Ui, p: &egui::Painter, card: Rect, i: usize) {
        let on = self.body.corners[self.corner][i].on;
        p.rect(card, Rounding::same(2.0), GROUND, Stroke::new(1.0, if on { LINE } else { Color32::from_rgb(26, 30, 34) }));
        let c = card.shrink2(egui::vec2(8.0, 6.0));

        // toggle — add the pole, or park it (the body builds up from flat)
        let tg = Rect::from_min_size(Pos2::new(c.left(), c.top() + 1.0), egui::vec2(11.0, 11.0));
        if ui.interact(tg, egui::Id::new(("on", self.corner, i)), Sense::click()).clicked() {
            self.body.corners[self.corner][i].on = !on;
        }

        let snap = self.snap;
        let snap_hz = |hz: f64| if snap { snap_rail(hz) } else { hz };
        let part = &mut self.body.corners[self.corner][i];
        // identity = the frequency (amber when active, dim when parked)
        p.text(Pos2::new(c.left() + 18.0, c.top()), Align2::LEFT_TOP, &format!("{} Hz", part.spot.round()), FontId::monospace(13.0), if part.on { ACCENT } else { DIM });

        let yrow = |k: f32| c.top() + 18.0 + k * 16.0;
        let lo = F_LO.log10();
        let hi = f_hi().log10();
        // FOUNDATION null live: the zero gets its own frequency control,
        // sat on the identity row beside the pole's Hz.
        if part.cut == Cut::Null {
            p.text(Pos2::new(c.right() - 152.0, c.top() + 7.0), Align2::LEFT_CENTER, "z", FontId::monospace(8.0), DIM);
            let zr = Rect::from_min_size(Pos2::new(c.right() - 142.0, c.top() + 1.0), egui::vec2(96.0, 12.0));
            let zt = ((part.zspot.log10() - lo) / (hi - lo)) as f32;
            if let Some(nt) = fader(ui, p, zr, &format!("zsp{}{}", self.corner, i), zt) {
                part.zspot = snap_hz(10f64.powf(lo + nt as f64 * (hi - lo)));
            }
            p.text(Pos2::new(c.right(), c.top() + 7.0), Align2::RIGHT_CENTER, &format!("{}", part.zspot.round()), FontId::monospace(9.0), MID);
        }
        // bone: Hz wide, then radius | level
        p.text(Pos2::new(c.left(), yrow(0.0) + 6.0), Align2::LEFT_CENTER, "hz", FontId::monospace(8.0), DIM);
        let hzr = Rect::from_min_size(Pos2::new(c.left() + 16.0, yrow(0.0)), egui::vec2(c.width() - 16.0, 12.0));
        let t = ((part.spot.log10() - lo) / (hi - lo)) as f32;
        if let Some(nt) = fader(ui, p, hzr, &format!("hz{}{}", self.corner, i), t) {
            part.spot = snap_hz(10f64.powf(lo + nt as f64 * (hi - lo)));
        }
        let half = (c.width() - 16.0 - 8.0) / 2.0;
        p.text(Pos2::new(c.left(), yrow(1.0) + 6.0), Align2::LEFT_CENTER, "r", FontId::monospace(8.0), DIM);
        let radr = Rect::from_min_size(Pos2::new(c.left() + 16.0, yrow(1.0)), egui::vec2(half, 12.0));
        let st = ((part.sharp - 0.5) / (0.9999 - 0.5)) as f32;
        if let Some(nt) = fader(ui, p, radr, &format!("rad{}{}", self.corner, i), st) {
            part.sharp = 0.5 + nt as f64 * (0.9999 - 0.5);
        }
        p.text(Pos2::new(c.left() + 16.0 + half + 8.0, yrow(1.0) + 6.0), Align2::LEFT_CENTER, "g", FontId::monospace(8.0), DIM);
        let lvlr = Rect::from_min_size(Pos2::new(c.left() + 16.0 + half + 20.0, yrow(1.0)), egui::vec2(half - 12.0, 12.0));
        // the LEDGER fader: authored section level, ±24 dB about the anchor —
        // the ROM's drama is big opposing per-stage levels (median max +57 dB),
        // sanity policed by the audit, never by construction.
        let lt = ((20.0 * part.loud.max(1e-6).log10() + 24.0) / 48.0) as f32;
        if let Some(nt) = fader(ui, p, lvlr, &format!("lvl{}{}", self.corner, i), lt) {
            part.loud = 10f64.powf((nt as f64 * 48.0 - 24.0) / 20.0);
        }

        // divider — bone above, zero rule below
        let dy = yrow(2.0) + 2.0;
        p.hline(egui::Rangef::new(c.left(), c.right()), dy, Stroke::new(1.0, Color32::from_rgb(28, 32, 37)));

        // the zero rule (gray chips)
        let cw = c.width() / Cut::ALL.len() as f32;
        for (j, ct) in Cut::ALL.iter().enumerate() {
            let cr = Rect::from_min_size(Pos2::new(c.left() + j as f32 * cw, dy + 5.0), egui::vec2(cw - 2.0, 14.0));
            if chip(ui, p, cr, &format!("cut{}{}{}", self.corner, i, j), ct.chip(), part.cut == *ct, 9.0) {
                part.cut = *ct;
            }
        }

        // parked rows read as veiled; the toggle glyph stays crisp on top
        let active = part.on;
        if !active {
            p.rect_filled(card, Rounding::same(2.0), Color32::from_rgba_premultiplied(8, 9, 11, 150));
        }
        if active {
            p.rect_filled(tg, Rounding::same(2.0), ACCENT);
        } else {
            p.rect_stroke(tg, Rounding::same(2.0), Stroke::new(1.0, DIM));
            let cc = tg.center();
            p.line_segment([Pos2::new(cc.x - 3.0, cc.y), Pos2::new(cc.x + 3.0, cc.y)], Stroke::new(1.0, DIM));
            p.line_segment([Pos2::new(cc.x, cc.y - 3.0), Pos2::new(cc.x, cc.y + 3.0)], Stroke::new(1.0, DIM));
        }
    }

    // -- cull rack: keep/kill the held body, walk the folder, hear each --
    fn draw_cull(&mut self, ui: &mut egui::Ui, p: &egui::Painter, rack: Rect) {
        let inner = rack.shrink(10.0);
        let Some(cull) = self.cull.as_mut() else {
            p.text(inner.center(), Align2::CENTER_CENTER, "type a folder, hit load", FontId::monospace(11.0), DIM);
            return;
        };
        let last = cull.entries.len().saturating_sub(1);
        let mut action: Option<&'static str> = None;
        let mut goto: Option<usize> = None;

        // hotkeys — only when no text slot owns the keyboard
        if self.focus.is_none() {
            ui.input(|inp| {
                if inp.key_pressed(egui::Key::K) { action = Some("_keep"); }
                if inp.key_pressed(egui::Key::X) { action = Some("_kill"); }
                if inp.key_pressed(egui::Key::ArrowDown) || inp.key_pressed(egui::Key::ArrowRight) { goto = Some((cull.idx + 1).min(last)); }
                if inp.key_pressed(egui::Key::ArrowUp) || inp.key_pressed(egui::Key::ArrowLeft) { goto = Some(cull.idx.saturating_sub(1)); }
            });
        }

        // keep / kill — the whole point, big
        let bw = (inner.width() - 8.0) / 2.0;
        let keep = Rect::from_min_size(inner.min, egui::vec2(bw, 40.0));
        let kill = Rect::from_min_size(Pos2::new(inner.left() + bw + 8.0, inner.top()), egui::vec2(bw, 40.0));
        if ibutton(ui, p, keep, "keep", "keep", GOOD, GROUND, 15.0) { action = Some("_keep"); }
        if ibutton(ui, p, kill, "kill", "kill", WARN, GROUND, 15.0) { action = Some("_kill"); }
        // hotkey hints, quiet, in the button corners
        p.text(Pos2::new(keep.right() - 6.0, keep.bottom() - 4.0), Align2::RIGHT_BOTTOM, "k", FontId::monospace(9.0), lerp_col(GOOD, GROUND, 0.45));
        p.text(Pos2::new(kill.right() - 6.0, kill.bottom() - 4.0), Align2::RIGHT_BOTTOM, "x", FontId::monospace(9.0), lerp_col(WARN, GROUND, 0.45));

        // prev / next + count
        let ny = inner.top() + 48.0;
        let pv = Rect::from_min_size(Pos2::new(inner.left(), ny), egui::vec2(40.0, 22.0));
        let nx = Rect::from_min_size(Pos2::new(inner.left() + 44.0, ny), egui::vec2(40.0, 22.0));
        if ibutton(ui, p, pv, "prev", "◀", LINE, INK, 12.0) { goto = Some(cull.idx.saturating_sub(1)); }
        if ibutton(ui, p, nx, "next", "▶", LINE, INK, 12.0) { goto = Some((cull.idx + 1).min(last)); }
        let tally = format!("{}/{}  ·  k{} x{}", (cull.idx + 1).min(cull.entries.len()), cull.entries.len(), cull.kept, cull.killed);
        p.text(Pos2::new(inner.right(), ny + 11.0), Align2::RIGHT_CENTER, &tally, FontId::monospace(11.0), MID);

        // the list — hand-drawn rows, wheel-scrolled, clipped
        let list = Rect::from_min_max(Pos2::new(inner.left(), ny + 30.0), inner.max);
        p.rect_stroke(list, Rounding::ZERO, Stroke::new(1.0, LINE));
        let row_h = 18.0;
        let view = list.shrink(2.0);
        let total = cull.entries.len() as f32 * row_h;
        let max_scroll = (total - view.height()).max(0.0);
        // wheel
        if ui.rect_contains_pointer(list) {
            let dy = ui.input(|i| i.raw_scroll_delta.y);
            self.cull_scroll = (self.cull_scroll - dy).clamp(0.0, max_scroll);
        }
        // keep selected row in view
        let sel_top = cull.idx as f32 * row_h;
        if sel_top < self.cull_scroll { self.cull_scroll = sel_top; }
        if sel_top + row_h > self.cull_scroll + view.height() { self.cull_scroll = sel_top + row_h - view.height(); }
        self.cull_scroll = self.cull_scroll.clamp(0.0, max_scroll);

        let clip = p.with_clip_rect(view);
        for i in 0..cull.entries.len() {
            let y = view.top() + i as f32 * row_h - self.cull_scroll;
            if y + row_h < view.top() || y > view.bottom() { continue; }
            let rr = Rect::from_min_size(Pos2::new(view.left(), y), egui::vec2(view.width(), row_h));
            let sel = i == cull.idx;
            let resp = ui.interact(rr, egui::Id::new(("row", i)), Sense::click());
            if sel { clip.rect_filled(rr, Rounding::ZERO, Color32::from_rgb(30, 35, 40)); }
            let col = if sel { ACCENT } else if resp.hovered() { INK } else { MID };
            clip.text(Pos2::new(rr.left() + 6.0, rr.center().y), Align2::LEFT_CENTER, &cull.entries[i].name, FontId::monospace(11.0), col);
            if resp.clicked() { goto = Some(i); }
        }

        // apply mutations after the read-only borrows
        if let Some(sink) = action {
            match cull.verdict(sink) {
                Ok(msg) => self.status = msg,
                Err(e) => self.status = format!("{e}"),
            }
        } else if let Some(idx) = goto {
            if idx != cull.idx {
                if let Err(e) = cull.select(idx) {
                    self.status = format!("{e}");
                }
            }
        }
    }

    // -- footer = the lung: transport + source, then the SURVIVAL block where
    //    PUNCH (the AGC drive that keeps aggressive zeros from collapsing) is the
    //    biggest control, with grit/wide and the blend beside it. Lives here (not
    //    the rack) so it stays under the hand during cull too. --
    fn draw_footer(&mut self, ui: &mut egui::Ui, p: &egui::Painter, b: Rect) {
        let inner = b.shrink2(egui::vec2(14.0, 9.0));
        let top = inner.top();

        // transport
        let playing = self.shared.playing.load(Ordering::Relaxed);
        let pr = Rect::from_min_size(inner.min, egui::vec2(52.0, inner.height()));
        if ibutton(ui, p, pr, "play", if playing { "■" } else { "▶" }, if playing { ACCENT } else { LINE }, if playing { GROUND } else { INK }, 18.0) {
            self.shared.playing.store(!playing, Ordering::Relaxed);
        }

        // what goes in
        let mut x = inner.left() + 62.0;
        p.text(Pos2::new(x, top), Align2::LEFT_TOP, "in", FontId::monospace(9.0), DIM);
        for (i, s) in ["saw", "noise", "808", "voice"].iter().enumerate() {
            let r = Rect::from_min_size(Pos2::new(x, top + 13.0), egui::vec2(46.0, 20.0));
            if tab(ui, p, r, &format!("src{i}"), s, self.src == i, 10.0) {
                self.src = i;
            }
            x += 50.0;
        }
        p.vline(inner.left() + 320.0, b.y_range(), Stroke::new(1.0, LINE));

        // --- SURVIVAL: punch made the dominant control ---
        let sx = inner.left() + 334.0;
        p.text(Pos2::new(sx, top), Align2::LEFT_TOP, "PUNCH", FontId::monospace(11.0), ACCENT);
        p.text(Pos2::new(sx + 168.0, top), Align2::RIGHT_TOP, &format!("{:.0}", self.tame * 100.0), FontId::monospace(9.0), DIM);
        let bigr = Rect::from_min_size(Pos2::new(sx, top + 15.0), egui::vec2(168.0, 18.0));
        // thicker rail so the AGC drive reads as the heavy control
        p.rect_filled(Rect::from_min_max(Pos2::new(bigr.left(), bigr.center().y - 3.0), Pos2::new(bigr.right(), bigr.center().y + 3.0)), Rounding::same(2.0), TRACK);
        if let Some(v) = fader(ui, p, bigr, "tame", self.tame) {
            self.tame = v;
        }
        let sm = (168.0 - 8.0) / 2.0;
        let g = Rect::from_min_size(Pos2::new(sx, top + 38.0), egui::vec2(sm, 10.0));
        let w = Rect::from_min_size(Pos2::new(sx + sm + 8.0, top + 38.0), egui::vec2(sm, 10.0));
        if let Some(v) = fader(ui, p, g, "grit", self.grit) { self.grit = v; }
        if let Some(v) = fader(ui, p, w, "wide", self.wide) { self.wide = v; }
        p.text(Pos2::new(g.left(), top + 52.0), Align2::LEFT_TOP, "grit", FontId::monospace(8.0), DIM);
        p.text(Pos2::new(w.left(), top + 52.0), Align2::LEFT_TOP, "wide", FontId::monospace(8.0), DIM);

        // --- BLEND: morph + q ---
        let bx = sx + 196.0;
        p.vline(bx - 14.0, b.y_range(), Stroke::new(1.0, LINE));
        p.text(Pos2::new(bx, top), Align2::LEFT_TOP, "blend", FontId::monospace(10.0), DIM);
        let m = Rect::from_min_size(Pos2::new(bx + 16.0, top + 16.0), egui::vec2(168.0, 12.0));
        let qf = Rect::from_min_size(Pos2::new(bx + 16.0, top + 33.0), egui::vec2(168.0, 12.0));
        p.text(Pos2::new(bx, m.center().y), Align2::LEFT_CENTER, "m", FontId::monospace(8.0), DIM);
        p.text(Pos2::new(bx, qf.center().y), Align2::LEFT_CENTER, "q", FontId::monospace(8.0), DIM);
        if let Some(v) = fader(ui, p, m, "morph", self.morph) { self.morph = v; }
        if let Some(v) = fader(ui, p, qf, "q", self.q) { self.q = v; }
        p.text(Pos2::new(m.right() + 8.0, m.center().y), Align2::LEFT_CENTER, &format!("{:.0}", self.morph * 100.0), FontId::monospace(9.0), MID);
        p.text(Pos2::new(qf.right() + 8.0, qf.center().y), Align2::LEFT_CENTER, &format!("{:.0}", self.q * 100.0), FontId::monospace(9.0), MID);

        if !self.status.is_empty() {
            p.text(Pos2::new(inner.right(), inner.bottom()), Align2::RIGHT_BOTTOM, &self.status, FontId::monospace(10.0), MID);
        }
    }
}

const F_LO: f64 = 20.0;
fn f_hi() -> f64 {
    SR * 0.5
}

// grounded frequency rails from the ROM corpus (docs/study/frequency_rails.csv,
// top by endpoint presence) — the snap targets that make hands-on placement
// land on real table frequencies so the pole/null crossings hit clean.
const RAILS: [f64; 26] = [
    134.0, 200.0, 320.0, 365.0, 410.0, 430.0, 440.0, 450.0, 545.0, 680.0,
    780.0, 785.0, 790.0, 1090.0, 2180.0, 2220.0, 2840.0, 3790.0, 4130.0, 4440.0,
    5450.0, 8250.0, 8875.0, 9650.0, 16500.0, 17950.0,
];

fn snap_rail(hz: f64) -> f64 {
    RAILS
        .iter()
        .copied()
        .min_by(|a, b| (a - hz).abs().partial_cmp(&(b - hz).abs()).unwrap())
        .unwrap_or(hz)
}

impl eframe::App for Forge {
    fn update(&mut self, ctx: &egui::Context, _f: &mut eframe::Frame) {
        let mut v = egui::Visuals::dark();
        v.override_text_color = Some(INK);
        v.panel_fill = GROUND;
        v.window_fill = GROUND;
        ctx.set_visuals(v);

        // one hand-drawn canvas — no egui widgets, no chrome
        egui::CentralPanel::default().frame(egui::Frame::none().fill(GROUND)).show(ctx, |ui| {
            let p = ui.painter().clone();
            let full = ui.max_rect();

            let header = Rect::from_min_max(full.min, Pos2::new(full.right(), full.top() + 38.0));
            let footer = Rect::from_min_max(Pos2::new(full.left(), full.bottom() - 96.0), full.max);
            let band = Rect::from_min_max(Pos2::new(full.left(), header.bottom()), Pos2::new(full.right(), footer.top()));
            let rack_w = 332.0;
            let rack = Rect::from_min_max(Pos2::new(band.right() - rack_w, band.top()), band.max);
            let plot_area = Rect::from_min_max(band.min, Pos2::new(rack.left(), band.bottom()));

            // bands + hairlines
            p.rect_filled(header, Rounding::ZERO, PANEL);
            p.rect_filled(footer, Rounding::ZERO, PANEL);
            p.rect_filled(rack, Rounding::ZERO, PANEL);
            p.hline(full.x_range(), header.bottom(), Stroke::new(1.0, LINE));
            p.hline(full.x_range(), footer.top(), Stroke::new(1.0, LINE));
            p.vline(rack.left(), band.y_range(), Stroke::new(1.0, LINE));

            self.draw_header(ui, &p, header);
            self.draw_plot(ui, &p, plot_area);
            match self.mode {
                Mode::Author => self.draw_shape(ui, &p, rack),
                Mode::Cull => self.draw_cull(ui, &p, rack),
            }
            self.draw_footer(ui, &p, footer);

            // click outside any text slot drops the keyboard
            if self.focus.is_some() {
                let pressed = ui.input(|i| i.pointer.any_pressed());
                if pressed {
                    let hot = header; // both text slots live in the header band
                    let pos = ui.input(|i| i.pointer.interact_pos());
                    if pos.map_or(true, |pp| !hot.contains(pp)) {
                        self.focus = None;
                    }
                }
            }

            ctx.request_repaint(); // keep the trace live while dragging
        });

        // ---- push live state to the audio engine ----
        self.shared.set_f(&self.shared.morph, self.morph);
        self.shared.set_f(&self.shared.q, self.q);
        self.shared.set_f(&self.shared.tame, self.tame);
        self.shared.set_f(&self.shared.grit, self.grit);
        self.shared.set_f(&self.shared.wide, self.wide);
        self.shared.src.store(self.src, Ordering::Relaxed);
        let packed = match self.mode {
            Mode::Author => self.body.pack_240(),
            Mode::Cull => self.cull.as_ref().map(|c| words_to_body_bytes(&c.words)).unwrap_or_default(),
        };
        if packed.len() == 240 && packed != self.last_body {
            self.shared.publish_body(&packed);
            self.last_body = packed;
        }
    }
}

fn sanitize(s: &str) -> String {
    let out: String = s.chars().map(|c| if c.is_alphanumeric() { c } else { '_' }).collect();
    let t = out.trim_matches('_').to_lowercase();
    if t.is_empty() { "untitled".into() } else { t }
}

// ---------------------------------------------------------------------------
// bake: recipe JSON -> Body -> baked cartridge (recipe + keyframes, one file)
//   forge bake <recipe.cartridge.json> [out.cartridge.json]
// One owner of recipe->bytes. Writes <name>.body240 and folds the baked
// keyframes back into the cartridge (the runtime authority), leaving the
// editable `recipe` block intact. No second derivation path.
// ---------------------------------------------------------------------------
#[derive(Deserialize)]
struct RecipeFile {
    #[serde(default)]
    name: String,
    recipe: Recipe,
}
#[derive(Deserialize)]
struct Recipe {
    axes: Axes,
    lanes: Vec<Lane>,
    #[serde(default)]
    constraints: Constraints,
    #[serde(default)]
    overrides: Vec<OverrideSpec>,
}
#[derive(Deserialize)]
struct Axes {
    morph: MorphAxis,
    secondary: SecondaryAxis,
}
#[derive(Deserialize)]
struct MorphAxis {
    slide_semitones: f64,
}
#[derive(Deserialize)]
struct SecondaryAxis {
    mode: String,
    amount: f64,
}
#[derive(Deserialize)]
struct Lane {
    anatomy: Anatomy,
    articulation: Articulation,
    survival: Survival,
}
#[derive(Deserialize)]
struct Anatomy {
    pole_hz: f64,
    sharp: f64,
    /// Optional C1/C3 target pole. When set, the horizontal axis moves this lane
    /// from pole_hz -> target_hz instead of applying the global slide.
    #[serde(default)]
    target_hz: Option<f64>,
}
#[derive(Deserialize)]
struct Articulation {
    cut: String,
    #[serde(default)]
    zero: Option<ZeroSpec>,
    #[serde(default)]
    morph_move: f64,
}
#[derive(Deserialize, Clone, Copy)]
struct ZeroSpec {
    ratio: f64,
    depth: f64,
    #[serde(default)]
    track: TrackKind,
}
#[derive(Deserialize, Clone, Copy, Default, PartialEq)]
#[serde(rename_all = "lowercase")]
enum TrackKind {
    #[default]
    Follow,
    Absolute,
}
#[derive(Deserialize)]
struct Survival {
    gain: f64,
}
#[derive(Deserialize, Default)]
struct Constraints {
    #[serde(default)]
    on_unstable: OnUnstable,
}
#[derive(Deserialize, Default, Clone, Copy, PartialEq)]
#[serde(rename_all = "lowercase")]
enum OnUnstable {
    #[default]
    Reject,
    Clamp,
}
#[derive(Deserialize)]
struct OverrideSpec {
    corner: String,
    lane: usize,
    set: SetSpec,
}
#[derive(Deserialize)]
struct SetSpec {
    #[serde(default)]
    pole_hz: Option<f64>,
    #[serde(default)]
    sharp: Option<f64>,
    #[serde(default)]
    gain: Option<f64>,
    #[serde(default)]
    cut: Option<String>,
}

fn named_cut(s: &str) -> Option<Cut> {
    Some(match s {
        "none" => Cut::None,
        "hug" => Cut::Hug,
        "tear" => Cut::Tear,
        "canyon" => Cut::Canyon,
        "sub_kill" => Cut::SubKill,
        "air_cap" => Cut::AirCap,
        "air_kill" => Cut::AirKill,
        _ => return None,
    })
}
fn lane_cut(a: &Articulation) -> Result<Cut, String> {
    if a.cut == "null" {
        // foundation null: zero.ratio carries the absolute zero Hz; depth is 1.0 by definition
        a.zero.ok_or("null cut requires zero {ratio: Hz}")?;
        Ok(Cut::Null)
    } else if a.cut == "custom" {
        let z = a.zero.ok_or("custom cut requires zero {ratio,depth}")?;
        Ok(Cut::Custom {
            ratio: z.ratio,
            depth: z.depth,
            absolute: z.track == TrackKind::Absolute,
        })
    } else {
        named_cut(&a.cut).ok_or(format!("unknown cut '{}'", a.cut))
    }
}

fn bake_recipe(rf: &RecipeFile) -> Result<Body, String> {
    let r = &rf.recipe;
    if r.lanes.len() != 6 {
        return Err(format!("need exactly 6 lanes, got {}", r.lanes.len()));
    }
    let mut base = [Part { on: true, spot: 0.0, sharp: 0.0, loud: 0.0, cut: Cut::None, zspot: 8000.0 }; 6];
    let mut morph_moves = [0.0f64; 6];
    let mut target_hz: [Option<f64>; 6] = [None; 6];
    for (i, l) in r.lanes.iter().enumerate() {
        base[i] = Part {
            on: true,
            spot: l.anatomy.pole_hz,
            sharp: l.anatomy.sharp,
            loud: l.survival.gain,
            cut: lane_cut(&l.articulation)?,
            zspot: l.articulation.zero.map(|z| z.ratio).unwrap_or(8000.0),
        };
        morph_moves[i] = l.articulation.morph_move;
        target_hz[i] = l.anatomy.target_hz;
    }

    let slide = 2f64.powf(r.axes.morph.slide_semitones / 12.0);
    let amt = r.axes.secondary.amount;
    let mode = r.axes.secondary.mode.as_str();

    let apply_axis = |p: &Part, mv: f64, target: Option<f64>| -> Part {
        let mut np = *p;
        np.spot = target.unwrap_or(np.spot * slide); // per-lane target wins, else global slide
        if mv != 0.0 {
            if let Cut::Custom { ratio, depth, absolute } = np.cut {
                np.cut = Cut::Custom { ratio: ratio + mv, depth, absolute };
            }
        }
        np
    };
    let apply_secondary = |p: &Part| -> Part {
        let mut np = *p;
        match mode {
            "weight" => np.loud *= 1.0 + amt,
            "open" => np.sharp = (np.sharp - amt * (1.0 - np.sharp)).clamp(0.5, 0.9990),
            _ => np.sharp = (1.0 - amt * (1.0 - np.sharp)).clamp(0.5, 0.9990), // q_crank (freq-locked)
        }
        np
    };

    let mut corners = [base; 4];
    for i in 0..6 {
        corners[0][i] = base[i];
        corners[1][i] = apply_axis(&base[i], morph_moves[i], target_hz[i]);
        corners[2][i] = apply_secondary(&base[i]);
        corners[3][i] = apply_secondary(&apply_axis(&base[i], morph_moves[i], target_hz[i]));
    }

    for ov in &r.overrides {
        let ci = match ov.corner.as_str() {
            "c0" | "C0" => 0,
            "c1" | "C1" => 1,
            "c2" | "C2" => 2,
            "c3" | "C3" => 3,
            other => return Err(format!("bad override corner '{other}'")),
        };
        if ov.lane >= 6 {
            return Err(format!("override lane {} out of range", ov.lane));
        }
        let p = &mut corners[ci][ov.lane];
        if let Some(v) = ov.set.pole_hz {
            p.spot = v;
        }
        if let Some(v) = ov.set.sharp {
            p.sharp = v;
        }
        if let Some(v) = ov.set.gain {
            p.loud = v;
        }
        if let Some(ref c) = ov.set.cut {
            p.cut = named_cut(c).ok_or(format!("override cut '{c}' must be a named cut"))?;
        }
    }

    Ok(Body { name: rf.name.clone(), corners })
}

// worst pole radius across the whole Morph/Q grid (the packed middle can go
// unstable where no corner does) — the survival gate.
fn worst_radius_grid(b: &Body) -> f64 {
    let mut m = 0.0f64;
    for mi in 0..=8 {
        for qi in 0..=8 {
            let st = b.live(mi as f32 / 8.0, qi as f32 / 8.0);
            m = m.max(b.worst_radius(&st));
        }
    }
    m
}

fn bake_file(path: &str, out: Option<&str>) -> Result<String, String> {
    let text = std::fs::read_to_string(path).map_err(|e| format!("read {path}: {e}"))?;
    let mut root: serde_json::Value =
        serde_json::from_str(&text).map_err(|e| format!("parse {path}: {e}"))?;
    let rf: RecipeFile =
        serde_json::from_value(root.clone()).map_err(|e| format!("recipe in {path}: {e}"))?;

    let body = bake_recipe(&rf)?;
    let on_unstable = rf.recipe.constraints.on_unstable;
    let wr = worst_radius_grid(&body);
    if wr >= 1.0 && on_unstable == OnUnstable::Reject {
        return Err(format!(
            "unstable: worst pole radius {wr:.4} >= 1.0 across the Morph/Q grid (on_unstable=reject)"
        ));
    }

    let labels = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];
    let mut keyframes = Vec::new();
    for c in 0..4 {
        let mut pw = Vec::new();
        for p in 0..6 {
            pw.push(serde_json::json!(body.corners[c][p].words().to_vec()));
        }
        keyframes.push(serde_json::json!({
            "label": labels[c],
            "boost": 1.0,
            "packedWords": pw,
        }));
    }

    let stem = sanitize(&rf.name);
    let dir = std::path::Path::new(path)
        .parent()
        .unwrap_or_else(|| std::path::Path::new("."));
    let body_path = dir.join(format!("{stem}.body240"));
    std::fs::write(&body_path, body.pack_240()).map_err(|e| format!("write body240: {e}"))?;

    if let serde_json::Value::Object(map) = &mut root {
        map.insert("format".into(), serde_json::json!("forge-cartridge-v1"));
        map.insert("keyframes".into(), serde_json::Value::Array(keyframes));
        map.remove("stages");
    }
    let cart_path = out.unwrap_or(path).to_string();
    let pretty = serde_json::to_string_pretty(&root).map_err(|e| format!("serialize: {e}"))?;
    std::fs::write(&cart_path, pretty).map_err(|e| format!("write cartridge: {e}"))?;

    Ok(format!(
        "baked '{stem}'  ->  {cart_path}  +  {}   (worst radius {wr:.4}{})",
        body_path.display(),
        if wr >= 1.0 { " — UNSTABLE, clamped/kept" } else { " — stable" }
    ))
}

fn preset_bank() -> [(PresetKind, &'static str); 4] {
    [
        (PresetKind::Vowel, "vowel"),
        (PresetKind::Comb, "comb"),
        (PresetKind::Canyon, "canyon"),
        (PresetKind::Cliff, "cliff"),
    ]
}

fn write_builtin_presets(out_dir: &str) -> Result<String, String> {
    let dir = std::path::Path::new(out_dir);
    std::fs::create_dir_all(dir).map_err(|e| format!("mkdir {}: {e}", dir.display()))?;
    let labels = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];
    let mut manifest = Vec::new();

    for (kind, family) in preset_bank() {
        let body = Body::preset(kind);
        let stem = sanitize(&body.name);
        let body_path = dir.join(format!("{stem}.body240"));
        let cart_path = dir.join(format!("{stem}.cartridge.json"));
        std::fs::write(&body_path, body.pack_240()).map_err(|e| format!("write {}: {e}", body_path.display()))?;

        let mut keyframes = Vec::new();
        for c in 0..4 {
            let mut pw = Vec::new();
            for p in 0..6 {
                pw.push(serde_json::json!(body.corners[c][p].words().to_vec()));
            }
            keyframes.push(serde_json::json!({
                "label": labels[c],
                "boost": 1.0,
                "packedWords": pw,
            }));
        }
        let cart = serde_json::json!({
            "format": "compiled-v1",
            "name": body.name,
            "sampleRate": SR,
            "authoring_sample_rate_hz": SR,
            "stages": 6,
            "cornerOrder": labels,
            "provenance": "forge-builtins-v1",
            "family": family,
            "keyframes": keyframes,
        });
        let pretty = serde_json::to_string_pretty(&cart).map_err(|e| format!("serialize {}: {e}", stem))?;
        std::fs::write(&cart_path, pretty).map_err(|e| format!("write {}: {e}", cart_path.display()))?;
        manifest.push(serde_json::json!({
            "name": stem,
            "family": family,
            "body240": body_path.file_name().and_then(|s| s.to_str()).unwrap_or_default(),
            "cartridge": cart_path.file_name().and_then(|s| s.to_str()).unwrap_or_default(),
            "bytes": 240,
            "corners": 4,
            "stages": 6,
        }));
    }

    let manifest_path = dir.join("manifest.json");
    let text = serde_json::to_string_pretty(&serde_json::json!({
        "format": "forge-preset-manifest-v1",
        "corner_labels": ["C0", "C1", "C2", "C3"],
        "runtime_corner_order": labels,
        "presets": manifest,
    }))
    .map_err(|e| format!("serialize manifest: {e}"))?;
    std::fs::write(&manifest_path, text).map_err(|e| format!("write {}: {e}", manifest_path.display()))?;

    Ok(format!("wrote {} presets -> {}", manifest.len(), dir.display()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn body_bytes_roundtrip() {
        let body = Body::starter();
        let bytes = body.pack_240();
        assert_eq!(bytes.len(), 240);
        let words = words_from_body_bytes(&bytes).expect("240 bytes parse");
        assert_eq!(words_to_body_bytes(&words), bytes);
    }

    #[test]
    fn lerp_matches_msvc_reference() {
        // the C formula: (uint16_t)((int16_t)((float)((int)b - (int)a) * frac) + a)
        let reference = |a: u16, b: u16, frac: f32| -> u16 {
            let product = (b as i32 - a as i32) as f32 * frac;
            let trunc = product.trunc() as i32;
            let delta = (trunc + 0x8000).rem_euclid(0x1_0000) - 0x8000;
            ((a as i32 + delta) & 0xFFFF) as u16
        };
        for &(a, b) in &[(0u16, 0xFFFFu16), (0xFFFF, 0), (0x7FFF, 0x8000), (0x8000, 0x7FFF), (1234, 54321), (65535, 1)] {
            for i in 0..=16 {
                let frac = i as f32 / 16.0;
                assert_eq!(lerp_u16(a, b, frac), reference(a, b, frac), "a={a} b={b} frac={frac}");
            }
        }
    }

    #[test]
    fn null_cut_survives_packing_exactly_on_unit_circle() {
        // the FOUNDATION letter: after minifloat pack/unpack the zero must sit
        // at r = 1.0 EXACTLY (b2 == b0), like every studied ROM iconic.
        let p = Part { on: true, spot: 220.0, sharp: 0.995, loud: 1.0, cut: Cut::Null, zspot: 8000.0 };
        let b = words_to_biquad(p.words());
        assert!(b[0] != 0.0);
        assert_eq!(b[2], b[0], "zero radius must be exactly 1.0 after packing");
        // pole side untouched and stable
        assert!(b[4].max(0.0).sqrt() < 1.0);
        // a true audible kill lands near the asked Hz (minifloat may shift it slightly)
        let (mut min_db, mut min_f) = (f64::MAX, 0.0);
        for i in 0..4000 {
            let f = 4000.0 + i as f64;
            let m = biquad_mag_db(b, f);
            if m < min_db {
                min_db = m;
                min_f = f;
            }
        }
        assert!(min_db < -60.0, "null depth {min_db:.1} dB at {min_f} Hz");
        assert!((min_f - 8000.0).abs() < 800.0, "null landed at {min_f} Hz, asked 8000");
        // the FOUNDATION level law: neutral mids (anchored at sqrt(fp*fz)),
        // real weight below, top killed — never DC-normalized.
        let fr = (220.0f64 * 8000.0).sqrt();
        let mid = biquad_mag_db(b, fr);
        assert!(mid.abs() < 1.5, "mid anchor {mid:.1} dB at {fr:.0} Hz, want ~0");
        let dc = biquad_mag_db(b, F_LO);
        assert!(dc > 10.0, "foundation weight {dc:.1} dB at DC side, want > +10");
        let top = biquad_mag_db(b, 15000.0);
        assert!(top < -20.0, "top {top:.1} dB at 15 kHz, want killed");
    }

    #[test]
    fn snap_grabs_nearest_rail() {
        assert_eq!(snap_rail(205.0), 200.0);
        assert_eq!(snap_rail(800.0), 790.0);   // 790 is the nearest of 780/785/790
        assert_eq!(snap_rail(4100.0), 4130.0); // pull toward the tear rail, not 3790
        assert_eq!(snap_rail(10000.0), 9650.0);
        assert_eq!(snap_rail(30.0), 134.0);    // below all rails -> lowest
    }

    #[test]
    fn presets_stable_over_grid() {
        for kind in [PresetKind::Vowel, PresetKind::Comb, PresetKind::Canyon, PresetKind::Cliff] {
            let body = Body::preset(kind);
            assert_eq!(body.pack_240().len(), 240);
            let wr = worst_radius_grid(&body);
            assert!(wr < 1.0, "preset {:?} worst pole radius {wr} >= 1", body.name);
        }
    }

    #[test]
    fn ledger_reaches_rom_scale_gestures() {
        // the flatness ceiling is gone: cranking one lane's ledger must move
        // the packed cascade by ROM-scale amounts, not ±8 dB.
        let quiet = Body::preset(PresetKind::Vowel);
        let mut loud = Body::preset(PresetKind::Vowel);
        loud.corners[0][1].loud = 10.0; // +20 dB on the 620 Hz lane at C0
        let mag = |b: &Body, f: f64| {
            let stages = live_words(&b.words_all(), 0.0, 0.0);
            stages_mag(&stages, f)
        };
        let lift = mag(&loud, 620.0) - mag(&quiet, 620.0);
        assert!(lift > 15.0, "ledger lift only {lift:.1} dB, want ROM-scale");
    }

    #[test]
    fn presets_carry_the_foundation() {
        // the grammar law (33/33 musical ROM bodies): stage 6 holds a TRUE
        // unit-circle zero at every corner. Defaults must encode it.
        for kind in [PresetKind::Vowel, PresetKind::Comb, PresetKind::Canyon, PresetKind::Cliff] {
            let body = Body::preset(kind);
            let words = body.words_all();
            for c in 0..4 {
                let b = words_to_biquad(words[c][5]);
                assert!(b[0] != 0.0 && b[2] == b[0], "preset {:?} corner {c} stage 6 must carry the foundation null", body.name);
            }
        }
    }
}

fn main() -> eframe::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() >= 3 && args[1] == "bake" {
        match bake_file(&args[2], args.get(3).map(|s| s.as_str())) {
            Ok(msg) => println!("{msg}"),
            Err(e) => {
                eprintln!("bake failed: {e}");
                std::process::exit(1);
            }
        }
        return Ok(());
    }
    if args.len() >= 2 && args[1] == "presets" {
        let out = args.get(2).map(|s| s.as_str()).unwrap_or("../dev/tmp/forge_builtin_presets");
        match write_builtin_presets(out) {
            Ok(msg) => println!("{msg}"),
            Err(e) => {
                eprintln!("preset export failed: {e}");
                std::process::exit(1);
            }
        }
        return Ok(());
    }

    let opts = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default().with_inner_size([1180.0, 700.0]),
        ..Default::default()
    };
    eframe::run_native("df2 forge", opts, Box::new(|_cc| Ok(Box::new(Forge::new()))))
}
