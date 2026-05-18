//! Cluster topology for cascade body authoring.
//!
//! Ported from `archive/pre-runtime/trench-forge/src/cluster.rs:10-95`
//! (pure data types only; the `compile()` + `FourCornerTopology` solver
//! paths remain in the archive until their dependencies `SkeletonPlan`,
//! `RelativeZero`, and `StageTarget` are also ported).
//!
//! A `ClusterPlan` groups stages into spectral clusters, each with a
//! frequency band and a list of `ClusterStage`s. Each stage carries a
//! `StageFunction` role (`Anchor`/`Relief`/`Interference`/`Bypass`).
//! `InterferenceLink` encodes explicit cross-stage coupling between two
//! stages — the relationship, not a unary label — which is the primitive
//! that produces comb-like texture from closely-spaced poles with
//! opposite σ offsets.
//!
//! This is the cross-stage coordination vocabulary. The forge scorer
//! treats the cascade as a black box and cannot see it. Once these types
//! are in `trench-core`, downstream solvers can be ported against them.

use serde::{Deserialize, Serialize};

/// Functional role of a stage within a cluster.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum StageFunction {
    /// Carries a formant peak. `η ≈ 1`, small `σ`.
    Anchor,
    /// Shaves excess energy. Modest inward `η`, gap-directed `σ`.
    Relief,
    /// Asymmetry/bite between close poles. `η ≈ 1`, opposite `±σ` on
    /// paired stages.
    Interference,
    /// Inactive / passthrough.
    Bypass,
}

/// One stage within a cluster.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClusterStage {
    pub pole_freq_hz: f64,
    pub pole_r: f64,
    pub function: StageFunction,
}

/// A spectral cluster: 1–4 stages grouped by frequency region.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Cluster {
    /// Frequency bounds `(lo_hz, hi_hz)` for this cluster's region.
    pub band: (f64, f64),
    pub stages: Vec<ClusterStage>,
}

/// Explicit interference pairing between two stages.
///
/// Interference is a relationship, not a unary label. The two stages
/// create comb-like texture through closely-spaced poles with opposite
/// `σ` offsets.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InterferenceLink {
    /// Skeleton index of the first stage in the pair.
    pub a: usize,
    /// Skeleton index of the second stage in the pair.
    pub b: usize,
    /// Sign convention: `+1` means `a` gets `+σ`, `b` gets `-σ`. `-1`
    /// inverts.
    pub sign: i8,
    /// Strength: controls the magnitude of `σ` offset (`0.0–1.0`).
    pub strength: f64,
}

/// Complete cluster plan for a cascade body.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClusterPlan {
    pub clusters: Vec<Cluster>,
    /// Explicit interference pairings (skeleton indices resolved at
    /// compile time).
    pub interference_links: Vec<InterferenceLink>,
}

impl ClusterPlan {
    /// Total active (non-`Bypass`) stages across all clusters.
    pub fn active_count(&self) -> usize {
        self.clusters
            .iter()
            .flat_map(|c| &c.stages)
            .filter(|s| s.function != StageFunction::Bypass)
            .count()
    }

    /// Count of subordinate stages (`Relief` + `Bypass`).
    pub fn subordinate_count(&self) -> usize {
        self.clusters
            .iter()
            .flat_map(|c| &c.stages)
            .filter(|s| matches!(s.function, StageFunction::Relief | StageFunction::Bypass))
            .count()
    }

    /// Total stage count across all clusters.
    pub fn total_stages(&self) -> usize {
        self.clusters.iter().map(|c| c.stages.len()).sum()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_plan() -> ClusterPlan {
        ClusterPlan {
            clusters: vec![
                Cluster {
                    band: (80.0, 200.0),
                    stages: vec![ClusterStage {
                        pole_freq_hz: 120.0,
                        pole_r: 0.94,
                        function: StageFunction::Anchor,
                    }],
                },
                Cluster {
                    band: (500.0, 1500.0),
                    stages: vec![
                        ClusterStage {
                            pole_freq_hz: 700.0,
                            pole_r: 0.96,
                            function: StageFunction::Anchor,
                        },
                        ClusterStage {
                            pole_freq_hz: 820.0,
                            pole_r: 0.96,
                            function: StageFunction::Interference,
                        },
                    ],
                },
                Cluster {
                    band: (3000.0, 8000.0),
                    stages: vec![
                        ClusterStage {
                            pole_freq_hz: 4200.0,
                            pole_r: 0.91,
                            function: StageFunction::Relief,
                        },
                        ClusterStage {
                            pole_freq_hz: 6000.0,
                            pole_r: 0.88,
                            function: StageFunction::Bypass,
                        },
                    ],
                },
            ],
            interference_links: vec![InterferenceLink {
                a: 1,
                b: 2,
                sign: 1,
                strength: 0.65,
            }],
        }
    }

    #[test]
    fn active_count_excludes_bypass() {
        let plan = sample_plan();
        // 1 Anchor + 1 Anchor + 1 Interference + 1 Relief + 0 Bypass = 4
        assert_eq!(plan.active_count(), 4);
    }

    #[test]
    fn subordinate_count_matches_relief_plus_bypass() {
        let plan = sample_plan();
        // 1 Relief + 1 Bypass = 2
        assert_eq!(plan.subordinate_count(), 2);
    }

    #[test]
    fn total_stages_sums_all_cluster_stages() {
        let plan = sample_plan();
        // 1 + 2 + 2 = 5
        assert_eq!(plan.total_stages(), 5);
    }

    #[test]
    fn interference_link_carries_sign_and_strength() {
        let plan = sample_plan();
        assert_eq!(plan.interference_links.len(), 1);
        let link = &plan.interference_links[0];
        assert_eq!(link.a, 1);
        assert_eq!(link.b, 2);
        assert_eq!(link.sign, 1);
        assert!((link.strength - 0.65).abs() < 1e-9);
    }

    #[test]
    fn cluster_plan_serde_roundtrip() {
        let plan = sample_plan();
        let json = serde_json::to_string(&plan).unwrap();
        let back: ClusterPlan = serde_json::from_str(&json).unwrap();
        assert_eq!(back.active_count(), plan.active_count());
        assert_eq!(back.total_stages(), plan.total_stages());
        assert_eq!(back.interference_links.len(), plan.interference_links.len());
        assert!(matches!(
            back.clusters[1].stages[1].function,
            StageFunction::Interference
        ));
    }

    #[test]
    fn stage_function_equality_and_matching() {
        assert_eq!(StageFunction::Anchor, StageFunction::Anchor);
        assert_ne!(StageFunction::Anchor, StageFunction::Bypass);
        assert!(matches!(
            StageFunction::Interference,
            StageFunction::Interference
        ));
    }
}
