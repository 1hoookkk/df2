//! VOWL CHORD — two complete vowel actors coexisting in one body,
//! counter-moving across the four-corner surface (Tyson directive
//! 2026-07-10). Stages 1-3 = Actor A formants, stages 4-6 = Actor B
//! formants. Corners: C00 A=/u/ B=/i/, C10 A=/i/ B=/u/, C01 A=/ɑ/ B=/ɛ/,
//! C11 A=/ɛ/ B=/ɑ/ — Q is an authored second journey (dark pair → open
//! pair), never derived.
//!
//! Every number is table-pulled: formant centers + bandwidths from
//! tables/vowel_formants.json (Peterson & Barney 1952); radius law
//! r = exp(-pi*bw/SR); T1 ridge zero co-located at r_p - 0.005 (the
//! firmware-traced Q0 gain-byte split, typed grammar); section gain =
//! the DC-normalized one-owner law (trench_core stage_biquad via
//! Mode::pole_zero). No LPC over a mix; each vowel assigned to its lanes
//! deliberately.
//!
//! Emits: .body240 + .design.json + audit.json (grid trajectories,
//! collisions, stability, corner/center/diagonal curves) + packed-runtime
//! renders (pink noise, saw bass, chord) — then the Python side plots and
//! builds the phoneme-legend grid page.

use forge_model::packed::{project, CORNERS};
use forge_model::sos::cascade_loss;
use forge_model::{Anchor, Design, Mode, AUTHORING_SR};
use std::f64::consts::{PI, TAU};
use std::io::Write;
use std::path::PathBuf;
use trench_core::cartridge::Cartridge;
use trench_core::engine::FilterEngine;
use trench_core::minifloat::PackedCorners;

const NAME: &str = "VOWL_CHORD_2actor";
const GRID: usize = 17;

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..")
}

/// (f, bw) for formants 1..=3 of one vowel, read from the measured table.
fn vowel(table: &serde_json::Value, key: &str) -> [(f64, f64); 3] {
    let v = table["vowels"]
        .as_array()
        .expect("vowels array")
        .iter()
        .find(|v| v["key"] == key)
        .unwrap_or_else(|| panic!("vowel {key} not in table"));
    [1, 2, 3].map(|n| {
        (
            v[&format!("f{n}")].as_f64().expect("formant Hz"),
            v[&format!("bw{n}")].as_f64().expect("bandwidth Hz"),
        )
    })
}

/// T1 formant ridge from measured (f, bw): pole radius from the bandwidth
/// law, zero co-located 0.005 inside (firmware-traced Q0 split).
fn ridge(f: f64, bw: f64) -> Mode {
    let rp = (-PI * bw / AUTHORING_SR).exp();
    Mode::pole_zero(f, rp, f, rp - 0.005)
}

fn anchor(morph: f64, q: f64, a: [(f64, f64); 3], b: [(f64, f64); 3]) -> Anchor {
    Anchor {
        morph,
        q,
        modes: a
            .iter()
            .chain(b.iter())
            .map(|&(f, bw)| ridge(f, bw))
            .collect(),
    }
}

fn factor(a1: f64, a2: f64) -> (f64, f64) {
    // (freq_hz, radius) of the dominant root of z^2 + a1 z + a2.
    let disc = a1 * a1 - 4.0 * a2;
    if disc < 0.0 {
        let r = a2.max(0.0).sqrt();
        let hz = (-a1 / (2.0 * r.max(1e-12))).clamp(-1.0, 1.0).acos() * AUTHORING_SR / TAU;
        (hz, r)
    } else {
        let s = disc.sqrt();
        let (z1, z2) = ((-a1 + s) / 2.0, (-a1 - s) / 2.0);
        let z = if z1.abs() >= z2.abs() { z1 } else { z2 };
        let hz = if z >= 0.0 { 0.0 } else { AUTHORING_SR / 2.0 };
        (hz, z.abs())
    }
}

