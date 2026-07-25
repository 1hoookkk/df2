use crate::hash::sha256_hex;
use crate::model::{
    ChangedWord, EditField, EditRequest, RootGeometry, SampledAudit, Session, WorkstationError,
    CORNER_LABELS,
};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::Path;
use trench_core::cascade::{NUM_COEFFS, NUM_STAGES};
use trench_core::stage_law::STAGE_SR;

pub const RECIPE_INDEX_FORMAT: &str = "trench-workstation-recipe-index-v1";
pub const RECIPE_CATALOG_FORMAT: &str = "trench-workstation-recipe-catalog-v1";
pub const RECIPE_APPLICATION_FORMAT: &str = "trench-workstation-recipe-application-v1";
const PUBLISHED_CLOSURE_EPSILON: f64 = 1.5e-6;
const EXPECTED_EDGES: [(&str, &str, &str); 4] = [
    ("MORPH_AT_Q0", "M0_Q0", "M100_Q0"),
    ("MORPH_AT_Q100", "M0_Q100", "M100_Q100"),
    ("Q_AT_M0", "M0_Q0", "M0_Q100"),
    ("Q_AT_M100", "M100_Q0", "M100_Q100"),
];

#[derive(Debug, Clone, PartialEq, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RecipeIndex {
    pub format: String,
    pub contract: IndexContract,
    pub join: IndexJoin,
    pub recipes: Vec<Recipe>,
}

#[derive(Debug, Clone, PartialEq, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct IndexContract {
    pub study_evidence_only: bool,
    pub stage_correspondence_preserved: bool,
    pub recipe_does_not_supply_pole_scaffolds: bool,
    pub recipe_applies_to_frozen_poles_through_zero_only_authoring: bool,
    pub contains_packed_rows_or_words: bool,
    pub contains_absolute_reference_geometry: bool,
}

#[derive(Debug, Clone, PartialEq, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct IndexJoin {
    pub recipe_families: usize,
    pub observations_per_recipe: usize,
}

#[derive(Debug, Clone, PartialEq, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Recipe {
    pub recipe_id: String,
    pub observation_count: usize,
    pub lanes: Vec<RecipeLane>,
}

#[derive(Debug, Clone, PartialEq, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RecipeLane {
    pub lane: usize,
    pub topology_by_pose: MaybeRows<TopologyPose>,
    pub relative_movement: MaybeRows<MovementEdge>,
    pub zero_behavior_by_pose: MaybeRows<ZeroBehaviorPose>,
}

#[derive(Debug, Clone, PartialEq, Deserialize)]
#[serde(untagged)]
pub enum MaybeRows<T> {
    Rows(Vec<T>),
    Missing(String),
    Other(serde_json::Value),
}

#[derive(Debug, Clone, PartialEq, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TopologyPose {
    pub pose: String,
    pub pole: TopologySummary,
    pub zero: TopologySummary,
}

#[derive(Debug, Clone, PartialEq, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TopologySummary {
    pub mode: String,
    pub observed_counts: BTreeMap<String, usize>,
}

#[derive(Debug, Clone, PartialEq, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MovementEdge {
    pub edge: String,
    pub from_pose: String,
    pub to_pose: String,
    pub zero_octaves: NumericSummary,
    pub zero_radius_delta: NumericSummary,
}

#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct NumericSummary {
    pub median: f64,
    pub minimum: f64,
    pub maximum: f64,
    pub support: usize,
}

#[derive(Debug, Clone, PartialEq, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct OptionalNumericSummary {
    pub median: Option<f64>,
    pub minimum: Option<f64>,
    pub maximum: Option<f64>,
    pub support: usize,
}

