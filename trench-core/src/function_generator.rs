//! E-mu-style 8-segment function generator (Task 6).
//!
//! Drives MORPH (and potentially other modulation destinations) from a
//! baked `ModFnBlock` attached to a cartridge. Each segment has a target
//! level, a duration in milliseconds, a curve shape, and an optional
//! jump-to-index that fires when the segment completes.
//!
//! ## Shape functions (authoritative)
//!
//! For a segment ramping from `start` → `end` with normalized progress
//! `t ∈ [0, 1]`:
//!
//! | shape    | formula                                         |
//! |----------|-------------------------------------------------|
//! | `hold`   | `start`                                         |
//! | `lin`    | `start + (end - start) * t`                     |
//! | `exp`    | `start + (end - start) * t*t`          (concave-up) |
//! | `log`    | `start + (end - start) * (1 - (1 - t)*(1 - t))`   (concave-down) |
//! | `sCurve` | `start + (end - start) * (3t² - 2t³)`    (smoothstep) |
//!
//! Unknown shapes fall back to `lin`.
//!
//! ## Sync flags
//!
//! - `key_sync = true` → `note_on()` resets segment index and phase
//!   (or end-of-last-segment in REV mode).
//! - `key_sync = false` → `note_on()` is a no-op; the generator free-runs
//!   (LFO semantics).
//! - `tempo_sync = true` → `time_ms` is interpreted as "milliseconds at
//!   120 BPM" and scaled by `120 / tempo_bpm` at runtime. (Authored
//!   `time_ms = 500` with `tempo_sync = 1` → 500 ms at 120 BPM, 1000 ms
//!   at 60 BPM.)
//!
//! ## REV (time-reverse)
//!
//! When `set_reverse(true)` is in effect, segments are traversed in
//! reverse order and each segment's shape is evaluated with `(1 - t)`.
//! Jumps are **not** honored in reverse mode — they are a playback-
//! forward-only feature per spec. `note_on()` resets to the END of the
//! last segment when reverse is engaged.
//!
//! ## Contract
//!
//! - No allocations in `tick()`. `load()` is the only allocation site.
//! - `tick()` output is clamped to `[-1.0, 1.0]`.
//! - When no segments are loaded (or the generator has run off the end
//!   of the segment list with no jump), `tick()` returns `0.0`.

use crate::cartridge::ModFnBlock;

/// Output clamp range.
const OUT_MIN: f32 = -1.0;
const OUT_MAX: f32 = 1.0;

/// Segment curve shape (parsed from authored string at `load()` time).
///
/// The DTO type `cartridge::FnSegment` stores `shape` as a `String` (serde
/// contract), but at runtime the generator works with this enum so the
/// per-sample dispatch in `tick()` is a cheap integer branch instead of
/// a string compare. Also gives the upcoming C++ port a 1:1 type to
/// mirror rather than a bag of string literals.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SegmentShape {
    Hold,
    Lin,
    Exp,
    Log,
    SCurve,
}

impl SegmentShape {
    /// Parse an authored shape string into the enum. Unknown strings fall
    /// back silently to `Lin` — matches the prior `evaluate_shape` default
    /// branch so cartridge behavior is unchanged.
    pub fn from_str(s: &str) -> Self {
        match s {
            "hold" => SegmentShape::Hold,
            "lin" => SegmentShape::Lin,
            "exp" => SegmentShape::Exp,
            "log" => SegmentShape::Log,
            "sCurve" => SegmentShape::SCurve,
            _ => SegmentShape::Lin, // silent fallback (matches prior behavior)
        }
    }
}

