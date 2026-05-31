//! Filter Factory application state and interaction routing.

use crate::audio;
use crate::capture;
use crate::corner_library::CornerLibrary;
use crate::dsp::{corner_to_biquads, magnitude_response, AUTHORING_RATE};
use crate::forge_core::{ForgeCore, CARD_LABELS};
use crate::generators::Architecture;
use crate::{paint, player, push, shape, style};
use eframe::egui;
use egui::{Pos2, Sense, Stroke, Vec2};

#[derive(Clone, Copy, PartialEq, Eq)]
enum Section {
    Shape,
    Player,
    Push,
}

impl Section {
    const ALL: [Section; 3] = [Section::Shape, Section::Player, Section::Push];

    fn label(self) -> &'static str {
        match self {
            Section::Shape => "SHAPE",
            Section::Player => "PLAYER",
            Section::Push => "PUSH",
        }
    }

    fn index(self) -> usize {
        Self::ALL
            .iter()
            .position(|section| *section == self)
            .unwrap()
    }

    fn previous(self) -> Option<Self> {
        self.index().checked_sub(1).map(|index| Self::ALL[index])
    }

    fn next(self) -> Option<Self> {
        Self::ALL.get(self.index() + 1).copied()
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub(crate) enum PathType {
    Diagonal,
    LateNightmare,
    PureQ,
    ZKick,
}

impl PathType {
    pub(crate) const ALL: [PathType; 4] = [
        PathType::Diagonal,
        PathType::LateNightmare,
        PathType::PureQ,
        PathType::ZKick,
    ];

    pub(crate) fn label(self) -> &'static str {
        match self {
            PathType::Diagonal => "diagonal",
            PathType::LateNightmare => "late nightmare",
            PathType::PureQ => "pure Q first",
            PathType::ZKick => "Z kick",
        }
    }

    pub(crate) fn point(self, t: f64) -> (f64, f64) {
        let t = t.clamp(0.0, 1.0);
        match self {
            PathType::Diagonal => (t, t),
            PathType::PureQ => (t, 0.0),
            PathType::ZKick => ((t * 1.6).min(1.0), (t * 2.2).min(1.0)),
            PathType::LateNightmare => (t, ((t - 0.55) / 0.45).clamp(0.0, 1.0)),
        }
    }
}

struct App {
    core: ForgeCore,
    section: Section,
    audio: Option<audio::Audio>,
    capture: Option<capture::Capture>,
    capture_target: usize,
    bad_slot: Option<usize>,
    control_rect: egui::Rect,
    cube_yaw: f32,
    cube_pitch: f32,
    cube_mini: Vec<Vec<[f64; 2]>>,
    cube_mini_rev: u64,
    picker_cards: Vec<egui::Rect>,
    shape_cards: [egui::Rect; 8],
    path_type: PathType,
    play_t: f32,
    player_morph: egui::Rect,
    player_path: egui::Rect,
    player_cube: egui::Rect,
    picking: Option<usize>,
    corner_library: CornerLibrary,
    last_push: Option<String>,
}

impl Default for App {
    fn default() -> Self {
        let mut core = ForgeCore::default();
        core.set_architecture(Architecture::Tube);
        Self {
            core,
            section: Section::Shape,
            audio: audio::start(),
            capture: None,
            capture_target: 0,
            bad_slot: None,
            control_rect: egui::Rect::NOTHING,
            cube_yaw: -0.62,
            cube_pitch: -0.42,
            cube_mini: Vec::new(),
            cube_mini_rev: u64::MAX,
            picker_cards: Vec::new(),
            shape_cards: [egui::Rect::NOTHING; 8],
            path_type: PathType::Diagonal,
            play_t: 0.0,
            player_morph: egui::Rect::NOTHING,
            player_path: egui::Rect::NOTHING,
            player_cube: egui::Rect::NOTHING,
            picking: None,
            corner_library: CornerLibrary::load_default(),
            last_push: None,
        }
    }
}

