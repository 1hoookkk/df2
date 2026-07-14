use crate::hash::sha256_hex;
use crate::model::{
    ActorProvenance, AudioMode, AudioRender, ChangedWord, EditRequest, EditResult,
    EvidenceReference, Pose,
    RootGeometry, SampledAudit, ScreenData, Session, StageRecord, StageSourceReference,
    WorkstationError, CORNER_LABELS, DIRECT_STAGE_EVIDENCE, SESSION_FORMAT,
};
use crate::recipe_index::{apply_candidate, RecipeApplication, RecipeCatalog, RecipeIndex};
use crate::source_xml::{SourceCatalog, SourceEndpoint};
use serde::Serialize;
use std::fs;
use std::path::{Path, PathBuf};
use trench_core::cartridge::BODY_BYTES;
use trench_core::cascade::{NUM_COEFFS, NUM_STAGES};
use trench_core::lpc::{extract_poles, Pole};
use trench_core::stage_law::STAGE_SR;

const OWNED_ACTOR_EVIDENCE: &str = "owned-audio-lpc-fixed-actor-v1";
const MAX_ACTOR_SAMPLES: usize = 12_000_000;
const REFERENCE_GUIDE_SHA256: &str =
    "25D8F6D2E4BAC8B3588BA370513DD8B51FBBBC3C7204BDCC6BFD69672630E9CC";

#[derive(Debug, Clone)]
pub struct BodySource {
    pub path: String,
    pub name: String,
    pub file_sha256: String,
    pub session: Session,
    pub screen: ScreenData,
}

impl BodySource {
    fn view(&self) -> BodySourceView {
        BodySourceView {
            path: self.path.clone(),
            name: self.name.clone(),
            file_sha256: self.file_sha256.clone(),
            screen: self.screen.clone(),
        }
    }
}

#[derive(Debug, Clone)]
pub struct AppState {
    pub repo_root: PathBuf,
    pub session: Session,
    pub audit: SampledAudit,
    pub selected_corner: usize,
    pub selected_lane: usize,
    pub morph: f64,
    pub q: f64,
    pub pending_edit: Option<PendingPreview>,
    pub last_edit: Option<EditResult>,
    pub undo: Vec<Session>,
    pub redo: Vec<Session>,
    pub last_keep: Option<String>,
    pub source_catalog: SourceCatalog,
    pub last_source_apply: Option<SourceApplyReport>,
    pub last_actor_load: Option<ActorLoadReport>,
    pub recipe_catalog: RecipeCatalog,
    pub selected_recipe: usize,
    pub last_recipe_apply: Option<RecipeApplication>,
    pub recipe_ledger: Vec<RecipeApplication>,
    pub body_source: Option<BodySource>,
    pub last_body_apply: Option<BodyApplyReport>,
}

impl AppState {
    pub fn new(repo_root: impl AsRef<Path>) -> Result<Self, WorkstationError> {
        let repo_root = repo_root.as_ref().to_path_buf();
        let session = talking_frame_starter()?;
        let body = session.to_body_bytes()?;
        let audit = SampledAudit::run(&body)?;
        let source_catalog = SourceCatalog::discover(&repo_root)?;
        let recipe_catalog = load_recipe_catalog(&repo_root, &session)?;
        Ok(Self {
            repo_root,
            session,
            audit,
            selected_corner: 0,
            selected_lane: 0,
            morph: 0.5,
            q: 0.5,
            pending_edit: None,
            last_edit: None,
            undo: Vec::new(),
            redo: Vec::new(),
            last_keep: None,
            source_catalog,
            last_source_apply: None,
            last_actor_load: None,
            recipe_catalog,
            selected_recipe: 0,
            last_recipe_apply: None,
            recipe_ledger: Vec::new(),
            body_source: None,
            last_body_apply: None,
        })
    }

    pub fn screen(&self) -> Result<ScreenData, WorkstationError> {
        self.session.screen_with_audit(
            self.selected_corner,
            self.selected_lane,
            self.morph,
            self.q,
            self.audit.clone(),
        )
    }

    pub fn select(&mut self, corner: usize, lane: usize) -> Result<(), WorkstationError> {
        if corner >= 4 || lane >= 6 {
            return Err(WorkstationError("selection is out of range".to_owned()));
        }
        self.selected_corner = corner;
        self.selected_lane = lane;
        Ok(())
    }

    pub fn new_filter(&mut self) -> Result<(), WorkstationError> {
        let next = talking_frame_starter()?;
        let body = next.to_body_bytes()?;
        self.undo.push(self.session.clone());
        self.redo.clear();
        self.session = next;
        self.audit = SampledAudit::run(&body)?;
        self.selected_corner = 0;
        self.selected_lane = 0;
        self.morph = 0.5;
        self.q = 0.5;
        self.pending_edit = None;
        self.last_edit = None;
        self.last_keep = None;
        self.last_source_apply = None;
        self.last_actor_load = None;
        self.last_recipe_apply = None;
        self.recipe_ledger.clear();
        self.last_body_apply = None;
        self.refresh_recipe_catalog()?;
        Ok(())
    }

    pub fn make_filter(&mut self) -> Result<(), WorkstationError> {
        Err(WorkstationError(
            "choose an indexed XML endpoint; synthetic MAKE is disabled".to_owned(),
        ))
    }

    pub fn fill_corner_from_source(
        &mut self,
        corner: usize,
        source_index: usize,
        endpoint: SourceEndpoint,
    ) -> Result<SourceApplyReport, WorkstationError> {
        let assignments = (0..6)
            .map(|lane| (lane, source_index, endpoint, lane))
            .collect::<Vec<_>>();
        self.apply_source_assignments("fill_corner", corner, assignments)
    }

    pub fn assign_lane_from_source(
        &mut self,
        corner: usize,
        lane: usize,
        source_index: usize,
        endpoint: SourceEndpoint,
        source_section: usize,
    ) -> Result<SourceApplyReport, WorkstationError> {
        self.apply_source_assignments(
            "replace_lane",
            corner,
            vec![(lane, source_index, endpoint, source_section)],
        )
    }

    fn apply_source_assignments(
        &mut self,
        operation: &str,
        corner: usize,
        assignments: Vec<(usize, usize, SourceEndpoint, usize)>,
    ) -> Result<SourceApplyReport, WorkstationError> {
        if corner >= 4 {
            return Err(WorkstationError("corner is out of range".to_owned()));
        }
        if assignments.is_empty() {
            return Err(WorkstationError("source assignment is empty".to_owned()));
        }
        let before_body = self.session.to_body_bytes()?;
        let mut after = self.session.clone();
        let mut source_refs = Vec::with_capacity(assignments.len());
        let mut lanes = Vec::with_capacity(assignments.len());
        for &(lane, source_index, endpoint, source_section) in &assignments {
            if lane >= 6 {
                return Err(WorkstationError("lane is out of range".to_owned()));
            }
            if lanes.contains(&lane) {
                return Err(WorkstationError(
                    "source assignment names a lane more than once".to_owned(),
                ));
            }
            let compiled =
                self.source_catalog
                    .compile_stage(source_index, endpoint, source_section)?;
            source_refs.push(compiled.source.clone());
            lanes.push(lane);
            after.corners[corner].lanes[lane] =
                StageRecord::from_source_words(compiled.words, compiled.evidence, compiled.source);
        }
        after.validate()?;
        let after_body = after.to_body_bytes()?;
        let audit_after = SampledAudit::run(&after_body)?;
        let mut changed_words = Vec::new();
        for &lane in &lanes {
            let before = self.session.corners[corner].lanes[lane].packed_words;
            let after_words = after.corners[corner].lanes[lane].packed_words;
            for word_index in 0..5 {
                if before[word_index] != after_words[word_index] {
                    changed_words.push(ChangedWord {
                        corner_index: corner,
                        corner_label: CORNER_LABELS[corner].to_owned(),
                        lane_index: lane,
                        word_index,
                        before: before[word_index],
                        after: after_words[word_index],
                    });
                }
            }
        }
        let report = SourceApplyReport {
            format: "trench-workstation-source-apply-v1".to_owned(),
            operation: operation.to_owned(),
            corner_index: corner,
            lane_indices: lanes,
            assignments: source_refs,
            before_body_sha256: sha256_hex(&before_body),
            after_body_sha256: sha256_hex(&after_body),
            changed_words,
            sampled_audit_after: audit_after.clone(),
            cartridge_parity_after: after.cartridge_parity()?,
        };
        self.undo.push(self.session.clone());
        self.redo.clear();
        self.session = after;
        self.audit = audit_after;
        self.selected_corner = corner;
        if let Some(&lane) = report.lane_indices.first() {
            self.selected_lane = lane;
        }
        self.pending_edit = None;
        self.last_edit = None;
        self.last_source_apply = Some(report.clone());
        self.last_actor_load = None;
        self.last_recipe_apply = None;
        self.recipe_ledger.clear();
        self.last_body_apply = None;
        self.last_keep = None;
        self.refresh_recipe_catalog()?;
        Ok(report)
    }

