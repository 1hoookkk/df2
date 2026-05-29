//! Filter Factory — egui painter surface only.
//!
//! main.rs owns visual composition and input routing. ForgeCore owns the source
//! slots, body assembly, packed preview, export, and save path. DSP owns math.
//! Each corner has a dropdown listing every source in the bank; pick one to load
//! it into that corner. Drag the puck to roam Morph × Q.

#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]

mod audio;
mod capture;
mod dsp;
mod forge_core;

use eframe::egui;
use egui::{Align2, Color32, FontFamily, FontId, Mesh, Order, Pos2, Sense, Shape, Stroke, Vec2};
use trench_core::cartridge::CornerData;

use dsp::{corner_to_biquads, magnitude_response, ResoKind, AUTHORING_RATE};
use forge_core::{ForgeCore, SourceEntry, CARD_LABELS};

/// DRAW handle vertical axis = pole sharpness: bottom = tame, top = ringing.
const DRAW_R_MIN: f64 = 0.60;
const DRAW_R_MAX: f64 = 0.998;
/// An actor pushed past this sharpness is "screaming" — the heat cue warns.
const DRAW_R_HOT: f64 = 0.99;

/// DRAW reference frames you author against. Not a grid — a map of reality.
/// One vowel shows at a time (cycling through them) so the field stays readable.
#[derive(Clone, Copy, PartialEq)]
enum DrawOverlay {
    None,
    Vowel(usize),      // Peterson-Barney 1952 vowel F1..F4 targets
    VowelKlatt(usize), // Klatt 1980 vowel F1..F4 targets (synthesizer ground-truth)
    Bark,              // psychoacoustic critical-band edges
}

impl DrawOverlay {
    fn next(self) -> Self {
        match self {
            Self::None => Self::Vowel(0),
            Self::Vowel(i) if i + 1 < VOWELS.len() => Self::Vowel(i + 1),
            Self::Vowel(_) => Self::VowelKlatt(0),
            Self::VowelKlatt(i) if i + 1 < VOWELS_KLATT.len() => Self::VowelKlatt(i + 1),
            Self::VowelKlatt(_) => Self::Bark,
            Self::Bark => Self::None,
        }
    }
    fn label(self) -> &'static str {
        match self {
            Self::None => "OVERLAY",
            Self::Vowel(i) => VOWELS[i].0,
            Self::VowelKlatt(i) => VOWELS_KLATT[i].0,
            Self::Bark => "BARK",
        }
    }
}

/// One muted accent for the vowel reference marks (the response + actors own the
/// brighter colours; reference frames stay quiet and behind).
const VOWEL_COL: Color32 = Color32::from_rgb(216, 170, 92);
/// A second, cooler tint for the Klatt overlay so PB vs Klatt read as distinct
/// reference frames at a glance — the user A/Bs the two by ear.
const VOWEL_COL_KLATT: Color32 = Color32::from_rgb(143, 175, 196);

/// Canonical vowel formants F1..F4 — drag actors onto these to "make a vowel".
/// PETERSON-BARNEY 1952 adult-male averages (see `tables/vowel_formants.json`).
/// F1..F3 are measured; F4 is borrowed from Klatt's convention (F4 ≈ 3300 Hz,
/// approximately invariant across vowels per Klatt 1980). For the synthesizer-
/// ground-truth comparison set, see `VOWELS_KLATT` below. Don't churn these
/// per message — A/B by toggling the overlay, not by editing the constants.
const VOWELS: [(&str, [f64; 4]); 3] = [
    ("Ah", [730.0, 1090.0, 2440.0, 3300.0]),
    ("Ee", [270.0, 2290.0, 3010.0, 3300.0]),
    ("Oo", [300.0, 870.0, 2240.0, 3300.0]),
];

/// Klatt 1980 F1..F4 (the canonical formant-synthesizer table — `tables/
/// klatt_1980_formants.json`). F4 = 3300 const per Klatt's observation that
/// higher-frequency resonators don't vary much across vowels. /a/, /e/, /o/,
/// /u/ — these are NOT a 1:1 replacement for VOWELS (PB's "Ee" is /i/, not
/// /e/) — they're a complementary set. Toggle via REF to A/B by ear.
const VOWELS_KLATT: [(&str, [f64; 4]); 4] = [
    ("/a/", [700.0, 1220.0, 2600.0, 3300.0]),
    ("/e/", [490.0, 1720.0, 2520.0, 3300.0]),
    ("/o/", [540.0, 1100.0, 2300.0, 3300.0]),
    ("/u/", [350.0, 1250.0, 2200.0, 3300.0]),
];

/// Bark critical-band edges (Hz) — space combs by these, not linearly.
const BARK_EDGES: [f64; 25] = [
    20.0, 100.0, 200.0, 300.0, 400.0, 510.0, 630.0, 770.0, 920.0, 1080.0, 1270.0, 1480.0, 1720.0,
    2000.0, 2320.0, 2700.0, 3150.0, 3700.0, 4400.0, 5300.0, 6400.0, 7700.0, 9500.0, 12000.0,
    15500.0,
];

// ── palette ─────────────────────────────────────────────────────────────────
const FIELD: Color32 = Color32::from_rgb(4, 7, 6);
const INK: Color32 = Color32::from_rgb(190, 205, 188);
const INK_DIM: Color32 = Color32::from_rgb(70, 83, 75);
const GRID: Color32 = Color32::from_rgb(28, 39, 34);
const GREEN: Color32 = Color32::from_rgb(91, 239, 111);
const CYAN: Color32 = Color32::from_rgb(49, 198, 201);
const RED: Color32 = Color32::from_rgb(232, 61, 49);
/// The TEAR (coupled cavity) actor — warm-orange, distinct from RED (notch)
/// and VOWEL_COL (vowel reference). Hot enough to read as a "tear" but
/// outside the heat-cue palette so it doesn't read as a warning.
const ORANGE: Color32 = Color32::from_rgb(232, 144, 49);

/// Corner slot letters: A/B across the top (Morph 0→100), C/D across the bottom (Q).
const SLOTS: [&str; 4] = ["A", "B", "C", "D"];

