//! The technical back room — opened only via INSPECT. Deliberately spare: load a
//! sound, choose the slice, see the fit against the target, assign it to an end.
//! No numeric dumps, no z-plane, no code export — that was noise.

use eframe::egui;
use egui::RichText;
use egui_plot::{Legend, Line, Plot, PlotPoints, VLine};

use crate::dsp::{
    actor_magnitude_responses, display_name, downsample_plot, format_residual, magnitude_response,
    FitQuality,
};
use crate::theme::{self, with_alpha, CAUTION, INK, INK_FAINT, INK_SOFT};
use crate::App;

impl App {
    pub fn show_inspect_window(&mut self, ctx: &egui::Context) {
        let mut open = self.inspect_open;
        egui::Window::new("inspect")
            .open(&mut open)
            .default_size([920.0, 560.0])
            .resizable(true)
            .frame(egui::Frame::window(&ctx.style()).fill(theme::PAPER))
            .show(ctx, |ui| {
                ui.horizontal(|ui| {
                    ui.label(RichText::new("corner").color(INK_SOFT).size(11.0));
                    for slot in 0..4 {
                        if ui
                            .add(egui::SelectableLabel::new(
                                self.inspect_anchor == slot,
                                RichText::new(crate::CORNER_LABELS[slot]).color(INK).strong(),
                            ))
                            .clicked()
                        {
                            self.inspect_anchor = slot;
                        }
                    }
                });
                ui.separator();

                ui.columns(2, |columns| {
                    self.inspect_controls(&mut columns[0]);
                    self.inspect_waveform(&mut columns[1]);
                });
                ui.add_space(10.0);
                theme::panel_frame().show(ui, |ui| self.inspect_midpoint_scope(ui));
            });
        self.inspect_open = open;
    }

    fn inspect_controls(&mut self, ui: &mut egui::Ui) {
        let anchor = self.inspect_anchor;
        theme::panel_frame().show(ui, |ui| {
            let has_audio = self.anchor_audio[anchor].is_some();

            if ui
                .add(
                    egui::Button::new(RichText::new("LOAD FILE").color(INK).strong())
                        .min_size(egui::vec2(ui.available_width(), 32.0))
                        .fill(theme::PAPER_LOW),
                )
                .clicked()
            {
                self.load_anchor_button(anchor);
            }

            if let Some(state) = self.anchor_audio[anchor].as_ref() {
                ui.label(RichText::new(display_name(&state.path)).color(INK).size(11.0));
            }

            ui.add_space(8.0);

            let (max_start, cur_start) = if let Some(state) = self.anchor_audio[anchor].as_ref() {
                let max = state.buffer.len().saturating_sub(state.window_len) as f32;
                (max.max(1.0), state.start_trim as f32)
            } else {
                (1.0, 0.0)
            };
            let mut window_start = cur_start;
            if ui
                .add_enabled(
                    has_audio,
                    egui::Slider::new(&mut window_start, 0.0..=max_start)
                        .show_value(false)
                        .text("slice"),
                )
                .changed()
            {
                if let Some(state) = self.anchor_audio[anchor].as_mut() {
                    state.start_trim = window_start.round().max(0.0) as usize;
                }
                self.refit_anchor(anchor);
            }

            ui.add_space(8.0);

            // One line of truth: quality + residual. Nothing else.
            let quality = self.anchor_audio[anchor]
                .as_ref()
                .map(|s| s.extraction.quality)
                .unwrap_or(FitQuality::Blocked);
            let residual = self.anchor_audio[anchor]
                .as_ref()
                .map(|s| s.extraction.residual_db)
                .unwrap_or(f64::NAN);
            let qcol = quality_color(quality);
            ui.horizontal(|ui| {
                ui.label(RichText::new(quality_label(quality)).color(qcol).strong());
                ui.label(RichText::new(format_residual(residual)).color(qcol).monospace());
            });

            ui.add_space(8.0);

            ui.label(RichText::new("ASSIGN TO CORNER").color(INK_SOFT).size(10.0));
            for row in 0..2 {
                ui.columns(2, |cols| {
                    for c in 0..2 {
                        let slot = row * 2 + c;
                        let col = &mut cols[c];
                        if col
                            .add_enabled(
                                quality.can_assign() && has_audio,
                                egui::Button::new(
                                    RichText::new(crate::CORNER_LABELS[slot]).color(INK).strong(),
                                )
                                .min_size(egui::vec2(col.available_width(), 30.0))
                                .fill(theme::PAPER_LOW),
                            )
                            .clicked()
                        {
                            self.assign_to_slot(anchor, slot);
                        }
                    }
                });
            }

            ui.add_space(10.0);
            // Vintage sampler front-end — degrade this corner's source before the
            // fit. AAF-off presets fold aliasing into the band (the "scar").
            let cur_pre = self.anchor_audio[anchor]
                .as_ref()
                .map(|s| s.pre)
                .unwrap_or(crate::preprocess::VintagePreset::None);
            ui.horizontal(|ui| {
                ui.label(RichText::new("SAMPLER").color(INK_SOFT).size(10.0));
                if ui
                    .add_enabled(
                        has_audio,
                        egui::Button::new(RichText::new(cur_pre.label()).color(INK).strong())
                            .min_size(egui::vec2(120.0, 26.0))
                            .fill(theme::PAPER_LOW),
                    )
                    .clicked()
                {
                    let all = crate::preprocess::VintagePreset::ALL;
                    let idx = all.iter().position(|p| *p == cur_pre).unwrap_or(0);
                    let next = all[(idx + 1) % all.len()];
                    if let Some(s) = self.anchor_audio[anchor].as_mut() {
                        s.pre = next;
                    }
                    self.refit_anchor(anchor);
                    self.assign_to_slot(anchor, anchor);
                }
            });

            ui.add_space(10.0);
            ui.label(RichText::new("ACTORS · freq / Q / gain").color(INK_SOFT).size(10.0));
            match self.anchor_audio[anchor].as_ref().map(|s| s.extraction.corner) {
                Some(c) => {
                    let sr = self.internal_resample_rate as f64;
                    for (i, &(f, q, g)) in crate::dsp::actor_readout(&c, sr).iter().enumerate() {
                        let line = if f.is_finite() {
                            let qs = if q.is_finite() && q < 9_999.0 {
                                format!("{q:>5.1}")
                            } else {
                                " high".to_owned()
                            };
                            format!(
                                "{:<5} {f:>6.0}Hz  Q{qs}  {g:>+5.1}dB",
                                theme::ACTOR_NAMES[i]
                            )
                        } else {
                            format!("{:<5}    —", theme::ACTOR_NAMES[i])
                        };
                        ui.label(RichText::new(line).color(theme::ACTORS[i]).monospace().size(11.0));
                    }
                }
                None => {
                    ui.label(RichText::new("load a sound").color(INK_FAINT).size(10.0));
                }
            }
        });
    }

