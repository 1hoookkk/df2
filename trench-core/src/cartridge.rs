use crate::cascade::{NUM_COEFFS, NUM_STAGES};
use crate::emu_resonator::{emu_resonator, EmuResonatorParams};
use crate::minifloat::{stage_words_to_biquad, PackedCorners, PackedStage};
use serde::Deserialize;

/// Exact body container size: 4 corners × 6 stages × 5 u16 words × 2 bytes.
pub use crate::minifloat::BODY_BYTES;

/// Optional drive-stage config (preceding cascade).
#[derive(Debug, Clone, Deserialize)]
pub struct DriveBlock {
    #[serde(rename = "input_gain_dB", default)]
    pub input_gain_db: f32,
    #[serde(default = "default_mackie_model")]
    pub model: String,
}

fn default_mackie_model() -> String {
    "mackie_1202".to_string()
}

impl Default for DriveBlock {
    fn default() -> Self {
        Self {
            input_gain_db: 0.0,
            model: default_mackie_model(),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct FnSegment {
    pub level: f32,
    pub time_ms: f32,
    pub shape: String,
    #[serde(default)]
    pub jump: Option<i32>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ModFnBlock {
    pub segments: Vec<FnSegment>,
    #[serde(rename = "key-sync", default)]
    pub key_sync_int: i32,
    #[serde(rename = "tempo-sync", default)]
    pub tempo_sync_int: i32,
}

impl ModFnBlock {
    pub fn key_sync(&self) -> bool {
        self.key_sync_int != 0
    }
    pub fn tempo_sync(&self) -> bool {
        self.tempo_sync_int != 0
    }
}

pub type LawCoeffs6 = [f32; 6];
pub type BandLawCoeffs12 = [f32; 12];

#[derive(Debug, Clone, Deserialize)]
pub struct BandChannelCoeffs {
    pub low: BandLawCoeffs12,
    pub mid: BandLawCoeffs12,
    pub high: BandLawCoeffs12,
}

#[derive(Debug, Clone, Deserialize)]
pub struct BandCoeffs {
    pub l: BandChannelCoeffs,
    pub r: BandChannelCoeffs,
}

#[derive(Debug, Clone, Deserialize)]
pub struct SpatialProfile {
    pub azimuth: f32,
    pub distance: f32,
    pub elevation: f32,
    pub itd_coeffs: LawCoeffs6,
    pub ild_coeffs: LawCoeffs6,
    pub band_coeffs: BandCoeffs,
}

pub const NUM_CORNERS: usize = 4;
pub type CornerData = [[f64; NUM_COEFFS]; NUM_STAGES];

// ── formats ──

#[derive(Deserialize)]
struct RawStage {
    a1: f32,
    r: f32,
    val1: f32,
    val2: f32,
    val3: f32,
}

#[derive(Deserialize)]
struct KeyframeJson {
    label: String,
    #[serde(default = "default_boost")]
    boost: f64,
    #[serde(default)]
    stages: Vec<serde_json::Value>,
    #[serde(default, rename = "packedWords")]
    packed_words: Vec<PackedStage>,
}

fn default_boost() -> f64 {
    1.0
}

#[derive(Deserialize)]
struct CartridgeJson {
    name: String,
    #[serde(default = "default_sample_rate")]
    #[serde(rename = "sampleRate")]
    sample_rate: f64,
    keyframes: Vec<KeyframeJson>,
    #[serde(default)]
    drive: Option<DriveBlock>,
    #[serde(default, rename = "spatial_profile")]
    spatial_profile: Option<SpatialProfile>,
    #[serde(default, rename = "mod_fn")]
    mod_fn: Option<ModFnBlock>,
}

fn default_sample_rate() -> f64 {
    39062.5
}

#[derive(Clone, Debug)]
pub struct Cartridge {
    pub name: String,
    pub corners: [CornerData; NUM_CORNERS],
    pub boosts: [f64; NUM_CORNERS],
    pub packed: Option<PackedCorners>,
    pub drive: DriveBlock,
    pub spatial_profile: Option<SpatialProfile>,
    pub mod_fn: Option<ModFnBlock>,
}

impl Cartridge {
    pub fn hedz_rom() -> Self {
        Self {
            name: crate::hedz_rom::HEDZ_NAME.to_string(),
            corners: crate::hedz_rom::HEDZ_CORNERS,
            boosts: crate::hedz_rom::HEDZ_BOOSTS,
            packed: None,
            drive: DriveBlock::default(),
            spatial_profile: None,
            mod_fn: None,
        }
    }

    /// Canonical assembler: build a cartridge from a decoded packed corner bank.
    ///
    /// This is the single coefficient path. The runtime direct DF2T fallback
    /// rows (`corners`) are derived from the packed words here so they can never
    /// disagree with `packed`; `packed` stays the interpolation authority.
    fn from_packed(
        name: String,
        packed: PackedCorners,
        boosts: [f64; NUM_CORNERS],
        drive: DriveBlock,
        spatial_profile: Option<SpatialProfile>,
        mod_fn: Option<ModFnBlock>,
    ) -> Self {
        let mut corners = [[[0.0; NUM_COEFFS]; NUM_STAGES]; NUM_CORNERS];
        for ci in 0..NUM_CORNERS {
            for si in 0..NUM_STAGES {
                corners[ci][si] = stage_words_to_biquad(packed.words[ci][si]);
            }
        }
        Self {
            name,
            corners,
            boosts,
            packed: Some(packed),
            drive,
            spatial_profile,
            mod_fn,
        }
    }

    /// Load a body from exactly 240 raw bytes — the canonical entry point.
    ///
    /// Rejects anything that is not exactly [`BODY_BYTES`]. The bytes flow
    /// `BodyBytes240 → PackedCorners → Cartridge`, the same path JSON
    /// `packedWords` bodies take, so a raw `.body240` file and its JSON wrapper
    /// produce an identical `PackedCorners`.
    pub fn from_body_bytes(name: &str, bytes: &[u8], boost: f64) -> Result<Self, String> {
        let packed = PackedCorners::from_body_bytes(bytes).map_err(|e| e.to_string())?;
        Ok(Self::from_packed(
            name.to_string(),
            packed,
            [boost; NUM_CORNERS],
            DriveBlock::default(),
            None,
            None,
        ))
    }

    pub fn from_json(json: &str) -> Result<Self, String> {
        let raw: CartridgeJson =
            serde_json::from_str(json).map_err(|e| format!("JSON parse error: {e}"))?;
        let sr = raw.sample_rate;

        let mut packed_words = [[[0u16; NUM_COEFFS]; NUM_STAGES]; NUM_CORNERS];
        let mut packed_present = [false; NUM_CORNERS];
        // Stage-only fallback corners, used only when no packedWords are present.
        let mut stage_corners = [[[0.0; NUM_COEFFS]; NUM_STAGES]; NUM_CORNERS];
        let mut boosts = [1.0f64; NUM_CORNERS];

        let mut find_corner = |label: &str, idx: usize| -> Result<(), String> {
            let kf = raw
                .keyframes
                .iter()
                .find(|k| k.label == label)
                .ok_or_else(|| format!("missing keyframe '{label}'"))?;

            boosts[idx] = kf.boost;
            if !kf.packed_words.is_empty() {
                if kf.packed_words.len() != NUM_STAGES {
                    return Err(format!(
                        "{label}.packedWords has {} rows, expected {NUM_STAGES}",
                        kf.packed_words.len()
                    ));
                }
                for (i, words) in kf.packed_words.iter().copied().enumerate() {
                    packed_words[idx][i] = words;
                }
                packed_present[idx] = true;
            } else {
                for (i, v) in kf.stages.iter().take(NUM_STAGES).enumerate() {
                    // Try to parse as biquad first
                    if let Ok(c) = serde_json::from_value::<StageCoeffsJson>(v.clone()) {
                        stage_corners[idx][i] = [c.c0, c.c1, c.c2, c.c3, c.c4];
                    } else if let Ok(r) = serde_json::from_value::<RawStage>(v.clone()) {
                        // Compile from Z-plane
                        let params = EmuResonatorParams {
                            freq_hz: crate::emu_resonator::freq_from_a1_r(
                                r.a1 as f64,
                                r.r as f64,
                                sr,
                            ) as f32,
                            radius: r.r,
                            val1: r.val1,
                            val2: r.val2,
                            val3: r.val3,
                        };
                        let enc = emu_resonator(&params, sr);
                        stage_corners[idx][i] = [enc.c0, enc.c1, enc.c2, enc.c3, enc.c4];
                    }
                }
            }
            Ok(())
        };

        find_corner("M0_Q0", 0)?;
        find_corner("M100_Q0", 1)?;
        find_corner("M0_Q100", 2)?;
        find_corner("M100_Q100", 3)?;

        let packed_count = packed_present.iter().filter(|&&v| v).count();
        if packed_count == NUM_CORNERS {
            // Packed bytes are present → they are the coefficient authority.
            // Serialize to the exact 240-byte layout, then go through the same
            // canonical constructor as a raw `.body240` file. `stages` (if any)
            // are ignored: they are readback/fallback, never authority.
            let bytes = PackedCorners {
                words: packed_words,
            }
            .to_rom_bytes();
            let packed = PackedCorners::from_body_bytes(&bytes).map_err(|e| e.to_string())?;
            return Ok(Self::from_packed(
                raw.name,
                packed,
                boosts,
                raw.drive.unwrap_or_default(),
                raw.spatial_profile,
                raw.mod_fn,
            ));
        }
        if packed_count != 0 {
            return Err("packedWords must be present on all four corners or none".to_string());
        }

        // No packed bytes anywhere → legacy stage-coefficient body.
        Ok(Self {
            name: raw.name,
            corners: stage_corners,
            boosts,
            packed: None,
            drive: raw.drive.unwrap_or_default(),
            spatial_profile: raw.spatial_profile,
            mod_fn: raw.mod_fn,
        })
    }

    /// The single shipping morph/Q interpolation entry point.
    ///
    /// Every cartridge constructed from `.body240` / JSON `packedWords` / FFI
    /// raw bytes carries `packed = Some(_)` and dispatches into
    /// [`PackedCorners::interpolate_biquad`] — packed-u16 bilinear in the
    /// same domain the E-mu hardware morphs. This is the path the player
    /// runs, the path null-vs-X3 (-95.41 dB @ M50/Q50) was achieved with, and
    /// the only path tools should compare against.
    ///
    /// The `packed = None` branch is the legacy stage-coefficients f64
    /// fallback — see [`Self::interpolate_legacy_stages`]. It exists only for
    /// bodies that never carried packed words (pre-`packed-body-v1` JSON);
    /// no shipping body lands in this branch.
    pub fn interpolate(&self, morph: f64, q: f64) -> CornerData {
        if let Some(packed) = &self.packed {
            return packed.interpolate_biquad(morph as f32, q as f32);
        }
        self.interpolate_legacy_stages(morph, q)
    }

    /// f64 bilinear over the decoded `stages` coefficients — legacy fallback
    /// for cartridges built without `packedWords`.
    ///
    /// **Never used for shipping bodies.** Bodies authored after the canonical
    /// 240-byte path (`STATE.md` 2026-05-26) all carry packed words; this
    /// branch only fires for legacy compiled-v1 JSON files lacking
    /// `packedWords`. It is preserved so those files still load, not as a
    /// production interpolation path.
    fn interpolate_legacy_stages(&self, morph: f64, q: f64) -> CornerData {
        let mut result = [[0.0; NUM_COEFFS]; NUM_STAGES];
        for stage in 0..NUM_STAGES {
            for c in 0..NUM_COEFFS {
                let q_m0 = self.corners[0][stage][c]
                    + (self.corners[2][stage][c] - self.corners[0][stage][c]) * q;
                let q_m1 = self.corners[1][stage][c]
                    + (self.corners[3][stage][c] - self.corners[1][stage][c]) * q;
                result[stage][c] = q_m0 + (q_m1 - q_m0) * morph;
            }
        }
        result
    }

    pub fn interpolate_boost(&self, morph: f64, q: f64) -> f64 {
        let q_m0 = self.boosts[0] + (self.boosts[2] - self.boosts[0]) * q;
        let q_m1 = self.boosts[1] + (self.boosts[3] - self.boosts[1]) * q;
        q_m0 + (q_m1 - q_m0) * morph
    }
}

#[derive(Deserialize)]
struct StageCoeffsJson {
    c0: f64,
    c1: f64,
    c2: f64,
    c3: f64,
    c4: f64,
}
