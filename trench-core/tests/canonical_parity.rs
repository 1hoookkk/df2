//! Rust-side parity gate: trench-core Cascade + AGC + boost vs python
//! reference WAVs in `reference/canonical_audio/`.
//!
//! Walks `reference/canonical_audio/MANIFEST.json` and dispatches on `source_type`:
//!
//!   - `raw_p2k_skin`  : `datasets/p2k_skins/*.json` (33 numbered + 2 vocal)
//!                       stage form `{a1, r, val1, val2, val3, flag}`
//!                       3-stage entries are passthrough-padded to 6
//!   - `calibration_re`: `reference/calibration/*.json` (6 ft=33-55 extractions)
//!                       stage form `{pole_freq_hz, radius, val1, val2, val3, ...}`
//!                       a1 = -2 * radius * cos(2pi * pole_freq_hz / sample_rate_authored)
//!
//! Pipeline (matches `authoring/compilers/parity_null.py`):
//!     source stage -> [b0,b1,b2,a1,a2] -> trench_core::Cascade::tick (f64 inside, f32 cast at output)
//!                  -> agc_step_f64 inline (f64, mirrors python apply_agc)
//!                  -> * boost (f64)
//!                  -> compare to reference/canonical_audio/<name>_<corner>.wav
//!
//! Expected nulls: -274 to -303 dB at corners where AGC stays at 1.0
//! (cascade output peak < 1.0), and ~-147 dB at the few corners where
//! AGC fires (cascade output peak > 1.0). Threshold -120 dB.
//!
//! Why `agc_step_f64` instead of `trench_core::agc::agc_step`: the
//! shipping `agc_step` operates in f32 because the JUCE runtime buffers
//! are f32, but the python references are rendered through an f64 AGC.
//! AGC is path-dependent (`int(gain*|sample|) & 0xF`), so f32
//! quantization at any sample where cascade output exceeds ~1.0 produces
//! a different gain trajectory and tens of dB of residual. The f64
//! mirror keeps this test focused on the Cascade math; the f32-vs-f64
//! AGC question is documented in SESSION_STATE rev 4 truth #13 and
//! belongs to the FilterEngine port.
//!
//! Why raw skins / calibration files instead of compiled cartridges:
//! `cartridges/p2k/*.json` are f32-quantized through an f32 round-trip
//! in the compile path (~6e-8 per coef), which catastrophically
//! amplifies in high-Q stages. SESSION_STATE rev 4 truth #12.

use std::collections::BTreeMap;
use std::f64::consts::PI;
use std::fs;
use std::path::{Path, PathBuf};

use serde::Deserialize;
use trench_core::{Cascade, CornerData, BLOCK_SIZE, NUM_STAGES};

const AGC_TABLE: [f64; 16] = [
    1.0001, 1.0001, 0.996, 0.990, 0.920, 0.500, 0.200, 0.160, 0.120, 0.120, 0.120, 0.120, 0.120,
    0.120, 0.120, 0.120,
];

#[inline(always)]
fn agc_step_f64(sample: f64, agc_gain: &mut f64) -> f64 {
    let abs_sample = sample.abs();
    let idx = ((*agc_gain * abs_sample) as u32 & 0xF) as usize;
    let new_gain = *agc_gain * AGC_TABLE[idx];
    *agc_gain = if new_gain < 1.0 { new_gain } else { 1.0 };
    sample * *agc_gain
}

const FAIL_THRESHOLD_DB: f64 = -120.0;
const CORNER_LABELS: [&str; 4] = ["M0_Q0", "M0_Q100", "M100_Q0", "M100_Q100"];

// ─────────────────────────────────────────────────────────────────────────
// Manifest
// ─────────────────────────────────────────────────────────────────────────

#[derive(Deserialize)]
struct ManifestEntry {
    source: String,
    source_type: String,
    #[serde(default = "default_boost")]
    boost: f64,
    #[serde(default = "default_sr")]
    sample_rate_authored: f64,
}