impl App {
    fn reset(&mut self) {
        self.core.reset();
        self.core.set_architecture(Architecture::Tube);
        self.bad_slot = None;
        self.cube_mini_rev = u64::MAX;
        self.picking = None;
        self.picker_cards.clear();
        self.last_push = None;
        if let Some(audio) = &self.audio {
            audio.set_level(0.85);
        }
    }

    fn push(&mut self) {
        match self.core.save() {
            Ok(path) => {
                self.bad_slot = None;
                self.last_push = Some(format!("WRITTEN / {}", path.display()));
            }
            Err(error) => {
                self.bad_slot = Some(self.core.next_empty());
                eprintln!("forge push blocked: {error}");
                self.last_push = Some("BLOCKED / LOAD ALL FOUR EXPLICIT CORNERS".to_owned());
            }
        }
        self.play_if_ready();
    }

    fn load_bank(&mut self) {
        if self.core.load_legisign_phonetic_bank().is_ok() {
            if let Some(audio) = &self.audio {
                audio.set_source_mode(audio::SourceMode::Saw);
            }
            self.play_if_ready();
        } else {
            self.bad_slot = Some(self.core.next_empty());
        }
    }

    fn toggle_play(&self) {
        if let Some(audio) = &self.audio {
            audio.set_playing(!audio.is_playing());
        }
    }

    fn play_if_ready(&self) {
        if let Some(audio) = &self.audio {
            audio.set_playing(true);
        }
    }

    fn start_capture(&mut self, target: usize) {
        match capture::Capture::start() {
            Ok(capture) => {
                self.capture = Some(capture);
                self.capture_target = target;
                self.bad_slot = self.bad_slot.filter(|bad| *bad != target);
            }
            Err(_) => self.bad_slot = Some(target),
        }
    }

    fn finish_capture(&mut self) {
        let Some(capture) = self.capture.take() else {
            return;
        };
        let target = self.capture_target;
        let sample_rate = capture.sample_rate;
        let samples = capture.drain_mono_f64();
        drop(capture);
        if samples.len() < 64 {
            self.bad_slot = Some(target);
            return;
        }
        self.core.load_samples(
            target,
            &samples,
            sample_rate,
            format!("capture {}", CARD_LABELS[target]),
        );
        self.bad_slot = self.bad_slot.filter(|bad| *bad != target);
        self.play_if_ready();
    }

    fn capture_hotkey(&mut self) {
        if self.capture.is_some() {
            self.finish_capture();
        } else {
            self.start_capture(self.core.next_empty());
        }
    }

    fn load_drop(&mut self, path: &std::path::Path) {
        let target = self.core.next_empty();
        let result = if path.to_string_lossy().ends_with(".corner.json") {
            self.core.load_corner(target, path)
        } else {
            self.core.load_source(target, path)
        };
        if result.is_err() {
            self.bad_slot = Some(target);
        } else {
            self.bad_slot = self.bad_slot.filter(|bad| *bad != target);
            self.play_if_ready();
        }
    }

    fn take_drops(&mut self, ctx: &egui::Context) {
        for file in ctx.input(|input| input.raw.dropped_files.clone()) {
            if let Some(path) = file.path {
                self.load_drop(&path);
                break;
            }
        }
    }

    fn handle_hotkeys(&mut self, ctx: &egui::Context) {
        let (play, push, reset, capture, bank, fit, workspace) = ctx.input(|input| {
            (
                input.key_pressed(egui::Key::Space),
                input.modifiers.command && input.key_pressed(egui::Key::S)
                    || input.key_pressed(egui::Key::Enter),
                input.key_pressed(egui::Key::R)
                    || input.key_pressed(egui::Key::N)
                    || input.key_pressed(egui::Key::Escape),
                !input.modifiers.command && input.key_pressed(egui::Key::C),
                input.key_pressed(egui::Key::B) || input.key_pressed(egui::Key::L),
                input.key_pressed(egui::Key::F),
                if input.key_pressed(egui::Key::Num1) {
                    Some(Section::Shape)
                } else if input.key_pressed(egui::Key::Num2) {
                    Some(Section::Player)
                } else if input.key_pressed(egui::Key::Num3) {
                    Some(Section::Push)
                } else {
                    None
                },
            )
        });
        if let Some(section) = workspace {
            self.section = section;
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
            self.core.set_fit_mode(self.core.fit_mode().next());
        }
    }