    pub fn apply_recipe(
        &mut self,
        candidate_index: usize,
    ) -> Result<RecipeApplication, WorkstationError> {
        let candidate = self
            .recipe_catalog
            .candidates
            .get(candidate_index)
            .cloned()
            .ok_or_else(|| WorkstationError("recipe selection is out of range".to_owned()))?;
        let result = apply_candidate(&self.session.name, &self.session, &candidate)?;
        if !result.sampled_audit_after.pass || !result.sampled_audit_after.certify_pass {
            return Err(WorkstationError(
                "recipe result failed sampled packed-runtime certification".to_owned(),
            ));
        }
        self.undo.push(self.session.clone());
        self.redo.clear();
        self.session = result.after_session.clone();
        self.audit = result.sampled_audit_after.clone();
        self.selected_corner = 0;
        self.selected_lane = candidate.scaffold_lane_index;
        self.pending_edit = None;
        self.last_edit = None;
        self.last_source_apply = None;
        self.last_actor_load = None;
        self.last_recipe_apply = Some(result.clone());
        self.recipe_ledger.push(result.clone());
        self.last_body_apply = None;
        self.last_keep = None;
        self.refresh_recipe_catalog()?;
        self.selected_recipe = self
            .recipe_catalog
            .candidates
            .iter()
            .position(|item| item.candidate_id == candidate.candidate_id)
            .unwrap_or(0);
        Ok(result)
    }

    /// Backwards-compatible owned-audio entry point. Production actors use the
    /// provenance-aware method below; this path remains intentionally labeled
    /// as user-owned and is not eligible for the verified measured/simulated
    /// bank contract.
    pub fn load_fixed_actor_audio(
        &mut self,
        samples: &[f32],
        sample_rate_hz: f64,
        source_path: impl AsRef<Path>,
    ) -> Result<ActorLoadReport, WorkstationError> {
        let source_path = source_path.as_ref();
        let source_bytes = fs::read(source_path).map_err(|error| {
            WorkstationError(format!(
                "could not hash actor source '{}': {error}",
                source_path.display()
            ))
        })?;
        let absolute_source_path = fs::canonicalize(source_path)
            .unwrap_or_else(|_| source_path.to_path_buf())
            .display()
            .to_string();
        let provenance = ActorProvenance {
            evidence_class: OWNED_ACTOR_EVIDENCE.to_owned(),
            repository_commit: "not-applicable-user-owned-audio".to_owned(),
            absolute_source_path,
            relative_source_path: source_path.display().to_string(),
            file_sha256: sha256_hex(&source_bytes),
            license_source_description: "User-owned audio supplied to the workstation.".to_owned(),
            source_status: "MEASURED".to_owned(),
            source_sample_rate_hz: Some(sample_rate_hz),
            frf_reconstruction: Some("direct recorded waveform; no FRF reconstruction".to_owned()),
        };
        self.load_verified_actor_audio(samples, sample_rate_hz, source_path, provenance)
    }

    /// Establish one registered six-actor pole scaffold from a verified
    /// measured or simulated source. LPC is called exactly once by this
    /// loader. It supplies poles only; every zero starts exactly coincident
    /// with its pole and remains the explicit recipe-authoring layer.
    pub fn load_verified_actor_audio(
        &mut self,
        samples: &[f32],
        sample_rate_hz: f64,
        source_path: impl AsRef<Path>,
        provenance: ActorProvenance,
    ) -> Result<ActorLoadReport, WorkstationError> {
        provenance.validate()?;
        if !sample_rate_hz.is_finite() || !(8_000.0..=384_000.0).contains(&sample_rate_hz) {
            return Err(WorkstationError(
                "actor recording sample rate must be finite and in 8000..384000 Hz".to_owned(),
            ));
        }
        if samples.len() < 2_048 {
            return Err(WorkstationError(
                "actor recording is too short; provide at least 2048 mono samples".to_owned(),
            ));
        }
        if samples.len() > MAX_ACTOR_SAMPLES {
            return Err(WorkstationError(format!(
                "actor recording exceeds the explicit {MAX_ACTOR_SAMPLES}-sample analysis limit"
            )));
        }
        if samples.iter().any(|sample| !sample.is_finite()) {
            return Err(WorkstationError(
                "actor recording contains nonfinite samples".to_owned(),
            ));
        }
        let peak = samples
            .iter()
            .fold(0.0_f32, |largest, sample| largest.max(sample.abs()));
        if peak <= 1.0e-8 {
            return Err(WorkstationError(
                "actor recording is silent; no pole evidence can be extracted".to_owned(),
            ));
        }

        let source_path = source_path.as_ref();
        let source_bytes = fs::read(source_path).map_err(|error| {
            WorkstationError(format!(
                "could not hash actor source '{}': {error}",
                source_path.display()
            ))
        })?;
        let source_hash = sha256_hex(&source_bytes);
        if !source_hash.eq_ignore_ascii_case(&provenance.file_sha256) {
            return Err(WorkstationError(format!(
                "actor provenance hash mismatch for '{}'",
                source_path.display()
            )));
        }
        let canonical_source_path = fs::canonicalize(source_path)
            .unwrap_or_else(|_| source_path.to_path_buf())
            .display()
            .to_string();
        if !canonical_source_path.eq_ignore_ascii_case(&provenance.absolute_source_path) {
            return Err(WorkstationError(format!(
                "actor provenance absolute path mismatch for '{}'",
                source_path.display()
            )));
        }
        let analysis_samples = samples
            .iter()
            .map(|sample| *sample as f64)
            .collect::<Vec<_>>();
        let poles = extract_poles(&analysis_samples, sample_rate_hz);
        if poles.len() != NUM_STAGES {
            return Err(WorkstationError(format!(
                "LPC found {} usable resonant actors; exactly {NUM_STAGES} are required",
                poles.len()
            )));
        }

        let evidence = EvidenceReference {
            external_repository_commit: provenance.repository_commit.clone(),
            relative_path: provenance.relative_source_path.clone(),
            file_sha256: source_hash.clone(),
            evidence_type: provenance.evidence_class.clone(),
            note: format!(
                "Pole geometry is LPC-estimated from verified {} evidence. Lane order is registered once at import and never re-sorted per pose. Each zero starts exactly coincident with its pole; no valley fit, normalization, gain repair, or automatic zero placement is used. {}",
                provenance.source_status, provenance.license_source_description
            ),
        };
        let display_name = source_path
            .file_stem()
            .map(|stem| stem.to_string_lossy().trim().to_owned())
            .filter(|name| !name.is_empty())
            .unwrap_or_else(|| "Owned Actor Filter".to_owned());
        let (next, measurements) = fixed_actor_session(
            display_name,
            poles,
            evidence,
            Some(provenance.clone()),
        )?;
        let before = self.session.clone();
        let before_body = before.to_body_bytes()?;
        let after_body = next.to_body_bytes()?;
        let audit_after = SampledAudit::run(&after_body)?;
        if !audit_after.pass || !audit_after.certify_pass {
            return Err(WorkstationError(
                "fixed actor scaffold failed sampled packed-runtime certification".to_owned(),
            ));
        }
        let report = ActorLoadReport {
            format: "trench-workstation-actor-load-v1".to_owned(),
            source_path: source_path.display().to_string(),
            source_file_sha256: source_hash,
            source_sample_rate_hz: sample_rate_hz,
            source_sample_count: samples.len(),
            provenance,
            lane_registration: "one LPC extraction; six actors registered once in ascending measured frequency; identical packed pole/SCALE words stored in all four explicit poses".to_owned(),
            zero_initialization: "each zero exactly coincident with its pole; closed mask; zero character remains user-authored".to_owned(),
            lanes: measurements,
            before_body_sha256: sha256_hex(&before_body),
            after_body_sha256: sha256_hex(&after_body),
            changed_words: changed_words_between(&before, &next),
            sampled_audit_after: audit_after.clone(),
            cartridge_parity_after: next.cartridge_parity()?,
        };
        if !report.cartridge_parity_after {
            return Err(WorkstationError(
                "fixed actor body/cartridge packed-word parity failed".to_owned(),
            ));
        }

        self.undo.push(self.session.clone());
        self.redo.clear();
        self.session = next;
        self.audit = audit_after;
        self.selected_corner = 0;
        self.selected_lane = 0;
        self.pending_edit = None;
        self.last_edit = None;
        self.last_source_apply = None;
        self.last_actor_load = Some(report.clone());
        self.last_recipe_apply = None;
        self.recipe_ledger.clear();
        self.last_body_apply = None;
        self.last_keep = None;
        self.refresh_recipe_catalog()?;
        Ok(report)
    }

