//! Integration tests for `function_generator` (Task 6).
//!
//! The generator is authored in terms of `ModFnBlock` (cartridge type). These
//! tests build `ModFnBlock`s by JSON so we exercise the same path a real
//! cartridge would take.

use trench_core::cartridge::{FnSegment, ModFnBlock};
use trench_core::function_generator::FunctionGenerator;

// Helper: build a ModFnBlock from parts (avoids re-parsing JSON per test).
fn block(segments: Vec<FnSegment>, key_sync: bool, tempo_sync: bool) -> ModFnBlock {
    ModFnBlock {
        segments,
        key_sync_int: if key_sync { 1 } else { 0 },
        tempo_sync_int: if tempo_sync { 1 } else { 0 },
    }
}

fn seg(level: f32, time_ms: f32, shape: &str, jump: Option<i32>) -> FnSegment {
    FnSegment {
        level,
        time_ms,
        shape: shape.to_string(),
        jump,
    }
}

const SR: f32 = 48_000.0;

#[test]
fn function_generator_outputs_0_with_no_segments() {
    let mut fg = FunctionGenerator::new(SR);
    // No load() call → no segments loaded.
    for _ in 0..1000 {
        let y = fg.tick();
        assert_eq!(y, 0.0, "unloaded generator must output 0");
    }
}

#[test]
fn linear_segment_midpoint() {
    let mut fg = FunctionGenerator::new(SR);
    let b = block(vec![seg(1.0, 1000.0, "lin", None)], false, false);
    fg.load(&b);
    // Advance 24000 samples = 500 ms of 1000 ms segment → midpoint.
    let mut last = 0.0;
    for _ in 0..24_000 {
        last = fg.tick();
    }
    assert!(
        (last - 0.5).abs() < 0.01,
        "linear midpoint expected ~0.5, got {last}"
    );
}

// ── Parametric shape tests (ramp 0 → 1 over 100 ms at 48 kHz) ──
//
// Shape function definitions (must match the module comment in
// `function_generator.rs`):
//   hold    : y(t) = start                (output never moves toward target)
//   lin     : y(t) = start + (end-start)*t
//   exp     : y(t) = start + (end-start)*t*t                (concave-up)
//   log     : y(t) = start + (end-start)*(1 - (1-t)*(1-t))  (concave-down)
//   sCurve  : y(t) = start + (end-start)*(3t^2 - 2t^3)      (smoothstep)

fn run_shape_midpoint(shape: &str) -> f32 {
    let mut fg = FunctionGenerator::new(SR);
    let b = block(vec![seg(1.0, 100.0, shape, None)], false, false);
    fg.load(&b);
    // 100 ms at 48 kHz = 4800 samples. Midpoint at 2400.
    let mut last = 0.0;
    for _ in 0..2_400 {
        last = fg.tick();
    }
    last
}

#[test]
fn shape_hold_midpoint() {
    let y = run_shape_midpoint("hold");
    assert!(
        (y - 0.0).abs() < 1e-3,
        "hold midpoint expected ~0.0, got {y}"
    );
}

#[test]
fn shape_lin_midpoint() {
    let y = run_shape_midpoint("lin");
    assert!(
        (y - 0.5).abs() < 1e-3,
        "lin midpoint expected ~0.5, got {y}"
    );
}

#[test]
fn shape_exp_midpoint() {
    let y = run_shape_midpoint("exp");
    // exp = t*t → midpoint 0.25
    assert!(
        (y - 0.25).abs() < 1e-3,
        "exp midpoint expected ~0.25, got {y}"
    );
}

#[test]
fn shape_log_midpoint() {
    let y = run_shape_midpoint("log");
    // log = 1 - (1-t)^2 → midpoint 0.75
    assert!(
        (y - 0.75).abs() < 1e-3,
        "log midpoint expected ~0.75, got {y}"
    );
}

#[test]
fn shape_scurve_midpoint() {
    let y = run_shape_midpoint("sCurve");
    // smoothstep 3t^2 - 2t^3 → midpoint 0.5
    assert!(
        (y - 0.5).abs() < 1e-3,
        "sCurve midpoint expected ~0.5, got {y}"
    );
}