    fn push_audio(&self) {
        if let Some(audio) = &self.audio {
            if let Some(corner) = self.core.preview() {
                let mut biquads = corner_to_biquads(&corner);
                stabilize_biquads(&mut biquads);
                audio.set_target(biquads);
            } else {
                audio.clear_target();
            }
        }
    }

    fn refresh_cube_mini(&mut self) {
        let rev = self.core.body_rev();
        if self.cube_mini_rev == rev && self.cube_mini.len() == 8 {
            return;
        }
        if let Some(cube) = self.core.cube() {
            self.cube_mini = (0..8)
                .map(|i| {
                    let response = magnitude_response(&cube.corners[i], AUTHORING_RATE);
                    let n = 28usize;
                    (0..n)
                        .map(|k| response[k * (response.len() - 1) / (n - 1)])
                        .collect()
                })
                .collect();
        }
        self.cube_mini_rev = rev;
    }

    fn cycle_architecture(&mut self) {
        let current = self.core.cube().map(|cube| cube.arch);
        let index = current
            .and_then(|architecture| {
                Architecture::ALL
                    .iter()
                    .position(|candidate| *candidate == architecture)
            })
            .unwrap_or(0);
        self.core
            .set_architecture(Architecture::ALL[(index + 1) % Architecture::ALL.len()]);
        self.play_if_ready();
    }

    fn field(&mut self, ui: &mut egui::Ui) {
        let (response, painter) = ui.allocate_painter(ui.available_size(), Sense::click_and_drag());
        let rect = response.rect;
        let hover_pos = ui.ctx().input(|input| input.pointer.hover_pos());
        painter.rect_filled(rect, 0.0, style::FIELD);
        let field = egui::Rect::from_min_max(
            Pos2::new(rect.left() + 16.0, rect.top() + 112.0),
            Pos2::new(rect.right() - 16.0, rect.bottom() - 16.0),
        );
        paint::schematic_grid(&painter, field);
        let workspace =
            egui::Rect::from_min_max(field.min, Pos2::new(field.right(), field.bottom() - 46.0));

        match self.section {
            Section::Shape => {
                self.refresh_cube_mini();
                let architecture = self
                    .core
                    .cube()
                    .map(|cube| cube.arch.label())
                    .unwrap_or("EMPTY");
                let bar_h = 56.0;
                let cards_area = egui::Rect::from_min_max(
                    workspace.min,
                    Pos2::new(workspace.right(), workspace.bottom() - bar_h - 8.0),
                );
                self.shape_cards = shape::draw_cards(
                    &painter,
                    cards_area,
                    &self.cube_mini,
                    self.picking,
                    architecture,
                );
                let bar = egui::Rect::from_min_max(
                    Pos2::new(workspace.left(), workspace.bottom() - bar_h),
                    workspace.max,
                );
                self.shape_audition_bar(ui, &painter, bar);
                if let Some(corner) = self.picking {
                    let positions = self.corner_library.positions();
                    self.picker_cards = shape::draw_picker(
                        &painter,
                        workspace,
                        corner,
                        self.corner_library.entries(),
                        &positions,
                        hover_pos,
                    );
                }
            }
            Section::Player => {
                let live_response = self
                    .core
                    .preview()
                    .map(|corner| magnitude_response(&corner, AUTHORING_RATE))
                    .unwrap_or_default();
                let areas = player::draw(
                    &painter,
                    workspace,
                    self.core.morph(),
                    self.core.q(),
                    self.core.z(),
                    self.play_t,
                    self.cube_yaw,
                    self.cube_pitch,
                    self.core.cube_weights().unwrap_or([0.0; 8]),
                    &live_response,
                );
                self.player_morph = areas.morph;
                self.player_path = areas.path;
                self.player_cube = areas.cube;
                self.draw_path_selector(ui, &painter, workspace);
            }
            Section::Push => {
                push::draw(
                    &painter,
                    workspace,
                    self.core.publishability_error().as_deref(),
                    self.core.morph_surface_stability(),
                    self.corner_library.entries(),
                    self.core
                        .cube()
                        .map(|cube| cube.arch.label())
                        .unwrap_or("NO FIELD"),
                    self.last_push.as_deref(),
                );
            }
        }

        self.workflow_footer(ui, &painter, field);
        self.section_tabs(ui, &painter, rect);
        self.action_strip(ui, &painter, rect);
        self.handle_pointer(&response);
    }

