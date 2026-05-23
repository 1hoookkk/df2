#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]

#[allow(dead_code)]
mod audio;
mod capture;
mod dsp;
mod inspect;
#[allow(dead_code)]
mod preprocess;
mod surface;
mod theme;

use std::path::PathBuf;
use std::time::Instant;

use eframe::egui;
use trench_core::cartridge::CornerData;

use dsp::{
    body_midpoint, condition_fit_window, corner_to_biquads, cpp_df2t_output, detect_onset,
    display_name, hedz_rom_midpoint, load_wav_as_mono_f64, magnitude_response, samples_for_ms,
    source_envelope, spectral_residual_db, two_anchor_preview, z_plane_points, ComplexPoint,
    FitDiagnostics, FitQuality, AUTHORING_RATE, DEFAULT_WINDOW_MS, FIT_BLOCK_DB, FIT_WARN_DB,
    PASSTHROUGH, POLE_ZERO_COUNT,
};

// ── State ─────────────────────────────────────────────────────────────────────

#[derive(Clone)]
pub struct ExtractionResults {
    pub corner: CornerData,
    pub poles: [ComplexPoint; POLE_ZERO_COUNT],
    pub zeros: [ComplexPoint; POLE_ZERO_COUNT],
    pub magnitude_response: Vec<[f64; 2]>,
    /// The source sound's own spectral envelope `[freq, dB]` — overlaid behind
    /// the fit so the parse quality is visible.
    pub source_db: Vec<[f64; 2]>,
    pub target_db: Vec<[f64; 2]>,
    pub cpp_df2t_output: String,
    pub residual_db: f64,
    pub quality: FitQuality,
    pub diagnostics: FitDiagnostics,
}

impl ExtractionResults {
    fn empty(sample_rate: f64) -> Self {
        let corner = [PASSTHROUGH; POLE_ZERO_COUNT];
        Self {
            corner,
            poles: [ComplexPoint::default(); POLE_ZERO_COUNT],
            zeros: [ComplexPoint::default(); POLE_ZERO_COUNT],
            magnitude_response: magnitude_response(&corner, sample_rate),
            source_db: Vec::new(),
            target_db: Vec::new(),
            cpp_df2t_output: cpp_df2t_output(&corner),
            residual_db: f64::NAN,
            quality: FitQuality::Blocked,
            diagnostics: FitDiagnostics::default(),
        }
    }
}

#[derive(Clone)]
pub struct AssignedCorner {
    pub source: String,
    pub corner: CornerData,
    pub residual_db: f64,
    pub quality: FitQuality,
}

pub struct AnchorAudio {
    pub buffer: Vec<f64>,
    pub path: PathBuf,
    pub sample_rate: f64,
    pub start_trim: usize,
    pub window_len: usize,
    pub extraction: ExtractionResults,
}

pub struct App {
    pub anchor_audio: [Option<AnchorAudio>; 2],
    pub internal_resample_rate: f32,
    pub zero_dither_truncation: bool,
    pub corner_slots: [Option<AssignedCorner>; 4],
    pub anchor_morph: f32,
    pub audio: Option<audio::Audio>,
    pub audio_level: f32,
    pub inspect_open: bool,
    pub inspect_anchor: usize,
    pub save_status: Option<String>,
    pub status: String,
    pub capture: Option<capture::Capture>,
    pub capture_anchor: usize,
    pub start: Instant,
    /// Render cache: the fit response is recomputed only when the staged corner
    /// actually changes (morph drag, new fit), not every breathing frame.
    pub view_corner: Option<CornerData>,
    pub view_fit: Vec<[f64; 2]>,
    /// The Talking Hedz calibration truth at M50/Q50, decoded once from the
    /// verbatim 240-byte ROM block. The inspect midpoint scope draws the authored
    /// body's middle against it. None if the reference block isn't in this checkout.
    pub hedz_ref_midpoint: Option<CornerData>,
}