fn alpha(c: Color32, a: u8) -> Color32 {
    Color32::from_rgba_unmultiplied(c.r(), c.g(), c.b(), a)
}

// ── app state (UI only) ───────────────────────────────────────────────────────
struct App {
    core: ForgeCore,
    audio: Option<audio::Audio>,
    capture: Option<capture::Capture>,
    capture_target: usize,
    bad_slot: Option<usize>,
    sources: Vec<SourceEntry>,
    menu_tree: MenuNode, // navigable folder-tree of sources for the well dropdowns
    presets: Vec<SourceEntry>,
    preset_rect: egui::Rect,
    control_rect: egui::Rect,
    // render caches
    view_corner: Option<CornerData>,
    view_fit: Vec<[f64; 2]>, // the drawn curve, eased toward target_fit each frame
    target_fit: Vec<[f64; 2]>, // the true response of the current morph position
    // interaction
    source_marks: [egui::Rect; 4],
    combo_rects: [egui::Rect; 4],
    hover_pos: Option<Pos2>,
    // DRAW (from-scratch corner authoring)
    draw_kind: ResoKind,
    dragging: Option<usize>,
    overlay: DrawOverlay,
}

impl Default for App {
    fn default() -> Self {
        // Start BLANK — no baked-in corners. (Press L to load the starter bank.)
        let core = ForgeCore::default();
        let bad_slot: Option<usize> = None;
        let sources = forge_core::available_sources();
        let menu_tree = build_menu_tree(&sources);
        Self {
            core,
            audio: audio::start(),
            capture: None,
            capture_target: 0,
            bad_slot,
            sources,
            menu_tree,
            presets: forge_core::available_presets(),
            preset_rect: egui::Rect::NOTHING,
            control_rect: egui::Rect::NOTHING,
            view_corner: None,
            view_fit: Vec::new(),
            target_fit: Vec::new(),
            source_marks: [egui::Rect::NOTHING; 4],
            combo_rects: [egui::Rect::NOTHING; 4],
            hover_pos: None,
            draw_kind: ResoKind::Peak,
            dragging: None,
            overlay: DrawOverlay::None,
        }
    }
}

// ── source menu tree (folder hierarchy → nested submenus) ─────────────────────
#[derive(Default)]
struct MenuNode {
    folders: std::collections::BTreeMap<String, MenuNode>,
    items: Vec<(String, usize)>, // (label, source index)
}

impl MenuNode {
    fn total(&self) -> usize {
        self.items.len() + self.folders.values().map(MenuNode::total).sum::<usize>()
    }
}

fn build_menu_tree(sources: &[SourceEntry]) -> MenuNode {
    let mut root = MenuNode::default();
    for (idx, s) in sources.iter().enumerate() {
        let mut node = &mut root;
        if !s.category.is_empty() {
            for part in s.category.split('/') {
                node = node.folders.entry(part.to_string()).or_default();
            }
        }
        node.items.push((s.label.clone(), idx));
    }
    root
}

/// Render a source node as nested submenus; returns the clicked source index.
fn menu_tree_render(ui: &mut egui::Ui, node: &MenuNode) -> Option<usize> {
    let mut clicked = None;
    for (name, child) in &node.folders {
        let label = format!(
            "{}  ({})",
            name.trim_start_matches('_').replace('_', " "),
            child.total()
        );
        ui.menu_button(label, |ui| {
            egui::ScrollArea::vertical()
                .max_height(440.0)
                .show(ui, |ui| {
                    ui.set_min_width(170.0);
                    if let Some(c) = menu_tree_render(ui, child) {
                        clicked = Some(c);
                    }
                });
        });
    }
    for (label, idx) in &node.items {
        if ui.button(label.as_str()).clicked() {
            clicked = Some(*idx);
            ui.close_menu();
        }
    }
    clicked
}

// ── workflow plumbing (thin wrappers over ForgeCore) ──────────────────────────
impl App {
    fn hovered_source(&self) -> Option<usize> {
        let pos = self.hover_pos?;
        self.source_marks.iter().position(|r| r.contains(pos))
    }