    fn workflow_footer(&mut self, ui: &mut egui::Ui, painter: &egui::Painter, field: egui::Rect) {
        let line_y = field.bottom() - 38.0;
        paint::rail(
            painter,
            Pos2::new(field.left() + 18.0, line_y),
            Pos2::new(field.right() - 18.0, line_y),
            style::alpha(style::HAIRLINE, 170),
        );
        painter.text(
            Pos2::new(field.left() + 22.0, line_y + 14.0),
            egui::Align2::LEFT_CENTER,
            format!(
                "WORKFLOW  0{} / 0{}",
                self.section.index() + 1,
                Section::ALL.len()
            ),
            style::mono(9.0),
            style::alpha(style::CYAN, 210),
        );
        let back = egui::Rect::from_min_size(
            Pos2::new(field.right() - 270.0, line_y + 4.0),
            Vec2::new(78.0, 26.0),
        );
        let next = egui::Rect::from_min_size(
            Pos2::new(field.right() - 184.0, line_y + 4.0),
            Vec2::new(164.0, 26.0),
        );
        if let Some(previous) = self.section.previous() {
            if paint::button(ui, painter, "workflow-back", back, "BACK", false).clicked() {
                self.section = previous;
                self.picking = None;
            }
        }
        match self.section.next() {
            Some(next_section) => {
                if paint::button(
                    ui,
                    painter,
                    "workflow-next",
                    next,
                    &format!("NEXT / {}", next_section.label()),
                    true,
                )
                .clicked()
                {
                    self.section = next_section;
                    self.picking = None;
                }
            }
            None => {
                if paint::button(ui, painter, "workflow-publish", next, "PUBLISH BODY", true)
                    .clicked()
                {
                    self.push();
                }
            }
        }
    }

    fn section_tabs(&mut self, ui: &mut egui::Ui, painter: &egui::Painter, rect: egui::Rect) {
        let width = ((rect.width() - 32.0) / Section::ALL.len() as f32).min(176.0);
        for (i, section) in Section::ALL.iter().enumerate() {
            let tab = egui::Rect::from_min_size(
                Pos2::new(
                    rect.left() + 16.0 + i as f32 * (width + 6.0),
                    rect.top() + 16.0,
                ),
                Vec2::new(width, 30.0),
            );
            if paint::tab(
                ui,
                painter,
                ("workspace", i),
                tab,
                i + 1,
                section.label(),
                self.section == *section,
            )
            .clicked()
            {
                self.section = *section;
            }
        }
    }