impl Default for App {
    fn default() -> Self {
        Self {
            anchor_audio: [None, None],
            internal_resample_rate: AUTHORING_RATE as f32,
            zero_dither_truncation: false,
            corner_slots: core::array::from_fn(|_| None),
            anchor_morph: 0.5,
            audio: audio::start(),
            audio_level: 0.4,
            inspect_open: false,
            inspect_anchor: 0,
            save_status: None,
            status: String::new(),
            capture: None,
            capture_anchor: 0,
            start: Instant::now(),
            view_corner: None,
            view_fit: Vec::new(),
            hedz_ref_midpoint: hedz_rom_midpoint(),
        }
    }
}

// ── Business logic ──────────────────────────────────────────────────────────

impl App {
    pub fn elapsed(&self) -> f32 {
        self.start.elapsed().as_secs_f32()
    }

    /// The corner the mouth + audition reflect right now: the live morph if both
    /// ends are set, else whichever single end (assigned or just loaded) exists.
    pub fn stage_corner(&self) -> Option<CornerData> {
        if let Some(p) = self.anchor_preview_corner() {
            return Some(p);
        }
        if let Some(s) = self.corner_slots[0]
            .as_ref()
            .or(self.corner_slots[1].as_ref())
        {
            return Some(s.corner);
        }
        self.anchor_audio[0]
            .as_ref()
            .or(self.anchor_audio[1].as_ref())
            .map(|a| a.extraction.corner)
    }

    pub fn load_anchor_button(&mut self, anchor: usize) {
        if let Some(path) = rfd::FileDialog::new()
            .add_filter("Wave Audio", &["wav"])
            .pick_file()
        {
            self.load_anchor_path(anchor, path);
        }
    }

    fn load_anchor_path(&mut self, anchor: usize, path: PathBuf) {
        match load_wav_as_mono_f64(&path) {
            Ok((samples, sample_rate)) => {
                let onset = detect_onset(&samples, sample_rate);
                let window_len = samples_for_ms(sample_rate, DEFAULT_WINDOW_MS);
                let start_trim = onset.min(samples.len().saturating_sub(window_len));
                self.anchor_audio[anchor] = Some(AnchorAudio {
                    buffer: samples,
                    path,
                    sample_rate,
                    start_trim,
                    window_len,
                    extraction: ExtractionResults::empty(self.internal_resample_rate as f64),
                });
                self.refit_anchor(anchor);
                self.auto_assign(anchor);
            }
            Err(err) => self.status = format!("load failed: {err}"),
        }
    }

    /// Collapse the old explicit ASSIGN step for Ready fits only. Review and
    /// Blocked parses stay visible for inspection but do not silently assign.
    fn auto_assign(&mut self, anchor: usize) {
        let ok = self.anchor_audio[anchor]
            .as_ref()
            .map(|s| s.extraction.quality.can_assign())
            .unwrap_or(false);
        if ok {
            self.assign_to_slot(anchor, anchor);
        }
    }

    pub fn start_capture(&mut self, anchor: usize) {
        self.capture = None;
        match capture::Capture::start() {
            Ok(cap) => {
                self.capture = Some(cap);
                self.capture_anchor = anchor;
            }
            Err(err) => self.status = format!("capture failed: {err}"),
        }
    }

    pub fn finish_capture(&mut self) {
        let Some(cap) = self.capture.take() else {
            return;
        };
        let anchor = self.capture_anchor;
        let samples = cap.drain_mono_f64();
        let sample_rate = cap.sample_rate;
        drop(cap);

        if samples.len() < 64 {
            self.status = "capture produced no audio — is something playing?".to_owned();
            return;
        }
        let path = std::env::temp_dir().join(format!("trench_capture_{anchor}.wav"));
        let onset = detect_onset(&samples, sample_rate);
        let window_len = samples_for_ms(sample_rate, DEFAULT_WINDOW_MS);
        let start_trim = onset.min(samples.len().saturating_sub(window_len));
        self.anchor_audio[anchor] = Some(AnchorAudio {
            buffer: samples,
            path,
            sample_rate,
            start_trim,
            window_len,
            extraction: ExtractionResults::empty(self.internal_resample_rate as f64),
        });
        self.refit_anchor(anchor);
        self.auto_assign(anchor);
    }

