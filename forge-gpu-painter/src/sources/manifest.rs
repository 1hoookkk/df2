// The START manifest: four provenance lanes built by
// tools/build_forge_start_manifest.py from real source maps
// (FORGE_UI_COMPILE_SOURCES.md). Every row carries one badge —
// COMPILE EXACT · IMPORT EXACT · OVERLAY · APPROX — and quarantined
// rows are listed with their reason, never silently hidden.

use serde::Deserialize;
use std::collections::HashMap;
use std::fs;
use std::path::Path;

pub const MANIFEST_PATH: &str = "dev/tmp/forge_real_source_map/forge_start_manifest.json";

#[derive(Deserialize)]
pub struct StartManifest {
    pub format: String,
    pub lanes: Vec<Lane>,
    #[serde(default)]
    pub quarantine: Vec<QuarantineRow>,
}

#[derive(Deserialize)]
pub struct Lane {
    pub id: String,
    #[allow(dead_code)] // human-facing lane name; the picker shows kinds
    pub title: String,
    pub badge: String,
    pub rows: Vec<Row>,
}

#[derive(Clone, Deserialize)]
pub struct Row {
    pub label: String,
    pub note: String,
    /// peak_shelf | law | exact_skeleton | packed | overlay
    pub kind: String,
    /// what it IS (the picker's color code): law | physical | vocal |
    /// analog | import | reference | iconic | auto | study | approx
    #[serde(default)]
    pub kind_hint: Option<String>,
    #[serde(default)]
    pub body: Option<String>,
    #[serde(default)]
    pub stages: Option<String>,
    #[serde(default)]
    pub curves: Option<String>,
    #[serde(default)]
    pub exact_key: Option<String>,
    #[serde(default)]
    #[allow(dead_code)] // provenance record; surfaced as needed
    pub evidence: Option<String>,
}

#[derive(Deserialize)]
pub struct QuarantineRow {
    pub label: String,
    #[allow(dead_code)] // honest record; surfaced via --inventory-test
    pub reason: String,
}

/// Exact reference curves for the plot overlay (X3 fixed blocks decoded with
/// the pinned candidate, P2K packed refs probed through the shipped core).
#[derive(Clone, Deserialize)]
pub struct OverlayCurves {
    pub label: String,
    #[allow(dead_code)] // provenance record
    pub note: String,
    pub freqs: Vec<f32>,
    pub curves: Vec<OverlayCurve>,
}

#[derive(Clone, Deserialize)]
pub struct OverlayCurve {
    #[allow(dead_code)] // corner identity carried by draw order
    pub label: String,
    pub db: Vec<f32>,
}

pub fn load(root: &Path) -> Option<StartManifest> {
    let text = fs::read_to_string(root.join(MANIFEST_PATH)).ok()?;
    let m: StartManifest = serde_json::from_str(&text).ok()?;
    (m.format == "forge-start-manifest-v1").then_some(m)
}

/// Read every .body240 the manifest references, once, at startup.
pub fn load_bodies(root: &Path, manifest: &StartManifest) -> HashMap<String, [u8; 240]> {
    let mut out = HashMap::new();
    for lane in &manifest.lanes {
        for row in &lane.rows {
            if let Some(path) = &row.body {
                if let Ok(bytes) = fs::read(root.join(path)) {
                    if let Ok(body) = <[u8; 240]>::try_from(bytes) {
                        out.insert(path.clone(), body);
                    }
                }
            }
        }
    }
    out
}

/// Load every overlay curve set the manifest references, once, at startup.
pub fn load_overlays(root: &Path, manifest: &StartManifest) -> HashMap<String, OverlayCurves> {
    let mut out = HashMap::new();
    for lane in &manifest.lanes {
        for row in &lane.rows {
            if let Some(path) = &row.curves {
                if let Ok(text) = fs::read_to_string(root.join(path)) {
                    if let Ok(curves) = serde_json::from_str::<OverlayCurves>(&text) {
                        out.insert(path.clone(), curves);
                    }
                }
            }
        }
    }
    out
}