    fn action_strip(&mut self, ui: &mut egui::Ui, painter: &egui::Painter, rect: egui::Rect) {
        let strip = egui::Rect::from_min_size(
            Pos2::new(rect.left() + 16.0, rect.top() + 60.0),
            Vec2::new(rect.width() - 32.0, 38.0),
        );
        painter.rect_filled(strip, 4.0, style::alpha(style::WELL, 248));
        painter.rect_stroke(
            strip,
            4.0,
            Stroke::new(1.0, style::alpha(style::HAIRLINE, 210)),
        );

        let mut x = strip.left() + 8.0;
        let mut next = |width: f32| {
            let button =
                egui::Rect::from_min_size(Pos2::new(x, strip.top() + 6.0), Vec2::new(width, 26.0));
            x += width + 6.0;
            button
        };
        let playing = self
            .audio
            .as_ref()
            .map(|audio| audio.is_playing())
            .unwrap_or(false);
        if paint::button(
            ui,
            painter,
            "play",
            next(58.0),
            if playing { "STOP" } else { "PLAY" },
            playing,
        )
        .clicked()
        {
            self.toggle_play();
        }
        if let Some(audio) = &self.audio {
            let mode = audio.source_mode();
            if paint::toggle(
                ui,
                painter,
                "pink",
                next(52.0),
                "PINK",
                mode == audio::SourceMode::Pink,
            )
            .clicked()
            {
                audio.set_source_mode(audio::SourceMode::Pink);
                self.play_if_ready();
            }
            if paint::toggle(
                ui,
                painter,
                "saw",
                next(48.0),
                "SAW",
                mode == audio::SourceMode::Saw,
            )
            .clicked()
            {
                audio.set_source_mode(audio::SourceMode::Saw);
                self.play_if_ready();
            }
        }
        if paint::button(ui, painter, "gen", next(54.0), "GEN+", false).clicked() {
            self.cycle_architecture();
        }
        if self.core.cube_fsm().is_some() {
            if paint::button(ui, painter, "done", next(58.0), "DONE", true).clicked() {
                self.core.exit_cube_edit();
            }
        } else if self.core.cube().is_some() {
            let mut z = self.core.z();
            if paint::slider(ui, painter, "z-transform", next(150.0), "XFORM", &mut z).changed() {
                self.core.set_z(z);
            }
        }
        if paint::button(
            ui,
            painter,
            "push",
            next(58.0),
            "PUSH",
            self.section == Section::Push,
        )
        .clicked()
        {
            self.section = Section::Push;
            self.picking = None;
        }
        if paint::button(ui, painter, "reset", next(62.0), "RESET", false).clicked() {
            self.reset();
        }
        let current = self
            .core
            .cube()
            .map(|cube| cube.arch.label())
            .unwrap_or("NO FIELD");
        paint::readout(
            painter,
            egui::Rect::from_min_size(
                Pos2::new(strip.right() - 194.0, strip.top() + 5.0),
                Vec2::new(186.0, 28.0),
            ),
            "ACTIVE FIELD",
            current,
            true,
        );
        self.control_rect = strip;
    }