    pub fn load_session_json(&mut self, json: &str) -> Result<(), WorkstationError> {
        let next = Session::from_json(json)?;
        let body = next.to_body_bytes()?;
        if !next.cartridge_parity()? {
            return Err(WorkstationError(
                "opened session failed body/cartridge packed-word parity".to_owned(),
            ));
        }
        let audit = SampledAudit::run(&body)?;
        self.undo.push(self.session.clone());
        self.redo.clear();
        self.session = next;
        self.audit = audit;
        self.selected_corner = 0;
        self.selected_lane = 0;
        self.pending_edit = None;
        self.last_edit = None;
        self.last_source_apply = None;
        self.last_actor_load = None;
        self.last_recipe_apply = None;
        self.recipe_ledger.clear();
        self.last_body_apply = None;
        self.last_keep = None;
        self.refresh_recipe_catalog()?;
        Ok(())
    }

    pub fn load_body_source(
        &mut self,
        path: impl AsRef<Path>,
    ) -> Result<BodySourceView, WorkstationError> {
        let path = fs::canonicalize(path.as_ref()).map_err(|error| {
            WorkstationError(format!(
                "body source '{}' could not be opened: {error}",
                path.as_ref().display()
            ))
        })?;
        let bytes = fs::read(&path)?;
        if bytes.len() != BODY_BYTES {
            return Err(WorkstationError(format!(
                "{} is {} bytes; a body must be exactly {BODY_BYTES}",
                path.display(),
                bytes.len()
            )));
        }
        let name = path
            .file_stem()
            .and_then(|value| value.to_str())
            .ok_or_else(|| WorkstationError("body source filename is not UTF-8".to_owned()))?
            .to_owned();
        let file_sha256 = sha256_hex(&bytes);
        let evidence = EvidenceReference {
            external_repository_commit: "user-selected-body240".to_owned(),
            relative_path: path.display().to_string(),
            file_sha256: file_sha256.clone(),
            evidence_type: DIRECT_STAGE_EVIDENCE.to_owned(),
            note: "Exact user-selected SOS body; no fitting, sorting, normalization, or repair."
                .to_owned(),
        };
        let session = Session::from_body_bytes(
            &name,
            "Exact body240 source loaded for indexed corner stitching.",
            &bytes,
            evidence,
        )?;
        let audit = SampledAudit::run(&bytes)?;
        let screen = session.screen_with_audit(0, 0, 0.5, 0.5, audit)?;
        let source = BodySource {
            path: path.display().to_string(),
            name,
            file_sha256,
            session,
            screen,
        };
        let view = source.view();
        self.body_source = Some(source);
        Ok(view)
    }

    pub fn load_body_as_session(
        &mut self,
        path: impl AsRef<Path>,
    ) -> Result<BodyApplyReport, WorkstationError> {
        self.load_body_source(path)?;
        self.apply_body_source(None, None)
    }

    pub fn stitch_body_corner(
        &mut self,
        source_corner: usize,
        target_corner: usize,
    ) -> Result<BodyApplyReport, WorkstationError> {
        if source_corner >= 4 || target_corner >= 4 {
            return Err(WorkstationError(
                "source and target corners must be in 0..3".to_owned(),
            ));
        }
        self.apply_body_source(Some(source_corner), Some(target_corner))
    }

    fn apply_body_source(
        &mut self,
        source_corner: Option<usize>,
        target_corner: Option<usize>,
    ) -> Result<BodyApplyReport, WorkstationError> {
        let source = self
            .body_source
            .clone()
            .ok_or_else(|| WorkstationError("no body source is loaded".to_owned()))?;
        let before = self.session.clone();
        let before_body = before.to_body_bytes()?;
        let mut after = match (source_corner, target_corner) {
            (None, None) => source.session.clone(),
            (Some(source_corner), Some(target_corner)) => {
                let mut next = before.clone();
                next.corners[target_corner].lanes =
                    source.session.corners[source_corner].lanes.clone();
                next
            }
            _ => {
                return Err(WorkstationError(
                    "body stitch must name both source and target corners".to_owned(),
                ));
            }
        };
        after.note = match (source_corner, target_corner) {
            (None, None) => format!("Loaded exact body source '{}'.", source.name),
            (Some(source_corner), Some(target_corner)) => format!(
                "Stitched {} from '{}' into {} without reordering its six SOS stages.",
                CORNER_LABELS[source_corner], source.name, CORNER_LABELS[target_corner]
            ),
            _ => unreachable!(),
        };
        after.validate()?;
        let after_body = after.to_body_bytes()?;
        let audit_after = SampledAudit::run(&after_body)?;
        let report = BodyApplyReport {
            format: "trench-workstation-body-apply-v1".to_owned(),
            operation: if source_corner.is_some() {
                "stitch_corner".to_owned()
            } else {
                "load_body".to_owned()
            },
            source_path: source.path,
            source_name: source.name,
            source_file_sha256: source.file_sha256,
            source_corner,
            target_corner,
            before_body_sha256: sha256_hex(&before_body),
            after_body_sha256: sha256_hex(&after_body),
            changed_words: changed_words_between(&before, &after),
            sampled_audit_after: audit_after.clone(),
            cartridge_parity_after: after.cartridge_parity()?,
        };
        self.undo.push(before);
        self.redo.clear();
        self.session = after;
        self.audit = audit_after;
        self.selected_corner = target_corner.unwrap_or(0);
        self.pending_edit = None;
        self.last_edit = None;
        self.last_source_apply = None;
        self.last_actor_load = None;
        self.last_recipe_apply = None;
        self.recipe_ledger.clear();
        self.last_body_apply = Some(report.clone());
        self.last_keep = None;
        self.refresh_recipe_catalog()?;
        Ok(report)
    }

    fn refresh_recipe_catalog(&mut self) -> Result<(), WorkstationError> {
        self.recipe_catalog = load_recipe_catalog(&self.repo_root, &self.session)?;
        self.selected_recipe = self
            .selected_recipe
            .min(self.recipe_catalog.candidates.len().saturating_sub(1));
        Ok(())
    }

    pub fn set_morph_q(&mut self, morph: f64, q: f64) -> Result<(), WorkstationError> {
        if !morph.is_finite()
            || !q.is_finite()
            || !(0.0..=1.0).contains(&morph)
            || !(0.0..=1.0).contains(&q)
        {
            return Err(WorkstationError(
                "Morph and Q must be finite values in 0..1".to_owned(),
            ));
        }
        self.morph = morph;
        self.q = q;
        Ok(())
    }

