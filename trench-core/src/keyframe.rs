//! User-authored per-wheel modulation — the "keyframe recorder".
//!
//! A wheel records two points (A = where it is, B = where you turned it to) and a
//! musical length, then ping-pongs A ⇄ B locked to the host clock. This is the
//! whole DSP of the feature; the UI is just a button that captures A/B and a
//! readout that sets the length.
//!
//! One owner: the math is HERE. C++ calls `trench_keyframe_value` (ffi), and the
//! render harness uses this same function, so the button and the audio can never
//! disagree about the shape.

use std::f64::consts::PI;

/// The movement shape a recording plays. One sine wobble served none of the real
/// jobs (riser / texture / drum hit); these are the shapes those jobs need.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u32)]
pub enum LoopMode {
    /// A ⇄ B, smooth sine swing, forever. TEXTURE, wobble, evolving pads.
    Pendulum = 0,
    /// A → B once over `leg_bars`, then HOLD at B. The RISER / uplifter — the
    /// thing a wobble physically cannot do.
    RiseHold = 1,
    /// A → B over `leg_bars`, snap back to A, repeat. Repeated risers, rhythmic
    /// builds, tempo'd sweeps.
    Saw = 2,
    /// A → B over `leg_bars` then B held, but the leg is FAST relative to the
    /// grid — a percussive one-shot per trigger. CUSTOM DRUM / transient morph.
    /// (Identical curve to RiseHold; named so the UI/trigger layer reads clearly.)
    OneShot = 3,
}

impl LoopMode {
    #[inline]
    pub fn from_u32(v: u32) -> Self {
        match v {
            1 => LoopMode::RiseHold,
            2 => LoopMode::Saw,
            3 => LoopMode::OneShot,
            _ => LoopMode::Pendulum,
        }
    }
}

/// Value of a recorded movement between `a` and `b` at musical position `ppq`.
///
/// - `a`, `b`     : the two recorded endpoints (wheel-normalised 0..1).
/// - `leg_bars`   : musical length of ONE leg (A→B). For `Pendulum` a full A→B→A
///   cycle is twice this — "travel to the target in N bars", how the control reads.
/// - `ppq`        : quarter-note position from the host (`AudioPlayHead` ppqPosition).
///   For one-shot modes this is measured from the trigger point (the caller zeroes
///   it on transport start / note); for looping modes it free-runs.
/// - `beats_per_bar`: from the host time signature (4 if unknown).
/// - `mode`       : the movement shape.
///
/// Curves ease at the endpoints (raised cosine) so a resonant wheel does not
/// corner — a hard triangle clicks the filter.
#[inline]
pub fn keyframe_loop_value_mode(
    a: f32,
    b: f32,
    leg_bars: f32,
    ppq: f64,
    beats_per_bar: f64,
    mode: LoopMode,
) -> f32 {
    let leg_beats = leg_bars as f64 * beats_per_bar.max(1.0);
    if leg_beats <= 0.0 {
        return a;
    }
    let lerp = |t: f64| (a as f64 + (b as f64 - a as f64) * t) as f32;
    // raised-cosine ease of a 0..1 progress value
    let ease = |t: f64| 0.5 - 0.5 * (PI * t.clamp(0.0, 1.0)).cos();

    match mode {
        LoopMode::Pendulum => {
            let cycle = 2.0 * leg_beats;
            let phase = (ppq / cycle).rem_euclid(1.0);
            lerp(0.5 - 0.5 * (2.0 * PI * phase).cos()) // 0→1→0
        }
        LoopMode::RiseHold | LoopMode::OneShot => {
            // progress from the trigger; hold B once the leg completes
            let t = (ppq / leg_beats).max(0.0);
            lerp(ease(t.min(1.0)))
        }
        LoopMode::Saw => {
            let t = (ppq / leg_beats).rem_euclid(1.0); // 0→1, snap, repeat
            lerp(ease(t))
        }
    }
}

