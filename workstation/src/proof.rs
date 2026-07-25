use crate::hash::sha256_hex;
use crate::model::{
    declared_fixture, probe_body, render_audio, AudioMode, ChangedWord, EditField, EditRequest,
    EvidenceReference, SampledAudit, ScreenData, Session, WorkstationError, CORNER_LABELS,
};
use crate::recipe_index::{
    apply_candidate, RecipeApplication, RecipeIndex, RecipeIndexValidation,
};
use serde::Serialize;
use std::fs;
use std::path::{Path, PathBuf};
use trench_core::cascade::{NUM_COEFFS, NUM_STAGES};
use trench_core::response::biquad_cascade_mag_db;
use trench_core::stage_law::STAGE_SR;

pub const PROOF_FORMAT: &str = "trench-workstation-proof-slice-v1";
pub const PROOF_DIRECTORY: &str = "workstation-proof-slice-v1";

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ProofGates {
    pub source_body_is_240_bytes: bool,
    pub no_op_session_reopen_is_byte_identical: bool,
    pub edited_session_reopen_is_byte_identical: bool,
    pub body_and_cartridge_are_byte_identical: bool,
    pub declared_selection_only: bool,
    pub declared_packed_word_scope_only: bool,
    pub identity_lanes_decode_exactly: bool,
    pub real_root_row_round_trips_exactly: bool,
    pub real_root_conjugate_edit_is_refused: bool,
    pub displayed_coefficients_equal_packed_probe: bool,
    pub plot_uses_packed_probe_coefficients: bool,
    pub plot_uses_one_shared_db_scale: bool,
    pub raw_audio_is_not_normalized: bool,
    pub raw_audio_fits_pcm16_without_clipping: bool,
    pub body_solo_is_finite: bool,
    pub product_is_finite: bool,
    pub sampled_audit_has_zero_unstable_rows: bool,
    pub sampled_audit_has_zero_nonfinite_rows: bool,
}