    /// SHAPE's live-middle dock: sweep the interpolation point (Morph × Q) while
    /// composing corners — so you hear the emergent MIDDLE, not a frozen corner —
    /// with a continuous readout that flags when that middle rings out (the same
    /// morph-surface stability scan PUSH enforces). Z stays on the XFORM control.
    fn shape_audition_bar(&mut self, ui: &mut egui::Ui, painter: &egui::Painter, bar: egui::Rect) {
        painter.rect_filled(bar, 5.0, style::alpha(style::WELL, 250));
        painter.rect_stroke(bar, 5.0, Stroke::new(1.0, style::alpha(style::HAIRLINE, 200)));
        painter.text(
            Pos2::new(bar.left() + 12.0, bar.top() + 8.0),
            egui::Align2::LEFT_TOP,
            "AUDITION MIDDLE",
            style::mono(8.0),
            style::alpha(style::CYAN, 220),
        );

        let mut morph = self.core.morph();
        let morph_rect = egui::Rect::from_min_size(
            Pos2::new(bar.left() + 14.0, bar.top() + 25.0),
            Vec2::new(150.0, 22.0),
        );
        if paint::slider(ui, painter, "shape-morph", morph_rect, "MORPH", &mut morph).changed() {
            self.core.set_puck(morph, self.core.q());
            self.play_if_ready();
        }
        let mut q = self.core.q();
        let q_rect = egui::Rect::from_min_size(
            Pos2::new(morph_rect.right() + 18.0, bar.top() + 25.0),
            Vec2::new(150.0, 22.0),
        );
        if paint::slider(ui, painter, "shape-q", q_rect, "Q", &mut q).changed() {
            self.core.set_puck(self.core.morph(), q);
            self.play_if_ready();
        }

        let curve_rect = egui::Rect::from_min_max(
            Pos2::new(q_rect.right() + 20.0, bar.top() + 8.0),
            Pos2::new(bar.right() - 244.0, bar.bottom() - 8.0),
        );
        if curve_rect.width() > 50.0 {
            if let Some(corner) = self.core.preview() {
                let response = magnitude_response(&corner, AUTHORING_RATE);
                draw_mid_sparkline(painter, curve_rect, &response);
            }
        }

        let chip = egui::Rect::from_min_size(
            Pos2::new(bar.right() - 232.0, bar.top() + 13.0),
            Vec2::new(220.0, 30.0),
        );
        let (value, ok) = match self.core.morph_surface_stability() {
            Some((r, (m, q))) => {
                let ok = r <= crate::dsp::STABILITY_RADIUS_LIMIT;
                (
                    format!(
                        "r {:.3} @ {:02}/{:02}  {}",
                        r,
                        (m * 100.0) as u32,
                        (q * 100.0) as u32,
                        if ok { "STABLE" } else { "RING-OUT" }
                    ),
                    ok,
                )
            }
            None => ("NO FIELD".to_owned(), true),
        };
        let edge = if ok { style::PHOSPHOR } else { style::CLIP };
        painter.rect_filled(chip, 3.0, style::alpha(style::WELL, 245));
        painter.rect_stroke(chip, 3.0, Stroke::new(1.0, style::alpha(edge, 205)));
        painter.text(
            chip.left_center() + Vec2::new(8.0, -6.0),
            egui::Align2::LEFT_CENTER,
            "MIDDLE STABILITY",
            style::mono(7.0),
            style::alpha(style::CYAN, 205),
        );
        painter.text(
            chip.left_center() + Vec2::new(8.0, 7.0),
            egui::Align2::LEFT_CENTER,
            &value,
            style::mono(8.5),
            edge,
        );
    }

    /// PLAYER's route picker (folded in from the old TRAJECTORY tab): choose which
    /// path the Player's PATH roller tours through the Q × Transform plane, and
    /// audition it by ear in the same view.
    fn draw_path_selector(&mut self, ui: &mut egui::Ui, painter: &egui::Painter, area: egui::Rect) {
        let w = 150.0;
        let x = area.right() - w - 26.0;
        let y0 = area.top() + 244.0;
        painter.text(
            Pos2::new(x, y0 - 8.0),
            egui::Align2::LEFT_BOTTOM,
            "ROUTE / Q × XFORM",
            style::mono(8.0),
            style::alpha(style::CYAN, 210),
        );
        for (i, path) in PathType::ALL.iter().enumerate() {
            let rect =
                egui::Rect::from_min_size(Pos2::new(x, y0 + i as f32 * 30.0), Vec2::new(w, 24.0));
            let active = self.path_type == *path;
            if paint::button(ui, painter, ("route", i), rect, &path.label().to_uppercase(), active)
                .clicked()
            {
                self.path_type = *path;
                self.play_if_ready();
            }
        }
    }

