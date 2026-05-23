//! The product surface — a dark instrument scope. Pinned header + pinned
//! controls so nothing clips; THE SHAPE fills the middle and is the only thing
//! to watch. Drop two sounds, drag the rail from one to the other, PLAY · SAVE.
//! Dead simple to operate; everything technical lives behind INSPECT.

use eframe::egui;
use egui::{
    Align, Align2, Color32, FontFamily, FontId, Layout, Pos2, RichText, Sense, Shape, Stroke, Vec2,
};

use crate::dsp::{is_passthrough, magnitude_response, stage_frequency, trim_label};
use crate::{capture, theme, App};

impl App {
    pub fn show_product_surface(&mut self, ctx: &egui::Context) {
        let capturing = self.is_capturing(0) || self.is_capturing(1);

        egui::TopBottomPanel::top("forge_header")
            .frame(field_frame(20.0, 8.0))
            .show(ctx, |ui| self.header(ui));

        if !capturing {
            egui::TopBottomPanel::bottom("forge_controls")
                .frame(field_frame(12.0, 22.0))
                .show(ctx, |ui| {
                    self.morph_rail(ui);
                    ui.add_space(16.0);
                    self.transport(ui);
                });
        }

        egui::CentralPanel::default()
            .frame(field_frame(4.0, 4.0))
            .show(ctx, |ui| {
                if capturing {
                    self.capture_stage(ui);
                } else {
                    let h = ui.available_height();
                    self.shape_stage(ui, h);
                }
            });
    }

