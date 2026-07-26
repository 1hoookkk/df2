//! TRENCH Surface Forge — smallest useful native surface over the retained
//! `AppState` API. One toolbar plus four working panes: travel pad,
//! packed/runtime response, lane registration locker, edit/export.
//!
//! M50_Q50 is a view coordinate, never a stored keyframe. Tension (exact
//! interior solve) is disabled in this build: no core-owned TensionRequest
//! path exists yet, and the frontend must not fake exact interior edits.

use eframe::egui::{
    self, Align, Align2, Color32, FontId, Layout, Pos2, Rect, Response, RichText, Rounding, Sense,
    Stroke, Vec2,
};
use rodio::{Decoder, OutputStream, Sink, Source};
use std::fs::{self, File};
use std::io::BufReader;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use trench_core::cartridge::Cartridge;
use trench_core::engine::{FilterEngine, InputMode, SpatialMode};
use trench_core::response::biquad_stage_mag_db;
use trench_core::stage_law::STAGE_SR;
use trench_workstation::app::AppState;
use trench_workstation::model::{
    AudioMode, EditField, EditRequest, RootGeometry, ScreenData, StageSnapshot,
};
use trench_workstation::source_xml::SourceEndpoint;

const BG: Color32 = Color32::from_rgb(18, 20, 23);
const PANEL: Color32 = Color32::from_rgb(24, 27, 31);
const PANEL_RAISED: Color32 = Color32::from_rgb(29, 33, 38);
const LINE: Color32 = Color32::from_rgb(51, 57, 65);
const TEXT: Color32 = Color32::from_rgb(230, 233, 237);
const MUTED: Color32 = Color32::from_rgb(143, 151, 161);
const ACCENT: Color32 = Color32::from_rgb(70, 184, 151);
const ACCENT_SOFT: Color32 = Color32::from_rgb(42, 94, 82);
const WARN: Color32 = Color32::from_rgb(232, 173, 81);
const ERROR: Color32 = Color32::from_rgb(231, 102, 108);
/// Fixed dB scale for the whole session. Never re-normalized per render.
const DB_MIN: f64 = -48.0;
const DB_MAX: f64 = 24.0;
const CORNER_LABELS: [&str; 4] = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];
const AUDITION_BLOCK: usize = 64;

#[derive(Clone, Copy, PartialEq, Eq)]
enum RootSide {
    Pole,
    Zero,
}

impl RootSide {
    fn label(self) -> &'static str {
        match self {
            Self::Pole => "pole",
            Self::Zero => "zero",
        }
    }
}

#[derive(Clone, Copy)]
struct SideLocks {
    pole: bool,
    zero: bool,
}

impl SideLocks {
    const LOCKED: Self = Self {
        pole: true,
        zero: true,
    };

    fn get(&self, side: RootSide) -> bool {
        match side {
            RootSide::Pole => self.pole,
            RootSide::Zero => self.zero,
        }
    }

    fn toggle(&mut self, side: RootSide) {
        match side {
            RootSide::Pole => self.pole = !self.pole,
            RootSide::Zero => self.zero = !self.zero,
        }
    }
}

/// Fields the edit pane can target. Conjugate fields exist only for
/// conjugate rows; real-root rows only ever expose their explicit roots.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum PaneField {
    PoleHz,
    PoleRadius,
    PoleRootA,
    PoleRootB,
    ZeroHz,
    ZeroRadius,
    ZeroRootA,
    ZeroRootB,
    Scale,
}

impl PaneField {
    fn side(self) -> Option<RootSide> {
        match self {
            Self::PoleHz | Self::PoleRadius | Self::PoleRootA | Self::PoleRootB => {
                Some(RootSide::Pole)
            }
            Self::ZeroHz | Self::ZeroRadius | Self::ZeroRootA | Self::ZeroRootB => {
                Some(RootSide::Zero)
            }
            Self::Scale => None,
        }
    }

    #[cfg(test)]
    fn is_real_root(self) -> bool {
        matches!(
            self,
            Self::PoleRootA | Self::PoleRootB | Self::ZeroRootA | Self::ZeroRootB
        )
    }

    fn label(self) -> &'static str {
        match self {
            Self::PoleHz => "Pole freq (oct)",
            Self::PoleRadius => "Pole radius (Δ)",
            Self::PoleRootA => "Pole root A (abs)",
            Self::PoleRootB => "Pole root B (abs)",
            Self::ZeroHz => "Zero freq (oct)",
            Self::ZeroRadius => "Zero radius (Δ)",
            Self::ZeroRootA => "Zero root A (abs)",
            Self::ZeroRootB => "Zero root B (abs)",
            Self::Scale => "Scale (oct)",
        }
    }

    fn delta_hint(self) -> &'static str {
        match self {
            Self::PoleHz | Self::ZeroHz | Self::Scale => "octaves",
            Self::PoleRadius | Self::ZeroRadius => "Δ radius",
            _ => "Δ value",
        }
    }
}

/// Topology-filtered field list: a real-root row can never enter a
/// conjugate editor from this surface.
fn fields_for_geometry(geometry: &RootGeometry, side: RootSide) -> Vec<PaneField> {
    match (geometry, side) {
        (RootGeometry::Conjugate { .. }, RootSide::Pole) => {
            vec![PaneField::PoleHz, PaneField::PoleRadius]
        }
        (RootGeometry::RealPair { .. }, RootSide::Pole) => {
            vec![PaneField::PoleRootA, PaneField::PoleRootB]
        }
        (RootGeometry::Conjugate { .. }, RootSide::Zero) => {
            vec![PaneField::ZeroHz, PaneField::ZeroRadius]
        }
        (RootGeometry::RealPair { .. }, RootSide::Zero) => {
            vec![PaneField::ZeroRootA, PaneField::ZeroRootB]
        }
        (RootGeometry::Degenerate, _) => Vec::new(),
    }
}

fn available_fields(stage: &StageSnapshot) -> Vec<PaneField> {
    let mut fields = fields_for_geometry(&stage.pole, RootSide::Pole);
    fields.extend(fields_for_geometry(&stage.zero, RootSide::Zero));
    fields.push(PaneField::Scale);
    fields
}

// ---------------------------------------------------------------------------
// Audition monitor: UI thread owns AppState; the rodio thread owns the
// FilterEngine. The only things crossing the boundary are bounded scalar
// Morph/Q updates and a body swap (fresh engine) at a block boundary.
// ---------------------------------------------------------------------------

struct AuditionControl {
    morph: f64,
    q: f64,
    reload: Option<FilterEngine>,
}

struct AuditionStream {
    engine: FilterEngine,
    wav: Arc<Vec<f32>>,
    cursor: usize,
    control: Arc<Mutex<AuditionControl>>,
    buf: Vec<f32>,
    right: Vec<f32>,
    pos: usize,
}

impl AuditionStream {
    fn refill(&mut self) {
        let wav_len = self.wav.len().max(1);
        let (morph, q, reload) = {
            let mut control = self.control.lock().unwrap();
            (control.morph, control.q, control.reload.take())
        };
        if let Some(engine) = reload {
            self.engine = engine;
        }
        self.buf.clear();
        for _ in 0..AUDITION_BLOCK {
            self.buf.push(self.wav[self.cursor % wav_len]);
            self.cursor += 1;
        }
        self.right.clear();
        self.right.extend_from_slice(&self.buf);
        self.engine.process_block(&mut self.buf, &mut self.right, morph, q);
        self.pos = 0;
    }
}

impl Iterator for AuditionStream {
    type Item = f32;

    fn next(&mut self) -> Option<f32> {
        if self.pos >= self.buf.len() {
            self.refill();
        }
        let sample = self.buf[self.pos];
        self.pos += 1;
        Some(sample)
    }
}

impl Source for AuditionStream {
    fn current_frame_len(&self) -> Option<usize> {
        None
    }

    fn channels(&self) -> u16 {
        1
    }

    fn sample_rate(&self) -> u32 {
        STAGE_SR as u32
    }

    fn total_duration(&self) -> Option<Duration> {
        None
    }
}

// ---------------------------------------------------------------------------
// Packed-runtime pole/zero markers, factored from probe rows. Never from
// geometry JSON, never from authored structs: the plotted marker is what the
// packed runtime actually decodes to at the current Morph/Q.
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug, PartialEq)]
enum RootMark {
    Conjugate { hz: f64, radius: f64 },
    Real([f64; 2]),
    Degenerate,
}