    fn inspect_waveform(&mut self, ui: &mut egui::Ui) {
        let anchor = self.inspect_anchor;
        theme::panel_frame().show(ui, |ui| {
            if self.anchor_audio[anchor].is_none() {
                ui.label(RichText::new("no audio loaded").color(INK_SOFT));
                return;
            }
            let (waveform, selected, x_limit, start, end) = {
                let state = self.anchor_audio[anchor].as_ref().unwrap();
                let n = state.buffer.len();
                let wf = downsample_plot(&state.buffer, 0);
                let s = state.start_trim.min(n);
                let e = (state.start_trim + state.window_len).min(n);
                let sel = downsample_plot(&state.buffer[s..e], s);
                (wf, sel, n.saturating_sub(1).max(1) as f64, s as f64, e as f64)
            };

            Plot::new(format!("inspect_waveform_{anchor}"))
                .height(ui.available_height().max(150.0))
                .include_x(0.0)
                .include_x(x_limit)
                .include_y(-1.1)
                .include_y(1.1)
                .allow_boxed_zoom(false)
                .allow_scroll(false)
                .show_axes([false, false])
                .show_grid([false, false])
                .show(ui, |p| {
                    p.line(Line::new(PlotPoints::from(waveform)).color(with_alpha(INK, 90)).width(1.0));
                    p.line(Line::new(PlotPoints::from(selected)).color(CAUTION).width(1.6));
                    p.vline(VLine::new(start).color(CAUTION).width(2.0));
                    p.vline(VLine::new(end).color(with_alpha(INK, 150)).width(1.0));
                });
        });
    }