    fn handle_pointer(&mut self, response: &egui::Response) {
        let Some(pointer) = response.interact_pointer_pos() else {
            return;
        };
        if self.control_rect.contains(pointer) {
            return;
        }
        match self.section {
            Section::Shape => {
                if let Some(corner) = self.picking {
                    if response.clicked() {
                        for (i, rect) in self.picker_cards.iter().enumerate() {
                            if rect.contains(pointer) {
                                match self.corner_library.load_corner(i) {
                                    Ok(posture) => {
                                        self.core.assign_cube_corner_data(corner, posture);
                                        self.picking = None;
                                        self.play_if_ready();
                                    }
                                    Err(error) => {
                                        eprintln!("corner library assignment failed: {error}");
                                    }
                                }
                                return;
                            }
                        }
                        self.picking = None;
                    }
                    return;
                }
                if response.clicked() {
                    for (i, rect) in self.shape_cards.iter().enumerate() {
                        if rect.contains(pointer) {
                            self.picking = Some(i);
                            return;
                        }
                    }
                }
            }
            Section::Player if response.dragged() || response.clicked() => {
                if self.player_morph.contains(pointer) {
                    let morph = ((pointer.x - self.player_morph.left())
                        / self.player_morph.width())
                    .clamp(0.0, 1.0);
                    self.core.set_puck(morph, self.core.q());
                } else if self.player_path.contains(pointer) {
                    self.play_t = ((pointer.x - self.player_path.left())
                        / self.player_path.width())
                    .clamp(0.0, 1.0);
                    let (q, z) = self.path_type.point(self.play_t as f64);
                    self.core.set_puck(self.core.morph(), q as f32);
                    self.core.set_z(z as f32);
                } else if self.player_cube.contains(pointer) && response.dragged() {
                    let delta = response.drag_delta();
                    self.cube_yaw += delta.x * 0.01;
                    self.cube_pitch = (self.cube_pitch + delta.y * 0.01).clamp(-1.3, 1.3);
                }
            }
            _ => {}
        }
    }
}

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        if self
            .capture
            .as_ref()
            .map(|capture| capture.elapsed_secs() >= capture::CAPTURE_SECS)
            .unwrap_or(false)
        {
            self.finish_capture();
        }
        self.handle_hotkeys(ctx);
        self.take_drops(ctx);
        self.push_audio();
        egui::CentralPanel::default()
            .frame(egui::Frame::none().fill(style::FIELD))
            .show(ctx, |ui| self.field(ui));
        ctx.request_repaint_after(std::time::Duration::from_millis(16));
    }
}

fn draw_mid_sparkline(painter: &egui::Painter, rect: egui::Rect, response: &[[f64; 2]]) {
    painter.rect_filled(rect, 3.0, style::alpha(style::SCREEN, 240));
    painter.rect_stroke(rect, 3.0, Stroke::new(0.8, style::alpha(style::GRID, 180)));
    painter.text(
        rect.left_top() + Vec2::new(6.0, 4.0),
        egui::Align2::LEFT_TOP,
        "LIVE MIDDLE",
        style::mono(7.0),
        style::alpha(style::CYAN, 200),
    );
    if response.len() < 2 {
        return;
    }
    let n = response.len();
    let points: Vec<Pos2> = (0..n)
        .map(|i| {
            let x = rect.left() + rect.width() * i as f32 / (n - 1) as f32;
            let y = rect.bottom()
                - rect.height() * (((response[i][1] as f32) + 48.0) / 78.0).clamp(0.0, 1.0);
            Pos2::new(x, y)
        })
        .collect();
    painter.add(egui::Shape::line(
        points.clone(),
        Stroke::new(5.0, style::alpha(style::PHOSPHOR, 36)),
    ));
    painter.add(egui::Shape::line(points, Stroke::new(1.7, style::PHOSPHOR)));
}

fn stabilize_biquads(biquads: &mut [[f64; 5]; crate::dsp::POLE_ZERO_COUNT]) {
    const LIMIT: f64 = 0.997;
    for stage in biquads.iter_mut() {
        let radius = stage[4].max(0.0).sqrt();
        if radius > LIMIT {
            let factor = LIMIT / radius;
            stage[3] *= factor;
            stage[4] = LIMIT * LIMIT;
        }
        if !stage.iter().all(|value| value.is_finite()) {
            *stage = [1.0, 0.0, 0.0, 0.0, 0.0];
        }
    }
}

pub fn run() -> eframe::Result<()> {
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
        Box::new(|context| {
            style::install(&context.egui_ctx);
            Ok(Box::new(App::default()))
        }),
    )
}