fn roots_from_probe_row(row: &[f64; 5], side: RootSide) -> RootMark {
    // H(z) = (b0 + b1 z^-1 + b2 z^-2) / (1 + a1 z^-1 + a2 z^-2)
    let (c2, c1, c0) = match side {
        RootSide::Pole => (1.0, row[3], row[4]),
        RootSide::Zero => (row[0], row[1], row[2]),
    };
    if c2.abs() < 1e-12 {
        return RootMark::Degenerate;
    }
    let discriminant = c1 * c1 - 4.0 * c2 * c0;
    if discriminant < 0.0 {
        let re = -c1 / (2.0 * c2);
        let im = (-discriminant).sqrt() / (2.0 * c2.abs());
        let radius = (re * re + im * im).sqrt();
        let hz = im.atan2(re) / std::f64::consts::TAU * STAGE_SR;
        RootMark::Conjugate { hz, radius }
    } else {
        let root = discriminant.sqrt();
        let a = (-c1 + root) / (2.0 * c2);
        let b = (-c1 - root) / (2.0 * c2);
        if a.abs() < 1e-9 && b.abs() < 1e-9 {
            RootMark::Degenerate
        } else {
            RootMark::Real([a, b])
        }
    }
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

struct ForgeApp {
    state: AppState,
    body_path: Option<PathBuf>,
    locks: [[SideLocks; 6]; 4],
    corner_mask: [bool; 4],
    mode: AudioMode,
    status: String,
    status_error: bool,
    receipt: String,
    stream: Option<OutputStream>,
    sink: Option<Sink>,
    control: Option<Arc<Mutex<AuditionControl>>>,
    wav_path: Option<PathBuf>,
    actor_wavs: Vec<PathBuf>,
    actor_wav: usize,
    recipe_sel: usize,
    source_sel: usize,
    endpoint_high: bool,
    field: PaneField,
    delta: f64,
    drag: Option<RootSide>,
}

impl ForgeApp {
    fn new(repo_root: PathBuf) -> Result<Self, String> {
        let state = AppState::new(&repo_root).map_err(|error| error.to_string())?;
        let mut app = Self {
            state,
            body_path: None,
            locks: [[SideLocks::LOCKED; 6]; 4],
            corner_mask: [true; 4],
            mode: AudioMode::BodySolo,
            status: "Silent · open a body or audition the starter".to_owned(),
            status_error: false,
            receipt: String::new(),
            stream: None,
            sink: None,
            control: None,
            wav_path: first_audition_wav(&repo_root),
            actor_wavs: collect_actor_wavs(&repo_root),
            actor_wav: 0,
            recipe_sel: 0,
            source_sel: 0,
            endpoint_high: false,
            field: PaneField::PoleHz,
            delta: 0.0,
            drag: None,
        };
        if let Some(path) = first_body(&repo_root) {
            app.load_body(path);
        } else {
            app.state
                .set_morph_q(0.0, 0.0)
                .map_err(|error| error.to_string())?;
        }
        Ok(app)
    }

    /// Screen honors a pending preview so plots/markers/readouts show the
    /// exact packed candidate; the committed audit stays attached.
    fn screen(&self) -> Result<ScreenData, String> {
        if let Some(preview) = &self.state.pending_edit {
            preview
                .after_session
                .screen_with_audit(
                    self.state.selected_corner,
                    self.state.selected_lane,
                    self.state.morph,
                    self.state.q,
                    self.state.audit.clone(),
                )
                .map_err(|error| error.to_string())
        } else {
            self.state.screen().map_err(|error| error.to_string())
        }
    }

    fn set_status(&mut self, value: impl Into<String>) {
        self.status = value.into();
        self.status_error = false;
    }

    fn set_error(&mut self, value: impl Into<String>) {
        self.status = value.into();
        self.status_error = true;
    }

    /// Travel pad is a read/audition coordinate. It writes two f64 fields and
    /// the audition control block; it never touches session body bytes.
    fn set_pad(&mut self, morph: f64, q: f64) {
        let morph = morph.clamp(0.0, 1.0);
        let q = q.clamp(0.0, 1.0);
        if let Err(error) = self.state.set_morph_q(morph, q) {
            self.set_error(error.to_string());
            return;
        }
        if let Some(control) = &self.control {
            let mut control = control.lock().unwrap();
            control.morph = morph;
            control.q = q;
        }
    }

    fn load_body(&mut self, path: PathBuf) {
        // Frictionless audition: keep the pad position and keep the monitor
        // playing across a body switch — same listen point, new body.
        match self.state.load_body_as_session(&path) {
            Ok(_) => {
                self.locks = [[SideLocks::LOCKED; 6]; 4];
                self.drag = None;
                self.receipt.clear();
                self.body_path = Some(path.clone());
                if let Some(control) = &self.control {
                    let mut control = control.lock().unwrap();
                    control.morph = self.state.morph;
                    control.q = self.state.q;
                }
                self.reload_monitor();
                self.set_status(format!(
                    "Loaded {} · poles and zeros locked",
                    body_name(&path)
                ));
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn working_body_bytes(&self) -> Result<[u8; 240], String> {
        self.state
            .session
            .to_body_bytes()
            .map_err(|error| error.to_string())
    }

    fn reload_monitor(&mut self) {
        let Some(control) = self.control.clone() else {
            return;
        };
        let body = match self.working_body_bytes() {
            Ok(body) => body,
            Err(error) => {
                self.set_error(error);
                return;
            }
        };
        match build_audition_engine(&body, self.mode) {
            Ok(engine) => control.lock().unwrap().reload = Some(engine),
            Err(error) => self.set_error(error),
        }
    }

    fn stop_audio(&mut self) {
        if let Some(sink) = self.sink.take() {
            sink.stop();
        }
        self.stream = None;
        self.control = None;
    }

    fn toggle_audio(&mut self) {
        if self.sink.is_some() {
            self.stop_audio();
            self.set_status("Audition stopped · silent");
            return;
        }
        let Some(wav_path) = self.wav_path.clone() else {
            self.set_error("No WAV source under wav-source-library for the audition monitor");
            return;
        };
        let body = match self.working_body_bytes() {
            Ok(body) => body,
            Err(error) => {
                self.set_error(error);
                return;
            }
        };
        let engine = match build_audition_engine(&body, self.mode) {
            Ok(engine) => engine,
            Err(error) => {
                self.set_error(error);
                return;
            }
        };
        let wav = match decode_wav_to_stage_sr(&wav_path) {
            Ok(samples) => Arc::new(samples),
            Err(error) => {
                self.set_error(error);
                return;
            }
        };
        let (stream, handle) = match OutputStream::try_default() {
            Ok(value) => value,
            Err(error) => {
                self.set_error(format!("audio output is unavailable: {error}"));
                return;
            }
        };
        let sink = match Sink::try_new(&handle) {
            Ok(value) => value,
            Err(error) => {
                self.set_error(format!("audio output could not start: {error}"));
                return;
            }
        };
        let control = Arc::new(Mutex::new(AuditionControl {
            morph: self.state.morph,
            q: self.state.q,
            reload: None,
        }));
        let source = AuditionStream {
            engine,
            wav,
            cursor: 0,
            control: control.clone(),
            buf: Vec::with_capacity(AUDITION_BLOCK),
            right: Vec::with_capacity(AUDITION_BLOCK),
            pos: 0,
        };
        // Fixed monitor attenuation (~-12 dB); visible, conservative, and
        // never touches the packed body or the saved renders.
        sink.set_volume(0.25);
        sink.append(source);
        sink.play();
        self.stream = Some(stream);
        self.sink = Some(sink);
        self.control = Some(control);
        self.set_status(format!(
            "Auditioning {} · {} · monitor -12 dB · pad drives Morph/Q live",
            body_name(&wav_path),
            if self.mode == AudioMode::BodySolo {
                "BODY SOLO"
            } else {
                "PRODUCT"
            }
        ));
    }

    fn set_mode(&mut self, mode: AudioMode) {
        self.mode = mode;
        self.reload_monitor();
    }

    /// Corners an edit may touch: explicit toggles intersected with the lane
    /// locks. A lock is a refusal boundary, never a silent clamp.
    fn editable_corners(&self, lane: usize, side: Option<RootSide>) -> Vec<usize> {
        (0..4)
            .filter(|&corner| {
                self.corner_mask[corner]
                    && side.map_or(true, |side| !self.locks[corner][lane].get(side))
            })
            .collect()
    }

    fn build_request(&self, screen: &ScreenData) -> Result<EditRequest, String> {
        let lane = screen.selected_lane;
        let side = self.field.side();
        let corners = self.editable_corners(lane, side);
        if corners.is_empty() {
            return Err(format!(
                "no editable corner contributes for {} on S{} — unlock the lane or enable a corner",
                self.field.label(),
                lane + 1
            ));
        }
        let request = match self.field {
            PaneField::PoleHz | PaneField::ZeroHz => EditRequest {
                corner_indices: corners,
                lane_indices: vec![lane],
                field: if self.field == PaneField::PoleHz {
                    EditField::PoleGeometry
                } else {
                    EditField::ZeroGeometry
                },
                value: self.delta,
                secondary_value: Some(0.0),
                relative: true,
            },
            PaneField::PoleRadius | PaneField::ZeroRadius => EditRequest {
                corner_indices: corners,
                lane_indices: vec![lane],
                field: if self.field == PaneField::PoleRadius {
                    EditField::PoleGeometry
                } else {
                    EditField::ZeroGeometry
                },
                value: 0.0,
                secondary_value: Some(self.delta),
                relative: true,
            },
            PaneField::Scale => EditRequest {
                corner_indices: corners,
                lane_indices: vec![lane],
                field: EditField::Scale,
                value: self.delta,
                secondary_value: None,
                relative: true,
            },
            PaneField::PoleRootA
            | PaneField::PoleRootB
            | PaneField::ZeroRootA
            | PaneField::ZeroRootB => {
                // Real-root edits stay explicit: one corner, absolute value.
                if corners != [screen.selected_corner] {
                    return Err(
                        "real-root edits are explicit and single-corner — set the corner mask to the selected corner only"
                            .to_owned(),
                    );
                }
                let geometry = match self.field.side() {
                    Some(RootSide::Pole) => &screen.selected_stage.pole,
                    _ => &screen.selected_stage.zero,
                };
                let current = match (geometry, self.field) {
                    (RootGeometry::RealPair { root_a, .. }, PaneField::PoleRootA)
                    | (RootGeometry::RealPair { root_a, .. }, PaneField::ZeroRootA) => *root_a,
                    (RootGeometry::RealPair { root_b, .. }, PaneField::PoleRootB)
                    | (RootGeometry::RealPair { root_b, .. }, PaneField::ZeroRootB) => *root_b,
                    _ => {
                        return Err(format!(
                            "{} is not offered for this row's topology",
                            self.field.label()
                        ))
                    }
                };
                let edit_field = match self.field {
                    PaneField::PoleRootA => EditField::PoleRootA,
                    PaneField::PoleRootB => EditField::PoleRootB,
                    PaneField::ZeroRootA => EditField::ZeroRootA,
                    _ => EditField::ZeroRootB,
                };
                EditRequest::single(
                    screen.selected_corner,
                    lane,
                    edit_field,
                    current + self.delta,
                )
            }
        };
        Ok(request)
    }

    fn preview_edit(&mut self, request: EditRequest) {
        match self.state.preview(request) {
            Ok(preview) => {
                let corners = preview
                    .request
                    .corner_indices
                    .iter()
                    .map(|&corner| CORNER_LABELS[corner])
                    .collect::<Vec<_>>()
                    .join(" ");
                self.set_status(format!(
                    "Previewing {} on {} · S{} · Apply commits one undo step · monitor stays on committed body",
                    preview.request.field.as_str(),
                    corners,
                    preview.request.lane_indices.first().map_or(0, |lane| lane + 1)
                ));
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn preview_pane_request(&mut self, screen: &ScreenData) {
        match self.build_request(screen) {
            Ok(request) => self.preview_edit(request),
            Err(error) => self.set_error(error),
        }
    }

    fn apply(&mut self) {
        if self.state.pending_edit.is_none() {
            return;
        }
        match self.state.apply() {
            Ok(result) => {
                self.receipt = apply_receipt(&result);
                self.set_status(format!(
                    "Applied · {} packed words changed · audit {} · parity {}",
                    result.changed_words.len(),
                    if result.audit_after.pass { "PASS" } else { "FAIL" },
                    if result.cartridge_parity_after {
                        "OK"
                    } else {
                        "MISMATCH"
                    }
                ));
                self.reload_monitor();
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn cancel_preview(&mut self) {
        if self.state.pending_edit.is_some() {
            self.state.discard_preview();
            self.set_status("Preview discarded · committed body unchanged");
        }
    }

    fn undo(&mut self) {
        match self.state.undo() {
            Ok(()) => {
                self.receipt.clear();
                self.set_status("Undid one edit gesture");
                self.reload_monitor();
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn redo(&mut self) {
        match self.state.redo() {
            Ok(()) => {
                self.receipt.clear();
                self.set_status("Redid one edit gesture");
                self.reload_monitor();
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn export(&mut self) {
        match self.state.keep() {
            Ok(receipt) => self.set_status(format!(
                "Exported · {} · body_solo.wav + product.wav + session + audit inside",
                receipt.directory
            )),
            Err(error) => self.set_error(error.to_string()),
        }
    }

    // -- make paths: rich disk data -> certified body, all through AppState --

    /// One retained pole scaffold from owned audio: LPC runs exactly once,
    /// six registered actors, zeros stay the explicit authoring layer.
    fn make_from_audio(&mut self) {
        let Some(path) = self.actor_wavs.get(self.actor_wav).cloned() else {
            self.set_error("No actor WAVs under wav-source-library/measured_objects");
            return;
        };
        let result = decode_wav_mono(&path).and_then(|(samples, rate)| {
            self.state
                .load_fixed_actor_audio(&samples, rate as f64, &path)
                .map_err(|error| error.to_string())
        });
        match result {
            Ok(report) => {
                self.reload_monitor();
                self.set_status(format!(
                    "Made body from {} · {} registered actors · audit {} · parity {}",
                    body_name(&path),
                    report.lanes.len(),
                    if report.sampled_audit_after.pass {
                        "PASS"
                    } else {
                        "FAIL"
                    },
                    if report.cartridge_parity_after {
                        "OK"
                    } else {
                        "MISMATCH"
                    }
                ));
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    /// One iconic recipe candidate applied to the current pole scaffold:
    /// zero-only authoring, certified before it lands.
    fn make_from_recipe(&mut self) {
        let index = self.recipe_sel;
        match self.state.apply_recipe(index) {
            Ok(report) => {
                self.reload_monitor();
                self.set_status(format!(
                    "Recipe {} applied · {} zero words opened · audit PASS",
                    report.candidate.candidate_id,
                    report.changed_words.len()
                ));
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    /// Heritage designer stages fill the selected corner of the current body.
    fn make_fill_corner(&mut self) {
        let corner = self.state.selected_corner;
        let endpoint = if self.endpoint_high {
            SourceEndpoint::High
        } else {
            SourceEndpoint::Low
        };
        let source_name = self
            .state
            .source_catalog
            .sources
            .get(self.source_sel)
            .map(|source| source.name.clone())
            .unwrap_or_default();
        match self
            .state
            .fill_corner_from_source(corner, self.source_sel, endpoint)
        {
            Ok(report) => {
                self.reload_monitor();
                self.set_status(format!(
                    "Filled {} from {} ({}) · {} words changed · audit {}",
                    CORNER_LABELS[corner],
                    source_name,
                    endpoint.as_str(),
                    report.changed_words.len(),
                    if report.sampled_audit_after.pass {
                        "PASS"
                    } else {
                        "FAIL"
                    }
                ));
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    // -- panes --------------------------------------------------------------

    fn toolbar(&mut self, ctx: &egui::Context, screen: &ScreenData) {
        egui::TopBottomPanel::top("toolbar")
            .exact_height(46.0)
            .frame(
                egui::Frame::none()
                    .fill(PANEL)
                    .inner_margin(egui::Margin::symmetric(12.0, 7.0)),
            )
            .show(ctx, |ui| {
                ui.horizontal(|ui| {
                    if quiet_button(ui, "OPEN BODY…", true).clicked() {
                        let dialog = rfd::FileDialog::new()
                            .add_filter("TRENCH body", &["body240"])
                            .set_directory(
                                self.state.repo_root.join("filters").join("bodies"),
                            );
                        if let Some(path) = dialog.pick_file() {
                            self.load_body(path);
                        }
                    }
                    separator(ui);
                    let playing = self.sink.is_some();
                    if primary_button(ui, if playing { "STOP" } else { "PLAY" }).clicked() {
                        self.toggle_audio();
                    }
                    segmented_group(
                        ui,
                        &["BODY SOLO", "PRODUCT"],
                        (self.mode == AudioMode::Product) as usize,
                        76.0,
                        |index| {
                            self.set_mode(if index == 0 {
                                AudioMode::BodySolo
                            } else {
                                AudioMode::Product
                            });
                        },
                    );
                    separator(ui);
                    if quiet_button(ui, "UNDO", !self.state.undo.is_empty()).clicked() {
                        self.undo();
                    }
                    if quiet_button(ui, "REDO", !self.state.redo.is_empty()).clicked() {
                        self.redo();
                    }
                    separator(ui);
                    if quiet_button(ui, "EXPORT", true).clicked() {
                        self.export();
                    }
                    ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                        let (badge, color) = if self.state.pending_edit.is_some() {
                            ("PREVIEW — UNCOMMITTED", WARN)
                        } else if screen.audit.pass {
                            ("SAMPLED CERT PASS", ACCENT)
                        } else {
                            ("SAMPLED CERT FAIL", ERROR)
                        };
                        ui.label(RichText::new(badge).size(10.0).color(color));
                        ui.add_space(10.0);
                        ui.label(
                            RichText::new(screen.name.clone())
                                .strong()
                                .color(TEXT),
                        );
                    });
                });
            });
    }

    fn travel_pad(&mut self, ui: &mut egui::Ui) {
        section_heading(ui, "TRAVEL PAD", "READ + AUDITION ONLY");
        ui.add_space(4.0);
        let width = ui.available_width();
        let height = 268.0f32.min(width);
        let (rect, response) =
            ui.allocate_exact_size(Vec2::new(width, height), Sense::click_and_drag());
        let painter = ui.painter_at(rect);
        painter.rect_filled(rect, Rounding::ZERO, Color32::from_rgb(20, 23, 27));
        let pad = rect.shrink2(Vec2::new(34.0, 24.0));
        painter.rect_stroke(pad, Rounding::ZERO, Stroke::new(1.0, LINE));
        for step in [25.0, 50.0, 75.0] {
            let x = pad.left() + pad.width() * step / 100.0;
            let y = pad.bottom() - pad.height() * step / 100.0;
            painter.line_segment(
                [Pos2::new(x, pad.top()), Pos2::new(x, pad.bottom())],
                Stroke::new(0.5, LINE),
            );
            painter.line_segment(
                [Pos2::new(pad.left(), y), Pos2::new(pad.right(), y)],
                Stroke::new(0.5, LINE),
            );
        }
        painter.text(
            Pos2::new(pad.center().x, rect.bottom() - 8.0),
            Align2::CENTER_BOTTOM,
            "MORPH 0..100",
            FontId::proportional(9.0),
            MUTED,
        );
        painter.text(
            Pos2::new(rect.left() + 10.0, pad.center().y),
            Align2::CENTER_CENTER,
            "Q",
            FontId::proportional(9.0),
            MUTED,
        );
        for (label, x, y) in [
            ("M0_Q0", pad.left(), pad.bottom()),
            ("M100_Q0", pad.right(), pad.bottom()),
            ("M0_Q100", pad.left(), pad.top()),
            ("M100_Q100", pad.right(), pad.top()),
        ] {
            painter.text(
                Pos2::new(x, y),
                Align2::CENTER_CENTER,
                label,
                FontId::proportional(8.0),
                MUTED,
            );
        }
        let morph = self.state.morph;
        let q = self.state.q;
        let puck = Pos2::new(
            pad.left() + pad.width() * morph as f32,
            pad.bottom() - pad.height() * q as f32,
        );
        painter.line_segment(
            [Pos2::new(puck.x, pad.top()), Pos2::new(puck.x, pad.bottom())],
            Stroke::new(0.5, ACCENT_SOFT),
        );
        painter.line_segment(
            [Pos2::new(pad.left(), puck.y), Pos2::new(pad.right(), puck.y)],
            Stroke::new(0.5, ACCENT_SOFT),
        );
        painter.circle_filled(puck, 7.0, ACCENT);
        painter.circle_stroke(puck, 10.0, Stroke::new(1.0, ACCENT_SOFT));
        if response.dragged() || response.clicked() {
            if let Some(position) = response.interact_pointer_pos() {
                let morph = ((position.x - pad.left()) / pad.width()).clamp(0.0, 1.0) as f64;
                let q = ((pad.bottom() - position.y) / pad.height()).clamp(0.0, 1.0) as f64;
                self.set_pad(morph, q);
            }
        }
        ui.add_space(4.0);
        ui.horizontal(|ui| {
            ui.label(
                RichText::new(format!("M{:.0}", self.state.morph * 100.0))
                    .strong()
                    .size(16.0)
                    .color(TEXT),
            );
            ui.add_space(10.0);
            ui.label(
                RichText::new(format!("Q{:.0}", self.state.q * 100.0))
                    .strong()
                    .size(16.0)
                    .color(TEXT),
            );
            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                ui.label(
                    RichText::new("pad moves no body bytes")
                        .size(9.0)
                        .color(MUTED),
                );
            });
        });
    }

    fn make_pane(&mut self, ui: &mut egui::Ui) {
        section_heading(ui, "MAKE", "NEW BODY FROM DISK DATA");
        ui.add_space(4.0);
        let actor_names = self
            .actor_wavs
            .iter()
            .map(|path| body_name(path))
            .collect::<Vec<_>>();
        ui.horizontal(|ui| {
            ui.label(RichText::new("AUDIO").size(9.0).color(MUTED));
            egui::ComboBox::from_id_salt("actor_wav")
                .selected_text(
                    actor_names
                        .get(self.actor_wav)
                        .cloned()
                        .unwrap_or_else(|| "no measured wavs".to_owned()),
                )
                .width(160.0)
                .show_ui(ui, |ui| {
                    for (index, name) in actor_names.iter().enumerate() {
                        ui.selectable_value(&mut self.actor_wav, index, name);
                    }
                });
            if quiet_button(ui, "LOAD ACTOR", !actor_names.is_empty()).clicked() {
                self.make_from_audio();
            }
        });
        ui.add_space(2.0);
        let candidate_ids = self
            .state
            .recipe_catalog
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<Vec<_>>();
        if self.recipe_sel >= candidate_ids.len() {
            self.recipe_sel = 0;
        }
        ui.horizontal(|ui| {
            ui.label(RichText::new("RECIPE").size(9.0).color(MUTED));
            egui::ComboBox::from_id_salt("recipe_candidate")
                .selected_text(
                    candidate_ids
                        .get(self.recipe_sel)
                        .cloned()
                        .unwrap_or_else(|| "no candidates".to_owned()),
                )
                .width(160.0)
                .show_ui(ui, |ui| {
                    for (index, id) in candidate_ids.iter().enumerate() {
                        ui.selectable_value(&mut self.recipe_sel, index, id);
                    }
                });
            if quiet_button(ui, "APPLY", !candidate_ids.is_empty()).clicked() {
                self.make_from_recipe();
            }
        });
        ui.add_space(2.0);
        let source_names = self
            .state
            .source_catalog
            .sources
            .iter()
            .map(|source| source.name.clone())
            .collect::<Vec<_>>();
        if self.source_sel >= source_names.len() {
            self.source_sel = 0;
        }
        ui.horizontal(|ui| {
            ui.label(RichText::new("XML").size(9.0).color(MUTED));
            egui::ComboBox::from_id_salt("xml_source")
                .selected_text(
                    source_names
                        .get(self.source_sel)
                        .cloned()
                        .unwrap_or_else(|| "no heritage xml".to_owned()),
                )
                .width(130.0)
                .show_ui(ui, |ui| {
                    for (index, name) in source_names.iter().enumerate() {
                        ui.selectable_value(&mut self.source_sel, index, name);
                    }
                });
            segmented_group(
                ui,
                &["LOW", "HIGH"],
                self.endpoint_high as usize,
                42.0,
                |index| self.endpoint_high = index == 1,
            );
            if quiet_button(ui, "FILL CORNER", !source_names.is_empty()).clicked() {
                self.make_fill_corner();
            }
        });
        ui.label(
            RichText::new(
                "actor = LPC poles from your wav · recipe = zero law on current poles · xml = heritage stages into the selected corner",
            )
            .size(8.0)
            .color(MUTED),
        );
    }

    fn lane_locker(&mut self, ui: &mut egui::Ui, screen: &ScreenData) {
        section_heading(
            ui,
            "LANE REGISTRATION LOCKER",
            &format!("{} · permanent S1..S6", CORNER_LABELS[screen.selected_corner]),
        );
        ui.add_space(4.0);
        let corner = screen.selected_corner;
        for lane_view in &screen.corners[corner].lanes {
            let lane = lane_view.lane_index;
            egui::Frame::none()
                .fill(PANEL_RAISED)
                .rounding(Rounding::ZERO)
                .inner_margin(egui::Margin::symmetric(8.0, 4.0))
                .show(ui, |ui| {
                    ui.horizontal(|ui| {
                        ui.label(
                            RichText::new(format!("S{}", lane + 1))
                                .strong()
                                .color(if lane == screen.selected_lane {
                                    ACCENT
                                } else {
                                    TEXT
                                }),
                        );
                        ui.add_space(6.0);
                        let stage = &lane_view.stage;
                        ui.label(
                            RichText::new(topology_text(stage))
                                .size(9.0)
                                .color(MUTED),
                        );
                        ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                            for side in [RootSide::Zero, RootSide::Pole] {
                                let locked = self.locks[corner][lane].get(side);
                                let label = match side {
                                    RootSide::Pole => "P",
                                    RootSide::Zero => "Z",
                                };
                                if mini_lock_button(ui, label, locked).clicked() {
                                    self.locks[corner][lane].toggle(side);
                                    let now = self.locks[corner][lane].get(side);
                                    self.set_status(format!(
                                        "{} {} · {} S{}",
                                        CORNER_LABELS[corner],
                                        side.label(),
                                        if now { "locked" } else { "unlocked" },
                                        lane + 1
                                    ));
                                }
                            }
                        });
                    });
                    if let Some(source) = &lane_view.stage.source {
                        ui.label(
                            RichText::new(format!("role: {}", source.source_name))
                                .size(8.0)
                                .color(MUTED),
                        );
                    }
                });
            ui.add_space(3.0);
        }
        ui.label(
            RichText::new("locks refuse edits; they never clamp or repair")
                .size(8.0)
                .color(MUTED),
        );
    }

    fn response_panel(&mut self, ui: &mut egui::Ui, screen: &ScreenData) {
        egui::Frame::none()
            .fill(PANEL)
            .rounding(Rounding::ZERO)
            .inner_margin(egui::Margin::same(12.0))
            .show(ui, |ui| {
                ui.horizontal(|ui| {
                    section_heading(ui, "PACKED/RUNTIME RESPONSE", "SIX-STAGE CASCADE");
                    ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                        ui.label(
                            RichText::new("fixed -48..+24 dB · from trench_packed_probe rows")
                                .size(9.0)
                                .color(MUTED),
                        );
                    });
                });
                ui.add_space(4.0);
                self.response_plot(ui, screen);
                ui.add_space(6.0);
                ui.horizontal(|ui| {
                    let selected = screen.selected_lane;
                    segmented_group(
                        ui,
                        &["S1", "S2", "S3", "S4", "S5", "S6"],
                        selected,
                        40.0,
                        |index| {
                            if let Err(error) = self.state.select(screen.selected_corner, index)
                            {
                                self.set_error(error.to_string());
                            }
                        },
                    );
                    ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                        ui.label(
                            RichText::new("amber = selected lane · drag its marker")
                                .size(9.0)
                                .color(MUTED),
                        );
                    });
                });
            });
    }

    fn response_plot(&mut self, ui: &mut egui::Ui, screen: &ScreenData) {
        let desired = Vec2::new(
            ui.available_width(),
            (ui.available_height() - 44.0).max(200.0),
        );
        let (rect, response) = ui.allocate_exact_size(desired, Sense::click_and_drag());
        let plot = rect.shrink2(Vec2::new(46.0, 20.0));
        let painter = ui.painter_at(rect);
        painter.rect_filled(plot, Rounding::ZERO, Color32::from_rgb(20, 23, 27));
        draw_plot_grid(&painter, plot);
        // Per-lane curves from the same packed runtime probe rows: editing a
        // lane must show *which* bump in the combined curve is yours.
        let grid = log_grid(96);
        for lane in 0..6 {
            let row = &screen.current_probe.rows[lane];
            let points = grid
                .iter()
                .map(|&freq_hz| {
                    Pos2::new(
                        map_hz(plot, freq_hz),
                        map_db(plot, biquad_stage_mag_db(row, freq_hz, STAGE_SR)),
                    )
                })
                .collect::<Vec<_>>();
            let selected = lane == screen.selected_lane;
            let stroke = if selected {
                Stroke::new(1.5, WARN)
            } else {
                Stroke::new(0.75, Color32::from_rgba_unmultiplied(143, 151, 161, 60))
            };
            painter.add(egui::Shape::line(points, stroke));
        }
        let points = screen
            .current_response
            .points
            .iter()
            .filter(|point| point.db.is_finite())
            .map(|point| Pos2::new(map_hz(plot, point.freq_hz), map_db(plot, point.db)))
            .collect::<Vec<_>>();
        if points.len() > 1 {
            painter.add(egui::Shape::line(points, Stroke::new(2.0, ACCENT)));
        }

        // Pole/zero markers for all six lanes, factored from the packed
        // runtime probe rows at the current Morph/Q.
        let mark_pos = |hz: f64, radius: f64| {
            Pos2::new(
                map_hz(plot, hz.clamp(20.0, 16_000.0)),
                plot.top() + (1.0 - radius.clamp(0.0, 1.0)) as f32 * plot.height(),
            )
        };
        for lane in 0..6 {
            let row = &screen.current_probe.rows[lane];
            let selected = lane == screen.selected_lane;
            for side in [RootSide::Pole, RootSide::Zero] {
                let mark = roots_from_probe_row(row, side);
                let alpha: u8 = if selected { 255 } else { 90 };
                let (fill, stroke) = match side {
                    RootSide::Pole => (
                        Color32::from_rgba_unmultiplied(70, 184, 151, alpha),
                        Color32::from_rgba_unmultiplied(42, 94, 82, alpha),
                    ),
                    RootSide::Zero => (
                        Color32::from_rgba_unmultiplied(24, 27, 31, alpha),
                        Color32::from_rgba_unmultiplied(230, 233, 237, alpha),
                    ),
                };
                match mark {
                    RootMark::Conjugate { hz, radius } => {
                        let pos = mark_pos(hz, radius);
                        let size = if selected { 6.0 } else { 4.0 };
                        painter.circle_filled(pos, size, fill);
                        painter.circle_stroke(pos, size + 1.5, Stroke::new(1.0, stroke));
                    }
                    RootMark::Real(roots) => {
                        for root in roots {
                            let x = if root >= 0.0 {
                                plot.left() + 8.0
                            } else {
                                plot.right() - 8.0
                            };
                            let y = plot.top()
                                + (1.0 - root.abs().clamp(0.0, 1.0)) as f32 * plot.height();
                            painter.rect_filled(
                                Rect::from_center_size(Pos2::new(x, y), Vec2::splat(6.0)),
                                1.0,
                                fill,
                            );
                            painter.rect_stroke(
                                Rect::from_center_size(Pos2::new(x, y), Vec2::splat(8.0)),
                                1.0,
                                Stroke::new(1.0, stroke),
                            );
                        }
                    }
                    RootMark::Degenerate => {}
                }
            }
        }

        // Drag: only the selected stage, only a conjugate marker, only when
        // that side is unlocked. Preview rides the drag; commit on release.
        if response.drag_started() {
            self.drag = None;
            if let Some(position) = response.interact_pointer_pos() {
                let lane = screen.selected_lane;
                let row = &screen.current_probe.rows[lane];
                let mut best: Option<(f32, RootSide)> = None;
                for side in [RootSide::Pole, RootSide::Zero] {
                    if let RootMark::Conjugate { hz, radius } = roots_from_probe_row(row, side)
                    {
                        let distance = mark_pos(hz, radius).distance(position);
                        if distance <= 16.0 && best.map_or(true, |(d, _)| distance < d) {
                            best = Some((distance, side));
                        }
                    }
                }
                if let Some((_, side)) = best {
                    if self.locks[screen.selected_corner][lane].get(side) {
                        self.set_error(format!(
                            "Unlock the {} for {} S{} before dragging",
                            side.label(),
                            CORNER_LABELS[screen.selected_corner],
                            lane + 1
                        ));
                    } else {
                        self.drag = Some(side);
                    }
                }
            }
        }
        if response.dragged() {
            if let (Some(side), Some(position)) = (self.drag, response.interact_pointer_pos()) {
                let hz = unmap_hz(plot, position.x).clamp(1.0, STAGE_SR * 0.5 - 1.0);
                let radius = ((plot.bottom() - position.y) / plot.height()) as f64;
                let radius = radius.clamp(0.0, 0.999_98);
                self.preview_edit(EditRequest::conjugate(
                    vec![screen.selected_corner],
                    screen.selected_lane,
                    side == RootSide::Pole,
                    hz,
                    radius,
                ));
            }
        }
        if response.drag_stopped() {
            if self.drag.is_some() {
                self.drag = None;
                self.apply();
            }
        }
    }

    fn edit_pane(&mut self, ui: &mut egui::Ui, screen: &ScreenData) {
        egui::Frame::none()
            .fill(PANEL)
            .rounding(Rounding::ZERO)
            .inner_margin(egui::Margin::same(12.0))
            .show(ui, |ui| {
                ui.horizontal(|ui| {
                    section_heading(ui, "EDIT / EXPORT", "DECLARED EDITS ONLY");
                    ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                        ui.label(
                            RichText::new(
                                "TENSION (exact M50) — disabled: no core-owned solver in this build",
                            )
                            .size(9.0)
                            .color(WARN),
                        );
                    });
                });
                ui.add_space(6.0);
                // Corner mask: checkbox declares edit scope, label selects the
                // inspected corner. Four authored corners, never a fifth.
                ui.horizontal(|ui| {
                    ui.label(RichText::new("CORNERS").size(9.0).color(MUTED));
                    for corner in 0..4 {
                        let mut enabled = self.corner_mask[corner];
                        if flat_checkbox(ui, &mut enabled).changed() {
                            self.corner_mask[corner] = enabled;
                        }
                        let selected = screen.selected_corner == corner;
                        if ui
                            .selectable_label(
                                selected,
                                RichText::new(CORNER_LABELS[corner])
                                    .size(10.0)
                                    .color(if enabled { TEXT } else { MUTED }),
                            )
                            .clicked()
                        {
                            if let Err(error) = self.state.select(corner, screen.selected_lane)
                            {
                                self.set_error(error.to_string());
                            }
                        }
                        ui.add_space(4.0);
                    }
                    ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                        if screen.selected_stage.identity {
                            ui.label(
                                RichText::new("S{} INACTIVE (identity biquad)")
                                    .size(9.0)
                                    .color(MUTED),
                            );
                        } else {
                            let both_unlocked = self.editable_corners(
                                screen.selected_lane,
                                Some(RootSide::Pole),
                            ) == self.editable_corners(
                                screen.selected_lane,
                                Some(RootSide::Zero),
                            );
                            let corners = self.editable_corners(
                                screen.selected_lane,
                                Some(RootSide::Pole),
                            );
                            let enabled = both_unlocked && !corners.is_empty();
                            if quiet_button(ui, "DEACTIVATE STAGE", enabled).clicked() {
                                self.preview_edit(EditRequest {
                                    corner_indices: corners,
                                    lane_indices: vec![screen.selected_lane],
                                    field: EditField::Identity,
                                    value: 1.0,
                                    secondary_value: None,
                                    relative: false,
                                });
                            }
                        }
                    });
                });
                ui.add_space(6.0);
                ui.horizontal(|ui| {
                    ui.label(
                        RichText::new(format!("STAGE S{}", screen.selected_lane + 1))
                            .size(10.0)
                            .color(TEXT),
                    );
                    let fields = available_fields(&screen.selected_stage);
                    if !fields.contains(&self.field) {
                        self.field = fields.first().copied().unwrap_or(PaneField::Scale);
                    }
                    egui::ComboBox::from_id_salt("pane_field")
                        .selected_text(self.field.label())
                        .show_ui(ui, |ui| {
                            for field in &fields {
                                ui.selectable_value(&mut self.field, *field, field.label());
                            }
                        });
                    ui.label(
                        RichText::new(format!("Δ ({})", self.field.delta_hint()))
                            .size(9.0)
                            .color(MUTED),
                    );
                    ui.add(
                        egui::DragValue::new(&mut self.delta)
                            .speed(0.01)
                            .max_decimals(4),
                    );
                    if quiet_button(ui, "PREVIEW", true).clicked() {
                        self.preview_pane_request(screen);
                    }
                    if primary_button(ui, "APPLY").clicked() {
                        self.apply();
                    }
                    if quiet_button(ui, "CANCEL", self.state.pending_edit.is_some()).clicked() {
                        self.cancel_preview();
                    }
                    if quiet_button(ui, "UNDO", !self.state.undo.is_empty()).clicked() {
                        self.undo();
                    }
                    if quiet_button(ui, "EXPORT", true).clicked() {
                        self.export();
                    }
                });
                ui.add_space(6.0);
                ui.horizontal_wrapped(|ui| {
                    ui.label(RichText::new("STAGE").size(9.0).color(MUTED));
                    ui.label(
                        RichText::new(stage_readout(&screen.selected_stage))
                            .size(10.0)
                            .color(TEXT),
                    );
                });
                if !self.receipt.is_empty() {
                    ui.horizontal_wrapped(|ui| {
                        ui.label(RichText::new("RECEIPT").size(9.0).color(MUTED));
                        ui.label(
                            RichText::new(&self.receipt)
                                .size(9.0)
                                .color(ACCENT),
                        );
                    });
                }
            });
    }

    fn status_bar(&mut self, ctx: &egui::Context) {
        egui::TopBottomPanel::bottom("status")
            .exact_height(26.0)
            .frame(
                egui::Frame::none()
                    .fill(PANEL)
                    .inner_margin(egui::Margin::symmetric(12.0, 4.0)),
            )
            .show(ctx, |ui| {
                ui.horizontal(|ui| {
                    ui.label(
                        RichText::new(&self.status)
                            .size(10.0)
                            .color(if self.status_error { ERROR } else { MUTED }),
                    );
                });
            });
    }
}

impl eframe::App for ForgeApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        let screen = match self.screen() {
            Ok(screen) => screen,
            Err(error) => {
                self.set_error(error);
                return;
            }
        };
        self.toolbar(ctx, &screen);
        self.status_bar(ctx);
        egui::SidePanel::left("left")
            .exact_width(380.0)
            .frame(
                egui::Frame::none()
                    .fill(PANEL)
                    .inner_margin(egui::Margin::same(12.0)),
            )
            .show(ctx, |ui| {
                self.travel_pad(ui);
                ui.add_space(8.0);
                ui.separator();
                ui.add_space(6.0);
                self.make_pane(ui);
                ui.add_space(8.0);
                ui.separator();
                ui.add_space(6.0);
                egui::ScrollArea::vertical()
                    .auto_shrink([false, false])
                    .show(ui, |ui| self.lane_locker(ui, &screen));
            });
        egui::CentralPanel::default()
            .frame(
                egui::Frame::none()
                    .fill(BG)
                    .inner_margin(egui::Margin::same(10.0)),
            )
            .show(ctx, |ui| {
                let available = ui.available_size();
                let edit_height = 168.0f32.min(available.y * 0.4);
                ui.allocate_ui_with_layout(
                    Vec2::new(available.x, (available.y - edit_height - 10.0).max(240.0)),
                    Layout::top_down(Align::Min),
                    |ui| self.response_panel(ui, &screen),
                );
                ui.add_space(10.0);
                self.edit_pane(ui, &screen);
            });
        if self.sink.as_ref().is_some_and(Sink::empty) {
            self.stop_audio();
        }
    }
}

// ---------------------------------------------------------------------------
// Rendering helpers
// ---------------------------------------------------------------------------

fn topology_text(stage: &StageSnapshot) -> String {
    fn side_text(geometry: &RootGeometry) -> String {
        match geometry {
            RootGeometry::Conjugate { hz, radius } => format!("{hz:.0}Hz r{radius:.2}"),
            RootGeometry::RealPair { root_a, root_b } => {
                format!("real {root_a:+.2},{root_b:+.2}")
            }
            RootGeometry::Degenerate => "origin".to_owned(),
        }
    }
    if stage.identity {
        return "identity".to_owned();
    }
    format!(
        "P {} · Z {}",
        side_text(&stage.pole),
        side_text(&stage.zero)
    )
}

fn stage_readout(stage: &StageSnapshot) -> String {
    let mut parts = vec![topology_text(stage)];
    parts.push(format!("SCALE {}", stage.scale.display));
    parts.push(
        stage
            .packed_words
            .iter()
            .enumerate()
            .map(|(index, word)| format!("W{index} {word:04X}"))
            .collect::<Vec<_>>()
            .join(" "),
    );
    parts.join("  ·  ")
}

fn apply_receipt(result: &trench_workstation::model::EditResult) -> String {
    let words = result
        .changed_words
        .iter()
        .take(8)
        .map(|word| {
            format!(
                "{} S{} W{} {:04X}->{:04X}",
                word.corner_label,
                word.lane_index + 1,
                word.word_index,
                word.before,
                word.after
            )
        })
        .collect::<Vec<_>>()
        .join(" ");
    let more = if result.changed_words.len() > 8 {
        format!(" +{} more", result.changed_words.len() - 8)
    } else {
        String::new()
    };
    let quant = result
        .targets
        .iter()
        .map(|target| target.quantisation.max_abs)
        .fold(0.0, f64::max);
    format!(
        "{} word(s) · {} {more} · max |quant| {quant:.3e} · corners [{}] · lane(s) [{}]",
        result.changed_words.len(),
        words,
        result
            .request
            .corner_indices
            .iter()
            .map(|&corner| CORNER_LABELS[corner])
            .collect::<Vec<_>>()
            .join(" "),
        result
            .request
            .lane_indices
            .iter()
            .map(|lane| format!("S{}", lane + 1))
            .collect::<Vec<_>>()
            .join(" ")
    )
}

fn draw_plot_grid(painter: &egui::Painter, plot: Rect) {
    for db in [-48.0, -36.0, -24.0, -12.0, 0.0, 12.0, 24.0] {
        let y = map_db(plot, db);
        painter.line_segment(
            [Pos2::new(plot.left(), y), Pos2::new(plot.right(), y)],
            Stroke::new(if db == 0.0 { 1.0 } else { 0.5 }, LINE),
        );
        painter.text(
            Pos2::new(plot.left() - 6.0, y),
            Align2::RIGHT_CENTER,
            format!("{db:.0}"),
            FontId::proportional(9.0),
            MUTED,
        );
    }
    for hz in [
        20.0, 50.0, 100.0, 200.0, 500.0, 1_000.0, 2_000.0, 5_000.0, 10_000.0, 16_000.0,
    ] {
        let x = map_hz(plot, hz);
        painter.line_segment(
            [Pos2::new(x, plot.top()), Pos2::new(x, plot.bottom())],
            Stroke::new(0.5, LINE),
        );
        if matches!(hz as i32, 20 | 100 | 1000 | 10000 | 16000) {
            let label = if hz >= 1000.0 {
                format!("{}k", hz as i32 / 1000)
            } else {
                format!("{}", hz as i32)
            };
            painter.text(
                Pos2::new(x, plot.bottom() + 6.0),
                Align2::CENTER_TOP,
                label,
                FontId::proportional(9.0),
                MUTED,
            );
        }
    }
}

fn log_grid(points: usize) -> Vec<f64> {
    (0..points)
        .map(|index| 20.0 * (16_000.0_f64 / 20.0).powf(index as f64 / (points - 1) as f64))
        .collect()
}

fn map_hz(rect: Rect, hz: f64) -> f32 {
    let t = ((hz.clamp(20.0, 16_000.0).ln() - 20.0_f64.ln()) / (16_000.0_f64.ln() - 20.0_f64.ln()))
        as f32;
    egui::lerp(rect.x_range(), t)
}

fn unmap_hz(rect: Rect, x: f32) -> f64 {
    let t = ((x - rect.left()) / rect.width()).clamp(0.0, 1.0) as f64;
    (20.0_f64.ln() + t * (16_000.0_f64.ln() - 20.0_f64.ln())).exp()
}

fn map_db(rect: Rect, db: f64) -> f32 {
    let t = ((db.clamp(DB_MIN, DB_MAX) - DB_MIN) / (DB_MAX - DB_MIN)) as f32;
    egui::lerp(rect.y_range(), 1.0 - t)
}

// ---------------------------------------------------------------------------
// Widget helpers
// ---------------------------------------------------------------------------

fn section_heading(ui: &mut egui::Ui, title: &str, detail: &str) {
    ui.horizontal(|ui| {
        ui.label(RichText::new(title).size(11.0).strong().color(TEXT));
        ui.add_space(6.0);
        ui.label(RichText::new(detail).size(9.0).color(MUTED));
    });
}

fn separator(ui: &mut egui::Ui) {
    ui.add_space(3.0);
    let (rect, _) = ui.allocate_exact_size(Vec2::new(1.0, 22.0), Sense::hover());
    ui.painter().rect_filled(rect, 0.0, LINE);
    ui.add_space(3.0);
}

fn primary_button(ui: &mut egui::Ui, label: &str) -> Response {
    ui.add(
        egui::Button::new(
            RichText::new(label)
                .strong()
                .color(Color32::from_rgb(8, 25, 21)),
        )
        .fill(ACCENT)
        .stroke(Stroke::NONE)
        .rounding(Rounding::ZERO)
        .min_size(Vec2::new(56.0, 24.0)),
    )
}

fn quiet_button(ui: &mut egui::Ui, label: &str, enabled: bool) -> Response {
    ui.add_enabled(
        enabled,
        egui::Button::new(RichText::new(label).size(10.0).color(TEXT))
            .fill(PANEL_RAISED)
            .stroke(Stroke::new(1.0, LINE))
            .rounding(Rounding::ZERO)
            .min_size(Vec2::new(48.0, 24.0)),
    )
}

fn mini_lock_button(ui: &mut egui::Ui, label: &str, locked: bool) -> Response {
    ui.add(
        egui::Button::new(
            RichText::new(label)
                .size(10.0)
                .monospace()
                .color(if locked { MUTED } else { ACCENT }),
        )
        .fill(if locked { PANEL } else { ACCENT_SOFT })
        .stroke(Stroke::new(1.0, if locked { LINE } else { ACCENT }))
        .rounding(Rounding::ZERO)
        .min_size(Vec2::new(24.0, 20.0)),
    )
}

/// Joined segmented control — one bordered run, hairline cells, the selected
/// cell carries the accent fill. Used for mode and stage selection.
fn segmented_group(
    ui: &mut egui::Ui,
    options: &[&str],
    selected: usize,
    cell_width: f32,
    mut on_select: impl FnMut(usize),
) {
    let height = 22.0;
    let total = Vec2::new(cell_width * options.len() as f32, height);
    let (rect, _) = ui.allocate_exact_size(total, Sense::hover());
    let painter = ui.painter_at(rect);
    painter.rect_stroke(rect, Rounding::ZERO, Stroke::new(1.0, LINE));
    for (index, option) in options.iter().enumerate() {
        let cell = Rect::from_min_size(
            Pos2::new(rect.left() + cell_width * index as f32, rect.top()),
            Vec2::new(cell_width, height),
        );
        let response = ui.interact(cell, ui.id().with(("segment", index)), Sense::click());
        let is_selected = index == selected;
        if is_selected {
            painter.rect_filled(cell, Rounding::ZERO, ACCENT_SOFT);
        } else if response.hovered() {
            painter.rect_filled(cell, Rounding::ZERO, PANEL_RAISED);
        }
        if index > 0 {
            painter.line_segment(
                [cell.left_top(), cell.left_bottom()],
                Stroke::new(1.0, LINE),
            );
        }
        painter.text(
            cell.center(),
            Align2::CENTER_CENTER,
            *option,
            FontId::proportional(10.0),
            if is_selected { TEXT } else { MUTED },
        );
        if response.clicked() {
            on_select(index);
        }
    }
}

/// Flat square checkbox for the corner mask: hairline cell, accent core.
fn flat_checkbox(ui: &mut egui::Ui, value: &mut bool) -> Response {
    let (rect, response) = ui.allocate_exact_size(Vec2::splat(14.0), Sense::click());
    let painter = ui.painter_at(rect);
    painter.rect_stroke(
        rect,
        Rounding::ZERO,
        Stroke::new(1.0, if *value { ACCENT } else { LINE }),
    );
    if *value {
        painter.rect_filled(rect.shrink(3.0), Rounding::ZERO, ACCENT);
    }
    if response.clicked() {
        *value = !*value;
    }
    response
}

// ---------------------------------------------------------------------------
// Files / audio helpers
// ---------------------------------------------------------------------------

fn body_name(path: &Path) -> String {
    path.file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("Untitled")
        .replace('_', " ")
}

fn first_body(repo_root: &Path) -> Option<PathBuf> {
    let mut candidates = [
        repo_root.join("filters").join("bodies"),
        repo_root.join("plugin").join("presets").join("bodies"),
    ]
    .into_iter()
    .filter_map(|dir| {
        let mut bodies = fs::read_dir(dir)
            .ok()?
            .filter_map(Result::ok)
            .map(|entry| entry.path())
            .filter(|path| path.extension().and_then(|value| value.to_str()) == Some("body240"))
            .collect::<Vec<_>>();
        bodies.sort();
        bodies.into_iter().next()
    })
    .collect::<Vec<_>>();
    candidates.dedup();
    candidates.into_iter().next()
}

fn first_audition_wav(repo_root: &Path) -> Option<PathBuf> {
    let mut wavs = Vec::new();
    collect_wavs(&repo_root.join("wav-source-library"), &mut wavs).ok()?;
    wavs.sort();
    let cello = wavs
        .iter()
        .position(|path| body_name(path).to_lowercase().contains("cello"));
    cello.or(if wavs.is_empty() { None } else { Some(0) })
        .map(|index| wavs[index].clone())
}

fn collect_wavs(root: &Path, output: &mut Vec<PathBuf>) -> std::io::Result<()> {
    if !root.exists() {
        return Ok(());
    }
    for entry in fs::read_dir(root)? {
        let path = entry?.path();
        if path.is_dir() {
            collect_wavs(&path, output)?;
        } else if path
            .extension()
            .and_then(|value| value.to_str())
            .is_some_and(|extension| extension.eq_ignore_ascii_case("wav"))
        {
            output.push(path);
        }
    }
    Ok(())
}

/// One retained engine, prepared and loaded for cascade-only (BODY SOLO) or
/// the full retained path (PRODUCT). Same setup the proof renders use.
fn build_audition_engine(body: &[u8], mode: AudioMode) -> Result<FilterEngine, String> {
    let cartridge = Cartridge::from_body_bytes("workstation-audition", body, 1.0)
        .map_err(|error| error.to_string())?;
    let mut engine = FilterEngine::new();
    engine.prepare(STAGE_SR);
    engine.load_cartridge(cartridge);
    engine.set_input_mode(InputMode::None);
    engine.set_spatial_mode(SpatialMode::Off);
    engine.set_amount(1.0);
    engine.debug.spatial_enabled = false;
    if mode == AudioMode::BodySolo {
        engine.debug.agc_enabled = false;
        engine.debug.dc_block_enabled = false;
        engine.debug.saturation_enabled = false;
    }
    Ok(engine)
}

/// Decode a WAV once, downmix to mono, resample to the engine rate.
fn decode_wav_to_stage_sr(path: &Path) -> Result<Vec<f32>, String> {
    let file = File::open(path).map_err(|error| format!("WAV could not be opened: {error}"))?;
    let decoder = Decoder::new(BufReader::new(file))
        .map_err(|error| format!("WAV could not be decoded: {error}"))?;
    let source_rate = decoder.sample_rate();
    let channels = decoder.channels() as usize;
    let interleaved = decoder
        .convert_samples::<f32>()
        .take_duration(Duration::from_secs(60))
        .collect::<Vec<f32>>();
    if channels == 0 || interleaved.len() < channels * 2_048 {
        return Err("WAV is too short for an audition".to_owned());
    }
    let mono = interleaved
        .chunks(channels)
        .map(|frame| frame.iter().copied().sum::<f32>() / frame.len() as f32)
        .collect::<Vec<_>>();
    if mono.iter().any(|sample| !sample.is_finite()) {
        return Err("WAV contains nonfinite samples".to_owned());
    }
    let target_len = ((mono.len() as f64 * STAGE_SR / source_rate as f64).round() as usize).max(2);
    let mut source = Vec::with_capacity(target_len);
    for index in 0..target_len {
        let position = (index as f64 * source_rate as f64 / STAGE_SR).min((mono.len() - 1) as f64);
        let left = position.floor() as usize;
        let right = (left + 1).min(mono.len() - 1);
        let fraction = (position - left as f64) as f32;
        source.push(mono[left] * (1.0 - fraction) + mono[right] * fraction);
    }
    Ok(source)
}

fn collect_actor_wavs(repo_root: &Path) -> Vec<PathBuf> {
    let mut wavs = Vec::new();
    let _ = collect_wavs(
        &repo_root
            .join("wav-source-library")
            .join("measured_objects"),
        &mut wavs,
    );
    if wavs.is_empty() {
        let _ = collect_wavs(
            &repo_root
                .join("recipes")
                .join("measured_objects"),
            &mut wavs,
        );
    }
    wavs.sort();
    wavs
}

/// Decode a WAV to mono f32 at its own sample rate for the actor loader.
fn decode_wav_mono(path: &Path) -> Result<(Vec<f32>, u32), String> {
    const MAX_ACTOR_SAMPLES: usize = 12_000_000;
    let file = File::open(path).map_err(|error| format!("WAV could not be opened: {error}"))?;
    let decoder = Decoder::new(BufReader::new(file))
        .map_err(|error| format!("WAV could not be decoded: {error}"))?;
    let rate = decoder.sample_rate();
    let channels = decoder.channels() as usize;
    let interleaved = decoder
        .convert_samples::<f32>()
        .take(MAX_ACTOR_SAMPLES)
        .collect::<Vec<f32>>();
    if channels == 0 || interleaved.len() < channels * 2_048 {
        return Err("WAV is too short for an actor scaffold".to_owned());
    }
    let mono = interleaved
        .chunks(channels)
        .map(|frame| frame.iter().copied().sum::<f32>() / frame.len() as f32)
        .collect::<Vec<_>>();
    if mono.iter().any(|sample| !sample.is_finite()) {
        return Err("WAV contains nonfinite samples".to_owned());
    }
    Ok((mono, rate))
}

fn configure_ui(ctx: &egui::Context) {
    // Native type, loaded from the OS at runtime — nothing bundled, no stock
    // toolkit font. Falls back silently if the OS fonts are missing.
    let mut fonts = egui::FontDefinitions::default();
    for (name, path, family) in [
        (
            "segoe",
            r"C:\Windows\Fonts\segoeui.ttf",
            egui::FontFamily::Proportional,
        ),
        (
            "consolas",
            r"C:\Windows\Fonts\consola.ttf",
            egui::FontFamily::Monospace,
        ),
    ] {
        if let Ok(bytes) = std::fs::read(path) {
            fonts
                .font_data
                .insert(name.to_owned(), egui::FontData::from_owned(bytes));
            fonts
                .families
                .entry(family)
                .or_default()
                .insert(0, name.to_owned());
        }
    }
    ctx.set_fonts(fonts);

    // Flat, segmented, load-bearing chrome: zero radius, hairlines, no shadows.
    let mut visuals = egui::Visuals::dark();
    visuals.panel_fill = PANEL;
    visuals.window_fill = PANEL;
    visuals.extreme_bg_color = BG;
    visuals.faint_bg_color = PANEL;
    visuals.window_rounding = Rounding::ZERO;
    visuals.window_shadow = egui::Shadow::NONE;
    visuals.popup_shadow = egui::Shadow::NONE;
    let widget_state = |fill: Color32| egui::style::WidgetVisuals {
        bg_fill: fill,
        weak_bg_fill: fill,
        bg_stroke: Stroke::new(1.0, LINE),
        fg_stroke: Stroke::new(1.0, TEXT),
        rounding: Rounding::ZERO,
        expansion: 0.0,
    };
    visuals.widgets.inactive = widget_state(PANEL_RAISED);
    visuals.widgets.hovered = widget_state(Color32::from_rgb(35, 40, 46));
    visuals.widgets.active = widget_state(ACCENT_SOFT);
    visuals.widgets.open = widget_state(PANEL_RAISED);
    visuals.selection.bg_fill = ACCENT_SOFT;
    visuals.selection.stroke = Stroke::new(1.0, ACCENT);
    visuals.override_text_color = Some(TEXT);
    ctx.set_visuals(visuals);

    let mut style = (*ctx.style()).clone();
    style.spacing.item_spacing = Vec2::new(7.0, 6.0);
    style.spacing.button_padding = Vec2::new(10.0, 5.0);
    style.spacing.interact_size.y = 24.0;
    style.text_styles = [
        (egui::TextStyle::Body, FontId::new(12.0, egui::FontFamily::Proportional)),
        (egui::TextStyle::Small, FontId::new(10.0, egui::FontFamily::Proportional)),
        (egui::TextStyle::Button, FontId::new(11.0, egui::FontFamily::Proportional)),
        (egui::TextStyle::Monospace, FontId::new(11.0, egui::FontFamily::Monospace)),
        (egui::TextStyle::Heading, FontId::new(13.0, egui::FontFamily::Proportional)),
    ]
    .into();
    ctx.set_style(style);
}

fn main() -> eframe::Result<()> {
    let repo_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("workstation manifest must be inside the repository")
        .to_path_buf();
    let app = ForgeApp::new(repo_root).unwrap_or_else(|error| panic!("{error}"));
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("TRENCH Surface Forge")
            .with_inner_size([1440.0, 900.0])
            .with_min_inner_size([1100.0, 720.0]),
        ..Default::default()
    };
    eframe::run_native(
        "TRENCH Surface Forge",
        options,
        Box::new(|creation| {
            configure_ui(&creation.egui_ctx);
            Ok(Box::new(app))
        }),
    )
}

// ---------------------------------------------------------------------------
// Proof gates (acceptance gates 1, 2, 4 + the audio-thread boundary)
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use trench_workstation::model::{render_audio_at, Excitation};

    fn repo_root() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .to_path_buf()
    }

    fn app() -> ForgeApp {
        ForgeApp::new(repo_root()).unwrap()
    }

    fn probe_wav(len: usize) -> Vec<f32> {
        (0..len).map(|i| (i as f32 * 0.031).sin() * 0.25).collect()
    }

    /// Gate 1: travel-pad movement changes only the read position.
    #[test]
    fn pad_travel_keeps_body_bytes_identical() {
        let mut app = app();
        let before = app.working_body_bytes().unwrap();
        for step_m in 0..=10 {
            for step_q in 0..=10 {
                app.set_pad(step_m as f64 / 10.0, step_q as f64 / 10.0);
            }
        }
        assert_eq!(app.state.morph, 1.0);
        assert_eq!(app.state.q, 1.0);
        let after = app.working_body_bytes().unwrap();
        assert_eq!(before, after, "pad travel must not move body bytes");
        let screen = app.screen().unwrap();
        assert_eq!(screen.current_probe.morph, 1.0);
        assert_eq!(screen.current_probe.q, 1.0);
    }

    /// Gate 2: one selected-stage edit = one Preview/Apply undo step, and the
    /// receipt names only the declared corner/lane/words.
    #[test]
    fn preview_apply_reports_only_declared_words_and_one_undo_step() {
        let mut app = app();
        let screen = app.screen().unwrap();
        let lane = screen.corners[0]
            .lanes
            .iter()
            .position(|lane| matches!(lane.stage.pole, RootGeometry::Conjugate { .. }))
            .expect("starter body must expose at least one conjugate pole lane");
        app.state.select(0, lane).unwrap();
        let screen = app.screen().unwrap();
        let hz = match screen.corners[0].lanes[lane].stage.pole {
            RootGeometry::Conjugate { hz, .. } => hz,
            _ => unreachable!(),
        };
        app.corner_mask = [true, false, false, false];
        app.locks[0][lane].pole = false;
        app.field = PaneField::PoleHz;
        app.delta = if hz < 9_000.0 { 1.0 } else { -1.0 };
        let before = app.working_body_bytes().unwrap();
        let undo_depth = app.state.undo.len();

        let request = app.build_request(&screen).unwrap();
        app.preview_edit(request);
        assert!(app.state.pending_edit.is_some());
        app.apply();
        let result = app.state.last_edit.clone().expect("apply must record a result");
        assert_eq!(app.state.undo.len(), undo_depth + 1, "apply pushes one undo step");
        assert!(
            !result.changed_words.is_empty(),
            "a one-octave pole move must change packed words"
        );
        assert!(result
            .changed_words
            .iter()
            .all(|word| word.corner_index == 0 && word.lane_index == lane));
        let edited = app.working_body_bytes().unwrap();
        assert_ne!(before, edited);

        app.undo();
        assert_eq!(
            app.working_body_bytes().unwrap(),
            before,
            "undo restores the exact body bytes"
        );
    }

    /// Gate 4: real-root rows never enter the conjugate editor; empty masks
    /// and multi-corner real-root edits are refused, not clamped.
    #[test]
    fn real_root_rows_are_refused_conjugate_controls() {
        let real = RootGeometry::RealPair {
            root_a: 0.8,
            root_b: -0.4,
        };
        assert!(fields_for_geometry(&real, RootSide::Pole)
            .iter()
            .all(|field| field.is_real_root()));
        assert!(fields_for_geometry(&real, RootSide::Zero)
            .iter()
            .all(|field| field.is_real_root()));
        let degenerate = RootGeometry::Degenerate;
        assert!(fields_for_geometry(&degenerate, RootSide::Pole).is_empty());
        assert!(fields_for_geometry(&degenerate, RootSide::Zero).is_empty());

        let mut app = app();
        let screen = app.screen().unwrap();
        let lane = screen.selected_lane;
        // Every side locked + every corner toggled on: refusal, not a clamp.
        app.field = PaneField::PoleHz;
        let error = app.build_request(&screen).unwrap_err();
        assert!(
            error.contains("no editable corner contributes"),
            "expected a refusal boundary, got: {error}"
        );
        // Unlock pole side for all corners: a conjugate field builds a
        // relative request across the declared mask.
        for corner in 0..4 {
            app.locks[corner][lane].pole = false;
        }
        let request = app.build_request(&screen).unwrap();
        assert!(request.relative);
        assert_eq!(request.corner_indices, vec![0, 1, 2, 3]);
        assert_eq!(request.field, EditField::PoleGeometry);
        // Real-root fields demand exactly the selected corner.
        app.field = PaneField::PoleRootA;
        let error = app.build_request(&screen).unwrap_err();
        assert!(
            error.contains("single-corner"),
            "multi-corner real-root edit must be refused: {error}"
        );
        app.corner_mask = [true, false, false, false];
        app.state.select(0, lane).unwrap();
        let screen = app.screen().unwrap();
        if matches!(screen.selected_stage.pole, RootGeometry::RealPair { .. }) {
            let request = app.build_request(&screen).unwrap();
            assert_eq!(request.corner_indices, vec![0]);
            assert!(!request.relative);
        }
    }

    /// Gate 3 support: markers factored from probe rows match the authored
    /// packed snapshot when the pad sits on that corner.
    #[test]
    fn probe_row_roots_match_authored_corner_geometry() {
        let mut app = app();
        app.set_pad(0.0, 0.0);
        let screen = app.screen().unwrap();
        for lane in 0..6 {
            let authored = &screen.corners[0].lanes[lane].stage;
            if let RootGeometry::Conjugate { hz, radius } = authored.pole {
                let mark = roots_from_probe_row(&screen.current_probe.rows[lane], RootSide::Pole);
                let RootMark::Conjugate {
                    hz: mark_hz,
                    radius: mark_radius,
                } = mark
                else {
                    panic!("conjugate authored pole must factor as conjugate: {mark:?}");
                };
                assert!(
                    (mark_hz - hz).abs() < 1.0,
                    "S{} pole hz: authored {hz} vs probe {mark_hz}",
                    lane + 1
                );
                assert!(
                    (mark_radius - radius).abs() < 1e-3,
                    "S{} pole radius: authored {radius} vs probe {mark_radius}",
                    lane + 1
                );
            }
        }
    }

    /// Gate 6: BODY SOLO and PRODUCT renders are finite, use a fixed input,
    /// and are never per-render normalized. Deterministic equality across
    /// calls is what proves the fixed input.
    #[test]
    fn body_solo_and_product_renders_are_finite_fixed_and_unnormalized() {
        let app = app();
        for mode in [AudioMode::BodySolo, AudioMode::Product] {
            let render =
                render_audio_at(&app.state.session, mode, Excitation::Probe, 0.5, 0.5).unwrap();
            let again =
                render_audio_at(&app.state.session, mode, Excitation::Probe, 0.5, 0.5).unwrap();
            assert!(!render.normalized, "{mode:?} must not be normalized");
            assert!(render.input_peak > 0.0, "fixed input must be non-silent");
            assert_eq!(
                render.input_peak, again.input_peak,
                "input stimulus must be identical across renders"
            );
            assert_eq!(
                render.wav_bytes, again.wav_bytes,
                "same body, same input, same mode: bytes must be identical"
            );
            assert!(render.output_peak.is_finite() && render.output_rms.is_finite());
            assert!(render.output_peak > 0.0, "{mode:?} render must be non-silent");
            // A body whose raw cascade exceeds unity must report that peak
            // honestly; nothing here may clamp it away or re-normalize.
            let pcm_peak = render
                .wav_bytes
                .chunks_exact(2)
                .skip(22) // 44-byte RIFF header
                .map(|bytes| i16::from_le_bytes([bytes[0], bytes[1]]).abs())
                .max()
                .unwrap_or(0);
            assert!(pcm_peak > 0, "{mode:?} PCM container must be non-silent");
        }
    }

    /// Gate 5/export: Export uses the retained keep() path. It either writes
    /// a fresh content-addressed bundle (body240 + session + audit + both
    /// renders) or refuses because that exact content was already exported —
    /// never a silent overwrite of the source body or a previous run.
    #[test]
    fn export_keep_writes_bundle_or_refuses_duplicate_content() {
        let mut app = app();
        let source_bytes = app.body_path.as_ref().map(|path| fs::read(path).unwrap());
        match app.state.keep() {
            Ok(receipt) => {
                let dir = PathBuf::from(&receipt.directory);
                for artifact in [
                    "body240",
                    "session.json",
                    "audit.json",
                    "cartridge.json",
                    "body_solo.wav",
                    "product.wav",
                ] {
                    assert!(
                        dir.join(artifact).exists(),
                        "export bundle is missing {artifact}"
                    );
                }
                let exported = fs::read(dir.join("body240")).unwrap();
                assert_eq!(
                    exported,
                    app.working_body_bytes().unwrap(),
                    "exported body must equal the working packed body"
                );
            }
            Err(error) => {
                let message = error.to_string();
                assert!(
                    message.contains("already exists"),
                    "only a duplicate-content refusal is acceptable here: {message}"
                );
            }
        }
        if let Some(bytes) = source_bytes {
            let path = app.body_path.clone().unwrap();
            assert_eq!(
                fs::read(&path).unwrap(),
                bytes,
                "export must never touch the source body file"
            );
        }
    }

    // -- make paths -----------------------------------------------------------

    /// MAKE/FROM AUDIO: one owned wav becomes a certified six-actor scaffold
    /// through the surface wiring, as one undo step.
    #[test]
    fn make_from_audio_produces_certified_scaffold() {
        let mut app = app();
        assert!(
            !app.actor_wavs.is_empty(),
            "measured_objects wavs must be present for the actor path"
        );
        let before = app.working_body_bytes().unwrap();
        let undo_depth = app.state.undo.len();
        let mut made = false;
        for index in 0..app.actor_wavs.len().min(8) {
            app.actor_wav = index;
            app.make_from_audio();
            if !app.status_error {
                made = true;
                break;
            }
        }
        assert!(made, "no measured wav produced an actor scaffold");
        assert_eq!(app.state.undo.len(), undo_depth + 1, "actor load is one undo step");
        assert!(app.state.audit.pass && app.state.audit.certify_pass);
        assert_ne!(app.working_body_bytes().unwrap(), before);
    }

    /// MAKE/FROM RECIPE: the catalog is populated from disk, and one apply is
    /// certified, zero-scope-only, one undo step.
    #[test]
    fn make_from_recipe_is_certified_and_zero_scoped() {
        let mut app = app();
        assert!(
            !app.state.recipe_catalog.candidates.is_empty(),
            "recipe-index must yield candidates for the loaded scaffold"
        );
        let undo_depth = app.state.undo.len();
        app.recipe_sel = 0;
        app.make_from_recipe();
        assert!(!app.status_error, "recipe apply failed: {}", app.status);
        let report = app
            .state
            .last_recipe_apply
            .clone()
            .expect("apply must record a recipe report");
        assert!(report.declared_zero_word_scope_only);
        assert!(report.sampled_audit_after.pass && report.sampled_audit_after.certify_pass);
        assert!(report.cartridge_parity_after);
        assert_eq!(app.state.undo.len(), undo_depth + 1);
    }

    /// MAKE/FROM XML: heritage stages fill exactly the selected corner.
    #[test]
    fn make_fill_corner_touches_only_the_selected_corner() {
        let mut app = app();
        assert!(
            !app.state.source_catalog.sources.is_empty(),
            "heritage XML well must be discovered"
        );
        app.state.select(2, 0).unwrap();
        let undo_depth = app.state.undo.len();
        app.source_sel = 0;
        app.endpoint_high = false;
        app.make_fill_corner();
        assert!(!app.status_error, "corner fill failed: {}", app.status);
        let report = app
            .state
            .last_source_apply
            .clone()
            .expect("fill must record a source report");
        assert_eq!(report.corner_index, 2);
        assert_eq!(report.lane_indices.len(), 6, "fill assigns all six lanes");
        assert!(report
            .changed_words
            .iter()
            .all(|word| word.corner_index == 2));
        assert!(report.sampled_audit_after.pass && report.cartridge_parity_after);
        assert_eq!(app.state.undo.len(), undo_depth + 1);
    }

    // -- audio-thread boundary ----------------------------------------------

    fn stream_for(
        body: &[u8; 240],
        wav: Arc<Vec<f32>>,
        control: Arc<Mutex<AuditionControl>>,
    ) -> AuditionStream {
        AuditionStream {
            engine: build_audition_engine(body, AudioMode::BodySolo).unwrap(),
            wav,
            cursor: 0,
            control,
            buf: Vec::new(),
            right: Vec::new(),
            pos: 0,
        }
    }

    #[test]
    fn held_stream_equals_direct_process_block() {
        let app = app();
        let body = app.working_body_bytes().unwrap();
        let wav = Arc::new(probe_wav(AUDITION_BLOCK * 4));
        let (morph, q) = (0.372, 0.64);
        let control = Arc::new(Mutex::new(AuditionControl {
            morph,
            q,
            reload: None,
        }));
        let mut stream = stream_for(&body, wav.clone(), control);
        let streamed: Vec<f32> = (0..AUDITION_BLOCK).map(|_| stream.next().unwrap()).collect();

        let mut left = wav[..AUDITION_BLOCK].to_vec();
        let mut right = left.clone();
        let mut direct = build_audition_engine(&body, AudioMode::BodySolo).unwrap();
        direct.process_block(&mut left, &mut right, morph, q);
        for (streamed, direct) in streamed.iter().zip(left.iter()) {
            assert!(
                (streamed - direct).abs() < 1e-6,
                "monitor must equal a direct process_block: {streamed} vs {direct}"
            );
        }
    }

    #[test]
    fn mid_stream_pad_change_changes_the_audio() {
        let app = app();
        let body = app.working_body_bytes().unwrap();
        let render = |flip: bool| -> Vec<f32> {
            let wav = Arc::new(probe_wav(AUDITION_BLOCK * 4));
            let control = Arc::new(Mutex::new(AuditionControl {
                morph: 0.2,
                q: 0.2,
                reload: None,
            }));
            let mut stream = stream_for(&body, wav, control.clone());
            let mut out = Vec::new();
            for _ in 0..AUDITION_BLOCK * 100 {
                out.push(stream.next().unwrap());
            }
            if flip {
                let mut control = control.lock().unwrap();
                control.morph = 0.9;
                control.q = 0.9;
            }
            for _ in 0..AUDITION_BLOCK * 100 {
                out.push(stream.next().unwrap());
            }
            out
        };
        let steady = render(false);
        let flipped = render(true);
        let tail_delta: f32 = steady
            .iter()
            .zip(flipped.iter())
            .skip(AUDITION_BLOCK * 100)
            .map(|(a, b)| (a - b).abs())
            .sum();
        assert!(
            tail_delta > 1e-3,
            "pad writes must cross the boundary live (delta {tail_delta})"
        );
    }

    #[test]
    fn reload_swaps_body_at_block_boundary() {
        let app = app();
        let body = app.working_body_bytes().unwrap();
        // A declared Scale edit builds the swapped-in candidate body.
        let request = EditRequest {
            corner_indices: vec![0, 1, 2, 3],
            lane_indices: vec![0],
            field: EditField::Scale,
            value: 1.0,
            secondary_value: None,
            relative: true,
        };
        let edited = app
            .state
            .session
            .preview_edit(&request)
            .unwrap()
            .to_body_bytes()
            .unwrap();
        assert_ne!(body, edited);

        let wav = Arc::new(probe_wav(AUDITION_BLOCK * 8));
        let control = Arc::new(Mutex::new(AuditionControl {
            morph: 0.4,
            q: 0.3,
            reload: None,
        }));
        let mut stream = stream_for(&body, wav.clone(), control.clone());
        let _: Vec<f32> = (0..AUDITION_BLOCK).map(|_| stream.next().unwrap()).collect();
        control.lock().unwrap().reload =
            Some(build_audition_engine(&edited, AudioMode::BodySolo).unwrap());
        let streamed: Vec<f32> = (0..AUDITION_BLOCK).map(|_| stream.next().unwrap()).collect();

        // Second block, fresh engine over the edited body, same WAV segment.
        let mut left = wav[AUDITION_BLOCK..AUDITION_BLOCK * 2].to_vec();
        let mut right = left.clone();
        let mut direct = build_audition_engine(&edited, AudioMode::BodySolo).unwrap();
        direct.process_block(&mut left, &mut right, 0.4, 0.3);
        for (streamed, direct) in streamed.iter().zip(left.iter()) {
            assert!(
                (streamed - direct).abs() < 1e-6,
                "swapped engine must drive the next block: {streamed} vs {direct}"
            );
        }
    }
}
