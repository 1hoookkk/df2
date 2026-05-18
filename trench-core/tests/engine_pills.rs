//! Smoke gate: every cartridge listed in `cartridges/factory/manifest.json` must load
//! through `Cartridge::from_json` without error.
//!
//! This is intentionally the dumbest useful test — it does not try to
//! measure audio, enforce invariants, or judge taste. It only proves
//! that the shipping phoneme pills baked by `authoring/compilers/bake_phoneme_pills.py`
//! are all structurally valid `compiled-v1` cartridges the runtime can
//! consume. If this gate fails, either the bake is emitting bad files
//! or the upstream shape bank has drifted.

use std::fs;
use std::path::PathBuf;

use serde_json::Value;
use trench_core::Cartridge;

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|p| p.parent())
        .expect("repo root above runtime/")
        .to_path_buf()
}

fn manifest_path() -> PathBuf {
    repo_root()
        .join("cartridges")
        .join("factory")
        .join("manifest.json")
}

#[test]
fn every_engine_pill_loads() {
    let manifest_path = manifest_path();
    assert!(
        manifest_path.exists(),
        "missing {}; run `python authoring/compilers/bake_phoneme_pills.py`",
        manifest_path.display()
    );

    let manifest_json = fs::read_to_string(&manifest_path)
        .unwrap_or_else(|e| panic!("read {}: {e}", manifest_path.display()));
    let manifest: Value = serde_json::from_str(&manifest_json)
        .unwrap_or_else(|e| panic!("parse {}: {e}", manifest_path.display()));

    let tokens = manifest
        .get("tokens")
        .and_then(|v| v.as_array())
        .expect("factory manifest must contain a tokens array");
    assert!(
        !tokens.is_empty(),
        "factory manifest {} contains no tokens",
        manifest_path.display()
    );

    let mut failures: Vec<String> = Vec::new();
    let root = repo_root();
    for token in tokens {
        let id = token.get("id").and_then(|v| v.as_str()).unwrap_or("<missing id>");
        let path = match token.get("path").and_then(|v| v.as_str()) {
            Some(path) => root.join(path),
            None => {
                failures.push(format!("{id}: missing path"));
                continue;
            }
        };
        let json = match fs::read_to_string(&path) {
            Ok(j) => j,
            Err(e) => {
                failures.push(format!("{id}: {}: read error: {e}", path.display()));
                continue;
            }
        };
        if let Err(e) = Cartridge::from_json(&json) {
            failures.push(format!("{id}: {}: {e}", path.display()));
        }
    }

    assert!(
        failures.is_empty(),
        "{} / {} pills failed to load:\n  {}",
        failures.len(),
        tokens.len(),
        failures.join("\n  ")
    );

    println!(
        "loaded {} phoneme pills from {}",
        tokens.len(),
        manifest_path.display()
    );
}
