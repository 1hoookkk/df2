//! P12 — the hedz stage 1+6 treatment (Tyson directive 2026-07-10).
//!
//! MEASURED from REF_013_talking_hedz (packed decode, all four corners):
//! stages 1 and 6 form a complementary seesaw frame —
//!   S1: traveling low ZERO (the sub boundary rides the wheel 347->1711 Hz,
//!       r~0.94) under a high pole crown (~9 kHz) that blooms under Q
//!       (r 0.975 -> 0.999);
//!   S6: resonant low POLE climbing 199->1789 Hz (r 0.991->0.9966, Q blooms
//!       to 0.9991) against a unit-radius high cliff zero climbing
//!       6.4k->17.3k. The pair self-balances at DC (-53 dB + +54 dB).
//! Q moves centers here — the measured ROM Secondary law, authored
//! explicitly per corner (Q is never derived).
//!
//! P12 keeps its vowel ridges (lanes 2-4) and high cliff (lane 5); its
//! static sub floor (lane 1) and canyon (lane 6) are re-authored to the
//! measured law above. Roots + gains re-expressed through the one-owner
//! compiler — no packed words copied.

use forge_model::packed::{import, project, CORNERS};
use forge_model::{Mode, RootPair};
use std::path::PathBuf;

fn mode(ph: f64, pr: f64, zh: f64, zr: f64, gain: f64) -> Mode {
    Mode {
        pole: RootPair::Pair { hz: ph, r: pr },
        zero: RootPair::Pair { hz: zh, r: zr },
        gain,
        active: 1.0,
    }
}

fn main() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
    let bytes = std::fs::read(root.join("desk/sheets/VOWL_typed_p12.body240")).expect("P12");
    let mut design = import("VOWL_p12_hedz16", &bytes).expect("imports");

    // measured per-corner values (C0 M0Q0, C1 M100Q0, C2 M0Q100, C3 M100Q100)
    let s1 = [
        mode(9321.0, 0.9753, 347.0, 0.9354, 0.5619),
        mode(8376.0, 0.9622, 1711.0, 0.9438, 0.5216),
        mode(10158.0, 0.9990, 192.0, 0.9229, 0.5487),
        mode(8989.0, 0.9991, 1618.0, 0.9540, 0.5115),
    ];
    let s6 = [
        mode(199.0, 0.9912, 6396.0, 1.0, 0.5619),
        mode(1789.0, 0.9966, 17313.0, 1.0, 0.5216),
        mode(157.0, 0.9991, 6050.0, 1.0, 0.5487),
        mode(1509.0, 0.9991, 17313.0, 1.0, 0.5115),
    ];
    for (ci, &(m, q)) in CORNERS.iter().enumerate() {
        let anchor = design
            .anchors
            .iter_mut()
            .find(|a| a.morph == m && a.q == q)
            .expect("corner anchor");
        anchor.modes[0] = s1[ci];
        anchor.modes[5] = s6[ci];
    }

    let body = project(&design).expect("projects");
    let out = root.join("bodies/proofs");
    std::fs::create_dir_all(&out).unwrap();
    std::fs::write(out.join("VOWL_p12_hedz16.body240"), body).unwrap();
    std::fs::write(out.join("VOWL_p12_hedz16.design.json"), design.to_json()).unwrap();

    // stability over the full packed grid
    let pc = trench_core::minifloat::PackedCorners::from_body_bytes(&body).unwrap();
    let mut worst = 0.0f64;
    for qi in 0..17 {
        for mi in 0..17 {
            let rows = pc.interpolate_biquad(mi as f32 / 16.0, qi as f32 / 16.0);
            for r in rows.iter() {
                worst = worst.max(trench_core::minifloat::pole_radius(r[3], r[4]));
            }
        }
    }
    println!("VOWL_p12_hedz16: worst rho over 17x17 grid = {worst:.6}");
    assert!(worst < 1.0, "unstable");
    println!("wrote {}", out.join("VOWL_p12_hedz16.body240").display());
}