    pub fn is_capturing(&self, anchor: usize) -> bool {
        self.capture.is_some() && self.capture_anchor == anchor
    }

    pub fn refit_anchor(&mut self, anchor: usize) {
        let rate = self.internal_resample_rate as f64;
        let dither = self.zero_dither_truncation;
        let Some(state) = self.anchor_audio[anchor].as_mut() else {
            return;
        };

        let start = state.start_trim.min(state.buffer.len());
        let end = (state.start_trim + state.window_len).min(state.buffer.len());
        let raw = &state.buffer[start..end];
        if raw.len() < 16 {
            state.extraction = ExtractionResults::empty(rate);
            return;
        }

        let fit_window = condition_fit_window(raw, dither);
        // Restored to the 2026-05-22 Talking-Hedz-matching fitter. The ARMA path
        // (fit_corner_arma_from_window) regressed the match; lpc::fit_corner is
        // the working one — Levinson LPC + Durand-Kerner roots + spectral-valley
        // zeros. The residual badge below is cosmetic; the corner is the fit.
        let corner = trench_core::lpc::fit_corner(&fit_window, state.sample_rate, rate);
        let residual = spectral_residual_db(&fit_window, state.sample_rate, &corner, rate);
        let quality = if !residual.is_finite()
            || residual > FIT_BLOCK_DB
            || corner.iter().flatten().any(|c| !c.is_finite())
        {
            FitQuality::Blocked
        } else if residual > FIT_WARN_DB {
            FitQuality::Review
        } else {
            FitQuality::Ready
        };
        let (poles, zeros) = z_plane_points(&corner);

        state.extraction = ExtractionResults {
            corner,
            poles,
            zeros,
            magnitude_response: magnitude_response(&corner, rate),
            source_db: source_envelope(&fit_window, state.sample_rate),
            target_db: Vec::new(),
            cpp_df2t_output: cpp_df2t_output(&corner),
            residual_db: residual,
            quality,
            diagnostics: FitDiagnostics::default(),
        };
    }

    pub fn assign_to_slot(&mut self, anchor: usize, slot: usize) {
        let Some(state) = self.anchor_audio[anchor].as_ref() else {
            return;
        };
        if !state.extraction.quality.can_assign() {
            return;
        }
        self.corner_slots[slot] = Some(AssignedCorner {
            source: display_name(&state.path),
            corner: state.extraction.corner,
            residual_db: state.extraction.residual_db,
            quality: state.extraction.quality,
        });
        self.save_status = None;
    }

    pub fn anchor_preview_corner(&self) -> Option<CornerData> {
        let low = self.corner_slots[0].as_ref()?.corner;
        let high = self.corner_slots[1].as_ref()?.corner;
        Some(two_anchor_preview(&low, &high, self.anchor_morph))
    }

    /// The authored body's M50/Q50 midpoint — the candidate the calibration scope
    /// judges. Built from the four assigned corners through the real packed-u16
    /// interpolation; slots 2/3 fall back to LOW/HIGH exactly like the exporter,
    /// so a two-end body still resolves a midpoint.
    pub fn candidate_midpoint(&self) -> Option<CornerData> {
        let low = self.corner_slots[0].as_ref()?.corner;
        let high = self.corner_slots[1].as_ref()?.corner;
        let c = self.corner_slots[2].as_ref().map(|s| s.corner).unwrap_or(low);
        let d = self.corner_slots[3].as_ref().map(|s| s.corner).unwrap_or(high);
        Some(body_midpoint(&[low, high, c, d]))
    }

    fn active_audio_corner(&self) -> CornerData {
        self.stage_corner()
            .unwrap_or_else(|| ExtractionResults::empty(AUTHORING_RATE).corner)
    }

    fn set_audio_target(&self) {
        if let Some(audio) = &self.audio {
            audio.set_target(corner_to_biquads(&self.active_audio_corner()));
            audio.set_level(self.audio_level);
        }
    }

    fn take_dropped_files(&mut self, ctx: &egui::Context) {
        let dropped = ctx.input(|i| i.raw.dropped_files.clone());
        for file in dropped {
            if let Some(path) = file.path {
                let target = if self.corner_slots[0].is_none() { 0 } else { 1 };
                self.load_anchor_path(target, path);
                break;
            }
        }
    }

