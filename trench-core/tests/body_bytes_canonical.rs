//! The 240-byte packed body is the single canonical coefficient path.
//!
//! Proves that a raw `.body240` load and a JSON `packedWords` load converge to
//! the same `PackedCorners`, that `stages` are never coefficient authority when
//! packed bytes are present, and that malformed bodies are rejected.

use trench_core::cartridge::BODY_BYTES;
use trench_core::Cartridge;

const CORNER_LABELS: [&str; 4] = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];

/// Deterministic, distinct words per corner/stage/word so byte ordering is
/// exercised. Kept inside the minifloat range so they decode to finite coeffs.
fn corner_words() -> [[[u16; 5]; 6]; 4] {
    let mut w = [[[0u16; 5]; 6]; 4];
    let mut n: u32 = 0x1234;
    for ci in 0..4 {
        for si in 0..6 {
            for wi in 0..5 {
                // Spread across the word range, distinct everywhere.
                n = n.wrapping_mul(1103515245).wrapping_add(12345);
                w[ci][si][wi] = ((n >> 8) & 0xFFFF) as u16;
            }
        }
    }
    w
}

/// Corner-major, stage-major, LE u16 — the canonical 240-byte layout.
fn raw_bytes(words: &[[[u16; 5]; 6]; 4]) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(BODY_BYTES);
    for corner in words.iter() {
        for stage in corner.iter() {
            for &word in stage.iter() {
                bytes.extend_from_slice(&word.to_le_bytes());
            }
        }
    }
    bytes
}

/// Compiled-v1 JSON carrying `packedWords`. `extra_stages` optionally injects a
/// bogus `stages` block to prove it is ignored when packedWords are present.
fn json_with_packed(words: &[[[u16; 5]; 6]; 4], bogus_stages: bool) -> String {
    let mut keyframes = Vec::new();
    for (ci, label) in CORNER_LABELS.iter().enumerate() {
        let packed: Vec<serde_json::Value> = words[ci]
            .iter()
            .map(|row| serde_json::json!(row.to_vec()))
            .collect();
        let mut kf = serde_json::json!({
            "label": label,
            "boost": 1.0,
            "packedWords": packed,
        });
        if bogus_stages {
            // Wildly wrong coefficients — if these were authority the corners
            // would be unrecognisable garbage relative to the packed words.
            let stages: Vec<serde_json::Value> = (0..6)
                .map(|_| serde_json::json!({"c0":9.9,"c1":-9.9,"c2":9.9,"c3":-9.9,"c4":9.9}))
                .collect();
            kf["stages"] = serde_json::json!(stages);
        }
        keyframes.push(kf);
    }
    serde_json::json!({
        "format": "compiled-v1",
        "name": "canonical",
        "sampleRate": 39062.5,
        "keyframes": keyframes,
    })
    .to_string()
}

#[test]
fn raw_and_json_produce_identical_packed_corners() {
    let words = corner_words();
    let raw = Cartridge::from_body_bytes("canonical", &raw_bytes(&words), 1.0).unwrap();
    let json = Cartridge::from_json(&json_with_packed(&words, false)).unwrap();

    let raw_packed = raw.packed.as_ref().expect("raw body must carry packed");
    let json_packed = json.packed.as_ref().expect("json body must carry packed");
    assert_eq!(
        raw_packed, json_packed,
        "raw .body240 and JSON packedWords must decode to identical PackedCorners"
    );
}

#[test]
fn raw_equals_json_at_all_corners_and_midpoint() {
    let words = corner_words();
    let raw = Cartridge::from_body_bytes("canonical", &raw_bytes(&words), 1.0).unwrap();
    let json = Cartridge::from_json(&json_with_packed(&words, false)).unwrap();

    for (m, q) in [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0), (0.5, 0.5)] {
        let cr = raw.interpolate(m, q);
        let cj = json.interpolate(m, q);
        assert_eq!(cr, cj, "interpolate({m},{q}) differs raw vs json");
        for stage in &cr {
            for v in stage {
                assert!(v.is_finite(), "non-finite coeff at ({m},{q})");
            }
        }
    }
}

