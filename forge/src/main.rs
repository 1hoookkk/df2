//! Filter Factory — the whole app, one file.
//!
//! First principles: the product is a 4-corner Morph×Q filter. Authoring is just
//! defining the four corners. So the entire job here is —
//!
//!   drop a sound into each corner → fit it to six biquads → roam morph×Q → hear it.
//!
//! No assign step, no quality gates, no inspect room. A dropped sound *is* that
//! corner. If the result is wrong, change the source. The fit (deterministic ARMA
//! pole-zero, in trench-core) and the runtime interpolation are the engine; this
//! file is only the surface and the glue.

#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]

mod audio;
mod capture;
mod dsp;

use std::path::PathBuf;
use std::time::Instant;

use eframe::egui;
use egui::{
    Align, Align2, Color32, FontFamily, FontId, Layout, Pos2, RichText, Sense, Shape, Stroke, Vec2,
};
use trench_core::cartridge::CornerData;

use dsp::{
    body_preview, condition_fit_window, corner_to_biquads, detect_onset, display_name, fit_window,
    is_passthrough, load_wav_as_mono_f64, magnitude_response, samples_for_ms, source_envelope,
    stage_frequency, trim_label, AUTHORING_RATE, DEFAULT_WINDOW_MS,
};

// ── palette — a dark instrument scope ─────────────────────────────────────────
const FIELD: Color32 = Color32::from_rgb(14, 16, 15);
const PANEL: Color32 = Color32::from_rgb(36, 40, 37);
const INK: Color32 = Color32::from_rgb(216, 221, 212);
const INK_SOFT: Color32 = Color32::from_rgb(130, 140, 130);
const FAINT: Color32 = Color32::from_rgb(58, 65, 60);
const VERM: Color32 = Color32::from_rgb(228, 78, 46);
const GREEN: Color32 = Color32::from_rgb(74, 222, 128); // the source you dropped
const AMBER: Color32 = Color32::from_rgb(232, 150, 58); // the fit the six actors built
const ACTOR_COL: [Color32; 6] = [
    Color32::from_rgb(86, 156, 232),
    Color32::from_rgb(58, 200, 184),
    Color32::from_rgb(150, 120, 232),
    Color32::from_rgb(224, 196, 76),
    Color32::from_rgb(240, 110, 70),
    Color32::from_rgb(228, 96, 168),
];
const ACTOR_NAMES: [&str; 6] = ["ROOT", "BODY", "MOUTH", "SCAR", "EDGE", "RIP"];
/// Corners in PackedCorners index order: TL, TR, BL, BR of the pad.
const CORNERS: [&str; 4] = ["M0·Q0", "M100·Q0", "M0·Q100", "M100·Q100"];

fn alpha(c: Color32, a: u8) -> Color32 {
    Color32::from_rgba_unmultiplied(c.r(), c.g(), c.b(), a)
}

// ── one authored corner ───────────────────────────────────────────────────────
struct Corner {
    name: String,
    fit: CornerData,
    /// the dropped sound's own spectral envelope `[freq, dB]`, for the green ghost
    src_db: Vec<[f64; 2]>,
}

// ── state ─────────────────────────────────────────────────────────────────────
struct App {
    corners: [Option<Corner>; 4],
    morph: f32,   // 0 = M0 (left), 1 = M100 (right)
    q: f32,       // 0 = Q0 (top), 1 = Q100 (bottom) — the puck position
    q_sharp: f32, // how much sharper the high-Q row is (auto-derived from Q0)
    audio: Option<audio::Audio>,
    capture: Option<capture::Capture>,
    capture_target: usize,
    start: Instant,
    status: String,
    save_status: String,
    // recompute the 540-bin response only when the shown corner actually changes
    view_corner: Option<CornerData>,
    view_fit: Vec<[f64; 2]>,
}

impl Default for App {
    fn default() -> Self {
        Self {
            corners: core::array::from_fn(|_| None),
            morph: 0.5,
            q: 0.5,
            q_sharp: 0.6,
            audio: audio::start(),
            capture: None,
            capture_target: 0,
            start: Instant::now(),
            status: String::new(),
            save_status: String::new(),
            view_corner: None,
            view_fit: Vec::new(),
        }
    }
}

impl App {
    fn elapsed(&self) -> f32 {
        self.start.elapsed().as_secs_f32()
    }

    fn next_empty(&self) -> usize {
        self.corners.iter().position(|c| c.is_none()).unwrap_or(0)
    }

