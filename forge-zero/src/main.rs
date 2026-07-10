//! FORGE ZERO — iteration 1 of the from-zero design surface.
//!
//! The model IS the state: `forge_model::Mode` (one mode today), and the
//! 240-byte packed body is its PROJECTION via `forge_model::packed`.
//! it1 = native-vs-projection A/B: both curves drawn (native white, packed
//! projection amber), the per-projection loss printed on-surface, and an
//! A/B monitor — hear the true packed engine or the native f64 model.
//! Ladder: it2 anchors/morph · it3 mode activation · it4 adaptive order.

use eframe::egui::{self, Color32, Pos2, Rect, Sense, Stroke, Vec2};
use forge_model::packed::{project, CORNERS};
use forge_model::sos::cascade_loss;
use forge_model::{Anchor, Design, Mode, RootPair};
use std::path::Path;
use std::sync::{Arc, Mutex};

const SR_AUTHOR: f32 = 39062.5; // packed-domain rate: drawing + packing
const F_MIN: f32 = 30.0;
const F_MAX: f32 = 16_000.0;
const DB_MIN: f32 = -36.0;
const DB_MAX: f32 = 24.0;
const RP_MAX: f32 = 0.9989;

fn hz_r(p: RootPair) -> (f64, f64) {
    match p {
        RootPair::Pair { hz, r } => (hz, r),
        RootPair::Split { z1, z2 } => (0.0, z1.abs().max(z2.abs())),
    }
}

fn make_mode(pole_hz: f32, pole_r: f32, zero_hz: f32, zero_r: f32) -> Mode {
    Mode::pole_zero(pole_hz as f64, pole_r as f64, zero_hz as f64, zero_r as f64)
}

fn default_mode() -> Mode {
    make_mode(740.0, 0.97, 1480.0, 0.90)
}