#[test]
fn interpolate_midpoint_identical_raw_vs_json() {
    let words = corner_words();
    let raw = Cartridge::from_body_bytes("canonical", &raw_bytes(&words), 1.0).unwrap();
    let json = Cartridge::from_json(&json_with_packed(&words, false)).unwrap();
    assert_eq!(
        raw.interpolate(0.5, 0.5),
        json.interpolate(0.5, 0.5),
        "Cartridge::interpolate(0.5,0.5) must be bit-identical for raw bytes and JSON wrapper"
    );
}

#[test]
fn bogus_stages_are_ignored_when_packed_present() {
    let words = corner_words();
    // Same words, one with a wildly-wrong `stages` block, one without.
    let with_bogus = Cartridge::from_json(&json_with_packed(&words, true)).unwrap();
    let raw = Cartridge::from_body_bytes("canonical", &raw_bytes(&words), 1.0).unwrap();

    // The packed bank — and therefore every interpolated corner — must match
    // the raw body. If `stages` had been authority, these would diverge.
    assert_eq!(
        with_bogus.packed.as_ref().unwrap(),
        raw.packed.as_ref().unwrap(),
        "packedWords must win over a bogus stages block"
    );
    for (m, q) in [(0.0, 0.0), (1.0, 1.0), (0.5, 0.5)] {
        assert_eq!(
            with_bogus.interpolate(m, q),
            raw.interpolate(m, q),
            "stages leaked into coefficients at ({m},{q})"
        );
    }
}

#[test]
fn partial_packed_words_is_rejected() {
    let words = corner_words();
    // Truncate the first corner's packedWords to 3 rows (< 6 stages).
    let mut keyframes = Vec::new();
    for (ci, label) in CORNER_LABELS.iter().enumerate() {
        let rows = if ci == 0 { 3 } else { 6 };
        let packed: Vec<serde_json::Value> = words[ci][..rows]
            .iter()
            .map(|row| serde_json::json!(row.to_vec()))
            .collect();
        keyframes.push(serde_json::json!({
            "label": label, "boost": 1.0, "packedWords": packed,
        }));
    }
    let json = serde_json::json!({
        "format": "compiled-v1", "name": "partial",
        "sampleRate": 39062.5, "keyframes": keyframes,
    })
    .to_string();
    assert!(
        Cartridge::from_json(&json).is_err(),
        "a corner with fewer than 6 packedWords rows must be rejected"
    );
}

#[test]
fn packed_on_some_corners_only_is_rejected() {
    let words = corner_words();
    let mut keyframes = Vec::new();
    for (ci, label) in CORNER_LABELS.iter().enumerate() {
        if ci < 2 {
            let packed: Vec<serde_json::Value> = words[ci]
                .iter()
                .map(|row| serde_json::json!(row.to_vec()))
                .collect();
            keyframes.push(serde_json::json!({
                "label": label, "boost": 1.0, "packedWords": packed,
            }));
        } else {
            let stages: Vec<serde_json::Value> = (0..6)
                .map(|_| serde_json::json!({"c0":1.0,"c1":0.0,"c2":0.0,"c3":0.0,"c4":0.0}))
                .collect();
            keyframes.push(serde_json::json!({
                "label": label, "boost": 1.0, "stages": stages,
            }));
        }
    }
    let json = serde_json::json!({
        "format": "compiled-v1", "name": "mixed",
        "sampleRate": 39062.5, "keyframes": keyframes,
    })
    .to_string();
    assert!(
        Cartridge::from_json(&json).is_err(),
        "packedWords on some-but-not-all corners must be rejected"
    );
}