    fn load(&mut self, i: usize, path: &std::path::Path) {
        // One well, three faucets: a precomputed corner loads direct; a WAV is fit.
        let res = if path.to_string_lossy().ends_with(".corner.json") {
            self.core.load_corner(i, path)
        } else {
            self.core.load_source(i, path)
        };
        match res {
            Ok(()) => {
                self.bad_slot = self.bad_slot.filter(|bad| *bad != i);
                // Snap the puck onto the corner you just loaded, so the curve shows
                // THAT corner alone — work one at a time, not the four-way blend.
                let (m, q) = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)][i];
                self.core.set_puck(m, q);
                self.play_if_ready();
            }
            Err(_) => self.bad_slot = Some(i),
        }
        self.view_corner = None;
    }

    fn start_capture(&mut self, i: usize) {
        match capture::Capture::start() {
            Ok(cap) => {
                self.capture = Some(cap);
                self.capture_target = i;
                self.bad_slot = self.bad_slot.filter(|bad| *bad != i);
            }
            Err(_) => self.bad_slot = Some(i),
        }
    }

    fn finish_capture(&mut self) {
        let Some(cap) = self.capture.take() else {
            return;
        };
        let i = self.capture_target;
        let sr = cap.sample_rate;
        let samples = cap.drain_mono_f64();
        drop(cap);
        if samples.len() < 64 {
            self.bad_slot = Some(i);
            return;
        }
        self.core
            .load_samples(i, &samples, sr, format!("capture {}", CARD_LABELS[i]));
        self.bad_slot = self.bad_slot.filter(|bad| *bad != i);
        self.view_corner = None;
        self.play_if_ready();
    }

    fn reset(&mut self) {
        self.core.reset();
        self.bad_slot = None;
        self.view_corner = None;
        self.view_fit.clear();
        self.target_fit.clear();
        if let Some(a) = &self.audio {
            a.set_playing(false);
            a.clear_target();
            a.set_source_mode(audio::SourceMode::Saw);
            a.set_level(0.85);
        }
    }

    fn save(&mut self) {
        if self.core.save().is_err() {
            self.bad_slot = Some(self.core.next_empty());
        }
    }

    fn push(&mut self) {
        self.save();
        self.play_if_ready();
    }

    /// Cycle the fitter proposal mode (PEAK → VOICE → ARMA) and re-fit any loaded
    /// sources in place, so you can A/B the proposals by ear. The audio target is
    /// refreshed by `push_audio` on the next frame.
    fn cycle_fit_mode(&mut self) {
        let next = self.core.fit_mode().next();
        self.core.set_fit_mode(next);
        self.view_corner = None;
    }

    fn load_bank(&mut self) {
        if self.core.load_legisign_phonetic_bank().is_ok() {
            if let Some(a) = &self.audio {
                a.set_source_mode(audio::SourceMode::Saw);
            }
            self.view_corner = None;
            self.play_if_ready();
        } else {
            self.bad_slot = Some(self.core.next_empty());
        }
    }

    fn toggle_play(&mut self) {
        if let Some(a) = &self.audio {
            a.set_playing(!a.is_playing());
        }
    }

    fn play_if_ready(&self) {
        if let Some(a) = &self.audio {
            a.set_playing(true);
        }
    }

    fn capture_hotkey(&mut self) {
        if self.capture.is_some() {
            self.finish_capture();
            return;
        }
        let target = self
            .hovered_source()
            .unwrap_or_else(|| self.core.next_empty());
        self.start_capture(target);
    }

    fn take_drops(&mut self, ctx: &egui::Context) {
        let dropped = ctx.input(|i| i.raw.dropped_files.clone());
        for f in dropped {
            if let Some(path) = f.path {
                let target = self
                    .hovered_source()
                    .unwrap_or_else(|| self.core.next_empty());
                self.load(target, &path);
                break;
            }
        }
    }

    fn handle_hotkeys(&mut self, ctx: &egui::Context) {
        let (play, push, reset, capture, bank, saw, tone, pink, fit, draw, overlay) =
            ctx.input(|i| {
            (
                i.key_pressed(egui::Key::Space),
                i.modifiers.command && i.key_pressed(egui::Key::S)
                    || i.key_pressed(egui::Key::Enter),
                i.key_pressed(egui::Key::R)
                    || i.key_pressed(egui::Key::N)
                    || i.key_pressed(egui::Key::Escape),
                !i.modifiers.command && i.key_pressed(egui::Key::C),
                i.key_pressed(egui::Key::B) || i.key_pressed(egui::Key::L),
                i.key_pressed(egui::Key::Num1),
                i.key_pressed(egui::Key::Num2),
                i.key_pressed(egui::Key::Num3),
                i.key_pressed(egui::Key::F),
                i.key_pressed(egui::Key::D),
                i.key_pressed(egui::Key::O),
            )
        });
        if draw {
            self.core.toggle_design();
            self.view_corner = None;
        }
        if overlay {
            self.overlay = self.overlay.next();
        }
        if play {
            self.toggle_play();
        }
        if push {
            self.push();
        }
        if reset {
            self.reset();
        }
        if capture {
            self.capture_hotkey();
        }
        if bank {
            self.load_bank();
        }
        if fit {
            self.cycle_fit_mode();
        }
        if let Some(a) = &self.audio {
            if saw {
                a.set_source_mode(audio::SourceMode::Saw);
                self.play_if_ready();
            } else if tone {
                a.set_source_mode(audio::SourceMode::Tone);
                self.play_if_ready();
            } else if pink {
                a.set_source_mode(audio::SourceMode::Pink);
                self.play_if_ready();
            }
        }
    }

    fn push_audio(&mut self) {
        if let Some(a) = &self.audio {
            if let Some(c) = self.core.preview() {
                a.set_target(corner_to_biquads(&c));
            } else {
                a.clear_target();
            }
        }
    }

    fn source_state(&self, i: usize) -> SourceState {
        if self.bad_slot == Some(i) {
            SourceState::Bad
        } else if self.core.corner(i).is_some() {
            SourceState::Ready
        } else {
            SourceState::Empty
        }
    }
}

// ── eframe loop ───────────────────────────────────────────────────────────────
impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.hover_pos = ctx.input(|i| i.pointer.hover_pos());
        if self
            .capture
            .as_ref()
            .map(|c| c.elapsed_secs() >= capture::CAPTURE_SECS)
            .unwrap_or(false)
        {
            self.finish_capture();
        }
        self.handle_hotkeys(ctx);
        self.take_drops(ctx);
        self.push_audio();

        egui::CentralPanel::default()
            .frame(egui::Frame::none().fill(FIELD))
            .show(ctx, |ui| self.field(ui));

        ctx.request_repaint_after(std::time::Duration::from_millis(16));
    }
}

// ── the field ─────────────────────────────────────────────────────────────────
impl App {
    fn field(&mut self, ui: &mut egui::Ui) {
        let (resp, painter) = ui.allocate_painter(ui.available_size(), Sense::click_and_drag());
        let rect = resp.rect;
        painter.rect_filled(rect, 0.0, FIELD);

        let field = rect.shrink2(Vec2::new(54.0, 42.0));
        self.source_marks = source_mark_rects(field);

        draw_grid(&painter, field);
        self.draw_overlay(&painter, field);
        self.draw_response(&painter, field);
        self.draw_source_marks(&painter, field);
        self.draw_puck(&painter, field);
        self.draw_resonances(&painter, field);
        self.draw_stability_warning(&painter, field);
        if self.core.design_mode() {
            // Focus mode: hide the four corner loaders + preset picker — you shape
            // one corner at a time. Clear their click-rects so the field takes clicks.
            self.combo_rects = [egui::Rect::NOTHING; 4];
            self.preset_rect = egui::Rect::NOTHING;
        } else {
            self.corner_combos(ui, field);
            self.preset_combo(ui, field);
        }
        self.speedrun_controls(ui, field);
        self.handle_pointer(&resp, field);

        if self.capture.is_some() {
            draw_capture_pulse(&painter, field, self.capture_target);
        }
    }