    pub fn preview(&mut self, request: EditRequest) -> Result<PendingPreview, WorkstationError> {
        let after_session = self.session.preview_edit(&request)?;
        let result = PendingPreview {
            after_body_sha256: sha256_hex(&after_session.to_body_bytes()?),
            request,
            after_session,
        };
        if let Some(&corner) = result.request.corner_indices.first() {
            self.selected_corner = corner;
        }
        if let Some(&lane) = result.request.lane_indices.first() {
            self.selected_lane = lane;
        }
        self.pending_edit = Some(result.clone());
        self.last_source_apply = None;
        Ok(result)
    }

    pub fn apply(&mut self) -> Result<EditResult, WorkstationError> {
        let preview = self
            .pending_edit
            .take()
            .ok_or_else(|| WorkstationError("there is no pending edit to apply".to_owned()))?;
        let result = self.session.edit(&preview.request)?;
        if sha256_hex(&result.after_session.to_body_bytes()?) != preview.after_body_sha256 {
            return Err(WorkstationError(
                "preview and commit produced different packed body bytes".to_owned(),
            ));
        }
        self.undo.push(self.session.clone());
        self.redo.clear();
        self.session = result.after_session.clone();
        self.audit = result.audit_after.clone();
        self.last_edit = Some(result.clone());
        self.last_source_apply = None;
        self.last_actor_load = None;
        self.last_recipe_apply = None;
        self.recipe_ledger.clear();
        self.last_body_apply = None;
        self.last_keep = None;
        self.refresh_recipe_catalog()?;
        Ok(result)
    }

    pub fn discard_preview(&mut self) {
        self.pending_edit = None;
    }

    pub fn undo(&mut self) -> Result<(), WorkstationError> {
        let previous = self
            .undo
            .pop()
            .ok_or_else(|| WorkstationError("nothing to undo".to_owned()))?;
        self.redo.push(self.session.clone());
        self.session = previous;
        self.audit = SampledAudit::run(&self.session.to_body_bytes()?)?;
        self.pending_edit = None;
        self.last_edit = None;
        self.last_source_apply = None;
        self.last_actor_load = None;
        self.last_recipe_apply = None;
        self.recipe_ledger.clear();
        self.last_body_apply = None;
        self.last_keep = None;
        self.refresh_recipe_catalog()?;
        Ok(())
    }

    pub fn redo(&mut self) -> Result<(), WorkstationError> {
        let next = self
            .redo
            .pop()
            .ok_or_else(|| WorkstationError("nothing to redo".to_owned()))?;
        self.undo.push(self.session.clone());
        self.session = next;
        self.audit = SampledAudit::run(&self.session.to_body_bytes()?)?;
        self.pending_edit = None;
        self.last_edit = None;
        self.last_source_apply = None;
        self.last_actor_load = None;
        self.last_recipe_apply = None;
        self.recipe_ledger.clear();
        self.last_body_apply = None;
        self.last_keep = None;
        self.refresh_recipe_catalog()?;
        Ok(())
    }

    pub fn render_audio(&self, mode: AudioMode) -> Result<AudioRender, WorkstationError> {
        crate::model::render_audio(&self.session, mode)
    }

    pub fn stage_solo_body(&self, pending: bool) -> Result<[u8; BODY_BYTES], WorkstationError> {
        let session = if pending {
            self.pending_edit
                .as_ref()
                .map(|preview| &preview.after_session)
                .unwrap_or(&self.session)
        } else {
            &self.session
        };
        session.stage_solo_body_bytes(self.selected_lane)
    }

    pub fn keep(&mut self) -> Result<SaveReceipt, WorkstationError> {
        let body = self.session.to_body_bytes()?;
        self.audit = SampledAudit::run(&body)?;
        let readiness = self.export_readiness()?;
        if !readiness.ready {
            return Err(WorkstationError(format!(
                "export blocked: {}",
                readiness.blockers.join("; ")
            )));
        }
        let session_json = self.session.to_json()?;
        let reopened = Session::from_json(&session_json)?;
        if reopened.to_body_bytes()? != body {
            return Err(WorkstationError(
                "session save/reopen changed body bytes".to_owned(),
            ));
        }
        if !self.session.cartridge_parity()? {
            return Err(WorkstationError(
                "body/cartridge packed-word parity failed".to_owned(),
            ));
        }
        let screen = self.screen()?;
        let body_solo = self.render_audio(AudioMode::BodySolo)?;
        let product = self.render_audio(AudioMode::Product)?;
        let runs = self.repo_root.join("workstation").join("runs");
        fs::create_dir_all(&runs)?;
        let content_key = sha256_hex(&body);
        let tmp = runs.join(format!(".keep_{content_key}.tmp"));
        let final_dir = runs.join(format!("keep_{content_key}"));
        if final_dir.exists() {
            return Err(WorkstationError(format!(
                "content-addressed KEEP already exists at '{}'; inspect that receipt instead of creating a second run",
                final_dir.display()
            )));
        }
        if tmp.exists() {
            fs::remove_dir_all(&tmp)?;
        }
        fs::create_dir_all(&tmp)?;
        let artifacts: [(&str, Vec<u8>); 8] = [
            ("session.json", session_json.into_bytes()),
            ("body240", body.to_vec()),
            (
                "cartridge.json",
                self.session.to_cartridge_json()?.into_bytes(),
            ),
            ("audit.json", serde_json::to_vec_pretty(&self.audit)?),
            ("plot.json", serde_json::to_vec_pretty(&screen)?),
            (
                "reference-shape-guide.json",
                serde_json::to_vec_pretty(&reference_shape_guide())?,
            ),
            ("body_solo.wav", body_solo.wav_bytes.clone()),
            ("product.wav", product.wav_bytes.clone()),
        ];
        let mut files = Vec::with_capacity(artifacts.len());
        for (relative, bytes) in artifacts {
            let path = tmp.join(relative);
            fs::write(&path, &bytes)?;
            files.push(SavedFile {
                path: relative.to_owned(),
                bytes: bytes.len(),
                sha256: sha256_hex(&bytes),
            });
        }
        if let Some(edit) = &self.last_edit {
            let bytes = serde_json::to_vec_pretty(edit)?;
            fs::write(tmp.join("edit-report.json"), &bytes)?;
            files.push(SavedFile {
                path: "edit-report.json".to_owned(),
                bytes: bytes.len(),
                sha256: sha256_hex(&bytes),
            });
        }
        if let Some(report) = &self.last_source_apply {
            let bytes = serde_json::to_vec_pretty(report)?;
            fs::write(tmp.join("source-apply-report.json"), &bytes)?;
            files.push(SavedFile {
                path: "source-apply-report.json".to_owned(),
                bytes: bytes.len(),
                sha256: sha256_hex(&bytes),
            });
        }
        if let Some(report) = &self.last_actor_load {
            let bytes = serde_json::to_vec_pretty(report)?;
            fs::write(tmp.join("actor-load-report.json"), &bytes)?;
            files.push(SavedFile {
                path: "actor-load-report.json".to_owned(),
                bytes: bytes.len(),
                sha256: sha256_hex(&bytes),
            });
        }
        if let Some(report) = &self.last_recipe_apply {
            let bytes = serde_json::to_vec_pretty(report)?;
            fs::write(tmp.join("recipe-apply-report.json"), &bytes)?;
            files.push(SavedFile {
                path: "recipe-apply-report.json".to_owned(),
                bytes: bytes.len(),
                sha256: sha256_hex(&bytes),
            });
        }
        if !self.recipe_ledger.is_empty() {
            let bytes = serde_json::to_vec_pretty(&self.recipe_ledger)?;
            fs::write(tmp.join("recipe-ledger.json"), &bytes)?;
            files.push(SavedFile {
                path: "recipe-ledger.json".to_owned(),
                bytes: bytes.len(),
                sha256: sha256_hex(&bytes),
            });
        }
        if let Some(report) = &self.last_body_apply {
            let bytes = serde_json::to_vec_pretty(report)?;
            fs::write(tmp.join("body-apply-report.json"), &bytes)?;
            files.push(SavedFile {
                path: "body-apply-report.json".to_owned(),
                bytes: bytes.len(),
                sha256: sha256_hex(&bytes),
            });
        }
        let manifest = SaveManifest {
            format: "trench-workstation-keep-v1".to_owned(),
            body_bytes: BODY_BYTES,
            session_reopen_identical: true,
            cartridge_parity: true,
            raw_audio_normalized: false,
            audio_fixture: "fixed two-tone technical probe; make the musical KEEP/KILL decision through live BODY SOLO and PRODUCT audition".to_owned(),
            export_readiness: readiness,
            files: files.clone(),
        };
        fs::write(
            tmp.join("manifest.json"),
            serde_json::to_vec_pretty(&manifest)?,
        )?;
        fs::rename(&tmp, &final_dir)?;
        let receipt = SaveReceipt {
            directory: final_dir.display().to_string(),
            manifest,
            body_solo_peak: body_solo.output_peak,
            product_peak: product.output_peak,
        };
        self.last_keep = Some(receipt.directory.clone());
        Ok(receipt)
    }

