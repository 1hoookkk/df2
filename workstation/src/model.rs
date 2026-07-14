use crate::hash::sha256_hex;
use serde::{Deserialize, Serialize};
use std::fmt;
use trench_core::cartridge::BODY_BYTES;
use trench_core::cascade::{NUM_COEFFS, NUM_STAGES};
use trench_core::ffi::{trench_certify_body, trench_packed_probe};
use trench_core::minifloat::{stage_words_to_biquad, PackedCorners, PackedStage};
use trench_core::response::{
    biquad_cascade_mag_db, biquad_stage_mag_db, log_frequency_grid, ResponseCurve, ResponsePoint,
};
use trench_core::stage_law::{
    geometry_from_words, words_from_geometry, words_from_roots, RootPair, StageGeometry,
    StageRoots, STAGE_SR,
};
use trench_core::{Cartridge, FilterEngine, InputMode, SpatialMode};

pub const SESSION_FORMAT: &str = "trench-workstation-session-v1";
pub const EDIT_FORMAT: &str = "trench-workstation-edit-v1";
pub const AUDIT_FORMAT: &str = "trench-workstation-sampled-audit-v1";
pub const SCREEN_FORMAT: &str = "trench-workstation-screen-v1";
pub const CORNER_LABELS: [&str; 4] = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];
pub const DEFAULT_RESPONSE_BINS: usize = 256;
pub const DEFAULT_AUDIT_RESOLUTION: usize = 17;
pub const DIRECT_STAGE_EVIDENCE: &str = "clean-room-direct-stage-v1";

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct FixtureManifest {
    pub format: String,
    pub provenance: String,
    pub fixtures: Vec<FixtureEntry>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct FixtureEntry {
    pub name: String,
    pub path: String,
    pub size: usize,
    pub sha256: String,
    pub purpose: String,
    #[serde(rename = "expectedBehavior")]
    pub expected_behavior: Vec<String>,
}

pub fn declared_fixture_manifest(
    repo_root: impl AsRef<std::path::Path>,
) -> Result<FixtureManifest, WorkstationError> {
    let path = repo_root.as_ref().join("fixtures").join("manifest.json");
    let manifest: FixtureManifest = serde_json::from_str(&std::fs::read_to_string(path)?)?;
    if manifest.format != "trench-workstation-fixtures-v1" {
        return Err(invalid("unsupported fixture manifest format"));
    }
    Ok(manifest)
}

pub fn declared_fixture(
    repo_root: impl AsRef<std::path::Path>,
    name: &str,
) -> Result<(FixtureEntry, Vec<u8>), WorkstationError> {
    let root = repo_root.as_ref();
    let manifest = declared_fixture_manifest(root)?;
    let entry = manifest
        .fixtures
        .into_iter()
        .find(|fixture| fixture.name == name)
        .ok_or_else(|| invalid(format!("fixture '{name}' is not declared")))?;
    let bytes = std::fs::read(root.join(&entry.path))?;
    if bytes.len() != entry.size || sha256_hex(&bytes) != entry.sha256 {
        return Err(invalid(format!(
            "fixture '{}' failed manifest hash/size",
            entry.name
        )));
    }
    Ok((entry, bytes))
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkstationError(pub String);

impl fmt::Display for WorkstationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for WorkstationError {}

impl From<std::io::Error> for WorkstationError {
    fn from(error: std::io::Error) -> Self {
        Self(error.to_string())
    }
}

impl From<serde_json::Error> for WorkstationError {
    fn from(error: serde_json::Error) -> Self {
        Self(error.to_string())
    }
}

fn invalid(message: impl Into<String>) -> WorkstationError {
    WorkstationError(message.into())
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EvidenceReference {
    #[serde(rename = "externalRepositoryCommit")]
    pub external_repository_commit: String,
    #[serde(rename = "relativePath")]
    pub relative_path: String,
    #[serde(rename = "fileSha256")]
    pub file_sha256: String,
    #[serde(rename = "evidenceType")]
    pub evidence_type: String,
    pub note: String,
}

/// Provenance for a fixed six-actor scaffold. This is distinct from the
/// packed stage evidence: it identifies the source artifact and the verified
/// measured/simulated class that made it eligible for LPC import.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ActorProvenance {
    pub evidence_class: String,
    pub repository_commit: String,
    pub absolute_source_path: String,
    pub relative_source_path: String,
    pub file_sha256: String,
    pub license_source_description: String,
    pub source_status: String,
    pub source_sample_rate_hz: Option<f64>,
    pub frf_reconstruction: Option<String>,
}

impl ActorProvenance {
    pub fn validate(&self) -> Result<(), WorkstationError> {
        if self.evidence_class.trim().is_empty()
            || self.repository_commit.trim().is_empty()
            || self.absolute_source_path.trim().is_empty()
            || self.relative_source_path.trim().is_empty()
            || self.file_sha256.len() != 64
            || self.license_source_description.trim().is_empty()
        {
            return Err(invalid("actor provenance has an empty or malformed identity field"));
        }
        if !matches!(self.source_status.as_str(), "MEASURED" | "SIMULATED") {
            return Err(invalid("actor provenance source status must be MEASURED or SIMULATED"));
        }
        if let Some(rate) = self.source_sample_rate_hz {
            if !rate.is_finite() || rate <= 0.0 {
                return Err(invalid("actor provenance sample rate is nonfinite or nonpositive"));
            }
        }
        if self.source_status == "MEASURED" && self.frf_reconstruction.is_none() {
            return Err(invalid(
                "measured actor provenance must record its FRF/impulse reconstruction",
            ));
        }
        Ok(())
    }
}

/// Reproducible address of the XML endpoint/section that supplied one lane.
/// The source bytes remain external and read-only; the hash makes drift
/// explicit when the session is reopened.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StageSourceReference {
    #[serde(rename = "catalogIndex")]
    pub catalog_index: usize,
    #[serde(rename = "sourceName")]
    pub source_name: String,
    #[serde(rename = "relativePath")]
    pub relative_path: String,
    #[serde(rename = "fileSha256")]
    pub file_sha256: String,
    pub endpoint: String,
    #[serde(rename = "sectionIndex")]
    pub section_index: usize,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum RootGeometry {
    Conjugate { hz: f64, radius: f64 },
    RealPair { root_a: f64, root_b: f64 },
    Degenerate,
}

impl RootGeometry {
    fn from_root_pair(pair: RootPair) -> Self {
        match pair {
            RootPair::Conjugate { hz, r } => Self::Conjugate { hz, radius: r },
            RootPair::RealPair { root_a, root_b } => Self::RealPair { root_a, root_b },
            RootPair::Degenerate => Self::Degenerate,
        }
    }

    fn validate(&self, side: &str) -> Result<(), WorkstationError> {
        match self {
            Self::Conjugate { hz, radius } => {
                if !hz.is_finite()
                    || !radius.is_finite()
                    || *hz < 0.0
                    || *radius < 0.0
                    || *hz > STAGE_SR * 0.5
                    || *radius > 1.0
                {
                    return Err(invalid(format!(
                        "{side} conjugate geometry is outside the stored edit domain"
                    )));
                }
            }
            Self::RealPair { root_a, root_b } => {
                if !root_a.is_finite() || !root_b.is_finite() {
                    return Err(invalid(format!("{side} real-root geometry is nonfinite")));
                }
            }
            Self::Degenerate => {}
        }
        Ok(())
    }

    fn coefficients(&self, sample_rate_hz: f64) -> (f64, f64) {
        match self {
            Self::Conjugate { hz, radius } => {
                let angle = std::f64::consts::TAU * *hz / sample_rate_hz;
                (-2.0 * *radius * angle.cos(), *radius * *radius)
            }
            Self::RealPair { root_a, root_b } => (-(root_a + root_b), root_a * root_b),
            Self::Degenerate => (0.0, 0.0),
        }
    }

    fn to_root_pair(&self) -> RootPair {
        match self {
            Self::Conjugate { hz, radius } => RootPair::Conjugate {
                hz: *hz,
                r: *radius,
            },
            Self::RealPair { root_a, root_b } => RootPair::RealPair {
                root_a: *root_a,
                root_b: *root_b,
            },
            Self::Degenerate => RootPair::Degenerate,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct StageRecord {
    pub identity: bool,
    pub pole: RootGeometry,
    pub zero: RootGeometry,
    pub scale: f64,
    #[serde(rename = "packedWords")]
    pub packed_words: PackedStage,
    pub evidence: EvidenceReference,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source: Option<StageSourceReference>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub actor_provenance: Option<ActorProvenance>,
}

impl StageRecord {
    pub(crate) fn from_words(words: PackedStage, evidence: EvidenceReference) -> Self {
        let geometry = geometry_from_words(words);
        Self {
            identity: stage_words_to_biquad(words) == [1.0, 0.0, 0.0, 0.0, 0.0],
            pole: RootGeometry::from_root_pair(geometry.pole),
            zero: RootGeometry::from_root_pair(geometry.zero),
            scale: geometry.scale,
            packed_words: words,
            evidence,
            source: None,
            actor_provenance: None,
        }
    }

    pub(crate) fn from_source_words(
        words: PackedStage,
        evidence: EvidenceReference,
        source: StageSourceReference,
    ) -> Self {
        let mut stage = Self::from_words(words, evidence);
        stage.source = Some(source);
        stage
    }

    pub(crate) fn from_geometry(
        pole: RootGeometry,
        zero: RootGeometry,
        scale: f64,
        evidence: EvidenceReference,
    ) -> Result<Self, WorkstationError> {
        pole.validate("pole")?;
        zero.validate("zero")?;
        if !scale.is_finite() || !(0.0..=4.0).contains(&scale) {
            return Err(invalid("SCALE is outside 0..4"));
        }
        let expected_pole_is_conjugate = matches!(pole, RootGeometry::Conjugate { .. });
        let expected_zero_is_conjugate = matches!(zero, RootGeometry::Conjugate { .. });
        let words = words_from_geometry(&StageGeometry {
            pole: pole.to_root_pair(),
            zero: zero.to_root_pair(),
            scale,
        });
        let stage = Self::from_words(words, evidence);
        if expected_pole_is_conjugate != matches!(stage.pole, RootGeometry::Conjugate { .. })
            || expected_zero_is_conjugate != matches!(stage.zero, RootGeometry::Conjugate { .. })
        {
            return Err(invalid(
                "packed actor geometry changed root topology during quantisation",
            ));
        }
        Ok(stage)
    }

    pub fn runtime_coefficients(&self) -> [f64; NUM_COEFFS] {
        stage_words_to_biquad(self.packed_words)
    }

    fn validate(&self, corner: usize, lane: usize) -> Result<(), WorkstationError> {
        self.pole.validate("pole")?;
        self.zero.validate("zero")?;
        if !self.scale.is_finite() || !(0.0..=4.0).contains(&self.scale) {
            return Err(invalid(format!(
                "corner {corner} lane {lane} SCALE is outside 0..4"
            )));
        }
        let decoded_identity = self.runtime_coefficients() == [1.0, 0.0, 0.0, 0.0, 0.0];
        if decoded_identity != self.identity {
            return Err(invalid(format!(
                "corner {corner} lane {lane} identity flag disagrees with packed runtime"
            )));
        }
        let decoded = geometry_from_words(self.packed_words);
        let decoded_pole = RootGeometry::from_root_pair(decoded.pole);
        let decoded_zero = RootGeometry::from_root_pair(decoded.zero);
        if !root_geometry_matches(&self.pole, &decoded_pole)
            || !root_geometry_matches(&self.zero, &decoded_zero)
            || self.scale.to_bits() != decoded.scale.to_bits()
        {
            return Err(invalid(format!(
                "corner {corner} lane {lane} authored geometry disagrees with packed words: pole {:?} vs {:?}, zero {:?} vs {:?}, scale {:016X} vs {:016X}",
                self.pole,
                decoded_pole,
                self.zero,
                decoded_zero,
                self.scale.to_bits(),
                decoded.scale.to_bits()
            )));
        }
        Ok(())
    }

    fn snapshot(&self) -> StageSnapshot {
        StageSnapshot {
            identity: self.identity,
            pole: self.pole.clone(),
            zero: self.zero.clone(),
            scale: FieldReadout::scale(self.scale),
            packed_words: self.packed_words,
            runtime_coefficients: self.runtime_coefficients(),
            evidence: self.evidence.clone(),
            source: self.source.clone(),
            actor_provenance: self.actor_provenance.clone(),
        }
    }

    fn authored_biquad(&self) -> [f64; NUM_COEFFS] {
        let (pole_p, pole_q) = self.pole.coefficients(STAGE_SR);
        let (zero_p, zero_q) = self.zero.coefficients(STAGE_SR);
        [
            self.scale,
            self.scale * zero_p,
            self.scale * zero_q,
            pole_p,
            pole_q,
        ]
    }

    fn full_geometry_editable(&self) -> bool {
        self.source.is_none() && self.evidence.evidence_type == DIRECT_STAGE_EVIDENCE
    }
}

fn root_geometry_matches(authored: &RootGeometry, decoded: &RootGeometry) -> bool {
    let close = |left: f64, right: f64| {
        (left - right).abs() <= 1.0e-12 * left.abs().max(right.abs()).max(1.0)
    };
    match (authored, decoded) {
        (
            RootGeometry::Conjugate {
                hz: authored_hz,
                radius: authored_radius,
            },
            RootGeometry::Conjugate {
                hz: decoded_hz,
                radius: decoded_radius,
            },
        ) => close(*authored_hz, *decoded_hz) && close(*authored_radius, *decoded_radius),
        (
            RootGeometry::RealPair {
                root_a: authored_a,
                root_b: authored_b,
            },
            RootGeometry::RealPair {
                root_a: decoded_a,
                root_b: decoded_b,
            },
        ) => close(*authored_a, *decoded_a) && close(*authored_b, *decoded_b),
        (RootGeometry::Degenerate, RootGeometry::Degenerate) => true,
        _ => false,
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Pose {
    pub label: String,
    pub lanes: Vec<StageRecord>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Session {
    pub format: String,
    pub name: String,
    pub note: String,
    #[serde(rename = "authoringSampleRateHz")]
    pub authoring_sample_rate_hz: f64,
    pub corners: Vec<Pose>,
}

impl Session {
    pub fn from_body_bytes(
        name: impl Into<String>,
        note: impl Into<String>,
        bytes: &[u8],
        evidence: EvidenceReference,
    ) -> Result<Self, WorkstationError> {
        let packed =
            PackedCorners::from_body_bytes(bytes).map_err(|error| invalid(error.to_owned()))?;
        let corners = CORNER_LABELS
            .iter()
            .enumerate()
            .map(|(corner_index, label)| Pose {
                label: (*label).to_owned(),
                lanes: (0..NUM_STAGES)
                    .map(|lane_index| {
                        StageRecord::from_words(
                            packed.words[corner_index][lane_index],
                            evidence.clone(),
                        )
                    })
                    .collect(),
            })
            .collect();
        let session = Self {
            format: SESSION_FORMAT.to_owned(),
            name: name.into(),
            note: note.into(),
            authoring_sample_rate_hz: STAGE_SR,
            corners,
        };
        session.validate()?;
        Ok(session)
    }

    pub fn from_json(json: &str) -> Result<Self, WorkstationError> {
        let session: Self = serde_json::from_str(json)?;
        session.validate()?;
        Ok(session)
    }

    pub fn to_json(&self) -> Result<String, WorkstationError> {
        self.validate()?;
        Ok(serde_json::to_string_pretty(self)?)
    }

    pub fn to_body_bytes(&self) -> Result<[u8; BODY_BYTES], WorkstationError> {
        self.validate()?;
        let mut words = [[[0u16; NUM_COEFFS]; NUM_STAGES]; 4];
        for (corner_index, pose) in self.corners.iter().enumerate() {
            for (lane_index, stage) in pose.lanes.iter().enumerate() {
                words[corner_index][lane_index] = stage.packed_words;
            }
        }
        Ok(PackedCorners { words }.to_rom_bytes())
    }

    /// Audition one sacred registered lane through the same packed-runtime
    /// body contract. Every other section is the exact packed identity row;
    /// the selected lane keeps all four independently authored poses.
    pub fn stage_solo_body_bytes(
        &self,
        lane_index: usize,
    ) -> Result<[u8; BODY_BYTES], WorkstationError> {
        self.validate()?;
        if lane_index >= NUM_STAGES {
            return Err(invalid("stage-solo lane is out of range"));
        }
        let identity = words_from_roots(&StageRoots::IDENTITY);
        let mut words = [[identity; NUM_STAGES]; 4];
        for (corner_index, corner) in self.corners.iter().enumerate() {
            words[corner_index][lane_index] = corner.lanes[lane_index].packed_words;
        }
        Ok(PackedCorners { words }.to_rom_bytes())
    }

    pub fn to_cartridge_json(&self) -> Result<String, WorkstationError> {
        self.validate()?;
        let keyframes = self
            .corners
            .iter()
            .map(|pose| {
                serde_json::json!({
                    "label": pose.label,
                    "boost": 1.0,
                    "packedWords": pose.lanes.iter().map(|lane| lane.packed_words).collect::<Vec<_>>()
                })
            })
            .collect::<Vec<_>>();
        Ok(serde_json::to_string_pretty(&serde_json::json!({
            "format": "compiled-v1",
            "name": self.name,
            "sampleRate": self.authoring_sample_rate_hz,
            "keyframes": keyframes
        }))?)
    }

    pub fn validate(&self) -> Result<(), WorkstationError> {
        if self.format != SESSION_FORMAT {
            return Err(invalid(format!(
                "unsupported session format '{}'",
                self.format
            )));
        }
        if self.name.trim().is_empty() {
            return Err(invalid("session name is empty"));
        }
        if !self.authoring_sample_rate_hz.is_finite()
            || (self.authoring_sample_rate_hz - STAGE_SR).abs() > 1.0e-9
        {
            return Err(invalid(format!("authoring sample rate must be {STAGE_SR}")));
        }
        if self.corners.len() != CORNER_LABELS.len() {
            return Err(invalid("session must contain four corners"));
        }
        for (corner_index, (pose, expected)) in self.corners.iter().zip(CORNER_LABELS).enumerate() {
            if pose.label != expected {
                return Err(invalid(format!(
                    "corner {corner_index} is '{}', expected '{expected}'",
                    pose.label
                )));
            }
            if pose.lanes.len() != NUM_STAGES {
                return Err(invalid(format!(
                    "{expected} must contain {NUM_STAGES} registered lanes"
                )));
            }
            for (lane_index, lane) in pose.lanes.iter().enumerate() {
                lane.validate(corner_index, lane_index)?;
            }
        }
        Ok(())
    }

    pub fn cartridge_parity(&self) -> Result<bool, WorkstationError> {
        let body = self.to_body_bytes()?;
        let json = self.to_cartridge_json()?;
        let cartridge = Cartridge::from_json(&json).map_err(invalid)?;
        Ok(cartridge.packed.to_rom_bytes() == body)
    }

    pub fn edit(&self, request: &EditRequest) -> Result<EditResult, WorkstationError> {
        let before_body = self.to_body_bytes()?;
        let after = self.preview_edit(request)?;
        let after_body = after.to_body_bytes()?;
        let audit_before = SampledAudit::run(&before_body)?;
        let audit_after = SampledAudit::run(&after_body)?;
        let mut targets =
            Vec::with_capacity(request.corner_indices.len() * request.lane_indices.len());
        for &corner_index in &request.corner_indices {
            for &lane_index in &request.lane_indices {
                let before_stage = self.corners[corner_index].lanes[lane_index].clone();
                let after_stage = after.corners[corner_index].lanes[lane_index].clone();
                let (corner_morph, corner_q) = corner_position(corner_index)?;
                let before_probe = probe_body(&before_body, corner_morph, corner_q)?;
                let after_probe = probe_body(&after_body, corner_morph, corner_q)?;
                let before_row = before_probe.rows[lane_index];
                let after_row = after_probe.rows[lane_index];
                let grid = response_grid(DEFAULT_RESPONSE_BINS);
                let stage_before = curve_for_stage(before_row, &grid);
                let stage_after = curve_for_stage(after_row, &grid);
                let before_rows = before_probe.rows;
                let after_rows = after_probe.rows;
                let cascade_before = curve_for_cascade(&before_rows, &grid);
                let cascade_after = curve_for_cascade(&after_rows, &grid);
                let changed_words = changed_words(
                    corner_index,
                    &self.corners[corner_index].label,
                    lane_index,
                    before_stage.packed_words,
                    after_stage.packed_words,
                );
                let quantisation = quantisation_difference(&after_stage, after_row);
                targets.push(TargetEdit {
                    corner_index,
                    corner_label: self.corners[corner_index].label.clone(),
                    lane_index,
                    field: request.field,
                    authored_before: FieldReadout::for_field(&before_stage, request.field)?,
                    authored_after: FieldReadout::for_field(&after_stage, request.field)?,
                    before: before_stage.snapshot(),
                    after: after_stage.snapshot(),
                    changed_words,
                    quantisation,
                    stage_response: CurvePair {
                        before: stage_before,
                        after: stage_after,
                    },
                    cascade_response: CurvePair {
                        before: cascade_before,
                        after: cascade_after,
                    },
                });
            }
        }
        let changed = targets
            .iter()
            .flat_map(|target| target.changed_words.iter().cloned())
            .collect();
        Ok(EditResult {
            format: EDIT_FORMAT.to_owned(),
            request: request.clone(),
            before_body_sha256: sha256_hex(&before_body),
            after_body_sha256: sha256_hex(&after_body),
            targets,
            changed_words: changed,
            audit_before,
            audit_after,
            cartridge_parity_after: after.cartridge_parity()?,
            after_session: after,
        })
    }

    /// Build the exact packed edit candidate without sampled certification or
    /// response receipts. Pointer motion uses this path; `edit` is the commit
    /// path and must resolve the same request to the same body bytes.
    pub fn preview_edit(&self, request: &EditRequest) -> Result<Self, WorkstationError> {
        self.validate()?;
        request.validate(self)?;
        let mut after = self.clone();
        for &corner_index in &request.corner_indices {
            for &lane_index in &request.lane_indices {
                edit_stage(
                    &mut after.corners[corner_index].lanes[lane_index],
                    request.field,
                    request.value,
                    request.secondary_value,
                    request.relative,
                    corner_index,
                    lane_index,
                )?;
            }
        }
        after.validate()?;
        Ok(after)
    }

    pub fn screen(
        &self,
        selected_corner: usize,
        selected_lane: usize,
        morph: f64,
        q: f64,
    ) -> Result<ScreenData, WorkstationError> {
        let audit = SampledAudit::run(&self.to_body_bytes()?)?;
        self.screen_with_audit(selected_corner, selected_lane, morph, q, audit)
    }

    /// Construct packed-runtime plots with an audit already known to belong
    /// to this session. Selection/readout refreshes must not re-run the grid.
    pub fn screen_with_audit(
        &self,
        selected_corner: usize,
        selected_lane: usize,
        morph: f64,
        q: f64,
        audit: SampledAudit,
    ) -> Result<ScreenData, WorkstationError> {
        if selected_corner >= 4 || selected_lane >= NUM_STAGES {
            return Err(invalid("screen selection is out of range"));
        }
        let body = self.to_body_bytes()?;
        let probe = probe_body(&body, morph, q)?;
        let grid = response_grid(DEFAULT_RESPONSE_BINS);
        let mut corners = Vec::with_capacity(4);
        for corner_index in 0..4 {
            let (corner_morph, corner_q) = corner_position(corner_index)?;
            let corner_probe = probe_body(&body, corner_morph, corner_q)?;
            let corner_rows = corner_probe.rows;
            let mut lanes = Vec::with_capacity(NUM_STAGES);
            for lane_index in 0..NUM_STAGES {
                lanes.push(LaneView {
                    lane_index,
                    stage: self.corners[corner_index].lanes[lane_index].snapshot(),
                    response: curve_for_stage(corner_rows[lane_index], &grid),
                });
            }
            corners.push(CornerView {
                index: corner_index,
                label: self.corners[corner_index].label.clone(),
                response: curve_for_cascade(&corner_rows, &grid),
                lanes,
            });
        }
        Ok(ScreenData {
            format: SCREEN_FORMAT.to_owned(),
            name: self.name.clone(),
            selected_corner,
            selected_lane,
            morph,
            q,
            current_probe: probe.clone(),
            current_response: curve_for_cascade(&probe.rows, &grid),
            selected_stage: self.corners[selected_corner].lanes[selected_lane].snapshot(),
            corners,
            audit,
        })
    }
}

fn corner_position(corner_index: usize) -> Result<(f64, f64), WorkstationError> {
    match corner_index {
        0 => Ok((0.0, 0.0)),
        1 => Ok((1.0, 0.0)),
        2 => Ok((0.0, 1.0)),
        3 => Ok((1.0, 1.0)),
        _ => Err(invalid("corner index is out of range")),
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EditField {
    PoleHz,
    PoleRadius,
    PoleGeometry,
    PoleRootA,
    PoleRootB,
    ZeroHz,
    ZeroRadius,
    ZeroGeometry,
    ZeroRootA,
    ZeroRootB,
    Scale,
    Identity,
}

impl EditField {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::PoleHz => "pole_hz",
            Self::PoleRadius => "pole_radius",
            Self::PoleGeometry => "pole_geometry",
            Self::PoleRootA => "pole_root_a",
            Self::PoleRootB => "pole_root_b",
            Self::ZeroHz => "zero_hz",
            Self::ZeroRadius => "zero_radius",
            Self::ZeroGeometry => "zero_geometry",
            Self::ZeroRootA => "zero_root_a",
            Self::ZeroRootB => "zero_root_b",
            Self::Scale => "scale",
            Self::Identity => "identity",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EditRequest {
    #[serde(rename = "cornerIndices")]
    pub corner_indices: Vec<usize>,
    #[serde(rename = "laneIndices")]
    pub lane_indices: Vec<usize>,
    pub field: EditField,
    pub value: f64,
    #[serde(rename = "secondaryValue", skip_serializing_if = "Option::is_none")]
    pub secondary_value: Option<f64>,
    #[serde(default)]
    pub relative: bool,
}

impl EditRequest {
    pub fn single(corner: usize, lane: usize, field: EditField, value: f64) -> Self {
        Self {
            corner_indices: vec![corner],
            lane_indices: vec![lane],
            field,
            value,
            secondary_value: None,
            relative: false,
        }
    }

    pub fn conjugate(corners: Vec<usize>, lane: usize, pole: bool, hz: f64, radius: f64) -> Self {
        Self {
            corner_indices: corners,
            lane_indices: vec![lane],
            field: if pole {
                EditField::PoleGeometry
            } else {
                EditField::ZeroGeometry
            },
            value: hz,
            secondary_value: Some(radius),
            relative: false,
        }
    }

    pub fn relative_conjugate(
        lane: usize,
        pole: bool,
        octave_delta: f64,
        radius_delta: f64,
    ) -> Self {
        Self {
            corner_indices: vec![0, 1, 2, 3],
            lane_indices: vec![lane],
            field: if pole {
                EditField::PoleGeometry
            } else {
                EditField::ZeroGeometry
            },
            value: octave_delta,
            secondary_value: Some(radius_delta),
            relative: true,
        }
    }

    fn validate(&self, session: &Session) -> Result<(), WorkstationError> {
        if self.corner_indices.is_empty() || self.lane_indices.is_empty() {
            return Err(invalid("edit must name at least one corner and one lane"));
        }
        if !self.value.is_finite() {
            return Err(invalid("edit value is nonfinite"));
        }
        for (index, value) in self.corner_indices.iter().enumerate() {
            if self.corner_indices[..index].contains(value) || *value >= session.corners.len() {
                return Err(invalid("corner selection must be explicit and unique"));
            }
        }
        for (index, value) in self.lane_indices.iter().enumerate() {
            if self.lane_indices[..index].contains(value) || *value >= NUM_STAGES {
                return Err(invalid("lane selection must be explicit and unique"));
            }
        }
        if self.relative {
            if self.field == EditField::Identity {
                return Err(invalid("identity cannot be edited relatively"));
            }
            if !(-16.0..=16.0).contains(&self.value) {
                return Err(invalid(
                    "relative edit delta is outside its declared domain",
                ));
            }
            if matches!(
                self.field,
                EditField::PoleGeometry | EditField::ZeroGeometry
            ) {
                let radius_delta = self.secondary_value.ok_or_else(|| {
                    invalid("relative conjugate edit requires an explicit radius delta")
                })?;
                if !radius_delta.is_finite() || !(-1.0..=1.0).contains(&radius_delta) {
                    return Err(invalid("relative radius delta is outside -1..1"));
                }
            }
        } else {
            match self.field {
                EditField::PoleHz
                | EditField::PoleGeometry
                | EditField::ZeroHz
                | EditField::ZeroGeometry => {
                    if !(0.0..=STAGE_SR * 0.5).contains(&self.value) {
                        return Err(invalid("root frequency is outside 0..Nyquist"));
                    }
                    if matches!(
                        self.field,
                        EditField::PoleGeometry | EditField::ZeroGeometry
                    ) {
                        let radius = self.secondary_value.ok_or_else(|| {
                            invalid("conjugate root edit requires an explicit radius")
                        })?;
                        if !radius.is_finite() || !(0.0..=1.0).contains(&radius) {
                            return Err(invalid("root radius is outside 0..1"));
                        }
                    }
                }
                EditField::PoleRadius | EditField::ZeroRadius => {
                    if !(0.0..=1.0).contains(&self.value) {
                        return Err(invalid("root radius is outside 0..1"));
                    }
                }
                EditField::PoleRootA
                | EditField::PoleRootB
                | EditField::ZeroRootA
                | EditField::ZeroRootB => {
                    if !(-1.0..=1.0).contains(&self.value) {
                        return Err(invalid("real root is outside -1..1"));
                    }
                }
                EditField::Scale => {
                    if !(0.0..=4.0).contains(&self.value) {
                        return Err(invalid("SCALE is outside 0..4"));
                    }
                }
                EditField::Identity => {
                    if self.value != 0.0 && self.value != 1.0 {
                        return Err(invalid("identity control must be exactly 0 or 1"));
                    }
                    if self.value == 0.0 {
                        return Err(invalid(
                        "identity has no hidden geometry to restore; undo or author explicit roots",
                    ));
                    }
                }
            }
        }

        let requires_direct_authoring = matches!(
            self.field,
            EditField::PoleHz
                | EditField::PoleRadius
                | EditField::PoleGeometry
                | EditField::PoleRootA
                | EditField::PoleRootB
                | EditField::Scale
                | EditField::Identity
        );
        if requires_direct_authoring {
            for &corner in &self.corner_indices {
                for &lane in &self.lane_indices {
                    if !session.corners[corner].lanes[lane].full_geometry_editable() {
                        return Err(invalid(
                            "source/actor poles and SCALE are locked; use a direct clean-room stage session for full geometry edits",
                        ));
                    }
                }
            }
        }
        Ok(())
    }
}

fn edit_stage(
    stage: &mut StageRecord,
    field: EditField,
    mut value: f64,
    mut secondary_value: Option<f64>,
    relative: bool,
    corner: usize,
    lane: usize,
) -> Result<(), WorkstationError> {
    if relative {
        match field {
            EditField::PoleGeometry | EditField::ZeroGeometry => {
                let source = if field == EditField::PoleGeometry {
                    &stage.pole
                } else {
                    &stage.zero
                };
                let RootGeometry::Conjugate { hz, radius } = source else {
                    return Err(invalid(format!(
                        "relative conjugate edit refused for real/degenerate roots at corner {corner}, lane {lane}"
                    )));
                };
                value = *hz * 2.0_f64.powf(value);
                secondary_value = Some(
                    *radius
                        + secondary_value.ok_or_else(|| {
                            invalid("relative conjugate edit requires an explicit radius delta")
                        })?,
                );
                RootGeometry::Conjugate {
                    hz: value,
                    radius: secondary_value.unwrap(),
                }
                .validate(if field == EditField::PoleGeometry {
                    "pole"
                } else {
                    "zero"
                })?;
            }
            EditField::Scale => {
                value = stage.scale * 2.0_f64.powf(value);
                if !(0.0..=4.0).contains(&value) {
                    return Err(invalid("relative SCALE result is outside 0..4"));
                }
            }
            _ => {
                return Err(invalid(
                    "relative editing is defined for conjugate roots and SCALE",
                ));
            }
        }
    }

    if field == EditField::Identity {
        stage.packed_words = words_from_roots(&StageRoots::IDENTITY);
        canonicalize_stage(stage);
        return Ok(());
    }

    if field == EditField::Scale {
        let current = geometry_from_words(stage.packed_words);
        let candidate = words_from_geometry(&StageGeometry {
            pole: current.pole,
            zero: current.zero,
            scale: value,
        });
        stage.packed_words[4] = candidate[4];
        canonicalize_stage(stage);
        return Ok(());
    }

    if matches!(field, EditField::PoleGeometry | EditField::ZeroGeometry) {
        let root = RootGeometry::Conjugate {
            hz: value,
            radius: secondary_value
                .ok_or_else(|| invalid("conjugate root edit requires an explicit radius"))?,
        };
        let current = geometry_from_words(stage.packed_words);
        let candidate = words_from_geometry(&StageGeometry {
            pole: if field == EditField::PoleGeometry {
                root.to_root_pair()
            } else {
                current.pole
            },
            zero: if field == EditField::ZeroGeometry {
                root.to_root_pair()
            } else {
                current.zero
            },
            scale: current.scale,
        });
        let mut next = stage.packed_words;
        let (side, decoded) = if field == EditField::PoleGeometry {
            next[2] = candidate[2];
            next[3] = candidate[3];
            ("pole", geometry_from_words(next).pole)
        } else {
            next[0] = candidate[0];
            next[1] = candidate[1];
            ("zero", geometry_from_words(next).zero)
        };
        reject_topology_change(&root, decoded, side, corner, lane)?;
        stage.packed_words = next;
        canonicalize_stage(stage);
        return Ok(());
    }

    if matches!(
        field,
        EditField::PoleHz | EditField::PoleRadius | EditField::PoleRootA | EditField::PoleRootB
    ) {
        let next_pole = edited_root_geometry(&stage.pole, field, value, "pole", corner, lane)?;
        let current = geometry_from_words(stage.packed_words);
        let candidate = words_from_geometry(&StageGeometry {
            pole: next_pole.to_root_pair(),
            zero: current.zero,
            scale: current.scale,
        });
        let mut next = stage.packed_words;
        next[2] = candidate[2];
        next[3] = candidate[3];
        reject_topology_change(
            &next_pole,
            geometry_from_words(next).pole,
            "pole",
            corner,
            lane,
        )?;
        stage.packed_words = next;
        canonicalize_stage(stage);
        return Ok(());
    }

    let next_zero = match (&stage.zero, field) {
        (RootGeometry::Conjugate { hz: _, radius }, EditField::ZeroHz) => RootGeometry::Conjugate {
            hz: value,
            radius: *radius,
        },
        (RootGeometry::Conjugate { hz, radius: _ }, EditField::ZeroRadius) => {
            RootGeometry::Conjugate {
                hz: *hz,
                radius: value,
            }
        }
        (RootGeometry::Degenerate, EditField::ZeroHz) => RootGeometry::Conjugate {
            hz: value,
            radius: 0.0,
        },
        (RootGeometry::Degenerate, EditField::ZeroRadius) => RootGeometry::Conjugate {
            hz: 0.0,
            radius: value,
        },
        (RootGeometry::RealPair { root_a: _, root_b }, EditField::ZeroRootA) => {
            RootGeometry::RealPair {
                root_a: value,
                root_b: *root_b,
            }
        }
        (RootGeometry::RealPair { root_a, root_b: _ }, EditField::ZeroRootB) => {
            RootGeometry::RealPair {
                root_a: *root_a,
                root_b: value,
            }
        }
        (RootGeometry::Degenerate, EditField::ZeroRootA) => RootGeometry::RealPair {
            root_a: value,
            root_b: 0.0,
        },
        (RootGeometry::Degenerate, EditField::ZeroRootB) => RootGeometry::RealPair {
            root_a: 0.0,
            root_b: value,
        },
        (RootGeometry::RealPair { .. }, EditField::ZeroHz | EditField::ZeroRadius) => {
            return Err(invalid(format!(
                "real-root zero at corner {corner} lane {lane} requires explicit ROOT A / ROOT B editing"
            )));
        }
        (RootGeometry::Conjugate { .. }, EditField::ZeroRootA | EditField::ZeroRootB) => {
            return Err(invalid(format!(
                "conjugate zero at corner {corner} lane {lane} requires Hz / radius editing"
            )));
        }
        _ => return Err(invalid("unsupported zero edit")),
    };

    let current = geometry_from_words(stage.packed_words);
    let candidate = words_from_geometry(&StageGeometry {
        pole: current.pole,
        zero: next_zero.to_root_pair(),
        scale: current.scale,
    });
    let mut next = stage.packed_words;
    next[0] = candidate[0];
    next[1] = candidate[1];
    let decoded = geometry_from_words(next);
    reject_topology_change(&next_zero, decoded.zero, "zero", corner, lane)?;
    stage.packed_words = next;
    canonicalize_stage(stage);
    Ok(())
}

fn edited_root_geometry(
    root: &RootGeometry,
    field: EditField,
    value: f64,
    side: &str,
    corner: usize,
    lane: usize,
) -> Result<RootGeometry, WorkstationError> {
    let next = match (root, field) {
        (RootGeometry::Conjugate { radius, .. }, EditField::PoleHz)
        | (RootGeometry::Conjugate { radius, .. }, EditField::ZeroHz) => RootGeometry::Conjugate {
            hz: value,
            radius: *radius,
        },
        (RootGeometry::Conjugate { hz, .. }, EditField::PoleRadius)
        | (RootGeometry::Conjugate { hz, .. }, EditField::ZeroRadius) => RootGeometry::Conjugate {
            hz: *hz,
            radius: value,
        },
        (RootGeometry::RealPair { root_b, .. }, EditField::PoleRootA)
        | (RootGeometry::RealPair { root_b, .. }, EditField::ZeroRootA) => RootGeometry::RealPair {
            root_a: value,
            root_b: *root_b,
        },
        (RootGeometry::RealPair { root_a, .. }, EditField::PoleRootB)
        | (RootGeometry::RealPair { root_a, .. }, EditField::ZeroRootB) => RootGeometry::RealPair {
            root_a: *root_a,
            root_b: value,
        },
        (RootGeometry::Degenerate, EditField::PoleHz)
        | (RootGeometry::Degenerate, EditField::ZeroHz) => RootGeometry::Conjugate {
            hz: value,
            radius: 0.0,
        },
        (RootGeometry::Degenerate, EditField::PoleRadius)
        | (RootGeometry::Degenerate, EditField::ZeroRadius) => RootGeometry::Conjugate {
            hz: 0.0,
            radius: value,
        },
        (RootGeometry::Degenerate, EditField::PoleRootA)
        | (RootGeometry::Degenerate, EditField::ZeroRootA) => RootGeometry::RealPair {
            root_a: value,
            root_b: 0.0,
        },
        (RootGeometry::Degenerate, EditField::PoleRootB)
        | (RootGeometry::Degenerate, EditField::ZeroRootB) => RootGeometry::RealPair {
            root_a: 0.0,
            root_b: value,
        },
        (RootGeometry::RealPair { .. }, EditField::PoleHz | EditField::PoleRadius)
        | (RootGeometry::RealPair { .. }, EditField::ZeroHz | EditField::ZeroRadius) => {
            return Err(invalid(format!(
                "real-root {side} at corner {corner} lane {lane} requires explicit ROOT A / ROOT B editing"
            )));
        }
        (RootGeometry::Conjugate { .. }, EditField::PoleRootA | EditField::PoleRootB)
        | (RootGeometry::Conjugate { .. }, EditField::ZeroRootA | EditField::ZeroRootB) => {
            return Err(invalid(format!(
                "conjugate {side} at corner {corner} lane {lane} requires Hz / radius editing"
            )));
        }
        _ => return Err(invalid(format!("unsupported {side} edit"))),
    };
    Ok(next)
}

fn reject_topology_change(
    authored: &RootGeometry,
    decoded: RootPair,
    side: &str,
    corner: usize,
    lane: usize,
) -> Result<(), WorkstationError> {
    if matches!(authored, RootGeometry::Conjugate { .. })
        && matches!(decoded, RootPair::RealPair { .. })
    {
        return Err(invalid(format!(
            "edited {side} at corner {corner} lane {lane} quantised to a real-root row"
        )));
    }
    if matches!(authored, RootGeometry::RealPair { .. })
        && matches!(decoded, RootPair::Conjugate { .. })
    {
        return Err(invalid(format!(
            "edited real {side} at corner {corner} lane {lane} quantised to a conjugate row"
        )));
    }
    Ok(())
}

fn canonicalize_stage(stage: &mut StageRecord) {
    let decoded = geometry_from_words(stage.packed_words);
    stage.pole = RootGeometry::from_root_pair(decoded.pole);
    stage.zero = RootGeometry::from_root_pair(decoded.zero);
    stage.scale = decoded.scale;
    stage.identity = stage.runtime_coefficients() == [1.0, 0.0, 0.0, 0.0, 0.0];
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct FieldReadout {
    pub field: EditField,
    pub value: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub db: Option<f64>,
    pub display: String,
}

impl FieldReadout {
    fn scale(value: f64) -> Self {
        if value == 0.0 {
            return Self {
                field: EditField::Scale,
                value,
                db: None,
                display: "0 (explicit zero)".to_owned(),
            };
        }
        let db = 20.0 * value.log10();
        Self {
            field: EditField::Scale,
            value,
            db: Some(db),
            display: format!("{value:.6} ({db:.3} dB)"),
        }
    }

    fn for_field(stage: &StageRecord, field: EditField) -> Result<Self, WorkstationError> {
        let value = match field {
            EditField::PoleHz => control_value(&stage.pole, true)?,
            EditField::PoleRadius => control_value(&stage.pole, false)?,
            EditField::PoleGeometry => return Self::geometry(field, &stage.pole),
            EditField::PoleRootA => real_control_value(&stage.pole, true)?,
            EditField::PoleRootB => real_control_value(&stage.pole, false)?,
            EditField::ZeroHz => control_value(&stage.zero, true)?,
            EditField::ZeroRadius => control_value(&stage.zero, false)?,
            EditField::ZeroGeometry => return Self::geometry(field, &stage.zero),
            EditField::ZeroRootA => real_control_value(&stage.zero, true)?,
            EditField::ZeroRootB => real_control_value(&stage.zero, false)?,
            EditField::Scale => return Ok(Self::scale(stage.scale)),
            EditField::Identity => {
                let value = if stage.identity { 1.0 } else { 0.0 };
                return Ok(Self {
                    field,
                    value,
                    db: None,
                    display: if stage.identity { "IDENTITY" } else { "ACTIVE" }.to_owned(),
                });
            }
        };
        Ok(Self {
            field,
            value,
            db: None,
            display: format!("{value:.6}"),
        })
    }

    fn geometry(field: EditField, root: &RootGeometry) -> Result<Self, WorkstationError> {
        match root {
            RootGeometry::Conjugate { hz, radius } => Ok(Self {
                field,
                value: *hz,
                db: None,
                display: format!("{hz:.3} Hz / r {radius:.6}"),
            }),
            RootGeometry::Degenerate => Ok(Self {
                field,
                value: 0.0,
                db: None,
                display: "ORIGIN".to_owned(),
            }),
            RootGeometry::RealPair { .. } => {
                Err(invalid("real-root rows have no conjugate geometry control"))
            }
        }
    }
}

fn real_control_value(root: &RootGeometry, first: bool) -> Result<f64, WorkstationError> {
    match root {
        RootGeometry::RealPair { root_a, root_b } => Ok(if first { *root_a } else { *root_b }),
        RootGeometry::Degenerate => Ok(0.0),
        RootGeometry::Conjugate { .. } => Err(invalid(
            "conjugate rows have no independent real-root value",
        )),
    }
}

fn control_value(root: &RootGeometry, hz: bool) -> Result<f64, WorkstationError> {
    match root {
        RootGeometry::Conjugate { hz: value, radius } => Ok(if hz { *value } else { *radius }),
        RootGeometry::Degenerate => Ok(0.0),
        RootGeometry::RealPair { .. } => {
            Err(invalid("real-root rows have no conjugate control value"))
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct StageSnapshot {
    pub identity: bool,
    pub pole: RootGeometry,
    pub zero: RootGeometry,
    pub scale: FieldReadout,
    #[serde(rename = "packedWords")]
    pub packed_words: PackedStage,
    #[serde(rename = "runtimeCoefficients")]
    pub runtime_coefficients: [f64; NUM_COEFFS],
    pub evidence: EvidenceReference,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source: Option<StageSourceReference>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub actor_provenance: Option<ActorProvenance>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ChangedWord {
    pub corner_index: usize,
    pub corner_label: String,
    pub lane_index: usize,
    pub word_index: usize,
    pub before: u16,
    pub after: u16,
}

fn changed_words(
    corner_index: usize,
    corner_label: &str,
    lane_index: usize,
    before: PackedStage,
    after: PackedStage,
) -> Vec<ChangedWord> {
    (0..NUM_COEFFS)
        .filter_map(|word_index| {
            (before[word_index] != after[word_index]).then(|| ChangedWord {
                corner_index,
                corner_label: corner_label.to_owned(),
                lane_index,
                word_index,
                before: before[word_index],
                after: after[word_index],
            })
        })
        .collect()
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct QuantisationDifference {
    #[serde(rename = "runtimeMinusAuthored")]
    pub runtime_minus_authored: [f64; NUM_COEFFS],
    pub max_abs: f64,
}

fn quantisation_difference(
    stage: &StageRecord,
    runtime: [f64; NUM_COEFFS],
) -> QuantisationDifference {
    let authored = stage.authored_biquad();
    let mut diff = [0.0; NUM_COEFFS];
    for i in 0..NUM_COEFFS {
        diff[i] = runtime[i] - authored[i];
    }
    QuantisationDifference {
        runtime_minus_authored: diff,
        max_abs: diff.iter().map(|value| value.abs()).fold(0.0, f64::max),
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CurvePair {
    pub before: ResponseCurve,
    pub after: ResponseCurve,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TargetEdit {
    pub corner_index: usize,
    pub corner_label: String,
    pub lane_index: usize,
    pub field: EditField,
    #[serde(rename = "authoredBefore")]
    pub authored_before: FieldReadout,
    #[serde(rename = "authoredAfter")]
    pub authored_after: FieldReadout,
    pub before: StageSnapshot,
    pub after: StageSnapshot,
    pub changed_words: Vec<ChangedWord>,
    pub quantisation: QuantisationDifference,
    #[serde(rename = "stageResponse")]
    pub stage_response: CurvePair,
    #[serde(rename = "cascadeResponse")]
    pub cascade_response: CurvePair,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct EditResult {
    pub format: String,
    pub request: EditRequest,
    #[serde(rename = "beforeBodySha256")]
    pub before_body_sha256: String,
    #[serde(rename = "afterBodySha256")]
    pub after_body_sha256: String,
    pub targets: Vec<TargetEdit>,
    pub changed_words: Vec<ChangedWord>,
    #[serde(rename = "auditBefore")]
    pub audit_before: SampledAudit,
    #[serde(rename = "auditAfter")]
    pub audit_after: SampledAudit,
    #[serde(rename = "cartridgeParityAfter")]
    pub cartridge_parity_after: bool,
    #[serde(skip)]
    pub after_session: Session,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RuntimeProbe {
    pub morph: f64,
    pub q: f64,
    pub rows: [[f64; NUM_COEFFS]; NUM_STAGES],
    #[serde(rename = "maxPoleRadius")]
    pub max_pole_radius: f64,
    #[serde(rename = "unstableMask")]
    pub unstable_mask: u32,
    #[serde(rename = "nonfiniteMask")]
    pub nonfinite_mask: u32,
}

pub fn probe_body(bytes: &[u8], morph: f64, q: f64) -> Result<RuntimeProbe, WorkstationError> {
    if bytes.len() != BODY_BYTES {
        return Err(invalid("packed probe requires exactly 240 body bytes"));
    }
    let mut rows = [[0.0; NUM_COEFFS]; NUM_STAGES];
    let mut max_pole_radius = 0.0;
    let mut unstable_mask = 0u32;
    let mut nonfinite_mask = 0u32;
    let status = unsafe {
        trench_packed_probe(
            bytes.as_ptr(),
            bytes.len(),
            morph,
            q,
            rows.as_mut_ptr() as *mut f64,
            &mut max_pole_radius,
            &mut unstable_mask,
            &mut nonfinite_mask,
        )
    };
    if status != 0 {
        return Err(invalid(format!("trench_packed_probe returned {status}")));
    }
    Ok(RuntimeProbe {
        morph,
        q,
        rows,
        max_pole_radius,
        unstable_mask,
        nonfinite_mask,
    })
}

fn response_grid(points: usize) -> Vec<f64> {
    log_frequency_grid(20.0, (STAGE_SR * 0.5).min(16_000.0), points)
}

fn curve_for_stage(row: [f64; NUM_COEFFS], grid: &[f64]) -> ResponseCurve {
    ResponseCurve {
        sample_rate_hz: STAGE_SR,
        points: grid
            .iter()
            .map(|&freq_hz| ResponsePoint {
                freq_hz,
                db: biquad_stage_mag_db(&row, freq_hz, STAGE_SR),
            })
            .collect(),
    }
}

fn curve_for_cascade(rows: &[[f64; NUM_COEFFS]; NUM_STAGES], grid: &[f64]) -> ResponseCurve {
    ResponseCurve {
        sample_rate_hz: STAGE_SR,
        points: grid
            .iter()
            .map(|&freq_hz| ResponsePoint {
                freq_hz,
                db: biquad_cascade_mag_db(rows, freq_hz, STAGE_SR),
            })
            .collect(),
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AuditPosition {
    pub morph_index: usize,
    pub q_index: usize,
    pub morph: f64,
    pub q: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AuditCell {
    pub position: AuditPosition,
    pub finite: bool,
    pub stable: bool,
    #[serde(rename = "maxPoleRadius")]
    pub max_pole_radius: f64,
    #[serde(rename = "unstableMask")]
    pub unstable_mask: u32,
    #[serde(rename = "nonfiniteMask")]
    pub nonfinite_mask: u32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SampledAudit {
    pub format: String,
    pub contract: String,
    #[serde(rename = "morphPoints")]
    pub morph_points: usize,
    #[serde(rename = "qPoints")]
    pub q_points: usize,
    #[serde(rename = "responseBins")]
    pub response_bins: usize,
    #[serde(rename = "maximumPoleRadius")]
    pub maximum_pole_radius: f64,
    #[serde(rename = "unstableMask")]
    pub unstable_mask: Vec<bool>,
    #[serde(rename = "nonfiniteMask")]
    pub nonfinite_mask: Vec<bool>,
    #[serde(rename = "firstFailingPosition")]
    pub first_failing_position: Option<AuditPosition>,
    pub cells: Vec<AuditCell>,
    pub pass: bool,
    #[serde(rename = "certifyPass")]
    pub certify_pass: bool,
}

impl SampledAudit {
    pub fn run(bytes: &[u8]) -> Result<Self, WorkstationError> {
        let resolution = DEFAULT_AUDIT_RESOLUTION;
        let bins = DEFAULT_RESPONSE_BINS;
        let grid = response_grid(bins);
        let mut certify_pass = 0i32;
        let mut certify_max_radius = 0.0;
        let mut certify_fail_morph = -1.0;
        let mut certify_fail_q = -1.0;
        let certify_status = unsafe {
            trench_certify_body(
                bytes.as_ptr(),
                bytes.len(),
                resolution as u32,
                1.0,
                &mut certify_pass,
                &mut certify_max_radius,
                &mut certify_fail_morph,
                &mut certify_fail_q,
            )
        };
        if certify_status != 0 {
            return Err(invalid(format!(
                "trench_certify_body returned {certify_status}"
            )));
        }
        let mut cells = Vec::with_capacity(resolution * resolution);
        let mut unstable_mask = Vec::with_capacity(resolution * resolution);
        let mut nonfinite_mask = Vec::with_capacity(resolution * resolution);
        let mut maximum_pole_radius = 0.0;
        let mut first_failing_position = None;
        for q_index in 0..resolution {
            let q = q_index as f64 / (resolution - 1) as f64;
            for morph_index in 0..resolution {
                let morph = morph_index as f64 / (resolution - 1) as f64;
                let position = AuditPosition {
                    morph_index,
                    q_index,
                    morph,
                    q,
                };
                let probe = probe_body(bytes, morph, q)?;
                let response_finite = probe.rows.iter().all(|row| {
                    grid.iter().all(|&frequency_hz| {
                        biquad_stage_mag_db(row, frequency_hz, STAGE_SR).is_finite()
                    })
                });
                let finite = probe.nonfinite_mask == 0 && response_finite;
                let stable = finite && probe.unstable_mask == 0;
                let failed = !finite || !stable;
                if probe.max_pole_radius > maximum_pole_radius {
                    maximum_pole_radius = probe.max_pole_radius;
                }
                if failed && first_failing_position.is_none() {
                    first_failing_position = Some(position.clone());
                }
                cells.push(AuditCell {
                    position,
                    finite,
                    stable,
                    max_pole_radius: probe.max_pole_radius,
                    unstable_mask: probe.unstable_mask,
                    nonfinite_mask: probe.nonfinite_mask,
                });
                unstable_mask.push(!stable);
                nonfinite_mask.push(!finite);
            }
        }
        let pass =
            unstable_mask.iter().all(|value| !value) && nonfinite_mask.iter().all(|value| !value);
        if certify_pass != if pass { 1 } else { 0 } {
            return Err(invalid(format!(
                "packed probe audit disagrees with retained certify path: probe={pass} certify={certify_pass}"
            )));
        }
        if certify_pass == 0 && first_failing_position.is_none() {
            return Err(invalid(format!(
                "certify reported first failure at ({certify_fail_morph}, {certify_fail_q}) but probe masks were empty"
            )));
        }
        Ok(Self {
            format: AUDIT_FORMAT.to_owned(),
            contract: "sampled Morph x Q certification; not proof of every continuum point"
                .to_owned(),
            morph_points: resolution,
            q_points: resolution,
            response_bins: bins,
            maximum_pole_radius: maximum_pole_radius.max(certify_max_radius),
            unstable_mask,
            nonfinite_mask,
            first_failing_position,
            cells,
            pass,
            certify_pass: certify_pass == 1,
        })
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LaneView {
    pub lane_index: usize,
    pub stage: StageSnapshot,
    pub response: ResponseCurve,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CornerView {
    pub index: usize,
    pub label: String,
    pub response: ResponseCurve,
    pub lanes: Vec<LaneView>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ScreenData {
    pub format: String,
    pub name: String,
    #[serde(rename = "selectedCorner")]
    pub selected_corner: usize,
    #[serde(rename = "selectedLane")]
    pub selected_lane: usize,
    pub morph: f64,
    pub q: f64,
    #[serde(rename = "currentProbe")]
    pub current_probe: RuntimeProbe,
    #[serde(rename = "currentResponse")]
    pub current_response: ResponseCurve,
    #[serde(rename = "selectedStage")]
    pub selected_stage: StageSnapshot,
    pub corners: Vec<CornerView>,
    pub audit: SampledAudit,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AudioMode {
    BodySolo,
    Product,
}

impl AudioMode {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::BodySolo => "body_solo",
            Self::Product => "product",
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct AudioRender {
    pub mode: AudioMode,
    pub sample_rate: u32,
    pub input_peak: f32,
    pub output_peak: f32,
    pub output_rms: f32,
    pub normalized: bool,
    pub wav_bytes: Vec<u8>,
}

pub fn render_audio(session: &Session, mode: AudioMode) -> Result<AudioRender, WorkstationError> {
    let body = session.to_body_bytes()?;
    let cartridge =
        Cartridge::from_body_bytes("workstation-listen", &body, 1.0).map_err(invalid)?;
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
    let sample_rate = STAGE_SR as u32;
    let frames = sample_rate as usize / 2;
    let mut left = Vec::with_capacity(frames);
    let mut right = Vec::with_capacity(frames);
    for index in 0..frames {
        let t = index as f32 / sample_rate as f32;
        // Fixed source headroom, identical for both render modes. This is not
        // per-render normalization: the stimulus stays fixed and the raw
        // engine output must fit the PCM16 audition container without clipping.
        let sample = 0.08 * (std::f32::consts::TAU * 220.0 * t).sin()
            + 0.04 * (std::f32::consts::TAU * 880.0 * t).sin();
        left.push(sample);
        right.push(sample);
    }
    let input_peak = left.iter().map(|sample| sample.abs()).fold(0.0, f32::max);
    engine.process_block(&mut left, &mut right, 0.5, 0.5);
    let output_peak = left.iter().map(|sample| sample.abs()).fold(0.0, f32::max);
    let output_rms =
        (left.iter().map(|sample| sample * sample).sum::<f32>() / left.len() as f32).sqrt();
    let wav_bytes = wav_pcm16_mono(&left, sample_rate);
    Ok(AudioRender {
        mode,
        sample_rate,
        input_peak,
        output_peak,
        output_rms,
        normalized: false,
        wav_bytes,
    })
}

fn wav_pcm16_mono(samples: &[f32], sample_rate: u32) -> Vec<u8> {
    let data_len = samples.len() as u32 * 2;
    let mut bytes = Vec::with_capacity(44 + data_len as usize);
    bytes.extend_from_slice(b"RIFF");
    bytes.extend_from_slice(&(36 + data_len).to_le_bytes());
    bytes.extend_from_slice(b"WAVEfmt ");
    bytes.extend_from_slice(&16u32.to_le_bytes());
    bytes.extend_from_slice(&1u16.to_le_bytes());
    bytes.extend_from_slice(&1u16.to_le_bytes());
    bytes.extend_from_slice(&sample_rate.to_le_bytes());
    bytes.extend_from_slice(&(sample_rate * 2).to_le_bytes());
    bytes.extend_from_slice(&2u16.to_le_bytes());
    bytes.extend_from_slice(&16u16.to_le_bytes());
    bytes.extend_from_slice(b"data");
    bytes.extend_from_slice(&data_len.to_le_bytes());
    for sample in samples {
        let quantized = (sample.clamp(-1.0, 1.0) * 32767.0) as i16;
        bytes.extend_from_slice(&quantized.to_le_bytes());
    }
    bytes
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::hash::sha256_hex;

    fn repo_root() -> std::path::PathBuf {
        let source = std::path::Path::new(file!());
        if source.is_absolute() {
            return source.ancestors().nth(3).expect("repo root").to_path_buf();
        }
        std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .to_path_buf()
    }

    fn fixture(name: &str) -> [u8; BODY_BYTES] {
        let (_, bytes) = declared_fixture(repo_root(), name).unwrap();
        bytes.try_into().expect("declared 240-byte fixture")
    }

    fn evidence() -> EvidenceReference {
        EvidenceReference {
            external_repository_commit: "76309767a2e454f82fdcf8737d6d753c92482ad5".to_owned(),
            relative_path: "BRIEF_2026-07-10_night_run.md".to_owned(),
            file_sha256: "A5F74FEE3E248484DBC63292CBA34F703E5DFF42BA1BBF76155F6FA97BC35AC4".to_owned(),
            evidence_type: "synthetic-fixture-provenance".to_owned(),
            note: "Synthetic fixture only; external source is read-only provenance, not a runtime compiler.".to_owned(),
        }
    }

    fn direct_evidence() -> EvidenceReference {
        EvidenceReference {
            external_repository_commit: "not-applicable".to_owned(),
            relative_path: "embedded:test".to_owned(),
            file_sha256: "B".repeat(64),
            evidence_type: DIRECT_STAGE_EVIDENCE.to_owned(),
            note: "direct-stage test".to_owned(),
        }
    }

    fn identity_body() -> [u8; BODY_BYTES] {
        fixture("identity")
    }

    fn active_body() -> [u8; BODY_BYTES] {
        fixture("conjugate")
    }

    #[test]
    fn identity_is_exact() {
        let session =
            Session::from_body_bytes("identity", "test", &identity_body(), evidence()).unwrap();
        assert_eq!(
            session.corners[0].lanes[0].runtime_coefficients(),
            [1.0, 0.0, 0.0, 0.0, 0.0]
        );
    }

    #[test]
    fn one_edit_changes_only_selected_zero_words() {
        let session =
            Session::from_body_bytes("active", "test", &active_body(), evidence()).unwrap();
        let result = session
            .edit(&EditRequest::single(0, 0, EditField::ZeroHz, 1300.0))
            .unwrap();
        assert!(!result.changed_words.is_empty());
        assert!(result
            .changed_words
            .iter()
            .all(|word| word.word_index == 0 || word.word_index == 1));
        assert!(result.cartridge_parity_after);
        assert_eq!(
            result.targets[0].after.runtime_coefficients,
            probe_body(&result.after_session.to_body_bytes().unwrap(), 0.0, 0.0)
                .unwrap()
                .rows[0]
        );
    }

    #[test]
    fn direct_conjugate_handle_edit_is_atomic_and_declares_only_pole_words() {
        let session =
            Session::from_body_bytes("direct", "test", &active_body(), direct_evidence()).unwrap();
        let request = EditRequest::conjugate(vec![3], 4, true, 4_800.0, 0.965);
        let result = session.edit(&request).unwrap();
        assert!(!result.changed_words.is_empty());
        assert!(result.changed_words.iter().all(|word| {
            word.corner_index == 3
                && word.lane_index == 4
                && (word.word_index == 2 || word.word_index == 3)
        }));
        assert!(matches!(
            result.after_session.corners[3].lanes[4].pole,
            RootGeometry::Conjugate { .. }
        ));
        assert!(result.audit_after.pass && result.cartridge_parity_after);
    }

    #[test]
    fn relative_all_pose_edit_preserves_authored_root_relationships() {
        let mut session =
            Session::from_body_bytes("relative", "test", &active_body(), direct_evidence())
                .unwrap();
        for corner in 0..4 {
            session.corners[corner].lanes[0] = StageRecord::from_geometry(
                RootGeometry::Conjugate {
                    hz: 900.0 + corner as f64 * 430.0,
                    radius: 0.82 + corner as f64 * 0.02,
                },
                RootGeometry::Conjugate {
                    hz: 3_200.0 + corner as f64 * 380.0,
                    radius: 0.72 + corner as f64 * 0.015,
                },
                0.5,
                direct_evidence(),
            )
            .unwrap();
        }
        session.validate().unwrap();
        let before = session
            .corners
            .iter()
            .map(|corner| match corner.lanes[0].pole {
                RootGeometry::Conjugate { hz, radius } => (hz, radius),
                _ => panic!("fixture pole must remain conjugate"),
            })
            .collect::<Vec<_>>();
        let result = session
            .edit(&EditRequest::relative_conjugate(0, true, 0.25, 0.01))
            .unwrap();
        assert_eq!(result.targets.len(), 4);
        assert!(result.changed_words.iter().all(|word| {
            word.lane_index == 0 && (word.word_index == 2 || word.word_index == 3)
        }));
        for (corner_index, (before_hz, before_radius)) in before.into_iter().enumerate() {
            let RootGeometry::Conjugate { hz, radius } =
                result.after_session.corners[corner_index].lanes[0].pole
            else {
                panic!("relative edit changed root topology");
            };
            assert!(((hz / before_hz).log2() - 0.25).abs() < 0.002);
            assert!((radius - before_radius - 0.01).abs() < 0.0002);
        }
    }

    #[test]
    fn source_geometry_keeps_poles_and_scale_locked() {
        let session =
            Session::from_body_bytes("source", "test", &active_body(), evidence()).unwrap();
        assert!(session
            .edit(&EditRequest::conjugate(vec![0], 0, true, 900.0, 0.9))
            .is_err());
        assert!(session
            .edit(&EditRequest::single(0, 0, EditField::Scale, 0.8))
            .is_err());
        assert!(session
            .edit(&EditRequest::conjugate(vec![0], 0, false, 900.0, 0.9))
            .is_ok());
    }

    #[test]
    fn stage_solo_preserves_one_registered_lane_and_uses_exact_identity_elsewhere() {
        let session =
            Session::from_body_bytes("active", "test", &active_body(), evidence()).unwrap();
        let solo =
            PackedCorners::from_body_bytes(&session.stage_solo_body_bytes(2).unwrap()).unwrap();
        let full = PackedCorners::from_body_bytes(&session.to_body_bytes().unwrap()).unwrap();
        let identity = words_from_roots(&StageRoots::IDENTITY);
        for corner in 0..4 {
            for lane in 0..NUM_STAGES {
                assert_eq!(
                    solo.words[corner][lane],
                    if lane == 2 {
                        full.words[corner][lane]
                    } else {
                        identity
                    }
                );
            }
        }
    }

    #[test]
    fn real_root_is_refused() {
        let body = fixture("real-root");
        let session = Session::from_body_bytes("real", "test", &body, evidence()).unwrap();
        assert!(session.corners[0].lanes[0].zero.is_real());
        assert!(session
            .edit(&EditRequest::single(0, 0, EditField::ZeroHz, 900.0))
            .is_err());
    }

    #[test]
    fn sampled_audit_has_masks_and_resolution() {
        let audit = SampledAudit::run(&fixture("four-pose")).unwrap();
        assert_eq!(audit.morph_points, DEFAULT_AUDIT_RESOLUTION);
        assert_eq!(audit.q_points, DEFAULT_AUDIT_RESOLUTION);
        assert_eq!(
            audit.unstable_mask.len(),
            DEFAULT_AUDIT_RESOLUTION * DEFAULT_AUDIT_RESOLUTION
        );
        assert!(audit.pass);
        assert!(audit.first_failing_position.is_none());
    }

    #[test]
    fn audio_is_raw_and_modes_are_retained_engine_paths() {
        let session =
            Session::from_body_bytes("active", "test", &active_body(), evidence()).unwrap();
        let solo = render_audio(&session, AudioMode::BodySolo).unwrap();
        let product = render_audio(&session, AudioMode::Product).unwrap();
        assert!(!solo.normalized);
        assert!(!product.normalized);
        assert!(solo.output_peak.is_finite() && product.output_peak.is_finite());
        assert_ne!(solo.wav_bytes, product.wav_bytes);
    }

    #[test]
    fn body_and_cartridge_bytes_match() {
        let session =
            Session::from_body_bytes("active", "test", &active_body(), evidence()).unwrap();
        assert!(session.cartridge_parity().unwrap());
        assert_eq!(
            sha256_hex(&session.to_body_bytes().unwrap()),
            sha256_hex(&session.to_body_bytes().unwrap())
        );
    }

    #[test]
    fn every_declared_fixture_is_hashed_and_sized() {
        let manifest = declared_fixture_manifest(repo_root()).unwrap();
        assert_eq!(manifest.fixtures.len(), 5);
        for entry in manifest.fixtures {
            let (_, bytes) = declared_fixture(repo_root(), &entry.name).unwrap();
            assert_eq!(bytes.len(), 240);
            assert!(!entry.purpose.is_empty());
            assert!(!entry.expected_behavior.is_empty());
        }
    }

    #[test]
    fn identity_active_fixture_keeps_pose_state_explicit() {
        let session = Session::from_body_bytes(
            "identity-active",
            "test",
            &fixture("identity-active"),
            evidence(),
        )
        .unwrap();
        assert!(session.corners[0].lanes[0].identity);
        assert!(!session.corners[1].lanes[0].identity);
    }

    trait RootCheck {
        fn is_real(&self) -> bool;
    }

    impl RootCheck for RootGeometry {
        fn is_real(&self) -> bool {
            matches!(self, RootGeometry::RealPair { .. })
        }
    }
}