fn default_boost() -> f64 {
    1.0
}

fn default_sr() -> f64 {
    39062.5
}

// ─────────────────────────────────────────────────────────────────────────
// Source parsing
// ─────────────────────────────────────────────────────────────────────────

#[derive(Deserialize)]
struct RawSkin {
    corners: BTreeMap<String, RawCorner>,
}

#[derive(Deserialize)]
struct RawCorner {
    stages: Vec<RawStage>,
}

#[derive(Deserialize)]
struct RawStage {
    a1: f64,
    r: f64,
    #[serde(default)]
    val1: f64,
    #[serde(default)]
    val2: f64,
    #[serde(default)]
    val3: f64,
    #[serde(default = "default_flag")]
    flag: f64,
}

fn default_flag() -> f64 {
    1.0
}

#[derive(Deserialize)]
struct CalibrationSkin {
    corners: BTreeMap<String, CalibrationCorner>,
}

#[derive(Deserialize)]
struct CalibrationCorner {
    stages: Vec<CalibrationStage>,
}

#[derive(Deserialize)]
struct CalibrationStage {
    pole_freq_hz: f64,
    radius: f64,
    #[serde(default)]
    val1: f64,
    #[serde(default)]
    val2: f64,
    #[serde(default)]
    val3: f64,
}

// ─────────────────────────────────────────────────────────────────────────
// Stage → SOS row
// ─────────────────────────────────────────────────────────────────────────

const PASSTHROUGH_ROW: [f64; 5] = [1.0, 0.0, 0.0, 0.0, 0.0];

fn raw_stage_to_row(s: &RawStage) -> [f64; 5] {
    let r = s.r.min(0.999999);
    let a2 = r * r;
    let (b0, b1, b2) = if s.flag < 0.5 {
        (1.0, 0.0, 0.0)
    } else {
        (1.0 + s.val1, s.a1 + s.val2, a2 - s.val3)
    };
    [b0, b1, b2, s.a1, a2]
}

fn calibration_stage_to_row(s: &CalibrationStage, sample_rate_authored: f64) -> [f64; 5] {
    let r = s.radius.min(0.999999);
    let a1 = -2.0 * r * (2.0 * PI * s.pole_freq_hz / sample_rate_authored).cos();
    let a2 = r * r;
    let (b0, b1, b2) = if s.val1 == 0.0 && s.val2 == 0.0 && s.val3 == 0.0 {
        (1.0, 0.0, 0.0)
    } else {
        (1.0 + s.val1, a1 + s.val2, a2 - s.val3)
    };
    [b0, b1, b2, a1, a2]
}

fn pad_corner(rows: Vec<[f64; 5]>) -> Option<CornerData> {
    if rows.is_empty() || rows.len() > NUM_STAGES {
        return None;
    }
    let mut corner = [PASSTHROUGH_ROW; NUM_STAGES];
    for (i, row) in rows.into_iter().enumerate() {
        corner[i] = row;
    }
    Some(corner)
}

// ─────────────────────────────────────────────────────────────────────────
// Pipeline
// ─────────────────────────────────────────────────────────────────────────

fn render_corner(corner: &CornerData, boost: f64, dry: &[f32]) -> Vec<f32> {
    let mut cascade = Cascade::new();
    cascade.set_targets(corner, 1);
    let _ = cascade.tick(0.0);
    cascade.reset();
    cascade.set_targets(corner, BLOCK_SIZE);
    cascade.set_boost(1.0, BLOCK_SIZE);

    let mut agc_gain = 1.0f64;
    let mut out = Vec::with_capacity(dry.len());
    for &x in dry {
        let cascaded = cascade.tick(x) as f64;
        let post_agc = agc_step_f64(cascaded, &mut agc_gain);
        out.push((post_agc * boost) as f32);
    }
    out
}