    pub fn export_readiness(&self) -> Result<ExportReadiness, WorkstationError> {
        let body = self.session.to_body_bytes()?;
        let no_pending_preview = self.pending_edit.is_none();
        let sampled_certification = self.audit.pass && self.audit.certify_pass;
        let cartridge_parity = self.session.cartridge_parity()?;
        let verified_actor_scaffold = self
            .session
            .corners
            .iter()
            .flat_map(|corner| corner.lanes.iter())
            .all(|stage| {
                stage.source.is_none()
                    && stage
                        .actor_provenance
                        .as_ref()
                        .map(|provenance| provenance.validate().is_ok())
                        .unwrap_or(false)
                    && matches!(
                        stage.evidence.evidence_type.as_str(),
                        "measured-vvtf-lpc-fixed-actor-v1"
                            | "simulated-physical-object-lpc-fixed-actor-v1"
                            | OWNED_ACTOR_EVIDENCE
                    )
            });
        let owned_fixed_actor_scaffold = verified_actor_scaffold;
        let direct_stage_session = self
            .session
            .corners
            .iter()
            .flat_map(|corner| corner.lanes.iter())
            .all(|stage| {
                stage.evidence.evidence_type == DIRECT_STAGE_EVIDENCE && stage.source.is_none()
            });
        let eligible_scaffold = verified_actor_scaffold || direct_stage_session;
        let fixed_poles_across_corners = (0..NUM_STAGES).all(|lane| {
            let anchor = self.session.corners[0].lanes[lane].packed_words;
            self.session.corners[1..].iter().all(|corner| {
                let words = corner.lanes[lane].packed_words;
                words[2..=4] == anchor[2..=4]
            })
        });
        let zero_character_authored = self
            .session
            .corners
            .iter()
            .flat_map(|corner| corner.lanes.iter())
            .any(|stage| stage.packed_words[0..=1] != stage.packed_words[2..=3]);
        let packed = trench_core::minifloat::PackedCorners::from_body_bytes(&body)
            .map_err(|error| WorkstationError(error.to_owned()))?;
        let four_pose_character_authored = packed.words[1..]
            .iter()
            .any(|corner| *corner != packed.words[0]);
        let exact_edit_receipt = self.last_edit.is_some()
            || self.last_recipe_apply.is_some()
            || self.last_body_apply.is_some();
        let mut blockers = Vec::new();
        if !no_pending_preview {
            blockers.push("KEEP or DISCARD the pending geometry preview".to_owned());
        }
        if !eligible_scaffold {
            blockers.push(
                "start from the direct clean-room body or load an owned recording; reference XML is study-only"
                    .to_owned(),
            );
        }
        if verified_actor_scaffold && !fixed_poles_across_corners {
            blockers.push("fixed actor pole/SCALE registration differs across poses".to_owned());
        }
        if !zero_character_authored {
            blockers.push("open at least one actor mask by authoring a zero".to_owned());
        }
        if !four_pose_character_authored {
            blockers.push("author a Morph or Q difference across the four stored poses".to_owned());
        }
        if direct_stage_session && !exact_edit_receipt {
            blockers.push("sculpt and KEEP at least one declared stage edit".to_owned());
        }
        if !sampled_certification {
            blockers.push("sampled Morph x Q certification is not passing".to_owned());
        }
        if !cartridge_parity {
            blockers.push("body/cartridge packed-word parity is not passing".to_owned());
        }
        Ok(ExportReadiness {
            format: "trench-workstation-export-readiness-v1".to_owned(),
            ready: blockers.is_empty(),
            no_pending_preview,
            eligible_scaffold,
            direct_stage_session,
            verified_actor_scaffold,
            owned_fixed_actor_scaffold,
            fixed_poles_across_corners,
            zero_character_authored,
            four_pose_character_authored,
            exact_edit_receipt,
            sampled_certification,
            cartridge_parity,
            blockers,
        })
    }
}

pub(crate) fn fixed_actor_session(
    name: String,
    poles: Vec<Pole>,
    evidence: EvidenceReference,
    actor_provenance: Option<ActorProvenance>,
) -> Result<(Session, Vec<ActorLaneMeasurement>), WorkstationError> {
    if let Some(provenance) = &actor_provenance {
        provenance.validate()?;
    }
    if poles.len() != NUM_STAGES {
        return Err(WorkstationError(format!(
            "fixed actor scaffold requires exactly {NUM_STAGES} poles"
        )));
    }
    let mut lanes = Vec::with_capacity(NUM_STAGES);
    let mut measurements = Vec::with_capacity(NUM_STAGES);
    for (lane_index, pole) in poles.into_iter().enumerate() {
        if !pole.freq_hz.is_finite()
            || !pole.bw_hz.is_finite()
            || pole.freq_hz <= 0.0
            || pole.freq_hz >= STAGE_SR * 0.5
            || pole.bw_hz <= 0.0
        {
            return Err(WorkstationError(format!(
                "LPC actor L{} has illegal measured geometry",
                lane_index + 1
            )));
        }
        let runtime_radius = (-std::f64::consts::PI * pole.bw_hz / STAGE_SR).exp();
        if !runtime_radius.is_finite() || !(0.0..1.0).contains(&runtime_radius) {
            return Err(WorkstationError(format!(
                "LPC actor L{} cannot be re-homed at the packed runtime rate",
                lane_index + 1
            )));
        }
        let geometry = RootGeometry::Conjugate {
            hz: pole.freq_hz,
            radius: runtime_radius,
        };
        let mut stage = StageRecord::from_geometry(geometry.clone(), geometry, 1.0, evidence.clone())?;
        stage.actor_provenance = actor_provenance.clone();
        if stage.packed_words[0..=1] != stage.packed_words[2..=3] {
            return Err(WorkstationError(format!(
                "LPC actor L{} did not quantise to an exactly closed pole-zero mask",
                lane_index + 1
            )));
        }
        measurements.push(ActorLaneMeasurement {
            lane_index,
            frequency_hz: pole.freq_hz,
            analysis_radius: pole.radius,
            bandwidth_hz: pole.bw_hz,
            runtime_radius,
            packed_pole_words: [stage.packed_words[2], stage.packed_words[3]],
        });
        lanes.push(stage);
    }
    let corners = CORNER_LABELS
        .iter()
        .map(|label| Pose {
            label: (*label).to_owned(),
            lanes: lanes.clone(),
        })
        .collect();
    let session = Session {
        format: SESSION_FORMAT.to_owned(),
        name,
        note: "Six LPC-estimated actors from one verified source. Packed pole/SCALE words are fixed across all four explicit poses; coincident zeros begin as closed masks and remain the only editable character layer.".to_owned(),
        authoring_sample_rate_hz: STAGE_SR,
        corners,
    };
    session.validate()?;
    Ok((session, measurements))
}