/// Internal (post-parse) representation of a function-generator segment.
/// Distinct from `cartridge::FnSegment` so the runtime never re-parses a
/// string per sample.
#[derive(Debug, Clone, Copy)]
struct InternalSegment {
    level: f32,
    time_ms: f32,
    shape: SegmentShape,
    jump: Option<i32>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum State {
    /// No segments loaded, or we've fallen off the end without a jump.
    Idle,
    /// Running a segment at `index` (valid into `segments`).
    Running { index: usize, sample_in_seg: u64 },
}

pub struct FunctionGenerator {
    sample_rate: f32,
    segments: Vec<InternalSegment>,
    key_sync: bool,
    tempo_sync: bool,
    tempo_bpm: f32,
    reverse: bool,
    state: State,
    /// Level emitted by the previous segment's completion (or the authored
    /// "starting level" for segment 0 = 0.0). Used as the `start` of the
    /// active segment's ramp.
    prev_level: f32,
    /// Last emitted sample (useful for `key_sync_restarts` / debugging).
    last_out: f32,
}

impl FunctionGenerator {
    pub fn new(sample_rate: f32) -> Self {
        Self {
            sample_rate: sample_rate.max(1.0),
            segments: Vec::new(),
            key_sync: false,
            tempo_sync: false,
            tempo_bpm: 120.0,
            reverse: false,
            state: State::Idle,
            prev_level: 0.0,
            last_out: 0.0,
        }
    }

    /// Load a function-generator program from a `ModFnBlock`. Allocates
    /// exactly once to copy (and parse) the segment list. Shape strings are
    /// resolved to `SegmentShape` here so `tick()` never touches strings.
    pub fn load(&mut self, block: &ModFnBlock) {
        self.segments.clear();
        self.segments.reserve(block.segments.len());
        for s in &block.segments {
            self.segments.push(InternalSegment {
                level: s.level,
                time_ms: s.time_ms,
                shape: SegmentShape::from_str(&s.shape),
                jump: s.jump,
            });
        }
        self.key_sync = block.key_sync();
        self.tempo_sync = block.tempo_sync();
        self.prev_level = 0.0;
        self.last_out = 0.0;
        self.rearm_from_start();
    }

    /// Reset segment index + phase when `key_sync` is true. When
    /// `key_sync = false`, `note_on()` is a no-op and the generator
    /// free-runs (LFO semantics).
    pub fn note_on(&mut self) {
        if !self.key_sync {
            return;
        }
        self.prev_level = 0.0;
        self.last_out = 0.0;
        self.rearm_from_start();
    }

    /// Set reverse playback. Changing direction re-arms the generator at
    /// the appropriate end (start of first seg fwd; end of last seg rev).
    pub fn set_reverse(&mut self, rev: bool) {
        if self.reverse != rev {
            self.reverse = rev;
            // Re-arm so the caller can immediately start ticking at the
            // new "start" boundary. Drivers that want to keep playing
            // from the current phase can avoid toggling mid-playback.
            self.rearm_from_start();
        }
    }

    pub fn set_tempo_bpm(&mut self, bpm: f32) {
        // Clamp to something sane to avoid div-by-zero or negative durations.
        self.tempo_bpm = bpm.max(1.0e-3);
    }

    /// Reset to idle. Keeps the loaded program.
    pub fn reset(&mut self) {
        self.prev_level = 0.0;
        self.last_out = 0.0;
        self.rearm_from_start();
    }

    #[inline]
    fn rearm_from_start(&mut self) {
        if self.segments.is_empty() {
            self.state = State::Idle;
            return;
        }
        let idx = if self.reverse {
            self.segments.len() - 1
        } else {
            0
        };
        // `prev_level` must equal the AUTHORED start level of segment `idx`.
        // For segment 0 that's 0.0; for segment i>0 that's segments[i-1].level.
        self.prev_level = if idx == 0 {
            0.0
        } else {
            self.segments[idx - 1].level
        };
        self.state = State::Running {
            index: idx,
            sample_in_seg: 0,
        };
    }

    /// Effective duration of a segment in samples. At least 1 sample so
    /// ramps can't divide by zero and zero-duration segments advance on
    /// the next tick.
    #[inline]
    fn segment_length_samples(&self, seg: &InternalSegment) -> u64 {
        let ms = if self.tempo_sync {
            seg.time_ms * (120.0 / self.tempo_bpm)
        } else {
            seg.time_ms
        };
        // samples = ms / 1000 * sample_rate
        let s = (ms * 0.001 * self.sample_rate).round() as i64;
        if s < 1 {
            1
        } else {
            s as u64
        }
    }