impl ProofGates {
    fn all_pass(&self) -> bool {
        self.source_body_is_240_bytes
            && self.no_op_session_reopen_is_byte_identical
            && self.edited_session_reopen_is_byte_identical
            && self.body_and_cartridge_are_byte_identical
            && self.declared_selection_only
            && self.declared_packed_word_scope_only
            && self.identity_lanes_decode_exactly
            && self.real_root_row_round_trips_exactly
            && self.real_root_conjugate_edit_is_refused
            && self.displayed_coefficients_equal_packed_probe
            && self.plot_uses_packed_probe_coefficients
            && self.plot_uses_one_shared_db_scale
            && self.raw_audio_is_not_normalized
            && self.raw_audio_fits_pcm16_without_clipping
            && self.body_solo_is_finite
            && self.product_is_finite
            && self.sampled_audit_has_zero_unstable_rows
            && self.sampled_audit_has_zero_nonfinite_rows
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct PlotScale {
    pub minimum_db: f64,
    pub maximum_db: f64,
    pub shared_by_corner_labels: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct AudioSummary {
    pub mode: String,
    pub sample_rate_hz: u32,
    pub input_peak: f32,
    pub output_peak: f32,
    pub output_rms: f32,
    pub normalized: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ProofReport {
    pub format: String,
    pub verdict: String,
    pub contract: String,
    pub source_fixture: String,
    pub source_fixture_path: String,
    pub source_body_sha256: String,
    pub edited_body_sha256: String,
    pub edit: EditRequest,
    pub changed_words: Vec<ChangedWord>,
    pub plot_scale: PlotScale,
    pub body_solo: AudioSummary,
    pub product: AudioSummary,
    pub sampled_audit: SampledAudit,
    pub gates: ProofGates,
    pub limitations: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ArtifactRecord {
    pub path: String,
    pub bytes: usize,
    pub sha256: String,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ProofManifest {
    pub format: String,
    pub proof_report: String,
    pub artifacts: Vec<ArtifactRecord>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ProofReceipt {
    pub directory: String,
    pub manifest_sha256: String,
    pub reused_identical_bundle: bool,
    pub report: ProofReport,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct RecipeProofGates {
    pub index_loaded_and_validated_outside_ui: bool,
    pub scaffold_is_240_bytes: bool,
    pub no_op_scaffold_reopen_is_byte_identical: bool,
    pub edited_session_reopen_is_byte_identical: bool,
    pub anchor_zero_words_opened: bool,
    pub declared_zero_word_scope_only: bool,
    pub body_and_cartridge_are_byte_identical: bool,
    pub plot_uses_packed_probe_coefficients: bool,
    pub plot_uses_one_shared_db_scale: bool,
    pub raw_audio_is_not_normalized: bool,
    pub raw_audio_fits_pcm16_without_clipping: bool,
    pub body_solo_is_finite: bool,
    pub product_is_finite: bool,
    pub sampled_audit_has_zero_unstable_rows: bool,
    pub sampled_audit_has_zero_nonfinite_rows: bool,
}

impl RecipeProofGates {
    fn all_pass(&self) -> bool {
        self.index_loaded_and_validated_outside_ui
            && self.scaffold_is_240_bytes
            && self.no_op_scaffold_reopen_is_byte_identical
            && self.edited_session_reopen_is_byte_identical
            && self.anchor_zero_words_opened
            && self.declared_zero_word_scope_only
            && self.body_and_cartridge_are_byte_identical
            && self.plot_uses_packed_probe_coefficients
            && self.plot_uses_one_shared_db_scale
            && self.raw_audio_is_not_normalized
            && self.raw_audio_fits_pcm16_without_clipping
            && self.body_solo_is_finite
            && self.product_is_finite
            && self.sampled_audit_has_zero_unstable_rows
            && self.sampled_audit_has_zero_nonfinite_rows
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct RecipeProofReport {
    pub format: String,
    pub verdict: String,
    pub contract: String,
    pub index_validation: RecipeIndexValidation,
    pub application: RecipeApplication,
    pub plot_scale: PlotScale,
    pub body_solo: AudioSummary,
    pub product: AudioSummary,
    pub gates: RecipeProofGates,
    pub limitations: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct RecipeProofReceipt {
    pub directory: String,
    pub manifest_sha256: String,
    pub reused_identical_bundle: bool,
    pub report: RecipeProofReport,
}

pub fn run_recipe_proof(
    repo_root: impl AsRef<Path>,
    output_directory: impl AsRef<Path>,
    scaffold_name: &str,
    candidate_id: &str,
) -> Result<RecipeProofReceipt, WorkstationError> {
    let repo_root = repo_root.as_ref();
    let output_directory = output_directory.as_ref();
    let (source_entry, source_bytes) = declared_fixture(repo_root, scaffold_name)?;
    let source_session = Session::from_body_bytes(
        format!("{} Recipe Scaffold", source_entry.name),
        "Clean-room four-pose scaffold; recipe movement is applied to zero words only.",
        &source_bytes,
        synthetic_evidence(&source_entry.path, &source_bytes),
    )?;
    let source_json = source_session.to_json()?;
    let no_op_identical = Session::from_json(&source_json)?.to_body_bytes()?.as_slice()
        == source_bytes.as_slice();

    let index_path = repo_root
        .join("recipe-index")
        .join("recipe_index_v1.json");
    let (index, index_bytes) = RecipeIndex::load(repo_root)?;
    let catalog = index.catalog(&index_path, &index_bytes, &source_session)?;
    let candidate = catalog
        .candidates
        .iter()
        .find(|candidate| candidate.candidate_id == candidate_id)
        .or_else(|| catalog.candidates.first())
        .ok_or_else(|| {
            WorkstationError(format!(
                "recipe candidate '{candidate_id}' is not eligible for scaffold '{scaffold_name}', and no eligible replacement exists"
            ))
        })?;
    let application = apply_candidate(scaffold_name, &source_session, candidate)?;
    let edited_session = application.after_session.clone();
    let edited_body = edited_session.to_body_bytes()?;
    let edited_json = edited_session.to_json()?;
    let edited_reopen_identical = Session::from_json(&edited_json)?.to_body_bytes()? == edited_body;
    let screen = edited_session.screen(0, candidate.scaffold_lane_index, 0.5, 0.5)?;
    let plot_uses_probe = screen_uses_probe_rows(&screen, &edited_body)?;
    let (svg, plot_scale) = response_svg(&screen)?;
    let plot_shared = plot_scale.shared_by_corner_labels == CORNER_LABELS.map(str::to_owned);
    let body_solo = render_audio(&edited_session, AudioMode::BodySolo)?;
    let product = render_audio(&edited_session, AudioMode::Product)?;
    let zero_unstable = application
        .sampled_audit_after
        .unstable_mask
        .iter()
        .all(|failed| !failed);
    let zero_nonfinite = application
        .sampled_audit_after
        .nonfinite_mask
        .iter()
        .all(|failed| !failed);
    let gates = RecipeProofGates {
        index_loaded_and_validated_outside_ui: catalog.validation.accepted_lane_count > 0,
        scaffold_is_240_bytes: source_bytes.len() == 240,
        no_op_scaffold_reopen_is_byte_identical: no_op_identical,
        edited_session_reopen_is_byte_identical: edited_reopen_identical,
        anchor_zero_words_opened: application.anchor_zero_words_opened,
        declared_zero_word_scope_only: application.declared_zero_word_scope_only,
        body_and_cartridge_are_byte_identical: application.cartridge_parity_after,
        plot_uses_packed_probe_coefficients: plot_uses_probe,
        plot_uses_one_shared_db_scale: plot_shared,
        raw_audio_is_not_normalized: !body_solo.normalized && !product.normalized,
        raw_audio_fits_pcm16_without_clipping: body_solo.output_peak <= 1.0
            && product.output_peak <= 1.0,
        body_solo_is_finite: audio_is_finite(&body_solo),
        product_is_finite: audio_is_finite(&product),
        sampled_audit_has_zero_unstable_rows: zero_unstable,
        sampled_audit_has_zero_nonfinite_rows: zero_nonfinite,
    };
    if !gates.all_pass() {
        return Err(WorkstationError(
            "recipe proof gate failed; no proof bundle was promoted".to_owned(),
        ));
    }
    let report = RecipeProofReport {
        format: "trench-workstation-recipe-proof-v1".to_owned(),
        verdict: "PASS".to_owned(),
        contract: "sampled packed-runtime certification; not continuum proof".to_owned(),
        index_validation: catalog.validation,
        application,
        plot_scale,
        body_solo: audio_summary(&body_solo),
        product: audio_summary(&product),
        gates,
        limitations: vec![
            "This proves one clean-room scaffold and one selected recipe lane only.".to_owned(),
            "Published six-decimal edge closure is accepted within 1.5e-6; movements are not averaged or repaired.".to_owned(),
            "The sampled Morph x Q grid does not prove stability over the continuum.".to_owned(),
            "No protected reference bytes, names, coefficient rows, tables, or presets are present.".to_owned(),
        ],
    };
    let artifacts = vec![
        ("source.body240", source_bytes),
        ("edited.body240", edited_body.to_vec()),
        ("session.json", edited_json.into_bytes()),
        ("cartridge.json", edited_session.to_cartridge_json()?.into_bytes()),
        (
            "index-validation.json",
            serde_json::to_vec_pretty(&report.index_validation)?,
        ),
        (
            "changed-word-receipt.json",
            serde_json::to_vec_pretty(&report.application)?,
        ),
        (
            "certification.json",
            serde_json::to_vec_pretty(&report.application.sampled_audit_after)?,
        ),
        ("runtime-plot.json", serde_json::to_vec_pretty(&screen)?),
        ("runtime-response.svg", svg.into_bytes()),
        ("body-solo.wav", body_solo.wav_bytes),
        ("product.wav", product.wav_bytes),
        ("proof.json", serde_json::to_vec_pretty(&report)?),
    ];
    let bundle = write_artifact_bundle(
        output_directory,
        artifacts,
        "trench-workstation-recipe-proof-v1",
    )?;
    Ok(RecipeProofReceipt {
        directory: output_directory.display().to_string(),
        manifest_sha256: bundle.manifest_sha256,
        reused_identical_bundle: bundle.reused_identical_bundle,
        report,
    })
}

pub fn run_proof_slice(
    repo_root: impl AsRef<Path>,
    output_directory: impl AsRef<Path>,
) -> Result<ProofReceipt, WorkstationError> {
    let repo_root = repo_root.as_ref();
    let output_directory = output_directory.as_ref();
    let (source_entry, source_bytes) = declared_fixture(repo_root, "four-pose")?;
    let evidence = EvidenceReference {
        external_repository_commit: "not-applicable-workspace-synthetic-fixture".to_owned(),
        relative_path: source_entry.path.clone(),
        file_sha256: source_entry.sha256.clone(),
        evidence_type: "synthetic-clean-room-fixture".to_owned(),
        note: "Workspace fixture only; no external compiler, protected body, coefficient row, table, or preset bytes were copied.".to_owned(),
    };
    let source_session = Session::from_body_bytes(
        "Four Pose Proof Slice",
        "Synthetic four-authored-pose fixture; lane indices remain registered and unsorted.",
        &source_bytes,
        evidence,
    )?;
    let source_session_json = source_session.to_json()?;
    let source_reopened = Session::from_json(&source_session_json)?;
    let no_op_identical = source_reopened.to_body_bytes()?.as_slice() == source_bytes.as_slice();

    let request = EditRequest::single(0, 0, EditField::ZeroHz, 1300.0);
    let edit = source_session.edit(&request)?;
    let edited_session = &edit.after_session;
    let edited_body = edited_session.to_body_bytes()?;
    let edited_session_json = edited_session.to_json()?;
    let edited_reopened = Session::from_json(&edited_session_json)?;
    let edited_reopen_identical = edited_reopened.to_body_bytes()? == edited_body;
    let declared_selection_only = edit.changed_words.iter().all(|word| {
        word.corner_index == request.corner_indices[0] && word.lane_index == request.lane_indices[0]
    });
    let declared_word_scope_only = !edit.changed_words.is_empty()
        && edit
            .changed_words
            .iter()
            .all(|word| matches!(word.word_index, 0 | 1));

    let (_, identity_bytes) = declared_fixture(repo_root, "identity")?;
    let identity_session = Session::from_body_bytes(
        "Identity Proof Fixture",
        "Synthetic identity fixture.",
        &identity_bytes,
        synthetic_evidence("fixtures/identity.body240", &identity_bytes),
    )?;
    let identity_exact = identity_session
        .corners
        .iter()
        .flat_map(|corner| corner.lanes.iter())
        .all(|stage| stage.runtime_coefficients() == [1.0, 0.0, 0.0, 0.0, 0.0]);

    let (_, real_root_bytes) = declared_fixture(repo_root, "real-root")?;
    let real_root_session = Session::from_body_bytes(
        "Real Root Proof Fixture",
        "Synthetic real-root refusal fixture.",
        &real_root_bytes,
        synthetic_evidence("fixtures/real-root.body240", &real_root_bytes),
    )?;
    let real_root_json = real_root_session.to_json()?;
    let real_root_round_trip = Session::from_json(&real_root_json)?
        .to_body_bytes()?
        .as_slice()
        == real_root_bytes.as_slice();
    let real_root_refused = real_root_session
        .edit(&EditRequest::single(0, 0, EditField::ZeroHz, 900.0))
        .is_err();

    let corner_probe = probe_body(&edited_body, 0.0, 0.0)?;
    let displayed_coefficients_match = edit.targets.len() == 1
        && edit.targets[0].after.runtime_coefficients == corner_probe.rows[0];
    let screen = edited_session.screen(0, 0, 0.5, 0.5)?;
    let plot_uses_probe = screen_uses_probe_rows(&screen, &edited_body)?;
    let (svg, plot_scale) = response_svg(&screen)?;
    let plot_shared = plot_scale.shared_by_corner_labels == CORNER_LABELS.map(str::to_owned);

    let body_solo = render_audio(edited_session, AudioMode::BodySolo)?;
    let product = render_audio(edited_session, AudioMode::Product)?;
    let audit = edit.audit_after.clone();
    let zero_unstable = audit.unstable_mask.iter().all(|failed| !failed);
    let zero_nonfinite = audit.nonfinite_mask.iter().all(|failed| !failed);
    let gates = ProofGates {
        source_body_is_240_bytes: source_bytes.len() == 240,
        no_op_session_reopen_is_byte_identical: no_op_identical,
        edited_session_reopen_is_byte_identical: edited_reopen_identical,
        body_and_cartridge_are_byte_identical: edited_session.cartridge_parity()?,
        declared_selection_only,
        declared_packed_word_scope_only: declared_word_scope_only,
        identity_lanes_decode_exactly: identity_exact,
        real_root_row_round_trips_exactly: real_root_round_trip,
        real_root_conjugate_edit_is_refused: real_root_refused,
        displayed_coefficients_equal_packed_probe: displayed_coefficients_match,
        plot_uses_packed_probe_coefficients: plot_uses_probe,
        plot_uses_one_shared_db_scale: plot_shared,
        raw_audio_is_not_normalized: !body_solo.normalized && !product.normalized,
        raw_audio_fits_pcm16_without_clipping: body_solo.output_peak <= 1.0
            && product.output_peak <= 1.0,
        body_solo_is_finite: audio_is_finite(&body_solo),
        product_is_finite: audio_is_finite(&product),
        sampled_audit_has_zero_unstable_rows: zero_unstable,
        sampled_audit_has_zero_nonfinite_rows: zero_nonfinite,
    };
    if !gates.all_pass() {
        return Err(WorkstationError(
            "proof slice gate failed; no proof bundle was promoted".to_owned(),
        ));
    }

    let report = ProofReport {
        format: PROOF_FORMAT.to_owned(),
        verdict: "PASS".to_owned(),
        contract: "sampled packed-runtime certification; not continuum proof".to_owned(),
        source_fixture: source_entry.name,
        source_fixture_path: source_entry.path,
        source_body_sha256: sha256_hex(&source_bytes),
        edited_body_sha256: sha256_hex(&edited_body),
        edit: request,
        changed_words: edit.changed_words.clone(),
        plot_scale,
        body_solo: audio_summary(&body_solo),
        product: audio_summary(&product),
        sampled_audit: audit,
        gates,
        limitations: vec![
            "This proves one synthetic fixture and one explicit packed edit only.".to_owned(),
            "The sampled Morph x Q grid does not prove stability over the continuum.".to_owned(),
            "Installed VST3 loading and playback are not claimed by this bundle.".to_owned(),
            "No musical recording was fitted and no KEEP/KILL sound judgment is claimed."
                .to_owned(),
        ],
    };

    let artifacts = vec![
        ("source.body240", source_bytes),
        ("edited.body240", edited_body.to_vec()),
        ("session.json", edited_session_json.into_bytes()),
        (
            "cartridge.json",
            edited_session.to_cartridge_json()?.into_bytes(),
        ),
        ("edit-report.json", serde_json::to_vec_pretty(&edit)?),
        (
            "audit.json",
            serde_json::to_vec_pretty(&report.sampled_audit)?,
        ),
        ("runtime-plot.json", serde_json::to_vec_pretty(&screen)?),
        ("runtime-response.svg", svg.into_bytes()),
        ("body-solo.wav", body_solo.wav_bytes),
        ("product.wav", product.wav_bytes),
        ("proof.json", serde_json::to_vec_pretty(&report)?),
    ];
    write_bundle(output_directory, artifacts, report)
}

fn synthetic_evidence(path: &str, bytes: &[u8]) -> EvidenceReference {
    EvidenceReference {
        external_repository_commit: "not-applicable-workspace-synthetic-fixture".to_owned(),
        relative_path: path.to_owned(),
        file_sha256: sha256_hex(bytes),
        evidence_type: "synthetic-clean-room-fixture".to_owned(),
        note: "Workspace fixture only; no external runtime or compiler authority claimed."
            .to_owned(),
    }
}

fn audio_is_finite(audio: &crate::model::AudioRender) -> bool {
    audio.input_peak.is_finite()
        && audio.output_peak.is_finite()
        && audio.output_rms.is_finite()
        && !audio.wav_bytes.is_empty()
}

fn audio_summary(audio: &crate::model::AudioRender) -> AudioSummary {
    AudioSummary {
        mode: audio.mode.as_str().to_owned(),
        sample_rate_hz: audio.sample_rate,
        input_peak: audio.input_peak,
        output_peak: audio.output_peak,
        output_rms: audio.output_rms,
        normalized: audio.normalized,
    }
}

fn screen_uses_probe_rows(screen: &ScreenData, body: &[u8]) -> Result<bool, WorkstationError> {
    for corner in &screen.corners {
        let (morph, q) = match corner.index {
            0 => (0.0, 0.0),
            1 => (1.0, 0.0),
            2 => (0.0, 1.0),
            3 => (1.0, 1.0),
            _ => return Ok(false),
        };
        let probe = probe_body(body, morph, q)?;
        for point in &corner.response.points {
            let expected = biquad_cascade_mag_db(&probe.rows, point.freq_hz, STAGE_SR);
            if point.db.to_bits() != expected.to_bits() {
                return Ok(false);
            }
        }
        if corner.lanes.len() != NUM_STAGES || probe.rows.iter().any(|row| row.len() != NUM_COEFFS)
        {
            return Ok(false);
        }
    }
    Ok(true)
}

fn response_svg(screen: &ScreenData) -> Result<(String, PlotScale), WorkstationError> {
    let values = screen
        .corners
        .iter()
        .flat_map(|corner| corner.response.points.iter().map(|point| point.db))
        .collect::<Vec<_>>();
    if values.is_empty() || values.iter().any(|value| !value.is_finite()) {
        return Err(WorkstationError(
            "runtime plot contains no finite response points".to_owned(),
        ));
    }
    let raw_min = values.iter().copied().fold(f64::INFINITY, f64::min);
    let raw_max = values.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    let minimum_db = (raw_min / 5.0).floor() * 5.0 - 5.0;
    let mut maximum_db = (raw_max / 5.0).ceil() * 5.0 + 5.0;
    if maximum_db <= minimum_db {
        maximum_db = minimum_db + 10.0;
    }
    let scale = PlotScale {
        minimum_db,
        maximum_db,
        shared_by_corner_labels: screen
            .corners
            .iter()
            .map(|corner| corner.label.clone())
            .collect(),
    };

    const WIDTH: f64 = 1200.0;
    const HEIGHT: f64 = 720.0;
    const LEFT: f64 = 92.0;
    const RIGHT: f64 = 32.0;
    const TOP: f64 = 54.0;
    const BOTTOM: f64 = 72.0;
    let plot_width = WIDTH - LEFT - RIGHT;
    let plot_height = HEIGHT - TOP - BOTTOM;
    let colors = ["#d4512a", "#0d6b57", "#3f5f9f", "#8a4f96"];
    let mut svg = String::new();
    svg.push_str("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1200\" height=\"720\" viewBox=\"0 0 1200 720\">\n");
    svg.push_str("<rect width=\"1200\" height=\"720\" fill=\"#f7f5ee\"/>\n");
    svg.push_str("<text x=\"92\" y=\"30\" font-family=\"sans-serif\" font-size=\"18\" fill=\"#202722\">PACKED-RUNTIME FOUR-POSE RESPONSE</text>\n");
    for step in 0..=8 {
        let y = TOP + plot_height * step as f64 / 8.0;
        let db = maximum_db - (maximum_db - minimum_db) * step as f64 / 8.0;
        svg.push_str(&format!("<line x1=\"{LEFT:.2}\" y1=\"{y:.2}\" x2=\"{:.2}\" y2=\"{y:.2}\" stroke=\"#d8d4ca\" stroke-width=\"1\"/>\n", LEFT + plot_width));
        svg.push_str(&format!("<text x=\"{:.2}\" y=\"{:.2}\" text-anchor=\"end\" font-family=\"monospace\" font-size=\"11\" fill=\"#59615b\">{db:.1} dB</text>\n", LEFT - 8.0, y + 4.0));
    }
    if minimum_db <= 0.0 && maximum_db >= 0.0 {
        let y = TOP + (maximum_db / (maximum_db - minimum_db)) * plot_height;
        svg.push_str(&format!("<line x1=\"{LEFT:.2}\" y1=\"{y:.2}\" x2=\"{:.2}\" y2=\"{y:.2}\" stroke=\"#6d746e\" stroke-width=\"1.5\" stroke-dasharray=\"6 5\"/>\n", LEFT + plot_width));
    }
    for (corner_index, corner) in screen.corners.iter().enumerate() {
        let points = &corner.response.points;
        let mut encoded = String::new();
        for (index, point) in points.iter().enumerate() {
            let x =
                LEFT + plot_width * index as f64 / (points.len().saturating_sub(1).max(1)) as f64;
            let y = TOP + (maximum_db - point.db) / (maximum_db - minimum_db) * plot_height;
            encoded.push_str(&format!("{x:.2},{y:.2} "));
        }
        svg.push_str(&format!(
            "<polyline points=\"{}\" fill=\"none\" stroke=\"{}\" stroke-width=\"2.3\"/>\n",
            encoded.trim_end(),
            colors[corner_index]
        ));
        let lx = LEFT + corner_index as f64 * 245.0;
        svg.push_str(&format!("<line x1=\"{lx:.2}\" y1=\"682\" x2=\"{:.2}\" y2=\"682\" stroke=\"{}\" stroke-width=\"4\"/>\n", lx + 28.0, colors[corner_index]));
        svg.push_str(&format!("<text x=\"{:.2}\" y=\"687\" font-family=\"monospace\" font-size=\"13\" fill=\"#202722\">{}</text>\n", lx + 36.0, corner.label));
    }
    for (label, frequency_hz) in [
        ("20", 20.0_f64),
        ("100", 100.0),
        ("1k", 1_000.0),
        ("10k", 10_000.0),
        ("16k Hz", 16_000.0),
    ] {
        let fraction = (frequency_hz / 20.0).ln() / (16_000.0_f64 / 20.0).ln();
        let x = LEFT + plot_width * fraction;
        svg.push_str(&format!("<text x=\"{x:.2}\" y=\"660\" text-anchor=\"middle\" font-family=\"monospace\" font-size=\"11\" fill=\"#59615b\">{label}</text>\n"));
    }
    svg.push_str("</svg>\n");
    Ok((svg, scale))
}

fn write_bundle(
    output_directory: &Path,
    artifacts: Vec<(&str, Vec<u8>)>,
    report: ProofReport,
) -> Result<ProofReceipt, WorkstationError> {
    let bundle = write_artifact_bundle(output_directory, artifacts, PROOF_FORMAT)?;
    Ok(ProofReceipt {
        directory: output_directory.display().to_string(),
        manifest_sha256: bundle.manifest_sha256,
        reused_identical_bundle: bundle.reused_identical_bundle,
        report,
    })
}

struct BundleWriteReceipt {
    manifest_sha256: String,
    reused_identical_bundle: bool,
}

fn write_artifact_bundle(
    output_directory: &Path,
    artifacts: Vec<(&str, Vec<u8>)>,
    manifest_format: &str,
) -> Result<BundleWriteReceipt, WorkstationError> {
    let parent = output_directory
        .parent()
        .ok_or_else(|| WorkstationError("proof output must have a parent directory".to_owned()))?;
    fs::create_dir_all(parent)?;
    let name = output_directory
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| WorkstationError("proof output name is not valid UTF-8".to_owned()))?;
    let temporary = parent.join(format!(".{name}.tmp"));
    if temporary.exists() {
        fs::remove_dir_all(&temporary)?;
    }
    fs::create_dir(&temporary)?;
    let mut records = Vec::with_capacity(artifacts.len());
    for (relative, bytes) in artifacts {
        fs::write(temporary.join(relative), &bytes)?;
        records.push(ArtifactRecord {
            path: relative.to_owned(),
            bytes: bytes.len(),
            sha256: sha256_hex(&bytes),
        });
    }
    let manifest = ProofManifest {
        format: manifest_format.to_owned(),
        proof_report: "proof.json".to_owned(),
        artifacts: records,
    };
    let manifest_bytes = serde_json::to_vec_pretty(&manifest)?;
    fs::write(temporary.join("manifest.json"), &manifest_bytes)?;
    let manifest_sha256 = sha256_hex(&manifest_bytes);

    let reused_identical_bundle = if output_directory.exists() {
        if directories_are_byte_identical(&temporary, output_directory)? {
            fs::remove_dir_all(&temporary)?;
            true
        } else {
            fs::remove_dir_all(&temporary)?;
            return Err(WorkstationError(format!(
                "existing proof bundle '{}' differs; it was not overwritten",
                output_directory.display()
            )));
        }
    } else {
        rename_directory_with_retry(&temporary, output_directory)?;
        false
    };
    Ok(BundleWriteReceipt {
        manifest_sha256,
        reused_identical_bundle,
    })
}

fn rename_directory_with_retry(source: &Path, destination: &Path) -> Result<(), WorkstationError> {
    let mut last_error = None;
    for _ in 0..25 {
        match fs::rename(source, destination) {
            Ok(()) => return Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => {
                last_error = Some(error);
                std::thread::sleep(std::time::Duration::from_millis(20));
            }
            Err(error) => return Err(error.into()),
        }
    }
    Err(last_error
        .unwrap_or_else(|| std::io::Error::new(std::io::ErrorKind::Other, "rename failed"))
        .into())
}

fn directories_are_byte_identical(left: &Path, right: &Path) -> Result<bool, WorkstationError> {
    fn files(path: &Path) -> Result<Vec<PathBuf>, std::io::Error> {
        let mut out = fs::read_dir(path)?
            .filter_map(Result::ok)
            .map(|entry| entry.path())
            .filter(|entry| entry.is_file())
            .collect::<Vec<_>>();
        out.sort_by(|a, b| a.file_name().cmp(&b.file_name()));
        Ok(out)
    }
    let left_files = files(left)?;
    let right_files = files(right)?;
    if left_files.len() != right_files.len() {
        return Ok(false);
    }
    for (left_file, right_file) in left_files.iter().zip(right_files.iter()) {
        if left_file.file_name() != right_file.file_name()
            || fs::read(left_file)? != fs::read(right_file)?
        {
            return Ok(false);
        }
    }
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn repo_root() -> PathBuf {
        let source = Path::new(file!());
        if source.is_absolute() {
            return source.ancestors().nth(3).expect("repository root").to_path_buf();
        }
        Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf()
    }

    #[test]
    fn proof_slice_passes_and_is_byte_reproducible() {
        let output = repo_root()
            .join("target")
            .join("proof-slice-test")
            .join(PROOF_DIRECTORY);
        if let Some(parent) = output.parent() {
            let _ = fs::remove_dir_all(parent);
        }
        let first = run_proof_slice(repo_root(), &output).unwrap();
        assert_eq!(first.report.verdict, "PASS");
        assert!(!first.reused_identical_bundle);
        let second = run_proof_slice(repo_root(), &output).unwrap();
        assert!(second.reused_identical_bundle);
        assert_eq!(first.manifest_sha256, second.manifest_sha256);
    }
}