fn cascade_db(rows: &[[f64; 5]], freqs: &[f64]) -> Vec<f64> {
    freqs
        .iter()
        .map(|&f| {
            let w = TAU * f / AUTHORING_SR;
            let (c1, s1) = (w.cos(), -w.sin());
            let (c2, s2) = ((2.0 * w).cos(), -(2.0 * w).sin());
            let mut mag2 = 1.0f64;
            for r in rows {
                let (nr, ni) = (r[0] + r[1] * c1 + r[2] * c2, r[1] * s1 + r[2] * s2);
                let (dr, di) = (1.0 + r[3] * c1 + r[4] * c2, r[3] * s1 + r[4] * s2);
                mag2 *= (nr * nr + ni * ni) / (dr * dr + di * di).max(1e-300);
            }
            10.0 * mag2.max(1e-30).log10()
        })
        .collect()
}

fn max_rho(rows: &[[f64; 5]]) -> f64 {
    rows.iter()
        .map(|r| trench_core::minifloat::pole_radius(r[3], r[4]))
        .fold(0.0, f64::max)
}

// ---- renders through the REAL shipped chain --------------------------------

fn render(engine_body: &[u8; 240], signal: Vec<f32>, sr: f64, path: &str, q_law: impl Fn(f64) -> (f64, f64)) {
    let cart = Cartridge::from_body_bytes("vowel_chord", engine_body, 1.0).expect("cartridge");
    let mut e = FilterEngine::new();
    e.prepare(sr);
    e.load_cartridge(cart);
    let n = signal.len();
    let mut left = signal;
    let mut right = left.clone();
    let mut offset = 0usize;
    while offset < n {
        let len = (n - offset).min(512);
        let t = offset as f64 / n as f64;
        let (morph, q) = q_law(t);
        e.process_block(&mut left[offset..offset + len], &mut right[offset..offset + len], morph, q);
        offset += len;
    }
    assert_eq!(left.iter().filter(|x| !x.is_finite()).count(), 0, "nonfinite render");
    write_wav(path, &left, sr as u32);
}

fn write_wav(path: &str, samples: &[f32], sr: u32) {
    // minimal float32 mono WAV
    let mut f = std::fs::File::create(path).expect("create wav");
    let data_len = (samples.len() * 4) as u32;
    let mut h = Vec::new();
    h.extend(b"RIFF");
    h.extend((36 + data_len).to_le_bytes());
    h.extend(b"WAVEfmt ");
    h.extend(16u32.to_le_bytes());
    h.extend(3u16.to_le_bytes()); // float
    h.extend(1u16.to_le_bytes());
    h.extend(sr.to_le_bytes());
    h.extend((sr * 4).to_le_bytes());
    h.extend(4u16.to_le_bytes());
    h.extend(32u16.to_le_bytes());
    h.extend(b"data");
    h.extend(data_len.to_le_bytes());
    f.write_all(&h).unwrap();
    for &s in samples {
        f.write_all(&s.to_le_bytes()).unwrap();
    }
}

fn saw_stack(freqs: &[f64], sr: f64, seconds: f64, amp: f32) -> Vec<f32> {
    let n = (sr * seconds) as usize;
    let mut out = vec![0.0f32; n];
    for &f in freqs {
        let step = (f / sr) as f32;
        let mut ph = 0.0f32;
        for x in out.iter_mut() {
            ph = (ph + step).fract();
            *x += (ph * 2.0 - 1.0) * amp;
        }
    }
    out
}

fn pink(sr: f64, seconds: f64) -> Vec<f32> {
    let n = (sr * seconds) as usize;
    let mut seed: u32 = 0xA57E_19D3;
    let (mut b0, mut b1, mut b2) = (0.0f64, 0.0, 0.0);
    (0..n)
        .map(|_| {
            seed = seed.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
            let w = ((seed >> 8) as f64 / ((u32::MAX >> 8) as f64)) * 2.0 - 1.0;
            b0 = 0.99886 * b0 + w * 0.0555179;
            b1 = 0.96900 * b1 + w * 0.1538520;
            b2 = 0.55000 * b2 + w * 0.5329522;
            ((b0 + b1 + b2 + w * 0.5362) * 0.07) as f32
        })
        .collect()
}

fn scale(v: [(f64, f64); 3], k: f64) -> [(f64, f64); 3] {
    v.map(|(f, bw)| (f * k, bw))
}