#[derive(Debug, Clone, PartialEq, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ZeroBehaviorPose {
    pub pose: String,
    pub representative_zero_to_pole_octaves: OptionalNumericSummary,
    pub nearest_root_interval_octaves: OptionalNumericSummary,
    pub zero_minus_pole_radius: OptionalNumericSummary,
    pub remote_at_least_one_octave_rate: Option<f64>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RecipeIndexValidation {
    pub format: String,
    pub index_path: String,
    pub index_sha256: String,
    pub recipe_count: usize,
    pub lane_count: usize,
    pub accepted_lane_count: usize,
    pub rejected_lane_count: usize,
    pub rejected_by_reason: BTreeMap<String, usize>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PoseZeroTarget {
    pub corner_index: usize,
    pub corner_label: String,
    pub octave_delta_from_anchor: f64,
    pub radius_delta_from_anchor: f64,
    pub hz: f64,
    pub radius: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RecipeLaneCandidate {
    pub candidate_id: String,
    pub recipe_id: String,
    pub recipe_lane: usize,
    pub scaffold_lane_index: usize,
    pub observation_count: usize,
    pub closure_octaves_error: f64,
    pub closure_radius_error: f64,
    pub anchor_zero_to_pole_octaves: f64,
    pub anchor_zero_minus_pole_radius: f64,
    pub pose_zero_targets: Vec<PoseZeroTarget>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RecipeCatalog {
    pub format: String,
    pub validation: RecipeIndexValidation,
    pub candidates: Vec<RecipeLaneCandidate>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RecipeApplication {
    pub format: String,
    pub scaffold_name: String,
    pub candidate: RecipeLaneCandidate,
    pub anchor_zero_words_opened: bool,
    pub declared_zero_word_scope_only: bool,
    pub before_body_sha256: String,
    pub after_body_sha256: String,
    pub changed_words: Vec<ChangedWord>,
    pub cartridge_parity_after: bool,
    pub sampled_audit_after: SampledAudit,
    #[serde(skip)]
    pub after_session: Session,
}

impl RecipeIndex {
    pub fn load(repo_root: impl AsRef<Path>) -> Result<(Self, Vec<u8>), WorkstationError> {
        let path = repo_root
            .as_ref()
            .join("recipe-index")
            .join("recipe_index_v1.json");
        let bytes = fs::read(&path)?;
        let index: Self = serde_json::from_slice(&bytes)?;
        index.validate_top_level()?;
        Ok((index, bytes))
    }

    fn validate_top_level(&self) -> Result<(), WorkstationError> {
        if self.format != RECIPE_INDEX_FORMAT {
            return Err(invalid(format!(
                "unsupported recipe index format '{}'",
                self.format
            )));
        }
        if !self.contract.study_evidence_only
            || !self.contract.stage_correspondence_preserved
            || !self.contract.recipe_does_not_supply_pole_scaffolds
            || !self
                .contract
                .recipe_applies_to_frozen_poles_through_zero_only_authoring
            || self.contract.contains_packed_rows_or_words
            || self.contract.contains_absolute_reference_geometry
        {
            return Err(invalid(
                "recipe index contract is incompatible with zero-only authoring",
            ));
        }
        if self.join.recipe_families != self.recipes.len() || self.join.observations_per_recipe == 0
        {
            return Err(invalid(
                "recipe index join counts disagree with recipe rows",
            ));
        }
        let mut ids = BTreeSet::new();
        for recipe in &self.recipes {
            if !ids.insert(recipe.recipe_id.clone()) {
                return Err(invalid(format!(
                    "duplicate recipe id '{}'",
                    recipe.recipe_id
                )));
            }
            if recipe.observation_count != self.join.observations_per_recipe
                || recipe.lanes.len() != NUM_STAGES
            {
                return Err(invalid(format!(
                    "recipe '{}' has incomplete observation/lane structure",
                    recipe.recipe_id
                )));
            }
            let lanes = recipe
                .lanes
                .iter()
                .map(|lane| lane.lane)
                .collect::<BTreeSet<_>>();
            if lanes != (1..=NUM_STAGES).collect() {
                return Err(invalid(format!(
                    "recipe '{}' lane registration is incomplete",
                    recipe.recipe_id
                )));
            }
        }
        Ok(())
    }

    pub fn catalog(
        &self,
        index_path: impl AsRef<Path>,
        index_bytes: &[u8],
        scaffold: &Session,
    ) -> Result<RecipeCatalog, WorkstationError> {
        self.validate_top_level()?;
        scaffold.validate()?;
        let mut candidates = Vec::new();
        let mut rejected_by_reason = BTreeMap::new();
        for recipe in &self.recipes {
            for lane in &recipe.lanes {
                match candidate_for_lane(recipe, lane, scaffold) {
                    Ok(candidate) => candidates.push(candidate),
                    Err(reason) => *rejected_by_reason.entry(reason).or_insert(0) += 1,
                }
            }
        }
        candidates.sort_by(|a, b| a.candidate_id.cmp(&b.candidate_id));
        let lane_count = self.recipes.len() * NUM_STAGES;
        Ok(RecipeCatalog {
            format: RECIPE_CATALOG_FORMAT.to_owned(),
            validation: RecipeIndexValidation {
                format: RECIPE_INDEX_FORMAT.to_owned(),
                index_path: index_path.as_ref().display().to_string(),
                index_sha256: sha256_hex(index_bytes),
                recipe_count: self.recipes.len(),
                lane_count,
                accepted_lane_count: candidates.len(),
                rejected_lane_count: lane_count - candidates.len(),
                rejected_by_reason,
            },
            candidates,
        })
    }
}

pub fn apply_candidate(
    scaffold_name: &str,
    scaffold: &Session,
    candidate: &RecipeLaneCandidate,
) -> Result<RecipeApplication, WorkstationError> {
    scaffold.validate()?;
    if candidate.scaffold_lane_index >= NUM_STAGES
        || candidate.pose_zero_targets.len() != CORNER_LABELS.len()
    {
        return Err(invalid("recipe candidate target registration is invalid"));
    }
    let before_body = scaffold.to_body_bytes()?;
    let anchor_before = scaffold.corners[0].lanes[candidate.scaffold_lane_index].packed_words;
    let mut after = scaffold.clone();
    for target in &candidate.pose_zero_targets {
        if target.corner_index >= CORNER_LABELS.len()
            || target.corner_label != CORNER_LABELS[target.corner_index]
        {
            return Err(invalid("recipe target corner registration is invalid"));
        }
        after = after.preview_edit(&EditRequest::single(
            target.corner_index,
            candidate.scaffold_lane_index,
            EditField::ZeroHz,
            target.hz,
        ))?;
        after = after.preview_edit(&EditRequest::single(
            target.corner_index,
            candidate.scaffold_lane_index,
            EditField::ZeroRadius,
            target.radius,
        ))?;
    }
    let after_body = after.to_body_bytes()?;
    let changed_words = body_changed_words(scaffold, &after);
    let anchor_after = after.corners[0].lanes[candidate.scaffold_lane_index].packed_words;
    let anchor_zero_words_opened = anchor_before[..2] != anchor_after[..2]
        && anchor_after[..2] != anchor_after[2..=3];
    let declared_zero_word_scope_only = !changed_words.is_empty()
        && changed_words.iter().all(|word| {
            word.corner_index < CORNER_LABELS.len()
                && word.lane_index == candidate.scaffold_lane_index
                && word.word_index <= 1
        });
    if !anchor_zero_words_opened || !declared_zero_word_scope_only {
        return Err(invalid(
            "recipe application did not open the signed anchor or changed an undeclared packed word",
        ));
    }
    let sampled_audit_after = SampledAudit::run(&after_body)?;
    Ok(RecipeApplication {
        format: RECIPE_APPLICATION_FORMAT.to_owned(),
        scaffold_name: scaffold_name.to_owned(),
        candidate: candidate.clone(),
        anchor_zero_words_opened,
        declared_zero_word_scope_only,
        before_body_sha256: sha256_hex(&before_body),
        after_body_sha256: sha256_hex(&after_body),
        changed_words,
        cartridge_parity_after: after.cartridge_parity()?,
        sampled_audit_after,
        after_session: after,
    })
}

fn candidate_for_lane(
    recipe: &Recipe,
    lane: &RecipeLane,
    scaffold: &Session,
) -> Result<RecipeLaneCandidate, String> {
    if !(1..=NUM_STAGES).contains(&lane.lane) {
        return Err("invalid_lane_registration".to_owned());
    }
    let topology = match &lane.topology_by_pose {
        MaybeRows::Rows(rows) => rows,
        MaybeRows::Missing(_) | MaybeRows::Other(_) => return Err("missing_data".to_owned()),
    };
    let movements = match &lane.relative_movement {
        MaybeRows::Rows(rows) => rows,
        MaybeRows::Missing(_) | MaybeRows::Other(_) => return Err("missing_data".to_owned()),
    };
    if topology.len() != CORNER_LABELS.len() {
        return Err("missing_four_pose_topology".to_owned());
    }
    for (row, expected_pose) in topology.iter().zip(CORNER_LABELS) {
        if row.pose != expected_pose
            || row.pole.mode != "conjugate_pair"
            || row.pole.observed_counts.len() != 1
            || row.pole.observed_counts.get("conjugate_pair") != Some(&recipe.observation_count)
            || row.zero.mode != "conjugate_pair"
            || row.zero.observed_counts.len() != 1
            || row.zero.observed_counts.get("conjugate_pair") != Some(&recipe.observation_count)
        {
            return Err("topology_disagreement".to_owned());
        }
    }
    let scaffold_lane = lane.lane - 1;
    let (pole_hz, pole_radius) = match scaffold.corners[0].lanes[scaffold_lane].pole {
        RootGeometry::Conjugate { hz, radius } => (hz, radius),
        _ => return Err("scaffold_pole_topology_disagreement".to_owned()),
    };
    for corner in &scaffold.corners {
        if !matches!(corner.lanes[scaffold_lane].pole, RootGeometry::Conjugate { .. }) {
            return Err("scaffold_pole_topology_disagreement".to_owned());
        }
    }
    let zero_behavior = match &lane.zero_behavior_by_pose {
        MaybeRows::Rows(rows) => rows,
        MaybeRows::Missing(_) | MaybeRows::Other(_) => {
            return Err("missing_zero_behavior_evidence".to_owned())
        }
    };
    if zero_behavior.len() != CORNER_LABELS.len() {
        return Err("missing_four_pose_zero_behavior".to_owned());
    }
    for (row, expected_pose) in zero_behavior.iter().zip(CORNER_LABELS) {
        if row.pose != expected_pose {
            return Err("zero_behavior_pose_registration_disagreement".to_owned());
        }
        validate_optional_summary(&row.representative_zero_to_pole_octaves)?;
        validate_optional_summary(&row.nearest_root_interval_octaves)?;
        validate_optional_summary(&row.zero_minus_pole_radius)?;
        if let Some(rate) = row.remote_at_least_one_octave_rate {
            if !rate.is_finite() || !(0.0..=1.0).contains(&rate) {
                return Err("nonfinite_zero_behavior_rate".to_owned());
            }
        }
    }
    let anchor_behavior = &zero_behavior[0];
    let anchor_octaves = complete_optional_summary(
        &anchor_behavior.representative_zero_to_pole_octaves,
        recipe.observation_count,
    )?;
    let anchor_radius_delta = complete_optional_summary(
        &anchor_behavior.zero_minus_pole_radius,
        recipe.observation_count,
    )?;
    if movements.len() != EXPECTED_EDGES.len() {
        return Err("missing_edge_support".to_owned());
    }
    let mut edge_map = BTreeMap::new();
    for edge in movements {
        if edge_map.insert(edge.edge.as_str(), edge).is_some() {
            return Err("duplicate_edge".to_owned());
        }
    }
    for (edge_name, from_pose, to_pose) in EXPECTED_EDGES {
        let Some(edge) = edge_map.get(edge_name) else {
            return Err("missing_edge_support".to_owned());
        };
        if edge.from_pose != from_pose || edge.to_pose != to_pose {
            return Err("edge_registration_disagreement".to_owned());
        }
        if !summary_is_complete(&edge.zero_octaves, recipe.observation_count)
            || !summary_is_complete(&edge.zero_radius_delta, recipe.observation_count)
        {
            return Err("missing_edge_support".to_owned());
        }
    }
    let morph_q0 = edge_map["MORPH_AT_Q0"];
    let morph_q100 = edge_map["MORPH_AT_Q100"];
    let q_m0 = edge_map["Q_AT_M0"];
    let q_m100 = edge_map["Q_AT_M100"];
    let b_oct = morph_q0.zero_octaves.median;
    let c_oct = q_m0.zero_octaves.median;
    let d_oct = b_oct + q_m100.zero_octaves.median;
    let d_oct_other = c_oct + morph_q100.zero_octaves.median;
    let b_radius = morph_q0.zero_radius_delta.median;
    let c_radius = q_m0.zero_radius_delta.median;
    let d_radius = b_radius + q_m100.zero_radius_delta.median;
    let d_radius_other = c_radius + morph_q100.zero_radius_delta.median;
    let closure_octaves_error = (d_oct - d_oct_other).abs();
    let closure_radius_error = (d_radius - d_radius_other).abs();
    if closure_octaves_error > PUBLISHED_CLOSURE_EPSILON
        || closure_radius_error > PUBLISHED_CLOSURE_EPSILON
    {
        return Err("non_closing_edges".to_owned());
    }
    let deltas = [
        (anchor_octaves, anchor_radius_delta),
        (anchor_octaves + b_oct, anchor_radius_delta + b_radius),
        (anchor_octaves + c_oct, anchor_radius_delta + c_radius),
        (anchor_octaves + d_oct, anchor_radius_delta + d_radius),
    ];
    let mut pose_zero_targets = Vec::with_capacity(4);
    for (corner_index, ((octave_delta, radius_delta), label)) in
        deltas.into_iter().zip(CORNER_LABELS).enumerate()
    {
        let hz = pole_hz * 2.0_f64.powf(octave_delta);
        let radius = pole_radius + radius_delta;
        if !hz.is_finite()
            || !radius.is_finite()
            || !(0.0..=STAGE_SR * 0.5).contains(&hz)
            || !(0.0..=1.0).contains(&radius)
        {
            return Err("illegal_geometry".to_owned());
        }
        pose_zero_targets.push(PoseZeroTarget {
            corner_index,
            corner_label: label.to_owned(),
            octave_delta_from_anchor: octave_delta,
            radius_delta_from_anchor: radius_delta,
            hz,
            radius,
        });
    }
    Ok(RecipeLaneCandidate {
        candidate_id: format!("{}:L{}", recipe.recipe_id, lane.lane),
        recipe_id: recipe.recipe_id.clone(),
        recipe_lane: lane.lane,
        scaffold_lane_index: scaffold_lane,
        observation_count: recipe.observation_count,
        closure_octaves_error,
        closure_radius_error,
        anchor_zero_to_pole_octaves: anchor_octaves,
        anchor_zero_minus_pole_radius: anchor_radius_delta,
        pose_zero_targets,
    })
}

fn validate_optional_summary(summary: &OptionalNumericSummary) -> Result<(), String> {
    for value in [summary.median, summary.minimum, summary.maximum]
        .into_iter()
        .flatten()
    {
        if !value.is_finite() {
            return Err("nonfinite_zero_behavior_summary".to_owned());
        }
    }
    Ok(())
}

fn complete_optional_summary(
    summary: &OptionalNumericSummary,
    observation_count: usize,
) -> Result<f64, String> {
    if summary.support != observation_count {
        return Err("missing_zero_behavior_support".to_owned());
    }
    match (summary.median, summary.minimum, summary.maximum) {
        (Some(median), Some(minimum), Some(maximum))
            if median.is_finite() && minimum.is_finite() && maximum.is_finite() => Ok(median),
        _ => Err("missing_zero_behavior_value".to_owned()),
    }
}

fn summary_is_complete(summary: &NumericSummary, observation_count: usize) -> bool {
    summary.support == observation_count
        && summary.median.is_finite()
        && summary.minimum.is_finite()
        && summary.maximum.is_finite()
        && summary.minimum <= summary.median
        && summary.median <= summary.maximum
}

fn body_changed_words(before: &Session, after: &Session) -> Vec<ChangedWord> {
    let mut receipt = Vec::new();
    for corner_index in 0..CORNER_LABELS.len() {
        for lane_index in 0..NUM_STAGES {
            let before_words = before.corners[corner_index].lanes[lane_index].packed_words;
            let after_words = after.corners[corner_index].lanes[lane_index].packed_words;
            for word_index in 0..NUM_COEFFS {
                if before_words[word_index] != after_words[word_index] {
                    receipt.push(ChangedWord {
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
    receipt
}

fn invalid(message: impl Into<String>) -> WorkstationError {
    WorkstationError(message.into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{declared_fixture, EvidenceReference};

    fn repo_root() -> std::path::PathBuf {
        let source = Path::new(file!());
        if source.is_absolute() {
            return source
                .ancestors()
                .nth(3)
                .expect("repository root")
                .to_path_buf();
        }
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .to_path_buf()
    }

    fn scaffold() -> Session {
        let (_, bytes) = declared_fixture(repo_root(), "four-pose").unwrap();
        Session::from_body_bytes(
            "four-pose",
            "recipe test",
            &bytes,
            EvidenceReference {
                external_repository_commit: "none".to_owned(),
                relative_path: "fixtures/four-pose.body240".to_owned(),
                file_sha256: sha256_hex(&bytes),
                evidence_type: "synthetic-clean-room-fixture".to_owned(),
                note: "test".to_owned(),
            },
        )
        .unwrap()
    }

    #[test]
    fn index_loads_and_exposes_a_strictly_eligible_candidate() {
        let root = repo_root();
        let (index, bytes) = RecipeIndex::load(&root).unwrap();
        let catalog = index
            .catalog(
                root.join("recipe-index/recipe_index_v1.json"),
                &bytes,
                &scaffold(),
            )
            .unwrap();
        assert_eq!(catalog.validation.recipe_count, 33);
        let candidate = catalog.candidates.first().unwrap();
        assert_eq!(candidate.pose_zero_targets.len(), 4);
        assert!(candidate.anchor_zero_to_pole_octaves.is_finite());
        assert!(candidate.anchor_zero_minus_pole_radius.is_finite());
        assert!(candidate.closure_octaves_error <= PUBLISHED_CLOSURE_EPSILON);
    }

    #[test]
    fn recipe_application_authors_signed_anchor_and_changes_only_declared_zero_words() {
        let root = repo_root();
        let (index, bytes) = RecipeIndex::load(&root).unwrap();
        let source = scaffold();
        let catalog = index
            .catalog(
                root.join("recipe-index/recipe_index_v1.json"),
                &bytes,
                &source,
            )
            .unwrap();
        let candidate = catalog.candidates.first().unwrap();
        let result = apply_candidate("four-pose", &source, candidate).unwrap();
        assert!(result.anchor_zero_words_opened);
        assert!(result.declared_zero_word_scope_only);
        assert!(result.cartridge_parity_after);
        assert!(result.changed_words.iter().all(|word| {
            word.corner_index < 4
                && word.lane_index == candidate.scaffold_lane_index
                && word.word_index <= 1
        }));
    }

    #[test]
    fn legal_multi_octave_motion_is_not_distance_limited() {
        let root = repo_root();
        let (index, _) = RecipeIndex::load(&root).unwrap();
        let mut source = scaffold();
        let recipe = index
            .recipes
            .iter()
            .find(|recipe| recipe.recipe_id == "R003")
            .unwrap();
        let mut lane = recipe
            .lanes
            .iter()
            .find(|lane| lane.lane == 6)
            .unwrap()
            .clone();

        for corner in &mut source.corners {
            corner.lanes[5].pole = RootGeometry::Conjugate {
                hz: 20.0,
                radius: 0.30,
            };
            corner.lanes[5].zero = RootGeometry::Conjugate {
                hz: 20.0,
                radius: 0.30,
            };
        }
        if let MaybeRows::Rows(rows) = &mut lane.relative_movement {
            for edge in rows {
                let octave_delta = if edge.edge.starts_with("MORPH_") {
                    9.0
                } else {
                    0.0
                };
                edge.zero_octaves.median = octave_delta;
                edge.zero_octaves.minimum = octave_delta;
                edge.zero_octaves.maximum = octave_delta;
                edge.zero_radius_delta.median = 0.0;
                edge.zero_radius_delta.minimum = 0.0;
                edge.zero_radius_delta.maximum = 0.0;
            }
        }

        let candidate = candidate_for_lane(recipe, &lane, &source).unwrap();
        assert_eq!(
            candidate.pose_zero_targets[1].octave_delta_from_anchor,
            candidate.anchor_zero_to_pole_octaves + 9.0
        );
        assert_eq!(
            candidate.pose_zero_targets[1].hz,
            20.0 * 2.0_f64.powf(candidate.anchor_zero_to_pole_octaves + 9.0)
        );
        assert_eq!(
            candidate.pose_zero_targets[3].octave_delta_from_anchor,
            candidate.anchor_zero_to_pole_octaves + 9.0
        );
        assert_eq!(
            candidate.pose_zero_targets[3].hz,
            20.0 * 2.0_f64.powf(candidate.anchor_zero_to_pole_octaves + 9.0)
        );
    }

    #[test]
    fn missing_topology_nonclosing_edges_and_illegal_geometry_are_rejected() {
        let root = repo_root();
        let (index, _) = RecipeIndex::load(&root).unwrap();
        let source = scaffold();
        let recipe = index
            .recipes
            .iter()
            .find(|recipe| recipe.recipe_id == "R003")
            .unwrap();
        let lane = recipe.lanes.iter().find(|lane| lane.lane == 6).unwrap();

        let mut missing = lane.clone();
        missing.relative_movement = MaybeRows::Missing("   ".to_owned());
        assert_eq!(
            candidate_for_lane(recipe, &missing, &source).unwrap_err(),
            "missing_data"
        );

        let mut topology = lane.clone();
        if let MaybeRows::Rows(rows) = &mut topology.topology_by_pose {
            rows[1].zero.mode = "independent_real_pair".to_owned();
        }
        assert_eq!(
            candidate_for_lane(recipe, &topology, &source).unwrap_err(),
            "topology_disagreement"
        );

        let mut nonclosing = lane.clone();
        if let MaybeRows::Rows(rows) = &mut nonclosing.relative_movement {
            rows[0].zero_octaves.median += 0.25;
            rows[0].zero_octaves.maximum += 0.25;
        }
        assert_eq!(
            candidate_for_lane(recipe, &nonclosing, &source).unwrap_err(),
            "non_closing_edges"
        );

        let mut illegal = lane.clone();
        if let MaybeRows::Rows(rows) = &mut illegal.relative_movement {
            rows[0].zero_octaves.median = 20.0;
            rows[0].zero_octaves.minimum = 20.0;
            rows[0].zero_octaves.maximum = 20.0;
            rows[1].zero_octaves.median = 0.0;
            rows[1].zero_octaves.minimum = 0.0;
            rows[1].zero_octaves.maximum = 0.0;
            rows[2].zero_octaves.median = 0.0;
            rows[2].zero_octaves.minimum = 0.0;
            rows[2].zero_octaves.maximum = 0.0;
            rows[3].zero_octaves.median = -20.0;
            rows[3].zero_octaves.minimum = -20.0;
            rows[3].zero_octaves.maximum = -20.0;
        }
        assert_eq!(
            candidate_for_lane(recipe, &illegal, &source).unwrap_err(),
            "illegal_geometry"
        );
    }
}