    // ── Header ───────────────────────────────────────────────────────────────
    fn header(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            ui.label(
                RichText::new("FILTER FACTORY")
                    .color(theme::INK)
                    .size(16.0)
                    .strong(),
            );
            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                if text_link(ui, "INSPECT", theme::INK_SOFT).clicked() {
                    self.inspect_open = true;
                }
                ui.add_space(18.0);
                if text_link(ui, "CAPTURE", theme::INK_SOFT).clicked() {
                    let target = if self.corner_slots[0].is_none() { 0 } else { 1 };
                    self.start_capture(target);
                }
                if !self.status.is_empty() {
                    ui.add_space(18.0);
                    ui.label(
                        RichText::new(&self.status)
                            .color(theme::INK_SOFT)
                            .size(10.0),
                    );
                }
            });
        });
    }

    // ── THE SHAPE — the one live element ──────────────────────────────────────
    // Phosphor-green TARGET (the sound you gave it) read against the amber FIT
    // (what the six actors built). It breathes with the audio and morphs as the
    // rail moves; the actors ride along as coloured markers.
    fn shape_stage(&mut self, ui: &mut egui::Ui, height: f32) {
        let (resp, painter) =
            ui.allocate_painter(Vec2::new(ui.available_width(), height), Sense::hover());
        let rect = resp.rect;
        let inner = rect.shrink2(Vec2::new(16.0, 28.0));

        let rate = self.internal_resample_rate as f64;
        let corner = self.stage_corner();

        // breathing + signal
        let t = self.elapsed();
        let breath = 1.0 + 0.02 * (t * 1.1).sin();
        let meter = self
            .audio
            .as_ref()
            .filter(|a| a.is_playing())
            .map(|a| a.meter())
            .unwrap_or(0.0);
        let amp = (breath + meter * 0.14) as f32;
        let intro = smoothstep((t / 0.6) as f32);
        let base_y = inner.bottom();

        // log-frequency x, dB y (−48..+24)
        let nyq = (rate * 0.5).max(10_000.0);
        let span = (nyq / 20.0).ln();
        let x_for = |f: f64| -> f32 {
            let tt = ((f / 20.0).max(1.0).ln() / span).clamp(0.0, 1.0) as f32;
            egui::lerp(inner.left()..=inner.right(), tt)
        };
        let y_for = |db: f64| -> f32 {
            let nn = (((db as f32) + 48.0) / 72.0).clamp(0.0, 1.0);
            egui::lerp(inner.bottom()..=inner.top(), nn)
        };

        // grid — faint, with sparse Hz labels so it reads as analyser gear
        for f in [200.0, 300.0, 500.0, 2_000.0, 3_000.0, 5_000.0] {
            let x = x_for(f);
            painter.line_segment(
                [Pos2::new(x, inner.top()), Pos2::new(x, base_y)],
                Stroke::new(1.0, theme::with_alpha(theme::INK_FAINT, 90)),
            );
        }
        for &(f, label) in &[(100.0, "100"), (1_000.0, "1k"), (10_000.0, "10k")] {
            let x = x_for(f);
            painter.line_segment(
                [Pos2::new(x, inner.top()), Pos2::new(x, base_y)],
                Stroke::new(1.0, theme::INK_FAINT),
            );
            painter.text(
                Pos2::new(x, base_y + 9.0),
                Align2::CENTER_TOP,
                label,
                FontId::new(10.0, FontFamily::Monospace),
                theme::INK_SOFT,
            );
        }
        for frac in [0.34_f32, 0.67] {
            let y = egui::lerp(inner.top()..=base_y, frac);
            painter.line_segment(
                [Pos2::new(inner.left(), y), Pos2::new(inner.right(), y)],
                Stroke::new(1.0, theme::with_alpha(theme::INK_FAINT, 60)),
            );
        }

        if let Some(c) = corner {
            // Recompute the 540-bin fit only when the staged corner changes.
            if self.view_corner != Some(c) {
                self.view_fit = magnitude_response(&c, rate);
                self.view_corner = Some(c);
            }
            let fit_peak = self
                .view_fit
                .iter()
                .map(|[_, d]| *d)
                .fold(f64::NEG_INFINITY, f64::max);

            // amber FIT curve + soft fill
            let mut top: Vec<Pos2> = Vec::with_capacity(self.view_fit.len());
            for [f, db] in self.view_fit.iter() {
                let x = x_for(*f);
                let y_full = y_for(*db * amp as f64);
                top.push(Pos2::new(x, base_y + (y_full - base_y) * intro));
            }
            let mut mesh = egui::Mesh::default();
            let fill = theme::with_alpha(theme::FIT, 34);
            for p in &top {
                mesh.colored_vertex(*p, fill);
                mesh.colored_vertex(Pos2::new(p.x, base_y), fill);
            }
            for i in 0..top.len().saturating_sub(1) {
                let a = (2 * i) as u32;
                mesh.add_triangle(a, a + 1, a + 2);
                mesh.add_triangle(a + 1, a + 3, a + 2);
            }
            painter.add(Shape::mesh(mesh));

            // green TARGET(s) — peak-aligned to the fit; alpha follows how close
            // the morph is to that end, so it crossfades as you drag the rail.
            let both = self.corner_slots[0].is_some() && self.corner_slots[1].is_some();
            for slot in 0..2 {
                let Some(a) = self.anchor_audio[slot].as_ref() else {
                    continue;
                };
                let src = &a.extraction.source_db;
                if src.len() < 2 {
                    continue;
                }
                let src_peak = src
                    .iter()
                    .map(|[_, d]| *d)
                    .fold(f64::NEG_INFINITY, f64::max);
                if !src_peak.is_finite() || !fit_peak.is_finite() {
                    continue;
                }
                let offset = fit_peak - src_peak;
                let prox = if slot == 0 {
                    1.0 - self.anchor_morph
                } else {
                    self.anchor_morph
                };
                let alpha = if both {
                    (50.0 + 165.0 * prox) as u8
                } else {
                    220
                };
                let pts: Vec<Pos2> = src
                    .iter()
                    .map(|[f, d]| {
                        let x = x_for(*f);
                        let y_full = y_for((*d + offset) * amp as f64);
                        Pos2::new(x, base_y + (y_full - base_y) * intro)
                    })
                    .collect();
                painter.add(Shape::line(
                    pts,
                    Stroke::new(2.0, theme::with_alpha(theme::TARGET, alpha)),
                ));
            }

            // amber FIT line on top (the hero)
            painter.add(Shape::line(top, Stroke::new(2.4, theme::FIT)));

            // actors — coloured markers that ride the morph (low→high = the order)
            for (i, stage) in c.iter().enumerate().take(6) {
                if is_passthrough(stage) {
                    continue;
                }
                let f = stage_frequency(stage, rate);
                if !f.is_finite() || f < 20.0 {
                    continue;
                }
                let x = x_for(f);
                let col = theme::ACTORS[i];
                painter.line_segment(
                    [Pos2::new(x, inner.top() + 10.0), Pos2::new(x, base_y)],
                    Stroke::new(1.0, theme::with_alpha(col, 70)),
                );
                painter.circle_filled(Pos2::new(x, inner.top() + 8.0), 3.5, col);
                painter.text(
                    Pos2::new(x, inner.top() - 3.0),
                    Align2::CENTER_BOTTOM,
                    theme::ACTOR_NAMES[i],
                    FontId::new(9.0, FontFamily::Proportional),
                    theme::with_alpha(col, 220),
                );
            }
        }

        // baseline shelf
        painter.line_segment(
            [
                Pos2::new(inner.left(), base_y),
                Pos2::new(inner.right(), base_y),
            ],
            Stroke::new(1.5, theme::INK_FAINT),
        );

        if corner.is_none() {
            painter.text(
                rect.center(),
                Align2::CENTER_CENTER,
                "DROP TWO SOUNDS — LOW AND HIGH",
                FontId::new(14.0, FontFamily::Proportional),
                theme::INK_SOFT,
            );
        }
    }

    // ── Morph rail — the 1-D A→B move ─────────────────────────────────────────
    fn morph_rail(&mut self, ui: &mut egui::Ui) {
        let ready = self.corner_slots[0].is_some() && self.corner_slots[1].is_some();
        let end_w = 150.0;

        ui.horizontal(|ui| {
            ui.allocate_ui_with_layout(
                Vec2::new(end_w, 52.0),
                Layout::top_down(Align::Min),
                |ui| self.rail_end(ui, 0, "LOW", false),
            );

            let track_w = (ui.available_width() - end_w).max(120.0);
            let (track, painter) = ui.allocate_painter(
                Vec2::new(track_w, 52.0),
                if ready {
                    Sense::click_and_drag()
                } else {
                    Sense::hover()
                },
            );
            let r = track.rect;
            let cy = r.center().y;
            let h = 8.0;
            let bar = egui::Rect::from_min_max(
                Pos2::new(r.left(), cy - h * 0.5),
                Pos2::new(r.right(), cy + h * 0.5),
            );
            painter.rect_filled(bar, egui::Rounding::same(2.0), theme::PAPER_LOW);

            if ready {
                let hx = r.left() + self.anchor_morph * r.width();
                let fill = egui::Rect::from_min_max(
                    Pos2::new(r.left(), cy - h * 0.5),
                    Pos2::new(hx, cy + h * 0.5),
                );
                painter.rect_filled(fill, egui::Rounding::same(2.0), theme::VERM);
                let s = 11.0;
                painter.add(egui::Shape::convex_polygon(
                    vec![
                        Pos2::new(hx, cy - s),
                        Pos2::new(hx + s * 0.72, cy),
                        Pos2::new(hx, cy + s),
                        Pos2::new(hx - s * 0.72, cy),
                    ],
                    theme::INK,
                    Stroke::new(2.0, theme::PAPER),
                ));
                if track.clicked() || track.dragged() {
                    if let Some(p) = track.interact_pointer_pos() {
                        self.anchor_morph = ((p.x - r.left()) / r.width()).clamp(0.0, 1.0);
                    }
                }
            } else {
                painter.text(
                    r.center(),
                    Align2::CENTER_CENTER,
                    "load both ends",
                    FontId::new(11.0, FontFamily::Proportional),
                    theme::INK_FAINT,
                );
            }

            ui.allocate_ui_with_layout(
                Vec2::new(end_w, 52.0),
                Layout::top_down(Align::Max),
                |ui| self.rail_end(ui, 1, "HIGH", true),
            );
        });
    }

    fn rail_end(&mut self, ui: &mut egui::Ui, anchor: usize, label: &str, right: bool) {
        let align = if right { Align::Max } else { Align::Min };
        ui.with_layout(Layout::top_down(align), |ui| {
            ui.label(RichText::new(label).color(theme::INK).size(13.0).strong());

            if let Some(slot) = self.corner_slots[anchor].as_ref() {
                let name = trim_label(&slot.source, 16);
                let bad = !matches!(slot.quality, crate::dsp::FitQuality::Ready);
                let color = if bad { theme::CAUTION } else { theme::INK_SOFT };
                if text_link(ui, &name, color).clicked() {
                    self.load_anchor_button(anchor);
                }
                let (tick, p) = ui.allocate_painter(Vec2::new(54.0, 4.0), Sense::hover());
                let tr = tick.rect;
                let x0 = if right { tr.right() - 38.0 } else { tr.left() };
                p.rect_filled(
                    egui::Rect::from_min_size(
                        Pos2::new(x0, tr.center().y - 1.0),
                        Vec2::new(38.0, 2.0),
                    ),
                    egui::Rounding::ZERO,
                    if bad { theme::CAUTION } else { theme::VERM },
                );
            } else if self.anchor_audio[anchor].is_some() {
                if text_link(ui, "needs a cleaner slice", theme::CAUTION).clicked() {
                    self.inspect_open = true;
                    self.inspect_anchor = anchor;
                }
            } else {
                // A clear, obvious load target — not a tiny text link.
                let add = egui::Button::new(
                    RichText::new("+ ADD SOUND").color(theme::INK).size(12.0).strong(),
                )
                .fill(theme::PAPER_LOW)
                .stroke(Stroke::new(1.0, theme::INK_FAINT))
                .min_size(Vec2::new(132.0, 30.0))
                .rounding(2.0);
                if ui.add(add).clicked() {
                    self.load_anchor_button(anchor);
                }
            }
        });
    }

    // ── Transport ──────────────────────────────────────────────────────────────
    fn transport(&mut self, ui: &mut egui::Ui) {
        let ready = self.corner_slots[0].is_some() && self.corner_slots[1].is_some();
        let playing = self.audio.as_ref().map(|a| a.is_playing()).unwrap_or(false);

        ui.horizontal(|ui| {
            let label = if playing { "STOP" } else { "PLAY" };
            if solid_button(ui, label, ready).clicked() {
                if let Some(a) = &self.audio {
                    a.set_playing(!playing);
                }
            }
            ui.add_space(12.0);
            if outline_button(ui, "SAVE", ready).clicked() {
                self.save_body();
            }

            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                if text_link(ui, "RESET", theme::INK_SOFT).clicked() {
                    self.reset_body();
                }
                if let Some(msg) = self.save_status.clone() {
                    ui.add_space(16.0);
                    ui.label(RichText::new(msg).color(theme::INK_SOFT).size(10.0));
                }
            });
        });
    }

    // ── Capturing overlay (DAW loopback) ───────────────────────────────────────
    fn capture_stage(&mut self, ui: &mut egui::Ui) {
        let (elapsed, total) = self
            .capture
            .as_ref()
            .map(|c| (c.elapsed_secs(), capture::CAPTURE_SECS))
            .unwrap_or((0.0, capture::CAPTURE_SECS));
        let frac = (elapsed / total).clamp(0.0, 1.0);

        let (resp, painter) = ui.allocate_painter(
            Vec2::new(ui.available_width(), ui.available_height() - 20.0),
            Sense::hover(),
        );
        let r = resp.rect;
        let pulse = (elapsed * 2.0) as u32 % 2 == 0;
        painter.circle_filled(
            Pos2::new(r.center().x, r.center().y - 40.0),
            10.0,
            if pulse {
                theme::VERM
            } else {
                theme::with_alpha(theme::VERM, 70)
            },
        );
        painter.text(
            r.center(),
            Align2::CENTER_CENTER,
            "PLAY YOUR SOUND IN THE DAW NOW",
            FontId::new(15.0, FontFamily::Proportional),
            theme::INK,
        );
        painter.text(
            Pos2::new(r.center().x, r.center().y + 28.0),
            Align2::CENTER_CENTER,
            format!("{:.1}s / {:.0}s", elapsed, total),
            FontId::new(11.0, FontFamily::Monospace),
            theme::INK_SOFT,
        );
        let pw = r.width() * 0.4;
        let x0 = r.center().x - pw * 0.5;
        let y = r.center().y + 52.0;
        painter.rect_filled(
            egui::Rect::from_min_size(Pos2::new(x0, y), Vec2::new(pw, 3.0)),
            egui::Rounding::ZERO,
            theme::PAPER_LOW,
        );
        painter.rect_filled(
            egui::Rect::from_min_size(Pos2::new(x0, y), Vec2::new(pw * frac, 3.0)),
            egui::Rounding::ZERO,
            theme::VERM,
        );

        ui.with_layout(Layout::top_down(Align::Center), |ui| {
            if text_link(ui, "STOP", theme::INK_SOFT).clicked() {
                self.finish_capture();
            }
        });
    }
}

