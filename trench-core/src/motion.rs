//! A sampled physical motion path for the product motion prototype.
//!
//! The path is a schedule for the existing Morph/Q controls. It does not touch
//! filter coefficients, add a second smoothing law, or invent a second runtime
//! kernel. `FilterEngine` remains the owner of packed interpolation and its
//! coefficient carry. This module only answers: "where should the two wheels be
//! at this musical phase?"

/// Maximum number of interleaved `[morph_delta, q_delta]` points accepted by the
/// FFI entry point. The processor's current user recorder already samples to 64
/// points, so this is deliberately the smallest useful fixed surface.
pub const MAX_PATH_POINTS: usize = 64;

/// Interleaved stride for a time-preserving take: `[time, morph_delta,
/// q_delta]`. Times are normalized to the duration of the take. A zero
/// `grid_steps` argument preserves those times; a non-zero argument snaps
/// them to that many equal subdivisions of the take.
pub const TIMED_POINT_STRIDE: usize = 3;

/// Evaluate a recorded path of interleaved Morph/Q deltas.
///
/// `points` contains `point_count` pairs, sampled at equal normalized time.
/// `phase` is the host-musical path position where 0.0 is the first point and
/// 1.0 is the end of the take. Closed paths wrap; open paths hold their last
/// point after the take completes. `amount` scales the recorded displacement
/// from the current wheel positions.
///
/// The interpolation is intentionally linear. The audio engine's existing
/// coefficient ramp is the physical smoothing law; adding a second hidden
/// smoother here would make the gesture and the shipped runtime disagree.
#[inline]
pub fn path_value(
    points: &[f32],
    phase: f64,
    closed: bool,
    base_morph: f32,
    base_q: f32,
    amount: f32,
) -> (f32, f32) {
    if points.len() < 2 {
        return (clamp_unit(base_morph), clamp_unit(base_q));
    }

    let point_count = (points.len() / 2).min(MAX_PATH_POINTS);
    if point_count == 0 {
        return (clamp_unit(base_morph), clamp_unit(base_q));
    }

    let t = if closed {
        phase.rem_euclid(1.0)
    } else {
        phase.clamp(0.0, 1.0)
    };
    let scaled = t * (point_count.saturating_sub(1)) as f64;
    let left = scaled.floor() as usize;
    let right = (left + 1).min(point_count - 1);
    let frac = (scaled - left as f64) as f32;

    let m0 = points[left * 2];
    let q0 = points[left * 2 + 1];
    let m1 = points[right * 2];
    let q1 = points[right * 2 + 1];
    let morph_delta = m0 + (m1 - m0) * frac;
    let q_delta = q0 + (q1 - q0) * frac;
    let depth = amount.clamp(0.0, 1.0);

    (
        clamp_unit(base_morph + morph_delta * depth),
        clamp_unit(base_q + q_delta * depth),
    )
}

/// Evaluate a time-preserving Morph/Q take.
///
/// `points` contains interleaved `[time, morph_delta, q_delta]` triples. The
/// recorded times are the free-timing form. `grid_steps > 0` is an explicit
/// capture policy for the same take: only the internal event times are
/// quantized; the authored wheel positions are not changed. The evaluator is
/// deliberately linear and does not add a second smoothing law — the filter's
/// coefficient carry remains the physical response.
#[inline]
pub fn path_value_timed(
    points: &[f32],
    phase: f64,
    closed: bool,
    base_morph: f32,
    base_q: f32,
    amount: f32,
    grid_steps: usize,
) -> (f32, f32) {
    if points.len() < TIMED_POINT_STRIDE {
        return (clamp_unit(base_morph), clamp_unit(base_q));
    }

    let point_count = (points.len() / TIMED_POINT_STRIDE).min(MAX_PATH_POINTS);
    if point_count == 0 {
        return (clamp_unit(base_morph), clamp_unit(base_q));
    }

    // Copy only the time coordinates into a fixed stack buffer. This keeps the
    // audio-thread path allocation-free while allowing the grid policy to be
    // applied without mutating the recorded values.
    let mut times = [0.0f32; MAX_PATH_POINTS];
    let mut previous = 0.0f32;
    let steps = grid_steps.min(256);
    for i in 0..point_count {
        let raw = points[i * TIMED_POINT_STRIDE];
        let mut time = if raw.is_finite() {
            raw.clamp(0.0, 1.0)
        } else {
            previous
        };
        if steps > 0 {
            time = (time * steps as f32).round() / steps as f32;
        }
        time = time.max(previous);
        times[i] = time;
        previous = time;
    }

    let t = if closed {
        phase.rem_euclid(1.0) as f32
    } else {
        phase.clamp(0.0, 1.0) as f32
    };

    let (left, right, frac) = if point_count == 1 {
        (0usize, 0usize, 0.0f32)
    } else if !closed {
        if t <= times[0] {
            (0usize, 0usize, 0.0)
        } else if t >= times[point_count - 1] {
            (point_count - 1, point_count - 1, 0.0)
        } else {
            let mut right = 1usize;
            while right < point_count && t > times[right] {
                right += 1;
            }
            let left = right - 1;
            let span = times[right] - times[left];
            let frac = if span > f32::EPSILON {
                (t - times[left]) / span
            } else {
                1.0
            };
            (left, right, frac.clamp(0.0, 1.0))
        }
    } else {
        let first_time = times[0];
        let last_time = times[point_count - 1];
        if t < first_time {
            let end = first_time + 1.0;
            let span = (end - last_time).max(f32::EPSILON);
            (
                point_count - 1,
                0,
                ((t + 1.0 - last_time) / span).clamp(0.0, 1.0),
            )
        } else if t >= last_time && last_time < 1.0 - f32::EPSILON {
            let end = first_time + 1.0;
            let span = (end - last_time).max(f32::EPSILON);
            (point_count - 1, 0, ((t - last_time) / span).clamp(0.0, 1.0))
        } else {
            let mut right = 1usize;
            while right < point_count && t > times[right] {
                right += 1;
            }
            if right >= point_count {
                (point_count - 1, point_count - 1, 0.0)
            } else {
                let left = right - 1;
                let span = times[right] - times[left];
                let frac = if span > f32::EPSILON {
                    (t - times[left]) / span
                } else {
                    1.0
                };
                (left, right, frac.clamp(0.0, 1.0))
            }
        }
    };

    let m0 = points[left * TIMED_POINT_STRIDE + 1];
    let q0 = points[left * TIMED_POINT_STRIDE + 2];
    let m1 = points[right * TIMED_POINT_STRIDE + 1];
    let q1 = points[right * TIMED_POINT_STRIDE + 2];
    let morph_delta = m0 + (m1 - m0) * frac;
    let q_delta = q0 + (q1 - q0) * frac;
    let depth = amount.clamp(0.0, 1.0);

    (
        clamp_unit(base_morph + morph_delta * depth),
        clamp_unit(base_q + q_delta * depth),
    )
}