    /// Evaluate one sample. Never allocates.
    pub fn tick(&mut self) -> f32 {
        let State::Running {
            index,
            sample_in_seg,
        } = self.state
        else {
            self.last_out = 0.0;
            return 0.0;
        };

        // Bounds guard (should always hold).
        if index >= self.segments.len() {
            self.state = State::Idle;
            self.last_out = 0.0;
            return 0.0;
        }

        let seg = &self.segments[index];
        let len = self.segment_length_samples(seg);
        // t ∈ [0, 1]. When len == 1 this degenerates to "complete on next tick".
        let t = (sample_in_seg as f32 / len as f32).min(1.0);
        // In reverse mode the authored trajectory is played end-to-start.
        // Spec §REV says "evaluate shape with t replaced by (1 - t)". To
        // keep the discrete-grid time-reverse invariant exact (rev[k] ≈
        // fwd[N-1-k]), we mirror across the samples actually emitted:
        //    fwd emits at t ∈ {0, 1/len, ..., (len-1)/len}
        //    rev emits the same set in reverse: t ∈ {(len-1)/len, ..., 0}
        // i.e. rev's t_eff at sample_in_seg = s is (len-1-s)/len.
        let t_eff = if self.reverse {
            if len <= 1 {
                0.0
            } else {
                let inv = (len - 1 - sample_in_seg) as f32 / len as f32;
                inv.clamp(0.0, 1.0)
            }
        } else {
            t
        };

        // Compute ramp endpoints. In forward mode the ramp goes from
        // `prev_level` to `seg.level`. In reverse mode we still render
        // the authored shape between the same two endpoints — using
        // (1 - t) flips direction in-place.
        let start = self.prev_level;
        let end = seg.level;
        let y = evaluate_shape(seg.shape, start, end, t_eff);

        // Advance phase. After this tick, check for segment completion.
        let next_sample = sample_in_seg + 1;
        if next_sample >= len {
            // Segment complete. In forward mode, honor `jump` if present.
            // In reverse mode, ignore jumps and walk index downward.
            let completed_end_level = if self.reverse {
                // When REV, the *effective* end of this segment is the
                // authored start (prev_level). We've just emitted the
                // sample at t_eff = 0, which equals `start`.
                start
            } else {
                end
            };
            self.prev_level = completed_end_level;

            if self.reverse {
                // Walk backwards. No jumps in reverse.
                if index == 0 {
                    self.state = State::Idle;
                } else {
                    let new_index = index - 1;
                    // prev_level for the upcoming (earlier) segment is
                    // the authored start of that segment. The *authored*
                    // "start level" of a segment is the end level of the
                    // previous segment — i.e. for seg i>0, start = seg[i-1].level;
                    // for seg 0, start = 0.0. In REV playback the upcoming
                    // segment was authored to end at its own `level` and
                    // start at `segments[new_index - 1].level` (or 0 if
                    // new_index == 0). We render it from its authored
                    // start up to its authored end, using (1 - t) to
                    // reverse in time.
                    let authored_start = if new_index == 0 {
                        0.0
                    } else {
                        self.segments[new_index - 1].level
                    };
                    self.prev_level = authored_start;
                    self.state = State::Running {
                        index: new_index,
                        sample_in_seg: 0,
                    };
                }
            } else {
                // Forward mode: honor jump if valid, else advance linearly.
                let next_index = match seg.jump {
                    Some(j) if j >= 0 && (j as usize) < self.segments.len() => Some(j as usize),
                    Some(_) => None,
                    None => {
                        let n = index + 1;
                        if n < self.segments.len() {
                            Some(n)
                        } else {
                            None
                        }
                    }
                };
                match next_index {
                    Some(n) => {
                        // Entering segment `n`: its authored starting
                        // level is the just-completed end level.
                        self.state = State::Running {
                            index: n,
                            sample_in_seg: 0,
                        };
                    }
                    None => {
                        self.state = State::Idle;
                    }
                }
            }
        } else {
            self.state = State::Running {
                index,
                sample_in_seg: next_sample,
            };
        }

        let y = y.clamp(OUT_MIN, OUT_MAX);
        self.last_out = y;
        y
    }
}

/// Evaluate a single shape at normalized progress `t ∈ [0, 1]`.
#[inline]
fn evaluate_shape(shape: SegmentShape, start: f32, end: f32, t: f32) -> f32 {
    let span = end - start;
    match shape {
        SegmentShape::Hold => start,
        SegmentShape::Lin => start + span * t,
        SegmentShape::Exp => start + span * (t * t),
        SegmentShape::Log => {
            let u = 1.0 - t;
            start + span * (1.0 - u * u)
        }
        SegmentShape::SCurve => start + span * (3.0 * t * t - 2.0 * t * t * t),
    }
}

#[cfg(test)]
mod unit {
    use super::*;
    use crate::cartridge::FnSegment;

