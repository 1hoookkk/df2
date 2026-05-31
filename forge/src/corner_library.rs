//! Audited global corner library consumed by SHAPE's spectrum picker.

use std::path::{Path, PathBuf};

use serde_json::Value;
use trench_core::cartridge::{Cartridge, CornerData};

#[derive(Clone, Debug)]
pub struct CornerLibraryEntry {
    pub id: String,
    pub name: String,
    pub category: String,
    pub provenance: String,
    pub path: PathBuf,
    pub brightness: f32,
    pub openness: f32,
    pub response_trace_db: Vec<f32>,
    pub response_min_db: f32,
    pub response_max_db: f32,
    pub peak_count: usize,
}

#[derive(Default)]
pub struct CornerLibrary {
    entries: Vec<CornerLibraryEntry>,
}

impl CornerLibrary {
    pub fn load_default() -> Self {
        let index = default_index();
        match Self::load(&index) {
            Ok(library) => library,
            Err(error) => {
                eprintln!("corner library unavailable: {error}");
                Self::default()
            }
        }
    }

    pub fn load(index: &Path) -> Result<Self, String> {
        let json = std::fs::read_to_string(index)
            .map_err(|error| format!("{}: {error}", index.display()))?;
        Self::from_json(index, &json)
    }

    fn from_json(index: &Path, json: &str) -> Result<Self, String> {
        let manifest: Value =
            serde_json::from_str(json).map_err(|error| format!("manifest JSON: {error}"))?;
        if manifest["format"].as_str() != Some("df2-corner-library-v1") {
            return Err("unsupported corner library format".to_owned());
        }
        let root = index.parent().ok_or("corner library index has no parent")?;
        let rows = manifest["entries"]
            .as_array()
            .ok_or("corner library entries missing")?;
        let mut entries = Vec::with_capacity(rows.len());
        for row in rows {
            let required = |key: &str| {
                row[key]
                    .as_str()
                    .map(str::to_owned)
                    .ok_or_else(|| format!("corner library entry missing {key}"))
            };
            let path = required("path")?;
            let audit = &row["audit"];
            entries.push(CornerLibraryEntry {
                id: required("id")?,
                name: required("name")?,
                category: required("category")?,
                provenance: required("provenance")?,
                path: root.join(path),
                brightness: row["brightness"]
                    .as_f64()
                    .ok_or("corner library entry missing brightness")?
                    .clamp(0.0, 1.0) as f32,
                openness: row["openness"]
                    .as_f64()
                    .ok_or("corner library entry missing openness")?
                    .clamp(0.0, 1.0) as f32,
                response_trace_db: row["responseTraceDb"]
                    .as_array()
                    .map(|trace| {
                        trace
                            .iter()
                            .filter_map(|value| value.as_f64())
                            .map(|value| value as f32)
                            .collect()
                    })
                    .unwrap_or_default(),
                response_min_db: audit["responseMinDb"].as_f64().unwrap_or(0.0) as f32,
                response_max_db: audit["responseMaxDb"].as_f64().unwrap_or(0.0) as f32,
                peak_count: audit["peakCount"].as_u64().unwrap_or(0) as usize,
            });
        }
        Ok(Self { entries })
    }

    pub fn entries(&self) -> &[CornerLibraryEntry] {
        &self.entries
    }

    pub fn positions(&self) -> Vec<(f32, f32)> {
        self.entries
            .iter()
            .map(|entry| (entry.brightness, entry.openness))
            .collect()
    }

    pub fn load_corner(&self, index: usize) -> Result<CornerData, String> {
        let entry = self
            .entries
            .get(index)
            .ok_or_else(|| format!("corner library index {index} out of range"))?;
        let json = std::fs::read_to_string(&entry.path)
            .map_err(|error| format!("{}: {error}", entry.path.display()))?;
        Ok(Cartridge::from_json(&json)?.corners[0])
    }
}

fn default_index() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../dev/tmp/corner_library/index.json")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parser_tracks_every_manifest_entry_and_keeps_the_final_one_selectable() {
        let json = r#"{
          "format": "df2-corner-library-v1",
          "entries": [
            {"id":"first","name":"First","category":"authored","provenance":"candidate-original","path":"first.corner.json","brightness":0.1,"openness":0.2},
            {"id":"last","name":"Last","category":"physics","provenance":"candidate-original","path":"last.corner.json","brightness":0.9,"openness":0.8}
          ]
        }"#;
        let library = CornerLibrary::from_json(Path::new("corner_library/index.json"), json)
            .expect("parse manifest");
        assert_eq!(library.entries().len(), 2);
        assert_eq!(library.entries()[library.entries().len() - 1].id, "last");
    }

    #[test]
    fn generated_manifest_survivors_load_when_the_index_is_present() {
        let index = default_index();
        if !index.exists() {
            return;
        }
        let library = CornerLibrary::load(&index).expect("load generated manifest");
        assert!(!library.entries().is_empty());
        for index in 0..library.entries().len() {
            library.load_corner(index).expect("load audited survivor");
        }
        assert!(library
            .entries()
            .iter()
            .all(|entry| entry.response_trace_db.len() == 36));
        library
            .load_corner(library.entries().len() - 1)
            .expect("load final audited survivor");
    }
}