fn one_mode_design(mode: Mode) -> Design {
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

fn mode_db(m: &Mode, f: f32) -> f32 {
    rows_db(&[m.biquad()], f)
}

/// Solve the radius so the native curve at the handle's own frequency meets
/// target_db. Monotonic in r -> bisection; the dot follows the cursor.
fn solve_radius(m: &Mode, pole: bool, target_db: f32) -> f32 {
    let (ph, pr) = hz_r(m.pole);
    let (zh, zr) = hz_r(m.zero);
    let (mut lo, mut hi) = if pole { (0.05f32, RP_MAX) } else { (0.0f32, 1.0f32) };
    for _ in 0..28 {
        let mid = 0.5 * (lo + hi);
        let (probe, f, rising) = if pole {
            (make_mode(ph as f32, mid, zh as f32, zr as f32), ph as f32, true)
        } else {
            (make_mode(ph as f32, pr as f32, zh as f32, mid), zh as f32, false)
        };
        if (mode_db(&probe, f) < target_db) == rising {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    0.5 * (lo + hi)
}

// ---- projection: the model packed into the 240-byte body ----------------------

fn pack(m: &Mode) -> [u8; 240] {
    project(&one_mode_design(*m)).expect("one-mode design projects")
}

/// Decoded packed rows of corner 0 — what the runtime actually plays there.
fn packed_rows(body: &[u8; 240]) -> Vec<[f64; 5]> {
    let pc = trench_core::minifloat::PackedCorners::from_body_bytes(body).expect("240 bytes");
    (0..6)
        .map(|si| trench_core::minifloat::stage_words_to_biquad(pc.words[0][si]))
        .collect()
}

// ---- audio: source -> Packed (real engine) or Native (f64 model) --------------

#[derive(Clone, Copy, PartialEq)]
enum Monitor {
    Packed,
    Native,
}

struct AudioCtl {
    playing: bool,
    monitor: Monitor,
    pending_cart: Option<trench_core::cartridge::Cartridge>,
    pending_native: Option<[f64; 5]>,
    pending_loop: Option<Arc<Vec<f32>>>,
}

struct Audio {
    _stream: cpal::Stream,
    ctl: Arc<Mutex<AudioCtl>>,
    sr: f64,
}

fn start_audio(body: [u8; 240], native: [f64; 5]) -> Result<Audio, String> {
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
        pending_cart: Some(cart),
        pending_native: Some(native),
        pending_loop: None,
    }));
    let ctl_cb = ctl.clone();
    let mut engine = trench_core::engine::FilterEngine::new();
    engine.prepare(sr);
    let mut native_rows = [1.0f64, 0.0, 0.0, 0.0, 0.0];
    let (mut nw1, mut nw2) = (0.0f64, 0.0f64);
    let mut loop_buf: Option<Arc<Vec<f32>>> = None;
    let mut loop_pos = 0usize;
    let mut saw_phase = 0.0f32;
    let mut left = vec![0.0f32; 256];
    let mut right = vec![0.0f32; 256];
    let stream = device
        .build_output_stream(
            &config.into(),
            move |data: &mut [f32], _| {
                let (playing, monitor, cart, native, lp) = {
                    let mut c = ctl_cb.lock().unwrap();
                    (
                        c.playing,
                        c.monitor,
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
                            engine.process_block(&mut left[..n], &mut right[..n], 0.0, 0.0);
                        }
                        Monitor::Native => {
                            // the model itself: one DF2T biquad, f64, no packing
                            let r = native_rows;
                            for v in left[..n].iter_mut() {
                                let x = *v as f64;
                                let y = r[0] * x + nw1;
                                nw1 = r[1] * x - r[3] * y + nw2;
                                nw2 = r[2] * x - r[4] * y;
                                *v = y as f32;
                            }
                            if !nw1.is_finite() || !nw2.is_finite() {
                                nw1 = 0.0;
                                nw2 = 0.0;
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
    Pole,
    Zero,
}

struct Zero {
    mode: Mode,
    packed: Vec<[f64; 5]>,
    loss: (f64, f64),
    monitor: Monitor,
    audio: Option<Audio>,
    playing: bool,
    grab: Option<Grab>,
    status: String,
}

impl Zero {
    fn new() -> Self {
        let mode = default_mode();
        let packed = packed_rows(&pack(&mode));
        let loss = cascade_loss(&packed, &[mode.biquad()]);
        Self {
            mode,
            packed,
            loss,
            monitor: Monitor::Packed,
            audio: None,
            playing: false,
            grab: None,
            status: "drop a WAV to replace the saw".into(),
        }
    }

    /// Model changed: re-project, re-measure the loss, push both to audio.
    fn model_changed(&mut self) {
        let body = pack(&self.mode);
        self.packed = packed_rows(&body);
        self.loss = cascade_loss(&self.packed, &[self.mode.biquad()]);
        if let Some(a) = &self.audio {
            if let Ok(cart) =
                trench_core::cartridge::Cartridge::from_body_bytes("zero", &body, 1.0)
            {
                if let Ok(mut c) = a.ctl.lock() {
                    c.pending_cart = Some(cart);
                    c.pending_native = Some(self.mode.biquad());
                }
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

impl eframe::App for Zero {
    fn update(&mut self, ctx: &egui::Context, _f: &mut eframe::Frame) {
        // drop a WAV anywhere = the loop
        let dropped = ctx.input(|i| i.raw.dropped_files.clone());
        if let Some(path) = dropped.first().and_then(|d| d.path.clone()) {
            if let Some((samples, wav_sr)) = read_wav(&path) {
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
                self.status = format!(
                    "loop: {}",
                    path.file_name().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default()
                );
            } else {
                self.status = "not a readable WAV (PCM16 / float32)".into();
            }
        }

        egui::CentralPanel::default()
            .frame(egui::Frame::none().fill(Color32::from_rgb(8, 10, 10)))
            .show(ctx, |ui| {
                let full = ui.available_rect_before_wrap();
                let bar = Rect::from_min_size(full.min, Vec2::new(full.width(), 34.0));
                let plot = Rect::from_min_max(
                    Pos2::new(full.left() + 8.0, bar.bottom() + 4.0),
                    Pos2::new(full.right() - 8.0, full.bottom() - 26.0),
                );
                let p = ui.painter();

                // top bar: PLAY + A/B monitor + status
                let play_r = Rect::from_min_size(
                    Pos2::new(bar.left() + 10.0, bar.top() + 5.0),
                    Vec2::new(70.0, 24.0),
                );
                p.rect_filled(play_r, 4.0, Color32::from_rgb(20, 30, 26));
                p.rect_stroke(
                    play_r,
                    4.0,
                    Stroke::new(1.0, Color32::from_rgb(70, 200, 120)),
                );
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
                    "FORGE ZERO — the model, projected · drag the dots · drop a WAV",
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

                // it1 A/B on the canvas: packed projection (amber, what ships)
                // under the native model curve (white, the source of truth)
                let n = 360;
                let packed_pts: Vec<Pos2> = (0..n)
                    .map(|i| {
                        let f = F_MIN * (F_MAX / F_MIN).powf(i as f32 / (n - 1) as f32);
                        Pos2::new(x_of(plot, f), y_of(plot, rows_db(&self.packed, f)))
                    })
                    .collect();
                p.add(egui::Shape::line(
                    packed_pts,
                    Stroke::new(1.4, Color32::from_rgb(214, 148, 62)),
                ));
                let pts: Vec<Pos2> = (0..n)
                    .map(|i| {
                        let f = F_MIN * (F_MAX / F_MIN).powf(i as f32 / (n - 1) as f32);
                        Pos2::new(x_of(plot, f), y_of(plot, mode_db(&self.mode, f)))
                    })
                    .collect();
                p.add(egui::Shape::line(
                    pts,
                    Stroke::new(2.4, Color32::from_rgb(235, 245, 240)),
                ));

                // the two dots, ON the native curve at their own frequencies
                let (ph, _pr) = hz_r(self.mode.pole);
                let (zh, _zr) = hz_r(self.mode.zero);
                let pole_pos = Pos2::new(
                    x_of(plot, ph as f32),
                    y_of(plot, mode_db(&self.mode, ph as f32)),
                );
                let zero_pos = Pos2::new(
                    x_of(plot, zh as f32),
                    y_of(plot, mode_db(&self.mode, zh as f32)),
                );
                p.circle_filled(pole_pos, 8.0, Color32::from_rgb(255, 178, 92));
                p.circle_stroke(zero_pos, 8.0, Stroke::new(2.4, Color32::from_rgb(127, 212, 255)));

                // interaction
                let resp = ui.interact(full, ui.id().with("z"), Sense::click_and_drag());
                let pointer = ctx.input(|i| i.pointer.interact_pos());
                if resp.drag_started() {
                    if let Some(pos) = pointer {
                        if !play_r.contains(pos) && !ab_r.contains(pos) {
                            let dp = pos.distance(pole_pos);
                            let dz = pos.distance(zero_pos);
                            if dp.min(dz) < 30.0 {
                                self.grab = Some(if dp <= dz { Grab::Pole } else { Grab::Zero });
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
                                match start_audio(pack(&self.mode), self.mode.biquad()) {
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
                                }
                            }
                        }
                    }
                }
                if let (Some(g), Some(pos)) = (self.grab, pointer) {
                    if resp.dragged() {
                        let f = f_of(plot, pos.x).clamp(F_MIN, F_MAX);
                        let db_t = db_of(plot, pos.y);
                        let (cur_ph, cur_pr) = hz_r(self.mode.pole);
                        let (cur_zh, cur_zr) = hz_r(self.mode.zero);
                        self.mode = match g {
                            Grab::Pole => {
                                let m = make_mode(f, cur_pr as f32, cur_zh as f32, cur_zr as f32);
                                let r = solve_radius(&m, true, db_t);
                                make_mode(f, r, cur_zh as f32, cur_zr as f32)
                            }
                            Grab::Zero => {
                                let m = make_mode(cur_ph as f32, cur_pr as f32, f, cur_zr as f32);
                                let r = solve_radius(&m, false, db_t);
                                make_mode(cur_ph as f32, cur_pr as f32, f, r)
                            }
                        };
                        self.model_changed();
                    }
                }
                if resp.drag_stopped() {
                    self.grab = None;
                }

                // footer: the mode + the projection loss, in plain words
                let (fph, fpr) = hz_r(self.mode.pole);
                let (fzh, fzr) = hz_r(self.mode.zero);
                p.text(
                    Pos2::new(plot.left(), full.bottom() - 18.0),
                    egui::Align2::LEFT_TOP,
                    format!(
                        "pole {fph:.0} Hz r{fpr:.3}   ·   zero {fzh:.0} Hz r{fzr:.3}   ·   \
                         projection loss: complex {:.1e} / impulse {:.1e}   ·   {}",
                        self.loss.0, self.loss.1, self.status
                    ),
                    egui::FontId::monospace(11.0),
                    Color32::from_rgb(120, 140, 132),
                );
            });
    }
}

fn main() -> eframe::Result<()> {
    eframe::run_native(
        "FORGE ZERO",
        eframe::NativeOptions {
            viewport: egui::ViewportBuilder::default().with_inner_size([980.0, 560.0]),
            ..Default::default()
        },
        Box::new(|_| Ok(Box::new(Zero::new()))),
    )
}