// ── Small widgets ──────────────────────────────────────────────────────────

fn field_frame(top: f32, bottom: f32) -> egui::Frame {
    egui::Frame::none()
        .fill(theme::PAPER)
        .inner_margin(egui::Margin {
            left: 46.0,
            right: 46.0,
            top,
            bottom,
        })
}

fn text_link(ui: &mut egui::Ui, label: &str, color: Color32) -> egui::Response {
    ui.add(
        egui::Button::new(RichText::new(label).color(color).size(11.0))
            .fill(Color32::TRANSPARENT)
            .frame(false),
    )
}

fn solid_button(ui: &mut egui::Ui, label: &str, enabled: bool) -> egui::Response {
    let fill = if enabled {
        theme::VERM
    } else {
        theme::PAPER_LOW
    };
    let fg = if enabled {
        theme::PAPER
    } else {
        theme::INK_FAINT
    };
    ui.add_enabled(
        enabled,
        egui::Button::new(RichText::new(label).color(fg).size(14.0).strong())
            .fill(fill)
            .min_size(Vec2::new(108.0, 38.0))
            .rounding(2.0),
    )
}

fn outline_button(ui: &mut egui::Ui, label: &str, enabled: bool) -> egui::Response {
    let fg = if enabled {
        theme::INK
    } else {
        theme::INK_FAINT
    };
    ui.add_enabled(
        enabled,
        egui::Button::new(RichText::new(label).color(fg).size(14.0).strong())
            .fill(Color32::TRANSPARENT)
            .stroke(Stroke::new(1.5, fg))
            .min_size(Vec2::new(96.0, 38.0))
            .rounding(2.0),
    )
}

fn smoothstep(x: f32) -> f32 {
    let x = x.clamp(0.0, 1.0);
    x * x * (3.0 - 2.0 * x)
}