    /// The midpoint scope — M50/Q50, the position that tells. Corners always look
    /// fitted; the middle is where a wrong fit shows itself (decoded-float nulls
    /// −0.07 dB there, packed ROM −95.41 dB). Green is the verbatim-ROM Hedz truth,
    /// amber is the authored body's middle, and the six named actors decompose it
    /// so the gap can be read per actor — which one is misplaced, not just that the
    /// sum is off. The runtime packed-u16 interpolation produces both middles.
    fn inspect_midpoint_scope(&mut self, ui: &mut egui::Ui) {
        let rate = self.internal_resample_rate as f64;
        let x_max = (rate * 0.5).max(10_000.0);

        ui.horizontal(|ui| {
            ui.label(RichText::new("MIDPOINT · M50/Q50 — where the fit tells").color(INK_SOFT).size(10.0));
            ui.add_space(10.0);
            ui.label(RichText::new("truth").color(INK_SOFT).size(10.0));
            for truth in [crate::RefTruth::Hedz, crate::RefTruth::P2k003] {
                let has = match truth {
                    crate::RefTruth::Hedz => self.hedz_ref_midpoint.is_some(),
                    crate::RefTruth::P2k003 => self.p2k003_ref_midpoint.is_some(),
                };
                let sel = self.ref_truth == truth;
                if ui
                    .add_enabled(
                        has,
                        egui::SelectableLabel::new(
                            sel,
                            RichText::new(truth.label()).color(INK).strong(),
                        ),
                    )
                    .clicked()
                {
                    self.ref_truth = truth;
                }
            }
        });

        let reference = self.reference_midpoint();
        let candidate = self.candidate_midpoint();
        let truth_name = self.ref_truth.label();
        ui.label(
            RichText::new(match (reference.is_some(), candidate.is_some()) {
                (true, true) => "green = heritage truth · amber = your body",
                (true, false) => "heritage truth — author the four corners to compare",
                (false, _) => "this reference isn't in the checkout",
            })
            .color(if reference.is_some() { INK_SOFT } else { CAUTION })
            .size(10.0),
        );

        Plot::new("inspect_midpoint_scope")
            .height(ui.available_height().max(240.0))
            .include_x(20.0)
            .include_x(x_max)
            .include_y(-48.0)
            .include_y(24.0)
            .show_axes([false, false])
            .show_grid([false, false])
            .legend(Legend::default())
            .x_axis_formatter(|m, _| {
                if m.value >= 1_000.0 {
                    format!("{:.0}k", m.value / 1_000.0)
                } else {
                    format!("{:.0}", m.value)
                }
            })
            .show(ui, |p| {
                // Lab-gear grid: log-decade verticals, dB horizontals.
                for f in [100.0, 1_000.0, 10_000.0] {
                    p.vline(VLine::new(f).color(INK_FAINT).width(1.0));
                }
                for g in [0.0, -12.0, -24.0, -36.0] {
                    p.line(
                        Line::new(PlotPoints::from(vec![[20.0, g], [x_max, g]]))
                            .color(INK_FAINT)
                            .width(1.0),
                    );
                }

                // The six actors of whichever middle we have — the candidate when
                // present (read its gaps against the green truth), else the truth's
                // own anatomy to author toward.
                if let Some(c) = candidate.or(reference) {
                    let actors = actor_magnitude_responses(&c, rate);
                    for (i, curve) in actors.iter().enumerate() {
                        p.line(
                            Line::new(PlotPoints::from(curve.clone()))
                                .color(with_alpha(theme::ACTORS[i], 170))
                                .width(1.2)
                                .name(theme::ACTOR_NAMES[i]),
                        );
                    }
                }

                // Green — the E-mu verbatim-ROM truth silhouette.
                if let Some(r) = reference {
                    p.line(
                        Line::new(PlotPoints::from(magnitude_response(&r, rate)))
                            .color(theme::TARGET)
                            .width(2.4)
                            .name(truth_name),
                    );
                }

                // Amber — the authored body's middle (glow + core).
                if let Some(c) = candidate {
                    let resp = magnitude_response(&c, rate);
                    p.line(Line::new(PlotPoints::from(resp.clone())).color(with_alpha(theme::FIT, 70)).width(6.0));
                    p.line(Line::new(PlotPoints::from(resp)).color(theme::FIT).width(1.8).name("your body"));
                }
            });
    }
}

fn quality_color(q: FitQuality) -> egui::Color32 {
    match q {
        FitQuality::Ready => theme::TARGET,
        FitQuality::Review => CAUTION,
        FitQuality::Blocked => theme::VERM,
    }
}

fn quality_label(q: FitQuality) -> &'static str {
    match q {
        FitQuality::Ready => "READY",
        FitQuality::Review => "REVIEW",
        FitQuality::Blocked => "BLOCKED",
    }
}