fn main() {
    let root = root();
    let table: serde_json::Value = serde_json::from_str(
        &std::fs::read_to_string(root.join("tables/vowel_formants.json")).expect("vowel table"),
    )
    .expect("vowel table json");

    let (uw, iy, aa, eh) = (
        vowel(&table, "uw"),
        vowel(&table, "iy"),
        vowel(&table, "aa"),
        vowel(&table, "eh"),
    );

    // Two variants, one lever. UNISON = the verbatim corner table (both
    // actors the same male voice — the symmetric swap makes them coincide
    // at M50, three doubled formants). DUET = actor B female-scaled by the
    // table's own voice_scaling (1.16), a second mouth that cannot
    // degenerate into the first.
    let female = table["voice_scaling"]["female"].as_f64().expect("voice_scaling.female");
    let variants: Vec<(String, f64)> = vec![(NAME.into(), 1.0), (format!("{NAME}_duet"), female)];
    for (name, k) in variants {
        build(&root, &table, &name, uw, iy, aa, eh, k);
    }
}

#[allow(clippy::too_many_arguments)]
fn build(
    root: &std::path::Path,
    table: &serde_json::Value,
    name: &str,
    uw: [(f64, f64); 3],
    iy: [(f64, f64); 3],
    aa: [(f64, f64); 3],
    eh: [(f64, f64); 3],
    b_scale: f64,
) {
    // counter-motion: A clockwise, B counter — every corner holds two mouths
    let design = Design {
        name: name.into(),
        anchors: vec![
            anchor(0.0, 0.0, uw, scale(iy, b_scale)),
            anchor(1.0, 0.0, iy, scale(uw, b_scale)),
            anchor(0.0, 1.0, aa, scale(eh, b_scale)),
            anchor(1.0, 1.0, eh, scale(aa, b_scale)),
        ],
    };

    let body = project(&design).expect("projects");
    let proofs = root.join("bodies/proofs");
    std::fs::create_dir_all(&proofs).unwrap();
    std::fs::write(proofs.join(format!("{name}.body240")), body).unwrap();
    std::fs::write(proofs.join(format!("{name}.design.json")), design.to_json()).unwrap();

    // ---- per-projection loss report: native model vs decoded packed corner
    let pc = PackedCorners::from_body_bytes(&body).unwrap();
    println!("PROJECTION LOSS (native f64 model -> packed 240B, per corner)");
    for (ci, &(m, q)) in CORNERS.iter().enumerate() {
        let native: Vec<[f64; 5]> = design.anchor_at(m, q).unwrap().modes.iter().map(Mode::biquad).collect();
        let packed_rows: Vec<[f64; 5]> = (0..6)
            .map(|si| trench_core::minifloat::stage_words_to_biquad(pc.words[ci][si]))
            .collect();
        let (c, i) = cascade_loss(&packed_rows, &native);
        println!("  corner M{}_Q{}: complex NRMSE {:.3e}  impulse NRMSE {:.3e}", (m * 100.0) as u32, (q * 100.0) as u32, c, i);
    }

    // ---- actor-track audit over the TRUE packed 17x17 grid
    let freqs: Vec<f64> = (0..240)
        .map(|i| 40.0 * (18_000.0f64 / 40.0).powf(i as f64 / 239.0))
        .collect();
    let mut worst_rho = 0.0f64;
    let mut min_gap_oct = f64::INFINITY;
    let mut min_gap_at = (0usize, 0usize);
    let mut cells = Vec::new();
    for qi in 0..GRID {
        for mi in 0..GRID {
            let (m, q) = (mi as f32 / (GRID - 1) as f32, qi as f32 / (GRID - 1) as f32);
            let rows = pc.interpolate_biquad(m, q);
            worst_rho = worst_rho.max(max_rho(&rows));
            let stages: Vec<serde_json::Value> = rows
                .iter()
                .map(|r| {
                    let (pf, pr) = factor(r[3], r[4]);
                    let (zf, zr) = if r[0].abs() > 1e-12 {
                        factor(r[1] / r[0], r[2] / r[0])
                    } else {
                        (0.0, 0.0)
                    };
                    serde_json::json!({"pf": pf, "pr": pr, "zf": zf, "zr": zr})
                })
                .collect();
            // actor collision: closest A-lane pole to any B-lane pole, octaves
            for a in 0..3 {
                for b in 3..6 {
                    let (fa, ra) = (stages[a]["pf"].as_f64().unwrap(), stages[a]["pr"].as_f64().unwrap());
                    let (fb, rb) = (stages[b]["pf"].as_f64().unwrap(), stages[b]["pr"].as_f64().unwrap());
                    if ra > 0.5 && rb > 0.5 && fa > 20.0 && fb > 20.0 {
                        let gap = (fa / fb).abs().log2().abs();
                        if gap < min_gap_oct {
                            min_gap_oct = gap;
                            min_gap_at = (mi, qi);
                        }
                    }
                }
            }
            cells.push(serde_json::json!({"m": m, "q": q, "stages": stages}));
        }
    }
    println!("AUDIT  worst rho {worst_rho:.6}  min A-B pole gap {min_gap_oct:.3} oct at grid ({}, {})", min_gap_at.0, min_gap_at.1);
    assert!(worst_rho < 1.0, "unstable grid point");

    // corner + center + diagonal curves
    let key_points: Vec<(&str, f32, f32)> = vec![
        ("C00 uw+iy", 0.0, 0.0),
        ("C10 iy+uw", 1.0, 0.0),
        ("C01 aa+eh", 0.0, 1.0),
        ("C11 eh+aa", 1.0, 1.0),
        ("center", 0.5, 0.5),
        ("diag_main_25", 0.25, 0.25),
        ("diag_main_75", 0.75, 0.75),
        ("diag_anti_25", 0.25, 0.75),
        ("diag_anti_75", 0.75, 0.25),
    ];
    let curves: Vec<serde_json::Value> = key_points
        .iter()
        .map(|&(label, m, q)| {
            let rows = pc.interpolate_biquad(m, q);
            serde_json::json!({"label": label, "m": m, "q": q, "db": cascade_db(&rows, &freqs)})
        })
        .collect();

    // phoneme legend reference set (measured table, verbatim)
    let legend: Vec<serde_json::Value> = table["vowels"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| serde_json::json!({"key": v["key"], "ipa": v["ipa"], "example": v["example"], "f1": v["f1"], "f2": v["f2"], "f3": v["f3"]}))
        .collect();

    let audit = serde_json::json!({
        "name": name,
        "source": table["source"],
        "grid": GRID,
        "worst_rho": worst_rho,
        "min_actor_gap_oct": min_gap_oct,
        "freqs": freqs,
        "curves": curves,
        "cells": cells,
        "legend": legend,
    });
    std::fs::write(proofs.join(format!("{name}.audit.json")), serde_json::to_string(&audit).unwrap()).unwrap();

    // ---- packed-runtime renders: pink noise, saw bass, chord ---------------
    let sr = 48_000.0;
    let out = std::env::args().nth(1).unwrap_or_else(|| proofs.to_string_lossy().into_owned());
    let sweep_q0 = |t: f64| (((t - 0.1) / 0.8).clamp(0.0, 1.0), 0.0);
    let sweep_q1 = |t: f64| (((t - 0.1) / 0.8).clamp(0.0, 1.0), 1.0);
    let sweep_diag = |t: f64| {
        let s = ((t - 0.1) / 0.8).clamp(0.0, 1.0);
        (s, s)
    };
    for (sig_name, sig) in [
        ("pink", pink(sr, 8.0)),
        ("sawbass", saw_stack(&[55.0], sr, 8.0, 0.25)),
        ("chord", saw_stack(&[110.0, 130.81, 164.81], sr, 8.0, 0.11)),
    ] {
        for (law_name, law) in [
            ("Q0", &sweep_q0 as &dyn Fn(f64) -> (f64, f64)),
            ("Q100", &sweep_q1),
            ("diag", &sweep_diag),
        ] {
            render(
                &body,
                sig.clone(),
                sr,
                &format!("{out}/{name}_{sig_name}_{law_name}.wav"),
                law,
            );
        }
    }
    println!("wrote body/design/audit to {} and 9 renders to {out}", proofs.display());
}