    /// When the bilinear-interp morph surface destabilises (a pole at the
    /// interpolated middle has effectively left the unit circle), surface a
    /// RED chip at the top of the field and paint a hot ring at the offending
    /// (morph, q) cell. The corners themselves can look fine on the response —
    /// the warning is about what the *middle* does. See
    /// `memory/armadillo-morphing-rules.md`.
    fn draw_stability_warning(&self, painter: &egui::Painter, field: egui::Rect) {
        let Some((r_max, (m, q))) = self.core.morph_surface_stability() else {
            return;
        };
        if r_max <= dsp::STABILITY_RADIUS_LIMIT {
            return;
        }
        // Banner chip at the top of the field.
        chip(
            painter,
            Pos2::new(field.center().x, field.top() + 14.0),
            &format!("UNSTABLE MIDDLE · r={:.3} at m={:.2} Q={:.2}", r_max, m, q),
            RED,
        );
        // Hot ring at the offending cell, so the eye finds the trouble spot.
        let cell_x = field.left() + m as f32 * field.width();
        let cell_y = field.top() + q as f32 * field.height();
        let pos = Pos2::new(cell_x, cell_y);
        painter.circle_stroke(pos, 16.0, Stroke::new(1.6, alpha(RED, 230)));
        painter.circle_filled(pos, 16.0, alpha(RED, 36));
    }

    fn speedrun_controls(&mut self, ui: &mut egui::Ui, field: egui::Rect) {
        let pos = Pos2::new(field.left() + 184.0, field.top() + 10.0);
        let inner = egui::Area::new(egui::Id::new("speedrun_controls"))
            .fixed_pos(pos)
            .order(Order::Foreground)
            .show(ui.ctx(), |ui| {
                egui::Frame::none()
                    .fill(alpha(FIELD, 214))
                    .stroke(Stroke::new(1.0, alpha(GRID, 180)))
                    .rounding(4.0)
                    .inner_margin(egui::Margin::symmetric(8.0, 5.0))
                    .show(ui, |ui| {
                        ui.horizontal(|ui| {
                            let playing =
                                self.audio.as_ref().map(|a| a.is_playing()).unwrap_or(false);
                            if ui.button(if playing { "STOP" } else { "PLAY" }).clicked() {
                                self.toggle_play();
                            }

                            if let Some(a) = &self.audio {
                                let mut mode = a.source_mode();
                                ui.selectable_value(&mut mode, audio::SourceMode::Saw, "SAW");
                                ui.selectable_value(&mut mode, audio::SourceMode::Tone, "TONE");
                                ui.selectable_value(&mut mode, audio::SourceMode::Pink, "PINK");
                                if mode != a.source_mode() {
                                    a.set_source_mode(mode);
                                    self.play_if_ready();
                                }
                                let mut level = a.level();
                                if ui
                                    .add(egui::Slider::new(&mut level, 0.05..=1.5).text("LVL"))
                                    .changed()
                                {
                                    a.set_level(level);
                                }
                            } else {
                                ui.label(
                                    egui::RichText::new("AUDIO OFF")
                                        .family(FontFamily::Monospace)
                                        .color(RED),
                                );
                            }

                            if ui.button("NEW").clicked() {
                                self.reset();
                            }
                            if ui.button("BANK").clicked() {
                                self.load_bank();
                            }
                            // Fitter proposal mode (F): PEAK / VOICE / ARMA. The fit
                            // is a starting point — this picks how it's proposed.
                            let fm = self.core.fit_mode();
                            if ui
                                .button(format!("FIT·{}", fm.label()))
                                .on_hover_text("Fitter proposal: PEAK → VOICE → ARMA (F)")
                                .clicked()
                            {
                                self.cycle_fit_mode();
                            }
                            if ui.button("PUSH").clicked() {
                                self.push();
                            }

                            // ── DRAW: from-scratch corner authoring ──────────
                            ui.separator();
                            let dm = self.core.design_mode();
                            if ui
                                .selectable_label(dm, "DRAW")
                                .on_hover_text("From scratch: place actors on the scope (D)")
                                .clicked()
                            {
                                self.core.toggle_design();
                                self.view_corner = None;
                            }
                            if self.core.design_mode() {
                                for i in 0..4 {
                                    if ui
                                        .selectable_label(self.core.active() == i, SLOTS[i])
                                        .clicked()
                                    {
                                        self.core.set_active(i);
                                        self.dragging = None;
                                        self.view_corner = None;
                                    }
                                }
                                ui.separator();
                                for k in [ResoKind::Peak, ResoKind::Cavity, ResoKind::Notch, ResoKind::Edge] {
                                    if ui
                                        .selectable_label(self.draw_kind == k, k.label())
                                        .clicked()
                                    {
                                        self.draw_kind = k;
                                    }
                                }
                                ui.separator();
                                if ui
                                    .selectable_label(
                                        self.overlay != DrawOverlay::None,
                                        self.overlay.label(),
                                    )
                                    .on_hover_text("Reference frame: Ah → Ee → Oo → Bark → off (O)")
                                    .clicked()
                                {
                                    self.overlay = self.overlay.next();
                                }
                            }
                        });
                    });
            });
        self.control_rect = inner.response.rect;
    }

    fn draw_response(&mut self, painter: &egui::Painter, field: egui::Rect) {
        let Some(corner) = self.core.preview() else {
            return;
        };
        if self.view_corner != Some(corner) {
            self.target_fit = magnitude_response(&corner, AUTHORING_RATE);
            self.view_corner = Some(corner);
        }
        // Ease the drawn curve toward the target so morphs and loads GLIDE, not snap.
        if self.view_fit.len() != self.target_fit.len() {
            self.view_fit = self.target_fit.clone();
        } else {
            for (v, t) in self.view_fit.iter_mut().zip(self.target_fit.iter()) {
                v[1] += (t[1] - v[1]) * 0.35;
            }
        }
        let pts = response_points(field, &self.view_fit);
        if pts.len() < 2 {
            return;
        }
        let clip = painter.with_clip_rect(field);
        let base_y = db_y(field, -30.0);
        let mut mesh = Mesh::default();
        for p in &pts {
            mesh.colored_vertex(*p, alpha(GREEN, 16));
            mesh.colored_vertex(Pos2::new(p.x, base_y), alpha(GREEN, 4));
        }
        for i in 0..pts.len().saturating_sub(1) {
            let a = (i * 2) as u32;
            mesh.add_triangle(a, a + 1, a + 2);
            mesh.add_triangle(a + 1, a + 3, a + 2);
        }
        clip.add(Shape::mesh(mesh));
        clip.add(Shape::line(pts.clone(), Stroke::new(7.0, alpha(GREEN, 18))));
        clip.add(Shape::line(pts.clone(), Stroke::new(3.5, alpha(GREEN, 80))));
        clip.add(Shape::line(pts, Stroke::new(1.6, alpha(GREEN, 245))));
    }