#[test]
fn conditional_jump_loops() {
    // Seg 0: instant hold at 0 (zero-duration).
    // Seg 1: ramp 0 → 1 over 100 ms.
    // Seg 2: ramp 1 → 0.5 over 100 ms, then jump to segment 1.
    let segs = vec![
        seg(0.0, 0.0, "hold", None),
        seg(1.0, 100.0, "lin", None),
        seg(0.5, 100.0, "lin", Some(1)),
    ];
    let b = block(segs, false, false);
    let mut fg = FunctionGenerator::new(SR);
    fg.load(&b);

    // Run forever: sample the output at many points. If jumps did NOT loop,
    // the generator would go silent after ~200 ms. We check that after
    // 1000 ms (5× the segment group) there is still non-trivial motion.
    let mut saw_high_after_loop = false;
    let mut saw_low_after_loop = false;
    // Advance past the first two segments (200 ms = 9600 samples).
    for _ in 0..9_600 {
        fg.tick();
    }
    // Now we're in loop territory. Sample another 600 ms.
    for i in 0..28_800 {
        let y = fg.tick();
        // Inside segment 1 the ramp climbs from 0.5 → 1.
        // Inside segment 2 the ramp descends from 1 → 0.5.
        if y > 0.9 {
            saw_high_after_loop = true;
        }
        if y < 0.6 {
            saw_low_after_loop = true;
        }
        if saw_high_after_loop && saw_low_after_loop && i > 10_000 {
            break;
        }
    }
    assert!(
        saw_high_after_loop,
        "expected to see a post-loop peak ≥0.9 — did the jump fail?"
    );
    assert!(
        saw_low_after_loop,
        "expected to see a post-loop trough ≤0.6 — did the jump fail?"
    );
}

#[test]
fn key_sync_restarts() {
    let segs = vec![seg(1.0, 100.0, "lin", None)];
    let b = block(segs, true, false); // key_sync on
    let mut fg = FunctionGenerator::new(SR);
    fg.load(&b);

    // Advance 500 samples.
    for _ in 0..500 {
        fg.tick();
    }
    // Now reset via note_on.
    fg.note_on();
    // First tick after reset should be at (or near) segment 0's starting
    // value, which — for a single-segment generator starting at 0 — is 0.0
    // evaluated at t=0 of a linear ramp from 0 → 1. We allow a tiny epsilon
    // for "one sample into the ramp" since tick advances state.
    let first = fg.tick();
    assert!(
        first.abs() < 1e-3,
        "after note_on, first tick should be near 0.0, got {first}"
    );
}

#[test]
fn rev_time_reverses_trajectory() {
    // 0 → 1 over 100 ms, then 1 → 0 over 100 ms. Symmetric tent.
    let segs = vec![seg(1.0, 100.0, "lin", None), seg(0.0, 100.0, "lin", None)];
    let b = block(segs, false, false);
    const N: usize = 9_600; // 200 ms @ 48 kHz

    // Render both forward and reverse over exactly N ticks.
    let mut fwd = vec![0.0f32; N];
    {
        let mut fg = FunctionGenerator::new(SR);
        fg.load(&b);
        for v in fwd.iter_mut() {
            *v = fg.tick();
        }
    }

    let mut rev = vec![0.0f32; N];
    {
        let mut fg = FunctionGenerator::new(SR);
        fg.load(&b);
        fg.set_reverse(true);
        for v in rev.iter_mut() {
            *v = fg.tick();
        }
    }

    // REV playback is the time-reversal of FWD playback. Because `tick()`
    // returns y at the *current* sample_in_seg and then advances, the two
    // streams align at the mid-sample granularity. We assert the whole
    // reversed stream matches FWD within a tight tolerance.
    //
    // Specifically: rev[k] ≈ fwd[N - 1 - k]  modulo tiny off-by-one at
    // segment boundaries, which we absorb by comparing rev[k] against
    // fwd[N - 1 - k] with a per-sample tolerance accounting for the
    // single-sample step between forward and reversed phases.
    for k in 0..N {
        let expected = fwd[N - 1 - k];
        let got = rev[k];
        assert!(
            (got - expected).abs() < 1e-4,
            "REV sample {k} expected {expected}, got {got}"
        );
    }

    // Spot-check the spec: take 20 evenly-spaced samples and compare
    // rev[i] to fwd[N - 1 - i] (the authoritative rule).
    let step = N / 20;
    for i in 0..20 {
        let k = i * step;
        let j = N - 1 - k;
        assert!(
            (rev[k] - fwd[j]).abs() < 1e-4,
            "REV[{k}]={} vs FWD[{j}]={} mismatch",
            rev[k],
            fwd[j]
        );
    }
}