    #[test]
    fn evaluate_shape_endpoints() {
        for (name, shape) in [
            ("hold", SegmentShape::Hold),
            ("lin", SegmentShape::Lin),
            ("exp", SegmentShape::Exp),
            ("log", SegmentShape::Log),
            ("sCurve", SegmentShape::SCurve),
        ] {
            let y0 = evaluate_shape(shape, 0.0, 1.0, 0.0);
            let y1 = evaluate_shape(shape, 0.0, 1.0, 1.0);
            assert!(
                (y0 - 0.0).abs() < 1e-6,
                "{name} at t=0 should be 0, got {y0}"
            );
            if shape == SegmentShape::Hold {
                assert!((y1 - 0.0).abs() < 1e-6, "hold at t=1 should still be 0");
            } else {
                assert!(
                    (y1 - 1.0).abs() < 1e-6,
                    "{name} at t=1 should be 1, got {y1}"
                );
            }
        }
    }

    #[test]
    fn from_str_unknown_falls_back_to_lin() {
        assert_eq!(SegmentShape::from_str("not-a-shape"), SegmentShape::Lin);
        assert_eq!(SegmentShape::from_str(""), SegmentShape::Lin);
        assert_eq!(SegmentShape::from_str("HOLD"), SegmentShape::Lin); // case-sensitive
    }

    #[test]
    fn zero_duration_advances() {
        // A zero-duration segment should not wedge forever.
        let mut fg = FunctionGenerator::new(48_000.0);
        let block = ModFnBlock {
            segments: vec![
                FnSegment {
                    level: 0.0,
                    time_ms: 0.0,
                    shape: "hold".to_string(),
                    jump: None,
                },
                FnSegment {
                    level: 1.0,
                    time_ms: 0.0, // also zero
                    shape: "lin".to_string(),
                    jump: None,
                },
            ],
            key_sync_int: 0,
            tempo_sync_int: 0,
        };
        fg.load(&block);
        // A few ticks should exhaust both zero-duration segments.
        for _ in 0..10 {
            fg.tick();
        }
        // After exhausting, generator should be idle (output 0).
        assert_eq!(fg.tick(), 0.0);
    }

    #[test]
    fn jump_out_of_bounds_goes_idle() {
        let mut fg = FunctionGenerator::new(48_000.0);
        let block = ModFnBlock {
            segments: vec![FnSegment {
                level: 1.0,
                time_ms: 10.0,
                shape: "lin".to_string(),
                jump: Some(99), // invalid
            }],
            key_sync_int: 0,
            tempo_sync_int: 0,
        };
        fg.load(&block);
        // Run well past the segment's length.
        for _ in 0..10_000 {
            fg.tick();
        }
        assert_eq!(fg.tick(), 0.0);
    }
}
