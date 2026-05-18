//! Round-trip gate: `authoring/compilers/compile_grid.py` output must load via
//! `Cartridge::from_json`. Spec: docs/superpowers/specs/compiler_grid_to_cartridge.md.
//!
//! Also pins the strict 2-token limit — the v1 compiler MUST reject any
//! grid with more than 2 tokens rather than silently dropping middle entries.

use std::path::PathBuf;
use std::process::{Command, Stdio};

use trench_core::Cartridge;

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|p| p.parent())
        .expect("repo root above runtime/")
        .to_path_buf()
}

fn run_compiler(grid_json: &str) -> (std::process::Output, String) {
    let script = repo_root()
        .join("authoring")
        .join("compilers")
        .join("compile_grid.py");
    let mut child = Command::new("python")
        .arg(&script)
        .arg("-")
        .current_dir(repo_root())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("failed to spawn python compile_grid.py");

    use std::io::Write;
    child
        .stdin
        .as_mut()
        .expect("stdin")
        .write_all(grid_json.as_bytes())
        .expect("write stdin");

    let output = child.wait_with_output().expect("wait_with_output");
    let stderr = String::from_utf8_lossy(&output.stderr).into_owned();
    (output, stderr)
}

#[test]
fn two_token_grid_round_trips_through_rust_loader() {
    let grid = r#"{
        "name": "ah_to_ee_roundtrip",
        "grid": [
            {"token": "vowels.ah"},
            {"token": "vowels.ee"}
        ]
    }"#;

    let (output, stderr) = run_compiler(grid);
    assert!(
        output.status.success(),
        "compiler exited non-zero: stderr={stderr}"
    );

    let stdout = String::from_utf8(output.stdout).expect("utf8 stdout");
    let cart = Cartridge::from_json(&stdout)
        .unwrap_or_else(|e| panic!("loader rejected compiled cartridge: {e}\n\njson:\n{stdout}"));

    assert_eq!(cart.name, "ah_to_ee_roundtrip");
    assert_eq!(cart.corners.len(), 4);
    assert_eq!(cart.boosts.len(), 4);
}

#[test]
fn three_token_grid_is_rejected() {
    let grid = r#"{
        "grid": [
            {"token": "vowels.ah"},
            {"token": "vowels.oo"},
            {"token": "vowels.ee"}
        ]
    }"#;

    let (output, stderr) = run_compiler(grid);
    assert!(
        !output.status.success(),
        "compiler accepted a 3-token grid; expected strict rejection"
    );
    assert!(
        stderr.contains("exactly 2 tokens"),
        "error message must name the 2-token limit, got: {stderr}"
    );
}

#[test]
fn unknown_token_is_rejected() {
    let grid = r#"{
        "grid": [
            {"token": "vowels.ah"},
            {"token": "vowels.not_a_real_token"}
        ]
    }"#;

    let (output, stderr) = run_compiler(grid);
    assert!(
        !output.status.success(),
        "compiler accepted an unknown token; expected failure"
    );
    assert!(
        stderr.contains("unknown token"),
        "error message must name the unknown token, got: {stderr}"
    );
}