/// Back-compat pendulum entry (the original shape).
#[inline]
pub fn keyframe_loop_value(a: f32, b: f32, leg_bars: f32, ppq: f64, beats_per_bar: f64) -> f32 {
    keyframe_loop_value_mode(a, b, leg_bars, ppq, beats_per_bar, LoopMode::Pendulum)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lands_on_a_at_cycle_start() {
        // ppq 0 and any whole cycle later must be exactly A.
        let v0 = keyframe_loop_value(0.2, 0.8, 2.0, 0.0, 4.0);
        let vcycle = keyframe_loop_value(0.2, 0.8, 2.0, 16.0, 4.0); // 2 bars * 4 * 2 legs
        assert!((v0 - 0.2).abs() < 1e-6, "start should be A, got {v0}");
        assert!((vcycle - 0.2).abs() < 1e-5, "full cycle should return to A, got {vcycle}");
    }

    #[test]
    fn reaches_b_at_half_cycle() {
        // A→B leg is leg_bars long → B at ppq = leg_bars * beats_per_bar.
        let v = keyframe_loop_value(0.2, 0.8, 2.0, 8.0, 4.0); // 2 bars * 4 beats
        assert!((v - 0.8).abs() < 1e-5, "half cycle should be B, got {v}");
    }

    #[test]
    fn pendulum_is_symmetric() {
        // The swing out and the swing back must mirror around the B turnaround.
        for d in [0.5f64, 1.0, 1.7, 3.3] {
            let out = keyframe_loop_value(0.0, 1.0, 1.0, 4.0 - d, 4.0);
            let back = keyframe_loop_value(0.0, 1.0, 1.0, 4.0 + d, 4.0);
            assert!((out - back).abs() < 1e-5, "asymmetric at +/-{d}: {out} vs {back}");
        }
    }

    #[test]
    fn stays_within_the_endpoints() {
        // Never overshoots A..B — a filter wheel must not be driven out of range.
        let (a, b) = (0.3f32, 0.9f32);
        for i in 0..1000 {
            let ppq = i as f64 * 0.031;
            let v = keyframe_loop_value(a, b, 1.5, ppq, 4.0);
            assert!(v >= a - 1e-6 && v <= b + 1e-6, "out of range at ppq {ppq}: {v}");
        }
    }

    #[test]
    fn zero_length_holds_a() {
        assert_eq!(keyframe_loop_value(0.4, 0.9, 0.0, 12.0, 4.0), 0.4);
    }

    #[test]
    fn negative_ppq_is_handled() {
        // Some hosts report negative ppq during count-in; must not NaN or jump.
        let v = keyframe_loop_value(0.2, 0.8, 2.0, -3.0, 4.0);
        assert!(v.is_finite() && (0.2..=0.8).contains(&v));
    }

    #[test]
    fn rise_hold_reaches_b_and_stays() {
        // The riser: climbs A→B over the leg, then holds B forever.
        let m = LoopMode::RiseHold;
        assert!((keyframe_loop_value_mode(0.2, 0.9, 4.0, 0.0, 4.0, m) - 0.2).abs() < 1e-6);
        let at_b = keyframe_loop_value_mode(0.2, 0.9, 4.0, 16.0, 4.0, m); // 4 bars * 4
        assert!((at_b - 0.9).abs() < 1e-5, "should reach B, got {at_b}");
        let held = keyframe_loop_value_mode(0.2, 0.9, 4.0, 999.0, 4.0, m);
        assert!((held - 0.9).abs() < 1e-6, "should HOLD B, got {held}");
    }

    #[test]
    fn saw_resets_to_a_each_cycle() {
        let m = LoopMode::Saw;
        let start = keyframe_loop_value_mode(0.1, 0.7, 2.0, 0.0, 4.0, m);
        let after_cycle = keyframe_loop_value_mode(0.1, 0.7, 2.0, 8.0, 4.0, m); // one leg later
        assert!((start - 0.1).abs() < 1e-5);
        assert!((after_cycle - 0.1).abs() < 1e-4, "saw should snap back to A, got {after_cycle}");
    }

    #[test]
    fn every_mode_stays_in_range() {
        for mv in [0u32, 1, 2, 3] {
            let m = LoopMode::from_u32(mv);
            for i in 0..500 {
                let v = keyframe_loop_value_mode(0.25, 0.85, 3.0, i as f64 * 0.07, 4.0, m);
                assert!(v >= 0.25 - 1e-5 && v <= 0.85 + 1e-5, "mode {mv} out of range: {v}");
            }
        }
    }
}

#[cfg(test)]
mod render {
    use super::*;
    use crate::cartridge::Cartridge;
    use crate::engine::FilterEngine;