fn changed_words_between(before: &Session, after: &Session) -> Vec<ChangedWord> {
    let mut changed = Vec::new();
    for corner_index in 0..CORNER_LABELS.len() {
        for lane_index in 0..NUM_STAGES {
            let before_words = before.corners[corner_index].lanes[lane_index].packed_words;
            let after_words = after.corners[corner_index].lanes[lane_index].packed_words;
            for word_index in 0..NUM_COEFFS {
                if before_words[word_index] != after_words[word_index] {
                    changed.push(ChangedWord {
                        corner_index,
                        corner_label: CORNER_LABELS[corner_index].to_owned(),
                        lane_index,
                        word_index,
                        before: before_words[word_index],
                        after: after_words[word_index],
                    });
                }
            }
        }
    }
    changed
}

fn load_recipe_catalog(
    repo_root: &Path,
    session: &Session,
) -> Result<RecipeCatalog, WorkstationError> {
    let path = repo_root.join("recipe-index").join("recipe_index_v1.json");
    let (index, bytes) = RecipeIndex::load(repo_root)?;
    index.catalog(path, &bytes, session)
}

fn talking_frame_starter() -> Result<Session, WorkstationError> {
    // Independently chosen authoring coordinates. The table is deliberately
    // explicit: Q100 is not derived, no lane is sorted, and every SCALE is an
    // authored numerator scalar. The external study contributes only the
    // coarse relationship guide returned by `reference_shape_guide`.
    const SPECS: [[[f64; 5]; NUM_STAGES]; 4] = [
        [
            [8800.0, 0.910, 420.0, 0.780, 0.562],
            [760.0, 0.920, 1120.0, 0.840, 0.749],
            [1420.0, 0.900, 2050.0, 0.860, 0.764],
            [2260.0, 0.920, 3180.0, 0.870, 0.749],
            [4160.0, 0.900, 7200.0, 0.760, 0.655],
            [180.0, 0.940, 6100.0, 0.860, 0.546],
        ],
        [
            [8200.0, 0.890, 1450.0, 0.800, 0.593],
            [260.0, 0.930, 820.0, 0.860, 0.741],
            [2250.0, 0.920, 2100.0, 0.840, 0.796],
            [2840.0, 0.910, 2730.0, 0.860, 0.764],
            [4500.0, 0.890, 5550.0, 0.750, 0.686],
            [1540.0, 0.950, 7200.0, 0.880, 0.562],
        ],
        [
            [9300.0, 0.965, 360.0, 0.760, 0.515],
            [860.0, 0.972, 1040.0, 0.870, 0.702],
            [1540.0, 0.966, 1900.0, 0.880, 0.725],
            [2140.0, 0.972, 2960.0, 0.890, 0.710],
            [3900.0, 0.958, 7500.0, 0.780, 0.624],
            [150.0, 0.976, 5900.0, 0.890, 0.484],
        ],
        [
            [8500.0, 0.962, 1320.0, 0.820, 0.546],
            [230.0, 0.974, 760.0, 0.890, 0.694],
            [2100.0, 0.968, 2000.0, 0.900, 0.749],
            [2520.0, 0.970, 2600.0, 0.910, 0.733],
            [4260.0, 0.960, 5300.0, 0.800, 0.655],
            [1380.0, 0.977, 6900.0, 0.910, 0.499],
        ],
    ];
    let evidence = direct_stage_evidence();
    let mut corners = Vec::with_capacity(CORNER_LABELS.len());
    for (corner_index, label) in CORNER_LABELS.iter().enumerate() {
        let mut lanes = Vec::with_capacity(NUM_STAGES);
        for spec in SPECS[corner_index] {
            lanes.push(StageRecord::from_geometry(
                RootGeometry::Conjugate {
                    hz: spec[0],
                    radius: spec[1],
                },
                RootGeometry::Conjugate {
                    hz: spec[2],
                    radius: spec[3],
                },
                spec[4],
                evidence.clone(),
            )?);
        }
        corners.push(Pose {
            label: (*label).to_owned(),
            lanes,
        });
    }
    let session = Session {
        format: SESSION_FORMAT.to_owned(),
        name: "Original Talking Frame 01".to_owned(),
        note: "Independent six-stage clean-room starter. S1/S6 are movable outer boundaries; S2-S5 are registered internal articulators. All four poses and every SCALE are explicit. The qualitative guide contains no reference roots, coefficients, words, tables, names, or assets.".to_owned(),
        authoring_sample_rate_hz: STAGE_SR,
        corners,
    };
    session.validate()?;
    Ok(session)
}

