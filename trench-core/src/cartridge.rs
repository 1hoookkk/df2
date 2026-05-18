use crate::cascade::{NUM_COEFFS, NUM_STAGES};
use crate::emu_resonator::{emu_resonator, EmuResonatorParams};
use serde::Deserialize;

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
}

fn default_sample_rate() -> f64 {
    39062.5
}

#[derive(Clone, Debug)]
pub struct Cartridge {
    pub name: String,
    pub corners: [CornerData; NUM_CORNERS],
    pub boosts: [f64; NUM_CORNERS],
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
            drive: DriveBlock::default(),
            spatial_profile: None,
            mod_fn: None,
        }
    }

    pub fn from_json(json: &str) -> Result<Self, String> {
        let raw: CartridgeJson =
            serde_json::from_str(json).map_err(|e| format!("JSON parse error: {e}"))?;
        let sr = raw.sample_rate;

        let find_corner = |label: &str| -> Result<(CornerData, f64), String> {
            let kf = raw
                .keyframes
                .iter()
                .find(|k| k.label == label)
                .ok_or_else(|| format!("missing keyframe '{label}'"))?;

            let mut corner = [[0.0; NUM_COEFFS]; NUM_STAGES];
            for (i, v) in kf.stages.iter().take(NUM_STAGES).enumerate() {
                // Try to parse as biquad first
                if let Ok(c) = serde_json::from_value::<StageCoeffsJson>(v.clone()) {
                    corner[i] = [c.c0, c.c1, c.c2, c.c3, c.c4];
                } else if let Ok(r) = serde_json::from_value::<RawStage>(v.clone()) {
                    // Compile from Z-plane
                    let params = EmuResonatorParams {
                        freq_hz: crate::emu_resonator::freq_from_a1_r(r.a1 as f64, r.r as f64, sr)
                            as f32,
                        radius: r.r,
                        val1: r.val1,
                        val2: r.val2,
                        val3: r.val3,
                    };
                    let enc = emu_resonator(&params, sr);
                    corner[i] = [enc.c0, enc.c1, enc.c2, enc.c3, enc.c4];
                }
            }
            Ok((corner, kf.boost))
        };

        let (c0, b0) = find_corner("M0_Q0")?;
        let (c1, b1) = find_corner("M100_Q0")?;
        let (c2, b2) = find_corner("M0_Q100")?;
        let (c3, b3) = find_corner("M100_Q100")?;

        Ok(Self {
            name: raw.name,
            corners: [c0, c1, c2, c3],
            boosts: [b0, b1, b2, b3],
            drive: DriveBlock::default(),
            spatial_profile: None, // Simplified for now
            mod_fn: None,
        })
    }

    pub fn interpolate(&self, morph: f64, q: f64) -> CornerData {
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