    /// Render a MORPH wheel ping-ponging between two recorded points, tempo-synced.
    /// This drives the shipping engine's morph with `keyframe_loop_value` exactly
    /// as the plug-in will, so the sound IS the feature, not an approximation.
    ///   cargo test -p trench-core --lib render_keyframe_demo -- --ignored --nocapture
    #[test]
    #[ignore = "renders the keyframe-recorder demo wav"]
    fn render_keyframe_demo() {
        const SR: f64 = 39_062.5;
        const OUT: u32 = 44_100;
        const BPM: f64 = 120.0;
        const BEATS_PER_BAR: f64 = 4.0;
        const BARS_TOTAL: f64 = 8.0;

        let body = std::fs::read("../filters/bodies/CAVL_mason_jar_to_stone_pipe.body240").unwrap();

        // Render one take: (name, A, B, leg_bars, mode).
        let takes = [
            ("texture_pendulum_0.2-0.8_2bar", 0.2f32, 0.8f32, 2.0f32, LoopMode::Pendulum),
            ("RISER_0.0-1.0_8bar", 0.0, 1.0, 8.0, LoopMode::RiseHold),
            ("build_saw_0.1-0.9_1bar", 0.1, 0.9, 1.0, LoopMode::Saw),
        ];

        let dir = "C:/Users/hooki/df2-workstation/out/keyframe_demo";
        std::fs::create_dir_all(dir).unwrap();
        println!("\n  keyframe recorder — {BPM} bpm, mason_jar_to_stone_pipe, Q100\n");

        for (name, a, b, leg_bars, mode) in takes {
            let mut eng = FilterEngine::new();
            eng.prepare(SR);
            eng.load_cartridge(Cartridge::from_body_bytes("d", &body, 1.0).unwrap());

            let secs = BARS_TOTAL * BEATS_PER_BAR * 60.0 / BPM;
            let n = (secs * SR) as usize;
            const HB: usize = 128;
            let mut rng = 0x2545_F491_4F6C_DD1Du64;
            let mut pb = [0f64; 7];
            let mut out: Vec<f32> = Vec::with_capacity(n);
            let mut off = 0;
            while off < n {
                let len = HB.min(n - off);
                let ppq = (off + len / 2) as f64 / SR * BPM / 60.0;
                let morph = keyframe_loop_value_mode(a, b, leg_bars, ppq, BEATS_PER_BAR, mode);
                let mut l: Vec<f32> = (0..len).map(|_| {
                    rng = rng.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
                    let w = ((rng >> 40) as f64 / (1u64 << 23) as f64) - 1.0;
                    pb[0]=0.99886*pb[0]+w*0.0555179; pb[1]=0.99332*pb[1]+w*0.0750759;
                    pb[2]=0.96900*pb[2]+w*0.1538520; pb[3]=0.86650*pb[3]+w*0.3104856;
                    pb[4]=0.55000*pb[4]+w*0.5329522; pb[5]=-0.7616*pb[5]-w*0.0168980;
                    let s=(pb[0]+pb[1]+pb[2]+pb[3]+pb[4]+pb[5]+pb[6]+w*0.5362)*0.11;
                    pb[6]=w*0.115926;
                    (s*0.6) as f32
                }).collect();
                let mut r = l.clone();
                eng.process_block(&mut l, &mut r, morph as f64, 1.0);
                out.extend_from_slice(&l);
                off += len;
            }
            let ratio = SR / OUT as f64;
            let on = (out.len() as f64 / ratio) as usize;
            let mut v: Vec<f32> = (0..on).map(|i| {
                let p = i as f64 * ratio; let i0 = p.floor() as usize;
                let f = (p - i0 as f64) as f32;
                let x = out.get(i0).copied().unwrap_or(0.0);
                let y = out.get(i0 + 1).copied().unwrap_or(x);
                x + (y - x) * f
            }).collect();
            let pk = v.iter().fold(0.0f32, |m, &x| m.max(x.abs())).max(1e-9);
            let g = 0.5012 / pk;
            for x in v.iter_mut() { *x *= g; }
            let mut w = Vec::new();
            let dl = (v.len() * 2) as u32;
            w.extend_from_slice(b"RIFF"); w.extend_from_slice(&(36 + dl).to_le_bytes());
            w.extend_from_slice(b"WAVEfmt "); w.extend_from_slice(&16u32.to_le_bytes());
            w.extend_from_slice(&1u16.to_le_bytes()); w.extend_from_slice(&1u16.to_le_bytes());
            w.extend_from_slice(&OUT.to_le_bytes()); w.extend_from_slice(&(OUT * 2).to_le_bytes());
            w.extend_from_slice(&2u16.to_le_bytes()); w.extend_from_slice(&16u16.to_le_bytes());
            w.extend_from_slice(b"data"); w.extend_from_slice(&dl.to_le_bytes());
            for &x in &v { w.extend_from_slice(&((x.clamp(-1.0,1.0)*32767.0) as i16).to_le_bytes()); }
            let p = format!("{dir}/{name}.wav");
            std::fs::write(&p, w).unwrap();
            println!("  {p}");
        }
    }
}
