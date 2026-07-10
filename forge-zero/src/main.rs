//! FORGE ZERO — iteration 2 of the from-zero design surface.
//!
//! The model IS the state: a `forge_model::Design` (multi-anchor, six
//! modes), and the 240-byte packed body is its PROJECTION. it2 = the
//! wheels: MORPH and Q both drive the real packed engine live; the four
//! corner anchors are the editing poses. Drop a roster `.body240` and its six lanes are
//! on screen, each grabbable at the poses; drop a WAV and it's the loop.
//!
//! White curve = the packed interior you are hearing (the runtime's
//! truth). Amber = the native model at the active pose; the daylight
//! between them is the projection loss, printed in the footer.
//! Interior wheel positions are derived — no dots there, no lie.
//! Ladder: it3b mode activation · it4 adaptive order.

use eframe::egui::{self, Color32, Pos2, Rect, Sense, Stroke, Vec2};
use forge_model::packed::{import, project, CORNERS};
use forge_model::sos::cascade_loss;
use forge_model::{Anchor, Design, Mode, RootPair};
use std::path::Path;
use std::sync::{Arc, Mutex};
use trench_core::minifloat::PackedCorners;

const SR_AUTHOR: f32 = 39062.5; // packed-domain rate: drawing + packing
const F_MIN: f32 = 30.0;
const F_MAX: f32 = 16_000.0;
const DB_MIN: f32 = -36.0;
const DB_MAX: f32 = 24.0;
const RP_MAX: f64 = 0.9989;
/// Wheel this close to an end = you are AT that pose, editing it.
const POSE_SNAP: f32 = 0.02;

/// Lane colors (the typed_vowl palette — stage identity across the repo).
const LANE: [Color32; 6] = [
    Color32::from_rgb(0x8b, 0x8f, 0xf0),
    Color32::from_rgb(0xe6, 0xa1, 0x3b),
    Color32::from_rgb(0xee, 0x6a, 0x3c),
    Color32::from_rgb(0x56, 0xed, 0x70),
    Color32::from_rgb(0x2f, 0xc8, 0xcc),
    Color32::from_rgb(0xe0, 0xd2, 0x4a),
];

fn hz_r(p: RootPair) -> (f64, f64) {
    match p {
        RootPair::Pair { hz, r } => (hz, r),
        RootPair::Split { z1, z2 } => (0.0, z1.abs().max(z2.abs())),
    }
}

fn default_design() -> Design {
    let mode = Mode::pole_zero(740.0, 0.97, 1480.0, 0.90);
    Design {
        name: "zero".into(),
        anchors: CORNERS
            .iter()
            .map(|&(morph, q)| Anchor {
                morph,
                q,
                modes: vec![mode],
            })
            .collect(),
    }
}

// ---- response math ------------------------------------------------------------

fn rows_db(rows: &[[f64; 5]], f: f32) -> f32 {
    let w = std::f64::consts::TAU * f as f64 / SR_AUTHOR as f64;
    let (c1, s1) = (w.cos(), -w.sin());
    let (c2, s2) = ((2.0 * w).cos(), -(2.0 * w).sin());
    let mut mag2 = 1.0f64;
    for r in rows {
        let (nr, ni) = (r[0] + r[1] * c1 + r[2] * c2, r[1] * s1 + r[2] * s2);
        let (dr, di) = (1.0 + r[3] * c1 + r[4] * c2, r[3] * s1 + r[4] * s2);
        mag2 *= (nr * nr + ni * ni) / (dr * dr + di * di).max(1e-300);
    }
    (10.0 * mag2.max(1e-30).log10()) as f32
}

/// Replace one root of a mode, keeping its authored gain and other root.
/// Rebuilding through a gain law here would silently re-voice roster
/// stages (typed c4 gains are not the DC-norm law) — so only roots move.
fn with_root(m: &Mode, pole: bool, hz: f64, r: f64) -> Mode {
    let mut out = *m;
    let pair = RootPair::Pair { hz, r };
    if pole {
        out.pole = pair;
    } else {
        out.zero = pair;
    }
    out
}