    fn draw_source_marks(&self, painter: &egui::Painter, field: egui::Rect) {
        let anchors = [
            field.left_top(),
            field.right_top(),
            field.left_bottom(),
            field.right_bottom(),
        ];
        let puck = puck_pos(field, self.core.morph(), self.core.q());
        // DRAW focuses one corner: show only the active corner's marker, no
        // four-way puck web — so you're looking at one thing, not four.
        let focus = self.core.design_mode();
        let active = self.core.active();

        for (i, anchor) in anchors.into_iter().enumerate() {
            if focus && i != active {
                continue;
            }
            let state = self.source_state(i);
            let col = state.color();
            let sx = if i % 2 == 0 { 1.0 } else { -1.0 };
            let sy = if i < 2 { 1.0 } else { -1.0 };

            if !focus {
                painter.line_segment([anchor, puck], Stroke::new(0.7, alpha(CYAN, 32)));
            }
            painter.line_segment(
                [anchor, Pos2::new(anchor.x + sx * 22.0, anchor.y)],
                Stroke::new(1.3, alpha(col, 150)),
            );
            painter.line_segment(
                [anchor, Pos2::new(anchor.x, anchor.y + sy * 22.0)],
                Stroke::new(1.3, alpha(col, 150)),
            );
            painter.circle_filled(anchor, 2.6, alpha(col, 210));

            let label_pos = Pos2::new(anchor.x + sx * 10.0, anchor.y + sy * 10.0);
            let align = match i {
                0 => Align2::LEFT_TOP,
                1 => Align2::RIGHT_TOP,
                2 => Align2::LEFT_BOTTOM,
                _ => Align2::RIGHT_BOTTOM,
            };
            let text = if focus {
                format!("{} · DRAW", SLOTS[i])
            } else {
                format!("{}  {}", SLOTS[i], state.text())
            };
            painter.text(
                label_pos,
                align,
                text,
                FontId::new(12.0, FontFamily::Monospace),
                col,
            );
        }
    }

    /// A dropdown at each corner listing every source in the bank.
    fn corner_combos(&mut self, ui: &mut egui::Ui, field: egui::Rect) {
        const CW: f32 = 168.0;
        let p = 10.0;
        let pos = [
            Pos2::new(field.left() + p, field.top() + p + 24.0),
            Pos2::new(field.right() - CW - p, field.top() + p + 24.0),
            Pos2::new(field.left() + p, field.bottom() - p - 44.0),
            Pos2::new(field.right() - CW - p, field.bottom() - p - 44.0),
        ];
        let names: [String; 4] = core::array::from_fn(|i| {
            self.core
                .corner(i)
                .map(|c| c.name.clone())
                .unwrap_or_else(|| "— load —".to_owned())
        });
        let tree = &self.menu_tree;
        let mut change: Option<(usize, usize)> = None;
        let mut rects = [egui::Rect::NOTHING; 4];

        for i in 0..4 {
            let inner = egui::Area::new(egui::Id::new(("corner_combo", i)))
                .fixed_pos(pos[i])
                .order(Order::Foreground)
                .show(ui.ctx(), |ui| {
                    // Menu button + submenus (NOT a ComboBox): a ComboBox popup
                    // dismisses the instant you click a CollapsingHeader inside it.
                    // Submenus are built to stay open — open on hover, close on pick.
                    ui.set_width(CW);
                    let btn = egui::RichText::new(format!("{}  ▾", names[i]))
                        .family(FontFamily::Monospace);
                    ui.menu_button(btn, |ui| {
                        ui.set_min_width(170.0);
                        egui::ScrollArea::vertical()
                            .max_height(440.0)
                            .show(ui, |ui| {
                                if let Some(j) = menu_tree_render(ui, tree) {
                                    change = Some((i, j));
                                }
                            });
                    });
                });
            rects[i] = inner.response.rect;
        }
        self.combo_rects = rects;

        if let Some((i, j)) = change {
            let path = self.sources[j].path.clone();
            self.load(i, &path);
        }
    }

    /// A PRESET dropdown (top-centre) that loads a verbatim 240-byte frame into
    /// all four corners at once.
    fn preset_combo(&mut self, ui: &mut egui::Ui, field: egui::Rect) {
        if self.presets.is_empty() {
            self.preset_rect = egui::Rect::NOTHING;
            return;
        }
        const PW: f32 = 220.0;
        let pos = Pos2::new(field.center().x - PW / 2.0, field.top() + 8.0);
        let presets = &self.presets;
        let mut pick: Option<usize> = None;
        let inner = egui::Area::new(egui::Id::new("preset_combo"))
            .fixed_pos(pos)
            .order(Order::Foreground)
            .show(ui.ctx(), |ui| {
                egui::ComboBox::from_id_source("preset")
                    .selected_text("PRESET")
                    .width(PW)
                    .show_ui(ui, |ui| {
                        for (j, p) in presets.iter().enumerate() {
                            if ui.selectable_label(false, p.label.as_str()).clicked() {
                                pick = Some(j);
                            }
                        }
                    });
            });
        self.preset_rect = inner.response.rect;
        if let Some(j) = pick {
            let path = self.presets[j].path.clone();
            let label = self.presets[j].label.clone();
            self.bad_slot = self.core.load_reference_rom(&path, &label).err().map(|_| 0);
            if self.bad_slot.is_none() {
                if let Some(a) = &self.audio {
                    a.set_source_mode(audio::SourceMode::Saw);
                }
                self.play_if_ready();
            }
            self.view_corner = None;
        }
    }

