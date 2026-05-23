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
        let capturing = self.capture.is_some();

        egui::TopBottomPanel::top("forge_header")
            .frame(field_frame(20.0, 8.0))
            .show(ctx, |ui| self.header(ui));

        if !capturing {
            egui::TopBottomPanel::bottom("forge_controls")
                .frame(field_frame(12.0, 18.0))
                .show(ctx, |ui| self.transport(ui));
        }

        egui::CentralPanel::default()
            .frame(field_frame(4.0, 4.0))
            .show(ctx, |ui| {
                if capturing {
                    self.capture_stage(ui);
                } else {
                    // THE SHAPE stays the hero up top; the Morph×Q authoring pad
                    // sits beneath it (drop a sound into each corner, drag the
                    // puck to roam the 4-corner space).
                    let total = ui.available_height();
                    let shape_h = (total * 0.58).max(150.0);
                    self.shape_stage(ui, shape_h);
                    ui.add_space(6.0);
                    let pad_h = (total - shape_h - 12.0).max(150.0);
                    self.morph_q_pad(ui, pad_h);
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
                    let target = self.next_empty_anchor();
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

            // green TARGET(s) — peak-aligned to the fit; each corner's opacity
            // follows its bilinear weight at the puck, so the targets crossfade
            // as you roam the Morph×Q pad.
            let loaded = self.anchor_audio.iter().filter(|a| a.is_some()).count();
            let m = self.preview_morph as f64;
            let q = self.preview_q as f64;
            let weight = [
                (1.0 - m) * (1.0 - q), // M0_Q0
                m * (1.0 - q),         // M100_Q0
                (1.0 - m) * q,         // M0_Q100
                m * q,                 // M100_Q100
            ];
            for slot in 0..4 {
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
                let alpha = if loaded > 1 {
                    (45.0 + 175.0 * weight[slot]) as u8
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
                "DROP A SOUND INTO EACH CORNER",
                FontId::new(14.0, FontFamily::Proportional),
                theme::INK_SOFT,
            );
        }
    }

    // ── Morph × Q pad — the 2-D authoring surface ─────────────────────────────
    // Four corners (drop a sound into each), one puck you drag to roam the
    // Morph (X) × Q (Y) space. THE SHAPE above shows the body at the puck.
    fn morph_q_pad(&mut self, ui: &mut egui::Ui, height: f32) {
        // corner loader chips — M0·Q0  M100·Q0  M0·Q100  M100·Q100
        ui.horizontal(|ui| {
            let chip_w = (ui.available_width() - 24.0) / 4.0;
            for slot in 0..4 {
                self.corner_chip(ui, slot, chip_w);
            }
        });
        ui.add_space(4.0);

        let pad_h = (height - 42.0).max(90.0);
        let (resp, painter) =
            ui.allocate_painter(Vec2::new(ui.available_width(), pad_h), Sense::click_and_drag());
        let full = resp.rect;
        let side = full.height().min(full.width()).max(80.0);
        let pad = egui::Rect::from_center_size(full.center(), Vec2::splat(side));

        // field + frame + mid crosshairs
        painter.rect_filled(pad, egui::Rounding::same(3.0), theme::PAPER_DIM);
        painter.rect_stroke(pad, egui::Rounding::same(3.0), Stroke::new(1.0, theme::INK_FAINT));
        painter.line_segment(
            [Pos2::new(pad.center().x, pad.top()), Pos2::new(pad.center().x, pad.bottom())],
            Stroke::new(1.0, theme::with_alpha(theme::INK_FAINT, 110)),
        );
        painter.line_segment(
            [Pos2::new(pad.left(), pad.center().y), Pos2::new(pad.right(), pad.center().y)],
            Stroke::new(1.0, theme::with_alpha(theme::INK_FAINT, 110)),
        );
        painter.text(
            Pos2::new(pad.center().x, pad.bottom() + 1.0),
            Align2::CENTER_TOP,
            "MORPH →",
            FontId::new(9.0, FontFamily::Monospace),
            theme::INK_SOFT,
        );
        painter.text(
            Pos2::new(pad.left() - 3.0, pad.center().y),
            Align2::RIGHT_CENTER,
            "Q ↓",
            FontId::new(9.0, FontFamily::Monospace),
            theme::INK_SOFT,
        );

        // corner status dots — TL=M0·Q0, TR=M100·Q0, BL=M0·Q100, BR=M100·Q100
        for (pos, slot, align) in [
            (pad.left_top(), 0usize, Align2::LEFT_TOP),
            (pad.right_top(), 1, Align2::RIGHT_TOP),
            (pad.left_bottom(), 2, Align2::LEFT_BOTTOM),
            (pad.right_bottom(), 3, Align2::RIGHT_BOTTOM),
        ] {
            let inset = Vec2::new(
                if align.x() == Align::Min { 8.0 } else { -8.0 },
                if align.y() == Align::Min { 8.0 } else { -8.0 },
            );
            painter.circle_filled(pos + inset, 3.5, self.corner_dot(slot));
        }

        // drag anywhere on the pad to move the puck
        if (resp.dragged() || resp.clicked()) && pad.width() > 1.0 && pad.height() > 1.0 {
            if let Some(p) = resp.interact_pointer_pos() {
                self.preview_morph = ((p.x - pad.left()) / pad.width()).clamp(0.0, 1.0);
                self.preview_q = ((p.y - pad.top()) / pad.height()).clamp(0.0, 1.0);
            }
        }

        // puck — vermillion ring once the M0·Q0 anchor exists (morph is live)
        let px = egui::lerp(pad.left()..=pad.right(), self.preview_morph);
        let py = egui::lerp(pad.top()..=pad.bottom(), self.preview_q);
        let ring = if self.corner_slots[0].is_some() {
            theme::VERM
        } else {
            theme::INK_FAINT
        };
        painter.circle_filled(Pos2::new(px, py), 6.0, theme::INK);
        painter.circle_stroke(Pos2::new(px, py), 7.5, Stroke::new(2.0, ring));
    }

    /// One corner loader: "M0·Q0" + the sound's name (or + ADD), tinted by fit
    /// quality. Click loads/replaces that corner; if a sound is loaded but its
    /// fit needs a cleaner slice, it opens INSPECT on that corner instead.
    fn corner_chip(&mut self, ui: &mut egui::Ui, slot: usize, width: f32) {
        let loaded = self.anchor_audio[slot].is_some();
        // Resolve everything we need to a bool/owned value so no borrow of
        // self.corner_slots is held across the &mut self click handlers below.
        let (line2, col, assigned) = match self.corner_slots[slot].as_ref() {
            Some(s) if matches!(s.quality, crate::dsp::FitQuality::Ready) => {
                (trim_label(&s.source, 12), theme::INK, true)
            }
            Some(s) => (trim_label(&s.source, 12), theme::CAUTION, true),
            None if loaded => ("needs slice".to_owned(), theme::CAUTION, false),
            None => ("+ ADD".to_owned(), theme::INK_SOFT, false),
        };
        let text = format!("{}\n{}", crate::CORNER_LABELS[slot], line2);
        let btn = egui::Button::new(RichText::new(text).color(col).size(10.0))
            .fill(theme::PAPER_LOW)
            .stroke(Stroke::new(1.0, theme::INK_FAINT))
            .min_size(Vec2::new(width.max(56.0), 34.0))
            .rounding(2.0);
        if ui.add(btn).clicked() {
            if loaded && !assigned {
                self.inspect_open = true;
                self.inspect_anchor = slot;
            } else {
                self.load_anchor_button(slot);
            }
        }
    }

    /// The status colour for a corner: green Ready, amber loaded-but-not-clean,
    /// faint empty.
    fn corner_dot(&self, slot: usize) -> Color32 {
        match self.corner_slots[slot].as_ref() {
            Some(s) if matches!(s.quality, crate::dsp::FitQuality::Ready) => theme::TARGET,
            Some(_) => theme::CAUTION,
            None if self.anchor_audio[slot].is_some() => theme::CAUTION,
            None => theme::INK_FAINT,
        }
    }

    // ── Transport ──────────────────────────────────────────────────────────────
    fn transport(&mut self, ui: &mut egui::Ui) {
        let play_ready = self.stage_corner().is_some();
        let save_ready = self.corner_slots.iter().all(|s| s.is_some());
        let playing = self.audio.as_ref().map(|a| a.is_playing()).unwrap_or(false);

        ui.horizontal(|ui| {
            let label = if playing { "STOP" } else { "PLAY" };
            if solid_button(ui, label, play_ready).clicked() {
                if let Some(a) = &self.audio {
                    a.set_playing(!playing);
                }
            }
            ui.add_space(12.0);
            if outline_button(ui, "SAVE", save_ready).clicked() {
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