fn direct_stage_evidence() -> EvidenceReference {
    EvidenceReference {
        external_repository_commit: "not-applicable-independent-authoring".to_owned(),
        relative_path: "embedded:original-talking-frame-starter-v1".to_owned(),
        file_sha256: REFERENCE_GUIDE_SHA256.to_owned(),
        evidence_type: DIRECT_STAGE_EVIDENCE.to_owned(),
        note: "Independently authored pole, zero, and SCALE geometry. External plot hash identifies the study observation used only for a coarse relationship guide; no source coordinates or packed data are retained.".to_owned(),
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct GuidePoint {
    pub x: f64,
    pub y: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct GuidePoseShape {
    pub corner_index: usize,
    pub pole: GuidePoint,
    pub zero: GuidePoint,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StageShapeGuide {
    pub stage_index: usize,
    pub role: String,
    pub movement: String,
    pub poses: Vec<GuidePoseShape>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ReferenceShapeGuide {
    pub format: String,
    pub visible_label: String,
    pub source_file_sha256: String,
    pub construction: String,
    pub prohibition: String,
    pub stages: Vec<StageShapeGuide>,
}

fn reference_shape_guide() -> ReferenceShapeGuide {
    // Deliberately coarse, hand-redrawn unit-disk relationships: coordinates
    // are snapped to a small visual vocabulary and are not source roots.
    const POINTS: [[[[f64; 2]; 2]; 4]; NUM_STAGES] = [
        [
            [[0.15, 0.90], [0.85, 0.15]],
            [[0.25, 0.85], [0.80, 0.30]],
            [[0.00, 0.90], [0.85, 0.10]],
            [[0.15, 0.90], [0.80, 0.25]],
        ],
        [
            [[0.88, 0.18], [0.84, 0.24]],
            [[0.92, 0.06], [0.86, 0.16]],
            [[0.88, 0.18], [0.84, 0.24]],
            [[0.92, 0.06], [0.86, 0.16]],
        ],
        [
            [[0.80, 0.32], [0.76, 0.38]],
            [[0.72, 0.42], [0.74, 0.38]],
            [[0.80, 0.32], [0.77, 0.36]],
            [[0.74, 0.38], [0.76, 0.34]],
        ],
        [
            [[0.72, 0.46], [0.66, 0.54]],
            [[0.68, 0.50], [0.66, 0.52]],
            [[0.74, 0.42], [0.68, 0.50]],
            [[0.70, 0.46], [0.68, 0.48]],
        ],
        [
            [[0.62, 0.66], [0.30, 0.72]],
            [[0.60, 0.64], [0.44, 0.62]],
            [[0.64, 0.64], [0.28, 0.72]],
            [[0.62, 0.62], [0.46, 0.58]],
        ],
        [
            [[0.90, 0.08], [0.50, 0.80]],
            [[0.78, 0.34], [-0.84, 0.34]],
            [[0.90, 0.06], [0.52, 0.78]],
            [[0.78, 0.32], [-0.84, 0.34]],
        ],
    ];
    const ROLES: [&str; NUM_STAGES] = [
        "FRAME A", "TALKER 1", "TALKER 2", "TALKER 3", "TALKER 4", "FRAME B",
    ];
    const MOVEMENTS: [&str; NUM_STAGES] = [
        "wide separation; zero travels while pole holds the upper boundary",
        "close pair; pole walks past a steadier zero",
        "near pair; converge and cross",
        "near pair; close the gap without losing correspondence",
        "upper pair; zero approaches the pole",
        "wide frame; pole climbs while the zero traverses the outer arc",
    ];
    let stages = (0..NUM_STAGES)
        .map(|stage_index| StageShapeGuide {
            stage_index,
            role: ROLES[stage_index].to_owned(),
            movement: MOVEMENTS[stage_index].to_owned(),
            poses: (0..4)
                .map(|corner_index| GuidePoseShape {
                    corner_index,
                    pole: GuidePoint {
                        x: POINTS[stage_index][corner_index][0][0],
                        y: POINTS[stage_index][corner_index][0][1],
                    },
                    zero: GuidePoint {
                        x: POINTS[stage_index][corner_index][1][0],
                        y: POINTS[stage_index][corner_index][1][1],
                    },
                })
                .collect(),
        })
        .collect();
    ReferenceShapeGuide {
        format: "trench-workstation-qualitative-stage-guide-v1".to_owned(),
        visible_label: "STUDY GUIDE / QUALITATIVE / NOT AUTHORING DATA".to_owned(),
        source_file_sha256: REFERENCE_GUIDE_SHA256.to_owned(),
        construction: "hand-redrawn unit-disk relationships snapped to a coarse visual vocabulary; no source coordinate extraction".to_owned(),
        prohibition: "must not be exported as roots, coefficients, words, a body, a preset, or a protected asset".to_owned(),
        stages,
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BodySourceView {
    pub path: String,
    pub name: String,
    pub file_sha256: String,
    pub screen: ScreenData,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BodyApplyReport {
    pub format: String,
    pub operation: String,
    pub source_path: String,
    pub source_name: String,
    pub source_file_sha256: String,
    pub source_corner: Option<usize>,
    pub target_corner: Option<usize>,
    pub before_body_sha256: String,
    pub after_body_sha256: String,
    pub changed_words: Vec<ChangedWord>,
    pub sampled_audit_after: SampledAudit,
    pub cartridge_parity_after: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct AppSnapshot {
    pub screen: ScreenData,
    #[serde(rename = "referenceShapeGuide")]
    pub reference_shape_guide: ReferenceShapeGuide,
    #[serde(rename = "pendingEdit")]
    pub pending_edit: Option<PendingPreview>,
    #[serde(rename = "lastEdit")]
    pub last_edit: Option<EditResult>,
    pub can_undo: bool,
    pub can_redo: bool,
    #[serde(rename = "lastKeep")]
    pub last_keep: Option<String>,
    #[serde(rename = "sourceCatalog")]
    pub source_catalog: SourceCatalog,
    #[serde(rename = "lastSourceApply")]
    pub last_source_apply: Option<SourceApplyReport>,
    #[serde(rename = "lastActorLoad")]
    pub last_actor_load: Option<ActorLoadReport>,
    #[serde(rename = "recipeCatalog")]
    pub recipe_catalog: RecipeCatalog,
    #[serde(rename = "selectedRecipe")]
    pub selected_recipe: usize,
    #[serde(rename = "lastRecipeApply")]
    pub last_recipe_apply: Option<RecipeApplication>,
    #[serde(rename = "recipeLedger")]
    pub recipe_ledger: Vec<RecipeApplication>,
    #[serde(rename = "bodySource")]
    pub body_source: Option<BodySourceView>,
    #[serde(rename = "lastBodyApply")]
    pub last_body_apply: Option<BodyApplyReport>,
    #[serde(rename = "exportReadiness")]
    pub export_readiness: ExportReadiness,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct PendingPreview {
    pub request: EditRequest,
    #[serde(rename = "afterBodySha256")]
    pub after_body_sha256: String,
    #[serde(skip)]
    pub after_session: Session,
}

impl AppState {
    pub fn snapshot(&self) -> Result<AppSnapshot, WorkstationError> {
        Ok(AppSnapshot {
            screen: self.screen()?,
            reference_shape_guide: reference_shape_guide(),
            pending_edit: self.pending_edit.clone(),
            last_edit: self.last_edit.clone(),
            can_undo: !self.undo.is_empty(),
            can_redo: !self.redo.is_empty(),
            last_keep: self.last_keep.clone(),
            source_catalog: self.source_catalog.clone(),
            last_source_apply: self.last_source_apply.clone(),
            last_actor_load: self.last_actor_load.clone(),
            recipe_catalog: self.recipe_catalog.clone(),
            selected_recipe: self.selected_recipe,
            last_recipe_apply: self.last_recipe_apply.clone(),
            recipe_ledger: self.recipe_ledger.clone(),
            body_source: self.body_source.as_ref().map(BodySource::view),
            last_body_apply: self.last_body_apply.clone(),
            export_readiness: self.export_readiness()?,
        })
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ActorLaneMeasurement {
    pub lane_index: usize,
    pub frequency_hz: f64,
    pub analysis_radius: f64,
    pub bandwidth_hz: f64,
    pub runtime_radius: f64,
    pub packed_pole_words: [u16; 2],
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ActorLoadReport {
    pub format: String,
    pub source_path: String,
    pub source_file_sha256: String,
    pub source_sample_rate_hz: f64,
    pub source_sample_count: usize,
    pub provenance: ActorProvenance,
    pub lane_registration: String,
    pub zero_initialization: String,
    pub lanes: Vec<ActorLaneMeasurement>,
    pub before_body_sha256: String,
    pub after_body_sha256: String,
    pub changed_words: Vec<ChangedWord>,
    pub sampled_audit_after: SampledAudit,
    pub cartridge_parity_after: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ExportReadiness {
    pub format: String,
    pub ready: bool,
    pub no_pending_preview: bool,
    pub eligible_scaffold: bool,
    pub direct_stage_session: bool,
    pub verified_actor_scaffold: bool,
    pub owned_fixed_actor_scaffold: bool,
    pub fixed_poles_across_corners: bool,
    pub zero_character_authored: bool,
    pub four_pose_character_authored: bool,
    pub exact_edit_receipt: bool,
    pub sampled_certification: bool,
    pub cartridge_parity: bool,
    pub blockers: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct SourceApplyReport {
    pub format: String,
    pub operation: String,
    #[serde(rename = "cornerIndex")]
    pub corner_index: usize,
    #[serde(rename = "laneIndices")]
    pub lane_indices: Vec<usize>,
    pub assignments: Vec<StageSourceReference>,
    #[serde(rename = "beforeBodySha256")]
    pub before_body_sha256: String,
    #[serde(rename = "afterBodySha256")]
    pub after_body_sha256: String,
    #[serde(rename = "changedWords")]
    pub changed_words: Vec<ChangedWord>,
    #[serde(rename = "sampledAuditAfter")]
    pub sampled_audit_after: SampledAudit,
    #[serde(rename = "cartridgeParityAfter")]
    pub cartridge_parity_after: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct SavedFile {
    pub path: String,
    pub bytes: usize,
    pub sha256: String,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct SaveManifest {
    pub format: String,
    pub body_bytes: usize,
    pub session_reopen_identical: bool,
    pub cartridge_parity: bool,
    pub raw_audio_normalized: bool,
    pub audio_fixture: String,
    pub export_readiness: ExportReadiness,
    pub files: Vec<SavedFile>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct SaveReceipt {
    pub directory: String,
    pub manifest: SaveManifest,
    pub body_solo_peak: f32,
    pub product_peak: f32,
}

#[cfg(test)]
mod tests {
    use super::{fixed_actor_session, AppState, DIRECT_STAGE_EVIDENCE, OWNED_ACTOR_EVIDENCE};
    use crate::hash::sha256_hex;
    use crate::model::{ActorProvenance, EditField, EditRequest, EvidenceReference, SampledAudit};
    use crate::source_xml::SourceEndpoint;
    use std::fs;
    use trench_core::lpc::Pole;

    fn repo_root() -> std::path::PathBuf {
        let source = std::path::Path::new(file!());
        if source.is_absolute() {
            return source
                .ancestors()
                .nth(3)
                .expect("repository root")
                .to_path_buf();
        }
        std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .to_path_buf()
    }

    fn identity_body_path() -> std::path::PathBuf {
        repo_root()
            .join("plugin")
            .join("assets")
            .join("bodies")
            .join("identity.body240")
    }

    #[test]
    fn body_source_selection_is_read_only_and_whole_body_load_is_byte_exact() {
        let mut app = AppState::new(repo_root()).unwrap();
        let before = app.session.to_body_bytes().unwrap();
        let source = app.load_body_source(identity_body_path()).unwrap();
        assert_eq!(app.session.to_body_bytes().unwrap(), before);
        assert_eq!(source.screen.corners.len(), 4);
        assert_eq!(source.file_sha256.len(), 64);

        let expected = fs::read(identity_body_path()).unwrap();
        let report = app.load_body_as_session(identity_body_path()).unwrap();
        assert_eq!(app.session.to_body_bytes().unwrap().as_slice(), expected);
        assert_eq!(report.operation, "load_body");
        assert!(report.source_corner.is_none());
        assert!(report.target_corner.is_none());
        assert!(report.cartridge_parity_after);
        assert!(report.sampled_audit_after.pass && report.sampled_audit_after.certify_pass);
        assert_eq!(app.last_body_apply, Some(report));
    }

    #[test]
    fn body_corner_stitch_replaces_exactly_six_registered_stages_in_one_pose() {
        let mut app = AppState::new(repo_root()).unwrap();
        let before = app.session.clone();
        app.load_body_source(identity_body_path()).unwrap();
        let source = app.body_source.as_ref().unwrap().session.clone();
        let report = app.stitch_body_corner(3, 1).unwrap();

        assert_eq!(app.session.corners[1].lanes, source.corners[3].lanes);
        assert_eq!(app.session.corners[0], before.corners[0]);
        assert_eq!(app.session.corners[2], before.corners[2]);
        assert_eq!(app.session.corners[3], before.corners[3]);
        assert_eq!(report.operation, "stitch_corner");
        assert_eq!(report.source_corner, Some(3));
        assert_eq!(report.target_corner, Some(1));
        assert!(report
            .changed_words
            .iter()
            .all(|word| word.corner_index == 1 && word.lane_index < 6 && word.word_index < 5));
        assert!(report.cartridge_parity_after);
        assert!(report.sampled_audit_after.pass && report.sampled_audit_after.certify_pass);
        assert!(app.export_readiness().unwrap().exact_edit_receipt);
    }

    #[test]
    fn new_filter_is_an_explicit_four_pose_direct_stage_scaffold() {
        let mut app = AppState::new(repo_root()).unwrap();
        app.new_filter().unwrap();
        assert_eq!(app.session.name, "Original Talking Frame 01");
        assert!(app
            .session
            .corners
            .iter()
            .flat_map(|pose| pose.lanes.iter())
            .all(|stage| !stage.identity && stage.evidence.evidence_type == DIRECT_STAGE_EVIDENCE));
        assert!(app.audit.pass && app.audit.certify_pass);
        let screen = app.screen().unwrap();
        let peak_db = screen
            .corners
            .iter()
            .flat_map(|corner| corner.response.points.iter())
            .map(|point| point.db)
            .fold(f64::NEG_INFINITY, f64::max);
        assert!(
            peak_db <= 30.0,
            "starter exceeds the audition plot headroom: {peak_db:.2} dB"
        );
        let body_solo = app.render_audio(crate::model::AudioMode::BodySolo).unwrap();
        assert!(
            body_solo.output_peak <= 1.0,
            "raw starter audition clips without normalization: {}",
            body_solo.output_peak
        );
        let before = app.session.to_body_bytes().unwrap();

        app.preview(EditRequest::conjugate(vec![0], 0, true, 9_100.0, 0.925))
            .unwrap();
        assert!(app.pending_edit.is_some());
        let edit = app.apply().unwrap();
        assert!(edit.changed_words.iter().all(|word| word.corner_index == 0
            && word.lane_index == 0
            && (word.word_index == 2 || word.word_index == 3)));
        assert_ne!(before, app.session.to_body_bytes().unwrap());
        assert!(app.export_readiness().unwrap().ready);
    }

    #[test]
    fn synthetic_make_is_disabled() {
        let mut app = AppState::new(repo_root()).unwrap();
        app.new_filter().unwrap();
        assert!(app.make_filter().is_err());
    }

    #[test]
    fn whole_xml_endpoint_fills_registered_lanes_without_sorting() {
        let mut app = AppState::new(repo_root()).unwrap();
        let Some(source) = app
            .source_catalog
            .sources
            .iter()
            .find(|source| source.active_sections > 0)
            .cloned()
        else {
            return;
        };
        let report = app
            .fill_corner_from_source(2, source.index, SourceEndpoint::High)
            .unwrap();
        assert_eq!(report.lane_indices, vec![0, 1, 2, 3, 4, 5]);
        for (lane, stage) in app.session.corners[2].lanes.iter().enumerate() {
            let reference = stage.source.as_ref().unwrap();
            assert_eq!(reference.catalog_index, source.index);
            assert_eq!(reference.section_index, lane + 1);
            assert_eq!(reference.endpoint, "high");
        }
    }

    #[test]
    fn proven_recipe_path_is_available_and_applies_through_the_same_state_bridge() {
        let mut app = AppState::new(repo_root()).unwrap();
        let index = 0;
        let result = app.apply_recipe(index).unwrap();
        assert!(result.anchor_zero_words_opened);
        assert!(result.declared_zero_word_scope_only);
        assert!(result.sampled_audit_after.pass);
        assert_eq!(app.selected_lane, result.candidate.scaffold_lane_index);
        assert!(app.last_recipe_apply.is_some());
    }

    #[test]
    fn fixed_actor_scaffold_stays_closed_until_an_exact_zero_edit_is_applied() {
        let poles = [180.0, 420.0, 900.0, 1_800.0, 4_200.0, 8_000.0]
            .into_iter()
            .enumerate()
            .map(|(index, freq_hz)| Pole {
                freq_hz,
                radius: 0.96 - index as f64 * 0.01,
                bw_hz: 80.0 + index as f64 * 90.0,
            })
            .collect();
        let evidence = EvidenceReference {
            external_repository_commit: "not-applicable-user-owned-audio".to_owned(),
            relative_path: "owned-test.wav".to_owned(),
            file_sha256: "A".repeat(64),
            evidence_type: OWNED_ACTOR_EVIDENCE.to_owned(),
            note: "test actor evidence".to_owned(),
        };
        let provenance = ActorProvenance {
            evidence_class: OWNED_ACTOR_EVIDENCE.to_owned(),
            repository_commit: "test-commit".to_owned(),
            absolute_source_path: r"C:\test\owned-test.wav".to_owned(),
            relative_source_path: "owned-test.wav".to_owned(),
            file_sha256: "A".repeat(64),
            license_source_description: "test source".to_owned(),
            source_status: "MEASURED".to_owned(),
            source_sample_rate_hz: Some(16_000.0),
            frf_reconstruction: Some("test waveform".to_owned()),
        };
        let (session, lanes) = fixed_actor_session(
            "Owned Actors".to_owned(),
            poles,
            evidence,
            Some(provenance),
        )
        .unwrap();
        assert_eq!(lanes.len(), 6);
        assert!(session
            .corners
            .iter()
            .flat_map(|corner| &corner.lanes)
            .all(|stage| { stage.packed_words[0..=1] == stage.packed_words[2..=3] }));

        let mut app = AppState::new(repo_root()).unwrap();
        app.session = session;
        app.audit = SampledAudit::run(&app.session.to_body_bytes().unwrap()).unwrap();
        app.refresh_recipe_catalog().unwrap();
        let closed = app.export_readiness().unwrap();
        assert!(!closed.ready);
        assert!(!closed.zero_character_authored);

        let preview = app
            .preview(EditRequest::single(1, 0, EditField::ZeroHz, 260.0))
            .unwrap();
        assert!(!app.export_readiness().unwrap().no_pending_preview);
        let preview_hash = preview.after_body_sha256;
        let committed = app.apply().unwrap();
        assert_eq!(preview_hash, committed.after_body_sha256);
        assert_eq!(
            preview_hash,
            sha256_hex(&app.session.to_body_bytes().unwrap())
        );
        let ready = app.export_readiness().unwrap();
        assert!(ready.ready, "{:?}", ready.blockers);

        let body = app.session.to_body_bytes().unwrap();
        let json = app.session.to_json().unwrap();
        app.new_filter().unwrap();
        app.load_session_json(&json).unwrap();
        assert_eq!(app.session.to_body_bytes().unwrap(), body);
        assert!(app.export_readiness().unwrap().ready);
    }
}