    fn draw_puck(&self, painter: &egui::Painter, field: egui::Rect) {
        let pos = puck_pos(field, self.core.morph(), self.core.q());
        let active = self.core.count() > 0;
        let col = if active { GREEN } else { INK_DIM };
        let d = if active { 10.0 } else { 8.0 };
        let diamond = vec![
            Pos2::new(pos.x, pos.y - d),
            Pos2::new(pos.x + d, pos.y),
            Pos2::new(pos.x, pos.y + d),
            Pos2::new(pos.x - d, pos.y),
        ];
        painter.add(Shape::convex_polygon(
            diamond,
            alpha(col, if active { 44 } else { 18 }),
            Stroke::new(1.8, alpha(col, 230)),
        ));
        painter.circle_filled(pos, 2.0, alpha(col, 240));
    }

    fn handle_pointer(&mut self, resp: &egui::Response, field: egui::Rect) {
        let Some(pt) = resp.interact_pointer_pos() else {
            return;
        };
        // The corner + preset dropdowns and the control strip own their clicks.
        if self.combo_rects.iter().any(|r| r.contains(pt))
            || self.preset_rect.contains(pt)
            || self.control_rect.contains(pt)
        {
            return;
        }
        if !field.contains(pt) {
            return;
        }

        // DRAW mode: the field places and drags actors instead of roaming the puck.
        if self.core.design_mode() {
            if resp.secondary_clicked() {
                if let Some(idx) = self.nearest_handle(field, pt) {
                    self.core.remove_resonance(idx);
                }
                self.dragging = None;
                self.view_corner = None;
                return;
            }
            let f = self.snap_freq(field, freq_from_x(field, pt.x));
            let rad = radius_from_y(field, pt.y);
            if resp.drag_started() {
                // Grab a nearby handle to drag, or drop a fresh actor and drag it.
                self.dragging = match self.nearest_handle(field, pt) {
                    Some(idx) => Some(idx),
                    None => Some(self.core.add_resonance(f, rad, self.draw_kind)),
                };
            }
            if resp.dragged() {
                if let Some(idx) = self.dragging {
                    self.core.move_resonance(idx, f, rad);
                }
            }
            if resp.clicked() && self.nearest_handle(field, pt).is_none() {
                // A tap on empty space drops an actor at the cursor.
                self.core.add_resonance(f, rad, self.draw_kind);
            }
            self.view_corner = None;
            return;
        }

        // Default: roam the Morph × Q puck.
        if resp.dragged() || resp.clicked() {
            let morph = ((pt.x - field.left()) / field.width()).clamp(0.0, 1.0);
            let q = ((pt.y - field.top()) / field.height()).clamp(0.0, 1.0);
            self.core.set_puck(morph, q);
            self.view_corner = None;
        }
    }

    /// Magnetic snap: when a vowel overlay is up, an actor dragged within a few
    /// pixels of a formant mark locks onto that exact frequency (drag onto the F1
    /// line → it IS F1). Works for both PB and Klatt overlays. Off when no vowel
    /// overlay is showing.
    fn snap_freq(&self, field: egui::Rect, f: f64) -> f64 {
        let formants: Option<&[f64; 4]> = match self.overlay {
            DrawOverlay::Vowel(i) => Some(&VOWELS[i].1),
            DrawOverlay::VowelKlatt(i) => Some(&VOWELS_KLATT[i].1),
            _ => None,
        };
        if let Some(targets) = formants {
            let x = freq_x(field, f);
            for &ff in targets {
                if (freq_x(field, ff) - x).abs() < 9.0 {
                    return ff;
                }
            }
        }
        f
    }

    /// The active corner's actor whose drawn handle is within grab range of `pt`.
    fn nearest_handle(&self, field: egui::Rect, pt: Pos2) -> Option<usize> {
        let a = self.core.active();
        let mut best: Option<(usize, f32)> = None;
        for (idx, r) in self.core.resonances(a).iter().enumerate() {
            let hp = Pos2::new(freq_x(field, r.freq_hz), reso_y(field, r.radius));
            let d = hp.distance(pt);
            if d < 16.0 && best.map(|(_, bd)| d < bd).unwrap_or(true) {
                best = Some((idx, d));
            }
        }
        best.map(|(i, _)| i)
    }

    /// Reference frames you author against: one vowel's formant marks, or Bark
    /// bands. Faint lines that sit behind the curve; labels in chips at the edge.
    fn draw_overlay(&self, painter: &egui::Painter, field: egui::Rect) {
        let clip = painter.with_clip_rect(field);
        match self.overlay {
            DrawOverlay::None => {}
            DrawOverlay::Bark => {
                for f in BARK_EDGES {
                    let x = freq_x(field, f);
                    clip.line_segment(
                        [
                            Pos2::new(x, field.top() + 20.0),
                            Pos2::new(x, field.bottom() - 22.0),
                        ],
                        Stroke::new(0.6, alpha(CYAN, 24)),
                    );
                }
                chip(
                    painter,
                    Pos2::new(field.left() + 84.0, field.bottom() - 12.0),
                    "BARK · critical bands",
                    alpha(CYAN, 205),
                );
            }
            DrawOverlay::Vowel(i) => {
                draw_vowel_marks(&clip, painter, field, &VOWELS[i].1, VOWEL_COL);
            }
            DrawOverlay::VowelKlatt(i) => {
                draw_vowel_marks(&clip, painter, field, &VOWELS_KLATT[i].1, VOWEL_COL_KLATT);
            }
        }
    }

