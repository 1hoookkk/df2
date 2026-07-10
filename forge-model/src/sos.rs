//! Adaptive SOS compiler — section budget 3/6/9/12 chosen by MEASURED
//! complex + impulse error against the model's native response.
//! Magnitude-only acceptance is dead (E2: 1.2e-5 dB magnitude error coexisted
//! with 1.6 complex NRMSE). Both metrics are always computed and reported.

use crate::{Mode, AUTHORING_SR};

/// Candidate section budgets, ascending.
pub const ORDERS: [usize; 4] = [3, 6, 9, 12];

const GRID_POINTS: usize = 512;
const IMPULSE_LEN: usize = 4096;
const F_LO: f64 = 20.0;

/// One tried budget and its measured errors — the raw material of the
/// per-projection loss report.
#[derive(Clone, Copy, Debug)]
pub struct CandidateReport {
    pub order: usize,
    pub complex_nrmse: f64,
    pub impulse_nrmse: f64,
}

/// The chosen projection: which modes survive and what the projection loses.
#[derive(Clone, Debug)]
pub struct SosChoice {
    pub order: usize,
    /// Indices of kept modes, in original order — identity is preserved.
    pub keep: Vec<usize>,
    pub complex_nrmse: f64,
    pub impulse_nrmse: f64,
    /// Every budget measured on the way to the choice.
    pub tried: Vec<CandidateReport>,
}

fn freq_grid() -> Vec<f64> {
    let hi = AUTHORING_SR * 0.49;
    (0..GRID_POINTS)
        .map(|i| F_LO * (hi / F_LO).powf(i as f64 / (GRID_POINTS - 1) as f64))
        .collect()
}

/// Complex response of a serial cascade at one frequency.
fn cascade_h(rows: &[[f64; 5]], f: f64) -> (f64, f64) {
    let w = std::f64::consts::TAU * f / AUTHORING_SR;
    let (c1, s1) = (w.cos(), -w.sin());
    let (c2, s2) = ((2.0 * w).cos(), -(2.0 * w).sin());
    let (mut re, mut im) = (1.0f64, 0.0f64);
    for r in rows {
        let (nr, ni) = (r[0] + r[1] * c1 + r[2] * c2, r[1] * s1 + r[2] * s2);
        let (dr, di) = (1.0 + r[3] * c1 + r[4] * c2, r[3] * s1 + r[4] * s2);
        let d = (dr * dr + di * di).max(1e-300);
        let (hr, hi) = ((nr * dr + ni * di) / d, (ni * dr - nr * di) / d);
        (re, im) = (re * hr - im * hi, re * hi + im * hr);
    }
    (re, im)
}

fn response(rows: &[[f64; 5]], grid: &[f64]) -> Vec<(f64, f64)> {
    grid.iter().map(|&f| cascade_h(rows, f)).collect()
}

/// Impulse response of a serial DF2T cascade, f64 throughout.
fn impulse(rows: &[[f64; 5]], n: usize) -> Vec<f64> {
    let mut w = vec![(0.0f64, 0.0f64); rows.len()];
    (0..n)
        .map(|i| {
            let mut x = if i == 0 { 1.0 } else { 0.0 };
            for (r, s) in rows.iter().zip(w.iter_mut()) {
                let y = r[0] * x + s.0;
                s.0 = r[1] * x - r[3] * y + s.1;
                s.1 = r[2] * x - r[4] * y;
                x = y;
            }
            x
        })
        .collect()
}

fn nrmse_complex(got: &[(f64, f64)], want: &[(f64, f64)]) -> f64 {
    let (mut err, mut refp) = (0.0, 0.0);
    for (g, w) in got.iter().zip(want) {
        let (dr, di) = (g.0 - w.0, g.1 - w.1);
        err += dr * dr + di * di;
        refp += w.0 * w.0 + w.1 * w.1;
    }
    (err / refp.max(1e-300)).sqrt()
}

fn nrmse_real(got: &[f64], want: &[f64]) -> f64 {
    let (mut err, mut refp) = (0.0, 0.0);
    for (g, w) in got.iter().zip(want) {
        err += (g - w) * (g - w);
        refp += w * w;
    }
    (err / refp.max(1e-300)).sqrt()
}