#[test]
fn tempo_sync_scales_time() {
    // time_ms = 500 with tempo_sync=1 means "500 ms at 120 BPM".
    // At BPM 120, 500 ms of samples to reach 1.0.
    // At BPM 60,  1000 ms of samples to reach 1.0 (half as fast).
    let segs = vec![seg(1.0, 500.0, "lin", None)];
    let b = block(segs, false, true); // tempo_sync on

    let threshold = 0.999_f32;

    // ── 120 BPM run ──
    let samples_120 = {
        let mut fg = FunctionGenerator::new(SR);
        fg.set_tempo_bpm(120.0);
        fg.load(&b);
        let mut count = 0usize;
        for i in 0..(SR as usize * 3) {
            let y = fg.tick();
            if y >= threshold {
                count = i + 1;
                break;
            }
        }
        count
    };

    // ── 60 BPM run ──
    let samples_60 = {
        let mut fg = FunctionGenerator::new(SR);
        fg.set_tempo_bpm(60.0);
        fg.load(&b);
        let mut count = 0usize;
        for i in 0..(SR as usize * 5) {
            let y = fg.tick();
            if y >= threshold {
                count = i + 1;
                break;
            }
        }
        count
    };

    assert!(samples_120 > 0, "120 BPM: never reached threshold");
    assert!(samples_60 > 0, "60 BPM: never reached threshold");

    // At 60 BPM the segment should take roughly 2x as many samples as at 120 BPM.
    let ratio = samples_60 as f32 / samples_120 as f32;
    assert!(
        (ratio - 2.0).abs() < 0.05,
        "expected BPM-60/BPM-120 sample-count ratio ≈ 2.0, got {ratio} \
         (samples_120={samples_120}, samples_60={samples_60})"
    );

    // Sanity: 120 BPM should be in the vicinity of 500 ms = 24000 samples.
    let expected_120 = (SR * 0.5) as usize;
    let tol = (expected_120 as f32 * 0.05) as usize;
    assert!(
        samples_120.abs_diff(expected_120) <= tol,
        "120 BPM sample count {samples_120} not within 5% of {expected_120}"
    );
}

#[test]
fn key_sync_false_does_not_reset_on_note_on() {
    // key-sync = 0: free-run LFO. note_on() must not move the phase.
    let mut fg = FunctionGenerator::new(48_000.0);
    let block = ModFnBlock {
        segments: vec![
            FnSegment {
                level: 0.0,
                time_ms: 0.0,
                shape: "hold".into(),
                jump: None,
            },
            FnSegment {
                level: 1.0,
                time_ms: 500.0,
                shape: "lin".into(),
                jump: None,
            },
        ],
        key_sync_int: 0, // free-run
        tempo_sync_int: 0,
    };
    fg.load(&block);

    // Advance 12000 samples (≈250ms, mid-ramp at 48kHz). Expected output around 0.5.
    for _ in 0..12_000 {
        fg.tick();
    }
    let before_note_on = fg.tick();

    fg.note_on(); // should be a no-op when key_sync = false

    let after_note_on = fg.tick();
    // If key_sync=false was honored, the next sample is one step further down the
    // same ramp, not reset to 0. Tolerance is one sample's worth of progress.
    let ramp_step = 1.0 / 24_000.0; // lin 0->1 over 500ms @ 48kHz = 24000 samples
    assert!(
        (after_note_on - before_note_on).abs() < ramp_step * 4.0,
        "key_sync=false should free-run; got {} -> {}",
        before_note_on,
        after_note_on
    );
}

#[test]
fn forward_skip_jump_advances_past_later_segments() {
    // 4 segments; segment 1 jumps forward to segment 3 on end.
    // Verifies that jump targets can be > index + 1 (forward skip, not just backward loop).
    let mut fg = FunctionGenerator::new(48_000.0);
    let block = ModFnBlock {
        segments: vec![
            FnSegment {
                level: 0.0,
                time_ms: 0.0,
                shape: "hold".into(),
                jump: None,
            },
            FnSegment {
                level: 0.5,
                time_ms: 100.0,
                shape: "lin".into(),
                jump: Some(3),
            }, // skip seg 2
            FnSegment {
                level: 0.2,
                time_ms: 100.0,
                shape: "lin".into(),
                jump: None,
            }, // should NEVER be reached
            FnSegment {
                level: 1.0,
                time_ms: 100.0,
                shape: "lin".into(),
                jump: None,
            },
        ],
        key_sync_int: 1,
        tempo_sync_int: 0,
    };
    fg.load(&block);

    // Run past segment 1 end (100ms @ 48kHz = 4800 samples, plus segment 0 which is 0ms),
    // then run through what would be segment 2 (another 100ms). If the skip worked,
    // we should now be ramping from 0.5 (segment 1 end) to 1.0 (segment 3 target),
    // NOT from 0.5 back down to 0.2.
    for _ in 0..7200 {
        fg.tick();
    } // 150ms total: past seg 1, midway through what would be seg 3
    let out = fg.tick();
    assert!(
        out > 0.6,
        "Expected rising toward 1.0 (segment 3); got {out} (probably fell into segment 2)"
    );
}