    fn count(&self) -> usize {
        self.corners.iter().flatten().count()
    }

    fn pick_file(&mut self, i: usize) {
        if let Some(path) = rfd::FileDialog::new()
            .add_filter("Wave Audio", &["wav"])
            .pick_file()
        {
            self.load(i, path);
        }
    }

    fn load(&mut self, i: usize, path: PathBuf) {
        match load_wav_as_mono_f64(&path) {
            Ok((samples, sr)) => {
                self.corners[i] = Some(fit_corner(&samples, sr, display_name(&path)));
                self.view_corner = None; // force a redraw
            }
            Err(e) => self.status = format!("load failed: {e}"),
        }
    }

    fn start_capture(&mut self, i: usize) {
        match capture::Capture::start() {
            Ok(cap) => {
                self.capture = Some(cap);
                self.capture_target = i;
            }
            Err(e) => self.status = format!("capture failed: {e}"),
        }
    }

    fn finish_capture(&mut self) {
        let Some(cap) = self.capture.take() else {
            return;
        };
        let i = self.capture_target;
        let samples = cap.drain_mono_f64();
        let sr = cap.sample_rate;
        drop(cap);
        if samples.len() < 64 {
            self.status = "capture produced no audio — was something playing?".to_owned();
            return;
        }
        self.corners[i] = Some(fit_corner(&samples, sr, format!("capture {}", CORNERS[i])));
        self.view_corner = None;
    }

    /// The four corners assembled into a coherent body. M0·Q0 (or the first loaded
    /// corner) is the actor anchor; the others are re-indexed to it so the
    /// index-paired interpolation glides. The **high-Q row is auto-derived** from
    /// the low-Q row by raising pole radius (`q_sharp`) — that's what Q is — unless
    /// you drop a different source into a Q100 corner to override it.
    fn body(&self) -> Option<[CornerData; 4]> {
        let anchor_src = self.corners[0]
            .as_ref()
            .or_else(|| self.corners.iter().flatten().next())?;
        let anchor = dsp::canonical_anchor(&anchor_src.fit, AUTHORING_RATE);
        let aligned = |i: usize| {
            self.corners[i]
                .as_ref()
                .map(|c| dsp::align_to_anchor(&anchor, &c.fit, AUTHORING_RATE))
        };
        let m0 = aligned(0).unwrap_or(anchor);
        let m100 = aligned(1).unwrap_or(anchor);
        let amt = self.q_sharp as f64;
        let m0_q100 = aligned(2).unwrap_or_else(|| dsp::sharpen_corner(&m0, amt, AUTHORING_RATE));
        let m100_q100 = aligned(3).unwrap_or_else(|| dsp::sharpen_corner(&m100, amt, AUTHORING_RATE));
        Some([m0, m100, m0_q100, m100_q100])
    }

    /// The corner the scope draws and the audio plays: the body at the puck.
    fn shown(&self) -> Option<CornerData> {
        Some(body_preview(&self.body()?, self.morph, self.q))
    }

    fn reset(&mut self) {
        self.corners = core::array::from_fn(|_| None);
        self.morph = 0.5;
        self.q = 0.5;
        self.save_status.clear();
        self.view_corner = None;
        if let Some(a) = &self.audio {
            a.set_playing(false);
        }
    }

    fn save(&mut self) {
        let Some(body) = self.body() else {
            self.save_status = "drop a sound first".to_owned();
            return;
        };
        let json = export_body(&body, &self.corners);
        let home = std::env::var("USERPROFILE")
            .or_else(|_| std::env::var("HOME"))
            .unwrap_or_default();
        let path = PathBuf::from(home)
            .join("Documents")
            .join("TRENCH")
            .join("authoring_slot.json");
        if let Some(p) = path.parent() {
            let _ = std::fs::create_dir_all(p);
        }
        self.save_status = match std::fs::write(&path, json) {
            Ok(_) => "saved to authoring slot".to_owned(),
            Err(e) => format!("save failed: {e}"),
        };
    }

    fn take_drops(&mut self, ctx: &egui::Context) {
        let dropped = ctx.input(|i| i.raw.dropped_files.clone());
        for f in dropped {
            if let Some(path) = f.path {
                let i = self.next_empty();
                self.load(i, path);
                break;
            }
        }
    }

    fn push_audio(&mut self) {
        if let Some(a) = &self.audio {
            if let Some(c) = self.shown() {
                a.set_target(corner_to_biquads(&c));
            }
        }
    }
}