// ─────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────

fn trench_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("runtime/trench-core has repo and runtime parent dirs")
        .to_path_buf()
}

fn resolve_repo_path(root: &Path, rel: &str) -> PathBuf {
    let direct = root.join(rel);
    if direct.exists() {
        return direct;
    }

    let normalized = rel.replace('\\', "/");
    for (old, new) in [
        ("docs/calibration/", "reference/calibration/"),
        ("cartridges/engine/", "cartridges/factory/"),
        ("trench-core/", "runtime/trench-core/"),
    ] {
        if let Some(rest) = normalized.strip_prefix(old) {
            let candidate = root.join(new).join(rest);
            if candidate.exists() {
                return candidate;
            }
        }
    }

    direct
}

fn dry_path() -> PathBuf {
    PathBuf::from(r"C:/Users/hooki/trenchwork_clean/ref/bypassed-pinknoise.wav")
}

fn read_wav_mono(path: &Path) -> Vec<f32> {
    let mut reader =
        hound::WavReader::open(path).unwrap_or_else(|e| panic!("opening {}: {e}", path.display()));
    let spec = reader.spec();
    let channels = spec.channels as usize;
    assert_eq!(
        spec.sample_format,
        hound::SampleFormat::Float,
        "expected float WAV at {}",
        path.display()
    );
    assert_eq!(
        spec.bits_per_sample,
        32,
        "expected f32 WAV at {}",
        path.display()
    );
    let samples: Vec<f32> = reader
        .samples::<f32>()
        .map(|s| s.expect("wav sample read"))
        .collect();
    if channels == 1 {
        samples
    } else {
        samples.into_iter().step_by(channels).collect()
    }
}

fn db(x: f64) -> f64 {
    if x <= 0.0 {
        -300.0
    } else {
        20.0 * x.log10()
    }
}

fn rms(v: &[f32]) -> f64 {
    if v.is_empty() {
        return 0.0;
    }
    let s: f64 = v.iter().map(|&x| (x as f64) * (x as f64)).sum();
    (s / v.len() as f64).sqrt()
}

fn null_db(pred: &[f32], reference: &[f32]) -> (f64, f64) {
    let n = pred.len().min(reference.len());
    let mut num = 0.0f64;
    let mut den = 0.0f64;
    for i in 0..n {
        num += (pred[i] as f64) * (reference[i] as f64);
        den += (pred[i] as f64) * (pred[i] as f64);
    }
    if den <= 0.0 {
        return (0.0, 0.0);
    }
    let gain = num / den;
    let mut residual = Vec::with_capacity(n);
    for i in 0..n {
        residual.push(((reference[i] as f64) - gain * (pred[i] as f64)) as f32);
    }
    let res_rms = rms(&residual);
    let ref_rms = rms(&reference[..n]);
    let rel = db(res_rms) - db(ref_rms);
    (gain, rel)
}

fn build_corner_from_source(
    entry: &ManifestEntry,
    source_path: &Path,
) -> Result<BTreeMap<String, CornerData>, String> {
    let json = fs::read_to_string(source_path)
        .map_err(|e| format!("read {}: {e}", source_path.display()))?;
    let mut out: BTreeMap<String, CornerData> = BTreeMap::new();

    match entry.source_type.as_str() {
        "raw_p2k_skin" => {
            let skin: RawSkin = serde_json::from_str(&json)
                .map_err(|e| format!("raw parse {}: {e}", source_path.display()))?;
            for (label, corner) in skin.corners {
                let rows: Vec<[f64; 5]> = corner.stages.iter().map(raw_stage_to_row).collect();
                if let Some(cd) = pad_corner(rows) {
                    out.insert(label, cd);
                }
            }
        }
        "calibration_re" => {
            let skin: CalibrationSkin = serde_json::from_str(&json)
                .map_err(|e| format!("cal parse {}: {e}", source_path.display()))?;
            for (label, corner) in skin.corners {
                let rows: Vec<[f64; 5]> = corner
                    .stages
                    .iter()
                    .map(|s| calibration_stage_to_row(s, entry.sample_rate_authored))
                    .collect();
                if let Some(cd) = pad_corner(rows) {
                    out.insert(label, cd);
                }
            }
        }
        other => return Err(format!("unknown source_type: {other}")),
    }
    Ok(out)
}