#[test]
fn negative_levels_work_and_midpoint_matches_linear() {
    // A segment ramping from 0.0 to -0.7 should produce -0.35 at midpoint for lin shape.
    let mut fg = FunctionGenerator::new(48_000.0);
    let block = ModFnBlock {
        segments: vec![
            FnSegment {
                level: 0.0,
                time_ms: 0.0,
                shape: "hold".into(),
                jump: None,
            },
            FnSegment {
                level: -0.7,
                time_ms: 100.0,
                shape: "lin".into(),
                jump: None,
            },
        ],
        key_sync_int: 1,
        tempo_sync_int: 0,
    };
    fg.load(&block);
    for _ in 0..2400 {
        fg.tick();
    } // 50ms = midpoint of a 100ms segment at 48kHz
    let out = fg.tick();
    assert!(
        (out - (-0.35)).abs() < 1e-2,
        "Expected ~-0.35 at midpoint; got {out}"
    );
}

#[test]
fn out_of_range_level_is_clamped_to_unit_interval() {
    // Authored level of 2.5 is out of [-1,1]. tick() must clamp to 1.0 while
    // the ramp is still running. (Spec: when segments exhaust with no jump
    // the generator goes Idle and emits 0.0, so we probe near the end of the
    // ramp while still in-segment, where the unclamped value well exceeds 1.)
    let mut fg = FunctionGenerator::new(48_000.0);
    let block = ModFnBlock {
        segments: vec![
            FnSegment {
                level: 0.0,
                time_ms: 0.0,
                shape: "hold".into(),
                jump: None,
            },
            FnSegment {
                level: 2.5,
                time_ms: 10.0,
                shape: "lin".into(),
                jump: None,
            },
        ],
        key_sync_int: 1,
        tempo_sync_int: 0,
    };
    fg.load(&block);
    // 10 ms at 48 kHz = 480 samples. Advance to late-segment so the
    // unclamped ramp value is ~0.83 * 2.5 ≈ 2.08 and must clamp to 1.0.
    for _ in 0..400 {
        fg.tick();
    }
    let out = fg.tick();
    assert!(
        out <= 1.0 + 1e-6,
        "Expected output clamped to <=1.0; got {out}"
    );
    assert!(
        out >= 0.99,
        "Expected output at/near clamp ceiling 1.0; got {out}"
    );
}

#[test]
fn one_sample_segment_advances_correctly_forward_and_rev() {
    // time_ms so small it rounds to 1-sample length. Must not panic or stall.
    let mut fg = FunctionGenerator::new(48_000.0);
    let block = ModFnBlock {
        segments: vec![
            FnSegment {
                level: 0.0,
                time_ms: 0.0,
                shape: "hold".into(),
                jump: None,
            },
            FnSegment {
                level: 1.0,
                time_ms: 0.01,
                shape: "lin".into(),
                jump: None,
            }, // < 1 sample at 48kHz
            FnSegment {
                level: 0.0,
                time_ms: 100.0,
                shape: "lin".into(),
                jump: None,
            },
        ],
        key_sync_int: 1,
        tempo_sync_int: 0,
    };
    fg.load(&block);

    // Forward: generator must progress through the 1-sample segment without hanging.
    let mut hit_high = false;
    for _ in 0..100 {
        let o = fg.tick();
        if o > 0.5 {
            hit_high = true;
        }
    }
    assert!(
        hit_high,
        "Forward: 1-sample segment should allow output to briefly reach near 1.0"
    );

    // REV: same thing, time-reversed. Must not hang or panic.
    fg.set_reverse(true);
    fg.note_on();
    for _ in 0..100 {
        fg.tick();
    } // don't crash
}