/// Window a recorded sound around its onset and fit it to one corner.
fn fit_corner(samples: &[f64], sr: f64, name: String) -> Corner {
    let onset = detect_onset(samples, sr);
    let wlen = samples_for_ms(sr, DEFAULT_WINDOW_MS);
    let start = onset.min(samples.len().saturating_sub(wlen));
    let end = (start + wlen).min(samples.len());
    let win = condition_fit_window(&samples[start..end], false);
    Corner {
        fit: fit_window(&win, sr),
        src_db: source_envelope(&win, sr),
        name,
    }
}

fn export_body(body: &[CornerData; 4], corners: &[Option<Corner>; 4]) -> String {
    let name = {
        let names: Vec<&str> = corners
            .iter()
            .filter_map(|c| c.as_ref().map(|c| c.name.as_str()))
            .collect();
        names.join(" · ")
    };
    let labels = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];
    let keyframes: Vec<_> = labels
        .iter()
        .zip(body)
        .map(|(label, corner)| {
            let mut stages: Vec<_> = corner
                .iter()
                .map(|s| {
                    serde_json::json!({"c0":s[0],"c1":s[1],"c2":s[2],"c3":s[3],"c4":s[4]})
                })
                .collect();
            for _ in 6..12 {
                stages.push(serde_json::json!({"c0":2.0,"c1":1.0,"c2":2.0,"c3":1.0,"c4":1.0}));
            }
            serde_json::json!({"label": label, "boost": 1.0, "stages": stages})
        })
        .collect();
    serde_json::json!({
        "format": "compiled-v1",
        "name": name,
        "sampleRate": AUTHORING_RATE,
        "stages": 12,
        "keyframes": keyframes,
    })
    .to_string()
}

// ── UI ──────────────────────────────────────────────────────────────────────
impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        if self
            .capture
            .as_ref()
            .map(|c| c.elapsed_secs() >= capture::CAPTURE_SECS)
            .unwrap_or(false)
        {
            self.finish_capture();
        }
        self.take_drops(ctx);
        self.push_audio();

        let capturing = self.capture.is_some();
        egui::TopBottomPanel::top("head")
            .frame(frame(18.0, 8.0))
            .show(ctx, |ui| self.header(ui));
        if !capturing {
            egui::TopBottomPanel::bottom("foot")
                .frame(frame(12.0, 16.0))
                .show(ctx, |ui| self.transport(ui));
        }
        egui::CentralPanel::default()
            .frame(frame(6.0, 6.0))
            .show(ctx, |ui| {
                if capturing {
                    self.capture_view(ui);
                } else {
                    let h = ui.available_height();
                    let shape_h = (h * 0.58).max(150.0);
                    self.shape(ui, shape_h);
                    ui.add_space(6.0);
                    self.pad(ui, (h - shape_h - 12.0).max(150.0));
                }
            });
        ctx.request_repaint_after(std::time::Duration::from_millis(16));
    }
}