#[inline]
fn clamp_unit(value: f32) -> f32 {
    value.clamp(0.0, 1.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    const PATH: [f32; 6] = [0.0, 0.0, 0.5, 0.25, 1.0, 0.5];

    #[test]
    fn shared_phase_moves_both_wheels_from_one_take() {
        let (morph, q) = path_value(&PATH, 0.5, false, 0.2, 0.1, 1.0);
        assert!((morph - 0.7).abs() < 1.0e-6);
        assert!((q - 0.35).abs() < 1.0e-6);
    }

    #[test]
    fn open_take_holds_at_the_destination() {
        let (morph, q) = path_value(&PATH, 2.0, false, 0.2, 0.1, 1.0);
        assert!((morph - 1.0).abs() < 1.0e-6);
        assert!((q - 0.6).abs() < 1.0e-6);
    }

    #[test]
    fn closed_take_wraps_without_a_new_mode_shape() {
        let closed = [0.0, 0.0, 0.8, 0.4, 0.0, 0.0];
        let at_start = path_value(&closed, 0.125, true, 0.2, 0.1, 1.0);
        let after_cycle = path_value(&closed, 1.125, true, 0.2, 0.1, 1.0);
        assert!((at_start.0 - after_cycle.0).abs() < 1.0e-6);
        assert!((at_start.1 - after_cycle.1).abs() < 1.0e-6);
    }

    #[test]
    fn amount_scales_displacement_and_never_leaves_the_wheels() {
        let (morph, q) = path_value(&PATH, 0.5, false, 0.9, 0.9, 0.5);
        assert!((morph - 1.0).abs() < 1.0e-6);
        assert!((q - 1.0).abs() < 1.0e-6);
    }

    #[test]
    fn invalid_path_is_a_noop() {
        let (morph, q) = path_value(&[], 0.5, false, 0.35, 0.65, 1.0);
        assert!((morph - 0.35).abs() < 1.0e-6);
        assert!((q - 0.65).abs() < 1.0e-6);
    }

    #[test]
    fn free_timing_and_grid_timing_are_distinct_policies() {
        let timed = [0.0, 0.0, 0.0, 0.20, 0.8, 0.4, 0.70, 0.1, 0.9, 1.0, 0.0, 0.0];
        let free = path_value_timed(&timed, 0.20, false, 0.1, 0.1, 1.0, 0);
        let grid = path_value_timed(&timed, 0.20, false, 0.1, 0.1, 1.0, 4);
        assert!((free.0 - 0.9).abs() < 1.0e-6);
        assert!((free.1 - 0.5).abs() < 1.0e-6);
        assert!((free.0 - grid.0).abs() > 1.0e-3);
        assert!((free.1 - grid.1).abs() > 1.0e-3);
    }

    #[test]
    fn timed_open_take_holds_after_last_timestamp() {
        let timed = [0.0, 0.0, 0.0, 0.4, 0.5, 0.25, 0.8, 0.9, 0.5];
        let value = path_value_timed(&timed, 1.5, false, 0.1, 0.2, 1.0, 0);
        assert!((value.0 - 1.0).abs() < 1.0e-6);
        assert!((value.1 - 0.7).abs() < 1.0e-6);
    }
}