/// Compile one anchor's modes into the smallest section budget whose
/// complex AND impulse NRMSE against the native (all-mode) response stay
/// within `tol`. If no budget passes, the largest is returned with its
/// errors — the caller owns the accept/reject verdict (tol is a product
/// decision, not baked in here).
///
/// Mode ranking for truncation: each mode's own complex deviation from
/// identity, RMS over the grid — the modes that do the most to the sound
/// survive first. Kept modes stay in original order (identity preserved).
pub fn compile_adaptive(modes: &[Mode], tol: f64) -> SosChoice {
    let rows: Vec<[f64; 5]> = modes.iter().map(Mode::biquad).collect();
    let grid = freq_grid();
    let native_h = response(&rows, &grid);
    let native_imp = impulse(&rows, IMPULSE_LEN);

    // impact rank
    let mut ranked: Vec<usize> = (0..rows.len()).collect();
    let impact: Vec<f64> = rows
        .iter()
        .map(|r| {
            grid.iter()
                .map(|&f| {
                    let (re, im) = cascade_h(std::slice::from_ref(r), f);
                    (re - 1.0) * (re - 1.0) + im * im
                })
                .sum::<f64>()
        })
        .collect();
    ranked.sort_by(|&a, &b| impact[b].total_cmp(&impact[a]));

    let mut tried = Vec::new();
    let mut best: Option<SosChoice> = None;
    for order in ORDERS {
        let n = order.min(rows.len());
        let mut keep: Vec<usize> = ranked[..n].to_vec();
        keep.sort_unstable();
        let sub: Vec<[f64; 5]> = keep.iter().map(|&i| rows[i]).collect();
        let c = nrmse_complex(&response(&sub, &grid), &native_h);
        let im = nrmse_real(&impulse(&sub, IMPULSE_LEN), &native_imp);
        tried.push(CandidateReport {
            order,
            complex_nrmse: c,
            impulse_nrmse: im,
        });
        let covers_all = n == rows.len();
        best = Some(SosChoice {
            order,
            keep,
            complex_nrmse: c,
            impulse_nrmse: im,
            tried: Vec::new(),
        });
        if (c <= tol && im <= tol) || covers_all {
            break;
        }
    }
    let mut choice = best.expect("ORDERS is non-empty");
    choice.tried = tried;
    choice
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{Mode, RootPair, IDENTITY};

    fn peak(hz: f64, r: f64) -> Mode {
        Mode::pole_zero(hz, r, hz * 2.0, 0.5)
    }

    #[test]
    fn three_modes_compile_exactly_at_order_three() {
        let modes = vec![peak(300.0, 0.95), peak(900.0, 0.97), peak(2700.0, 0.96)];
        let c = compile_adaptive(&modes, 1e-6);
        assert_eq!(c.order, 3);
        assert_eq!(c.keep, vec![0, 1, 2]);
        assert!(c.complex_nrmse < 1e-12, "complex {}", c.complex_nrmse);
        assert!(c.impulse_nrmse < 1e-12, "impulse {}", c.impulse_nrmse);
    }

    #[test]
    fn nine_strong_modes_refuse_a_six_budget() {
        // Nine distinct resonances: six sections must measurably miss, nine
        // covers the source exactly. Six is a cost choice, not a model (E2).
        let modes: Vec<Mode> = (0..9)
            .map(|i| peak(150.0 * 1.8f64.powi(i), 0.985))
            .collect();
        let c = compile_adaptive(&modes, 1e-3);
        assert_eq!(c.order, 9);
        assert!(c.complex_nrmse < 1e-12);
        let six = c.tried.iter().find(|t| t.order == 6).unwrap();
        assert!(
            six.complex_nrmse > 1e-3 && six.impulse_nrmse > 1e-3,
            "six-section budget should measurably miss: c={} i={}",
            six.complex_nrmse,
            six.impulse_nrmse
        );
    }

    #[test]
    fn weak_modes_are_dropped_first() {
        // One strong resonance among near-identity modes: order 3 wins and
        // the strong mode survives, whatever its index.
        let mut modes = vec![IDENTITY; 6];
        modes[4] = Mode {
            pole: RootPair::Pair { hz: 740.0, r: 0.98 },
            zero: RootPair::Pair { hz: 0.0, r: 0.0 },
            gain: 0.04,
            active: 1.0,
        };
        let c = compile_adaptive(&modes, 1e-6);
        assert_eq!(c.order, 3);
        assert!(c.keep.contains(&4), "strong mode must survive: {:?}", c.keep);
        assert!(c.complex_nrmse < 1e-9);
    }

    #[test]
    fn report_lists_every_tried_budget() {
        let modes: Vec<Mode> = (0..9)
            .map(|i| peak(150.0 * 1.8f64.powi(i), 0.985))
            .collect();
        let c = compile_adaptive(&modes, 1e-3);
        let orders: Vec<usize> = c.tried.iter().map(|t| t.order).collect();
        assert_eq!(orders, vec![3, 6, 9]);
    }
}
