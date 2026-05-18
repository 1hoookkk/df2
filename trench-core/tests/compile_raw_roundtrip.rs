//! Round-trip gate: `authoring/compilers/compile_raw.py` output must load via
//! `Cartridge::from_json`. This is a mechanical compiler from the internal
//! raw-stage-v1 authoring surface to compiled-v1 JSON.

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

fn run_compiler(raw_json: &str) -> (std::process::Output, String) {
    let script = repo_root()
        .join("authoring")
        .join("compilers")
        .join("compile_raw.py");
    let mut child = Command::new("python")
        .arg(&script)
        .arg("-")
        .current_dir(repo_root())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("failed to spawn python compile_raw.py");

    use std::io::Write;
    child
        .stdin
        .as_mut()
        .expect("stdin")
        .write_all(raw_json.as_bytes())
        .expect("write stdin");

    let output = child.wait_with_output().expect("wait_with_output");
    let stderr = String::from_utf8_lossy(&output.stderr).into_owned();
    (output, stderr)
}

#[test]
fn raw_surface_round_trips_through_rust_loader() {
    let raw = r#"{
        "format": "raw-stage-v1",
        "name": "raw_roundtrip",
        "boost": 4.0,
        "corners": {
            "M0_Q0": {
                "stages": [
                    {"kind": "allpole", "pole_freq_hz": 440.0, "radius": 0.95, "stage_gain": 0.70}
                ]
            },
            "M0_Q100": {
                "stages": [
                    {"kind": "zero_forced", "pole_freq_hz": 1200.0, "radius": 0.98, "stage_gain": 0.82}
                ]
            },
            "M100_Q0": {
                "stages": [
                    {
                        "kind": "explicit_zero",
                        "pole_freq_hz": 900.0,
                        "radius": 0.93,
                        "stage_gain": 0.88,
                        "zero_freq_hz": 1800.0,
                        "zero_radius": 0.70
                    }
                ]
            },
            "M100_Q100": {
                "stages": [
                    {"kind": "zero_forced_offset", "pole_freq_hz": 3000.0, "radius": 0.96, "stage_gain": 0.75, "offset_semitones": 7.0}
                ]
            }
        }
    }"#;

    let (output, stderr) = run_compiler(raw);
    assert!(
        output.status.success(),
        "compiler exited non-zero: stderr={stderr}"
    );

    let stdout = String::from_utf8(output.stdout).expect("utf8 stdout");
    let cart = Cartridge::from_json(&stdout)
        .unwrap_or_else(|e| panic!("loader rejected compiled cartridge: {e}\n\njson:\n{stdout}"));

    assert_eq!(cart.name, "raw_roundtrip");
    assert_eq!(cart.corners.len(), 4);
    assert_eq!(cart.boosts, [4.0, 4.0, 4.0, 4.0]);
}

#[test]
fn corner_stage_list_shorthand_round_trips_through_rust_loader() {
    let raw = r#"{
        "format": "raw-stage-v1",
        "name": "raw_corner_list",
        "authoring_sample_rate_hz": 39062.5,
        "corners": {
            "M0_Q0": [
                {"kind": "zero_forced", "pole_freq_hz": 300.0, "radius": 0.82, "stage_gain": 1.0}
            ],
            "M0_Q100": [
                {"kind": "zero_forced_offset", "pole_freq_hz": 450.0, "radius": 0.77, "stage_gain": 1.05, "offset_semitones": 7.0}
            ],
            "M100_Q0": [
                {
                    "kind": "explicit_zero",
                    "pole_freq_hz": 700.0,
                    "radius": 0.73,
                    "stage_gain": 0.95,
                    "zero_freq_hz": 1200.0,
                    "zero_radius": 0.66
                }
            ],
            "M100_Q100": [
                {"kind": "passthrough"}
            ]
        }
    }"#;

    let (output, stderr) = run_compiler(raw);
    assert!(
        output.status.success(),
        "compiler rejected corner-list shorthand: stderr={stderr}"
    );

    let stdout = String::from_utf8(output.stdout).expect("utf8 stdout");
    let cart = Cartridge::from_json(&stdout)
        .unwrap_or_else(|e| panic!("loader rejected compiled cartridge: {e}\n\njson:\n{stdout}"));

    assert_eq!(cart.name, "raw_corner_list");
    assert_eq!(cart.corners.len(), 4);
}

#[test]
fn unknown_stage_kind_is_rejected() {
    let raw = r#"{
        "format": "raw-stage-v1",
        "corners": {
            "M0_Q0": {"stages": [{"kind": "mystery", "pole_freq_hz": 440.0, "radius": 0.95}]},
            "M0_Q100": {"stages": []},
            "M100_Q0": {"stages": []},
            "M100_Q100": {"stages": []}
        }
    }"#;

    let (output, stderr) = run_compiler(raw);
    assert!(
        !output.status.success(),
        "compiler accepted an unknown stage kind; expected failure"
    );
    assert!(
        stderr.contains("kind must be one of"),
        "error message must name the accepted kinds, got: {stderr}"
    );
}

#[test]
fn missing_corner_is_rejected() {
    let raw = r#"{
        "format": "raw-stage-v1",
        "corners": {
            "M0_Q0": {"stages": []},
            "M0_Q100": {"stages": []},
            "M100_Q0": {"stages": []}
        }
    }"#;

    let (output, stderr) = run_compiler(raw);
    assert!(
        !output.status.success(),
        "compiler accepted a raw surface with a missing corner; expected failure"
    );
    assert!(
        stderr.contains("missing corner 'M100_Q100'"),
        "error message must name the missing corner, got: {stderr}"
    );
}