impl App {
    fn header(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            ui.label(RichText::new("FILTER FACTORY").color(INK).size(16.0).strong());
            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                if link(ui, "CAPTURE").clicked() {
                    let i = self.next_empty();
                    self.start_capture(i);
                }
                if !self.status.is_empty() {
                    ui.add_space(14.0);
                    ui.label(RichText::new(&self.status).color(INK_SOFT).size(10.0));
                }
            });
        });
    }

    // THE SHAPE — green source(s) read against the amber fit; six named actors ride
    // along. The one thing to watch.
    fn shape(&mut self, ui: &mut egui::Ui, height: f32) {
        let (resp, p) = ui.allocate_painter(Vec2::new(ui.available_width(), height), Sense::hover());
        let rect = resp.rect;
        let inner = rect.shrink2(Vec2::new(14.0, 26.0));
        let base = inner.bottom();
        let t = self.elapsed();
        let breath = 1.0 + 0.02 * (t * 1.1).sin();
        let meter = self.audio.as_ref().filter(|a| a.is_playing()).map(|a| a.meter()).unwrap_or(0.0);
        let amp = (breath + meter * 0.14) as f32;

        let nyq = (AUTHORING_RATE * 0.5).max(10_000.0);
        let span = (nyq / 20.0).ln();
        let x_for = |f: f64| egui::lerp(inner.left()..=inner.right(), ((f / 20.0).max(1.0).ln() / span).clamp(0.0, 1.0) as f32);
        let y_for = |db: f64| egui::lerp(inner.bottom()..=inner.top(), (((db as f32) + 48.0) / 72.0).clamp(0.0, 1.0));

        // grid
        for &(f, lbl) in &[(100.0, "100"), (1_000.0, "1k"), (10_000.0, "10k")] {
            let x = x_for(f);
            p.line_segment([Pos2::new(x, inner.top()), Pos2::new(x, base)], Stroke::new(1.0, FAINT));
            p.text(Pos2::new(x, base + 8.0), Align2::CENTER_TOP, lbl, FontId::new(10.0, FontFamily::Monospace), INK_SOFT);
        }
        for frac in [0.34_f32, 0.67] {
            let y = egui::lerp(inner.top()..=base, frac);
            p.line_segment([Pos2::new(inner.left(), y), Pos2::new(inner.right(), y)], Stroke::new(1.0, alpha(FAINT, 60)));
        }

        if let Some(c) = self.shown() {
            if self.view_corner != Some(c) {
                self.view_fit = magnitude_response(&c, AUTHORING_RATE);
                self.view_corner = Some(c);
            }
            let fit_peak = self.view_fit.iter().map(|[_, d]| *d).fold(f64::NEG_INFINITY, f64::max);

            // amber fit fill + line
            let top: Vec<Pos2> = self.view_fit.iter().map(|[f, d]| Pos2::new(x_for(*f), y_for(*d * amp as f64))).collect();
            let mut mesh = egui::Mesh::default();
            let fill = alpha(AMBER, 34);
            for q in &top {
                mesh.colored_vertex(*q, fill);
                mesh.colored_vertex(Pos2::new(q.x, base), fill);
            }
            for i in 0..top.len().saturating_sub(1) {
                let a = (2 * i) as u32;
                mesh.add_triangle(a, a + 1, a + 2);
                mesh.add_triangle(a + 1, a + 3, a + 2);
            }
            p.add(Shape::mesh(mesh));

            // green source ghosts — opacity follows the bilinear weight at the puck
            let m = self.morph as f64;
            let qq = self.q as f64;
            let w = [(1.0 - m) * (1.0 - qq), m * (1.0 - qq), (1.0 - m) * qq, m * qq];
            let multi = self.count() > 1;
            for (i, corner) in self.corners.iter().enumerate() {
                let Some(corner) = corner else { continue };
                if corner.src_db.len() < 2 {
                    continue;
                }
                let src_peak = corner.src_db.iter().map(|[_, d]| *d).fold(f64::NEG_INFINITY, f64::max);
                if !src_peak.is_finite() || !fit_peak.is_finite() {
                    continue;
                }
                let off = fit_peak - src_peak;
                let a = if multi { (45.0 + 175.0 * w[i]) as u8 } else { 210 };
                let pts: Vec<Pos2> = corner.src_db.iter().map(|[f, d]| Pos2::new(x_for(*f), y_for((*d + off) * amp as f64))).collect();
                p.add(Shape::line(pts, Stroke::new(2.0, alpha(GREEN, a))));
            }

            p.add(Shape::line(top, Stroke::new(2.4, AMBER)));

            // six actors as named tick markers
            for (i, stage) in c.iter().enumerate().take(6) {
                if is_passthrough(stage) {
                    continue;
                }
                let f = stage_frequency(stage, AUTHORING_RATE);
                if !f.is_finite() || f < 20.0 {
                    continue;
                }
                let x = x_for(f);
                let col = ACTOR_COL[i];
                p.line_segment([Pos2::new(x, inner.top() + 10.0), Pos2::new(x, base)], Stroke::new(1.0, alpha(col, 70)));
                p.circle_filled(Pos2::new(x, inner.top() + 8.0), 3.5, col);
                p.text(Pos2::new(x, inner.top() - 3.0), Align2::CENTER_BOTTOM, ACTOR_NAMES[i], FontId::new(9.0, FontFamily::Proportional), alpha(col, 220));
            }
        } else {
            p.text(rect.center(), Align2::CENTER_CENTER, "DROP A SOUND INTO EACH CORNER", FontId::new(14.0, FontFamily::Proportional), INK_SOFT);
        }
        p.line_segment([Pos2::new(inner.left(), base), Pos2::new(inner.right(), base)], Stroke::new(1.5, FAINT));
    }

    // Morph × Q pad — drop a sound into each corner, drag the puck to roam.
    fn pad(&mut self, ui: &mut egui::Ui, height: f32) {
        ui.horizontal(|ui| {
            let w = (ui.available_width() - 24.0) / 4.0;
            for i in 0..4 {
                self.chip(ui, i, w);
            }
        });
        ui.add_space(4.0);

        let pad_h = (height - 42.0).max(90.0);
        let (resp, p) = ui.allocate_painter(Vec2::new(ui.available_width(), pad_h), Sense::click_and_drag());
        let full = resp.rect;
        let side = full.height().min(full.width()).max(80.0);
        let pad = egui::Rect::from_center_size(full.center(), Vec2::splat(side));

        p.rect_filled(pad, egui::Rounding::same(3.0), PANEL);
        p.rect_stroke(pad, egui::Rounding::same(3.0), Stroke::new(1.0, FAINT));
        p.line_segment([Pos2::new(pad.center().x, pad.top()), Pos2::new(pad.center().x, pad.bottom())], Stroke::new(1.0, alpha(FAINT, 110)));
        p.line_segment([Pos2::new(pad.left(), pad.center().y), Pos2::new(pad.right(), pad.center().y)], Stroke::new(1.0, alpha(FAINT, 110)));
        p.text(Pos2::new(pad.center().x, pad.bottom() + 1.0), Align2::CENTER_TOP, "MORPH →", FontId::new(9.0, FontFamily::Monospace), INK_SOFT);
        p.text(Pos2::new(pad.left() - 3.0, pad.center().y), Align2::RIGHT_CENTER, "Q ↓", FontId::new(9.0, FontFamily::Monospace), INK_SOFT);

        for (pos, i, ax, ay) in [
            (pad.left_top(), 0usize, 8.0, 8.0),
            (pad.right_top(), 1, -8.0, 8.0),
            (pad.left_bottom(), 2, 8.0, -8.0),
            (pad.right_bottom(), 3, -8.0, -8.0),
        ] {
            let dot = if self.corners[i].is_some() { GREEN } else { FAINT };
            p.circle_filled(pos + Vec2::new(ax, ay), 3.5, dot);
        }

        if (resp.dragged() || resp.clicked()) && pad.width() > 1.0 {
            if let Some(pt) = resp.interact_pointer_pos() {
                self.morph = ((pt.x - pad.left()) / pad.width()).clamp(0.0, 1.0);
                self.q = ((pt.y - pad.top()) / pad.height()).clamp(0.0, 1.0);
                self.view_corner = None;
            }
        }
        let px = egui::lerp(pad.left()..=pad.right(), self.morph);
        let py = egui::lerp(pad.top()..=pad.bottom(), self.q);
        let ring = if self.count() > 0 { VERM } else { FAINT };
        p.circle_filled(Pos2::new(px, py), 6.0, INK);
        p.circle_stroke(Pos2::new(px, py), 7.5, Stroke::new(2.0, ring));
    }

    fn chip(&mut self, ui: &mut egui::Ui, i: usize, w: f32) {
        let line2 = match &self.corners[i] {
            Some(c) => trim_label(&c.name, 12),
            None if i >= 2 => "auto".to_owned(), // high-Q corner auto-derived from low-Q
            None => "+ ADD".to_owned(),
        };
        let col = if self.corners[i].is_some() { INK } else { INK_SOFT };
        let btn = egui::Button::new(RichText::new(format!("{}\n{}", CORNERS[i], line2)).color(col).size(10.0))
            .fill(PANEL)
            .stroke(Stroke::new(1.0, FAINT))
            .min_size(Vec2::new(w.max(56.0), 34.0))
            .rounding(2.0);
        if ui.add(btn).clicked() {
            self.pick_file(i);
        }
    }

    fn transport(&mut self, ui: &mut egui::Ui) {
        let ready = self.count() > 0;
        let playing = self.audio.as_ref().map(|a| a.is_playing()).unwrap_or(false);
        ui.horizontal(|ui| {
            if button(ui, if playing { "STOP" } else { "PLAY" }, true, ready).clicked() {
                if let Some(a) = &self.audio {
                    a.set_playing(!playing);
                }
            }
            ui.add_space(10.0);
            if button(ui, "SAVE", false, ready).clicked() {
                self.save();
            }
            ui.add_space(18.0);
            ui.label(RichText::new("Q").color(INK_SOFT).size(11.0));
            let mut qs = self.q_sharp;
            if ui
                .add_sized([150.0, 18.0], egui::Slider::new(&mut qs, 0.0..=1.0).show_value(false))
                .changed()
            {
                self.q_sharp = qs;
                self.view_corner = None;
            }
            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                if link(ui, "RESET").clicked() {
                    self.reset();
                }
                if !self.save_status.is_empty() {
                    ui.add_space(14.0);
                    ui.label(RichText::new(&self.save_status).color(INK_SOFT).size(10.0));
                }
            });
        });
    }

    fn capture_view(&mut self, ui: &mut egui::Ui) {
        let (elapsed, total) = self
            .capture
            .as_ref()
            .map(|c| (c.elapsed_secs(), capture::CAPTURE_SECS))
            .unwrap_or((0.0, capture::CAPTURE_SECS));
        let (resp, p) = ui.allocate_painter(Vec2::new(ui.available_width(), ui.available_height() - 18.0), Sense::hover());
        let r = resp.rect;
        let pulse = (elapsed * 2.0) as u32 % 2 == 0;
        p.circle_filled(Pos2::new(r.center().x, r.center().y - 36.0), 10.0, if pulse { VERM } else { alpha(VERM, 70) });
        p.text(r.center(), Align2::CENTER_CENTER, "PLAY YOUR SOUND IN THE DAW NOW", FontId::new(15.0, FontFamily::Proportional), INK);
        p.text(Pos2::new(r.center().x, r.center().y + 26.0), Align2::CENTER_CENTER, format!("{elapsed:.1}s / {total:.0}s"), FontId::new(11.0, FontFamily::Monospace), INK_SOFT);
        ui.with_layout(Layout::top_down(Align::Center), |ui| {
            if link(ui, "STOP").clicked() {
                self.finish_capture();
            }
        });
    }
}