#[test]
fn ffi_interpolate_matches_in_process_packed_corners() {
    use trench_core::minifloat::{decode, PackedCorners};
    let words = corner_words();
    let bytes = raw_bytes(&words);
    let packed = PackedCorners::from_body_bytes(&bytes).unwrap();

    for (m, q) in [
        (0.0, 0.0),
        (1.0, 0.0),
        (0.0, 1.0),
        (1.0, 1.0),
        (0.5, 0.5),
        (0.3, 0.7),
    ] {
        let want = packed.interpolate(m as f32, q as f32); // kernel form
        let mut out = [0.0f64; 30];
        let rc = unsafe {
            trench_core::ffi::trench_packed_interpolate(
                bytes.as_ptr(),
                bytes.len(),
                m,
                q,
                out.as_mut_ptr(),
            )
        };
        assert_eq!(rc, 0, "ffi interpolate failed at ({m},{q})");
        for si in 0..6 {
            for ci in 0..5 {
                assert_eq!(
                    out[si * 5 + ci],
                    want[si][ci],
                    "ffi vs in-process interpolate differ at ({m},{q}) s{si} c{ci}"
                );
            }
        }
    }

    // decode parity: the FFI codec is the same `decode`.
    for w in [0u16, 1, 0x0040, 0x1000, 0x8000, 0xC000, 0xFFFF] {
        assert_eq!(trench_core::ffi::trench_packed_decode(w), decode(w));
    }

    // length rejection through the FFI.
    let mut out = [0.0f64; 30];
    let rc = unsafe {
        trench_core::ffi::trench_packed_interpolate(bytes.as_ptr(), 239, 0.5, 0.5, out.as_mut_ptr())
    };
    assert_eq!(rc, -4, "FFI must reject non-240-byte length");
}

#[test]
fn corner_kernel_decodes_each_corner_verbatim() {
    use trench_core::minifloat::{stage_words_to_kernel, PackedCorners};
    let words = corner_words();
    let packed = PackedCorners::from_body_bytes(&raw_bytes(&words)).unwrap();

    // Direct unpack via corner_kernel must equal the per-stage
    // stage_words_to_kernel applied to each stored corner's words. This is the
    // primitive load_reference_rom uses to decode ROM corners without going
    // through the interpolation path.
    for ci in 0..4 {
        let got = packed.corner_kernel(ci);
        for si in 0..6 {
            let want = stage_words_to_kernel(packed.words[ci][si]);
            assert_eq!(
                got[si], want,
                "corner_kernel({ci}) stage {si} != stage_words_to_kernel(words[{ci}][{si}])"
            );
        }
    }
}

#[test]
fn corner_kernel_matches_interpolate_at_grid_points() {
    use trench_core::minifloat::PackedCorners;
    let words = corner_words();
    let packed = PackedCorners::from_body_bytes(&raw_bytes(&words)).unwrap();

    // At the four grid points, decode-via-interpolate happens to be byte-
    // identical to direct unpack today (lerp_u16(_,_,0)=a and (_,_,1)=b for
    // u16 inputs). Lock this equivalence as a test so any future change to
    // lerp_u16 or stage_words_to_kernel keeps the two primitives consistent
    // at the grid — and so the FG-1 refactor (load_reference_rom switching
    // from interpolate-at-corner to corner_kernel) stays bit-identical.
    let grid = [
        (0, 0.0f32, 0.0f32),
        (1, 1.0, 0.0),
        (2, 0.0, 1.0),
        (3, 1.0, 1.0),
    ];
    for (ci, m, q) in grid {
        assert_eq!(
            packed.corner_kernel(ci),
            packed.interpolate(m, q),
            "corner_kernel({ci}) != interpolate({m},{q}) — grid-point equivalence broken"
        );
    }
}

#[test]
fn non_240_byte_raw_load_is_rejected() {
    let words = corner_words();
    let bytes = raw_bytes(&words);
    assert_eq!(bytes.len(), BODY_BYTES);

    // Too short.
    assert!(Cartridge::from_body_bytes("short", &bytes[..BODY_BYTES - 2], 1.0).is_err());
    // Too long.
    let mut long = bytes.clone();
    long.push(0);
    long.push(0);
    assert!(Cartridge::from_body_bytes("long", &long, 1.0).is_err());
    // Exact length still works.
    assert!(Cartridge::from_body_bytes("ok", &bytes, 1.0).is_ok());
}