/// Solve this mode's root radius so the POSE's cascade curve at `f` meets
/// `target_db`. The other modes are fixed, so bisection runs on this mode
/// alone against the residual target. Monotonic in r either way.
fn solve_radius(modes: &[Mode], k: usize, pole: bool, f: f32, target_db: f32) -> f64 {
    let others_db: f32 = modes
        .iter()
        .enumerate()
        .filter(|&(i, _)| i != k)
        .map(|(_, m)| rows_db(&[m.biquad()], f))
        .sum();
    let want = target_db - others_db;
    let (mut lo, mut hi) = if pole { (0.05f64, RP_MAX) } else { (0.0f64, 1.0f64) };
    for _ in 0..28 {
        let mid = 0.5 * (lo + hi);
        let probe = with_root(&modes[k], pole, f as f64, mid);
        let rising = pole;
        if (rows_db(&[probe.biquad()], f) < want) == rising {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    0.5 * (lo + hi)
}

// ---- audio: source -> Packed (real engine, live wheel) or Native pose ---------

#[derive(Clone, Copy, PartialEq)]
enum Monitor {
    Packed,
    Native,
}

struct AudioCtl {
    playing: bool,
    monitor: Monitor,
    morph: f64,
    q: f64,
    pending_cart: Option<trench_core::cartridge::Cartridge>,
    pending_native: Option<Vec<[f64; 5]>>,
    pending_loop: Option<Arc<Vec<f32>>>,
}

struct Audio {
    _stream: cpal::Stream,
    ctl: Arc<Mutex<AudioCtl>>,
    sr: f64,
}

fn start_audio(body: [u8; 240], native: Vec<[f64; 5]>) -> Result<Audio, String> {
    use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
    let device = cpal::default_host()
        .default_output_device()
        .ok_or("no audio output device")?;
    let config = device.default_output_config().map_err(|e| e.to_string())?;
    let sr = config.sample_rate().0 as f64;
    let channels = config.channels() as usize;
    let cart = trench_core::cartridge::Cartridge::from_body_bytes("zero", &body, 1.0)
        .map_err(|e| format!("cartridge: {e}"))?;
    let ctl = Arc::new(Mutex::new(AudioCtl {
        playing: false,
        monitor: Monitor::Packed,
        morph: 0.0,
        q: 0.0,
        pending_cart: Some(cart),
        pending_native: Some(native),
        pending_loop: None,
    }));
    let ctl_cb = ctl.clone();
    let mut engine = trench_core::engine::FilterEngine::new();
    engine.prepare(sr);
    let mut native_rows: Vec<[f64; 5]> = vec![[1.0, 0.0, 0.0, 0.0, 0.0]];
    let mut native_state: Vec<(f64, f64)> = vec![(0.0, 0.0)];
    let mut loop_buf: Option<Arc<Vec<f32>>> = None;
    let mut loop_pos = 0usize;
    let mut saw_phase = 0.0f32;
    let mut left = vec![0.0f32; 256];
    let mut right = vec![0.0f32; 256];
    let stream = device
        .build_output_stream(
            &config.into(),
            move |data: &mut [f32], _| {
                let (playing, monitor, morph, q, cart, native, lp) = {
                    let mut c = ctl_cb.lock().unwrap();
                    (
                        c.playing,
                        c.monitor,
                        c.morph,
                        c.q,
                        c.pending_cart.take(),
                        c.pending_native.take(),
                        c.pending_loop.take(),
                    )
                };
                if let Some(cart) = cart {
                    engine.load_cartridge(cart);
                }
                if let Some(rows) = native {
                    native_rows = rows;
                    native_state = vec![(0.0, 0.0); native_rows.len()];
                }
                if let Some(lp) = lp {
                    loop_buf = Some(lp);
                    loop_pos = 0;
                }
                if !playing {
                    data.fill(0.0);
                    return;
                }
                let frames = data.len() / channels;
                let mut done = 0;
                while done < frames {
                    let n = (frames - done).min(256);
                    if let Some(buf) = &loop_buf {
                        for v in left[..n].iter_mut() {
                            *v = buf[loop_pos];
                            loop_pos = (loop_pos + 1) % buf.len();
                        }
                    } else {
                        // A1 saw until a loop is dropped
                        let f = 55.0 / sr as f32;
                        for v in left[..n].iter_mut() {
                            saw_phase = (saw_phase + f).fract();
                            *v = (saw_phase * 2.0 - 1.0) * 0.30;
                        }
                    }
                    right[..n].copy_from_slice(&left[..n]);
                    match monitor {
                        Monitor::Packed => {
                            engine.process_block(&mut left[..n], &mut right[..n], morph, q);
                        }
                        Monitor::Native => {
                            // the model itself at the active pose: f64 DF2T
                            for v in left[..n].iter_mut() {
                                let mut x = *v as f64;
                                for (r, s) in native_rows.iter().zip(native_state.iter_mut()) {
                                    let y = r[0] * x + s.0;
                                    s.0 = r[1] * x - r[3] * y + s.1;
                                    s.1 = r[2] * x - r[4] * y;
                                    x = y;
                                }
                                *v = x as f32;
                            }
                            if native_state.iter().any(|s| !s.0.is_finite() || !s.1.is_finite()) {
                                for s in native_state.iter_mut() {
                                    *s = (0.0, 0.0);
                                }
                            }
                            right[..n].copy_from_slice(&left[..n]);
                        }
                    }
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
            |err| eprintln!("audio: {err}"),
            None,
        )
        .map_err(|e| e.to_string())?;
    stream.play().map_err(|e| e.to_string())?;
    Ok(Audio {
        _stream: stream,
        ctl,
        sr,
    })
}

// ---- minimal WAV reader (PCM16 + float32, first channel) ---------------------

fn read_wav(path: &Path) -> Option<(Vec<f32>, f64)> {
    let b = std::fs::read(path).ok()?;
    if b.len() < 44 || &b[0..4] != b"RIFF" || &b[8..12] != b"WAVE" {
        return None;
    }
    let (mut pos, mut fmt, mut data) = (12usize, None, None);
    while pos + 8 <= b.len() {
        let id = &b[pos..pos + 4];
        let sz = u32::from_le_bytes(b[pos + 4..pos + 8].try_into().ok()?) as usize;
        let body = pos + 8;
        if id == b"fmt " {
            fmt = Some((
                u16::from_le_bytes(b[body..body + 2].try_into().ok()?),
                u16::from_le_bytes(b[body + 2..body + 4].try_into().ok()?),
                u32::from_le_bytes(b[body + 4..body + 8].try_into().ok()?),
                u16::from_le_bytes(b[body + 14..body + 16].try_into().ok()?),
            ));
        } else if id == b"data" {
            data = Some((body, sz.min(b.len().saturating_sub(body))));
        }
        pos = body + sz + (sz & 1);
    }
    let ((tag, ch, sr, bits), (off, len)) = (fmt?, data?);
    let ch = ch.max(1) as usize;
    let mut out = Vec::new();
    match (tag, bits) {
        (1, 16) => {
            let step = 2 * ch;
            for i in (off..off + len).step_by(step) {
                if i + 2 > b.len() {
                    break;
                }
                out.push(i16::from_le_bytes([b[i], b[i + 1]]) as f32 / 32768.0);
            }
        }
        (3, 32) => {
            let step = 4 * ch;
            for i in (off..off + len).step_by(step) {
                if i + 4 > b.len() {
                    break;
                }
                out.push(f32::from_le_bytes([b[i], b[i + 1], b[i + 2], b[i + 3]]));
            }
        }
        _ => return None,
    }
    if out.is_empty() {
        return None;
    }
    Some((out, sr as f64))
}

// ---- the app -------------------------------------------------------------------

#[derive(Clone, Copy, PartialEq)]
enum Grab {
    Pole(usize),
    Zero(usize),
    MorphWheel,
    QWheel,
}

/// Which anchor pose the wheels are at, if any (both must sit at an end).
fn pose_of(wheel: f32, qwheel: f32) -> Option<(f64, f64)> {
    let axis = |w: f32| {
        if w <= POSE_SNAP {
            Some(0.0)
        } else if w >= 1.0 - POSE_SNAP {
            Some(1.0)
        } else {
            None
        }
    };
    Some((axis(wheel)?, axis(qwheel)?))
}

struct Zero {
    design: Design,
    wheel: f32,
    qwheel: f32,
    body: [u8; 240],
    /// Decoded packed rows at the current wheel position — what you hear.
    heard: Vec<[f64; 5]>,
    /// Projection loss at the active pose (None between poses).
    loss: Option<(f64, f64)>,
    monitor: Monitor,
    audio: Option<Audio>,
    playing: bool,
    grab: Option<Grab>,
    status: String,
}

impl Zero {
    fn new() -> Self {
        // optional CLI arg: a .body240 to load as the design
        let design = std::env::args()
            .nth(1)
            .and_then(|p| {
                let path = std::path::PathBuf::from(&p);
                let name = path
                    .file_stem()
                    .map(|s| s.to_string_lossy().into_owned())
                    .unwrap_or_default();
                std::fs::read(&path).ok().and_then(|b| import(&name, &b).ok())
            })
            .unwrap_or_else(default_design);
        let mut z = Self {
            design,
            wheel: 0.0,
            qwheel: 0.0,
            body: [0; 240],
            heard: Vec::new(),
            loss: None,
            monitor: Monitor::Packed,
            audio: None,
            playing: false,
            grab: None,
            status: "drop a .body240 to load it · drop a WAV to replace the saw".into(),
        };
        z.reproject();
        z
    }

    fn active_pose(&self) -> Option<&Anchor> {
        pose_of(self.wheel, self.qwheel).and_then(|(m, q)| self.design.anchor_at(m, q))
    }

    fn native_rows(&self) -> Vec<[f64; 5]> {
        // the pose the wheels are nearest — the native monitor's cascade
        let m = if self.wheel < 0.5 { 0.0 } else { 1.0 };
        let q = if self.qwheel < 0.5 { 0.0 } else { 1.0 };
        self.design
            .anchor_at(m, q)
            .map(|a| a.modes.iter().map(Mode::biquad).collect())
            .unwrap_or_default()
    }

    /// Design changed: re-project, push the cartridge + native rows.
    fn reproject(&mut self) {
        match project(&self.design) {
            Ok(body) => self.body = body,
            Err(e) => {
                self.status = format!("projection failed: {e}");
                return;
            }
        }
        self.wheel_moved();
        if let Some(a) = &self.audio {
            if let Ok(cart) =
                trench_core::cartridge::Cartridge::from_body_bytes("zero", &self.body, 1.0)
            {
                if let Ok(mut c) = a.ctl.lock() {
                    c.pending_cart = Some(cart);
                    c.pending_native = Some(self.native_rows());
                }
            }
        }
    }

    /// Wheel moved (or design changed): refresh the heard curve + loss.
    fn wheel_moved(&mut self) {
        if let Ok(pc) = PackedCorners::from_body_bytes(&self.body) {
            self.heard = pc.interpolate_biquad(self.wheel, self.qwheel).to_vec();
        }
        self.loss = self.active_pose().map(|anchor| {
            let native: Vec<[f64; 5]> = anchor.modes.iter().map(Mode::biquad).collect();
            cascade_loss(&self.heard, &native)
        });
        if let Some(a) = &self.audio {
            if let Ok(mut c) = a.ctl.lock() {
                c.morph = self.wheel as f64;
                c.q = self.qwheel as f64;
                c.pending_native = Some(self.native_rows());
            }
        }
    }
}

fn x_of(rect: Rect, f: f32) -> f32 {
    rect.left() + (f / F_MIN).log2() / (F_MAX / F_MIN).log2() * rect.width()
}
fn f_of(rect: Rect, x: f32) -> f32 {
    let t = ((x - rect.left()) / rect.width()).clamp(0.0, 1.0);
    F_MIN * (F_MAX / F_MIN).powf(t)
}
fn y_of(rect: Rect, db: f32) -> f32 {
    rect.bottom() - (db - DB_MIN) / (DB_MAX - DB_MIN) * rect.height()
}
fn db_of(rect: Rect, y: f32) -> f32 {
    DB_MIN + ((rect.bottom() - y) / rect.height()).clamp(0.0, 1.0) * (DB_MAX - DB_MIN)
}

fn curve(plot: Rect, rows: &[[f64; 5]]) -> Vec<Pos2> {
    let n = 360;
    (0..n)
        .map(|i| {
            let f = F_MIN * (F_MAX / F_MIN).powf(i as f32 / (n - 1) as f32);
            Pos2::new(x_of(plot, f), y_of(plot, rows_db(rows, f)))
        })
        .collect()
}

impl eframe::App for Zero {
    fn update(&mut self, ctx: &egui::Context, _f: &mut eframe::Frame) {
        // drops: .body240 = the design, WAV = the loop
        let dropped = ctx.input(|i| i.raw.dropped_files.clone());
        if let Some(path) = dropped.first().and_then(|d| d.path.clone()) {
            let name = path
                .file_stem()
                .map(|s| s.to_string_lossy().into_owned())
                .unwrap_or_default();
            if path.extension().is_some_and(|e| e == "body240") {
                match std::fs::read(&path).map_err(|e| e.to_string()).and_then(|b| import(&name, &b)) {
                    Ok(design) => {
                        self.design = design;
                        self.reproject();
                        self.status = format!("loaded {name} — six lanes, wheel it");
                    }
                    Err(e) => self.status = format!("import failed: {e}"),
                }
            } else if let Some((samples, wav_sr)) = read_wav(&path) {
                let dev_sr = self.audio.as_ref().map(|a| a.sr).unwrap_or(48_000.0);
                let n_out = ((samples.len() as f64) * dev_sr / wav_sr).max(1.0) as usize;
                let mut buf = Vec::with_capacity(n_out);
                for i in 0..n_out {
                    let x = i as f64 * wav_sr / dev_sr;
                    let j = x as usize;
                    let fr = (x - j as f64) as f32;
                    let a = samples[j.min(samples.len() - 1)];
                    let b = samples[(j + 1).min(samples.len() - 1)];
                    buf.push(a + (b - a) * fr);
                }
                let peak = buf.iter().fold(0.0f32, |m, v| m.max(v.abs())).max(1e-9);
                for v in &mut buf {
                    *v *= 0.5 / peak;
                }
                if let Some(a) = &self.audio {
                    if let Ok(mut c) = a.ctl.lock() {
                        c.pending_loop = Some(Arc::new(buf));
                    }
                }
                self.status = format!("loop: {name}");
            } else {
                self.status = "not a .body240 or readable WAV".into();
            }
        }

        egui::CentralPanel::default()
            .frame(egui::Frame::none().fill(Color32::from_rgb(8, 10, 10)))
            .show(ctx, |ui| {
                let full = ui.available_rect_before_wrap();
                let bar = Rect::from_min_size(full.min, Vec2::new(full.width(), 34.0));
                let wheel_strip = Rect::from_min_max(
                    Pos2::new(full.left() + 8.0, full.bottom() - 84.0),
                    Pos2::new(full.right() - 8.0, full.bottom() - 26.0),
                );
                let plot = Rect::from_min_max(
                    Pos2::new(full.left() + 8.0, bar.bottom() + 4.0),
                    Pos2::new(full.right() - 8.0, wheel_strip.top() - 6.0),
                );
                let p = ui.painter();

                // top bar: PLAY + A/B monitor + title
                let play_r = Rect::from_min_size(
                    Pos2::new(bar.left() + 10.0, bar.top() + 5.0),
                    Vec2::new(70.0, 24.0),
                );
                p.rect_filled(play_r, 4.0, Color32::from_rgb(20, 30, 26));
                p.rect_stroke(play_r, 4.0, Stroke::new(1.0, Color32::from_rgb(70, 200, 120)));
                p.text(
                    play_r.center(),
                    egui::Align2::CENTER_CENTER,
                    if self.playing { "STOP" } else { "PLAY" },
                    egui::FontId::monospace(13.0),
                    Color32::from_rgb(120, 240, 160),
                );
                let ab_r = Rect::from_min_size(
                    Pos2::new(play_r.right() + 10.0, bar.top() + 5.0),
                    Vec2::new(110.0, 24.0),
                );
                let ab_on = self.monitor == Monitor::Native;
                p.rect_filled(ab_r, 4.0, Color32::from_rgb(22, 24, 32));
                p.rect_stroke(
                    ab_r,
                    4.0,
                    Stroke::new(
                        1.0,
                        if ab_on {
                            Color32::from_rgb(240, 220, 120)
                        } else {
                            Color32::from_rgb(90, 100, 120)
                        },
                    ),
                );
                p.text(
                    ab_r.center(),
                    egui::Align2::CENTER_CENTER,
                    if ab_on { "NATIVE f64" } else { "PACKED 240B" },
                    egui::FontId::monospace(12.0),
                    if ab_on {
                        Color32::from_rgb(240, 220, 120)
                    } else {
                        Color32::from_rgb(150, 165, 190)
                    },
                );
                p.text(
                    Pos2::new(ab_r.right() + 14.0, bar.center().y),
                    egui::Align2::LEFT_CENTER,
                    format!("FORGE ZERO — {}", self.design.name),
                    egui::FontId::monospace(12.0),
                    Color32::from_rgb(140, 160, 150),
                );

                // grid
                p.rect_filled(plot, 4.0, Color32::from_rgb(12, 15, 15));
                for f in [100.0, 1000.0, 10000.0] {
                    let x = x_of(plot, f);
                    p.line_segment(
                        [Pos2::new(x, plot.top()), Pos2::new(x, plot.bottom())],
                        Stroke::new(0.6, Color32::from_rgb(30, 38, 36)),
                    );
                }
                let y0 = y_of(plot, 0.0);
                p.line_segment(
                    [Pos2::new(plot.left(), y0), Pos2::new(plot.right(), y0)],
                    Stroke::new(0.8, Color32::from_rgb(45, 55, 52)),
                );

                // native model curve at the active pose (amber, the intent)
                let pose = self.active_pose().cloned();
                if let Some(anchor) = &pose {
                    let native: Vec<[f64; 5]> = anchor.modes.iter().map(Mode::biquad).collect();
                    p.add(egui::Shape::line(
                        curve(plot, &native),
                        Stroke::new(1.4, Color32::from_rgb(214, 148, 62)),
                    ));
                }
                // the packed curve you are hearing (white, the runtime's truth)
                p.add(egui::Shape::line(
                    curve(plot, &self.heard),
                    Stroke::new(2.4, Color32::from_rgb(235, 245, 240)),
                ));

                // dots: only at a pose — the interior is derived, not editable
                let mut dots: Vec<(usize, bool, Pos2)> = Vec::new();
                if let Some(anchor) = &pose {
                    let native: Vec<[f64; 5]> = anchor.modes.iter().map(Mode::biquad).collect();
                    for (k, m) in anchor.modes.iter().enumerate() {
                        let (ph, _) = hz_r(m.pole);
                        let (zh, zr) = hz_r(m.zero);
                        let pf = (ph as f32).clamp(F_MIN, F_MAX);
                        let pos = Pos2::new(x_of(plot, pf), y_of(plot, rows_db(&native, pf)));
                        p.circle_filled(pos, 7.0, LANE[k % 6]);
                        dots.push((k, true, pos));
                        if zr > 0.0001 {
                            let zf = (zh as f32).clamp(F_MIN, F_MAX);
                            let zpos = Pos2::new(x_of(plot, zf), y_of(plot, rows_db(&native, zf)));
                            p.circle_stroke(zpos, 7.0, Stroke::new(2.2, LANE[k % 6]));
                            dots.push((k, false, zpos));
                        }
                    }
                }

                // wheel strip: MORPH and Q tracks
                p.rect_filled(wheel_strip, 4.0, Color32::from_rgb(14, 16, 18));
                let track_l = wheel_strip.left() + 60.0;
                let track_w = wheel_strip.right() - 16.0 - track_l;
                let morph_y = wheel_strip.top() + 20.0;
                let q_y = wheel_strip.bottom() - 16.0;
                for (label, y, val, col) in [
                    ("MORPH", morph_y, self.wheel, Color32::from_rgb(120, 200, 220)),
                    ("Q", q_y, self.qwheel, Color32::from_rgb(220, 170, 110)),
                ] {
                    p.line_segment(
                        [Pos2::new(track_l, y), Pos2::new(track_l + track_w, y)],
                        Stroke::new(2.0, Color32::from_rgb(50, 58, 64)),
                    );
                    let handle = Pos2::new(track_l + val * track_w, y);
                    p.circle_filled(handle, 9.0, col);
                    p.text(
                        Pos2::new(wheel_strip.left() + 8.0, y),
                        egui::Align2::LEFT_CENTER,
                        label,
                        egui::FontId::monospace(11.0),
                        Color32::from_rgb(140, 160, 150),
                    );
                    p.text(
                        Pos2::new(handle.x, y - 14.0),
                        egui::Align2::CENTER_CENTER,
                        format!("{:.0}", val * 100.0),
                        egui::FontId::monospace(10.0),
                        col,
                    );
                }
                let morph_zone = Rect::from_min_max(
                    Pos2::new(wheel_strip.left(), wheel_strip.top()),
                    Pos2::new(wheel_strip.right(), (morph_y + q_y) / 2.0),
                );

                // interaction
                let resp = ui.interact(full, ui.id().with("z"), Sense::click_and_drag());
                let pointer = ctx.input(|i| i.pointer.interact_pos());
                if resp.drag_started() {
                    if let Some(pos) = pointer {
                        if wheel_strip.contains(pos) {
                            self.grab = Some(if morph_zone.contains(pos) {
                                Grab::MorphWheel
                            } else {
                                Grab::QWheel
                            });
                        } else if !play_r.contains(pos) && !ab_r.contains(pos) {
                            let best = dots
                                .iter()
                                .map(|&(k, is_pole, d)| (k, is_pole, pos.distance(d)))
                                .min_by(|a, b| a.2.total_cmp(&b.2));
                            if let Some((k, is_pole, d)) = best {
                                if d < 30.0 {
                                    self.grab =
                                        Some(if is_pole { Grab::Pole(k) } else { Grab::Zero(k) });
                                }
                            }
                        }
                    }
                }
                if resp.clicked() {
                    if let Some(pos) = pointer {
                        if ab_r.contains(pos) {
                            self.monitor = if self.monitor == Monitor::Packed {
                                Monitor::Native
                            } else {
                                Monitor::Packed
                            };
                            if let Some(a) = &self.audio {
                                if let Ok(mut c) = a.ctl.lock() {
                                    c.monitor = self.monitor;
                                }
                            }
                        } else if play_r.contains(pos) {
                            self.playing = !self.playing;
                            if self.playing && self.audio.is_none() {
                                match start_audio(self.body, self.native_rows()) {
                                    Ok(a) => self.audio = Some(a),
                                    Err(e) => {
                                        self.playing = false;
                                        self.status = format!("audio failed: {e}");
                                    }
                                }
                            }
                            if let Some(a) = &self.audio {
                                if let Ok(mut c) = a.ctl.lock() {
                                    c.playing = self.playing;
                                    c.monitor = self.monitor;
                                    c.morph = self.wheel as f64;
                                    c.q = self.qwheel as f64;
                                }
                            }
                        }
                    }
                }
                if let (Some(g), Some(pos)) = (self.grab, pointer) {
                    if resp.dragged() {
                        match g {
                            Grab::MorphWheel => {
                                self.wheel = ((pos.x - track_l) / track_w).clamp(0.0, 1.0);
                                self.wheel_moved();
                            }
                            Grab::QWheel => {
                                self.qwheel = ((pos.x - track_l) / track_w).clamp(0.0, 1.0);
                                self.wheel_moved();
                            }
                            Grab::Pole(k) | Grab::Zero(k) => {
                                if let Some((m0, q0)) = pose_of(self.wheel, self.qwheel) {
                                    let is_pole = matches!(g, Grab::Pole(_));
                                    let f = f_of(plot, pos.x).clamp(F_MIN, F_MAX);
                                    let db_t = db_of(plot, pos.y);
                                    if let Some(ai) = self
                                        .design
                                        .anchors
                                        .iter()
                                        .position(|a| a.morph == m0 && a.q == q0)
                                    {
                                        let modes = &mut self.design.anchors[ai].modes;
                                        if k < modes.len() {
                                            let r = solve_radius(modes, k, is_pole, f, db_t);
                                            modes[k] =
                                                with_root(&modes[k], is_pole, f as f64, r);
                                            self.reproject();
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                if resp.drag_stopped() {
                    self.grab = None;
                }

                // footer: pose, loss, status
                let pose_txt = match pose_of(self.wheel, self.qwheel) {
                    Some((m, q)) => format!(
                        "POSE M{}·Q{} — editable",
                        if m == 0.0 { "0" } else { "100" },
                        if q == 0.0 { "0" } else { "100" }
                    ),
                    None => "interior — derived, wheel both to ends to edit".into(),
                };
                let loss_txt = match self.loss {
                    Some((c, i)) => format!("projection loss: complex {c:.1e} / impulse {i:.1e}"),
                    None => "".into(),
                };
                p.text(
                    Pos2::new(plot.left(), full.bottom() - 18.0),
                    egui::Align2::LEFT_TOP,
                    format!("{pose_txt}   ·   {loss_txt}   ·   {}", self.status),
                    egui::FontId::monospace(11.0),
                    Color32::from_rgb(120, 140, 132),
                );
            });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn solve_radius_lands_the_cascade_on_the_target() {
        // two modes; drag mode 1's pole to 900 Hz / +9 dB — the full-cascade
        // curve at 900 Hz must land on the target after the edit.
        let modes = vec![
            Mode::pole_zero(300.0, 0.95, 600.0, 0.7),
            Mode::pole_zero(2000.0, 0.9, 4000.0, 0.5),
        ];
        let f = 900.0f32;
        let target = 9.0f32;
        let mut probe = modes.clone();
        probe[1] = with_root(&probe[1], true, f as f64, 0.5);
        let r = solve_radius(&probe, 1, true, f, target);
        probe[1] = with_root(&probe[1], true, f as f64, r);
        let rows: Vec<[f64; 5]> = probe.iter().map(Mode::biquad).collect();
        let got = rows_db(&rows, f);
        assert!(
            (got - target).abs() < 0.1,
            "cascade at {f} Hz: got {got} dB, want {target} dB (r={r})"
        );
        // authored gain untouched by the root edit
        assert_eq!(probe[1].gain, modes[1].gain);
    }
}

fn main() -> eframe::Result<()> {
    eframe::run_native(
        "FORGE ZERO",
        eframe::NativeOptions {
            viewport: egui::ViewportBuilder::default().with_inner_size([1080.0, 640.0]),
            ..Default::default()
        },
        Box::new(|_| Ok(Box::new(Zero::new()))),
    )
}