#[test]
fn rust_cascade_nulls_against_python_canonical_refs() {
    let root = trench_root();
    let ref_dir = root.join("reference/canonical_audio");
    let manifest_path = ref_dir.join("MANIFEST.json");
    let dry = dry_path();

    assert!(
        ref_dir.exists(),
        "missing canonical reference dir: {}",
        ref_dir.display()
    );
    assert!(
        manifest_path.exists(),
        "missing canonical manifest: {}",
        manifest_path.display()
    );
    assert!(
        dry.exists(),
        "missing dry reference input: {}",
        dry.display()
    );

    let manifest_json = fs::read_to_string(&manifest_path).expect("read manifest");
    let manifest: BTreeMap<String, ManifestEntry> =
        serde_json::from_str(&manifest_json).expect("parse manifest");

    let dry_samples = read_wav_mono(&dry);
    eprintln!(
        "dry: {} samples, manifest: {} entries",
        dry_samples.len(),
        manifest.len()
    );

    let mut failures: Vec<(String, String, f64)> = Vec::new();
    let mut worst_pass: f64 = -300.0;
    let mut covered = 0usize;
    let mut raw_count = 0usize;
    let mut cal_count = 0usize;

    for (name, entry) in &manifest {
        let source_path = resolve_repo_path(&root, &entry.source);
        let corners = match build_corner_from_source(entry, &source_path) {
            Ok(c) => c,
            Err(e) => {
                eprintln!("  {name}: {e}");
                failures.push((name.clone(), "load".to_string(), 0.0));
                continue;
            }
        };

        let tag = if entry.source_type == "raw_p2k_skin" {
            raw_count += 1;
            "raw"
        } else {
            cal_count += 1;
            "cal"
        };

        for label in CORNER_LABELS.iter() {
            let corner_data = match corners.get(*label) {
                Some(cd) => cd,
                None => continue,
            };
            let ref_wav = ref_dir.join(format!("{name}_{label}.wav"));
            if !ref_wav.exists() {
                continue;
            }
            let reference = read_wav_mono(&ref_wav);
            let pred = render_corner(corner_data, entry.boost, &dry_samples);
            let (gain, rel) = null_db(&pred, &reference);
            covered += 1;
            if rel > FAIL_THRESHOLD_DB {
                eprintln!(
                    " ! {name:24} {tag:>4} {label:>10}  gain={gain:.4}  rel_null={rel:+8.1} dB"
                );
                failures.push((name.clone(), label.to_string(), rel));
            } else {
                if rel > worst_pass {
                    worst_pass = rel;
                }
                eprintln!(
                    "   {name:24} {tag:>4} {label:>10}  gain={gain:.4}  rel_null={rel:+8.1} dB"
                );
            }
        }
    }

    eprintln!();
    eprintln!(
        "rust parity: {covered} corners / {} entries ({raw_count} raw + {cal_count} cal), \
         worst pass {worst_pass:+.1} dB, threshold {FAIL_THRESHOLD_DB:.0} dB",
        manifest.len()
    );
    assert!(
        covered > 0,
        "canonical_parity covered zero reference corners"
    );
    if !failures.is_empty() {
        for (name, label, rel) in &failures {
            eprintln!("  FAIL: {name} {label} {rel:+.1} dB");
        }
        panic!(
            "{} corner(s) exceeded {} dB threshold",
            failures.len(),
            FAIL_THRESHOLD_DB
        );
    }
}