    /// Draw the active corner's actors as draggable handles (x = freq, y = sharpness).
    fn draw_resonances(&self, painter: &egui::Painter, field: egui::Rect) {
        if !self.core.design_mode() {
            return;
        }
        let a = self.core.active();
        let actors = self.core.resonances(a);
        if actors.is_empty() {
            // Empty-state guidance, centred in the blank canvas — gone once you work.
            chip(
                painter,
                field.center(),
                "click to place an actor   ·   drag to shape   ·   right-click to remove",
                alpha(INK, 170),
            );
            return;
        }
        for (idx, r) in actors.iter().enumerate() {
            let x = freq_x(field, r.freq_hz);
            let y = reso_y(field, r.radius);
            let pos = Pos2::new(x, y);
            let col = match r.kind {
                ResoKind::Peak => GREEN,
                ResoKind::Notch => RED,
                ResoKind::Edge => CYAN,
                ResoKind::Cavity => ORANGE,
            };
            painter.line_segment(
                [Pos2::new(x, field.bottom()), pos],
                Stroke::new(0.8, alpha(col, 90)),
            );
            // The TEAR's coupled zero: a small notch tick a few semis above
            // the pole. Sound-language only — the user reads it as "peak with
            // a canyon next to it", never as a z-plane radius readout.
            if matches!(r.kind, ResoKind::Cavity) {
                let semis = if r.cavity_semis < 0.5 { 3.0 } else { r.cavity_semis };
                let f_notch = r.freq_hz * 2.0_f64.powf(semis / 12.0);
                let xn = freq_x(field, f_notch);
                // Coupling brace: a faint arc-tie at the top of the field
                // showing pole and notch as one unit.
                let top_y = y - 16.0;
                painter.line_segment([Pos2::new(x, top_y), Pos2::new(xn, top_y)], Stroke::new(1.0, alpha(col, 150)));
                painter.line_segment([Pos2::new(x, top_y), pos], Stroke::new(0.8, alpha(col, 110)));
                // The notch nub: a tiny inverted triangle pinned to the
                // notch frequency, hanging just under the brace.
                let n_top = top_y + 2.0;
                let n_h = 6.0;
                let n_w = 4.0;
                painter.add(Shape::convex_polygon(
                    vec![
                        Pos2::new(xn - n_w, n_top),
                        Pos2::new(xn + n_w, n_top),
                        Pos2::new(xn, n_top + n_h),
                    ],
                    alpha(col, 90),
                    Stroke::new(1.2, alpha(col, 220)),
                ));
            }
            // Heat cue: an actor pushed toward screaming glows hot (sound language,
            // not a z-plane radius readout). The hotter it is, the bigger the halo.
            if r.radius > DRAW_R_HOT {
                let heat = ((r.radius - DRAW_R_HOT) / (DRAW_R_MAX - DRAW_R_HOT)).clamp(0.0, 1.0);
                painter.circle_filled(pos, 9.0 + 7.0 * heat as f32, alpha(RED, 26));
                painter.circle_stroke(pos, 9.0 + 7.0 * heat as f32, Stroke::new(1.0, alpha(RED, 150)));
            }
            let sel = self.dragging == Some(idx);
            painter.circle(
                pos,
                if sel { 7.0 } else { 5.0 },
                alpha(col, 70),
                Stroke::new(if sel { 2.0 } else { 1.5 }, alpha(col, 240)),
            );
            // Named actor (descriptive, follows its frequency) — and the exact Hz
            // while you're holding it.
            let label = if sel {
                format!("{} · {}", actor_band_name(r.freq_hz), fmt_hz(r.freq_hz))
            } else {
                actor_band_name(r.freq_hz).to_owned()
            };
            painter.text(
                Pos2::new(x, y - 11.0),
                Align2::CENTER_BOTTOM,
                label,
                FontId::new(10.0, FontFamily::Monospace),
                alpha(col, if sel { 240 } else { 185 }),
            );
        }
    }
}

// ── corner status ──────────────────────────────────────────────────────────────
#[derive(Clone, Copy)]
enum SourceState {
    Empty,
    Ready,
    Bad,
}

impl SourceState {
    fn text(self) -> &'static str {
        match self {
            Self::Empty => "EMPTY",
            Self::Ready => "READY",
            Self::Bad => "BAD",
        }
    }

    fn color(self) -> Color32 {
        match self {
            Self::Empty => INK_DIM,
            Self::Ready => GREEN,
            Self::Bad => RED,
        }
    }
}

// ── geometry / drawing helpers ──────────────────────────────────────────────────
fn source_mark_rects(field: egui::Rect) -> [egui::Rect; 4] {
    let size = Vec2::new(138.0, 56.0);
    [
        egui::Rect::from_min_size(field.left_top(), size),
        egui::Rect::from_min_size(Pos2::new(field.right() - size.x, field.top()), size),
        egui::Rect::from_min_size(Pos2::new(field.left(), field.bottom() - size.y), size),
        egui::Rect::from_min_size(field.right_bottom() - size, size),
    ]
}

fn draw_grid(painter: &egui::Painter, field: egui::Rect) {
    let clip = painter.with_clip_rect(field);
    for f in [
        20.0, 31.5, 50.0, 80.0, 100.0, 160.0, 250.0, 400.0, 630.0, 1_000.0, 1_600.0, 2_500.0,
        4_000.0, 6_300.0, 10_000.0, 16_000.0, 20_000.0,
    ] {
        let x = freq_x(field, f);
        let major = matches!(f as i32, 20 | 100 | 1000 | 10000 | 20000);
        clip.line_segment(
            [Pos2::new(x, field.top()), Pos2::new(x, field.bottom())],
            Stroke::new(
                if major { 1.0 } else { 0.6 },
                alpha(GRID, if major { 92 } else { 46 }),
            ),
        );
    }
    for db in [-24.0, -12.0, 0.0, 12.0, 24.0] {
        let y = db_y(field, db);
        clip.line_segment(
            [Pos2::new(field.left(), y), Pos2::new(field.right(), y)],
            Stroke::new(if db == 0.0 { 1.1 } else { 0.7 }, alpha(GRID, 72)),
        );
    }
}

fn draw_capture_pulse(painter: &egui::Painter, field: egui::Rect, target: usize) {
    let anchors = [
        field.left_top(),
        field.right_top(),
        field.left_bottom(),
        field.right_bottom(),
    ];
    if let Some(pos) = anchors.get(target) {
        painter.circle_stroke(*pos, 18.0, Stroke::new(1.6, alpha(RED, 230)));
        painter.circle_stroke(*pos, 29.0, Stroke::new(0.8, alpha(RED, 110)));
    }
}