    pub fn reset_body(&mut self) {
        self.anchor_audio = [None, None];
        self.corner_slots = core::array::from_fn(|_| None);
        self.anchor_morph = 0.5;
        self.save_status = None;
        if let Some(audio) = &self.audio {
            audio.set_playing(false);
        }
    }

    pub fn save_body(&mut self) {
        let Some(json) = self.export_two_anchor_body() else {
            self.save_status = Some("load both ends before saving".to_owned());
            return;
        };
        let home = std::env::var("USERPROFILE")
            .or_else(|_| std::env::var("HOME"))
            .unwrap_or_default();
        let slot = PathBuf::from(home)
            .join("Documents")
            .join("TRENCH")
            .join("authoring_slot.json");
        if let Some(parent) = slot.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        match std::fs::write(&slot, json) {
            Ok(_) => self.save_status = Some("saved to authoring slot".to_owned()),
            Err(err) => self.save_status = Some(format!("save failed: {err}")),
        }
    }

    fn export_two_anchor_body(&self) -> Option<String> {
        let low = self.corner_slots[0].as_ref()?;
        let high = self.corner_slots[1].as_ref()?;
        let corners = [
            low.corner,
            high.corner,
            self.corner_slots[2]
                .as_ref()
                .map(|s| s.corner)
                .unwrap_or(low.corner),
            self.corner_slots[3]
                .as_ref()
                .map(|s| s.corner)
                .unwrap_or(high.corner),
        ];
        let labels = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];
        let mut keyframes = Vec::new();
        for (label, corner) in labels.iter().zip(corners) {
            let mut stages = Vec::new();
            for stage in corner {
                stages.push(serde_json::json!({
                    "c0": stage[0], "c1": stage[1], "c2": stage[2],
                    "c3": stage[3], "c4": stage[4]
                }));
            }
            for _ in POLE_ZERO_COUNT..12 {
                stages.push(serde_json::json!({
                    "c0": 2.0, "c1": 1.0, "c2": 2.0, "c3": 1.0, "c4": 1.0
                }));
            }
            keyframes.push(serde_json::json!({"label": label, "boost": 1.0, "stages": stages}));
        }
        Some(
            serde_json::json!({
                "format": "compiled-v1",
                "name": format!("{} — {}", low.source, high.source),
                "sampleRate": AUTHORING_RATE,
                "stages": 12,
                "keyframes": keyframes
            })
            .to_string(),
        )
    }
}

// ── eframe glue ─────────────────────────────────────────────────────────────

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        let capture_done = self
            .capture
            .as_ref()
            .map(|c| c.elapsed_secs() >= capture::CAPTURE_SECS)
            .unwrap_or(false);
        if capture_done {
            self.finish_capture();
        }

        self.take_dropped_files(ctx);
        self.set_audio_target();
        self.show_product_surface(ctx);
        if self.inspect_open {
            self.show_inspect_window(ctx);
        }

        // The mouth breathes; keep a steady ~60fps so it stays alive.
        ctx.request_repaint_after(std::time::Duration::from_millis(16));
    }
}

fn main() -> eframe::Result<()> {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1_040.0, 860.0])
            .with_min_inner_size([860.0, 680.0])
            .with_title("Filter Factory")
            .with_drag_and_drop(true),
        ..Default::default()
    };
    eframe::run_native(
        "Filter Factory",
        options,
        Box::new(|cc| {
            theme::install(&cc.egui_ctx);
            let mut app = App::default();
            // Optional: TRENCH_FORGE_DEMO="low.wav;high.wav" preloads two ends
            // (used for screenshots / visual checks; off by default).
            if let Ok(demo) = std::env::var("TRENCH_FORGE_DEMO") {
                let mut it = demo.split(';');
                if let (Some(a), Some(b)) = (it.next(), it.next()) {
                    app.load_anchor_path(0, PathBuf::from(a));
                    app.load_anchor_path(1, PathBuf::from(b));
                }
            }
            Ok(Box::new(app))
        }),
    )
}
