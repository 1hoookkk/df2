use eframe::egui::{
    self, Align, Align2, Color32, FontId, Layout, Pos2, Rect, Response, RichText, Rounding, Sense,
    Stroke, Vec2,
};
use rodio::{Decoder, OutputStream, Sink, Source};
use std::collections::BTreeMap;
use std::fs::{self, File};
use std::io::{BufReader, Cursor};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use trench_core::cartridge::Cartridge;
use trench_core::engine::{FilterEngine, InputMode, SpatialMode};
use trench_core::response::ResponseCurve;
use trench_core::stage_law::STAGE_SR;
use trench_workstation::app::AppState;
use trench_workstation::model::{
    render_audio_at, AudioMode, EditField, EditRequest, Excitation, RootGeometry, ScreenData,
    Session, StageSnapshot,
};

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
const DB_MIN: f64 = -48.0;
const DB_MAX: f64 = 24.0;
const CORNER_UI_LABELS: [&str; 4] = ["M0 Q0", "M100 Q0", "M0 Q100", "M100 Q100"];

#[derive(Clone, Copy, PartialEq, Eq)]
enum Triage {
    Keep,
    Repair,
    Reject,
}

impl Triage {
    fn label(self) -> &'static str {
        match self {
            Self::Keep => "KEEP",
            Self::Repair => "REPAIR",
            Self::Reject => "REJECT",
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum RootSide {
    Pole,
    Zero,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum RootHandle {
    Conjugate(RootSide),
    Real(RootSide, bool),
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Transport {
    Sweeping,
    Held,
}

#[derive(Clone, Copy)]
struct CaptureInfo {
    morph: f64,
    q: f64,
}

/// Shared control block between the egui main thread (writer of morph/q/transport)
/// and the rodio audio thread (writer of the reported playhead/time). The audio
/// engine itself is owned by the `AuditionStream` on the audio thread; only this
/// small struct crosses the boundary.
struct AuditionControl {
    // GUI writes / audio reads:
    q: f64,
    morph: f64, // HELD target and sweep resume point
    transport: Transport,
    sweep_len_frames: u64,
    reload: Option<FilterEngine>, // swap a fresh engine in at the next block boundary
    // audio writes / GUI reads:
    playhead: f64,
    time_frames: u64,
    held_at_end: bool,
}

const AUDITION_BLOCK: usize = 64;

/// Continuous, looping audition source: owns a retained `FilterEngine` and the
/// decoded WAV, and processes real audio one `AUDITION_BLOCK` at a time reading
/// live Morph/Q/transport from `control`. This is the real-time streaming host
/// the engine was already built for (`process_block` takes morph/q per block).
struct AuditionStream {
    engine: FilterEngine,
    wav: Arc<Vec<f32>>,
    wav_cursor: usize, // monotonic frames read (wraps mod wav.len for looping)
    sweep_pos: u64,    // morph-clock position in frames
    last_transport: Transport,
    control: Arc<Mutex<AuditionControl>>,
    buf: Vec<f32>, // processed output block (yield source)
    right: Vec<f32>,
    pos: usize,
}

impl AuditionStream {
    fn refill(&mut self) {
        let wav_len = self.wav.len().max(1);
        // ponytail: one Mutex lock per 64-sample block (~1.6 ms); go lock-free
        // atomics only if it ever xruns.
        let (q, morph_target, transport, sweep_len, reload) = {
            let mut control = self.control.lock().unwrap();
            (
                control.q,
                control.morph,
                control.transport,
                control.sweep_len_frames.max(1),
                control.reload.take(),
            )
        };
        if let Some(engine) = reload {
            // Fresh engine: filter state reset deterministically; WAV cursor and
            // morph are preserved because they live here, not in the engine.
            // ponytail: dropping the old engine frees on the audio thread — fine
            // for a desktop monitor; hand it back to the UI thread if it glitches.
            self.engine = engine;
        }

        self.buf.clear();
        for _ in 0..AUDITION_BLOCK {
            self.buf.push(self.wav[self.wav_cursor % wav_len]);
            self.wav_cursor += 1;
        }
        self.right.clear();
        self.right.extend_from_slice(&self.buf);

        let mut latched_end = false;
        let morph = match transport {
            Transport::Sweeping => {
                if self.last_transport == Transport::Held {
                    // Resume or scrub: re-anchor the sweep clock to the morph.
                    self.sweep_pos = (morph_target * sweep_len as f64) as u64;
                }
                self.sweep_pos = self.sweep_pos.saturating_add(AUDITION_BLOCK as u64);
                if self.sweep_pos >= sweep_len {
                    latched_end = true;
                    1.0
                } else {
                    self.sweep_pos as f64 / sweep_len as f64
                }
            }
            Transport::Held => morph_target,
        };
        self.last_transport = if latched_end {
            Transport::Held
        } else {
            transport
        };

        self.engine
            .process_block(&mut self.buf, &mut self.right, morph, q);

        let mut control = self.control.lock().unwrap();
        control.playhead = morph;
        control.time_frames = self.wav_cursor as u64;
        if matches!(transport, Transport::Sweeping) {
            control.morph = morph; // so a later HOLD freezes exactly here
        }
        if latched_end {
            control.transport = Transport::Held;
            control.morph = 1.0;
            control.held_at_end = true;
        }
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

struct StudioApp {
    repo_root: PathBuf,
    state: AppState,
    original_session: Session,
    original_audit: trench_workstation::model::SampledAudit,
    showing_original: bool,
    bodies: Vec<PathBuf>,
    selected_body: Option<PathBuf>,
    query: String,
    triage: BTreeMap<PathBuf, Triage>,
    mode: AudioMode,
    inspect: bool,
    dirty: bool,
    status: String,
    status_error: bool,
    locks: [[StageLocks; 6]; 4],
    stream: Option<OutputStream>,
    sink: Option<Sink>,
    active_root: Option<RootHandle>,
    wav_sources: Vec<PathBuf>,
    selected_wav: usize,
    audition: Option<Arc<Mutex<AuditionControl>>>,
    audition_q: f64,
    captured: [Option<CaptureInfo>; 4],
}

#[derive(Clone, Copy)]
struct StageLocks {
    pole: bool,
    zero: bool,
}

impl StageLocks {
    const LOCKED: Self = Self {
        pole: true,
        zero: true,
    };
}

impl StudioApp {
    fn new(repo_root: PathBuf) -> Result<Self, String> {
        let mut state = AppState::new(&repo_root).map_err(|error| error.to_string())?;
        let mut bodies = fs::read_dir(repo_root.join("filters").join("bodies"))
            .map_err(|error| format!("filter library could not be opened: {error}"))?
            .filter_map(Result::ok)
            .map(|entry| entry.path())
            .filter(|path| path.extension().and_then(|value| value.to_str()) == Some("body240"))
            .collect::<Vec<_>>();
        bodies.sort_by_key(|path| body_name(path).to_lowercase());
        let selected_body = bodies.first().cloned();
        let (status, status_error) = if let Some(path) = &selected_body {
            match state.load_body_as_session(path) {
                Ok(_) => {
                    state
                        .set_morph_q(0.0, 0.0)
                        .map_err(|error| error.to_string())?;
                    (
                        format!("Loaded {} · poles and zeros locked", body_name(path)),
                        false,
                    )
                }
                Err(error) => (error.to_string(), true),
            }
        } else {
            ("No filter bodies found".to_owned(), true)
        };
        let original_session = state.session.clone();
        let original_audit = state.audit.clone();
        let mut wav_sources = Vec::new();
        collect_wavs(&repo_root.join("wav-source-library"), &mut wav_sources)
            .map_err(|error| format!("WAV library could not be read: {error}"))?;
        wav_sources.sort();
        let selected_wav = wav_sources
            .iter()
            .position(|path| body_name(path).to_lowercase().contains("cello"))
            .unwrap_or(0);
        Ok(Self {
            repo_root,
            state,
            original_session,
            original_audit,
            showing_original: true,
            bodies,
            selected_body,
            query: String::new(),
            triage: BTreeMap::new(),
            mode: AudioMode::BodySolo,
            inspect: false,
            dirty: false,
            status,
            status_error,
            locks: [[StageLocks::LOCKED; 6]; 4],
            stream: None,
            sink: None,
            active_root: None,
            wav_sources,
            selected_wav,
            audition: None,
            audition_q: 0.0,
            captured: [None; 4],
        })
    }

    fn screen(&self) -> Result<ScreenData, String> {
        if self.showing_original {
            self.original_session
                .screen_with_audit(
                    self.state.selected_corner,
                    self.state.selected_lane,
                    self.state.morph,
                    self.state.q,
                    self.original_audit.clone(),
                )
                .map_err(|error| error.to_string())
        } else if let Some(preview) = &self.state.pending_edit {
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

    fn load_body(&mut self, path: PathBuf) {
        self.stop_audio();
        match self.state.load_body_as_session(&path) {
            Ok(_) => {
                if let Err(error) = self.state.set_morph_q(0.0, 0.0) {
                    self.set_error(error.to_string());
                    return;
                }
                self.selected_body = Some(path.clone());
                self.original_session = self.state.session.clone();
                self.original_audit = self.state.audit.clone();
                self.showing_original = true;
                self.dirty = false;
                self.locks = [[StageLocks::LOCKED; 6]; 4];
                self.captured = [None; 4];
                self.set_status(format!(
                    "Loaded {} · poles and zeros locked",
                    body_name(&path)
                ));
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn stop_audio(&mut self) {
        if let Some(sink) = self.sink.take() {
            sink.stop();
        }
        self.stream = None;
        self.audition = None;
    }

    fn toggle_audio(&mut self) {
        if self.sink.as_ref().is_some_and(|sink| !sink.empty()) {
            self.stop_audio();
            self.set_status("Audition stopped");
            return;
        }
        self.stop_audio();
        let session = if self.showing_original {
            &self.original_session
        } else {
            &self.state.session
        };
        let render = match render_audio_at(
            session,
            self.mode,
            Excitation::Pink,
            self.state.morph,
            self.state.q,
        ) {
            Ok(render) => render,
            Err(error) => {
                self.set_error(error.to_string());
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
        match Decoder::new(Cursor::new(render.wav_bytes)) {
            Ok(source) => sink.append(source),
            Err(error) => {
                self.set_error(format!("audition buffer could not be decoded: {error}"));
                return;
            }
        }
        sink.play();
        self.stream = Some(stream);
        self.sink = Some(sink);
        self.set_status(format!(
            "Playing pink noise · {} · M{:.0} Q{:.0} · peak {:.3}",
            if self.mode == AudioMode::BodySolo {
                "BODY SOLO"
            } else {
                "PRODUCT"
            },
            self.state.morph * 100.0,
            self.state.q * 100.0,
            render.output_peak
        ));
    }

    fn shown_body_bytes(&self) -> Result<[u8; 240], String> {
        let session = if self.showing_original {
            &self.original_session
        } else {
            &self.state.session
        };
        session.to_body_bytes().map_err(|error| error.to_string())
    }

    fn start_audition(&mut self) {
        let Some(path) = self.wav_sources.get(self.selected_wav).cloned() else {
            self.set_error("No WAV source is available for the audition");
            return;
        };
        self.stop_audio();
        let body = match self.shown_body_bytes() {
            Ok(bytes) => bytes,
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
        let wav = match decode_wav_to_stage_sr(&path) {
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
            q: self.audition_q,
            morph: 0.0,
            transport: Transport::Sweeping,
            sweep_len_frames: wav.len() as u64,
            reload: None,
            playhead: 0.0,
            time_frames: 0,
            held_at_end: false,
        }));
        let source = AuditionStream {
            engine,
            wav,
            wav_cursor: 0,
            sweep_pos: 0,
            last_transport: Transport::Sweeping,
            control: control.clone(),
            buf: Vec::with_capacity(AUDITION_BLOCK),
            right: Vec::with_capacity(AUDITION_BLOCK),
            pos: 0,
        };
        // Fixed monitor attenuation (~-12 dB); visible, and does not affect capture.
        sink.set_volume(0.25);
        sink.append(source);
        sink.play();
        self.stream = Some(stream);
        self.sink = Some(sink);
        self.audition = Some(control);
        let _ = self.state.set_morph_q(0.0, self.audition_q);
        self.set_status(format!(
            "Auditioning {} · {} · sweeping M0 → M100 · monitor -12 dB",
            body_name(&path),
            if self.mode == AudioMode::BodySolo {
                "BODY SOLO"
            } else {
                "PRODUCT"
            }
        ));
    }

    fn audition_is_held(&self) -> bool {
        self.audition.as_ref().is_some_and(|control| {
            matches!(control.lock().unwrap().transport, Transport::Held)
        })
    }

    fn hold_toggle(&mut self) {
        let Some(control) = self.audition.clone() else {
            self.set_error("Start an audition before holding");
            return;
        };
        let resumed = {
            let mut control = control.lock().unwrap();
            control.held_at_end = false;
            match control.transport {
                Transport::Sweeping => {
                    control.transport = Transport::Held;
                    control.morph = control.playhead; // freeze at the current position
                    false
                }
                Transport::Held => {
                    control.transport = Transport::Sweeping;
                    true
                }
            }
        };
        self.set_status(if resumed {
            "Sweeping"
        } else {
            "Held · Morph and Q frozen, WAV still playing"
        });
    }

    fn scrub_morph(&mut self, morph: f64) {
        let morph = morph.clamp(0.0, 1.0);
        if let Some(control) = self.audition.clone() {
            let mut control = control.lock().unwrap();
            control.morph = morph;
            control.transport = Transport::Held;
            control.held_at_end = false;
        } else {
            let _ = self.state.set_morph_q(morph, self.audition_q);
        }
    }

    fn set_audition_q(&mut self, q: f64) {
        self.audition_q = q.clamp(0.0, 1.0);
        if let Some(control) = self.audition.clone() {
            // Q stays live during a sweep — it does NOT force HELD. This is the
            // headline feature (adjust Q while Morph keeps sweeping).
            control.lock().unwrap().q = self.audition_q;
        } else {
            let _ = self.state.set_morph_q(self.state.morph, self.audition_q);
        }
    }

    fn reload_audition_body(&mut self) {
        let Some(control) = self.audition.clone() else {
            return;
        };
        let body = match self.shown_body_bytes() {
            Ok(bytes) => bytes,
            Err(error) => {
                self.set_error(error);
                return;
            }
        };
        match build_audition_engine(&body, self.mode) {
            // Preserves WAV position + Morph/Q; only the body (and filter state) change.
            Ok(engine) => control.lock().unwrap().reload = Some(engine),
            Err(error) => self.set_error(error),
        }
    }

    fn start_new_audition_from_working(&mut self) {
        self.original_session = self.state.session.clone();
        self.original_audit = self.state.audit.clone();
        self.captured = [None; 4];
        self.showing_original = true;
        self.reload_audition_body();
        self.set_status("New audition source set from working · capture provenance cleared");
    }

    fn set_current(&mut self, corner: usize) {
        if corner >= 4 {
            return;
        }
        let (morph, q) = if let Some(control) = self.audition.clone() {
            // Freeze so the value cannot move between read and apply.
            let mut control = control.lock().unwrap();
            control.transport = Transport::Held;
            control.morph = control.playhead;
            control.held_at_end = false;
            (control.playhead, control.q)
        } else {
            (self.state.morph, self.state.q)
        };
        let source = self.original_session.clone();
        let wav = self
            .wav_sources
            .get(self.selected_wav)
            .map(|path| body_name(path))
            .unwrap_or_default();
        match self.state.capture_runtime_position_to_corner(
            &source,
            morph,
            q,
            corner,
            &wav,
            self.mode.as_str(),
        ) {
            Ok(report) => {
                self.captured[corner] = Some(CaptureInfo { morph, q });
                self.dirty = true;
                if let Err(error) = self.state.select(corner, self.state.selected_lane) {
                    self.set_error(error.to_string());
                    return;
                }
                self.set_status(format!(
                    "{} set from Morph {:.3}, Q {:.3} · {} packed words changed",
                    CORNER_UI_LABELS[corner],
                    morph,
                    q,
                    report.changed_words.len()
                ));
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn preview(&mut self, request: EditRequest) {
        match self.state.preview(request) {
            Ok(_) => {
                self.status_error = false;
                self.status = "Previewing packed edit".to_owned();
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn apply_preview(&mut self) {
        if self.state.pending_edit.is_none() {
            return;
        }
        match self.state.apply() {
            Ok(result) => {
                self.showing_original = false;
                self.dirty = true;
                let summary = result
                    .changed_words
                    .iter()
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
                    .join(" · ");
                self.set_status(if summary.is_empty() {
                    "No packed words changed".to_owned()
                } else {
                    summary
                });
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn root_locked(&self, corner: usize, lane: usize, side: RootSide) -> bool {
        match side {
            RootSide::Pole => self.locks[corner][lane].pole,
            RootSide::Zero => self.locks[corner][lane].zero,
        }
    }

    fn toggle_root_lock(&mut self, corner: usize, lane: usize, side: RootSide) {
        self.showing_original = false;
        self.focus_corner(corner);
        let lock = &mut self.locks[corner][lane];
        let value = match side {
            RootSide::Pole => &mut lock.pole,
            RootSide::Zero => &mut lock.zero,
        };
        *value = !*value;
        let locked = *value;
        self.set_status(format!(
            "{} {} · S{}",
            match side {
                RootSide::Pole => "Poles",
                RootSide::Zero => "Zeros",
            },
            if locked { "locked" } else { "unlocked" },
            lane + 1
        ));
    }

    fn focus_corner(&mut self, corner: usize) {
        let (morph, q) = match corner {
            0 => (0.0, 0.0),
            1 => (1.0, 0.0),
            2 => (0.0, 1.0),
            3 => (1.0, 1.0),
            _ => return,
        };
        if let Err(error) = self.state.set_morph_q(morph, q) {
            self.set_error(error.to_string());
        }
    }

    fn undo(&mut self) {
        match self.state.undo() {
            Ok(()) => {
                self.showing_original = false;
                self.dirty = true;
                self.set_status("Undid one edit gesture");
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn redo(&mut self) {
        match self.state.redo() {
            Ok(()) => {
                self.showing_original = false;
                self.dirty = true;
                self.set_status("Redid one edit gesture");
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn keep(&mut self) {
        self.showing_original = false;
        match self.state.keep() {
            Ok(receipt) => {
                self.dirty = false;
                self.set_status(format!("Saved version · {}", receipt.directory));
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn changed_word_count(&self) -> usize {
        let Ok(original) = self.original_session.to_body_bytes() else {
            return 0;
        };
        let Ok(working) = self.state.session.to_body_bytes() else {
            return 0;
        };
        original
            .chunks_exact(2)
            .zip(working.chunks_exact(2))
            .filter(|(left, right)| left != right)
            .count()
    }

    fn reset_working(&mut self) {
        let Some(path) = self.selected_body.clone() else {
            self.set_error("There is no loaded body to restore");
            return;
        };
        match self.state.load_body_as_session(&path) {
            Ok(_) => {
                self.locks = [[StageLocks::LOCKED; 6]; 4];
                self.dirty = false;
                self.showing_original = true;
                self.set_status("Working copy reset to the loaded original");
            }
            Err(error) => self.set_error(error.to_string()),
        }
    }

    fn triage_current(&mut self, value: Triage) {
        let Some(path) = self.selected_body.clone() else {
            self.set_error("Select a library filter before triage");
            return;
        };
        self.triage.insert(path.clone(), value);
        self.set_status(format!("{} · {}", value.label(), body_name(&path)));
        if value == Triage::Reject {
            self.advance_after_reject(&path);
        }
    }

    fn advance_after_reject(&mut self, current: &Path) {
        let Some(index) = self.bodies.iter().position(|path| path == current) else {
            return;
        };
        let next = self
            .bodies
            .iter()
            .cycle()
            .skip(index + 1)
            .take(self.bodies.len())
            .find(|path| self.triage.get(*path) != Some(&Triage::Reject))
            .cloned();
        if let Some(path) = next {
            self.load_body(path);
        }
    }

    fn top_bar(&mut self, ctx: &egui::Context, screen: &ScreenData) {
        egui::TopBottomPanel::top("toolbar")
            .exact_height(52.0)
            .frame(
                egui::Frame::none()
                    .fill(PANEL)
                    .inner_margin(egui::Margin::symmetric(14.0, 8.0)),
            )
            .show(ctx, |ui| {
                ui.horizontal(|ui| {
                    let playing = self.sink.as_ref().is_some_and(|sink| !sink.empty());
                    if primary_button(ui, if playing { "STOP" } else { "PLAY" }).clicked() {
                        self.toggle_audio();
                    }
                    ui.label(RichText::new("PINK NOISE").size(11.0).color(MUTED));
                    separator(ui);
                    if quiet_button(ui, "UNDO", self.state.undo.len() > 0).clicked() {
                        self.undo();
                    }
                    if quiet_button(ui, "REDO", self.state.redo.len() > 0).clicked() {
                        self.redo();
                    }
                    if quiet_button(ui, "SAVE VERSION", true).clicked() {
                        self.keep();
                    }
                    separator(ui);
                    segmented(ui, "ORIGINAL", self.showing_original, || {
                        self.showing_original = true;
                        self.state.discard_preview();
                        self.reload_audition_body();
                        self.set_status("Auditioning loaded source");
                    });
                    segmented(ui, "WORKING", !self.showing_original, || {
                        self.showing_original = false;
                        self.reload_audition_body();
                        self.set_status("Auditioning working copy");
                    });
                    if quiet_button(ui, "RESET", self.changed_word_count() > 0).clicked() {
                        self.reset_working();
                    }
                    if quiet_button(ui, "SET AS SOURCE", self.changed_word_count() > 0).clicked() {
                        self.start_new_audition_from_working();
                    }
                    let changed_words = self.changed_word_count();
                    ui.label(
                        RichText::new(format!("{changed_words} CHANGED"))
                            .size(9.0)
                            .color(if changed_words > 0 { WARN } else { MUTED }),
                    );
                    separator(ui);
                    segmented(ui, "BODY SOLO", self.mode == AudioMode::BodySolo, || {
                        self.mode = AudioMode::BodySolo;
                        self.reload_audition_body();
                    });
                    segmented(ui, "PRODUCT", self.mode == AudioMode::Product, || {
                        self.mode = AudioMode::Product;
                        self.reload_audition_body();
                    });
                    separator(ui);
                    for value in [Triage::Keep, Triage::Repair, Triage::Reject] {
                        if quiet_button(ui, value.label(), true).clicked() {
                            self.triage_current(value);
                        }
                    }
                    ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                        let inspect = ui.selectable_label(self.inspect, "INSPECT");
                        if inspect.clicked() {
                            self.inspect = !self.inspect;
                        }
                        ui.add_space(10.0);
                        ui.label(
                            RichText::new(format!(
                                "{}  /  S{}",
                                screen.name,
                                screen.selected_lane + 1
                            ))
                            .strong()
                            .color(TEXT),
                        );
                        if self.changed_word_count() > 0 {
                            ui.label(RichText::new("UNSAVED").size(10.0).color(WARN));
                        }
                    });
                });
            });
    }

    fn library(&mut self, ctx: &egui::Context) {
        egui::SidePanel::left("library")
            .default_width(238.0)
            .width_range(190.0..=360.0)
            .resizable(true)
            .frame(panel_frame())
            .show(ctx, |ui| {
                section_heading(
                    ui,
                    "FILTER LIBRARY",
                    &format!("{} BODIES", self.bodies.len()),
                );
                ui.add(
                    egui::TextEdit::singleline(&mut self.query)
                        .hint_text("Search filters")
                        .desired_width(f32::INFINITY),
                );
                ui.add_space(8.0);
                if quiet_button(ui, "OPEN BODY…", true).clicked() {
                    if let Some(path) = rfd::FileDialog::new()
                        .add_filter("TRENCH body", &["body240"])
                        .set_directory(self.repo_root.join("filters").join("bodies"))
                        .pick_file()
                    {
                        self.load_body(path);
                    }
                }
                ui.add_space(8.0);
                let query = self.query.trim().to_lowercase();
                let visible = self
                    .bodies
                    .iter()
                    .filter(|path| {
                        query.is_empty() || body_name(path).to_lowercase().contains(&query)
                    })
                    .cloned()
                    .collect::<Vec<_>>();
                egui::ScrollArea::vertical()
                    .auto_shrink([false, false])
                    .show(ui, |ui| {
                        for path in visible {
                            let selected = self.selected_body.as_ref() == Some(&path);
                            let name = body_name(&path);
                            let response =
                                library_row(ui, &name, self.triage.get(&path).copied(), selected);
                            if response.clicked() {
                                self.load_body(path);
                            }
                        }
                    });
            });
    }

    fn main_view(&mut self, ctx: &egui::Context, screen: &ScreenData) {
        egui::CentralPanel::default()
            .frame(
                egui::Frame::none()
                    .fill(BG)
                    .inner_margin(egui::Margin::same(12.0)),
            )
            .show(ctx, |ui| {
                let available = ui.available_size();
                let lower_height = (available.y * 0.42).clamp(260.0, 390.0);
                ui.allocate_ui_with_layout(
                    Vec2::new(available.x, (available.y - lower_height - 12.0).max(230.0)),
                    Layout::top_down(Align::Min),
                    |ui| self.response_panel(ui, screen),
                );
                ui.add_space(12.0);
                ui.columns(2, |columns| {
                    columns[0].set_min_width(280.0);
                    egui::Frame::none()
                        .fill(PANEL)
                        .rounding(Rounding::same(6.0))
                        .inner_margin(egui::Margin::same(14.0))
                        .show(&mut columns[0], |ui| self.audition_view(ui, screen));
                    egui::Frame::none()
                        .fill(PANEL)
                        .rounding(Rounding::same(6.0))
                        .inner_margin(egui::Margin::same(14.0))
                        .show(&mut columns[1], |ui| self.stage_properties(ui, screen));
                });
            });
    }

    fn response_panel(&mut self, ui: &mut egui::Ui, screen: &ScreenData) {
        egui::Frame::none()
            .fill(PANEL)
            .rounding(Rounding::same(6.0))
            .inner_margin(egui::Margin::same(14.0))
            .show(ui, |ui| {
                ui.horizontal(|ui| {
                    section_heading(ui, "COMBINED RESPONSE", "PACKED RUNTIME");
                    ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                        let audit_color = if screen.audit.pass { ACCENT } else { ERROR };
                        ui.label(
                            RichText::new(if screen.audit.pass {
                                "SAMPLED CERTIFICATION PASS"
                            } else {
                                "SAMPLED CERTIFICATION FAIL"
                            })
                            .size(10.0)
                            .color(audit_color),
                        );
                    });
                });
                ui.add_space(6.0);
                response_plot(
                    ui,
                    &screen.current_response,
                    pole_frequency(&screen.selected_stage),
                );
                ui.add_space(8.0);
                ui.horizontal(|ui| {
                    ui.add_space(8.0);
                    for lane in 0..6 {
                        let selected = lane == screen.selected_lane;
                        let button =
                            egui::Button::new(RichText::new(format!("S{}", lane + 1)).strong())
                                .selected(selected)
                                .min_size(Vec2::new(48.0, 28.0));
                        if ui.add(button).clicked() {
                            if let Err(error) = self.state.select(screen.selected_corner, lane) {
                                self.set_error(error.to_string());
                            }
                        }
                    }
                });
            });
    }

    fn audition_view(&mut self, ui: &mut egui::Ui, screen: &ScreenData) {
        section_heading(ui, "AUDITION", "REAL WAV · PACKED RUNTIME");
        ui.add_space(6.0);
        let source_label = self
            .wav_sources
            .get(self.selected_wav)
            .map(|path| body_name(path))
            .unwrap_or_else(|| "No WAV sources".to_owned());
        ui.label(RichText::new("SOURCE WAV").size(9.0).color(MUTED));
        egui::ComboBox::from_id_salt("audition_wav_source")
            .selected_text(source_label)
            .width(ui.available_width())
            .show_ui(ui, |ui| {
                for (index, path) in self.wav_sources.iter().enumerate() {
                    ui.selectable_value(&mut self.selected_wav, index, body_name(path));
                }
            });
        ui.add_space(8.0);

        let (time_frames, held_at_end, auditioning) = match &self.audition {
            Some(control) => {
                let control = control.lock().unwrap();
                (control.time_frames, control.held_at_end, true)
            }
            None => (0, false, false),
        };
        let held = self.audition_is_held();

        // Persistent readout — follows the audio within one processing block.
        ui.horizontal(|ui| {
            ui.label(
                RichText::new(format!("Morph {:.3}", screen.morph))
                    .strong()
                    .color(TEXT),
            );
            ui.add_space(12.0);
            ui.label(RichText::new(format!("Q {:.3}", screen.q)).strong().color(TEXT));
            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                ui.label(RichText::new(format_transport_time(time_frames)).color(MUTED));
            });
        });
        ui.add_space(6.0);

        // Transport.
        ui.horizontal(|ui| {
            if quiet_button(ui, "⏮", auditioning).clicked() {
                self.scrub_morph(0.0);
            }
            if auditioning {
                if primary_button(ui, if held { "RESUME" } else { "HOLD" }).clicked() {
                    self.hold_toggle();
                }
                if quiet_button(ui, "STOP", true).clicked() {
                    self.stop_audio();
                }
            } else if primary_button(ui, "PLAY SWEEP").clicked() {
                self.start_audition();
            }
            if quiet_button(ui, "⏭", auditioning).clicked() {
                self.scrub_morph(1.0);
            }
            if held_at_end {
                ui.label(RichText::new("HELD @ END").size(9.0).color(WARN));
            }
        });
        ui.add_space(8.0);

        // Precise native Morph and Q — not a drawing surface. Dragging Morph
        // enters HELD; Q stays live so it can be adjusted during a sweep.
        let mut morph = screen.morph;
        ui.label(RichText::new("MORPH").size(9.0).color(MUTED));
        if ui
            .add(egui::Slider::new(&mut morph, 0.0..=1.0).show_value(false))
            .changed()
        {
            self.scrub_morph(morph);
        }
        let mut q = self.audition_q;
        ui.label(RichText::new("Q").size(9.0).color(MUTED));
        if ui
            .add(egui::Slider::new(&mut q, 0.0..=1.0).show_value(false))
            .changed()
        {
            self.set_audition_q(q);
        }
        ui.add_space(10.0);
        ui.separator();
        ui.add_space(8.0);
        self.corner_rack(ui, screen);
    }

    fn corner_rack(&mut self, ui: &mut egui::Ui, screen: &ScreenData) {
        section_heading(ui, "CORNER RACK", "SET CURRENT → CORNER");
        ui.add_space(4.0);
        let captured = self.captured;
        let selected_corner = screen.selected_corner;
        let mut select: Option<usize> = None;
        let mut set: Option<usize> = None;
        for corner in 0..4 {
            let is_selected = selected_corner == corner;
            egui::Frame::none()
                .fill(if is_selected {
                    Color32::from_rgb(38, 57, 54)
                } else {
                    PANEL_RAISED
                })
                .rounding(Rounding::same(4.0))
                .inner_margin(egui::Margin::symmetric(8.0, 6.0))
                .show(ui, |ui| {
                    ui.horizontal(|ui| {
                        if ui
                            .selectable_label(
                                is_selected,
                                RichText::new(CORNER_UI_LABELS[corner]).strong(),
                            )
                            .clicked()
                        {
                            select = Some(corner);
                        }
                        let provenance = match captured[corner] {
                            Some(info) => format!("src M{:.3} / Q{:.3}", info.morph, info.q),
                            None => "not set this session".to_owned(),
                        };
                        ui.label(RichText::new(provenance).size(9.0).color(MUTED));
                        ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                            if quiet_button(ui, "SET CURRENT", true).clicked() {
                                set = Some(corner);
                            }
                        });
                    });
                });
            ui.add_space(4.0);
        }
        ui.label(
            RichText::new("Exact interpolated u16 words from the source · Ctrl+1..4")
                .size(9.0)
                .color(MUTED),
        );
        if let Some(corner) = select {
            if let Err(error) = self.state.select(corner, screen.selected_lane) {
                self.set_error(error.to_string());
            }
        }
        if let Some(corner) = set {
            self.set_current(corner);
        }
    }

    fn stage_properties(&mut self, ui: &mut egui::Ui, screen: &ScreenData) {
        let corner_label = screen
            .corners
            .get(screen.selected_corner)
            .map(|corner| corner.label.as_str())
            .unwrap_or("POSITION");
        section_heading(
            ui,
            "SECTION PROPERTIES",
            &format!(
                "{} · S{} · AUDITION M{:.0} Q{:.0}",
                corner_label,
                screen.selected_lane + 1,
                screen.morph * 100.0,
                screen.q * 100.0
            ),
        );
        ui.add_space(8.0);
        ui.columns(2, |columns| {
            columns[0].set_min_width(210.0);
            self.z_plane(&mut columns[0], screen);
            self.numeric_controls(&mut columns[1], screen);
        });
        if self.inspect {
            ui.add_space(8.0);
            ui.separator();
            inspect_data(ui, &screen.selected_stage);
        }
    }

    fn z_plane(&mut self, ui: &mut egui::Ui, screen: &ScreenData) {
        ui.label(RichText::new("Z-PLANE").size(10.0).color(MUTED));
        let side = ui
            .available_width()
            .min((ui.available_height() - 22.0).max(150.0));
        let (rect, response) = ui.allocate_exact_size(Vec2::splat(side), Sense::click_and_drag());
        let painter = ui.painter_at(rect);
        painter.rect_filled(rect, Rounding::same(4.0), PANEL_RAISED);
        let center = rect.center();
        let radius = rect.width().min(rect.height()) * 0.41;
        painter.circle_stroke(
            center,
            radius,
            Stroke::new(1.0, Color32::from_rgb(82, 90, 100)),
        );
        painter.line_segment(
            [
                Pos2::new(center.x - radius, center.y),
                Pos2::new(center.x + radius, center.y),
            ],
            Stroke::new(1.0, LINE),
        );
        painter.line_segment(
            [
                Pos2::new(center.x, center.y - radius),
                Pos2::new(center.x, center.y + radius),
            ],
            Stroke::new(1.0, LINE),
        );
        draw_root_pair(
            &painter,
            center,
            radius,
            &screen.selected_stage.zero,
            RootSide::Zero,
        );
        draw_root_pair(
            &painter,
            center,
            radius,
            &screen.selected_stage.pole,
            RootSide::Pole,
        );
        if response.drag_started() {
            if let Some(position) = response.interact_pointer_pos() {
                if self.showing_original {
                    self.active_root = None;
                    self.set_error("Switch to WORKING before editing roots");
                    return;
                }
                self.active_root =
                    nearest_root_handle(position, center, radius, &screen.selected_stage);
                if let Some(handle) = self.active_root {
                    let side = root_handle_side(handle);
                    if self.root_locked(screen.selected_corner, screen.selected_lane, side) {
                        self.active_root = None;
                        self.set_error(format!(
                            "Unlock {} for {} · S{} before editing",
                            match side {
                                RootSide::Pole => "poles",
                                RootSide::Zero => "zeros",
                            },
                            screen.corners[screen.selected_corner].label,
                            screen.selected_lane + 1
                        ));
                    } else {
                        self.focus_corner(screen.selected_corner);
                    }
                }
            }
        }
        if response.dragged() {
            if let (Some(handle), Some(position)) =
                (self.active_root, response.interact_pointer_pos())
            {
                let x = ((position.x - center.x) / radius).clamp(-1.0, 1.0) as f64;
                let y = ((center.y - position.y) / radius).clamp(-1.0, 1.0) as f64;
                let request = match handle {
                    RootHandle::Conjugate(side) => {
                        let root_radius = (x * x + y * y).sqrt().clamp(0.0, 0.999_98);
                        let angle = y.abs().atan2(x).clamp(0.0, std::f64::consts::PI);
                        let hz = angle / std::f64::consts::PI * STAGE_SR * 0.5;
                        EditRequest::conjugate(
                            vec![screen.selected_corner],
                            screen.selected_lane,
                            side == RootSide::Pole,
                            hz,
                            root_radius,
                        )
                    }
                    RootHandle::Real(side, first) => EditRequest::single(
                        screen.selected_corner,
                        screen.selected_lane,
                        match (side, first) {
                            (RootSide::Pole, true) => EditField::PoleRootA,
                            (RootSide::Pole, false) => EditField::PoleRootB,
                            (RootSide::Zero, true) => EditField::ZeroRootA,
                            (RootSide::Zero, false) => EditField::ZeroRootB,
                        },
                        x,
                    ),
                };
                self.preview(request);
            }
        }
        if response.drag_stopped() {
            self.active_root = None;
            self.apply_preview();
        }
        ui.horizontal(|ui| {
            ui.label(
                RichText::new(
                    if self.root_locked(
                        screen.selected_corner,
                        screen.selected_lane,
                        RootSide::Pole,
                    ) {
                        "POLE LOCKED"
                    } else {
                        "POLE EDITABLE"
                    },
                )
                .size(9.0)
                .color(ACCENT),
            );
            ui.label(
                RichText::new(
                    if self.root_locked(
                        screen.selected_corner,
                        screen.selected_lane,
                        RootSide::Zero,
                    ) {
                        "ZERO LOCKED"
                    } else {
                        "ZERO EDITABLE"
                    },
                )
                .size(9.0)
                .color(TEXT),
            );
            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                ui.label(RichText::new("DRAG ROOTS").size(9.0).color(MUTED));
            });
        });
    }

    fn numeric_controls(&mut self, ui: &mut egui::Ui, screen: &ScreenData) {
        let pole_locked =
            self.root_locked(screen.selected_corner, screen.selected_lane, RootSide::Pole);
        let zero_locked =
            self.root_locked(screen.selected_corner, screen.selected_lane, RootSide::Zero);
        ui.horizontal(|ui| {
            if ui
                .add_enabled_ui(!self.showing_original, |ui| {
                    lock_button(ui, "POLES", pole_locked)
                })
                .inner
                .clicked()
            {
                self.toggle_root_lock(screen.selected_corner, screen.selected_lane, RootSide::Pole);
            }
            if ui
                .add_enabled_ui(!self.showing_original, |ui| {
                    lock_button(ui, "ZEROS", zero_locked)
                })
                .inner
                .clicked()
            {
                self.toggle_root_lock(screen.selected_corner, screen.selected_lane, RootSide::Zero);
            }
        });
        ui.add_space(6.0);
        ui.horizontal(|ui| {
            ui.label(RichText::new("STATE").size(10.0).color(MUTED));
            let label = if screen.selected_stage.identity {
                "INACTIVE"
            } else {
                "ACTIVE"
            };
            if ui
                .add_enabled(
                    !self.showing_original,
                    egui::SelectableLabel::new(!screen.selected_stage.identity, label),
                )
                .clicked()
            {
                self.preview(EditRequest::single(
                    screen.selected_corner,
                    screen.selected_lane,
                    EditField::Identity,
                    if screen.selected_stage.identity {
                        0.0
                    } else {
                        1.0
                    },
                ));
                self.apply_preview();
            }
        });
        ui.add_space(6.0);
        match &screen.selected_stage.pole {
            RootGeometry::Conjugate { hz, radius } => {
                self.number_control(
                    ui,
                    screen,
                    "POLE FREQUENCY",
                    *hz,
                    EditField::PoleHz,
                    1.0,
                    "Hz",
                    !pole_locked && !self.showing_original,
                );
                self.number_control(
                    ui,
                    screen,
                    "POLE RADIUS",
                    *radius,
                    EditField::PoleRadius,
                    0.0001,
                    "",
                    !pole_locked && !self.showing_original,
                );
            }
            RootGeometry::RealPair { root_a, root_b } => {
                self.number_control(
                    ui,
                    screen,
                    "POLE 1",
                    *root_a,
                    EditField::PoleRootA,
                    0.0001,
                    "",
                    !pole_locked && !self.showing_original,
                );
                self.number_control(
                    ui,
                    screen,
                    "POLE 2",
                    *root_b,
                    EditField::PoleRootB,
                    0.0001,
                    "",
                    !pole_locked && !self.showing_original,
                );
            }
            RootGeometry::Degenerate => {
                ui.label(RichText::new("POLE AT ORIGIN").size(10.0).color(MUTED));
            }
        }
        match &screen.selected_stage.zero {
            RootGeometry::Conjugate { hz, radius } => {
                self.number_control(
                    ui,
                    screen,
                    "ZERO FREQUENCY",
                    *hz,
                    EditField::ZeroHz,
                    1.0,
                    "Hz",
                    !zero_locked && !self.showing_original,
                );
                self.number_control(
                    ui,
                    screen,
                    "ZERO RADIUS",
                    *radius,
                    EditField::ZeroRadius,
                    0.0001,
                    "",
                    !zero_locked && !self.showing_original,
                );
            }
            RootGeometry::RealPair { root_a, root_b } => {
                self.number_control(
                    ui,
                    screen,
                    "ZERO 1",
                    *root_a,
                    EditField::ZeroRootA,
                    0.0001,
                    "",
                    !zero_locked && !self.showing_original,
                );
                self.number_control(
                    ui,
                    screen,
                    "ZERO 2",
                    *root_b,
                    EditField::ZeroRootB,
                    0.0001,
                    "",
                    !zero_locked && !self.showing_original,
                );
            }
            RootGeometry::Degenerate => {
                ui.label(RichText::new("ZERO AT ORIGIN").size(10.0).color(MUTED));
            }
        }
        self.number_control(
            ui,
            screen,
            "SCALE",
            screen.selected_stage.scale.value,
            EditField::Scale,
            0.0001,
            "b0",
            !self.showing_original,
        );
        ui.add_space(8.0);
        ui.horizontal(|ui| {
            if quiet_button(ui, "UNDO", !self.state.undo.is_empty()).clicked() {
                self.undo();
            }
            if quiet_button(ui, "REVERT PREVIEW", self.state.pending_edit.is_some()).clicked() {
                self.state.discard_preview();
                self.set_status("Preview discarded");
            }
        });
    }

    fn number_control(
        &mut self,
        ui: &mut egui::Ui,
        screen: &ScreenData,
        label: &str,
        current: f64,
        field: EditField,
        speed: f64,
        suffix: &str,
        enabled: bool,
    ) {
        ui.horizontal(|ui| {
            ui.label(RichText::new(label).size(10.0).color(MUTED));
            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                let mut value = current;
                let response = ui.add_enabled(
                    enabled,
                    egui::DragValue::new(&mut value)
                        .speed(speed)
                        .max_decimals(if speed >= 1.0 { 1 } else { 6 })
                        .suffix(if suffix.is_empty() {
                            "".to_owned()
                        } else {
                            format!(" {suffix}")
                        }),
                );
                if response.changed() {
                    self.preview(EditRequest::single(
                        screen.selected_corner,
                        screen.selected_lane,
                        field,
                        value,
                    ));
                }
                if response.drag_stopped() || response.lost_focus() {
                    self.apply_preview();
                }
            });
        });
    }

    fn status_bar(&mut self, ctx: &egui::Context) {
        egui::TopBottomPanel::bottom("status")
            .exact_height(28.0)
            .frame(
                egui::Frame::none()
                    .fill(PANEL)
                    .inner_margin(egui::Margin::symmetric(12.0, 5.0)),
            )
            .show(ctx, |ui| {
                ui.horizontal(|ui| {
                    ui.label(
                        RichText::new(&self.status)
                            .size(10.0)
                            .color(if self.status_error { ERROR } else { MUTED }),
                    );
                    ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                        ui.label(
                            RichText::new("39062.5 Hz · DF2T · 6 SECTIONS")
                                .size(9.0)
                                .color(MUTED),
                        );
                    });
                });
            });
    }
}

impl eframe::App for StudioApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        // Response, z-plane, packed words, and the readout follow the audio
        // within one processing block by reading the reported playhead/Q.
        if let Some(control) = self.audition.clone() {
            let (playhead, q) = {
                let control = control.lock().unwrap();
                (control.playhead, control.q)
            };
            let _ = self.state.set_morph_q(playhead, q);
            ctx.request_repaint_after(Duration::from_millis(16));
        }
        // Ctrl/Cmd + 1..4 → Set Current into that corner.
        let capture_corner = ctx.input(|input| {
            if !input.modifiers.command {
                return None;
            }
            [egui::Key::Num1, egui::Key::Num2, egui::Key::Num3, egui::Key::Num4]
                .into_iter()
                .position(|key| input.key_pressed(key))
        });
        if let Some(corner) = capture_corner {
            self.set_current(corner);
        }
        let screen = match self.screen() {
            Ok(screen) => screen,
            Err(error) => {
                self.set_error(error);
                return;
            }
        };
        self.top_bar(ctx, &screen);
        self.status_bar(ctx);
        self.library(ctx);
        self.main_view(ctx, &screen);
        if self.sink.as_ref().is_some_and(Sink::empty) {
            self.stop_audio();
        }
    }
}

fn panel_frame() -> egui::Frame {
    egui::Frame::none()
        .fill(PANEL)
        .inner_margin(egui::Margin::same(12.0))
        .stroke(Stroke::new(1.0, LINE))
}

fn section_heading(ui: &mut egui::Ui, title: &str, detail: &str) {
    ui.horizontal(|ui| {
        ui.label(RichText::new(title).size(11.0).strong().color(TEXT));
        ui.add_space(6.0);
        ui.label(RichText::new(detail).size(9.0).color(MUTED));
    });
}

fn separator(ui: &mut egui::Ui) {
    ui.add_space(3.0);
    let (rect, _) = ui.allocate_exact_size(Vec2::new(1.0, 24.0), Sense::hover());
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
        .rounding(Rounding::same(4.0))
        .min_size(Vec2::new(58.0, 30.0)),
    )
}

fn quiet_button(ui: &mut egui::Ui, label: &str, enabled: bool) -> Response {
    ui.add_enabled(
        enabled,
        egui::Button::new(RichText::new(label).size(10.0).color(TEXT))
            .fill(PANEL_RAISED)
            .stroke(Stroke::new(1.0, LINE))
            .rounding(Rounding::same(4.0))
            .min_size(Vec2::new(48.0, 28.0)),
    )
}

fn lock_button(ui: &mut egui::Ui, label: &str, locked: bool) -> Response {
    ui.add(
        egui::Button::new(
            RichText::new(format!(
                "{label} · {}",
                if locked { "LOCKED" } else { "EDITABLE" }
            ))
            .size(9.0)
            .color(if locked { MUTED } else { TEXT }),
        )
        .fill(if locked { PANEL_RAISED } else { ACCENT_SOFT })
        .stroke(Stroke::new(1.0, if locked { LINE } else { ACCENT }))
        .rounding(Rounding::same(4.0)),
    )
}

fn segmented(ui: &mut egui::Ui, label: &str, selected: bool, mut action: impl FnMut()) {
    let response = ui.add(
        egui::Button::new(RichText::new(label).size(10.0).color(if selected {
            TEXT
        } else {
            MUTED
        }))
        .selected(selected)
        .min_size(Vec2::new(66.0, 28.0)),
    );
    if response.clicked() {
        action();
    }
}

fn library_row(ui: &mut egui::Ui, name: &str, triage: Option<Triage>, selected: bool) -> Response {
    let height = 34.0;
    let (rect, response) =
        ui.allocate_exact_size(Vec2::new(ui.available_width(), height), Sense::click());
    if selected || response.hovered() {
        ui.painter().rect_filled(
            rect,
            Rounding::same(3.0),
            if selected {
                Color32::from_rgb(38, 57, 54)
            } else {
                PANEL_RAISED
            },
        );
    }
    ui.painter().text(
        Pos2::new(rect.left() + 8.0, rect.center().y),
        Align2::LEFT_CENTER,
        name,
        FontId::proportional(12.0),
        if selected {
            TEXT
        } else {
            Color32::from_rgb(197, 202, 209)
        },
    );
    if let Some(value) = triage {
        ui.painter().text(
            Pos2::new(rect.right() - 7.0, rect.center().y),
            Align2::RIGHT_CENTER,
            value.label(),
            FontId::proportional(9.0),
            MUTED,
        );
    }
    response
}

fn response_plot(ui: &mut egui::Ui, curve: &ResponseCurve, pole_hz: Option<f64>) -> Response {
    let desired = Vec2::new(
        ui.available_width(),
        (ui.available_height() - 48.0).max(170.0),
    );
    let (rect, response) = ui.allocate_exact_size(desired, Sense::hover());
    let plot = rect.shrink2(Vec2::new(48.0, 22.0));
    let painter = ui.painter_at(rect);
    painter.rect_filled(plot, Rounding::same(4.0), Color32::from_rgb(20, 23, 27));
    for db in [-48.0, -36.0, -24.0, -12.0, 0.0, 12.0, 24.0] {
        let y = map_db(plot, db);
        painter.line_segment(
            [Pos2::new(plot.left(), y), Pos2::new(plot.right(), y)],
            Stroke::new(if db == 0.0 { 1.0 } else { 0.5 }, LINE),
        );
        painter.text(
            Pos2::new(plot.left() - 8.0, y),
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
                Pos2::new(x, plot.bottom() + 7.0),
                Align2::CENTER_TOP,
                label,
                FontId::proportional(9.0),
                MUTED,
            );
        }
    }
    let points = curve
        .points
        .iter()
        .filter(|point| point.db.is_finite())
        .map(|point| Pos2::new(map_hz(plot, point.freq_hz), map_db(plot, point.db)))
        .collect::<Vec<_>>();
    if points.len() > 1 {
        painter.add(egui::Shape::line(points, Stroke::new(2.0, ACCENT)));
    }
    if let Some(hz) = pole_hz.filter(|hz| *hz >= 20.0 && *hz <= 16_000.0) {
        let x = map_hz(plot, hz);
        painter.line_segment(
            [Pos2::new(x, plot.top()), Pos2::new(x, plot.bottom())],
            Stroke::new(1.0, Color32::from_rgba_unmultiplied(70, 184, 151, 90)),
        );
        painter.circle_filled(Pos2::new(x, plot.top() + 10.0), 3.5, ACCENT);
    }
    response
}

fn map_hz(rect: Rect, hz: f64) -> f32 {
    let t = ((hz.clamp(20.0, 16_000.0).ln() - 20.0_f64.ln()) / (16_000.0_f64.ln() - 20.0_f64.ln()))
        as f32;
    egui::lerp(rect.x_range(), t)
}

fn map_db(rect: Rect, db: f64) -> f32 {
    let t = ((db.clamp(DB_MIN, DB_MAX) - DB_MIN) / (DB_MAX - DB_MIN)) as f32;
    egui::lerp(rect.y_range(), 1.0 - t)
}

fn pole_frequency(stage: &StageSnapshot) -> Option<f64> {
    match stage.pole {
        RootGeometry::Conjugate { hz, .. } => Some(hz),
        _ => None,
    }
}

fn root_positions(center: Pos2, radius: f32, root: &RootGeometry) -> Vec<(Pos2, bool)> {
    match root {
        RootGeometry::Conjugate { hz, radius: r } => {
            let angle = std::f64::consts::TAU * *hz / STAGE_SR;
            let x = angle.cos() as f32 * *r as f32;
            let y = angle.sin() as f32 * *r as f32;
            vec![
                (
                    Pos2::new(center.x + x * radius, center.y - y * radius),
                    true,
                ),
                (
                    Pos2::new(center.x + x * radius, center.y + y * radius),
                    false,
                ),
            ]
        }
        RootGeometry::RealPair { root_a, root_b } => vec![
            (
                Pos2::new(center.x + *root_a as f32 * radius, center.y),
                true,
            ),
            (
                Pos2::new(center.x + *root_b as f32 * radius, center.y),
                false,
            ),
        ],
        RootGeometry::Degenerate => vec![(center, true)],
    }
}

fn draw_root_pair(
    painter: &egui::Painter,
    center: Pos2,
    radius: f32,
    root: &RootGeometry,
    side: RootSide,
) {
    for (position, _) in root_positions(center, radius, root) {
        match side {
            RootSide::Pole => {
                painter.circle_filled(position, 5.5, ACCENT);
                painter.circle_stroke(position, 8.5, Stroke::new(1.0, ACCENT_SOFT));
            }
            RootSide::Zero => {
                painter.circle_filled(position, 5.5, PANEL_RAISED);
                painter.circle_stroke(position, 5.5, Stroke::new(2.0, TEXT));
            }
        }
    }
}

fn nearest_root_handle(
    pointer: Pos2,
    center: Pos2,
    radius: f32,
    stage: &StageSnapshot,
) -> Option<RootHandle> {
    let mut candidates = Vec::new();
    for (side, root) in [(RootSide::Pole, &stage.pole), (RootSide::Zero, &stage.zero)] {
        match root {
            RootGeometry::Conjugate { .. } => {
                if let Some((position, _)) = root_positions(center, radius, root).first() {
                    candidates.push((position.distance(pointer), RootHandle::Conjugate(side)));
                }
            }
            RootGeometry::RealPair { .. } => {
                for (position, first) in root_positions(center, radius, root) {
                    candidates.push((position.distance(pointer), RootHandle::Real(side, first)));
                }
            }
            RootGeometry::Degenerate => {}
        }
    }
    candidates
        .into_iter()
        .filter(|(distance, _)| *distance <= 18.0)
        .min_by(|left, right| left.0.total_cmp(&right.0))
        .map(|(_, handle)| handle)
}

fn root_handle_side(handle: RootHandle) -> RootSide {
    match handle {
        RootHandle::Conjugate(side) | RootHandle::Real(side, _) => side,
    }
}

fn inspect_data(ui: &mut egui::Ui, stage: &StageSnapshot) {
    ui.horizontal_wrapped(|ui| {
        ui.label(RichText::new("PACKED WORDS").size(9.0).color(MUTED));
        for (index, word) in stage.packed_words.iter().enumerate() {
            ui.monospace(format!("W{index} {word:04X}"));
        }
    });
    ui.horizontal_wrapped(|ui| {
        ui.label(RichText::new("DECODED DF2T").size(9.0).color(MUTED));
        for (index, value) in stage.runtime_coefficients.iter().enumerate() {
            ui.monospace(format!("C{index} {value:+.7}"));
        }
    });
}

fn body_name(path: &Path) -> String {
    path.file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("Untitled")
        .replace('_', " ")
}

fn format_transport_time(frames: u64) -> String {
    let seconds = frames as f64 / STAGE_SR;
    let minutes = (seconds / 60.0).floor() as u64;
    let remainder = seconds - (minutes as f64) * 60.0;
    format!("{minutes:02}:{remainder:06.3}")
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

/// One retained engine, prepared and loaded for cascade-only (BODY SOLO) or the
/// full retained path (PRODUCT). Mirrors the audio setup the offline sweep used.
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

/// Decode a WAV once, downmix to mono, resample to the engine rate. The audition
/// loops this material, so a generous cap is enough.
fn decode_wav_to_stage_sr(path: &Path) -> Result<Vec<f32>, String> {
    let file = File::open(path).map_err(|error| format!("WAV could not be opened: {error}"))?;
    let decoder = Decoder::new(BufReader::new(file))
        .map_err(|error| format!("WAV could not be decoded: {error}"))?;
    let source_rate = decoder.sample_rate();
    let channels = decoder.channels() as usize;
    // ponytail: cap decode at 60 s; the audition loops, so longer sources buy
    // nothing but RAM. Raise it if a real use-case needs a longer one-shot.
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

fn configure_ui(ctx: &egui::Context) {
    let mut visuals = egui::Visuals::dark();
    visuals.panel_fill = PANEL;
    visuals.window_fill = PANEL;
    visuals.extreme_bg_color = Color32::from_rgb(15, 17, 20);
    visuals.faint_bg_color = PANEL_RAISED;
    visuals.widgets.inactive.bg_fill = PANEL_RAISED;
    visuals.widgets.inactive.weak_bg_fill = PANEL_RAISED;
    visuals.widgets.inactive.bg_stroke = Stroke::new(1.0, LINE);
    visuals.widgets.hovered.bg_fill = Color32::from_rgb(38, 43, 49);
    visuals.widgets.hovered.bg_stroke = Stroke::new(1.0, Color32::from_rgb(79, 87, 97));
    visuals.widgets.active.bg_fill = ACCENT_SOFT;
    visuals.widgets.active.bg_stroke = Stroke::new(1.0, ACCENT);
    visuals.selection.bg_fill = ACCENT_SOFT;
    visuals.selection.stroke = Stroke::new(1.0, ACCENT);
    visuals.override_text_color = Some(TEXT);
    visuals.window_rounding = Rounding::same(6.0);
    ctx.set_visuals(visuals);
    let mut style = (*ctx.style()).clone();
    style.spacing.item_spacing = Vec2::new(7.0, 6.0);
    style.spacing.button_padding = Vec2::new(10.0, 6.0);
    style.spacing.interact_size.y = 28.0;
    ctx.set_style(style);
}

fn main() -> eframe::Result<()> {
    let repo_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("workstation manifest must be inside the repository")
        .to_path_buf();
    let app = StudioApp::new(repo_root).unwrap_or_else(|error| panic!("{error}"));
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("Filter Workstation")
            .with_inner_size([1440.0, 920.0])
            .with_min_inner_size([1050.0, 700.0]),
        ..Default::default()
    };
    eframe::run_native(
        "Filter Workstation",
        options,
        Box::new(|creation| {
            configure_ui(&creation.egui_ctx);
            Ok(Box::new(app))
        }),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn probe_wav(len: usize) -> Vec<f32> {
        // Deterministic, non-silent material at the engine rate.
        (0..len).map(|i| (i as f32 * 0.031).sin() * 0.25).collect()
    }

    fn loaded_body() -> [u8; 240] {
        let repo_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .to_path_buf();
        StudioApp::new(repo_root)
            .unwrap()
            .original_session
            .to_body_bytes()
            .unwrap()
    }

    #[test]
    fn audition_stream_sweeps_then_latches_held_and_stays_finite() {
        let body = loaded_body();
        let wav = Arc::new(probe_wav(4096));
        let control = Arc::new(Mutex::new(AuditionControl {
            q: 0.5,
            morph: 0.0,
            transport: Transport::Sweeping,
            sweep_len_frames: (AUDITION_BLOCK as u64) * 8, // short sweep, latches fast
            reload: None,
            playhead: 0.0,
            time_frames: 0,
            held_at_end: false,
        }));
        let mut stream = AuditionStream {
            engine: build_audition_engine(&body, AudioMode::BodySolo).unwrap(),
            wav,
            wav_cursor: 0,
            sweep_pos: 0,
            last_transport: Transport::Sweeping,
            control: control.clone(),
            buf: Vec::new(),
            right: Vec::new(),
            pos: 0,
        };
        let out: Vec<f32> = (0..AUDITION_BLOCK * 12).map(|_| stream.next().unwrap()).collect();
        assert!(out.iter().all(|sample| sample.is_finite()));
        let control = control.lock().unwrap();
        assert!(control.held_at_end, "sweep must latch HELD at the end");
        assert!((control.playhead - 1.0).abs() < 1e-9, "playhead must reach 1.0");
        assert_eq!(control.transport, Transport::Held);
    }

    #[test]
    fn held_block_equals_direct_process_block() {
        let body = loaded_body();
        let wav = Arc::new(probe_wav(AUDITION_BLOCK * 4));
        let (morph, q) = (0.372, 0.64);
        let control = Arc::new(Mutex::new(AuditionControl {
            q,
            morph,
            transport: Transport::Held,
            sweep_len_frames: wav.len() as u64,
            reload: None,
            playhead: 0.0,
            time_frames: 0,
            held_at_end: false,
        }));
        let mut stream = AuditionStream {
            engine: build_audition_engine(&body, AudioMode::BodySolo).unwrap(),
            wav: wav.clone(),
            wav_cursor: 0,
            sweep_pos: 0,
            last_transport: Transport::Held,
            control,
            buf: Vec::new(),
            right: Vec::new(),
            pos: 0,
        };
        let streamed: Vec<f32> = (0..AUDITION_BLOCK).map(|_| stream.next().unwrap()).collect();

        // Same fresh engine, same input block, fixed (morph, q): must match.
        let mut left = wav[..AUDITION_BLOCK].to_vec();
        let mut right = left.clone();
        let mut direct = build_audition_engine(&body, AudioMode::BodySolo).unwrap();
        direct.process_block(&mut left, &mut right, morph, q);
        for (streamed, direct) in streamed.iter().zip(left.iter()) {
            assert!(
                (streamed - direct).abs() < 1e-6,
                "HELD stream must equal a direct process_block: {streamed} vs {direct}"
            );
        }
    }

    #[test]
    fn changing_control_q_mid_stream_changes_the_audio() {
        // The marquee feature: Q is read live every block, not cached at start.
        let body = loaded_body();
        let held = |flip_q: bool| -> Vec<f32> {
            let wav = Arc::new(probe_wav(AUDITION_BLOCK * 4));
            let control = Arc::new(Mutex::new(AuditionControl {
                q: 0.2,
                morph: 0.5,
                transport: Transport::Held,
                sweep_len_frames: wav.len() as u64,
                reload: None,
                playhead: 0.0,
                time_frames: 0,
                held_at_end: false,
            }));
            let mut stream = AuditionStream {
                engine: build_audition_engine(&body, AudioMode::BodySolo).unwrap(),
                wav,
                wav_cursor: 0,
                sweep_pos: 0,
                last_transport: Transport::Held,
                control: control.clone(),
                buf: Vec::new(),
                right: Vec::new(),
                pos: 0,
            };
            let mut out = Vec::new();
            for _ in 0..AUDITION_BLOCK * 100 {
                out.push(stream.next().unwrap());
            }
            if flip_q {
                control.lock().unwrap().q = 0.9; // change Q mid-stream
            }
            for _ in 0..AUDITION_BLOCK * 100 {
                out.push(stream.next().unwrap());
            }
            out
        };
        let steady = held(false);
        let flipped = held(true);
        let tail_delta: f32 = steady
            .iter()
            .zip(flipped.iter())
            .skip(AUDITION_BLOCK * 100)
            .map(|(a, b)| (a - b).abs())
            .sum();
        assert!(
            tail_delta > 1e-3,
            "changing control.q mid-stream must change the audio (delta {tail_delta})"
        );
    }
}