fn response_points(field: egui::Rect, response: &[[f64; 2]]) -> Vec<Pos2> {
    response
        .iter()
        .map(|[f, db]| Pos2::new(freq_x(field, *f), db_y(field, *db)))
        .collect()
}

fn puck_pos(field: egui::Rect, morph: f32, q: f32) -> Pos2 {
    Pos2::new(
        egui::lerp(field.left()..=field.right(), morph),
        egui::lerp(field.top()..=field.bottom(), q),
    )
}

fn freq_x(field: egui::Rect, f: f64) -> f32 {
    let nyq = AUTHORING_RATE * 0.5;
    let span = (nyq / 20.0).ln();
    egui::lerp(
        field.left()..=field.right(),
        ((f.max(1.0) / 20.0).ln() / span).clamp(0.0, 1.0) as f32,
    )
}

fn db_y(field: egui::Rect, db: f64) -> f32 {
    egui::lerp(
        field.bottom()..=field.top(),
        ((db as f32 + 48.0) / 78.0).clamp(0.0, 1.0),
    )
}

/// Inverse of `freq_x`: scope x → frequency (log, 20 Hz → Nyquist).
fn freq_from_x(field: egui::Rect, x: f32) -> f64 {
    let nyq = AUTHORING_RATE * 0.5;
    let t = ((x - field.left()) / field.width()).clamp(0.0, 1.0) as f64;
    20.0 * (nyq / 20.0).powf(t)
}

/// DRAW handle y → pole sharpness (bottom = tame, top = ringing).
fn radius_from_y(field: egui::Rect, y: f32) -> f64 {
    let t = ((field.bottom() - y) / field.height()).clamp(0.0, 1.0) as f64;
    DRAW_R_MIN + (DRAW_R_MAX - DRAW_R_MIN) * t
}

/// DRAW pole sharpness → handle y (inverse of `radius_from_y`).
fn reso_y(field: egui::Rect, radius: f64) -> f32 {
    let t = ((radius - DRAW_R_MIN) / (DRAW_R_MAX - DRAW_R_MIN)).clamp(0.0, 1.0) as f32;
    egui::lerp(field.bottom()..=field.top(), t)
}

fn fmt_hz(f: f64) -> String {
    if f >= 1_000.0 {
        format!("{:.1}k", f / 1_000.0)
    } else {
        format!("{:.0}", f)
    }
}

/// Draw a vowel overlay's F1..F4 ghost marks. F1 emphasised (it carries the
/// vowel's body), F2..F4 quieter (the harmonic colouring). Caller passes the
/// already-clipped painter plus the unclipped one for chips at the foot of
/// the field. `col` distinguishes PB (warm amber) from Klatt (cooler blue).
fn draw_vowel_marks(
    clip: &egui::Painter,
    painter: &egui::Painter,
    field: egui::Rect,
    formants: &[f64; 4],
    col: Color32,
) {
    for (fi, &f) in formants.iter().enumerate() {
        let x = freq_x(field, f);
        let emph = fi == 0;
        clip.line_segment(
            [
                Pos2::new(x, field.top() + 20.0),
                Pos2::new(x, field.bottom() - 22.0),
            ],
            Stroke::new(
                if emph { 1.3 } else { 0.8 },
                alpha(col, if emph { 82 } else { 46 }),
            ),
        );
        chip(
            painter,
            Pos2::new(x, field.bottom() - 12.0),
            &format!("F{}", fi + 1),
            alpha(col, 225),
        );
    }
}

/// A small labelled chip with a backing so text reads against the grid.
fn chip(painter: &egui::Painter, center: Pos2, text: &str, fg: Color32) {
    let w = text.chars().count() as f32 * 6.4 + 10.0;
    let rect = egui::Rect::from_center_size(center, Vec2::new(w, 16.0));
    painter.rect_filled(rect, 3.0, alpha(FIELD, 236));
    painter.rect_stroke(rect, 3.0, Stroke::new(0.8, alpha(fg, 110)));
    painter.text(
        center,
        Align2::CENTER_CENTER,
        text,
        FontId::new(10.0, FontFamily::Monospace),
        fg,
    );
}

/// DESCRIPTIVE actor name from its current frequency — a named actor (the doctrine
/// vocabulary), NOT a stage role. The name follows the actor as it moves; it never
/// pins, clamps, or warns. Orientation only ("that low one is the throat").
fn actor_band_name(freq_hz: f64) -> &'static str {
    match freq_hz {
        f if f < 120.0 => "Sub",
        f if f < 450.0 => "Throat",
        f if f < 1_200.0 => "Body",
        f if f < 3_500.0 => "Bite",
        f if f < 9_000.0 => "Air",
        _ => "Edge",
    }
}

// ── theme + entry ────────────────────────────────────────────────────────────
fn install_theme(ctx: &egui::Context) {
    let mut fonts = egui::FontDefinitions::default();
    let read =
        |paths: &[&str]| -> Option<Vec<u8>> { paths.iter().find_map(|p| std::fs::read(p).ok()) };
    if let Some(b) = read(&[
        "C:/Windows/Fonts/bahnschrift.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]) {
        fonts
            .font_data
            .insert("disp".into(), egui::FontData::from_owned(b));
        fonts
            .families
            .entry(FontFamily::Proportional)
            .or_default()
            .insert(0, "disp".into());
    }
    if let Some(b) = read(&[
        "C:/Windows/Fonts/CascadiaMono.ttf",
        "C:/Windows/Fonts/consola.ttf",
    ]) {
        fonts
            .font_data
            .insert("mono".into(), egui::FontData::from_owned(b));
        fonts
            .families
            .entry(FontFamily::Monospace)
            .or_default()
            .insert(0, "mono".into());
    }
    ctx.set_fonts(fonts);

    let mut visuals = egui::Visuals::dark();
    visuals.panel_fill = FIELD;
    visuals.override_text_color = Some(INK);
    visuals.widgets.noninteractive.bg_fill = FIELD;
    visuals.widgets.inactive.bg_fill = FIELD;
    visuals.widgets.hovered.bg_fill = FIELD;
    ctx.set_visuals(visuals);
}

fn main() -> eframe::Result<()> {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1_100.0, 820.0])
            .with_min_inner_size([900.0, 680.0])
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