// ── small widgets ─────────────────────────────────────────────────────────────
fn frame(top: f32, bottom: f32) -> egui::Frame {
    egui::Frame::none().fill(FIELD).inner_margin(egui::Margin { left: 40.0, right: 40.0, top, bottom })
}

fn link(ui: &mut egui::Ui, label: &str) -> egui::Response {
    ui.add(egui::Button::new(RichText::new(label).color(INK_SOFT).size(11.0)).fill(Color32::TRANSPARENT).frame(false))
}

fn button(ui: &mut egui::Ui, label: &str, solid: bool, enabled: bool) -> egui::Response {
    let (fill, fg) = match (solid, enabled) {
        (true, true) => (VERM, FIELD),
        (true, false) => (PANEL, FAINT),
        (false, true) => (Color32::TRANSPARENT, INK),
        (false, false) => (Color32::TRANSPARENT, FAINT),
    };
    let mut b = egui::Button::new(RichText::new(label).color(fg).size(14.0).strong())
        .fill(fill)
        .min_size(Vec2::new(104.0, 36.0))
        .rounding(2.0);
    if !solid {
        b = b.stroke(Stroke::new(1.5, fg));
    }
    ui.add_enabled(enabled, b)
}

// ── theme + entry ─────────────────────────────────────────────────────────────
fn install_theme(ctx: &egui::Context) {
    let mut fonts = egui::FontDefinitions::default();
    let read = |paths: &[&str]| -> Option<Vec<u8>> { paths.iter().find_map(|p| std::fs::read(p).ok()) };
    if let Some(b) = read(&["C:/Windows/Fonts/bahnschrift.ttf", "C:/Windows/Fonts/segoeui.ttf"]) {
        fonts.font_data.insert("disp".into(), egui::FontData::from_owned(b));
        fonts.families.entry(FontFamily::Proportional).or_default().insert(0, "disp".into());
    }
    if let Some(b) = read(&["C:/Windows/Fonts/CascadiaMono.ttf", "C:/Windows/Fonts/consola.ttf"]) {
        fonts.font_data.insert("mono".into(), egui::FontData::from_owned(b));
        fonts.families.entry(FontFamily::Monospace).or_default().insert(0, "mono".into());
    }
    ctx.set_fonts(fonts);

    let mut v = egui::Visuals::dark();
    v.panel_fill = FIELD;
    v.override_text_color = Some(INK);
    v.widgets.inactive.bg_fill = PANEL;
    v.widgets.inactive.weak_bg_fill = PANEL;
    v.widgets.hovered.bg_fill = PANEL;
    v.widgets.hovered.weak_bg_fill = PANEL;
    ctx.set_visuals(v);
}

fn main() -> eframe::Result<()> {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1_000.0, 800.0])
            .with_min_inner_size([820.0, 640.0])
            .with_title("Filter Factory")
            .with_drag_and_drop(true),
        ..Default::default()
    };
    eframe::run_native(
        "Filter Factory",
        options,
        Box::new(|cc| {
            install_theme(&cc.egui_ctx);
            Ok(Box::new(App::default()))
        }),
    )
}
