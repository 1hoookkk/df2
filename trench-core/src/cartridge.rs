use crate::cascade::{NUM_COEFFS, NUM_STAGES};
use crate::minifloat::{PackedCorners, PackedStage};
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
#[serde(deny_unknown_fields)]
struct KeyframeJson {
    label: String,
    boost: f64,
    #[serde(rename = "packedWords")]
    packed_words: Vec<PackedStage>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CartridgeJson {
    format: String,
    name: String,
    #[serde(rename = "sampleRate")]
    sample_rate: f64,
    keyframes: Vec<KeyframeJson>,
    #[serde(default)]
    drive: Option<DriveBlock>,
    #[serde(default, rename = "spatial_profile")]
    spatial_profile: Option<SpatialProfile>,
}

#[derive(Clone, Debug)]
pub struct Cartridge {
    pub name: String,
    pub boosts: [f64; NUM_CORNERS],
    pub packed: PackedCorners,
    pub drive: DriveBlock,
    pub spatial_profile: Option<SpatialProfile>,
}

impl Cartridge {
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
    ) -> Self {
        Self {
            name,
            boosts,
            packed,
            drive,
            spatial_profile,
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
        ))
    }

    pub fn from_json(json: &str) -> Result<Self, String> {
        let raw: CartridgeJson =
            serde_json::from_str(json).map_err(|e| format!("JSON parse error: {e}"))?;
        if raw.format != "compiled-v1" {
            return Err(format!("unsupported cartridge format '{}'", raw.format));
        }
        if !raw.sample_rate.is_finite() || raw.sample_rate <= 0.0 {
            return Err("sampleRate must be finite and positive".to_string());
        }
        if raw.keyframes.len() != NUM_CORNERS {
            return Err(format!(
                "keyframes has {} entries, expected {NUM_CORNERS}",
                raw.keyframes.len()
            ));
        }

        const LABELS: [&str; NUM_CORNERS] = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];
        let mut packed_words = [[[0u16; NUM_COEFFS]; NUM_STAGES]; NUM_CORNERS];
        let mut boosts = [1.0f64; NUM_CORNERS];
        for (idx, (kf, expected_label)) in raw.keyframes.iter().zip(LABELS).enumerate() {
            if kf.label != expected_label {
                return Err(format!(
                    "keyframe {idx} is '{}', expected '{expected_label}'",
                    kf.label
                ));
            }
            if kf.packed_words.len() != NUM_STAGES {
                return Err(format!(
                    "{expected_label}.packedWords has {} rows, expected {NUM_STAGES}",
                    kf.packed_words.len()
                ));
            }
            boosts[idx] = kf.boost;
            for (stage_index, words) in kf.packed_words.iter().copied().enumerate() {
                packed_words[idx][stage_index] = words;
            }
        }

        Ok(Self::from_packed(
            raw.name,
            PackedCorners {
                words: packed_words,
            },
            boosts,
            raw.drive.unwrap_or_default(),
            raw.spatial_profile,
        ))
    }

    /// The single shipping morph/Q interpolation entry point.
    ///
    /// All cartridge inputs converge to packed-u16 interpolation.
    pub fn interpolate(&self, morph: f64, q: f64) -> CornerData {
        self.packed.interpolate_biquad(morph as f32, q as f32)
    }

    pub fn interpolate_boost(&self, morph: f64, q: f64) -> f64 {
        let q_m0 = self.boosts[0] + (self.boosts[2] - self.boosts[0]) * q;
        let q_m1 = self.boosts[1] + (self.boosts[3] - self.boosts[1]) * q;
        q_m0 + (q_m1 - q_m0) * morph
    }
}
