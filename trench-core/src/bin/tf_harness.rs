//! TRENCH transfer-function HARNESS — a source-agnostic experimental instrument.
//!
//! ```text
//! arbitrary continuous H_target(f, morph, q)
//!   -> jointly registered four-corner / six-lane candidate
//!   -> trench-core packing
//!   -> packed-runtime interpolation
//!   -> measured H_packed(f, morph, q)
//!   -> plots, audio, feature survival, residuals
//! ```
//!
//! The harness knows NOTHING about what a target means. It takes a [`Target`]
//! (any complex function of frequency × morph × q), jointly registers a
//! four-corner / six-lane candidate against the whole sampled Morph×Q surface
//! through the REAL packed loop, and reports what survived and what did not.
//!
//! ONE kernel. Packing, decode, packed-u16 interpolation, per-stage/cascade
//! complex response, and audio all come from `trench-core`:
//!   `params -> stage_law::words_from_geometry -> PackedCorners -> 240 bytes
//!    -> PackedCorners::interpolate_biquad -> response::biquad_cascade_complex`
//! and audio through `cascade::Cascade`. This bin adds only generic glue:
//! a pattern-search optimizer, SVG, WAV, JSON, SHA-256. No filter math is
//! re-implemented. The one piece of algebra that mirrors a private trench-core
//! function (`classify_pair` ~ `stage_law::pair_geometry`) is pinned against the
//! owned decoder by `classify_pair_mirrors_stage_law`.
//!
//! THE IDENTIFIABILITY BOUNDARY (H17, the harness's central contract).
//! MEASURED: permuting one corner's six lanes changes that corner's transfer
//! function by 0.0 dB while moving the interior by 25.82 dB. The cascade is a
//! permutation-invariant PRODUCT, so the corner transfer functions DO NOT
//! CONTAIN the lane registration. Recovering it from endpoints is not hard — it
//! is impossible. The harness therefore never asks "what is the true
//! correspondence?"; it asks what evidence exists (see [`EvidenceMode`]):
//!   ENDPOINT_ONLY       -> equivalence class, verdict AMBIGUOUS, select nothing
//!   OBSERVED_SURFACE    -> rank by measured interior error, REFUSE on a thin margin
//!   AUTHORED_TRAJECTORY -> preserve the source model's identities, label AUTHORED
//!
//! WHAT THIS HARNESS DOES NOT DO (deliberate, per the neutral-instrument brief):
//!   · no automatic normalization (absolute gain is preserved everywhere)
//!   · no derived Q (SCALE and both radii are explicit free parameters)
//!   · no stage sorting / no frequency-sorted correspondence
//!   · no category mapping, no named archetypes, no aesthetic scoring
//!   · no smart repair (an illegal candidate is reported, never patched)
//! Stable + finite + packable = LEGAL. Legal is never a claim of quality.
//!
//! Every non-runtime choice is labelled HYPOTHESIS in `hypotheses()` and echoed
//! into every emitted report.
//!
//!   cargo run --release -p trench-core --bin tf-harness -- all
//!
//! Artifacts land in dev/tmp/tf_harness/<fixture>/.

use std::f64::consts::TAU;
use std::path::{Path, PathBuf};

use trench_core::cartridge::{Cartridge, CornerData};
use trench_core::cascade::{Cascade, NUM_COEFFS, NUM_STAGES};
use trench_core::compiler::{section_biquad, TYPE_PEAK};
use trench_core::minifloat::{pole_radius, PackedCorners};
use trench_core::response::{biquad_cascade_complex, biquad_stage_complex, log_frequency_grid};
use trench_core::stage_law::{
    geometry_from_words, words_from_geometry, RootPair, StageGeometry, STAGE_SR,
};

// ── runtime constants (OBSERVED from trench-core, not chosen here) ───────────

/// The island rate. Owned by `trench-core`; this harness does not pick it.
const SR: f64 = STAGE_SR;
/// 4 corners × 6 lanes × 5 params. The candidate's entire degrees of freedom.
const PPS: usize = 5;
const NPARAM: usize = 4 * NUM_STAGES * PPS; // 120
const CORNER_LABELS: [&str; 4] = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"];
/// Corner (morph, q) coordinates, in the runtime's corner order.
const CORNER_MQ: [(f64, f64); 4] = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)];

// ── HYPOTHESES: every non-runtime decision, declared ─────────────────────────

/// H1 objective frequency band + grid.
const F_LO: f64 = 30.0;
const F_HI: f64 = 16_000.0;
const OBJ_F_BINS: usize = 192;
/// H2 objective Morph×Q grid (the surface the optimizer actually sees).
const OBJ_MQ: usize = 5;
/// H3 verification Morph×Q grid (held-out interior points the fit never saw).
const VERIFY_MQ: usize = 9;
/// H4 sampled-certification grid.
const CERT_MQ: usize = 33;
/// H5 phase weight, rad² vs dB².
const LAMBDA_PH: f64 = 4.0;
/// H6 interior-stability barrier: radius ceiling + weight. LEGALITY, not taste.
const STAB_R: f64 = 0.997;
const PEN_STAB: f64 = 3.0e4;
/// H7 param-box pole radius ceiling (packability + resolvability of the grid).
const POLE_Q_MAX: f64 = 0.994; // r <= ~0.997
/// H8 feature-survival matching tolerance (reporting only, never correspondence).
const FEATURE_TOL_OCT: f64 = 1.0 / 6.0;
const FEATURE_PROM_DB: f64 = 1.5;
/// H9 optimizer iteration budget.
const DEFAULT_ITERS: usize = 300;

fn hypotheses() -> serde_json::Value {
    serde_json::json!([
        {"id":"H1","claim":"objective band 30..16000 Hz on a 192-point log grid","status":"HYPOTHESIS","why":"log spacing matches how the response is read; the band excludes DC/Nyquist edges the packed format resolves poorly. Applied identically to target and candidate."},
        {"id":"H2","claim":"optimizer sees a 5x5 Morph×Q grid","status":"HYPOTHESIS","why":"interior must be scored (endpoint-only scoring is provably insufficient — see the correspondence fixture); 5x5 is a compute/coverage trade, not a proven sufficiency."},
        {"id":"H3","claim":"verification uses a 9x9 grid whose interior points the fit never saw","status":"HYPOTHESIS","why":"separates 'fit the grid' from 'fit the surface'. Not a continuum proof."},
        {"id":"H4","claim":"certification samples 33x33 Morph×Q","status":"HYPOTHESIS","why":"sampled certification only — NEVER a continuum proof of stability."},
        {"id":"H5","claim":"error = dB^2 + 4.0 * wrapped-phase^2 (rad)","status":"HYPOTHESIS","why":"log-magnitude is bounded where raw complex explodes near notches; the 4.0 phase weight is arbitrary and unvalidated against any perceptual criterion."},
        {"id":"H6","claim":"equal weight per octave (w = 1/f)","status":"HYPOTHESIS","why":"a neutral log-frequency weight. NOT a perceptual model. Applied identically to target and candidate, so it is not a normalization."},
        {"id":"H7","claim":"interior-stability barrier at pole radius 0.997 over a 17x17 grid","status":"HYPOTHESIS","why":"LEGALITY constraint: corners can be stable while their packed-word lerp overshoots in the interior. Weight 3e4 is arbitrary."},
        {"id":"H8","claim":"param box: zero q in [0,1], pole q in [0,0.994], scale in [0,4]","status":"HYPOTHESIS","why":"scale range is the packed format's representable k (OBSERVED). Radius ceiling is chosen so no resonance hides between objective grid samples."},
        {"id":"H9","claim":"feature survival matches peaks/notches within 1/6 octave, prominence >= 1.5 dB","status":"HYPOTHESIS","why":"a REPORTING heuristic for 'did this spectral feature survive'. It assigns NO lane identity and is NOT a correspondence claim."},
        {"id":"H10","claim":"deterministic Hooke-Jeeves pattern search, 300 iterations","status":"HYPOTHESIS","why":"any fit residual is an UPPER BOUND on achievable error, never a proof of what six stages cannot do. Only the order count is a proof. MEASURED: this optimizer does NOT recover the exactly-representable fixture from a blind init even though a zero-error solution provably exists — see the exact6 report."},
        {"id":"H15","claim":"deterministic step restarts do NOT rescue the blind optimizer","status":"REJECTED","why":"MEASURED: re-inflating the collapsed step (up to 6 times) changed the final objective on all three fixtures by nothing — exact6 blind stayed at 1.5275e1 to five significant figures. A deterministic exploration is a function of (incumbent, step), so restarting from the same incumbent replays the same failed search. Code removed; recorded so it is not re-tried."},
        {"id":"H16","claim":"a registration margin below 0.5 dB is UNRESOLVED/REFUSED, not a decision","status":"HYPOTHESIS","why":"the threshold is arbitrary. Its purpose is to stop a numerically meaningless margin (MEASURED: 0.003 dB between pairing A and pairing B) from being read as a choice."},
        {"id":"H17","claim":"lane correspondence is NOT IDENTIFIABLE from corner-only transfer functions","status":"OBSERVED","why":"DECISIVE and structural, not a difficulty: permuting one corner's lanes changes that corner's transfer function by 0.0 dB (the cascade is a permutation-invariant product) while moving the interior by 25.82 dB. The information is not present in the corners. No optimizer, no extra corner data, and no cleverness can recover it. Pinned by identifiability_boundary_zero_db_corners_25db_interior and by the REQUIRED NEGATIVE TEST blind_fit_must_not_resolve_correspondence."},
        {"id":"H18","claim":"what the harness may conclude about correspondence depends ONLY on the declared evidence mode","status":"HYPOTHESIS","why":"ENDPOINT_ONLY -> AMBIGUOUS, select nothing. OBSERVED_SURFACE -> rank by measured interior error vs real observations, refuse on an insignificant margin. AUTHORED_TRAJECTORY -> preserve the source model's identities as a prior labelled AUTHORED, never RECOVERED. The three-way split is a contract choice; the boundary it encodes (H17) is measured."},
        {"id":"H11","claim":"the candidate is ALWAYS the blind run; oracle-rows is a separate probe never promoted to candidate","status":"HYPOTHESIS","why":"oracle init measures whether the objective is minimized at truth. Blind init measures whether the optimizer can find it. A real target has no oracle, so only the blind run is a capability claim."},
        {"id":"H12","claim":"no transport delay is removed from any comparison","status":"OBSERVED","why":"all fixtures are analytic/packed section products with zero pure transport delay; the phase compared is the true response phase. Group delay is NOT removed."},
        {"id":"H13","claim":"blind init = six lanes log-spaced 100..12000 Hz as mild +3 dB peaks","status":"HYPOTHESIS","why":"TARGET-AGNOSTIC (never inspects the target) so it smuggles in no correspondence and no sorting. Required because the all-identity init is a permutation-symmetry trap — OBSERVED: it stalls at a fixed objective regardless of iteration budget (90/300/1200 iters -> 22.01/21.97/21.88). The spread is arbitrary and unvalidated as optimal."},
        {"id":"H14","claim":"packed-interpolation wrap barrier, weight 1e4","status":"HYPOTHESIS","why":"LEGALITY: the runtime u16 lerp casts the corner delta to i16 before adding the base, so |delta| > 32767 wraps to garbage. OBSERVED: without this barrier the optimizer parked words at a 65535 delta and emitted an illegal body. The weight is arbitrary."}
    ])
}

// ── complex helpers (tuple form) ─────────────────────────────────────────────

type Cf = (f64, f64);
#[inline]
fn cmul(a: Cf, b: Cf) -> Cf {
    (a.0 * b.0 - a.1 * b.1, a.0 * b.1 + a.1 * b.0)
}
#[inline]
fn cabs(a: Cf) -> f64 {
    (a.0 * a.0 + a.1 * a.1).sqrt()
}
#[inline]
fn cdb(a: Cf) -> f64 {
    20.0 * cabs(a).max(1e-12).log10()
}
fn wrap_pi(x: f64) -> f64 {
    let mut y = x % TAU;
    if y > std::f64::consts::PI {
        y -= TAU;
    }
    if y < -std::f64::consts::PI {
        y += TAU;
    }
    y
}

/// Ordered product of per-stage complex responses over ANY number of rows.
/// `response::biquad_stage_complex` is the single owner of per-stage response;
/// the cascade is defined as the ordered product of them. Pinned against
/// `biquad_cascade_complex` for the 6-row case by `rows_complex_matches_owner`.
fn rows_complex(rows: &[[f64; NUM_COEFFS]], f: f64) -> Cf {
    let mut acc = (1.0f64, 0.0f64);
    for r in rows {
        acc = cmul(acc, biquad_stage_complex(r, f, SR));
    }
    acc
}

// ── the source-agnostic target interface ────────────────────────────────────

// ── THE IDENTIFIABILITY BOUNDARY (the harness's central contract) ───────────
//
// MEASURED, and decisive: permuting one corner's six lanes leaves that corner's
// transfer function EXACTLY unchanged (0.0 dB) while moving the interior by
// 25.8 dB. The cascade is a permutation-invariant PRODUCT, so the four corner
// transfer functions do not contain the lane registration. It is not that
// recovering it is hard — the information is NOT THERE.
//
// Therefore the harness never asks "what is the true correspondence?" It asks
// "what evidence do I actually have?", and answers differently for each:
//
//   ENDPOINT_ONLY       -> report the equivalence class. Verdict AMBIGUOUS.
//                          NEVER select a permutation as truth.
//   OBSERVED_SURFACE    -> rank candidates by packed-runtime interior error
//                          against real interior observations. Report the
//                          winning margin; REFUSE if it is insignificant.
//   AUTHORED_TRAJECTORY -> a continuous source model supplies the actor
//                          identities. Preserve them as an explicit authoring
//                          prior. Label AUTHORED — never RECOVERED.
//
// In ENDPOINT_ONLY the two registrations are "pairing A" and "pairing B". There
// is no truth and no decoy: neither is identifiable from the endpoints, and
// naming one "truth" would smuggle in the very claim the boundary forbids.

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum EvidenceMode {
    /// Only the four corner transfer functions are available.
    EndpointOnly,
    /// Interior H_target(f, m, q) samples exist and may be scored against.
    ObservedSurface,
    /// A continuous source model supplies actor identities / trajectories.
    AuthoredTrajectory,
}

impl EvidenceMode {
    fn label(&self) -> &'static str {
        match self {
            Self::EndpointOnly => "ENDPOINT_ONLY",
            Self::ObservedSurface => "OBSERVED_SURFACE",
            Self::AuthoredTrajectory => "AUTHORED_TRAJECTORY",
        }
    }
    fn correspondence_status(&self) -> &'static str {
        match self {
            Self::EndpointOnly => "AMBIGUOUS — not identifiable from this evidence",
            Self::ObservedSurface => "RANKED against interior observations (may still REFUSE)",
            Self::AuthoredTrajectory => "AUTHORED — supplied by the source model, never RECOVERED",
        }
    }
}

/// An arbitrary continuous transfer function over frequency × morph × q.
///
/// The harness treats this as a black box. It is NOT required to be
/// representable, causal-minimum-phase, six-section, or anything else.
trait Target {
    fn name(&self) -> &str;
    fn describe(&self) -> String;
    /// What evidence about this target is ACTUALLY available. Governs what the
    /// harness is permitted to conclude about lane correspondence.
    fn evidence_mode(&self) -> EvidenceMode;
    /// AUTHORED_TRAJECTORY only: the source model's declared actor identity per
    /// lane. Returned as an authoring PRIOR — it is a declaration, not a
    /// measurement, and is always labelled AUTHORED.
    fn authored_lanes(&self, _m: f64, _q: f64) -> Option<Vec<String>> {
        None
    }
    /// THE definition of the target: complex response at (f, morph, q).
    fn h(&self, f: f64, m: f64, q: f64) -> Cf;
    /// Optional exact realization as ordered DF2T rows, when the target happens
    /// to be a section product. Enables target-side audio through the owned
    /// `Cascade`. `None` => no target audio; residual spectra only.
    fn rows(&self, _m: f64, _q: f64) -> Option<Vec<[f64; NUM_COEFFS]>> {
        None
    }
    /// Pole-pair count of the target realization, when known. Used ONLY for the
    /// analytic order-deficit statement (a proof), never for fitting.
    fn pole_pairs(&self) -> Option<usize> {
        None
    }
    /// EXACT causal Markov parameters, when the source can supply them.
    /// `None` => only SAMPLED_SPECTRUM_ESTIMATE is available; no bound may be
    /// claimed. Never used by any solver — this is an analysis channel.
    fn markov(&self, _m: f64, _q: f64, _n: usize) -> Option<Vec<f64>> {
        None
    }
    /// DECLARED pure transport delay in samples. Only this is ever removed from
    /// a comparison; group delay is never removed.
    fn transport_delay_samples(&self) -> usize {
        0
    }
}

/// A target that IS an ordered section product: `h` is derived from `rows`
/// through the owned response engine, so there is exactly one response law.
trait SectionTarget {
    fn name(&self) -> &str;
    fn describe(&self) -> String;
    fn rows_at(&self, m: f64, q: f64) -> Vec<[f64; NUM_COEFFS]>;
    fn pole_pairs(&self) -> usize;
    fn evidence_mode(&self) -> EvidenceMode;
    fn authored_lanes_at(&self, _m: f64, _q: f64) -> Option<Vec<String>> {
        None
    }
}

impl<T: SectionTarget> Target for T {
    fn name(&self) -> &str {
        SectionTarget::name(self)
    }
    fn describe(&self) -> String {
        SectionTarget::describe(self)
    }
    fn evidence_mode(&self) -> EvidenceMode {
        SectionTarget::evidence_mode(self)
    }
    fn authored_lanes(&self, m: f64, q: f64) -> Option<Vec<String>> {
        SectionTarget::authored_lanes_at(self, m, q)
    }
    fn h(&self, f: f64, m: f64, q: f64) -> Cf {
        rows_complex(&self.rows_at(m, q), f)
    }
    fn rows(&self, m: f64, q: f64) -> Option<Vec<[f64; NUM_COEFFS]>> {
        Some(self.rows_at(m, q))
    }
    fn pole_pairs(&self) -> Option<usize> {
        Some(SectionTarget::pole_pairs(self))
    }
    /// A section product can supply EXACT Markov parameters — no DFT, so no
    /// aliasing and no frequency sampling.
    fn markov(&self, m: f64, q: f64, n: usize) -> Option<Vec<f64>> {
        Some(exact_markov(&self.rows_at(m, q), n))
    }
}

// ── FIXTURE 1: exactly representable six-section surface ────────────────────
//
// The target IS the packed-runtime surface of a KNOWN 240-byte body. A perfect
// candidate therefore EXISTS by construction (the known body itself). This
// fixture answers: is the objective minimized at truth, and can the optimizer
// find it? It is the harness's own noise floor. Any error here is harness error,
// not budget error and not correspondence error.

struct ExactSix {
    known: PackedCorners,
}

impl ExactSix {
    fn new() -> Self {
        // Six distinct lanes with morph AND q motion. Deliberately includes the
        // format's awkward cases: a near-unit-circle notch zero and an explicit
        // REAL-ROOT numerator pair (which the conjugate reader must refuse).
        // Lane frequencies are monotone and well separated — correspondence is
        // NOT the subject of this fixture.
        let mut words = [[[0u16; NUM_COEFFS]; NUM_STAGES]; 4];
        for (ci, &(m, q)) in CORNER_MQ.iter().enumerate() {
            let lerp = |a: f64, b: f64, t: f64| a + (b - a) * t;
            let rq = |lo: f64, hi: f64| lerp(lo, hi, q);
            let g = |lo: f64, hi: f64| lerp(lo, hi, m);

            let lane =
                |pole: RootPair, zero: RootPair, scale: f64| StageGeometry { pole, zero, scale };
            let conj = |hz: f64, r: f64| RootPair::Conjugate { hz, r };

            words[ci][0] = words_from_geometry(&lane(
                conj(g(320.0, 480.0), rq(0.88, 0.955)),
                RootPair::Degenerate,
                0.45,
            ));
            words[ci][1] = words_from_geometry(&lane(
                conj(g(900.0, 1300.0), rq(0.90, 0.960)),
                RootPair::Degenerate,
                0.45,
            ));
            // lane 2 carries a near-unit notch zero travelling on morph
            words[ci][2] = words_from_geometry(&lane(
                conj(g(2100.0, 2600.0), rq(0.90, 0.960)),
                conj(g(1600.0, 3000.0), 0.99),
                1.0,
            ));
            words[ci][3] = words_from_geometry(&lane(
                conj(g(4200.0, 5200.0), rq(0.85, 0.930)),
                RootPair::Degenerate,
                0.6,
            ));
            // lane 4 carries an explicit REAL-ROOT numerator pair
            words[ci][4] = words_from_geometry(&lane(
                conj(g(8000.0, 9000.0), rq(0.80, 0.900)),
                RootPair::RealPair {
                    root_a: 0.7,
                    root_b: 0.2,
                },
                1.0,
            ));
            // lane 5 stays the exact identity biquad at every corner
            words[ci][5] =
                words_from_geometry(&lane(RootPair::Degenerate, RootPair::Degenerate, 1.0));
        }
        Self {
            known: PackedCorners { words },
        }
    }
}

impl SectionTarget for ExactSix {
    fn name(&self) -> &str {
        "exact6"
    }
    fn describe(&self) -> String {
        "The packed-runtime surface of a KNOWN 240-byte body (6 distinct lanes, \
         morph+q motion, one near-unit notch zero, one explicit real-root numerator, \
         one identity lane). A perfect candidate EXISTS by construction."
            .into()
    }
    fn rows_at(&self, m: f64, q: f64) -> Vec<[f64; NUM_COEFFS]> {
        self.known.interpolate_biquad(m as f32, q as f32).to_vec()
    }
    fn pole_pairs(&self) -> usize {
        5 // lane 5 is identity: no pole pair
    }
    /// Interior samples of this target are available at any (m, q), so the
    /// harness may RANK correspondence candidates against real observations.
    fn evidence_mode(&self) -> EvidenceMode {
        EvidenceMode::ObservedSurface
    }
}

// ── FIXTURE 2: intentionally over-budget target ─────────────────────────────
//
// Ten flat-off-resonance peaking sections. A six-section cascade has at most 6
// pole pairs; this target has 10. The order deficit is an ARITHMETIC FACT — a
// proof, independent of any optimizer. The fit then shows WHICH features die
// and how large the residual is. The residual is an UPPER BOUND on achievable
// error, never a proof of impossibility.

struct OverBudget {
    n: usize,
}

impl OverBudget {
    fn new() -> Self {
        Self { n: 10 }
    }
}

impl SectionTarget for OverBudget {
    fn name(&self) -> &str {
        "overbudget"
    }
    fn describe(&self) -> String {
        format!(
            "{} flat-off-resonance peaking sections log-spaced 220..12000 Hz, each gliding \
             up a minor third on morph, each sharpening on q. Target order = {} pole pairs \
             vs the format's 6. Order deficit = {} pole pairs (ARITHMETIC, not a fit result).",
            self.n,
            self.n,
            self.n - NUM_STAGES
        )
    }
    fn rows_at(&self, m: f64, q: f64) -> Vec<[f64; NUM_COEFFS]> {
        (0..self.n)
            .map(|i| {
                let t = i as f64 / (self.n - 1) as f64;
                let base = 220.0 * (12_000.0f64 / 220.0).powf(t);
                // every peak glides up a minor third (2^(3/12)) on morph
                let fc = base * 2.0f64.powf(0.25 * m);
                // Q sharpens on q; alternate gains so the comb is legible
                let qq = 3.0 + 9.0 * q;
                let gain = if i % 2 == 0 { 12.0 } else { 9.0 };
                section_biquad(TYPE_PEAK, fc, qq, gain)
            })
            .collect()
    }
    fn pole_pairs(&self) -> usize {
        self.n
    }
    fn evidence_mode(&self) -> EvidenceMode {
        EvidenceMode::ObservedSurface
    }
}

// ── FIXTURE 3: crossing / ambiguous actors ─────────────────────────────────
//
// Two lanes whose frequencies CROSS between the morph endpoints. The true
// registration keeps each lane's identity through the crossing.
//
// The exposure: the cascade transfer function is a permutation-invariant
// PRODUCT, so swapping two lanes inside one corner leaves that corner's response
// EXACTLY unchanged while changing every interior point. Corner data therefore
// cannot discriminate the crossed registration from the frequency-sorted one.
// A harness that sorts lanes by frequency would pick the sorted pairing and
// report a perfect corner match — while silently rendering the wrong interior.
//
// This harness does not sort. It reports the discriminability of both.

struct Crossing {
    /// The AUTHORED pairing. It is the target's realization because the source
    /// model DECLARES it — never because it was recovered from the corners.
    /// Under ENDPOINT_ONLY evidence this body is "pairing A", nothing more.
    authored: PackedCorners,
}

impl Crossing {
    /// `crossed = true` -> **pairing A**: lane 0 rises 600->2600 while lane 1
    /// falls 2400->560 (each actor's identity preserved through the crossing).
    /// `crossed = false` -> **pairing B**: the frequency-SORTED registration of
    /// the very same corner sets (lane 0 600->560, lane 1 2400->2600).
    ///
    /// Both have IDENTICAL per-corner section multisets, hence identical corner
    /// transfer functions — and different interiors. From endpoint evidence
    /// alone NEITHER is truth and NEITHER is a decoy: they are indistinguishable
    /// members of one equivalence class. Only an authoring prior or interior
    /// observations can separate them.
    fn build(crossed: bool) -> PackedCorners {
        // Flat-off-resonance peak sections. A stack of bare all-pole resonators
        // cannibalises into a monotone lowpass with NO local extrema (OBSERVED:
        // the first build of this fixture reported 0 detectable features at every
        // state), which would make feature survival unmeasurable. Flat-ended
        // sections keep each actor legible as a real peak.
        let mut words = [[[0u16; NUM_COEFFS]; NUM_STAGES]; 4];
        for (ci, &(m, q)) in CORNER_MQ.iter().enumerate() {
            let peak = |hz: f64, qq: f64, gain: f64| {
                biquad_to_words_owned(&section_biquad(TYPE_PEAK, hz, qq, gain))
            };
            let q_ac = if q > 0.5 { 9.0 } else { 3.5 };
            // The two crossing actors, addressed by their TRUE identity.
            let actor_a: f64 = if m > 0.5 { 2600.0 } else { 600.0 }; // rises
            let actor_b: f64 = if m > 0.5 { 560.0 } else { 2400.0 }; // falls

            let (lane0, lane1) = if crossed {
                // pairing A: each actor keeps its identity through the crossing
                (actor_a, actor_b)
            } else {
                // pairing B: the frequency-sorted registration — the low slot
                // gets the low frequency at EVERY corner. Identical per-corner
                // multiset {actor_a, actor_b}, hence identical corner responses,
                // and a different interior.
                (actor_a.min(actor_b), actor_a.max(actor_b))
            };
            words[ci][0] = peak(lane0, q_ac, 15.0);
            words[ci][1] = peak(lane1, q_ac, 15.0);

            // Three non-crossing spectator lanes + one identity lane, so the
            // fixture isolates correspondence and nothing else.
            let lerp = |a: f64, b: f64, t: f64| a + (b - a) * t;
            words[ci][2] = peak(lerp(4200.0, 4600.0, m), 4.0, 9.0);
            words[ci][3] = peak(lerp(7000.0, 7600.0, m), 4.0, 7.0);
            words[ci][4] = peak(lerp(150.0, 170.0, m), 3.0, 6.0);
            words[ci][5] = words_from_geometry(&StageGeometry {
                pole: RootPair::Degenerate,
                zero: RootPair::Degenerate,
                scale: 1.0,
            });
        }
        PackedCorners { words }
    }

    fn pairing_a() -> PackedCorners {
        Self::build(true)
    }
    fn pairing_b() -> PackedCorners {
        Self::build(false)
    }
    fn new() -> Self {
        Self {
            authored: Self::pairing_a(),
        }
    }
}

impl SectionTarget for Crossing {
    fn name(&self) -> &str {
        "crossing"
    }
    fn describe(&self) -> String {
        "Two actors CROSS in frequency across morph (600->2600 vs 2400->560). The source \
         model AUTHORS pairing A (each actor keeps its identity through the crossing). \
         Pairing B — the frequency-sorted registration of the same corner sets — has \
         IDENTICAL corner transfer functions and a different interior, so from endpoint \
         evidence alone the two are indistinguishable and neither is 'truth'."
            .into()
    }
    fn rows_at(&self, m: f64, q: f64) -> Vec<[f64; NUM_COEFFS]> {
        self.authored
            .interpolate_biquad(m as f32, q as f32)
            .to_vec()
    }
    fn pole_pairs(&self) -> usize {
        5
    }
    /// The source model is a continuous authored construction: it DECLARES which
    /// actor is which. That is a prior, not a recovery.
    fn evidence_mode(&self) -> EvidenceMode {
        EvidenceMode::AuthoredTrajectory
    }
    fn authored_lanes_at(&self, m: f64, _q: f64) -> Option<Vec<String>> {
        let a = if m > 0.5 { 2600.0 } else { 600.0 };
        let b = if m > 0.5 { 560.0 } else { 2400.0 };
        Some(vec![
            format!("actor_A/rising @ {a:.0} Hz"),
            format!("actor_B/falling @ {b:.0} Hz"),
            "spectator_4200_4600".into(),
            "spectator_7000_7600".into(),
            "spectator_150_170".into(),
            "identity".into(),
        ])
    }
}

// ── candidate parameterization ──────────────────────────────────────────────
//
// Per (corner, lane): [zero_p, zero_q, pole_p, pole_q, scale] — the monic
// quadratic coefficients of numerator and denominator (1 + p z^-1 + q z^-2) plus
// SCALE = b0. This spans conjugate AND real root pairs CONTINUOUSLY; the pair
// TYPE is an exact classification of (p,q), never a silent clamp, and a real
// pair is packed AS a RealPair through the owned `words_from_geometry`.
//
// Lane index is the registration. It is fixed by construction and never sorted.

/// Mirrors `stage_law::pair_geometry` (private there). Pinned against the owned
/// decoder by `classify_pair_mirrors_stage_law`.
fn classify_pair(p: f64, q: f64) -> RootPair {
    if p == 0.0 && q == 0.0 {
        return RootPair::Degenerate;
    }
    let disc = p * p - 4.0 * q;
    if disc < 0.0 {
        let r = q.max(0.0).sqrt();
        let cosw = (-p / (2.0 * r)).clamp(-1.0, 1.0);
        RootPair::Conjugate {
            hz: cosw.acos() / TAU * SR,
            r,
        }
    } else {
        let s = disc.sqrt();
        RootPair::RealPair {
            root_a: (-p + s) / 2.0,
            root_b: (-p - s) / 2.0,
        }
    }
}

/// H8 param box. Legality/packability only — no musical constraint.
fn clamp_stage(s: &mut [f64]) {
    s[1] = s[1].clamp(0.0, 1.0); // zero q = rz^2
    s[0] = s[0].clamp(-2.0, 2.0); // zero p
    s[3] = s[3].clamp(0.0, POLE_Q_MAX); // pole q = rp^2
    let lim = (1.0 + s[3]) - 1e-4; // stability triangle
    s[2] = s[2].clamp(-lim, lim);
    s[4] = s[4].clamp(0.0, 4.0); // SCALE = b0, the format's representable k
}

fn stage_words(s: &[f64]) -> [u16; NUM_COEFFS] {
    words_from_geometry(&StageGeometry {
        zero: classify_pair(s[0], s[1]),
        pole: classify_pair(s[2], s[3]),
        scale: s[4],
    })
}

fn params_to_packed(params: &[f64]) -> PackedCorners {
    let mut words = [[[0u16; NUM_COEFFS]; NUM_STAGES]; 4];
    for ci in 0..4 {
        for si in 0..NUM_STAGES {
            let base = (ci * NUM_STAGES + si) * PPS;
            words[ci][si] = stage_words(&params[base..base + PPS]);
        }
    }
    PackedCorners { words }
}

/// Direct DF2T row -> five packed words, through the OWNED geometry path (so a
/// real-root pair is packed AS a RealPair and never silently clamped).
fn biquad_to_words_owned(r: &[f64; NUM_COEFFS]) -> [u16; NUM_COEFFS] {
    let mut sp = biquad_to_stage_params(r);
    clamp_stage(&mut sp);
    stage_words(&sp)
}

/// Direct DF2T row -> monic-quadratic + SCALE params. Pure algebra.
fn biquad_to_stage_params(r: &[f64; NUM_COEFFS]) -> [f64; PPS] {
    let b0 = r[0];
    let (zp, zq) = if b0.abs() > 1e-12 {
        (r[1] / b0, r[2] / b0)
    } else {
        (0.0, 0.0)
    };
    [zp, zq, r[3], r[4], b0]
}

/// The exact-identity body. Used as the neutral reference (the "did the fit do
/// anything at all" yardstick), NOT as an init — see `init_spread`.
fn init_identity() -> Vec<f64> {
    let mut p = vec![0.0f64; NPARAM];
    for ci in 0..4 {
        for si in 0..NUM_STAGES {
            let base = (ci * NUM_STAGES + si) * PPS;
            p[base..base + PPS].copy_from_slice(&[0.0, 0.0, 0.0, 0.0, 1.0]);
        }
    }
    p
}

/// H13 blind init: six lanes log-spaced across the objective band, each a mild
/// flat-off-resonance peak. TARGET-AGNOSTIC and deterministic — it never looks
/// at the target, so it smuggles in no correspondence and no sorting.
///
/// WHY (OBSERVED, `blind_identity_init_is_a_symmetry_trap`): the all-identity
/// init makes every lane numerically IDENTICAL, so the objective is symmetric
/// under lane permutation and coordinate search cannot differentiate the lanes.
/// It stalls in that symmetric basin at a fixed objective regardless of the
/// iteration budget. Distinct starting frequencies break the symmetry.
fn init_spread() -> Vec<f64> {
    let mut p = vec![0.0f64; NPARAM];
    for ci in 0..4 {
        for si in 0..NUM_STAGES {
            let t = si as f64 / (NUM_STAGES - 1) as f64;
            let fc = 100.0 * (12_000.0f64 / 100.0).powf(t);
            let mut sp = biquad_to_stage_params(&section_biquad(TYPE_PEAK, fc, 2.0, 3.0));
            clamp_stage(&mut sp);
            let base = (ci * NUM_STAGES + si) * PPS;
            p[base..base + PPS].copy_from_slice(&sp);
        }
    }
    p
}

/// H11 identifiability probe: seed each corner from the target's OWN rows at
/// that corner. Only possible when the target exposes exactly six rows. This
/// measures whether the objective is minimized at truth — it is NOT a claim
/// about blind performance and is always reported separately.
fn init_oracle(t: &dyn Target) -> Option<Vec<f64>> {
    let mut p = vec![0.0f64; NPARAM];
    for (ci, &(m, q)) in CORNER_MQ.iter().enumerate() {
        let rows = t.rows(m, q)?;
        if rows.len() != NUM_STAGES {
            return None;
        }
        for si in 0..NUM_STAGES {
            let base = (ci * NUM_STAGES + si) * PPS;
            let mut sp = biquad_to_stage_params(&rows[si]);
            clamp_stage(&mut sp);
            p[base..base + PPS].copy_from_slice(&sp);
        }
    }
    Some(p)
}

// ── the sampled target surface (precomputed once) ───────────────────────────

struct SurfaceState {
    label: String,
    m: f64,
    q: f64,
    h: Vec<Cf>,
}

struct Surface {
    freqs: Vec<f64>,
    w: Vec<f64>,
    states: Vec<SurfaceState>,
}

fn mq_grid(n: usize) -> Vec<(String, f64, f64)> {
    let mut out = Vec::new();
    for qi in 0..n {
        for mi in 0..n {
            let m = mi as f64 / (n - 1) as f64;
            let q = qi as f64 / (n - 1) as f64;
            out.push((
                format!(
                    "M{:03}_Q{:03}",
                    (m * 100.0).round() as i32,
                    (q * 100.0).round() as i32
                ),
                m,
                q,
            ));
        }
    }
    out
}

/// ENDPOINT_ONLY evidence: the four corners and nothing else.
fn corner_only_surface(t: &dyn Target) -> Surface {
    let freqs = log_frequency_grid(F_LO, F_HI, OBJ_F_BINS);
    let w: Vec<f64> = freqs.iter().map(|&f| 1.0 / f.max(F_LO)).collect();
    let states = CORNER_MQ
        .iter()
        .enumerate()
        .map(|(ci, &(m, q))| SurfaceState {
            label: CORNER_LABELS[ci].to_string(),
            m,
            q,
            h: freqs.iter().map(|&f| t.h(f, m, q)).collect(),
        })
        .collect();
    Surface { freqs, w, states }
}

/// H19 TRUE held-out grid: 8×8 at (2k+1)/16, so NO point coincides with the 5×5
/// training grid (multiples of 1/4). The previous 9×9 verification grid CONTAINED
/// every training point, so it measured fit-plus-interpolation rather than
/// generalisation. Acceptance is judged here.
fn held_out_surface(t: &dyn Target) -> Surface {
    let freqs = log_frequency_grid(F_LO, F_HI, OBJ_F_BINS);
    let w: Vec<f64> = freqs.iter().map(|&f| 1.0 / f.max(F_LO)).collect();
    let mut states = Vec::new();
    for qi in 0..8 {
        for mi in 0..8 {
            let m = (2 * mi + 1) as f64 / 16.0;
            let q = (2 * qi + 1) as f64 / 16.0;
            states.push(SurfaceState {
                label: format!(
                    "H_M{:03}_Q{:03}",
                    (m * 100.0).round() as i32,
                    (q * 100.0).round() as i32
                ),
                m,
                q,
                h: freqs.iter().map(|&f| t.h(f, m, q)).collect(),
            });
        }
    }
    Surface { freqs, w, states }
}

fn sample_surface(t: &dyn Target, n_mq: usize) -> Surface {
    let freqs = log_frequency_grid(F_LO, F_HI, OBJ_F_BINS);
    // H6: equal weight per octave. Applied identically to target and candidate.
    let w: Vec<f64> = freqs.iter().map(|&f| 1.0 / f.max(F_LO)).collect();
    let states = mq_grid(n_mq)
        .into_iter()
        .map(|(label, m, q)| SurfaceState {
            label,
            m,
            q,
            h: freqs.iter().map(|&f| t.h(f, m, q)).collect(),
        })
        .collect();
    Surface { freqs, w, states }
}

/// H28 search subset: five diagonal interior states and every twelfth frequency
/// bin from the declared 5x5x192 training surface. This ranks search moves only;
/// acceptance is always recomputed on the complete training surface and the
/// disjoint 8x8 held-out surface.
fn search_subset(s: &Surface) -> Surface {
    let bins: Vec<usize> = (0..s.freqs.len()).step_by(12).collect();
    let freqs = bins.iter().map(|&i| s.freqs[i]).collect();
    let w = bins.iter().map(|&i| s.w[i]).collect();
    let states = s
        .states
        .iter()
        .filter(|st| {
            st.m > 0.0
                && st.m < 1.0
                && st.q > 0.0
                && st.q < 1.0
                && ((st.m - st.q).abs() < 1.0e-12 || (st.m + st.q - 1.0).abs() < 1.0e-12)
        })
        .map(|st| SurfaceState {
            label: st.label.clone(),
            m: st.m,
            q: st.q,
            h: bins.iter().map(|&i| st.h[i]).collect(),
        })
        .collect();
    Surface { freqs, w, states }
}

// ── objective: packed surface vs target surface ─────────────────────────────

/// H7 interior-stability barrier. Corners can be stable while their packed-word
/// lerp overshoots the unit circle in between. LEGALITY only.
fn stability_penalty(packed: &PackedCorners) -> f64 {
    let mut acc = 0.0;
    for mi in 0..17 {
        for qi in 0..17 {
            let rows = packed.interpolate_biquad(mi as f32 / 16.0, qi as f32 / 16.0);
            for r in rows.iter() {
                let over = pole_radius(r[3], r[4]) - STAB_R;
                if over > 0.0 {
                    acc += over * over;
                }
            }
        }
    }
    acc
}

/// H14 packed-interpolation wrap barrier. The runtime's u16 lerp casts the
/// corner delta to i16 BEFORE adding the base, so a delta beyond i16::MAX wraps
/// and the interpolated word is garbage. Without this barrier the optimizer is
/// free to park words at opposite ends of the u16 range and produce an ILLEGAL
/// body (OBSERVED: `overbudget` reached a 65535 word delta). LEGALITY, not taste.
fn wrap_penalty(pc: &PackedCorners) -> f64 {
    let mut acc = 0.0;
    for si in 0..NUM_STAGES {
        for wi in 0..NUM_COEFFS {
            let v: [i32; 4] = std::array::from_fn(|ci| pc.words[ci][si][wi] as i32);
            for &(a, b) in &[(0usize, 1usize), (2, 3), (0, 2), (1, 3)] {
                let over = (v[b] - v[a]).abs() as f64 - i16::MAX as f64;
                if over > 0.0 {
                    acc += (over / i16::MAX as f64).powi(2);
                }
            }
        }
    }
    acc
}

const PEN_WRAP: f64 = 1.0e4;

/// H5/H6. Absolute gain preserved: no normalization, no offset, no per-state
/// gain fit. The number is directly comparable across candidates and fixtures.
fn response_objective(packed: &PackedCorners, s: &Surface) -> f64 {
    let mut err = 0.0f64;
    let mut wsum = 0.0f64;
    for st in &s.states {
        let rows = packed.interpolate_biquad(st.m as f32, st.q as f32);
        for (i, &f) in s.freqs.iter().enumerate() {
            let hc = biquad_cascade_complex(&rows, f, SR);
            let ht = st.h[i];
            let dmag = cdb(hc) - cdb(ht);
            let dph = wrap_pi(hc.1.atan2(hc.0) - ht.1.atan2(ht.0));
            err += s.w[i] * (dmag * dmag + LAMBDA_PH * dph * dph);
            wsum += s.w[i];
        }
    }
    err / wsum.max(1e-30)
}

fn surface_objective(packed: &PackedCorners, s: &Surface) -> f64 {
    response_objective(packed, s)
        + PEN_STAB * stability_penalty(packed)
        + PEN_WRAP * wrap_penalty(packed)
}

/// H31 qualification loss scaled by the fixed acceptance units.
///
/// A 0.5 dB magnitude residual and a 2 degree phase residual contribute equally.
/// This changes only solver search geometry; it never changes, normalizes, or
/// repairs the target/candidate response. Acceptance is recomputed independently
/// from raw residuals on the complete held-out grid.
fn qualification_response_objective(packed: &PackedCorners, s: &Surface) -> f64 {
    let mut err = 0.0f64;
    let mut wsum = 0.0f64;
    for st in &s.states {
        let rows = packed.interpolate_biquad(st.m as f32, st.q as f32);
        for (i, &f) in s.freqs.iter().enumerate() {
            let hc = biquad_cascade_complex(&rows, f, SR);
            let ht = st.h[i];
            let dmag = (cdb(hc) - cdb(ht)) / ACC_P90_DB;
            let dph_deg = wrap_pi(hc.1.atan2(hc.0) - ht.1.atan2(ht.0)).to_degrees() / ACC_PHASE_DEG;
            err += s.w[i] * (dmag * dmag + dph_deg * dph_deg);
            wsum += s.w[i];
        }
    }
    err / wsum.max(1e-30)
}

fn qualification_objective(packed: &PackedCorners, s: &Surface) -> f64 {
    qualification_response_objective(packed, s)
        + PEN_STAB * stability_penalty(packed)
        + PEN_WRAP * wrap_penalty(packed)
}

// ── optimizer (generic; not filter math) ────────────────────────────────────

/// H10 deterministic Hooke-Jeeves pattern search. Same input, same output.
///
/// NEGATIVE RESULT (MEASURED, kept so it is not re-tried): adding deterministic
/// step RESTARTS (re-inflating the step once it collapses, up to 6 times)
/// changed the final objective on all three fixtures by NOTHING — exact6 blind
/// stayed at 1.5275e1 to five significant figures. In hindsight it cannot help:
/// the exploration is a deterministic function of (incumbent, step), so
/// re-inflating the step from the same incumbent just replays the same failed
/// exploration. Escaping requires a DIFFERENT point or a different step pattern,
/// not a bigger step from the same one. The restart code was removed.
fn hooke_jeeves(
    mut base: Vec<f64>,
    obj: &dyn Fn(&[f64]) -> f64,
    max_iters: usize,
) -> (Vec<f64>, f64) {
    let step_pat = [0.06f64, 0.04, 0.06, 0.03, 0.06];
    let n = base.len();
    let step: Vec<f64> = (0..n).map(|j| step_pat[j % PPS]).collect();
    let clamp_all = |p: &mut [f64]| {
        for s in 0..(n / PPS) {
            clamp_stage(&mut p[s * PPS..s * PPS + PPS]);
        }
    };
    clamp_all(&mut base);
    let mut fb = obj(&base);
    let mut scale = 1.0f64;
    for _ in 0..max_iters {
        let mut trial = base.clone();
        for j in 0..n {
            let save = trial[j];
            trial[j] = save + step[j] * scale;
            clamp_all(&mut trial);
            if obj(&trial) < fb {
                continue;
            }
            trial[j] = save - step[j] * scale;
            clamp_all(&mut trial);
            if obj(&trial) >= fb {
                trial[j] = save;
            }
        }
        let ft = obj(&trial);
        if ft < fb - 1e-15 {
            let mut moved: Vec<f64> = (0..n).map(|j| trial[j] + (trial[j] - base[j])).collect();
            clamp_all(&mut moved);
            let fm = obj(&moved);
            if fm < ft {
                base = moved;
                fb = fm;
            } else {
                base = trial;
                fb = ft;
            }
        } else {
            scale *= 0.5;
            if scale < 1e-3 {
                break;
            }
        }
    }
    (base, fb)
}

// ── legality gates (stable + finite + packable = LEGAL, never "good") ───────

fn wrap_hazard(pc: &PackedCorners) -> (bool, i32) {
    // The runtime lerps morph first: corner0->corner1 and corner2->corner3. The
    // E-MU/MSVC lerp casts the delta to i16 BEFORE adding the base, so a delta
    // beyond i16::MAX wraps. The Q lerp then runs on results bounded by those
    // pairs, so the conservative bound is the max spread across all four corners.
    let mut worst = 0i32;
    let mut hazard = false;
    for si in 0..NUM_STAGES {
        for wi in 0..NUM_COEFFS {
            let v: Vec<i32> = (0..4).map(|ci| pc.words[ci][si][wi] as i32).collect();
            for &(a, b) in &[(0usize, 1usize), (2, 3), (0, 2), (1, 3)] {
                let d = (v[b] - v[a]).abs();
                worst = worst.max(d);
                if d > i16::MAX as i32 {
                    hazard = true;
                }
            }
        }
    }
    (hazard, worst)
}

fn cartridge_json(pc: &PackedCorners, name: &str) -> serde_json::Value {
    let keyframes: Vec<serde_json::Value> = (0..4)
        .map(|ci| {
            let words: Vec<Vec<u16>> = (0..NUM_STAGES)
                .map(|si| pc.words[ci][si].to_vec())
                .collect();
            serde_json::json!({"label": CORNER_LABELS[ci], "boost": 1.0, "packedWords": words})
        })
        .collect();
    serde_json::json!({
        "format": "compiled-v1", "name": name, "sampleRate": SR, "keyframes": keyframes
    })
}

fn legality(body: &[u8], pc: &PackedCorners, name: &str) -> serde_json::Value {
    let (hazard, worst) = wrap_hazard(pc);
    let load_save = pc.to_rom_bytes().to_vec() == body;
    let cart = cartridge_json(pc, name);
    let cart_parity = Cartridge::from_json(&cart.to_string())
        .map(|c| c.packed == *pc)
        .unwrap_or(false);

    // H4 sampled certification — NOT a continuum proof.
    let mut unstable = 0usize;
    let mut nonfinite = 0usize;
    let mut max_r = 0.0f64;
    for mi in 0..CERT_MQ {
        for qi in 0..CERT_MQ {
            let rows = pc.interpolate_biquad(
                mi as f32 / (CERT_MQ - 1) as f32,
                qi as f32 / (CERT_MQ - 1) as f32,
            );
            for r in rows.iter() {
                if !r.iter().all(|v| v.is_finite()) {
                    nonfinite += 1;
                }
                let rad = pole_radius(r[3], r[4]);
                max_r = max_r.max(rad);
                if rad >= 1.0 {
                    unstable += 1;
                }
            }
        }
    }

    // Real-root rows must be returned exactly and REFUSED by the conjugate
    // reader — never silently clamped into an approximate (hz, r).
    let mut real_rows = 0usize;
    let mut silent_clamps = 0usize;
    for ci in 0..4 {
        for si in 0..NUM_STAGES {
            let w = pc.words[ci][si];
            let g = geometry_from_words(w);
            let is_real = matches!(g.pole, RootPair::RealPair { .. })
                || matches!(g.zero, RootPair::RealPair { .. });
            if is_real {
                real_rows += 1;
                if trench_core::stage_law::roots_from_words(w).is_some() {
                    silent_clamps += 1;
                }
            }
        }
    }

    serde_json::json!({
        "meaning": "LEGAL = stable + finite + packable + parity. Legality is NEVER a claim of quality.",
        "exactly_240_bytes": body.len() == 240,
        "no_op_load_save_identical": load_save,
        "body_cart_parity": cart_parity,
        "packed_interp_wrap_hazard": hazard,
        "worst_corner_word_delta": worst,
        "i16_wrap_threshold": i16::MAX as i32,
        "sampled_certification": {
            "grid": format!("{CERT_MQ}x{CERT_MQ} Morph×Q"),
            "unstable_rows": unstable,
            "nonfinite_rows": nonfinite,
            "max_pole_radius": max_r,
            "note": "SAMPLED certification over a finite grid — NEVER a continuum proof."
        },
        "real_root_rows": real_rows,
        "silent_conjugate_clamps": silent_clamps,
        "legal": body.len() == 240 && load_save && cart_parity && !hazard
            && unstable == 0 && nonfinite == 0 && silent_clamps == 0,
    })
}

// ── residuals ───────────────────────────────────────────────────────────────

struct Residual {
    rms_db: f64,
    max_db: f64,
    median_db: f64,
    p90_db: f64,
    p99_db: f64,
    worst_label: String,
    worst_hz: f64,
    phase_rms_deg: f64,
}

impl Residual {
    fn json(&self) -> serde_json::Value {
        serde_json::json!({
            "rms_db": self.rms_db,
            "median_db": self.median_db,
            "p90_db": self.p90_db,
            "p99_db": self.p99_db,
            "max_db": self.max_db,
            "phase_rms_deg": self.phase_rms_deg,
            "worst_case_at": {"state": self.worst_label, "hz": self.worst_hz, "db": self.max_db},
            "read_this_as": "dB error is UNBOUNDED near a deep notch: if target and candidate \
                             nulls sit a few Hz apart, the dB difference there is enormous while \
                             almost nothing is audibly wrong. RMS and max are both dominated by \
                             those few bins. The MEDIAN and p90 describe the typical surface; the \
                             max localises the worst bin. Report all of them, trust none alone.",
        })
    }
}

fn residual(pc: &PackedCorners, s: &Surface) -> Residual {
    let mut sq = 0.0f64;
    let mut max_db = 0.0f64;
    let mut worst_label = String::new();
    let mut worst_hz = 0.0f64;
    let mut psq = 0.0f64;
    let mut all: Vec<f64> = Vec::with_capacity(s.states.len() * s.freqs.len());
    for st in &s.states {
        let rows = pc.interpolate_biquad(st.m as f32, st.q as f32);
        for (i, &f) in s.freqs.iter().enumerate() {
            let hc = biquad_cascade_complex(&rows, f, SR);
            let d = (cdb(hc) - cdb(st.h[i])).abs();
            sq += d * d;
            all.push(d);
            let dp = wrap_pi(hc.1.atan2(hc.0) - st.h[i].1.atan2(st.h[i].0)).to_degrees();
            psq += dp * dp;
            if d > max_db {
                max_db = d;
                worst_label = st.label.clone();
                worst_hz = f;
            }
        }
    }
    let n = all.len().max(1);
    all.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let pct = |p: f64| all[(((all.len() - 1) as f64) * p) as usize];
    Residual {
        rms_db: (sq / n as f64).sqrt(),
        max_db,
        median_db: pct(0.50),
        p90_db: pct(0.90),
        p99_db: pct(0.99),
        worst_label,
        worst_hz,
        phase_rms_deg: (psq / n as f64).sqrt(),
    }
}

// ── feature survival (REPORTING ONLY — assigns no lane identity) ───────────

#[derive(Clone, Copy)]
struct Feature {
    hz: f64,
    db: f64,
    peak: bool,
}

/// TRUE topographic prominence of the extremum at `i`: descend both ways until
/// the curve rises back above (peak) / falls back below (valley) this level or
/// the band ends; prominence is the height above the HIGHER of the two saddles.
///
/// The naive version — comparing against the two IMMEDIATE grid neighbours —
/// measures sharpness relative to GRID SPACING, not prominence: at the apex of a
/// smooth peak adjacent samples differ by ~0.05 dB, so a 1.5 dB threshold
/// rejects genuine resonances. (OBSERVED: it found 1 peak on a 5-resonance
/// fixture and reported ~1 feature per state on exact6 — the survival metric was
/// measuring nothing.) Pinned by `prominence_finds_known_resonances`.
fn prominence(db: &[f64], i: usize, peak: bool) -> f64 {
    let h = db[i];
    let sign = if peak { 1.0 } else { -1.0 };
    let mut saddle = [h, h];
    for (d, s) in [(-1i64, 0usize), (1i64, 1usize)] {
        let mut j = i as i64;
        loop {
            j += d;
            if j < 0 || j as usize >= db.len() {
                break;
            }
            let v = db[j as usize];
            if !v.is_finite() {
                break;
            }
            if sign * (v - h) > 0.0 {
                break; // risen back above (peak) / fallen below (valley)
            }
            if sign * (v - saddle[s]) < 0.0 {
                saddle[s] = v;
            }
        }
    }
    // the limiting saddle is the SHALLOWER descent (higher for a peak)
    let limiting = if peak {
        saddle[0].max(saddle[1])
    } else {
        saddle[0].min(saddle[1])
    };
    sign * (h - limiting)
}

/// H9 local extrema whose TRUE prominence is >= FEATURE_PROM_DB. Describes the
/// CURVE, not the lanes.
fn features(db: &[f64], freqs: &[f64]) -> Vec<Feature> {
    let mut out = Vec::new();
    for i in 1..db.len() - 1 {
        let (l, c, r) = (db[i - 1], db[i], db[i + 1]);
        if !l.is_finite() || !c.is_finite() || !r.is_finite() {
            continue;
        }
        if c > l && c >= r && prominence(db, i, true) >= FEATURE_PROM_DB {
            out.push(Feature {
                hz: freqs[i],
                db: c,
                peak: true,
            });
        }
        if c < l && c <= r && prominence(db, i, false) >= FEATURE_PROM_DB {
            out.push(Feature {
                hz: freqs[i],
                db: c,
                peak: false,
            });
        }
    }
    out
}

/// One-to-one greedy matching within H9's tolerance. Unmatched target features
/// are LOST; unmatched packed features are SPURIOUS. This is a survival report,
/// NOT a correspondence solution — it never touches lane registration.
fn feature_survival(pc: &PackedCorners, t: &dyn Target, s: &Surface) -> serde_json::Value {
    let (mut matched, mut lost, mut spurious) = (0usize, 0usize, 0usize);
    let mut worst_traj_oct = 0.0f64;
    let mut per_state = Vec::new();
    for st in &s.states {
        let rows = pc.interpolate_biquad(st.m as f32, st.q as f32);
        let cand_db: Vec<f64> = s
            .freqs
            .iter()
            .map(|&f| cdb(biquad_cascade_complex(&rows, f, SR)))
            .collect();
        let targ_db: Vec<f64> = s.freqs.iter().map(|&f| cdb(t.h(f, st.m, st.q))).collect();
        let tf = features(&targ_db, &s.freqs);
        let cf = features(&cand_db, &s.freqs);
        let mut used = vec![false; cf.len()];
        let (mut m_, mut l_) = (0usize, 0usize);
        for a in &tf {
            let mut best: Option<usize> = None;
            let mut bd = FEATURE_TOL_OCT;
            for (j, b) in cf.iter().enumerate() {
                if used[j] || b.peak != a.peak {
                    continue;
                }
                let d = (b.hz / a.hz).log2().abs();
                if d < bd {
                    bd = d;
                    best = Some(j);
                }
            }
            match best {
                Some(j) => {
                    used[j] = true;
                    m_ += 1;
                    worst_traj_oct = worst_traj_oct.max(bd);
                }
                None => l_ += 1,
            }
        }
        let s_ = used.iter().filter(|&&u| !u).count();
        matched += m_;
        lost += l_;
        spurious += s_;
        per_state.push(serde_json::json!({
            "label": st.label, "target_features": tf.len(),
            "matched": m_, "lost": l_, "spurious": s_
        }));
    }
    serde_json::json!({
        "method": "H9 REPORTING heuristic: local extrema (prominence >= 1.5 dB) matched \
                   one-to-one within 1/6 octave, peaks to peaks and notches to notches. \
                   Assigns NO lane identity. NOT a correspondence claim.",
        "matched": matched, "lost": lost, "spurious": spurious,
        "survival_rate": matched as f64 / (matched + lost).max(1) as f64,
        "worst_matched_trajectory_error_octaves": worst_traj_oct,
        "per_state": per_state,
    })
}

// ── correspondence diagnostic (exposes; never resolves by sorting) ─────────

fn mag_at(p: &PackedCorners, m: f64, q: f64, f: f64) -> f64 {
    cdb(biquad_cascade_complex(
        &p.interpolate_biquad(m as f32, q as f32),
        f,
        SR,
    ))
}

/// All 720 orderings of six lanes (Heap's algorithm). Used ONLY to MEASURE the
/// size of the correspondence equivalence class — never to search for a "best"
/// ordering to declare as truth.
fn perms6() -> Vec<[usize; 6]> {
    let mut out = Vec::with_capacity(720);
    let mut a = [0usize, 1, 2, 3, 4, 5];
    let mut c = [0usize; 6];
    out.push(a);
    let mut i = 0;
    while i < 6 {
        if c[i] < i {
            if i % 2 == 0 {
                a.swap(0, i);
            } else {
                a.swap(c[i], i);
            }
            out.push(a);
            c[i] += 1;
            i = 0;
        } else {
            c[i] = 0;
            i += 1;
        }
    }
    out
}

/// THE decisive measurement, kept as the harness's regression fixture: how far
/// apart are two registrations at the CORNERS versus in the INTERIOR?
///
/// MEASURED: 0.0 dB at the corners, ~25.8 dB in the interior. The cascade is a
/// permutation-invariant product, so the corner transfer functions simply do not
/// contain the registration. This is an identifiability boundary, not a hard
/// problem: no optimizer, no amount of corner data, and no cleverness can
/// recover what is not present.
fn discriminability(
    a: &PackedCorners,
    b: &PackedCorners,
    freqs: &[f64],
) -> (f64, f64, (f64, f64, f64)) {
    let mut corner_max = 0.0f64;
    for &(m, q) in &CORNER_MQ {
        for &f in freqs {
            corner_max = corner_max.max((mag_at(a, m, q, f) - mag_at(b, m, q, f)).abs());
        }
    }
    let mut interior_max = 0.0f64;
    let mut worst = (0.0f64, 0.0f64, 0.0f64);
    for mi in 1..8 {
        for qi in 0..3 {
            let (m, q) = (mi as f64 / 8.0, qi as f64 / 2.0);
            for &f in freqs {
                let d = (mag_at(a, m, q, f) - mag_at(b, m, q, f)).abs();
                if d > interior_max {
                    interior_max = d;
                    worst = (m, q, f);
                }
            }
        }
    }
    (corner_max, interior_max, worst)
}

/// Interior RMS dB between two bodies over the held-out interior.
fn interior_rms(a: &PackedCorners, b: &PackedCorners, freqs: &[f64]) -> f64 {
    let mut sq = 0.0;
    let mut n = 0usize;
    for mi in 0..9 {
        for qi in 0..3 {
            let (m, q) = (mi as f64 / 8.0, qi as f64 / 2.0);
            for &f in freqs {
                let d = mag_at(a, m, q, f) - mag_at(b, m, q, f);
                sq += d * d;
                n += 1;
            }
        }
    }
    (sq / n.max(1) as f64).sqrt()
}

/// MODE 1 — ENDPOINT_ONLY.
///
/// Reports the correspondence EQUIVALENCE CLASS and refuses to choose. There is
/// no "truth" and no "decoy" here: pairing A and pairing B are indistinguishable
/// members of one class. `selected_permutation` is ALWAYS null, by contract.
fn endpoint_only_report(a: &PackedCorners, b: &PackedCorners, freqs: &[f64]) -> serde_json::Value {
    let (corner_db, interior_db, worst) = discriminability(a, b, freqs);
    // Distinct interiors consistent with the SAME four corner transfer functions:
    // each corner's six sections may be ordered 6! ways -> (6!)^4 assignments;
    // relabelling every corner by the same permutation leaves the interior
    // untouched, so quotient by 6! -> (6!)^3. Upper bound: exactly duplicated
    // sections (e.g. two identity lanes) collapse the class further.
    let fact6: u64 = 720;
    let class = fact6 * fact6 * fact6;
    // Concretely: permute ONE corner's lanes and count how many of the 720
    // orderings give a measurably different interior. All of them share this
    // body's four corner transfer functions exactly.
    let mut distinct = 0usize;
    for p in perms6() {
        let mut trial = a.clone();
        for (slot, &old) in p.iter().enumerate() {
            trial.words[1][slot] = a.words[1][old];
        }
        let mut moved = false;
        for &f in freqs.iter().step_by(8) {
            if (mag_at(&trial, 0.5, 0.0, f) - mag_at(a, 0.5, 0.0, f)).abs() > 0.5 {
                moved = true;
                break;
            }
        }
        if moved {
            distinct += 1;
        }
    }
    serde_json::json!({
        "mode": EvidenceMode::EndpointOnly.label(),
        "evidence": "the four corner transfer functions ONLY",
        "corner_only_discriminability_db": corner_db,
        "interior_discriminability_db": interior_db,
        "interior_worst_at": {"morph": worst.0, "q": worst.1, "hz": worst.2},
        "equivalence_class": {
            "distinct_interiors_upper_bound": class,
            "derivation": "(6!)^4 lane orderings across four corners, quotiented by the 6! global \
                           relabelling that leaves the interior unchanged => (6!)^3 = 373,248,000. \
                           An UPPER BOUND: exactly duplicated sections collapse it further.",
            "measured_single_corner_orderings_changing_the_interior": distinct,
            "measured_single_corner_orderings_total": 720,
            "meaning": "every one of these shares this body's four corner transfer functions \
                        EXACTLY, and they render different interiors.",
        },
        "selected_permutation": serde_json::Value::Null,
        "verdict": "AMBIGUOUS",
        "statement": "The registration is NOT IDENTIFIABLE from endpoint evidence. Corner \
                      discriminability is 0.0 dB — the cascade is a permutation-invariant product, \
                      so the corner transfer functions do not contain the registration at all. \
                      The interior differs by 25.8 dB, which is exactly why the choice matters and \
                      exactly why it cannot be made here. Pairing A and pairing B are equally \
                      consistent with this evidence; NEITHER is truth and NEITHER is a decoy. \
                      This harness selects no permutation under ENDPOINT_ONLY evidence. Frequency \
                      sorting would silently pick one and report a perfect corner match.",
    })
}

/// MODE 2 — OBSERVED_SURFACE.
///
/// Interior observations exist, so candidates can be RANKED by their actual
/// packed-runtime interior error against them. Reports the winning margin and
/// REFUSES when the margin is insignificant (H16).
fn observed_surface_report(
    candidates: &[(&str, &PackedCorners)],
    observed: &Surface,
    freqs: &[f64],
) -> serde_json::Value {
    const DECIDE_DB: f64 = 0.5;
    // Rank by error against the OBSERVED interior samples — the real evidence,
    // through the real packed runtime. Not against any assumed truth.
    let mut ranked: Vec<(String, f64)> = candidates
        .iter()
        .map(|(name, pc)| (name.to_string(), residual(pc, observed).rms_db))
        .collect();
    ranked.sort_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal));
    let margin = if ranked.len() >= 2 {
        ranked[1].1 - ranked[0].1
    } else {
        f64::INFINITY
    };
    let decided = margin >= DECIDE_DB;
    let _ = freqs;
    serde_json::json!({
        "mode": EvidenceMode::ObservedSurface.label(),
        "evidence": format!("{} interior H_target samples on a {}x{} Morph×Q grid",
                            observed.states.len(), VERIFY_MQ, VERIFY_MQ),
        "ranking": ranked.iter().map(|(n, e)| serde_json::json!({
            "candidate": n, "interior_rms_db_vs_observations": e
        })).collect::<Vec<_>>(),
        "winner": if decided { serde_json::json!(ranked[0].0) } else { serde_json::Value::Null },
        "margin_db": margin,
        "decision_threshold_db": DECIDE_DB,
        "verdict": if decided { "RANKED" } else { "REFUSED — margin insignificant" },
        "statement": if decided {
            "The interior observations separate the candidates by more than the decision \
             threshold. The winner is ranked BY MEASURED INTERIOR ERROR against real \
             observations — it is not asserted, and it is not recovered from the corners."
        } else {
            "REFUSED. The interior observations do NOT separate the candidates by more than the \
             decision threshold. The harness reports no winner. A nearer-by-noise candidate is \
             not a result."
        },
    })
}

/// MODE 3 — AUTHORED_TRAJECTORY.
///
/// The source model supplies the actor identities. They are preserved verbatim
/// as an authoring PRIOR and labelled AUTHORED. Nothing here is a recovery claim.
fn authored_trajectory_report(
    t: &dyn Target,
    a: &PackedCorners,
    b: &PackedCorners,
    freqs: &[f64],
) -> serde_json::Value {
    let (corner_db, interior_db, _) = discriminability(a, b, freqs);
    // Only the AUTHORED morph endpoints. This fixture's source model declares
    // identities at its corners; its interior is produced by packed
    // interpolation, so quoting an "authored identity" at morph 0.5 would imply
    // a continuous trajectory the model does not actually define.
    let traj: Vec<serde_json::Value> = [0.0f64, 1.0]
        .iter()
        .filter_map(|&m| {
            t.authored_lanes(m, 0.0)
                .map(|lanes| serde_json::json!({"morph": m, "lanes": lanes}))
        })
        .collect();
    serde_json::json!({
        "mode": EvidenceMode::AuthoredTrajectory.label(),
        "evidence": "a continuous source model that DECLARES which actor occupies which lane",
        "provenance": "AUTHORED",
        "authored_lane_identities": traj,
        "corner_only_discriminability_db": corner_db,
        "interior_discriminability_db": interior_db,
        "statement": "These lane identities are an AUTHORING PRIOR supplied by the source model. \
                      They are DECLARED, never RECOVERED. The corners remain 0.0 dB apart from the \
                      alternative pairing, so nothing here was identified from the transfer \
                      functions — the source model simply told us, and we preserved it. Labelling \
                      this 'recovered correspondence' would be false: an identical body with the \
                      other pairing fits the endpoint evidence exactly as well.",
        "forbidden": "This prior must never be reported as RECOVERED, and must never be used to \
                      claim the endpoint evidence identified the registration.",
    })
}

/// MEASURED SOLVER FAILURE — not a boundary result, and NOT a required invariant.
///
/// CORRECTION (this replaces an earlier, wrong reading). The blind fit is trained
/// on the 5×5 Morph×Q grid, which INCLUDES interior points — that is
/// OBSERVED_SURFACE evidence. Under the evidence contract such a solver is
/// PERMITTED AND EXPECTED to resolve the registration: the interior separates
/// pairing A from pairing B by 25.82 dB, and `observed_surface_report` ranks them
/// cleanly at a 3.608 dB margin from the very same samples.
///
/// So the equidistant result below (3.505 vs 3.502 dB, margin 0.003 dB) is a
/// MEASURED FAILURE OF THE SOLVER — it could not exploit evidence that is
/// demonstrably present and sufficient. Treating it as a "required negative
/// result" was an error: it enshrined a solver deficiency as if it were the
/// identifiability boundary. The boundary is ENDPOINT_ONLY => AMBIGUOUS, and it
/// stands on its own (0.0 dB corner discriminability). It says nothing about what
/// an interior-trained solver should achieve.
fn solver_correspondence_failure(
    fitted: &PackedCorners,
    pairing_a: &PackedCorners,
    pairing_b: &PackedCorners,
    freqs: &[f64],
) -> serde_json::Value {
    const DECIDE_DB: f64 = 0.5;
    let va = interior_rms(fitted, pairing_a, freqs);
    let vb = interior_rms(fitted, pairing_b, freqs);
    let margin = (vb - va).abs();
    let resolved = margin >= DECIDE_DB;
    serde_json::json!({
        "status": "MEASURED SOLVER FAILURE (not a required negative result, not a boundary result)",
        "evidence_available_to_this_solver": "OBSERVED_SURFACE — the 5x5 training grid includes \
                                              interior points, which separate the pairings by 25.82 dB",
        "fit_interior_rms_db_vs_pairing_a": va,
        "fit_interior_rms_db_vs_pairing_b": vb,
        "nearer_pairing": if va < vb { "pairing_a" } else { "pairing_b" },
        "margin_db": margin,
        "decision_threshold_db": DECIDE_DB,
        "verdict": if resolved { "RESOLVED" } else { "FAILED_TO_RESOLVE" },
        "statement": if resolved {
            "The solver resolved the registration from interior evidence — the expected outcome \
             for OBSERVED_SURFACE evidence."
        } else {
            "FAILED. The solver is equidistant from pairing A and pairing B despite being trained \
             on interior samples that separate them by 25.82 dB. The evidence is present and \
             sufficient — `observed_surface_report` ranks the pairings at a 3.608 dB margin from \
             the same grid — so this is a SOLVER deficiency, not an identifiability limit. It is \
             a qualification failure to be fixed, never an invariant to be preserved."
        },
    })
}

// ── audio: BODY SOLO through the owned Cascade, no normalization ────────────

/// Deterministic pink-ish noise. Identical bytes for every render in every
/// fixture, so any level difference between renders is the filter, not the input.
fn dry_signal(n: usize) -> Vec<f32> {
    let mut rng = 0x2545_F491_4F6C_DD1Du64;
    let mut pb = [0f64; 7];
    (0..n)
        .map(|_| {
            rng = rng
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
            let w = ((rng >> 40) as f64 / (1u64 << 23) as f64) - 1.0;
            pb[0] = 0.99886 * pb[0] + w * 0.0555179;
            pb[1] = 0.99332 * pb[1] + w * 0.0750759;
            pb[2] = 0.96900 * pb[2] + w * 0.1538520;
            pb[3] = 0.86650 * pb[3] + w * 0.3104856;
            pb[4] = 0.55000 * pb[4] + w * 0.5329522;
            pb[5] = -0.7616 * pb[5] - w * 0.0168980;
            let s = (pb[0] + pb[1] + pb[2] + pb[3] + pb[4] + pb[5] + pb[6] + w * 0.5362) * 0.11;
            pb[6] = w * 0.115926;
            (s * 0.25) as f32
        })
        .collect()
}

/// Render ANY number of ordered rows through the OWNED `Cascade`, six at a time.
/// A serial cascade composes, so >6 rows = successive passes. Static state:
/// coefficients are snapped, never ramped. No AGC, no drive, no boost, no gain.
fn render_rows(rows: &[[f64; NUM_COEFFS]], dry: &[f32]) -> Vec<f32> {
    let mut buf = dry.to_vec();
    for chunk in rows.chunks(NUM_STAGES) {
        let mut corner: CornerData = [[1.0, 0.0, 0.0, 0.0, 0.0]; NUM_STAGES];
        for (i, r) in chunk.iter().enumerate() {
            corner[i] = *r;
        }
        let mut c = Cascade::new();
        c.snap_targets(&corner);
        c.process_block_mono(&mut buf);
    }
    buf
}

/// Packed morph/Q sweep through the runtime path: per-block `set_targets` with a
/// block-length ramp — the shipped behaviour. No normalization.
fn render_sweep(pc: &PackedCorners, dry: &[f32], from: (f64, f64), to: (f64, f64)) -> Vec<f32> {
    const BLOCK: usize = 32;
    let mut casc = Cascade::new();
    let mut out = Vec::with_capacity(dry.len());
    let mut i = 0usize;
    while i < dry.len() {
        let len = BLOCK.min(dry.len() - i);
        let t = i as f64 / dry.len() as f64;
        let m = from.0 + (to.0 - from.0) * t;
        let q = from.1 + (to.1 - from.1) * t;
        casc.set_targets(&pc.interpolate_biquad(m as f32, q as f32), len);
        let mut buf = dry[i..i + len].to_vec();
        casc.process_block_mono(&mut buf);
        out.extend_from_slice(&buf);
        i += len;
    }
    out
}

fn stats(x: &[f32]) -> (f64, f64, usize) {
    let peak = x.iter().fold(0.0f64, |m, &v| m.max(v.abs() as f64));
    let rms =
        (x.iter().map(|&v| (v as f64) * (v as f64)).sum::<f64>() / x.len().max(1) as f64).sqrt();
    let clip = x.iter().filter(|&&v| v.abs() >= 1.0).count();
    (peak, rms, clip)
}

/// Energy ratio of (target - packed) to target, over identical input. Absolute:
/// no delay search (H12: zero transport delay), no gain match, no normalization.
fn null_db(a: &[f32], b: &[f32]) -> f64 {
    let n = a.len().min(b.len());
    let mut num = 0.0f64;
    let mut den = 0.0f64;
    for i in 0..n {
        let d = a[i] as f64 - b[i] as f64;
        num += d * d;
        den += (a[i] as f64) * (a[i] as f64);
    }
    10.0 * (num.max(1e-30) / den.max(1e-30)).log10()
}

fn wav_write(path: &Path, x: &[f32], sr: u32) {
    let mut b = Vec::with_capacity(44 + x.len() * 4);
    let dl = (x.len() * 4) as u32;
    b.extend_from_slice(b"RIFF");
    b.extend_from_slice(&(36 + dl).to_le_bytes());
    b.extend_from_slice(b"WAVEfmt ");
    b.extend_from_slice(&16u32.to_le_bytes());
    b.extend_from_slice(&3u16.to_le_bytes()); // IEEE float: absolute values preserved
    b.extend_from_slice(&1u16.to_le_bytes());
    b.extend_from_slice(&sr.to_le_bytes());
    b.extend_from_slice(&(sr * 4).to_le_bytes());
    b.extend_from_slice(&4u16.to_le_bytes());
    b.extend_from_slice(&32u16.to_le_bytes());
    b.extend_from_slice(b"data");
    b.extend_from_slice(&dl.to_le_bytes());
    for &v in x {
        b.extend_from_slice(&v.to_le_bytes());
    }
    std::fs::write(path, b).expect("write wav");
}

fn audio_proof(root: &Path, pc: &PackedCorners, t: &dyn Target) -> serde_json::Value {
    let dir = root.join("audio");
    std::fs::create_dir_all(&dir).unwrap();
    let n = (2.0 * SR) as usize;
    let dry = dry_signal(n);
    wav_write(&dir.join("dry.wav"), &dry, SR as u32);
    let (dpk, drms, _) = stats(&dry);

    let mut per_state = Vec::new();
    for (ci, &(m, q)) in CORNER_MQ.iter().enumerate() {
        let prows = pc.interpolate_biquad(m as f32, q as f32);
        let pk_wet = render_rows(&prows, &dry);
        wav_write(
            &dir.join(format!("packed_{}.wav", CORNER_LABELS[ci])),
            &pk_wet,
            SR as u32,
        );
        let (pp, pr, pc_clip) = stats(&pk_wet);
        let mut row = serde_json::json!({
            "state": CORNER_LABELS[ci], "morph": m, "q": q,
            "packed_peak": pp, "packed_rms": pr, "packed_clip_samples": pc_clip,
        });
        if let Some(trows) = t.rows(m, q) {
            let tg_wet = render_rows(&trows, &dry);
            wav_write(
                &dir.join(format!("target_{}.wav", CORNER_LABELS[ci])),
                &tg_wet,
                SR as u32,
            );
            let resid: Vec<f32> = (0..tg_wet.len().min(pk_wet.len()))
                .map(|i| tg_wet[i] - pk_wet[i])
                .collect();
            wav_write(
                &dir.join(format!("residual_{}.wav", CORNER_LABELS[ci])),
                &resid,
                SR as u32,
            );
            let (tp, tr, tc) = stats(&tg_wet);
            row["target_peak"] = tp.into();
            row["target_rms"] = tr.into();
            row["target_clip_samples"] = tc.into();
            row["null_db"] = null_db(&tg_wet, &pk_wet).into();
        }
        per_state.push(row);
    }

    // Interior state the fit never saw at this exact point, plus the journeys.
    let mut sweeps = Vec::new();
    for (name, from, to) in [
        ("morph_q0", (0.0, 0.0), (1.0, 0.0)),
        ("morph_q100", (0.0, 1.0), (1.0, 1.0)),
        ("q_m0", (0.0, 0.0), (0.0, 1.0)),
        ("diagonal", (0.0, 0.0), (1.0, 1.0)),
    ] {
        let w = render_sweep(pc, &dry, from, to);
        wav_write(&dir.join(format!("sweep_{name}.wav")), &w, SR as u32);
        let (p, r, c) = stats(&w);
        sweeps.push(serde_json::json!({"sweep": name, "peak": p, "rms": r, "clip_samples": c}));
    }

    serde_json::json!({
        "path": "BODY SOLO: the owned Cascade only. No AGC, no drive, no boost, no make-up gain.",
        "input": "identical deterministic pink-ish noise for EVERY render in every fixture",
        "normalization": "NONE — absolute sample values are written verbatim (32-bit float WAV)",
        "dry_peak": dpk, "dry_rms": drms,
        "static_states": per_state,
        "sweeps_packed_runtime_ramped": sweeps,
        "null_meaning": "10*log10(sum((target-packed)^2)/sum(target^2)) at identical input, \
                         no delay search, no gain match. Lower = the packed body reproduces \
                         the target's actual waveform.",
    })
}

// ── SVG (target vs packed, shared dB axis) ─────────────────────────────────

fn svg_response(title: &str, freqs: &[f64], curves: &[(&str, &str, Vec<f64>)]) -> String {
    let (w, h) = (1100.0f64, 600.0f64);
    let (ml, mr, mt, mb) = (70.0, 20.0, 40.0, 50.0);
    let (pw, ph) = (w - ml - mr, h - mt - mb);
    let mut ymin = f64::INFINITY;
    let mut ymax = f64::NEG_INFINITY;
    for (_, _, d) in curves {
        for &v in d {
            if v.is_finite() {
                ymin = ymin.min(v);
                ymax = ymax.max(v);
            }
        }
    }
    if !ymin.is_finite() {
        ymin = -60.0;
        ymax = 12.0;
    }
    ymin = (ymin - 3.0).floor();
    ymax = (ymax + 3.0).ceil();
    let xof = |f: f64| ml + pw * ((f.max(F_LO).ln() - F_LO.ln()) / (F_HI.ln() - F_LO.ln()));
    let yof = |db: f64| mt + ph * (1.0 - (db - ymin) / (ymax - ymin).max(1e-9));
    let mut s = format!(
        "<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' font-family='monospace' font-size='12'>\
         <rect width='{w}' height='{h}' fill='#111'/><text x='{ml}' y='22' fill='#ccc'>{title}</text>"
    );
    let mut db = (ymin / 12.0).ceil() * 12.0;
    while db <= ymax {
        let y = yof(db);
        s.push_str(&format!(
            "<line x1='{ml}' y1='{y:.1}' x2='{x2:.1}' y2='{y:.1}' stroke='#333'/><text x='6' y='{ty:.1}' fill='#888'>{db:.0}</text>",
            x2 = ml + pw, ty = y + 4.0
        ));
        db += 12.0;
    }
    for &f in &[30.0, 100.0, 300.0, 1000.0, 3000.0, 10000.0] {
        let x = xof(f);
        let lbl = if f >= 1000.0 {
            format!("{:.0}k", f / 1000.0)
        } else {
            format!("{f:.0}")
        };
        s.push_str(&format!(
            "<line x1='{x:.1}' y1='{mt}' x2='{x:.1}' y2='{y2:.1}' stroke='#282828'/><text x='{tx:.1}' y='{ty:.1}' fill='#888'>{lbl}</text>",
            y2 = mt + ph, tx = x - 10.0, ty = h - mb + 16.0
        ));
    }
    for (_, color, data) in curves {
        let mut pts = String::new();
        for (i, &f) in freqs.iter().enumerate() {
            if data[i].is_finite() {
                pts.push_str(&format!("{:.1},{:.1} ", xof(f), yof(data[i])));
            }
        }
        s.push_str(&format!(
            "<polyline points='{pts}' fill='none' stroke='{color}' stroke-width='1.6'/>"
        ));
    }
    let lx = ml + pw - 190.0;
    for (row, (name, color, _)) in curves.iter().enumerate() {
        let ly = mt + 6.0 + row as f64 * 18.0;
        s.push_str(&format!(
            "<rect x='{lx:.0}' y='{ly:.0}' width='12' height='12' fill='{color}'/><text x='{tx:.0}' y='{ty:.0}' fill='#ccc'>{name}</text>",
            tx = lx + 16.0, ty = ly + 11.0
        ));
    }
    s.push_str("</svg>");
    s
}

fn plot_states(
    root: &Path,
    pc: &PackedCorners,
    t: &dyn Target,
    freqs: &[f64],
    states: &[(&str, f64, f64)],
) -> Vec<String> {
    let dir = root.join("plots");
    std::fs::create_dir_all(&dir).unwrap();
    let mut out = Vec::new();
    for &(label, m, q) in states {
        let rows = pc.interpolate_biquad(m as f32, q as f32);
        let tg: Vec<f64> = freqs.iter().map(|&f| cdb(t.h(f, m, q))).collect();
        let pk: Vec<f64> = freqs
            .iter()
            .map(|&f| cdb(biquad_cascade_complex(&rows, f, SR)))
            .collect();
        let err: Vec<f64> = (0..freqs.len()).map(|i| pk[i] - tg[i]).collect();
        let svg = svg_response(
            &format!("{} — target vs packed runtime (morph {m:.3}, q {q:.3}) — shared dB axis, absolute gain", t.name()),
            freqs,
            &[
                ("target", "#e0b030", tg),
                ("packed runtime", "#30c0e0", pk),
                ("error (packed - target)", "#e06060", err),
            ],
        );
        let p = dir.join(format!("{label}.svg"));
        std::fs::write(&p, svg).unwrap();
        out.push(format!("plots/{label}.svg"));
    }
    out
}

// ── SHA-256 (dependency-free; KAT-checked below) ───────────────────────────

fn sha256_hex(bytes: &[u8]) -> String {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let mut state = [
        0x6a09e667u32,
        0xbb67ae85,
        0x3c6ef372,
        0xa54ff53a,
        0x510e527f,
        0x9b05688c,
        0x1f83d9ab,
        0x5be0cd19,
    ];
    let bit_len = (bytes.len() as u64).wrapping_mul(8);
    let padded_len = (bytes.len() + 9 + 63) / 64 * 64;
    let mut padded = Vec::with_capacity(padded_len);
    padded.extend_from_slice(bytes);
    padded.push(0x80);
    padded.resize(padded_len - 8, 0);
    padded.extend_from_slice(&bit_len.to_be_bytes());
    for chunk in padded.chunks_exact(64) {
        let mut w = [0u32; 64];
        for (i, word) in w[..16].iter_mut().enumerate() {
            let o = i * 4;
            *word = u32::from_be_bytes([chunk[o], chunk[o + 1], chunk[o + 2], chunk[o + 3]]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let mut v = state;
        for i in 0..64 {
            let s1 = v[4].rotate_right(6) ^ v[4].rotate_right(11) ^ v[4].rotate_right(25);
            let ch = (v[4] & v[5]) ^ ((!v[4]) & v[6]);
            let t1 = v[7]
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = v[0].rotate_right(2) ^ v[0].rotate_right(13) ^ v[0].rotate_right(22);
            let maj = (v[0] & v[1]) ^ (v[0] & v[2]) ^ (v[1] & v[2]);
            let t2 = s0.wrapping_add(maj);
            v = [
                t1.wrapping_add(t2),
                v[0],
                v[1],
                v[2],
                v[3].wrapping_add(t1),
                v[4],
                v[5],
                v[6],
            ];
        }
        for i in 0..8 {
            state[i] = state[i].wrapping_add(v[i]);
        }
    }
    let mut out = String::with_capacity(64);
    for word in state {
        use std::fmt::Write;
        let _ = write!(out, "{word:08x}");
    }
    out
}

// ── lane registration table (what actually got packed, per lane) ────────────

fn lane_table(pc: &PackedCorners) -> serde_json::Value {
    let mut rows = Vec::new();
    for si in 0..NUM_STAGES {
        let mut per_corner = Vec::new();
        for ci in 0..4 {
            let w = pc.words[ci][si];
            let g = geometry_from_words(w);
            let fmt = |p: &RootPair| match p {
                RootPair::Conjugate { hz, r } => {
                    serde_json::json!({"kind":"Conjugate","hz":hz,"r":r})
                }
                RootPair::RealPair { root_a, root_b } => {
                    serde_json::json!({"kind":"RealPair","root_a":root_a,"root_b":root_b})
                }
                RootPair::Degenerate => serde_json::json!({"kind":"Degenerate"}),
            };
            let identity = matches!(g.pole, RootPair::Degenerate)
                && matches!(g.zero, RootPair::Degenerate)
                && (g.scale - 1.0).abs() < 1e-9;
            per_corner.push(serde_json::json!({
                "corner": CORNER_LABELS[ci],
                "pole": fmt(&g.pole), "zero": fmt(&g.zero),
                "scale_b0": g.scale,
                "identity_biquad": identity,
                "evidence_provenance": "PACKED_RUNTIME decoded from candidate words",
                "words": w.to_vec(),
            }));
        }
        rows.push(serde_json::json!({"lane": si, "corners": per_corner}));
    }
    serde_json::json!({
        "law": "Lane index is the registration and is FIXED by construction across all four \
                corners. The harness never sorts, reorders, or re-pairs lanes.",
        "lanes": rows,
    })
}

// ── one fixture run ─────────────────────────────────────────────────────────

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_path_buf()
}

struct FitRun {
    init: &'static str,
    obj_init: f64,
    obj_final: f64,
    params: Vec<f64>,
}

fn fit(init: &'static str, start: Vec<f64>, surf: &Surface, iters: usize) -> FitRun {
    let obj = |p: &[f64]| surface_objective(&params_to_packed(p), surf);
    let obj_init = obj(&start);
    let (params, obj_final) = hooke_jeeves(start, &obj, iters);
    FitRun {
        init,
        obj_init,
        obj_final,
        params,
    }
}

fn run_fixture(t: &dyn Target, iters: usize) -> serde_json::Value {
    let root = repo_root()
        .join("dev")
        .join("tmp")
        .join("tf_harness")
        .join(t.name());
    std::fs::create_dir_all(&root).unwrap();
    println!("\n=== fixture: {} ===", t.name());
    println!("{}", t.describe());

    // The surface the optimizer sees (H2) and the held-out verification surface (H3).
    let train = sample_surface(t, OBJ_MQ);
    let verify = sample_surface(t, VERIFY_MQ);

    // THE CANDIDATE is always the BLIND run. A real arbitrary target has no
    // oracle, so the blind path is the harness's actual capability and the only
    // honest thing to report as "the candidate".
    let blind = fit("spread_blind", init_spread(), &train, iters);

    // Identifiability PROBE (H11), reported separately and never promoted to
    // "the candidate": seed from the target's own rows and ask whether the
    // objective bottoms out AT truth. It answers "is the objective correct?",
    // NOT "can the harness find it?". Conflating the two would let the oracle
    // launder a blind failure into a perfect-looking result.
    let oracle = init_oracle(t).map(|p| fit("oracle_rows", p, &train, iters));

    let chosen: &FitRun = &blind;
    let pc = params_to_packed(&chosen.params);
    let body = pc.to_rom_bytes();
    std::fs::write(root.join("candidate.body240"), body).unwrap();
    let cart = cartridge_json(&pc, &format!("tf-harness-{}", t.name()));
    std::fs::write(
        root.join("candidate.cart.json"),
        serde_json::to_string_pretty(&cart).unwrap(),
    )
    .unwrap();

    let legal = legality(&body, &pc, &format!("tf-harness-{}", t.name()));
    let res_train = residual(&pc, &train);
    let res_verify = residual(&pc, &verify);
    let surv = feature_survival(&pc, t, &verify);

    // Neutral reference: the identity body. Establishes what "did the fit do
    // anything at all" means, in the same units. Not a quality claim.
    let ident_pc = params_to_packed(&init_identity());
    let res_ident = residual(&ident_pc, &verify);

    let plots = plot_states(
        &root,
        &pc,
        t,
        &verify.freqs,
        &[
            ("M000_Q000", 0.0, 0.0),
            ("M100_Q000", 1.0, 0.0),
            ("M000_Q100", 0.0, 1.0),
            ("M100_Q100", 1.0, 1.0),
            ("M050_Q050_interior", 0.5, 0.5),
            ("M025_Q075_interior", 0.25, 0.75),
        ],
    );
    let audio = audio_proof(&root, &pc, t);

    let mut report = serde_json::json!({
        "schema": "tf-harness-fixture-v1",
        "fixture": t.name(),
        "target": t.describe(),
        "target_pole_pairs": t.pole_pairs(),
        "format_capacity_pole_pairs": NUM_STAGES,
        "hypotheses": hypotheses(),
        "fit": {
            "optimizer": "H10 deterministic Hooke-Jeeves pattern search",
            "iterations": iters,
            "free_params": NPARAM,
            "objective": "H5/H6 weighted (dB^2 + 4*phase_rad^2) over the H2 5x5 Morph×Q grid \
                          through the REAL packed loop, PLUS the H7 stability barrier. \
                          Absolute gain — no normalization anywhere.",
            "candidate_run_blind": {
                "init": blind.init,
                "init_meaning": "H13 target-agnostic log-spaced lane spread. Never looks at the target.",
                "objective_init": blind.obj_init,
                "objective_final": blind.obj_final,
            },
            "identifiability_probe_oracle": oracle.as_ref().map(|o| serde_json::json!({
                "objective_init": o.obj_init,
                "objective_final": o.obj_final,
                "held_out_error": residual(&params_to_packed(&o.params), &verify).json(),
                "meaning": "Seeded from the target's OWN rows at each corner. Answers 'is the \
                            objective minimized at truth?' — NOT 'can the harness find it?'. \
                            A real arbitrary target has no oracle. This run is NEVER reported \
                            as the candidate.",
                "gap_to_blind": "objective_final(blind) - objective_final(oracle) is the \
                                 OPTIMIZER's shortfall, isolated from any modelling error.",
            })),
            "reported_candidate_from": chosen.init,
            "selection_rule": "The candidate is ALWAYS the blind run. The oracle probe cannot be \
                               promoted to candidate under any circumstance.",
        },
        "accuracy": {
            "train_grid": res_train.json(),
            "held_out_grid": {
                "grid": format!("{VERIFY_MQ}x{VERIFY_MQ} — interior points the fit never scored"),
                "error": res_verify.json(),
            },
            "identity_body_reference": {
                "error": res_ident.json(),
                "meaning": "the neutral all-identity body against the same target. Units for \
                            'did the fit do anything at all'. NOT a quality baseline.",
            },
        },
        "feature_survival": surv,
        "legality": legal,
        "lane_registration": lane_table(&pc),
        "audio": audio,
        "plots": plots,
        "artifacts": {
            "body240_sha256": sha256_hex(&body),
            "body240": "candidate.body240",
            "cart": "candidate.cart.json",
        },
    });

    // ── the identifiability boundary, exercised in all three evidence modes ──
    //
    // The crossing fixture is the harness's decisive regression fixture: 0.0 dB
    // corner discriminability, ~25.8 dB interior. Running one body through all
    // three modes shows the boundary is about EVIDENCE, not about difficulty:
    // the same body is AMBIGUOUS, RANKED, or AUTHORED depending only on what is
    // actually known.
    if t.name() == "crossing" {
        let pa = Crossing::pairing_a();
        let pb = Crossing::pairing_b();
        report["evidence_modes"] = serde_json::json!({
            "contract": "What the harness may conclude about lane correspondence depends ONLY on \
                         what evidence exists. It never asks 'what is the true correspondence?' — \
                         from endpoint evidence that question has no answer.",
            "declared_mode_for_this_target": t.evidence_mode().label(),
            "endpoint_only": endpoint_only_report(&pa, &pb, &verify.freqs),
            "observed_surface": observed_surface_report(
                &[("pairing_a", &pa), ("pairing_b", &pb)], &verify, &verify.freqs),
            "authored_trajectory": authored_trajectory_report(t, &pa, &pb, &verify.freqs),
        });
        report["solver_correspondence_failure"] =
            solver_correspondence_failure(&pc, &pa, &pb, &verify.freqs);
    }
    if let Some(pp) = t.pole_pairs() {
        if pp > NUM_STAGES {
            report["order_deficit"] = serde_json::json!({
                "target_pole_pairs": pp,
                "format_capacity_pole_pairs": NUM_STAGES,
                "deficit_pole_pairs": pp - NUM_STAGES,
                "status": "OBSERVED (arithmetic)",
                "claim": "A six-section cascade has at most 6 pole pairs. This target has more. \
                          At least the difference CANNOT be represented — this is a counting proof, \
                          independent of any optimizer. The fitted residual below is an UPPER BOUND \
                          on achievable error, never a proof of what six stages cannot do.",
            });
        }
    }

    // The harness states its own failure modes in its own output. A number
    // without its caveat is a claim; a number with it is evidence.
    report["limitations"] = serde_json::json!([
        "IDENTIFIABILITY BOUNDARY (H17): lane correspondence is NOT identifiable from corner-only \
         transfer functions. MEASURED 0.0 dB corner discriminability vs 25.82 dB interior. This is \
         structural, not a difficulty — the information is absent. Do not attempt to recover \
         canonical stage correspondence from endpoint evidence; the harness reports AMBIGUOUS \
         instead, and that is the correct answer, not a shortfall.",
        "Correspondence conclusions are governed ONLY by the declared evidence mode (H18). An \
         AUTHORED_TRAJECTORY identity is a PRIOR, never a recovery — it must not be reported as \
         evidence that the transfer functions identified the registration.",
        "SOLVER, not measurement: the blind optimizer (H10) does NOT recover the exactly-\
         representable fixture even though a zero-error solution provably exists (the oracle probe \
         reaches objective 0.0). Any blind residual here is the OPTIMIZER's shortfall plus the \
         target's true irreducibility, and this harness CANNOT separate the two for an arbitrary \
         target. It can only separate them when an oracle exists — i.e. never, for a real target.",
        "A fit residual is an UPPER BOUND on achievable error. It is NEVER a proof that six stages \
         cannot represent something. The ONLY proof of irreducibility here is the arithmetic order \
         count (order_deficit), which needs no optimizer.",
        "dB error is unbounded near a deep notch, so rms_db and max_db are dominated by a handful \
         of bins where target and candidate nulls sit a few Hz apart. Read median/p90 for the \
         typical surface. No single scalar summarises this surface.",
        "Certification is SAMPLED on a finite Morph×Q grid. It is NEVER a continuum proof of \
         stability or finiteness. A hazard between grid points is not excluded.",
        "Legality (stable + finite + packable + parity) says NOTHING about whether the result \
         sounds like the target. It is a floor, not a verdict.",
        "Feature survival (H9) is a curve-description heuristic. It assigns NO lane identity and \
         must not be read as a correspondence result.",
        "The objective's weighting (H5/H6) and grids (H1/H2) are arbitrary declared choices, not \
         validated against any perceptual criterion. Changing them changes every number here.",
        "The harness has no opinion about whether any target is worth hitting. Stable and finite \
         means legal, never good. Only the ear decides the rest.",
    ]);

    std::fs::write(
        root.join("report.json"),
        serde_json::to_string_pretty(&report).unwrap(),
    )
    .unwrap();

    println!(
        "  fit: blind {:.4e} -> {:.4e}{}",
        blind.obj_init,
        blind.obj_final,
        oracle
            .as_ref()
            .map(|o| format!(" | oracle {:.4e} -> {:.4e}", o.obj_init, o.obj_final))
            .unwrap_or_default()
    );
    println!("  reported candidate from: {}", chosen.init);
    println!(
        "  held-out error: median {:.3} | p90 {:.3} | rms {:.3} | max {:.3} dB @ {} {:.0} Hz",
        res_verify.median_db,
        res_verify.p90_db,
        res_verify.rms_db,
        res_verify.max_db,
        res_verify.worst_label,
        res_verify.worst_hz
    );
    println!(
        "  identity-body reference: median {:.3} | rms {:.3} dB",
        res_ident.median_db, res_ident.rms_db
    );
    println!(
        "  features: {} matched / {} lost / {} spurious",
        surv["matched"], surv["lost"], surv["spurious"]
    );
    println!(
        "  legal: {} (unstable {} nonfinite {} wrap {})",
        legal["legal"],
        legal["sampled_certification"]["unstable_rows"],
        legal["sampled_certification"]["nonfinite_rows"],
        legal["packed_interp_wrap_hazard"]
    );
    println!("  artifacts: {}", root.display());
    report
}

// ── main ────────────────────────────────────────────────────────────────────

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let which = args.get(1).map(|s| s.as_str()).unwrap_or("all");
    let iters = args
        .iter()
        .position(|a| a == "--iters")
        .and_then(|i| args.get(i + 1))
        .and_then(|v| v.parse::<usize>().ok())
        .unwrap_or(DEFAULT_ITERS);

    if which == "floor" {
        cmd_floor();
        return;
    }

    if which == "mouth" {
        cmd_mouth();
        return;
    }

    if which == "qualify" {
        let seeds = args
            .iter()
            .position(|a| a == "--seeds")
            .and_then(|i| args.get(i + 1))
            .and_then(|v| v.parse::<u64>().ok())
            .unwrap_or(4);
        let fixture = args
            .iter()
            .position(|a| a == "--fixture")
            .and_then(|i| args.get(i + 1))
            .map(String::as_str);
        let qual_iters = args
            .iter()
            .position(|a| a == "--iters")
            .and_then(|i| args.get(i + 1))
            .and_then(|v| v.parse::<usize>().ok())
            .unwrap_or(140);
        // ONE unmistakable opt-in. The old `--approach <name>` selector is gone:
        // it was a second, quieter route to the REJECTED evolutionary solver, and
        // the contract is that evolutionary must never execute by accident.
        let include_evo = args.iter().any(|a| a == "--include-evolutionary-benchmark");
        if let Some(i) = args.iter().position(|a| a == "--approach") {
            eprintln!(
                "error: `--approach` was removed. Routine `qualify` runs the structured solver \
                 only.\n       The evolutionary solver is REJECTED for routine use (0/12 vs 12/12) \
                 and is reachable\n       ONLY via: tf_harness qualify --include-evolutionary-benchmark"
            );
            let _ = args.get(i + 1);
            std::process::exit(2);
        }
        cmd_qualify(seeds, fixture, include_evo, qual_iters);
        return;
    }

    let exact = ExactSix::new();
    let over = OverBudget::new();
    let cross = Crossing::new();
    let all: Vec<&dyn Target> = vec![&exact, &over, &cross];

    let selected: Vec<&dyn Target> = match which {
        "all" => all,
        n => all.into_iter().filter(|t| t.name() == n).collect(),
    };
    if selected.is_empty() {
        eprintln!("usage: tf-harness <all|exact6|overbudget|crossing> [--iters N]");
        std::process::exit(2);
    }

    let mut reports = Vec::new();
    for t in selected {
        reports.push(run_fixture(t, iters));
    }

    let root = repo_root().join("dev").join("tmp").join("tf_harness");
    std::fs::create_dir_all(&root).unwrap();
    std::fs::write(
        root.join("all_reports.json"),
        serde_json::to_string_pretty(&serde_json::json!({
            "schema": "tf-harness-v1",
            "sample_rate_hz": SR,
            "hypotheses": hypotheses(),
            "reports": reports,
        }))
        .unwrap(),
    )
    .unwrap();
    println!("\nwrote {}", root.join("all_reports.json").display());
}

// ════════════════════════════════════════════════════════════════════════════
// SOLVER QUALIFICATION
// ════════════════════════════════════════════════════════════════════════════
//
// The blind Hooke-Jeeves search is NOT an authoring instrument: it fails the
// exactly-representable exact6 fixture (MEASURED). Two oracle-free,
// source-agnostic solvers are built and BENCHMARKED against each other.
//
// Both may see ONLY sampled complex H_target(f, m, q). Neither may see the
// target's corner rows, packed words, lane identities, or any oracle init.
// Every candidate is scored through the REAL trench-core packed loop.

// ── complex helpers the solvers need ────────────────────────────────────────

#[inline]
fn cadd(a: Cf, b: Cf) -> Cf {
    (a.0 + b.0, a.1 + b.1)
}
#[inline]
fn csub(a: Cf, b: Cf) -> Cf {
    (a.0 - b.0, a.1 - b.1)
}
#[inline]
fn cdiv(a: Cf, b: Cf) -> Cf {
    let d = b.0 * b.0 + b.1 * b.1;
    if d < 1e-300 {
        return (0.0, 0.0);
    }
    ((a.0 * b.0 + a.1 * b.1) / d, (a.1 * b.0 - a.0 * b.1) / d)
}

/// Evaluate Σ c[i]·x^i at complex x.
fn poly_eval_c(c: &[f64], x: Cf) -> Cf {
    let mut acc = (0.0, 0.0);
    for &ci in c.iter().rev() {
        acc = cadd(cmul(acc, x), (ci, 0.0));
    }
    acc
}

/// Roots of Σ c[i]·x^i by Durand-Kerner. Leading near-zero coefficients are
/// trimmed first: a degree-deficient polynomial genuinely has fewer finite
/// roots (the missing ones sit at infinity in x, i.e. at the origin in z).
fn poly_roots(c: &[f64]) -> Vec<Cf> {
    let scale = c.iter().fold(0.0f64, |m, &v| m.max(v.abs()));
    if scale <= 0.0 {
        return vec![];
    }
    let mut n = c.len();
    while n > 1 && c[n - 1].abs() < 1e-9 * scale {
        n -= 1;
    }
    let deg = n - 1;
    if deg == 0 {
        return vec![];
    }
    let lead = c[deg];
    let mono: Vec<f64> = c[..n].iter().map(|&v| v / lead).collect();
    // spread the initial guesses around a circle (standard Durand-Kerner seed)
    let mut roots: Vec<Cf> = (0..deg)
        .map(|k| {
            let ang = TAU * (k as f64 + 0.25) / deg as f64;
            (0.9 * ang.cos(), 0.9 * ang.sin())
        })
        .collect();
    for _ in 0..800 {
        let mut maxd = 0.0f64;
        for i in 0..deg {
            let p = poly_eval_c(&mono, roots[i]);
            let mut den = (1.0f64, 0.0f64);
            for j in 0..deg {
                if j != i {
                    den = cmul(den, csub(roots[i], roots[j]));
                }
            }
            let d = cdiv(p, den);
            roots[i] = csub(roots[i], d);
            maxd = maxd.max(cabs(d));
        }
        if maxd < 1e-15 {
            break;
        }
    }
    roots
}

/// Householder QR least squares: min ||A·x − b||₂ for an overdetermined system.
///
/// Normal equations (AᵀA x = Aᵀb) SQUARE the condition number. Here |H| spans
/// ~100 dB across the band, so the a-columns (scaled by H) and b-columns differ
/// by many orders of magnitude and cond(A) is already large; squaring it destroys
/// the solution. MEASURED: the normal-equation version recovered corners only to
/// ~1.7 dB where the data supports machine precision. QR never forms AᵀA.
/// Generic linear algebra, not filter math.
fn lstsq_qr(mut a: Vec<Vec<f64>>, mut b: Vec<f64>) -> Option<Vec<f64>> {
    let m = a.len();
    if m == 0 {
        return None;
    }
    let n = a[0].len();
    if m < n {
        return None;
    }
    for k in 0..n {
        let mut norm = 0.0f64;
        for row in a.iter().take(m).skip(k) {
            norm += row[k] * row[k];
        }
        norm = norm.sqrt();
        if norm < 1e-300 {
            continue;
        }
        let alpha = if a[k][k] > 0.0 { -norm } else { norm };
        let mut v = vec![0.0f64; m];
        for i in k..m {
            v[i] = a[i][k];
        }
        v[k] -= alpha;
        let vn2: f64 = (k..m).map(|i| v[i] * v[i]).sum();
        if vn2 < 1e-300 {
            continue;
        }
        for j in k..n {
            let dot: f64 = (k..m).map(|i| v[i] * a[i][j]).sum();
            let f = 2.0 * dot / vn2;
            for i in k..m {
                a[i][j] -= f * v[i];
            }
        }
        let dot: f64 = (k..m).map(|i| v[i] * b[i]).sum();
        let f = 2.0 * dot / vn2;
        for i in k..m {
            b[i] -= f * v[i];
        }
    }
    let mut x = vec![0.0f64; n];
    for i in (0..n).rev() {
        let mut s = b[i];
        for j in i + 1..n {
            s -= a[i][j] * x[j];
        }
        x[i] = if a[i][i].abs() < 1e-13 {
            0.0
        } else {
            s / a[i][i]
        };
    }
    Some(x)
}

/// A(x) = 1 + a1 x + ... ; B(x) = b0 + b1 x + ... , with x = z^-1.
struct Rational {
    a: Vec<f64>, // a[0] == 1
    b: Vec<f64>,
}

/// H20 Levy's linear rational fit. For each sample:
///     H_k·A(x_k) − B(x_k) = 0   =>   Σ_j b_j x_k^j − H_k·Σ_{i≥1} a_i x_k^i = H_k
/// linear in (b, a). For NOISELESS, exactly-representable data the true
/// coefficients make every residual EXACTLY zero, so plain least squares
/// recovers them without any Sanathanan-Koerner reweighting — Levy's usual |A|
/// bias cannot matter at a zero residual.
///
/// Columns are scaled to unit norm before the solve (Jacobi preconditioning) and
/// unscaled after: |H| spans orders of magnitude, so the a-columns and b-columns
/// otherwise differ enormously in scale. This conditions the SOLVE only — it does
/// not touch the data, and is not a normalization of the target.
/// H24 Sanathanan-Koerner iterations: Levy's equation implicitly weights each
/// residual by |A(x_k)|, which biases the fit toward high-gain regions. SK
/// divides row k by |A_prev(x_k)| so the weighting converges to the true
/// equation-error. Cheap, standard, and it costs nothing on data that is already
/// exactly representable.
const SK_ITERS: usize = 6;

fn fit_rational(freqs: &[f64], h: &[Cf], na: usize, nb: usize) -> Option<Rational> {
    let nun = (nb + 1) + na; // b0..b_nb , a1..a_na
    let np = na.max(nb) + 1;
    // precompute x^j per frequency
    let xp: Vec<Vec<Cf>> = freqs
        .iter()
        .map(|&f| {
            let w = TAU * f / SR;
            let x = ((-w).cos(), (-w).sin()); // x = z^-1 = e^{-jw}
            let mut v = vec![(1.0f64, 0.0f64); np];
            for i in 1..np {
                v[i] = cmul(v[i - 1], x);
            }
            v
        })
        .collect();

    let mut a_prev: Option<Vec<f64>> = None;
    let mut out: Option<Rational> = None;
    for _sk in 0..SK_ITERS {
        let mut rows: Vec<Vec<f64>> = Vec::with_capacity(h.len() * 2);
        let mut rhs: Vec<f64> = Vec::with_capacity(h.len() * 2);
        for k in 0..freqs.len() {
            // SK weight: 1/|A_prev(x_k)| (1.0 on the first pass = plain Levy)
            let wk = match &a_prev {
                None => 1.0,
                Some(a) => {
                    let w = TAU * freqs[k] / SR;
                    let x = ((-w).cos(), (-w).sin());
                    let av = poly_eval_c(a, x);
                    let m = cabs(av);
                    if m > 1e-12 {
                        1.0 / m
                    } else {
                        1.0
                    }
                }
            };
            let mut rr = vec![0.0; nun];
            let mut ri = vec![0.0; nun];
            for j in 0..=nb {
                rr[j] = xp[k][j].0 * wk;
                ri[j] = xp[k][j].1 * wk;
            }
            for i in 1..=na {
                let t = cmul(h[k], xp[k][i]);
                rr[nb + i] = -t.0 * wk;
                ri[nb + i] = -t.1 * wk;
            }
            rows.push(rr);
            rhs.push(h[k].0 * wk);
            rows.push(ri);
            rhs.push(h[k].1 * wk);
        }
        // column scaling (Jacobi preconditioning of the SOLVE only; the data is
        // untouched and both sides see the same transform — not a normalization)
        let mut cs = vec![0.0f64; nun];
        for r in &rows {
            for j in 0..nun {
                cs[j] += r[j] * r[j];
            }
        }
        for c in cs.iter_mut() {
            *c = c.sqrt().max(1e-300);
        }
        for r in rows.iter_mut() {
            for j in 0..nun {
                r[j] /= cs[j];
            }
        }
        let sol = lstsq_qr(rows, rhs)?;
        let theta: Vec<f64> = (0..nun).map(|j| sol[j] / cs[j]).collect();
        if !theta.iter().all(|v| v.is_finite()) {
            return None;
        }
        let b = theta[..=nb].to_vec();
        let mut a = vec![1.0];
        a.extend_from_slice(&theta[nb + 1..]);
        a_prev = Some(a.clone());
        out = Some(Rational { a, b });
    }
    out
}

/// Poles/zeros (in z) and total gain recovered from one corner's spectrum.
struct CornerModel {
    poles: Vec<(f64, f64)>, // (p, q) of z^2 + p z + q
    zeros: Vec<(f64, f64)>,
    gain: f64, // K = product of the six SCALEs
}

/// Group roots (in z) into six real quadratics z^2 + p z + q.
///
/// Conjugate roots MUST pair with their conjugate (that is forced by realness).
/// Real roots have a genuine pairing freedom — H21: they are paired by sorted
/// adjacency. That is an INITIALIZATION hypothesis, never a verdict: the
/// correspondence search and packed refinement are free to move away from it.
fn group_into_quads(roots: &[Cf], want: usize) -> Vec<(f64, f64)> {
    let mut reals: Vec<f64> = Vec::new();
    let mut cplx: Vec<Cf> = Vec::new();
    for &r in roots {
        if r.1.abs() < 1e-7 * (1.0 + r.0.abs()) {
            reals.push(r.0);
        } else {
            cplx.push(r);
        }
    }
    let mut quads: Vec<(f64, f64)> = Vec::new();
    let mut used = vec![false; cplx.len()];
    for i in 0..cplx.len() {
        if used[i] {
            continue;
        }
        // find the conjugate partner
        let mut best = usize::MAX;
        let mut bd = f64::INFINITY;
        for j in i + 1..cplx.len() {
            if used[j] {
                continue;
            }
            let d = (cplx[j].0 - cplx[i].0).abs() + (cplx[j].1 + cplx[i].1).abs();
            if d < bd {
                bd = d;
                best = j;
            }
        }
        used[i] = true;
        if best != usize::MAX {
            used[best] = true;
        }
        let u = cplx[i];
        // z^2 - 2Re(u) z + |u|^2
        quads.push((-2.0 * u.0, u.0 * u.0 + u.1 * u.1));
    }
    reals.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let mut i = 0;
    while i + 1 < reals.len() {
        let (r1, r2) = (reals[i], reals[i + 1]);
        quads.push((-(r1 + r2), r1 * r2)); // H21 sorted-adjacent pairing
        i += 2;
    }
    if i < reals.len() {
        let r1 = reals[i];
        quads.push((-r1, 0.0)); // odd real root pairs with a root at the origin
    }
    while quads.len() < want {
        quads.push((0.0, 0.0)); // degenerate = the identity side
    }
    quads.truncate(want);
    quads
}

/// Relative complex-response RMS of a recovered rational model.
///
/// This is used only for numerical model-order selection. It preserves absolute
/// complex response: there is no gain, phase, or delay normalization.
fn rational_relative_rms(r: &Rational, freqs: &[f64], h: &[Cf]) -> f64 {
    let mut err = 0.0;
    let mut reference = 0.0;
    for (k, &f) in freqs.iter().enumerate() {
        let w = TAU * f / SR;
        let x = ((-w).cos(), (-w).sin());
        let got = cdiv(poly_eval_c(&r.b, x), poly_eval_c(&r.a, x));
        let d = csub(got, h[k]);
        err += d.0 * d.0 + d.1 * d.1;
        reference += h[k].0 * h[k].0 + h[k].1 * h[k].1;
    }
    (err / reference.max(1e-300)).sqrt()
}

/// H27 MODEL-ORDER SELECTION — replaces the rejected radius-pruning rule.
///
/// OBSERVED failure of the old rule: a fixed `radius < 0.15 => identity` prune
/// repaired exact6 corner 0 but damaged corner 3 to 0.279 dB median / 0.860 dB
/// p90. It guessed which factors were surplus and therefore was not a valid
/// source-agnostic recovery rule.
///
/// The packed representation contains six real quadratics, so candidate orders
/// 0,2,...,12 cover complete biquad factors. We test them in ascending TOTAL
/// order using only sampled complex H. The first model below the fixed numerical
/// tolerance is the minimal measured realization. Frequency sorting, target
/// rows, target words, and target identities are not consulted. If no reduced
/// model qualifies, the best measured candidate (including 12/12) is retained;
/// that fallback is a solver result, never a representation-limit claim.
const ORDER_REL_RMS: f64 = 1.0e-8;

fn select_rational_order(freqs: &[f64], h: &[Cf]) -> Option<Rational> {
    let orders = [0usize, 2, 4, 6, 8, 10, 12];
    let mut best: Option<(f64, Rational)> = None;
    for total in (0usize..=24).step_by(2) {
        for &na in &orders {
            let Some(nb) = total.checked_sub(na) else {
                continue;
            };
            if !orders.contains(&nb) {
                continue;
            }
            let Some(r) = fit_rational(freqs, h, na, nb) else {
                continue;
            };
            let e = rational_relative_rms(&r, freqs, h);
            if best.as_ref().map_or(true, |(be, _)| e < *be) {
                best = Some((
                    e,
                    Rational {
                        a: r.a.clone(),
                        b: r.b.clone(),
                    },
                ));
            }
            if e <= ORDER_REL_RMS {
                return Some(r);
            }
        }
    }
    best.map(|(_, r)| r)
}

/// Cancel near-coincident pole/zero pairs.
///
/// A degree-12/12 fit of a lower-order target is rank-deficient: A and B share a
/// spurious common factor (any C(x) gives A·C / B·C). Cancelling recovers the
/// true reduced order. Without this the recovered "poles" include artefacts that
/// exactly cancel and waste lanes.
fn cancel_common(poles: &mut Vec<Cf>, zeros: &mut Vec<Cf>, tol: f64) {
    let mut i = 0;
    while i < poles.len() {
        let mut hit = None;
        for (j, z) in zeros.iter().enumerate() {
            if cabs(csub(poles[i], *z)) < tol {
                hit = Some(j);
                break;
            }
        }
        match hit {
            Some(j) => {
                poles.remove(i);
                zeros.remove(j);
            }
            None => i += 1,
        }
    }
}

/// SOLVER A, step 1 — structured recovery from ONE corner's sampled spectrum.
/// Sees only (freqs, H). No rows, no words, no identities.
fn recover_corner(freqs: &[f64], h: &[Cf]) -> Option<CornerModel> {
    let r = select_rational_order(freqs, h)?;
    let mut pz = poly_roots(&r.a); // roots in x = z^-1
    let mut zz = poly_roots(&r.b);
    // x -> z
    let inv = |v: &Vec<Cf>| -> Vec<Cf> { v.iter().map(|&x| cdiv((1.0, 0.0), x)).collect() };
    let mut poles = inv(&pz);
    let mut zeros = inv(&zz);
    poles.retain(|p| p.0.is_finite() && p.1.is_finite() && cabs(*p) < 1.0e3);
    zeros.retain(|z| z.0.is_finite() && z.1.is_finite() && cabs(*z) < 1.0e3);
    cancel_common(&mut poles, &mut zeros, 2.0e-3);
    pz.clear();
    zz.clear();
    if poles.len() > 2 * NUM_STAGES || zeros.len() > 2 * NUM_STAGES {
        return None;
    }
    // K = B(0)/A(0) = b0 (A(0) = 1). This is the true total SCALE product only
    // after cancellation leaves the numerator monic-free; recompute robustly by
    // matching the model to the data at the sampled points instead.
    let pq = group_into_quads(&poles, NUM_STAGES);
    let zq = group_into_quads(&zeros, NUM_STAGES);
    // gain by least squares in the log domain against the recovered shape,
    // using the SAME owned response engine (no second law).
    let shape_rows: Vec<[f64; NUM_COEFFS]> = (0..NUM_STAGES)
        .map(|i| {
            let (zp, zqq) = zq[i];
            let (pp, pqq) = pq[i];
            [1.0, zp, zqq, pp, pqq]
        })
        .collect();
    let mut acc = 0.0;
    let mut n = 0usize;
    for (k, &f) in freqs.iter().enumerate() {
        let s = rows_complex(&shape_rows, f);
        let sa = cabs(s);
        let ha = cabs(h[k]);
        if sa > 1e-12 && ha > 1e-12 {
            acc += (ha / sa).ln();
            n += 1;
        }
    }
    let gain = if n > 0 { (acc / n as f64).exp() } else { 1.0 };
    Some(CornerModel {
        poles: pq,
        zeros: zq,
        gain,
    })
}

/// Build the 120-param vector from four corner models + per-corner lane
/// permutations + per-corner scale splits.
fn assemble_params(
    cm: &[CornerModel; 4],
    pole_perm: &[[usize; 6]; 4],
    zero_perm: &[[usize; 6]; 4],
    scales: &[[f64; 6]; 4],
) -> Vec<f64> {
    let mut p = vec![0.0f64; NPARAM];
    for ci in 0..4 {
        for si in 0..NUM_STAGES {
            let (zp, zq) = cm[ci].zeros[zero_perm[ci][si]];
            let (pp, pq) = cm[ci].poles[pole_perm[ci][si]];
            let base = (ci * NUM_STAGES + si) * PPS;
            let mut s = [zp, zq, pp, pq, scales[ci][si]];
            clamp_stage(&mut s);
            p[base..base + PPS].copy_from_slice(&s);
        }
    }
    p
}

/// H30 frequency-sorted POLE initialization only — never a verdict.
///
/// Durand-Kerner returns roots in an arbitrary enumeration, so an identity
/// permutation is not a neutral correspondence hypothesis. For conjugate pole
/// pairs, sort by angle (hence frequency); exact identity is placed last. The
/// observed-surface correspondence search remains free to replace every
/// non-gauge permutation and is the only source of a correspondence decision.
fn frequency_sorted_quad_perm(values: &[(f64, f64)]) -> [usize; 6] {
    let key = |&(p, q): &(f64, f64)| {
        if p == 0.0 && q == 0.0 {
            return f64::INFINITY;
        }
        let r = q.max(0.0).sqrt();
        if r > 0.0 && p * p < 4.0 * q {
            (-p / (2.0 * r)).clamp(-1.0, 1.0).acos()
        } else {
            // Independent real-root pole pairs have no unique resonant angle.
            // Keep them after conjugate actors but before identity; the interior
            // search, not this key, must decide their correspondence.
            std::f64::consts::PI + p.abs() * 1.0e-3 + q.abs() * 1.0e-6
        }
    };
    let mut idx = [0usize, 1, 2, 3, 4, 5];
    idx.sort_by(|&a, &b| {
        key(&values[a])
            .partial_cmp(&key(&values[b]))
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    idx
}

/// H29 explicit total-gain allocation hypothesis.
///
/// A corner transfer function identifies only the PRODUCT of the six SCALEs.
/// Splitting K as K^(1/6) compounds six independent quantization errors and was
/// MEASURED to produce 0.606 dB corner error on exact6 before correspondence.
/// Allocate K to the fewest lanes representable in [0,4], leaving the rest at
/// exact unity. The seed rotates the carrier lane, so multiple deterministic
/// seeds expose the otherwise endpoint-ambiguous scale trajectory to the
/// interior scorer. This is initialization, never recovered per-lane SCALE.
fn initial_scales(cm: &[CornerModel; 4], seed: u64) -> [[f64; 6]; 4] {
    let mut out = [[1.0f64; 6]; 4];
    let carrier = seed as usize % NUM_STAGES;
    for ci in 0..4 {
        let mut remaining = cm[ci].gain.max(1e-12);
        for offset in 0..NUM_STAGES {
            let si = (carrier + offset) % NUM_STAGES;
            if remaining <= 4.0 {
                out[ci][si] = remaining;
                break;
            }
            out[ci][si] = 4.0;
            remaining /= 4.0;
        }
    }
    out
}

/// SOLVER A, step 2 — CORRESPONDENCE SEARCH against the interior surface.
///
/// Corner 0's POLE order is the gauge (relabelling every complete lane at every
/// corner identically leaves the interior untouched). Its pole-to-zero pairing
/// is still unknown and is searched. Starting from H30's frequency pole order,
/// alternate exhaustive zero pairing at all corners with exhaustive pole
/// correspondence at non-gauge corners. Every move is ranked by packed-runtime
/// interior response. This can leave the sorting initialization without the
/// 720x720 joint enumeration that was measured to exceed two minutes.
///
/// This is not frequency sorting. Sorting is only ever the starting hypothesis
/// (H21/H22); the verdict is measured interior error.
fn correspondence_search(
    cm: &[CornerModel; 4],
    surf: &Surface,
    scales: &[[f64; 6]; 4],
    pole_perm: &mut [[usize; 6]; 4],
    zero_perm: &mut [[usize; 6]; 4],
) -> f64 {
    fn unique_quad_perms(values: &[(f64, f64)]) -> Vec<[usize; 6]> {
        let mut out: Vec<[usize; 6]> = Vec::new();
        'candidate: for p in perms6() {
            for kept in &out {
                if (0..NUM_STAGES).all(|i| {
                    values[p[i]].0.to_bits() == values[kept[i]].0.to_bits()
                        && values[p[i]].1.to_bits() == values[kept[i]].1.to_bits()
                }) {
                    continue 'candidate;
                }
            }
            out.push(p);
        }
        out
    }

    let search = search_subset(surf);
    let score = |pc: &PackedCorners| {
        qualification_response_objective(pc, &search) + PEN_WRAP * wrap_penalty(pc)
    };
    let mut best = score(&params_to_packed(&assemble_params(
        cm, pole_perm, zero_perm, scales,
    )));
    for _round in 0..2 {
        for ci in 0..4 {
            let zperms = unique_quad_perms(&cm[ci].zeros);
            let mut bz = zero_perm[ci];
            for z in &zperms {
                zero_perm[ci] = *z;
                let e = score(&params_to_packed(&assemble_params(
                    cm, pole_perm, zero_perm, scales,
                )));
                if e < best {
                    best = e;
                    bz = *z;
                }
            }
            zero_perm[ci] = bz;
        }

        for ci in 1..4 {
            let pperms = unique_quad_perms(&cm[ci].poles);
            let mut bp = pole_perm[ci];
            for p in &pperms {
                pole_perm[ci] = *p;
                let e = score(&params_to_packed(&assemble_params(
                    cm, pole_perm, zero_perm, scales,
                )));
                if e < best {
                    best = e;
                    bp = *p;
                }
            }
            pole_perm[ci] = bp;
        }
    }
    best
}

/// H25 PACKED-WORD REFINEMENT — discrete coordinate descent on the actual u16
/// words, the quantity the runtime actually consumes.
///
/// WHY this and not more param-domain search: recovery is response-exact in the
/// CONTINUOUS domain (MEASURED: median < 1e-3 dB per corner), but re-encoding
/// those roots lands on words one or more LSB away from the target's, and near a
/// sharp resonance a 1-LSB coefficient step is a real frequency/Q shift. No
/// amount of continuous-parameter search fixes a quantization landing error,
/// because the map param -> word is a step function. Searching the words
/// directly is the only refinement that can.
///
/// Scored through the REAL packed loop. Deterministic. No target words are read.
fn refine_words(
    mut pc: PackedCorners,
    objective: &dyn Fn(&PackedCorners) -> f64,
    sweeps: usize,
) -> PackedCorners {
    let mut best = objective(&pc);
    for _ in 0..sweeps {
        let mut improved = false;
        for ci in 0..4 {
            for si in 0..NUM_STAGES {
                for wi in 0..NUM_COEFFS {
                    let orig = pc.words[ci][si][wi];
                    let mut bw = orig;
                    for d in [-64i32, -16, -4, -1, 1, 4, 16, 64] {
                        let cand = (orig as i32 + d).clamp(0, 0xFFFF) as u16;
                        if cand == orig {
                            continue;
                        }
                        pc.words[ci][si][wi] = cand;
                        let e = objective(&pc);
                        if e < best {
                            best = e;
                            bw = cand;
                            improved = true;
                        }
                    }
                    pc.words[ci][si][wi] = bw;
                }
            }
        }
        if !improved {
            break;
        }
    }
    pc
}

/// SOLVER A — structured rational/root recovery -> correspondence search against
/// the interior surface -> packed-word refinement. Oracle-free: it touches only
/// `surf` (sampled complex H_target).
fn solver_structured(surf: &Surface, seed: u64, iters: usize) -> PackedCorners {
    let started = std::time::Instant::now();
    // step 1: recover each corner's roots + gain from its spectrum alone
    let mut models: Vec<CornerModel> = Vec::new();
    for &(m, q) in &CORNER_MQ {
        let st = surf
            .states
            .iter()
            .find(|s| (s.m - m).abs() < 1e-9 && (s.q - q).abs() < 1e-9);
        match st.and_then(|s| recover_corner(&surf.freqs, &s.h)) {
            Some(cm) => models.push(cm),
            None => return params_to_packed(&init_spread()), // recovery failed; reported
        }
    }
    let cm: [CornerModel; 4] = match models.try_into() {
        Ok(v) => v,
        Err(_) => return params_to_packed(&init_spread()),
    };
    eprintln!(
        "    structured: recovery {:.2}s",
        started.elapsed().as_secs_f64()
    );
    let scales = initial_scales(&cm, seed);

    // step 2: correspondence from interior behaviour (H22: identity permutation
    // is the starting hypothesis; the search may leave it)
    let mut pp: [[usize; 6]; 4] =
        std::array::from_fn(|ci| frequency_sorted_quad_perm(&cm[ci].poles));
    let mut zp = [[0usize, 1, 2, 3, 4, 5]; 4];
    correspondence_search(&cm, surf, &scales, &mut pp, &mut zp);
    eprintln!(
        "    structured: correspondence {:.2}s",
        started.elapsed().as_secs_f64()
    );

    // step 3: continuous polish, then packed-word refinement (H25) — the words
    // are what the runtime consumes, and quantization landing errors are only
    // reachable there.
    let base = assemble_params(&cm, &pp, &zp, &scales);
    if iters == 0 {
        eprintln!(
            "    structured: initial candidate {:.2}s (refinement disabled)",
            started.elapsed().as_secs_f64()
        );
        return params_to_packed(&base);
    }
    let obj = |p: &[f64]| qualification_objective(&params_to_packed(p), surf);
    let (refined, _) = hooke_jeeves(base, &obj, iters);
    eprintln!(
        "    structured: continuous refine {:.2}s",
        started.elapsed().as_secs_f64()
    );
    let packed_obj = |pc: &PackedCorners| qualification_objective(pc, surf);
    let out = refine_words(params_to_packed(&refined), &packed_obj, 2);
    eprintln!(
        "    structured: word refine {:.2}s",
        started.elapsed().as_secs_f64()
    );
    out
}

/// SOLVER B — deterministic differential evolution over the 120 packed-domain
/// params, then packed-runtime coordinate refinement. Population/global search:
/// no structure assumed, no roots recovered. Oracle-free.
fn solver_evolutionary(surf: &Surface, seed: u64, iters: usize) -> PackedCorners {
    const POP: usize = 48;
    const GENS: usize = 260;
    const F: f64 = 0.6;
    const CR: f64 = 0.9;
    let mut st = seed
        .wrapping_mul(0xD1B5_4A32_D192_ED03)
        .wrapping_add(0x9E37_79B9);
    let mut rnd = || {
        st ^= st << 13;
        st ^= st >> 7;
        st ^= st << 17;
        (st >> 11) as f64 / (1u64 << 53) as f64
    };
    let search = search_subset(surf);
    let obj = |p: &[f64]| {
        let pc = params_to_packed(p);
        qualification_response_objective(&pc, &search)
            + PEN_STAB * stability_penalty(&pc)
            + PEN_WRAP * wrap_penalty(&pc)
    };

    // H23 seeded population: one member is the target-agnostic spread; the rest
    // are random inside the param box. No target information is used.
    let mut pop: Vec<Vec<f64>> = Vec::with_capacity(POP);
    pop.push(init_spread());
    for _ in 1..POP {
        let mut v = vec![0.0f64; NPARAM];
        for s in 0..(NPARAM / PPS) {
            let b = s * PPS;
            v[b] = 4.0 * rnd() - 2.0;
            v[b + 1] = rnd();
            v[b + 2] = 4.0 * rnd() - 2.0;
            v[b + 3] = POLE_Q_MAX * rnd();
            v[b + 4] = 2.0 * rnd();
            clamp_stage(&mut v[b..b + PPS]);
        }
        pop.push(v);
    }
    let mut fit_v: Vec<f64> = pop.iter().map(|p| obj(p)).collect();

    for _g in 0..GENS {
        for i in 0..POP {
            let (a, b, c) = (
                (rnd() * POP as f64) as usize % POP,
                (rnd() * POP as f64) as usize % POP,
                (rnd() * POP as f64) as usize % POP,
            );
            if a == i || b == i || c == i || a == b || b == c || a == c {
                continue;
            }
            let jrand = (rnd() * NPARAM as f64) as usize % NPARAM;
            let mut trial = pop[i].clone();
            for j in 0..NPARAM {
                if rnd() < CR || j == jrand {
                    trial[j] = pop[a][j] + F * (pop[b][j] - pop[c][j]);
                }
            }
            for s in 0..(NPARAM / PPS) {
                clamp_stage(&mut trial[s * PPS..s * PPS + PPS]);
            }
            let ft = obj(&trial);
            if ft < fit_v[i] {
                pop[i] = trial;
                fit_v[i] = ft;
            }
        }
    }
    let best = (0..POP)
        .min_by(|&x, &y| fit_v[x].partial_cmp(&fit_v[y]).unwrap())
        .unwrap();
    let full_obj = |p: &[f64]| qualification_objective(&params_to_packed(p), surf);
    let (refined, _) = hooke_jeeves(pop[best].clone(), &full_obj, iters);
    // same final packed-word refinement (H25), so the two approaches are
    // compared on equal footing and the benchmark isolates the SEARCH.
    let packed_obj = |pc: &PackedCorners| qualification_objective(pc, surf);
    refine_words(params_to_packed(&refined), &packed_obj, 2)
}

// ── qualification fixtures: exactly representable, varied arrangements ───────

/// Build an exactly-representable target from a declared lane recipe. The
/// SOLVER never sees this construction — only the sampled spectrum.
struct PackedSurfaceTarget {
    name: &'static str,
    describe: &'static str,
    body: PackedCorners,
}

impl SectionTarget for PackedSurfaceTarget {
    fn name(&self) -> &str {
        self.name
    }
    fn describe(&self) -> String {
        self.describe.into()
    }
    fn rows_at(&self, m: f64, q: f64) -> Vec<[f64; NUM_COEFFS]> {
        self.body.interpolate_biquad(m as f32, q as f32).to_vec()
    }
    fn pole_pairs(&self) -> usize {
        NUM_STAGES
    }
    fn evidence_mode(&self) -> EvidenceMode {
        EvidenceMode::ObservedSurface
    }
}

/// QUAL-2: notch-dominated — near-unit-circle zeros travelling on morph, mild
/// poles. Stresses zero recovery and the unbounded-dB-near-a-null regime.
fn qual_notchy() -> PackedSurfaceTarget {
    let mut words = [[[0u16; NUM_COEFFS]; NUM_STAGES]; 4];
    for (ci, &(m, q)) in CORNER_MQ.iter().enumerate() {
        let g = |a: f64, b: f64| a + (b - a) * m;
        let r = |a: f64, b: f64| a + (b - a) * q;
        let lane = |ph: f64, pr: f64, zh: f64, zr: f64, s: f64| {
            words_from_geometry(&StageGeometry {
                pole: RootPair::Conjugate { hz: ph, r: pr },
                zero: RootPair::Conjugate { hz: zh, r: zr },
                scale: s,
            })
        };
        words[ci][0] = lane(g(400.0, 700.0), r(0.70, 0.86), g(500.0, 900.0), 0.985, 1.0);
        words[ci][1] = lane(
            g(1100.0, 1700.0),
            r(0.72, 0.88),
            g(1300.0, 2100.0),
            0.992,
            1.0,
        );
        words[ci][2] = lane(
            g(2600.0, 3400.0),
            r(0.74, 0.90),
            g(3000.0, 4200.0),
            0.996,
            1.0,
        );
        words[ci][3] = lane(
            g(5200.0, 6400.0),
            r(0.70, 0.86),
            g(6000.0, 7600.0),
            0.990,
            1.0,
        );
        words[ci][4] = lane(
            g(9000.0, 10500.0),
            r(0.68, 0.84),
            g(10000.0, 12000.0),
            0.980,
            1.0,
        );
        words[ci][5] = words_from_geometry(&StageGeometry {
            pole: RootPair::Degenerate,
            zero: RootPair::Degenerate,
            scale: 1.0,
        });
    }
    PackedSurfaceTarget {
        name: "qual_notchy",
        describe: "Exactly representable. Notch-dominated: five near-unit-circle zeros \
                   (r 0.98..0.996) travelling on morph over mild poles; one identity lane.",
        body: PackedCorners { words },
    }
}

/// QUAL-3: real-root + wide-spread — explicit REAL root pairs (which the
/// conjugate reader must refuse), a DC-adjacent lane, and an identity lane that
/// stays identity. Stresses the real/conjugate classification path.
fn qual_realroot() -> PackedSurfaceTarget {
    let mut words = [[[0u16; NUM_COEFFS]; NUM_STAGES]; 4];
    for (ci, &(m, q)) in CORNER_MQ.iter().enumerate() {
        let g = |a: f64, b: f64| a + (b - a) * m;
        let r = |a: f64, b: f64| a + (b - a) * q;
        words[ci][0] = words_from_geometry(&StageGeometry {
            pole: RootPair::Conjugate {
                hz: g(260.0, 340.0),
                r: r(0.86, 0.95),
            },
            zero: RootPair::RealPair {
                root_a: 0.80,
                root_b: 0.15,
            },
            scale: 0.8,
        });
        words[ci][1] = words_from_geometry(&StageGeometry {
            pole: RootPair::Conjugate {
                hz: g(1500.0, 1150.0),
                r: r(0.88, 0.958),
            },
            zero: RootPair::RealPair {
                root_a: -0.60,
                root_b: 0.30,
            },
            scale: 0.9,
        });
        words[ci][2] = words_from_geometry(&StageGeometry {
            pole: RootPair::Conjugate {
                hz: g(3300.0, 4100.0),
                r: r(0.84, 0.94),
            },
            zero: RootPair::Conjugate {
                hz: g(2500.0, 2000.0),
                r: 0.93,
            },
            scale: 1.1,
        });
        words[ci][3] = words_from_geometry(&StageGeometry {
            pole: RootPair::Conjugate {
                hz: g(7500.0, 6200.0),
                r: r(0.80, 0.90),
            },
            zero: RootPair::Degenerate,
            scale: 0.7,
        });
        words[ci][4] = words_from_geometry(&StageGeometry {
            pole: RootPair::Conjugate {
                hz: g(120.0, 150.0),
                r: r(0.78, 0.88),
            },
            zero: RootPair::Conjugate {
                hz: g(200.0, 260.0),
                r: 0.90,
            },
            scale: 1.0,
        });
        words[ci][5] = words_from_geometry(&StageGeometry {
            pole: RootPair::Degenerate,
            zero: RootPair::Degenerate,
            scale: 1.0,
        });
    }
    PackedSurfaceTarget {
        name: "qual_realroot",
        describe:
            "Exactly representable. Explicit REAL root pairs (refused by the conjugate \
                   reader), a DC-adjacent lane at 120..150 Hz, one falling pole, one identity lane.",
        body: PackedCorners { words },
    }
}

// ── MANDATORY FAILURE FIXTURES for the floor instrument ─────────────────────
//
// Each one is a case where a naive finite-section reading gives a confidently
// WRONG answer. They exist to make the instrument falsifiable: the guards must
// REFUSE on these, not produce a number.

/// FAILURE 1 & 2: a pure delay z^-d, optionally with the delay DECLARED.
///
/// Undeclared with d=320: the L=160 section reads h[1..319] and never touches
/// h[320], so it returns sigma = 0 — while the true Hankel operator of a pure
/// d-sample delay has sigma_1..sigma_d = 1 exactly (its Hankel matrix is an
/// exchange/anti-diagonal block). MEASURED before the guard: the instrument
/// reported "-301 dB, six destroys nothing" for a system 12 poles cannot touch
/// at all. With d = the DFT period, the sampled path aliases it to h[0] and the
/// same catastrophe arrives via aliasing rather than truncation.
struct PureDelay {
    d: usize,
    declare: bool,
}

impl Target for PureDelay {
    fn name(&self) -> &str {
        if self.declare { "pure_delay_declared" } else { "pure_delay_undeclared" }
    }
    fn describe(&self) -> String {
        format!(
            "z^-{} pure delay, transport delay {}. A delay of {} samples cannot be represented by \
             12 poles: its Hankel singular values are 1 (x{}). A finite section that does not reach \
             h[{}] returns 0 — valid as a bound, VACUOUS as evidence.",
            self.d,
            if self.declare { "DECLARED (removed)" } else { "UNDECLARED (not removed)" },
            self.d, self.d, self.d
        )
    }
    fn h(&self, f: f64, _m: f64, _q: f64) -> Cf {
        let w = TAU * f / SR * self.d as f64;
        ((-w).cos(), (-w).sin())
    }
    fn markov(&self, _m: f64, _q: f64, n: usize) -> Option<Vec<f64>> {
        let mut v = vec![0.0f64; n];
        if self.d < n {
            v[self.d] = 1.0;
        }
        Some(v)
    }
    fn transport_delay_samples(&self) -> usize {
        if self.declare { self.d } else { 0 }
    }
    fn evidence_mode(&self) -> EvidenceMode {
        EvidenceMode::ObservedSurface
    }
}

/// FAILURE 3: a slowly decaying, high-radius pole. Its impulse response outlives
/// any short section, so the omitted tail carries real energy and a finite
/// section understates the truth without saying so.
struct SlowPole {
    r: f64,
}

impl SectionTarget for SlowPole {
    fn name(&self) -> &str {
        "slow_pole"
    }
    fn describe(&self) -> String {
        format!(
            "One conjugate pole pair at radius {:.5} (~{:.0} samples per e-fold). Its impulse \
             response outlives the finite section, so the omitted tail carries real energy.",
            self.r,
            1.0 / (1.0 - self.r)
        )
    }
    fn rows_at(&self, _m: f64, _q: f64) -> Vec<[f64; NUM_COEFFS]> {
        let w = TAU * 300.0 / SR;
        vec![[1.0 - self.r, 0.0, 0.0, -2.0 * self.r * w.cos(), self.r * self.r]]
    }
    fn pole_pairs(&self) -> usize {
        1
    }
    fn evidence_mode(&self) -> EvidenceMode {
        EvidenceMode::ObservedSurface
    }
}

/// FAILURE 4: a feature narrower than the frequency grid spacing. The sampled
/// path steps straight over it and reports a system that is not there.
struct NarrowFeature;

impl SectionTarget for NarrowFeature {
    fn name(&self) -> &str {
        "narrow_feature"
    }
    fn describe(&self) -> String {
        format!(
            "A ~0.6 Hz null at 5000 Hz. NOT an IDFT failure (a razor zero does not lengthen the \
             impulse response, so a short h reconstructs exactly), but a SAMPLING failure: the \
             harness's {}-bin log grid steps over it, so every sampled H(f) the solver or the \
             estimate sees is blind to it.",
            OBJ_F_BINS
        )
    }
    fn rows_at(&self, _m: f64, _q: f64) -> Vec<[f64; NUM_COEFFS]> {
        let w = TAU * 5000.0 / SR;
        let rz = 0.99995; // razor-thin notch
        let rp = 0.9;
        vec![[
            1.0,
            -2.0 * rz * w.cos(),
            rz * rz,
            -2.0 * rp * w.cos(),
            rp * rp,
        ]]
    }
    fn pole_pairs(&self) -> usize {
        1
    }
    fn evidence_mode(&self) -> EvidenceMode {
        EvidenceMode::ObservedSurface
    }
}

/// FAILURE 5: interval-valued (noisy) measurements. Deterministic bounded noise
/// on H. No exact Markov parameters exist, so only an ESTIMATE is available and
/// the perturbation must be carried explicitly rather than ignored.
struct NoisyMeasurement {
    eps: f64,
}

impl Target for NoisyMeasurement {
    fn name(&self) -> &str {
        "noisy_measurement"
    }
    fn describe(&self) -> String {
        format!(
            "exact6 with deterministic bounded noise |e| <= {:.1e} added to H. Interval-valued \
             evidence: no exact Markov parameters, so NO certified bound is available.",
            self.eps
        )
    }
    fn h(&self, f: f64, m: f64, q: f64) -> Cf {
        let base = ExactSix::new().h(f, m, q);
        // deterministic, reproducible perturbation keyed to the frequency
        let k = (f * 7.3).sin() * 43758.5453;
        let n1 = (k - k.floor()) - 0.5;
        let k2 = (f * 12.9898 + 78.233).sin() * 43758.5453;
        let n2 = (k2 - k2.floor()) - 0.5;
        (base.0 + self.eps * n1, base.1 + self.eps * n2)
    }
    fn evidence_mode(&self) -> EvidenceMode {
        EvidenceMode::ObservedSurface
    }
    // markov(): deliberately None — noisy measurements cannot certify.
}

// ════════════════════════════════════════════════════════════════════════════
// THE HERO BODY — Branching Mouth
// ════════════════════════════════════════════════════════════════════════════
//
// PRODUCT INTENT: make basses, synths and drums sound as if they are SPEAKING.
//   Morph = what it becomes:  dark/back /ɑ/-like  ->  bright/front /i/-like
//   Q     = how strongly:     clean oral path     ->  nasal/lateral branch
//
// This is NOT an anatomical reproduction exercise. The physical model supplies
// the STRUCTURE — formant poles, and branches whose transmission zeros come from
// the branch quarter-wave — and the numbers are then tuned for musical legibility
// on bass and drums.
//
// The source model is INDEPENDENT and CONTINUOUS: at any (m,q) it is evaluated
// from physical parameters gliding in physical space. Its interior is NOT defined
// The killed serial-branch prototype and its proof bundle are preserved at
// `dev/tmp/serial_branch_prototype_KILLED`.  Its mistake was to treat six
// independently normalised pieces as creative objects.  This candidate starts
// from the opposite boundary: the complete complex product, including one
// authored absolute gain, is the creative object.  The six roots below are only
// coordinates used to author that product.
struct BranchingMouth;

const MOUTH_ROLES: [&str; NUM_STAGES] = [
    "low oral / F1 actor",
    "front-back / F2 actor",
    "F3 actor",
    "upper broad spectral-shaping actor",
    "low-mid branch-inspired pole-zero actor",
    "upper branch-inspired or closure pole-zero actor",
];

/// Explicit TOTAL-response gain anchors, in runtime corner order.  These are
/// authored constants, not measurements and not normalisation targets.
const MOUTH_GAIN_DB: [f64; 4] = [-4.0, -5.0, -5.0, -6.0];

#[derive(Clone, Copy)]
struct MouthLaneCorner {
    pole_hz: f64,
    pole_r: f64,
    zero_hz: f64,
    zero_r: f64,
}

/// Four genuinely authored poses.  Q0 branch actors are exact cancellations;
/// Q100 separates each zero from its restrained companion pole.  Lane index is
/// never sorted or changed.
const MOUTH_CORNERS: [[MouthLaneCorner; NUM_STAGES]; 4] = [
    [
        MouthLaneCorner { pole_hz: 730.0, pole_r: 0.958, zero_hz: 730.0, zero_r: 0.915 },
        MouthLaneCorner { pole_hz: 1090.0, pole_r: 0.968, zero_hz: 1090.0, zero_r: 0.915 },
        MouthLaneCorner { pole_hz: 2440.0, pole_r: 0.958, zero_hz: 2440.0, zero_r: 0.905 },
        MouthLaneCorner { pole_hz: 3650.0, pole_r: 0.925, zero_hz: 3650.0, zero_r: 0.850 },
        MouthLaneCorner { pole_hz: 850.0, pole_r: 0.550, zero_hz: 850.0, zero_r: 0.550 },
        MouthLaneCorner { pole_hz: 2700.0, pole_r: 0.500, zero_hz: 2700.0, zero_r: 0.500 },
    ],
    [
        MouthLaneCorner { pole_hz: 300.0, pole_r: 0.958, zero_hz: 300.0, zero_r: 0.915 },
        MouthLaneCorner { pole_hz: 2290.0, pole_r: 0.968, zero_hz: 2290.0, zero_r: 0.915 },
        MouthLaneCorner { pole_hz: 3010.0, pole_r: 0.958, zero_hz: 3010.0, zero_r: 0.905 },
        MouthLaneCorner { pole_hz: 4200.0, pole_r: 0.925, zero_hz: 4200.0, zero_r: 0.850 },
        MouthLaneCorner { pole_hz: 1050.0, pole_r: 0.550, zero_hz: 1050.0, zero_r: 0.550 },
        MouthLaneCorner { pole_hz: 3400.0, pole_r: 0.500, zero_hz: 3400.0, zero_r: 0.500 },
    ],
    [
        MouthLaneCorner { pole_hz: 700.0, pole_r: 0.950, zero_hz: 700.0, zero_r: 0.910 },
        MouthLaneCorner { pole_hz: 1120.0, pole_r: 0.964, zero_hz: 1120.0, zero_r: 0.915 },
        MouthLaneCorner { pole_hz: 2480.0, pole_r: 0.954, zero_hz: 2480.0, zero_r: 0.905 },
        MouthLaneCorner { pole_hz: 3650.0, pole_r: 0.920, zero_hz: 3650.0, zero_r: 0.850 },
        MouthLaneCorner { pole_hz: 690.0, pole_r: 0.680, zero_hz: 880.0, zero_r: 0.820 },
        MouthLaneCorner { pole_hz: 2300.0, pole_r: 0.640, zero_hz: 2720.0, zero_r: 0.780 },
    ],
    [
        MouthLaneCorner { pole_hz: 315.0, pole_r: 0.950, zero_hz: 315.0, zero_r: 0.910 },
        MouthLaneCorner { pole_hz: 2240.0, pole_r: 0.964, zero_hz: 2240.0, zero_r: 0.915 },
        MouthLaneCorner { pole_hz: 2960.0, pole_r: 0.954, zero_hz: 2960.0, zero_r: 0.905 },
        MouthLaneCorner { pole_hz: 4100.0, pole_r: 0.920, zero_hz: 4100.0, zero_r: 0.850 },
        MouthLaneCorner { pole_hz: 860.0, pole_r: 0.680, zero_hz: 1080.0, zero_r: 0.820 },
        MouthLaneCorner { pole_hz: 2860.0, pole_r: 0.640, zero_hz: 3380.0, zero_r: 0.780 },
    ],
];

fn mouth_bilerp(values: [f64; 4], m: f64, q: f64) -> f64 {
    let a = values[0] + (values[1] - values[0]) * m;
    let b = values[2] + (values[3] - values[2]) * m;
    a + (b - a) * q
}

fn mouth_geo(values: [f64; 4], m: f64, q: f64) -> f64 {
    mouth_bilerp(values.map(f64::ln), m, q).exp()
}

/// Direct root geometry to DF2T.  SCALE is passed explicitly.  There is no DC,
/// peak, log-mean, RMS, pose, or render normalisation anywhere in this path.
fn mouth_section(g: MouthLaneCorner, scale: f64) -> [f64; NUM_COEFFS] {
    let wp = TAU * g.pole_hz / SR;
    let wz = TAU * g.zero_hz / SR;
    [
        scale,
        scale * (-2.0 * g.zero_r * wz.cos()),
        scale * g.zero_r * g.zero_r,
        -2.0 * g.pole_r * wp.cos(),
        g.pole_r * g.pole_r,
    ]
}

fn mouth_lane_at(lane: usize, m: f64, q: f64) -> MouthLaneCorner {
    let v = |f: fn(MouthLaneCorner) -> f64| MOUTH_CORNERS.map(|c| f(c[lane]));
    MouthLaneCorner {
        pole_hz: mouth_geo(v(|x| x.pole_hz), m, q),
        pole_r: mouth_bilerp(v(|x| x.pole_r), m, q),
        zero_hz: mouth_geo(v(|x| x.zero_hz), m, q),
        zero_r: mouth_bilerp(v(|x| x.zero_r), m, q),
    }
}

impl SectionTarget for BranchingMouth {
    fn name(&self) -> &str {
        "branching_mouth"
    }
    fn describe(&self) -> String {
        "AUTHORED, BRANCH-INSPIRED product preset. The complete complex six-lane product is the \
         creative object. Morph moves an original open /ɑ/-like posture to a forward /i/-like \
         posture. Q preserves that identity while two authored pole-zero actors add restrained, \
         asymmetrical low-mid and upper antiresonance. Four explicit total-response gain anchors \
         are interpolated in dB. No section or render normalisation and no claim of physical \
         vocal-tract generation."
            .into()
    }
    fn rows_at(&self, m: f64, q: f64) -> Vec<[f64; NUM_COEFFS]> {
        let gain = 10.0f64.powf(mouth_bilerp(MOUTH_GAIN_DB, m, q) / 20.0);
        (0..NUM_STAGES)
            .map(|lane| mouth_section(mouth_lane_at(lane, m, q), if lane == 0 { gain } else { 1.0 }))
            .collect()
    }
    fn pole_pairs(&self) -> usize {
        NUM_STAGES
    }
    fn evidence_mode(&self) -> EvidenceMode {
        // The source model DECLARES which actor is which lane. That is an
        // authoring prior — never a recovery from the transfer functions.
        EvidenceMode::AuthoredTrajectory
    }
    fn authored_lanes_at(&self, m: f64, q: f64) -> Option<Vec<String>> {
        Some(
            (0..NUM_STAGES)
                .map(|lane| {
                    let g = mouth_lane_at(lane, m, q);
                    format!(
                        "{}: pole {:.0} Hz r={:.3}, zero {:.0} Hz r={:.3}",
                        MOUTH_ROLES[lane], g.pole_hz, g.pole_r, g.zero_hz, g.zero_r
                    )
                })
                .collect(),
        )
    }
}

// ── acceptance gate (thresholds fixed BEFORE any result was seen) ───────────

const ACC_MEDIAN_DB: f64 = 0.1;
const ACC_P90_DB: f64 = 0.5;
const ACC_PHASE_DEG: f64 = 2.0;

fn qualify_one(
    t: &dyn Target,
    approach: &str,
    seed: u64,
    train: &Surface,
    held: &Surface,
    refine_iters: usize,
) -> serde_json::Value {
    let t0 = std::time::Instant::now();
    let pc = match approach {
        "structured" => solver_structured(train, seed, refine_iters),
        _ => solver_evolutionary(train, seed, refine_iters),
    };
    let secs = t0.elapsed().as_secs_f64();
    let body = pc.to_rom_bytes();
    let rt = residual(&pc, train);
    let rh = residual(&pc, held);
    // DIAGNOSTIC: corner-only error localises the failure. Corners good +
    // interior bad => assembly/correspondence/scale-split. Corners bad =>
    // recovery or packing.
    let rc = residual(&pc, &corner_only_surface(t));
    let legal = legality(&body, &pc, "qual");
    let pass = rh.median_db <= ACC_MEDIAN_DB
        && rh.p90_db <= ACC_P90_DB
        && rh.phase_rms_deg <= ACC_PHASE_DEG
        && legal["legal"].as_bool().unwrap_or(false);
    serde_json::json!({
        "fixture": t.name(), "approach": approach, "seed": seed,
        "runtime_s": secs,
        "corners_only_diagnostic": {
            "median_db": rc.median_db, "p90_db": rc.p90_db,
            "localises": "corners good + interior bad => assembly/correspondence/scale-split. \
                          corners bad => recovery or packing.",
        },
        "train": {"median_db": rt.median_db, "p90_db": rt.p90_db, "rms_db": rt.rms_db},
        "held_out": {
            "median_db": rh.median_db, "p90_db": rh.p90_db, "rms_db": rh.rms_db,
            "max_db": rh.max_db, "phase_rms_deg": rh.phase_rms_deg,
            "worst_at": {"state": rh.worst_label, "hz": rh.worst_hz},
        },
        "legal": legal["legal"],
        "unstable_rows": legal["sampled_certification"]["unstable_rows"],
        "nonfinite_rows": legal["sampled_certification"]["nonfinite_rows"],
        "wrap_hazard": legal["packed_interp_wrap_hazard"],
        "pass": pass,
        "thresholds": {"median_db": ACC_MEDIAN_DB, "p90_db": ACC_P90_DB, "phase_rms_deg": ACC_PHASE_DEG},
    })
}

/// The routine qualification/authoring route. `structured` ONLY.
///
/// `evolutionary` has finished its job: it was required to benchmark a competing
/// approach, and it FAILED (0/12 vs structured's 12/12 on identical fixtures and
/// seeds). Keeping it in the default path buys no evidence and costs more than
/// half of every qualification run. It is quarantined behind an explicit opt-in,
/// NOT deleted, so the negative result stays reproducible.
const ROUTINE_APPROACHES: [&str; 1] = ["structured"];
const BENCHMARK_APPROACHES: [&str; 2] = ["structured", "evolutionary"];
/// The preserved 24-run comparison that REJECTED the evolutionary solver.
const COMPARISON_ARTIFACT: &str = "dev/tmp/tf_harness/comparison_24run_structured_vs_evolutionary.json";

fn cmd_qualify(
    seeds: u64,
    fixture_filter: Option<&str>,
    include_evolutionary_benchmark: bool,
    refine_iters: usize,
) {
    let approaches: &[&str] = if include_evolutionary_benchmark {
        &BENCHMARK_APPROACHES
    } else {
        &ROUTINE_APPROACHES
    };
    let f1 = ExactSix::new();
    let f2 = qual_notchy();
    let f3 = qual_realroot();
    let fixtures: Vec<&dyn Target> = vec![&f1, &f2, &f3];
    let mut runs = Vec::new();
    println!("\n=== SOLVER QUALIFICATION ===");
    println!(
        "acceptance (fixed before any result): held-out median <= {ACC_MEDIAN_DB} dB, \
         p90 <= {ACC_P90_DB} dB, phase RMS <= {ACC_PHASE_DEG} deg, legal"
    );
    println!("solver sees ONLY sampled complex H_target(f,m,q) — no rows, words, identities, or oracle init");
    println!("selected solver: structured    |    evolutionary: REJECTED for routine use, NOT executed");
    if include_evolutionary_benchmark {
        println!("*** --include-evolutionary-benchmark: running the REJECTED evolutionary solver as an explicit diagnostic ***");
    }
    println!();
    for t in &fixtures {
        if fixture_filter.is_some_and(|wanted| wanted != t.name()) {
            continue;
        }
        let train = sample_surface(*t, OBJ_MQ);
        let held = held_out_surface(*t);
        for &approach in approaches {
            for seed in 0..seeds {
                let r = qualify_one(*t, approach, seed, &train, &held, refine_iters);
                println!(
                    "  {:<14} {:<13} s{}  corners {:>7.3}  held-out med {:>7.3} p90 {:>7.3} ph {:>6.1}°  {:>5.1}s  {}",
                    t.name(), approach, seed,
                    r["corners_only_diagnostic"]["median_db"].as_f64().unwrap(),
                    r["held_out"]["median_db"].as_f64().unwrap(),
                    r["held_out"]["p90_db"].as_f64().unwrap(),
                    r["held_out"]["phase_rms_deg"].as_f64().unwrap(),
                    r["runtime_s"].as_f64().unwrap(),
                    if r["pass"].as_bool().unwrap() { "PASS" } else { "FAIL" },
                );
                runs.push(r);
            }
        }
    }
    let total = runs.len();
    let passed = runs.iter().filter(|r| r["pass"] == true).count();
    let selected_approaches: Vec<&str> = approaches.to_vec();
    let by = |a: &str| {
        let sel: Vec<&serde_json::Value> = runs.iter().filter(|r| r["approach"] == a).collect();
        let p = sel.iter().filter(|r| r["pass"] == true).count();
        let med: Vec<f64> = sel
            .iter()
            .map(|r| r["held_out"]["median_db"].as_f64().unwrap())
            .collect();
        let best = med.iter().cloned().fold(f64::INFINITY, f64::min);
        let secs: f64 = sel
            .iter()
            .map(|r| r["runtime_s"].as_f64().unwrap())
            .sum::<f64>()
            / sel.len().max(1) as f64;
        serde_json::json!({
            "approach": a, "runs": sel.len(), "passed": p,
            "success_rate": p as f64 / sel.len().max(1) as f64,
            "best_held_out_median_db": best,
            "mean_runtime_s": secs,
        })
    };
    let by_approach: Vec<serde_json::Value> = selected_approaches.iter().map(|a| by(a)).collect();
    let qualified_approaches: Vec<&str> = selected_approaches
        .iter()
        .copied()
        .filter(|a| {
            let sel: Vec<&serde_json::Value> =
                runs.iter().filter(|r| r["approach"] == *a).collect();
            !sel.is_empty() && sel.iter().all(|r| r["pass"] == true)
        })
        .collect();
    let gate_passed = !qualified_approaches.is_empty();
    let summary = serde_json::json!({
        "schema": "tf-harness-qualification-v1",
        "gate": "SOLVER QUALIFICATION",
        "thresholds_fixed_before_results": {
            "held_out_median_db": ACC_MEDIAN_DB, "held_out_p90_db": ACC_P90_DB,
            "phase_rms_deg": ACC_PHASE_DEG,
            "note": "thresholds were declared before any solver was run and were NOT weakened afterwards",
        },
        "solver_access": "sampled complex H_target(f,m,q) ONLY — no target corner rows, no target \
                          packed words, no target lane identities, no oracle initialization",
        "held_out_grid": "8x8 at (2k+1)/16 — disjoint from the 5x5 training grid",
        "configuration": {"seeds": seeds, "refine_iters": refine_iters},
        "solver_selection": {
            "selected_solver": "structured",
            "selected_solver_route": "the sole routine qualification and authoring route",
            "evolutionary_status": "REJECTED for routine use",
            "evolutionary_rejected_because": "0/12 PASS against structured's 12/12 on identical \
                                              fixtures and identical deterministic seeds, while \
                                              consuming more than half of the qualification runtime. \
                                              It completed its job — benchmarking a competing \
                                              approach — and failed it.",
            "evolutionary_executed_in_this_run": include_evolutionary_benchmark,
            "evolutionary_implementation": "RETAINED and quarantined behind an explicit opt-in, not \
                                            deleted — the negative result stays reproducible",
            "evolutionary_reachable_via": "tf_harness qualify --include-evolutionary-benchmark",
            "evolutionary_never_runs_during": "ordinary `qualify` — routine qualification executes \
                                               the structured solver only",
            "failed_benchmark_evidence": COMPARISON_ARTIFACT,
            "failed_benchmark_evidence_note": "the 24-run structured-vs-evolutionary comparison is \
                                               preserved verbatim as a historical artifact and is \
                                               NOT overwritten by routine qualification, which \
                                               writes qualification.json",
        },
        "thresholds_unchanged": "The acceptance thresholds are the values declared before any solver \
                                 was run (median 0.1 dB, p90 0.5 dB, phase 2.0 deg) and have NOT been \
                                 weakened. Retiring the evolutionary benchmark changed WHICH solvers \
                                 run, never what passing means.",
        "qualification_rule": "At least one benchmarked approach must pass every fixture and every \
                               deterministic seed. Benchmark alternatives may fail; their failures \
                               remain reported and do not invalidate a different qualified solver.",
        "total_runs": total, "total_passed": passed,
        "overall_success_rate": passed as f64 / total.max(1) as f64,
        "gate_passed": gate_passed,
        "qualified_approaches": qualified_approaches,
        "by_approach": by_approach,
        "runs": runs,
        "verdict": if gate_passed {
            "QUALIFIED — at least one solver approach met every acceptance threshold on every fixture \
             and every reported deterministic seed. Failed benchmark alternatives remain failures."
        } else {
            "NOT QUALIFIED — no solver approach passed every fixture and seed. Strongest measured failure reported. \
             The source tournament stays BLOCKED."
        },
    });
    let root = repo_root().join("dev").join("tmp").join("tf_harness");
    std::fs::create_dir_all(&root).unwrap();
    // Artifact separation: the routine report is the official one. A partial
    // probe or an explicit evolutionary benchmark writes ELSEWHERE, so neither a
    // narrowed run nor a diagnostic of the REJECTED solver can overwrite it.
    let output_name = if fixture_filter.is_some() {
        "qualification_probe.json"
    } else if include_evolutionary_benchmark {
        "qualification_with_evolutionary_benchmark.json"
    } else {
        "qualification.json"
    };
    std::fs::write(
        root.join(output_name),
        serde_json::to_string_pretty(&summary).unwrap(),
    )
    .unwrap();
    println!("\n  {} / {} runs passed", passed, total);
    for a in selected_approaches {
        let s = by(a);
        println!(
            "  {:<13} success {:>3.0}%  best held-out median {:.4} dB  mean {:.1}s",
            a,
            s["success_rate"].as_f64().unwrap() * 100.0,
            s["best_held_out_median_db"].as_f64().unwrap(),
            s["mean_runtime_s"].as_f64().unwrap()
        );
    }
    println!("  verdict: {}", summary["verdict"].as_str().unwrap());
    println!("  wrote {}", root.join(output_name).display());
}

// ════════════════════════════════════════════════════════════════════════════
// DESTRUCTION FLOOR — what six stages CANNOT keep, proven before any fit
// ════════════════════════════════════════════════════════════════════════════
//
// The question is no longer "can we fit into six?" but "what does six destroy,
// and is that destruction musically acceptable?" The first half of that is a
// solved problem in system theory, and it does NOT require a solver, an oracle,
// or a fit — all of which only ever produce an UPPER bound.
//
// GLOVER (1984) / model order reduction. For a stable LTI system G with Hankel
// singular values σ₁ ≥ σ₂ ≥ … ≥ σₙ:
//
//     inf over ALL stable Ĝ of order ≤ k  of  ‖G − Ĝ‖_∞   ≥   σ_{k+1}
//
// Six biquads are 12 poles, so k = 12 and **σ₁₃ is a PROVEN LOWER BOUND on the
// error of every six-stage cascade that could ever exist** — however cleverly
// fitted. Balanced truncation attains ≤ 2·Σ_{i>k} σᵢ, so the achievable error is
// BRACKETED with no optimizer in the loop.
//
// This is the attribution instrument the harness was missing:
//   · my solver's error ≈ σ₁₃  -> the solver is near-optimal; the loss IS the format
//   · my solver's error ≫ σ₁₃  -> the loss is MY SOLVER, and the format is innocent
//
// The σ spectrum itself is the answer to "what does six destroy": if σ collapses
// after 12, six stages lose nothing. If it decays slowly, six stages destroy a
// measurable amount and you know how much BEFORE authoring anything.
//
// Source-agnostic by construction: it needs only sampled H(f), so it works on an
// authored model, a physical simulation, or a real measurement alike.
//
// CAVEAT (declared): σ₁₃ bounds the ORDER constraint only. The packed format
// adds quantization and the 4-corner bilinear word interpolation on top, so the
// truly achievable error is ≥ σ₁₃. It is a floor on the floor — but a floor that
// is already musically fatal ends the argument without a single render.

/// EXACT causal Markov parameters of an ordered section product, by the DF2T
/// difference equation in f64. No DFT, so no time aliasing and no frequency
/// sampling — the only error is f64 rounding, which the certified allowance
/// covers. Pinned against the OWNED response engine by
/// `exact_markov_matches_owned_response`, so this is an analysis reader of the
/// same law, not a second kernel.
fn exact_markov(rows: &[[f64; NUM_COEFFS]], n: usize) -> Vec<f64> {
    let mut sig = vec![0.0f64; n];
    if n == 0 {
        return sig;
    }
    sig[0] = 1.0; // unit impulse
    for r in rows {
        let (b0, b1, b2, a1, a2) = (r[0], r[1], r[2], r[3], r[4]);
        let (mut w1, mut w2) = (0.0f64, 0.0f64);
        for x in sig.iter_mut() {
            let y = b0 * *x + w1;
            w1 = b1 * *x - a1 * y + w2;
            w2 = b2 * *x - a2 * y;
            *x = y;
        }
    }
    sig
}

/// Impulse (Markov) parameters from a sampled spectrum, by inverse DFT.
///
/// Source-agnostic — it needs only H(f), so the same path serves a measurement.
/// But it is NOT exact: the IDFT returns the TIME-ALIASED (periodized) impulse
/// response, h_alias[n] = Σ_k h[n + kN], and it can only see features the
/// frequency grid resolves. Both are why anything built on it is ESTIMATED.
fn impulse_from_spectrum(t: &dyn Target, m: f64, q: f64, n: usize) -> Vec<f64> {
    // uniform grid to Nyquist; Hermitian symmetry makes the result real
    let half = n / 2;
    let spec: Vec<Cf> = (0..=half)
        .map(|k| {
            let f = k as f64 * SR / n as f64;
            t.h(f, m, q)
        })
        .collect();
    let mut h = vec![0.0f64; n];
    for (nn, hv) in h.iter_mut().enumerate() {
        let mut acc = 0.0f64;
        for (k, s) in spec.iter().enumerate() {
            let ang = TAU * (k as f64) * (nn as f64) / n as f64;
            // k and its mirror N-k contribute conjugates -> 2·Re, except DC/Nyquist
            let w = if k == 0 || (k == half && n % 2 == 0) { 1.0 } else { 2.0 };
            acc += w * (s.0 * ang.cos() - s.1 * ang.sin());
        }
        *hv = acc / n as f64;
    }
    h
}

/// Singular values of A by ONE-SIDED JACOBI.
///
/// Not via the eigenvalues of AᵀA: squaring destroys exactly the SMALL singular
/// values, and σ₁₃ — the whole point — is small by construction. One-sided Jacobi
/// computes small singular values to high RELATIVE accuracy, which is what makes
/// "σ₁₃ ≈ 0 means representable" a trustworthy statement.
fn jacobi_singular_values(mut a: Vec<Vec<f64>>) -> Vec<f64> {
    let rows = a.len();
    let cols = if rows == 0 { 0 } else { a[0].len() };
    if rows == 0 || cols == 0 {
        return vec![];
    }
    for _sweep in 0..30 {
        let mut off = 0.0f64;
        for p in 0..cols - 1 {
            for qq in p + 1..cols {
                let (mut app, mut aqq, mut apq) = (0.0f64, 0.0f64, 0.0f64);
                for r in a.iter() {
                    app += r[p] * r[p];
                    aqq += r[qq] * r[qq];
                    apq += r[p] * r[qq];
                }
                if apq.abs() < 1e-300 {
                    continue;
                }
                off = off.max(apq.abs() / (app.sqrt() * aqq.sqrt()).max(1e-300));
                let tau = (aqq - app) / (2.0 * apq);
                let t = tau.signum() / (tau.abs() + (1.0 + tau * tau).sqrt());
                let c = 1.0 / (1.0 + t * t).sqrt();
                let s = c * t;
                for r in a.iter_mut() {
                    let (rp, rq) = (r[p], r[qq]);
                    r[p] = c * rp - s * rq;
                    r[qq] = s * rp + c * rq;
                }
            }
        }
        if off < 1e-14 {
            break;
        }
    }
    let mut sv: Vec<f64> = (0..cols)
        .map(|j| a.iter().map(|r| r[j] * r[j]).sum::<f64>().sqrt())
        .collect();
    sv.sort_by(|x, y| y.partial_cmp(x).unwrap_or(std::cmp::Ordering::Equal));
    sv
}

/// Hankel singular values of the system whose Markov parameters are `h`.
/// The Hankel matrix uses h[1..] — h[0] is the direct feedthrough D, which the
/// Hankel operator ignores (and which an approximant may match exactly).
fn hankel_singular_values(h: &[f64], l: usize) -> Vec<f64> {
    let mut mat = vec![vec![0.0f64; l]; l];
    for (i, row) in mat.iter_mut().enumerate() {
        for (j, v) in row.iter_mut().enumerate() {
            *v = h.get(1 + i + j).copied().unwrap_or(0.0);
        }
    }
    jacobi_singular_values(mat)
}

/// Two explicit evidence modes. What may be CLAIMED depends only on what the
/// evidence actually supports — the same discipline as the correspondence
/// contract.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum FloorMode {
    /// Exact (or interval-bounded) causal Markov parameters available.
    /// Yields a finite-section lower bound WITH a rigorous perturbation
    /// allowance and convergence evidence — or an explicit refusal.
    CertifiedMarkovBound,
    /// Only sampled H(f). σ_{k+1} is ESTIMATED, never proven: the inverse DFT
    /// time-aliases the impulse response and the frequency grid cannot see
    /// between its own samples.
    SampledSpectrumEstimate,
}

impl FloorMode {
    fn label(&self) -> &'static str {
        match self {
            Self::CertifiedMarkovBound => "CERTIFIED_MARKOV_BOUND",
            Self::SampledSpectrumEstimate => "SAMPLED_SPECTRUM_ESTIMATE",
        }
    }
}

struct Floor {
    mode: FloorMode,
    sigma: Vec<f64>,
    sigma_k1: f64,      // σ_{k+1} of the FINITE section actually computed
    allowance: f64,     // rigorous perturbation allowance (Weyl)
    lower_bound: f64,   // certified: max(0, σ_{k+1} − allowance). estimate: NaN
    /// Whether the bound MEANS anything. A near-zero bound from a section that
    /// missed the system is valid and worthless. Never read a non-informative
    /// bound as "six destroys nothing".
    informative: bool,
    peak_gain: f64,
    l_used: usize,
    markov_extent: usize,     // the section reads h[1 ..= 2L−1]
    tail_energy_fraction: f64, // energy in h beyond the section's reach
    convergence: Vec<(usize, f64)>, // (L, σ_{k+1}) — the L-sweep
    converged: bool,
    declared_delay: usize,
    status: &'static str,
}

/// Finite-section σ_{k+1} for one L.
fn section_sigma_k1(h: &[f64], l: usize, order: usize) -> (f64, Vec<f64>) {
    let sv = hankel_singular_values(h, l);
    (sv.get(order).copied().unwrap_or(0.0), sv)
}

/// THE instrument. `order` = pole budget (12 = six biquads).
///
/// VALIDITY (certified mode). The L×L section Γ_L is a SUBMATRIX of the infinite
/// Hankel operator Γ, so by the interlacing property σ_j(Γ_L) ≤ σ_j(Γ) for every
/// j. Combined with Glover: achievable ‖G−Ĝ‖_∞ ≥ σ_{k+1}(Γ) ≥ σ_{k+1}(Γ_L).
/// The finite section is therefore CONSERVATIVE — it can only ever understate.
///
/// THE TRAP THIS ENCODES. "Conservative" is not "informative". A section that
/// reaches h[1..2L−1] and misses where the system's energy actually lives returns
/// ~0, which is a VALID bound and a WORTHLESS one. MEASURED: for a pure delay
/// z^-320 the L=160 section reads h[1..319], never touches h[320], and returns
/// σ₁₃ = 0 — while the truth is σ₁₃ = 1 (a 320-sample delay is untouchable by 12
/// poles). Reporting that as "six destroys nothing" inverts the meaning of the
/// number. So a near-zero σ is only informative when the section provably
/// CAPTURED the system: the tail-energy guard and the L-sweep below decide that,
/// and refuse otherwise.
fn destruction_floor(t: &dyn Target, m: f64, q: f64, order: usize) -> Floor {
    const NIMP: usize = 8192;
    const L_MAX: usize = 320;
    const L_SWEEP: [usize; 4] = [40, 80, 160, 320];

    let grid = log_frequency_grid(F_LO, F_HI, 512);
    let peak_gain = grid.iter().map(|&f| cabs(t.h(f, m, q))).fold(0.0f64, f64::max);
    let declared_delay = t.transport_delay_samples();

    // ── certified path: exact Markov parameters, no DFT anywhere ──
    if let Some(mut h) = t.markov(m, q, NIMP) {
        // Remove ONLY the declared pure transport delay — nothing else.
        if declared_delay > 0 && declared_delay < h.len() {
            h.drain(..declared_delay);
        }
        let total: f64 = h.iter().skip(1).map(|v| v * v).sum();
        let reach = 2 * L_MAX - 1; // the largest Markov index any section reads
        let tail: f64 = h.iter().skip(reach + 1).map(|v| v * v).sum();
        let tail_frac = if total > 0.0 { tail / total } else { 0.0 };

        let mut convergence = Vec::new();
        for &l in &L_SWEEP {
            convergence.push((l, section_sigma_k1(&h, l, order).0));
        }
        let (sigma_k1, sigma) = section_sigma_k1(&h, L_MAX, order);

        // Weyl: |σ_k(A+E) − σ_k(A)| ≤ ‖E‖₂ ≤ ‖E‖_F. Each Markov entry carries at
        // most `eps_rel` relative f64 rounding; the L×L section has L² entries.
        let hmax = h.iter().fold(0.0f64, |a, &v| a.max(v.abs()));
        let allowance = (L_MAX as f64) * hmax * 1e-14;

        // Convergence: σ_{k+1} must have stopped moving as L grew.
        let last = convergence.last().map(|c| c.1).unwrap_or(0.0);
        let prev = convergence
            .get(convergence.len().saturating_sub(2))
            .map(|c| c.1)
            .unwrap_or(0.0);
        let scale = sigma.first().copied().unwrap_or(0.0).max(1e-300);
        let l_converged = (last - prev).abs() <= 1e-6 * scale + allowance;
        // Capture: the section must actually contain the system's energy.
        let captured = tail_frac < 1e-9;
        let converged = l_converged && captured;

        // VALIDITY vs INFORMATIVENESS — these are different, and conflating them
        // was the original error.
        //
        // The bound is ALWAYS valid: Γ_L is a submatrix of the infinite Hankel
        // operator, so σ_j(Γ_L) ≤ σ_j(Γ) by interlacing, with NO perturbation
        // from the omitted tail. A finite section can only ever UNDERSTATE.
        // So a POSITIVE bound is certified destruction whatever the tail does.
        //
        // A NEAR-ZERO bound is where the tail matters — not for validity but for
        // meaning. Zero is what you get both when the target genuinely fits in k
        // poles AND when the section simply missed the system (the z^-320 case).
        // Only the capture guard plus L-convergence can tell those apart.
        let bound = (sigma_k1 - allowance).max(0.0);
        let sigma1 = sigma.first().copied().unwrap_or(0.0);
        let materially_positive = bound > 1e-6 * sigma1.max(1e-300);
        let informative = materially_positive || (captured && l_converged);
        let status = if materially_positive {
            "CERTIFIED (positive) — a strictly positive lower bound on the error of EVERY six-stage \
             cascade. Valid by submatrix interlacing regardless of the omitted tail, since a finite \
             section can only understate."
        } else if captured && l_converged {
            "CERTIFIED (zero) — the bound is ~0 AND the section provably captures the system (tail \
             energy below threshold, converged in L), so the order constraint genuinely costs nothing."
        } else {
            "VACUOUS — the bound is ~0 but the section does NOT capture the system (energy beyond \
             h[2L-1], or not converged in L). NO CONCLUSION: this value is a valid bound that carries \
             no information. It must NEVER be read as 'six destroys nothing'."
        };
        return Floor {
            mode: FloorMode::CertifiedMarkovBound,
            sigma,
            sigma_k1,
            allowance,
            // the bound is valid unconditionally; `informative` gates what it MEANS
            lower_bound: bound,
            informative,
            peak_gain,
            l_used: L_MAX,
            markov_extent: reach,
            tail_energy_fraction: tail_frac,
            convergence,
            converged,
            declared_delay,
            status,
        };
    }

    // ── estimate path: sampled spectrum only ──
    let h = impulse_from_spectrum(t, m, q, NIMP);
    let mut convergence = Vec::new();
    for &l in &L_SWEEP {
        convergence.push((l, section_sigma_k1(&h, l, order).0));
    }
    let (sigma_k1, sigma) = section_sigma_k1(&h, L_MAX, order);
    Floor {
        mode: FloorMode::SampledSpectrumEstimate,
        sigma,
        sigma_k1,
        allowance: f64::NAN,
        lower_bound: f64::NAN,
        informative: false, // an estimate never certifies anything
        peak_gain,
        l_used: L_MAX,
        markov_extent: 2 * L_MAX - 1,
        tail_energy_fraction: f64::NAN,
        convergence,
        converged: false,
        declared_delay,
        status: "ESTIMATED — sampled-spectrum surrogate. The inverse DFT time-aliases the impulse \
                 response and the frequency grid cannot see between its own samples. This value is \
                 an ESTIMATE and is NOT a bound: it makes no claim about unsampled frequencies or \
                 omitted impulse response.",
    }
}

/// ADDITIVE H-infinity error over the sampled surface: max over (m,q,f) of
/// |H_candidate − H_target| in LINEAR magnitude.
///
/// This is the SAME norm and the SAME units as the Hankel bound, which is the
/// only reason the two may be compared. The harness's dB median/p90 is
/// |20·log10(|Hc|/|Ht|)| — a RATIO in dB — and the weighted dB+phase objective is
/// a different quantity again. Comparing either to σ_{k+1} is meaningless.
fn linf_additive_error(pc: &PackedCorners, s: &Surface) -> (f64, String, f64) {
    let mut worst = 0.0f64;
    let mut where_state = String::new();
    let mut where_hz = 0.0f64;
    for st in &s.states {
        let rows = pc.interpolate_biquad(st.m as f32, st.q as f32);
        for (i, &f) in s.freqs.iter().enumerate() {
            let hc = biquad_cascade_complex(&rows, f, SR);
            let d = cabs(csub(hc, st.h[i]));
            if d > worst {
                worst = d;
                where_state = st.label.clone();
                where_hz = f;
            }
        }
    }
    (worst, where_state, where_hz)
}

/// Sweep the COMPLETE sampled Morph×Q surface and report the strongest lower
/// bound and where it lives. A single mid-point is not the surface.
fn floor_over_surface(t: &dyn Target, order: usize) -> (f64, f64, f64, Vec<serde_json::Value>) {
    let mut best = f64::NEG_INFINITY;
    let (mut bm, mut bq) = (0.0f64, 0.0f64);
    let mut rows = Vec::new();
    for (label, m, q) in mq_grid(3) {
        let fl = destruction_floor(t, m, q, order);
        let val = if fl.mode == FloorMode::CertifiedMarkovBound && fl.converged {
            fl.lower_bound
        } else {
            fl.sigma_k1
        };
        if val > best {
            best = val;
            bm = m;
            bq = q;
        }
        rows.push(serde_json::json!({
            "state": label, "morph": m, "q": q,
            "mode": fl.mode.label(),
            "sigma_k1_finite_section": fl.sigma_k1,
            "certified_lower_bound": if fl.lower_bound.is_finite() { serde_json::json!(fl.lower_bound) } else { serde_json::Value::Null },
            "perturbation_allowance": if fl.allowance.is_finite() { serde_json::json!(fl.allowance) } else { serde_json::Value::Null },
            "peak_gain": fl.peak_gain,
            "L": fl.l_used,
            "markov_extent_h_1_to": fl.markov_extent,
            "tail_energy_fraction": if fl.tail_energy_fraction.is_finite() { serde_json::json!(fl.tail_energy_fraction) } else { serde_json::Value::Null },
            "L_convergence": fl.convergence.iter().map(|(l, s)| serde_json::json!({"L": l, "sigma_k1": s})).collect::<Vec<_>>(),
            "converged": fl.converged,
            "declared_transport_delay": fl.declared_delay,
            "status": fl.status,
        }));
    }
    (best, bm, bq, rows)
}

fn cmd_floor() {
    const ORDER: usize = 2 * NUM_STAGES; // 12 poles = six biquads
    println!("\n=== DESTRUCTION FLOOR — what six stages CANNOT keep ===");
    println!(
        "Glover (1984): the infimum of ||G - G_hat||_inf over ALL stable G_hat of order <= {ORDER}\n\
         is bounded below by sigma_{}. Six biquads = {ORDER} poles.\n",
        ORDER + 1
    );
    println!("TWO MODES — what may be claimed depends ONLY on the evidence:");
    println!("  CERTIFIED_MARKOV_BOUND    exact Markov params + Weyl allowance + L-convergence + capture guard");
    println!("  SAMPLED_SPECTRUM_ESTIMATE sampled H(f) only -> sigma is ESTIMATED, never proven\n");

    let f1 = ExactSix::new();
    let f2 = qual_notchy();
    let f3 = qual_realroot();
    let f4 = OverBudget::new();
    let d1 = PureDelay { d: 320, declare: false };
    let d2 = PureDelay { d: 320, declare: true };
    let d3 = PureDelay { d: 8192, declare: false }; // delay == the DFT period
    let sp = SlowPole { r: 0.9995 };
    let nf = NarrowFeature;
    let nm = NoisyMeasurement { eps: 1e-3 };
    let targets: Vec<(&dyn Target, &str)> = vec![
        (&f1, "exactly representable (5 pole pairs)"),
        (&f2, "exactly representable (near-unit zeros)"),
        (&f3, "exactly representable (real roots)"),
        (&f4, "OVER BUDGET (10 pole pairs = 20 poles)"),
        (&d1, "FAILURE FIXTURE: undeclared pure delay z^-320"),
        (&d2, "FAILURE FIXTURE: pure delay z^-320, DECLARED and removed"),
        (&d3, "FAILURE FIXTURE: delay == DFT period (aliases to h[0])"),
        (&sp, "FAILURE FIXTURE: slowly decaying pole r=0.9995"),
        (&nf, "FAILURE FIXTURE: feature narrower than the frequency grid"),
        (&nm, "FAILURE FIXTURE: noisy/interval measurement (no exact Markov)"),
    ];
    let mut report = Vec::new();
    for (t, note) in &targets {
        println!("-- {} : {}", t.name(), note);
        let fl = destruction_floor(*t, 0.0, 0.0, ORDER);
        let rel_db = if fl.peak_gain > 0.0 {
            20.0 * (fl.sigma_k1 / fl.peak_gain).max(1e-300).log10()
        } else {
            f64::NEG_INFINITY
        };
        let conv: Vec<String> = fl
            .convergence
            .iter()
            .map(|(l, s)| format!("L{l}:{s:.2e}"))
            .collect();
        println!("   mode {}   status {}", fl.mode.label(), &fl.status[..fl.status.len().min(58)]);
        println!(
            "   sigma{} = {:.4e} ({:+.1} dB rel peak) | L-sweep [{}] | tail {:.2e} | converged {}",
            ORDER + 1,
            fl.sigma_k1,
            rel_db,
            conv.join(" "),
            fl.tail_energy_fraction,
            fl.converged
        );
        if fl.lower_bound.is_finite() {
            println!("   CERTIFIED lower bound: {:.4e}  (allowance {:.2e})", fl.lower_bound, fl.allowance);
        } else {
            println!("   NO certified bound available.");
        }
        let (best, bm, bq, points) = floor_over_surface(*t, ORDER);
        println!("   strongest over surface: {best:.4e} at morph {bm:.2} q {bq:.2}\n");
        report.push(serde_json::json!({
            "target": t.name(), "note": note, "describe": t.describe(),
            "mode": fl.mode.label(),
            "strongest_lower_bound_over_surface": best,
            "strongest_at": {"morph": bm, "q": bq},
            "surface": points,
        }));
    }
    let out = serde_json::json!({
        "schema": "tf-harness-destruction-floor-v2",
        "theorem": "Glover (1984), optimal Hankel-norm approximation: for a stable LTI system with \
                    Hankel singular values sigma_1 >= sigma_2 >= ..., the infimum of ||G - G_hat||_inf \
                    over ALL stable G_hat of order <= k is bounded below by sigma_{k+1}.",
        "pole_budget": ORDER,
        "modes": {
            "CERTIFIED_MARKOV_BOUND": "Requires EXACT (or interval-bounded) causal Markov parameters \
                and a DECLARED transport delay, of which only that delay is removed. The L x L section \
                is a SUBMATRIX of the infinite Hankel operator, so by interlacing sigma_j(Gamma_L) <= \
                sigma_j(Gamma): the finite section can only UNDERSTATE, never overstate. Reported with \
                a Weyl perturbation allowance (|sigma_k(A+E) - sigma_k(A)| <= ||E||_2 <= ||E||_F), the \
                matrix extent, the L-convergence sweep, and a tail-energy capture guard.",
            "SAMPLED_SPECTRUM_ESTIMATE": "Accepts sampled H(f). sigma_{k+1} is ESTIMATED and is NOT a \
                bound. The inverse DFT returns the TIME-ALIASED impulse response and the frequency grid \
                cannot see between its own samples. Makes NO claim about unsampled frequencies or \
                omitted impulse response."
        },
        "conservative_is_not_informative": "A finite section that misses where the system's energy \
            lives returns ~0: a VALID bound and a WORTHLESS one. MEASURED: an undeclared pure delay \
            z^-320 read through an L=160 section (h[1..319], never reaching h[320]) returned sigma_13 \
            = 0 and was reported as '-301 dB, six destroys nothing' — while the true Hankel singular \
            values of a 320-sample delay are 1 (x320), i.e. utterly beyond 12 poles. The capture guard \
            and L-sweep now REFUSE instead of producing that number.",
        "no_upper_bound_claimed": "The earlier 'balanced truncation upper bound' and 'error is \
            bracketed' claims are WITHDRAWN. No stable reduced realization is constructed here and the \
            omitted tail is not bounded, so no upper bound is asserted. Only a lower bound (certified \
            mode) or an estimate (sampled mode) is reported.",
        "caveat_order_only": "sigma_{k+1} bounds the ORDER constraint ONLY. The packed format adds \
            minifloat quantization and 4-corner bilinear word interpolation on top, so the truly \
            achievable error is >= this. It is a floor on the floor.",
        "norm": "H-infinity: worst case over frequency of the ADDITIVE, LINEAR-magnitude difference \
                 |G - G_hat|. Candidate error MUST be compared in this same norm (see \
                 linf_additive_error) — never against dB median/p90 ratios or the weighted dB+phase \
                 training objective, which are different quantities entirely.",
        "targets": report,
    });
    let root = repo_root().join("dev").join("tmp").join("tf_harness");
    std::fs::create_dir_all(&root).unwrap();
    std::fs::write(
        root.join("destruction_floor.json"),
        serde_json::to_string_pretty(&out).unwrap(),
    )
    .unwrap();
    println!("wrote {}", root.join("destruction_floor.json").display());
}

// ── audition material: what the gate is actually judged on ──────────────────

/// A saw bass at 55 Hz (A1). Deterministic, band-limited enough to be honest.
fn sig_saw_bass(n: usize) -> Vec<f32> {
    let f0 = 55.0;
    (0..n)
        .map(|i| {
            let t = i as f64 / SR;
            let mut s = 0.0;
            let mut k = 1.0;
            while k * f0 < SR * 0.45 {
                s += (TAU * k * f0 * t).sin() / k;
                k += 1.0;
            }
            (s * 0.18) as f32
        })
        .collect()
}

/// A drum loop: kick on the beat, snare-ish noise burst on the off-beat.
fn sig_drums(n: usize) -> Vec<f32> {
    let mut rng = 0x9E37_79B9_7F4A_7C15u64;
    let beat = (SR * 0.5) as usize; // 120 bpm
    (0..n)
        .map(|i| {
            let p = i % beat;
            let t = p as f64 / SR;
            rng = rng.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            let noise = ((rng >> 40) as f64 / (1u64 << 23) as f64) - 1.0;
            let kick = if (i / beat) % 2 == 0 {
                (TAU * 58.0 * t).sin() * (-t * 26.0).exp() * 0.6
            } else {
                0.0
            };
            let snare = if (i / beat) % 2 == 1 {
                noise * (-t * 42.0).exp() * 0.35 + (TAU * 190.0 * t).sin() * (-t * 30.0).exp() * 0.15
            } else {
                0.0
            };
            ((kick + snare) * 0.5) as f32
        })
        .collect()
}

/// Broadband: the pink-ish noise already used everywhere else.
fn sig_broadband(n: usize) -> Vec<f32> {
    dry_signal(n)
}

fn rms_of(x: &[f32]) -> f64 {
    (x.iter().map(|&v| (v as f64) * (v as f64)).sum::<f64>() / x.len().max(1) as f64).sqrt()
}

/// Render a packed body at a STATIC (m,q). BODY SOLO: the owned Cascade only.
/// No AGC, no drive, no boost, NO normalization — absolute values preserved.
fn render_static(pc: &PackedCorners, m: f64, q: f64, dry: &[f32]) -> Vec<f32> {
    let rows = pc.interpolate_biquad(m as f32, q as f32);
    let mut c = Cascade::new();
    c.snap_targets(&rows);
    let mut buf = dry.to_vec();
    c.process_block_mono(&mut buf);
    buf
}

fn mouth_authored_table() -> serde_json::Value {
    let lanes: Vec<_> = (0..NUM_STAGES)
        .map(|lane| {
            let corners: Vec<_> = (0..4)
                .map(|ci| {
                    let g = MOUTH_CORNERS[ci][lane];
                    let scale = if lane == 0 {
                        10.0f64.powf(MOUTH_GAIN_DB[ci] / 20.0)
                    } else {
                        1.0
                    };
                    let identity = (g.pole_hz - g.zero_hz).abs() < 1e-12
                        && (g.pole_r - g.zero_r).abs() < 1e-12
                        && (scale - 1.0).abs() < 1e-12;
                    serde_json::json!({
                        "corner": CORNER_LABELS[ci],
                        "pole": {"kind":"Conjugate", "hz":g.pole_hz, "r":g.pole_r},
                        "zero": {"kind":"Conjugate", "hz":g.zero_hz, "r":g.zero_r},
                        "scale_b0": scale,
                        "state": if identity { "IDENTITY" } else { "ACTIVE" },
                        "evidence_provenance": "AUTHORED / BRANCH-INSPIRED",
                    })
                })
                .collect();
            serde_json::json!({"authored_lane":lane, "role":MOUTH_ROLES[lane], "corners":corners})
        })
        .collect();
    serde_json::json!({
        "correspondence": "AUTHORED_TRAJECTORY prior; never claimed RECOVERED from endpoint responses",
        "scale_policy": "the complete total gain is carried by authored lane 0; all other source SCALE values are exactly 1",
        "lanes": lanes,
    })
}

fn mouth_packed_lane_evidence(root: &Path, pc: &PackedCorners) -> serde_json::Value {
    let freqs = log_frequency_grid(F_LO, F_HI, 720);
    let states = [
        ("M000_Q000", 0.0, 0.0),
        ("M100_Q000", 1.0, 0.0),
        ("M000_Q100", 0.0, 1.0),
        ("M100_Q100", 1.0, 1.0),
        ("M050_Q050", 0.5, 0.5),
    ];
    let dir = root.join("plots").join("lane_ablation");
    std::fs::create_dir_all(&dir).unwrap();
    let mut plot_paths = Vec::new();
    for lane in 0..NUM_STAGES {
        for &(label, m, q) in &states {
            let rows = pc.interpolate_biquad(m as f32, q as f32);
            let kept: Vec<_> = rows
                .iter()
                .enumerate()
                .filter_map(|(i, r)| (i != lane).then_some(*r))
                .collect();
            let total: Vec<_> = freqs
                .iter()
                .map(|&f| cdb(biquad_cascade_complex(&rows, f, SR)))
                .collect();
            let isolated: Vec<_> = freqs
                .iter()
                .map(|&f| cdb(biquad_stage_complex(&rows[lane], f, SR)))
                .collect();
            let without: Vec<_> = freqs
                .iter()
                .map(|&f| cdb(rows_complex(&kept, f)))
                .collect();
            let svg = svg_response(
                &format!("packed runtime lane {lane} ablation — {label}"),
                &freqs,
                &[
                    ("full cascade", "#30c0e0", total),
                    ("without lane", "#e0b030", without),
                    ("isolated lane", "#e06060", isolated),
                ],
            );
            let rel = format!("plots/lane_ablation/lane{lane}_{label}.svg");
            std::fs::write(root.join(&rel), svg).unwrap();
            plot_paths.push(rel);
        }
    }

    let mut trajectories = Vec::new();
    for lane in 0..NUM_STAGES {
        let mut samples = Vec::new();
        for mi in 0..=8 {
            for qi in 0..=8 {
                let (m, q) = (mi as f32 / 8.0, qi as f32 / 8.0);
                let rows = pc.interpolate_biquad(m, q);
                let r = rows[lane];
                let pole = classify_pair(r[3], r[4]);
                let zero = if r[0].abs() > 1e-18 {
                    classify_pair(r[1] / r[0], r[2] / r[0])
                } else {
                    RootPair::Degenerate
                };
                samples.push(serde_json::json!({
                    "morph":m, "q":q,
                    "pole":format!("{:?}", pole),
                    "zero":format!("{:?}", zero),
                    "scale_b0":r[0],
                }));
            }
        }
        trajectories.push(serde_json::json!({"packed_lane":lane,"samples":samples}));
    }
    serde_json::json!({
        "authority":"all plots and trajectory samples use packed/runtime-decoded coefficients",
        "ablation_plots":plot_paths,
        "sampled_trajectories_9x9":trajectories,
    })
}

fn cmd_mouth() {
    let root = repo_root().join("dev").join("tmp").join("branching_mouth");
    std::fs::create_dir_all(root.join("audio")).unwrap();
    let t = BranchingMouth;
    println!("\n=== BRANCHING MOUTH — one product candidate ===");
    println!("{}\n", Target::describe(&t));

    // ── 1. PRE-CHECK: will six stages even hold the branch antiresonances? ──
    let (floor_best, fm, fq, _pts) = floor_over_surface(&t, 2 * NUM_STAGES);
    let fl0 = destruction_floor(&t, fm, fq, 2 * NUM_STAGES);
    println!(
        "pre-check (Hankel floor): strongest lower bound {floor_best:.3e} at morph {fm:.2} q {fq:.2}"
    );
    println!("   {}", &fl0.status[..fl0.status.len().min(72)]);

    // ── 2. COMPILE the independent continuous source into TRENCH ──
    let train = sample_surface(&t, OBJ_MQ);
    let held = held_out_surface(&t);
    let t0 = std::time::Instant::now();
    let pc = solver_structured(&train, 0, 140);
    let secs = t0.elapsed().as_secs_f64();
    let body = pc.to_rom_bytes();
    std::fs::write(root.join("branching_mouth.body240"), body).unwrap();
    std::fs::write(
        root.join("branching_mouth.cart.json"),
        serde_json::to_string_pretty(&cartridge_json(&pc, "branching_mouth")).unwrap(),
    )
    .unwrap();
    let rh = residual(&pc, &held);
    let rc = residual(&pc, &corner_only_surface(&t));
    let (linf, linf_state, linf_hz) = linf_additive_error(&pc, &held);
    let legal = legality(&body, &pc, "branching_mouth");
    let overlay_plots = plot_states(
        &root,
        &pc,
        &t,
        &log_frequency_grid(F_LO, F_HI, 720),
        &[
            ("M000_Q000", 0.0, 0.0),
            ("M100_Q000", 1.0, 0.0),
            ("M000_Q100", 0.0, 1.0),
            ("M100_Q100", 1.0, 1.0),
            ("M025_Q075_HELD", 0.25, 0.75),
            ("M050_Q050_HELD", 0.5, 0.5),
            ("M075_Q025_HELD", 0.75, 0.25),
        ],
    );
    let packed_lane_evidence = mouth_packed_lane_evidence(&root, &pc);
    println!("\ncompile: {secs:.1}s");
    println!(
        "   held-out vs authored total H_target: median {:.3} dB | p90 {:.3} | phase {:.2} deg",
        rh.median_db, rh.p90_db, rh.phase_rms_deg
    );
    println!("   additive H-inf error {linf:.4e} at {linf_state} {linf_hz:.0} Hz (bound norm)");
    println!(
        "   legal {} | unstable {} | nonfinite {} | wrap {}",
        legal["legal"], legal["sampled_certification"]["unstable_rows"],
        legal["sampled_certification"]["nonfinite_rows"], legal["packed_interp_wrap_hazard"]
    );

    // ── 2b. TOTAL-response gain audit: source and compiled, same dry signal. ──
    {
        let probe = sig_broadband((0.5 * SR) as usize);
        let dry_r = rms_of(&probe);
        println!("\n   source-vs-compile level (RMS re dry, broadband):");
        let mut worst_gap = 0.0f64;
        for &(m, q) in &[(0.0f64, 0.0f64), (0.0, 1.0), (0.5, 1.0), (1.0, 1.0)] {
            let src = render_rows(&t.rows_at(m, q), &probe);
            let cmp = render_static(&pc, m, q, &probe);
            let (sd, cd) = (
                20.0 * (rms_of(&src) / dry_r).log10(),
                20.0 * (rms_of(&cmp) / dry_r).log10(),
            );
            worst_gap = worst_gap.max((cd - sd).abs());
            println!("      m{m:.1} q{q:.1}   SOURCE {sd:+6.1} dB   COMPILED {cd:+6.1} dB   gap {:+6.1}", cd - sd);
        }
        println!("      worst source/compile level gap {worst_gap:.1} dB");
    }

    // ── 3. Did the BRANCH ZEROS survive packing? The whole point of Q. ──
    let grid = log_frequency_grid(200.0, 8000.0, 1400);
    let mut branch_report = Vec::new();
    // WHAT Q CARVES. Peak-to-trough inside a band is the WRONG measure: it reads
    // whichever formant is passing through (MEASURED: it reported the nasal notch
    // "16.5 dB deep at Q0" when Q0 has no notch at all — it was reading F2).
    // The branch's real signature is the DIFFERENCE the coupling makes:
    // dB(Q=0) − dB(Q=1) at each frequency. That is what Q owns, and nothing else.
    for &mm in &[0.0f64, 0.5, 1.0] {
        let carve = |lo: f64, hi: f64| -> (f64, f64, f64) {
            let r0 = pc.interpolate_biquad(mm as f32, 0.0);
            let r1 = pc.interpolate_biquad(mm as f32, 1.0);
            let mut best_hz = 0.0;
            let mut cut = f64::NEG_INFINITY; // deepest carve (Q1 below Q0)
            let mut boost = f64::NEG_INFINITY; // tallest companion peak
            for &f in grid.iter().filter(|&&f| f >= lo && f <= hi) {
                let d = cdb(biquad_cascade_complex(&r0, f, SR)) - cdb(biquad_cascade_complex(&r1, f, SR));
                if d > cut {
                    cut = d;
                    best_hz = f;
                }
                if -d > boost {
                    boost = -d;
                }
            }
            (best_hz, cut, boost)
        };
        let (nz_hz, nz_cut, nz_boost) = carve(450.0, 1400.0); // nasal branch region
        let (lz_hz, lz_cut, lz_boost) = carve(1700.0, 3600.0); // lateral branch region
        println!(
            "   morph {mm:.1}: Q carves {nz_cut:.1} dB @ {nz_hz:.0} Hz (nasal, companion peak \
             +{nz_boost:.1}) | {lz_cut:.1} dB @ {lz_hz:.0} Hz (lateral, +{lz_boost:.1})"
        );
        branch_report.push(serde_json::json!({
            "morph": mm,
            "metric": "dB(Q=0) - dB(Q=1): what the branch coupling actually carves",
            "nasal_cut_db": nz_cut, "nasal_cut_hz": nz_hz, "nasal_companion_peak_db": nz_boost,
            "lateral_cut_db": lz_cut, "lateral_cut_hz": lz_hz, "lateral_companion_peak_db": lz_boost,
            "gate": "each intended cut 8..15 dB and at least one restrained 0..6 dB companion boost",
            "q_useful_here": (8.0..=15.0).contains(&nz_cut)
                && (8.0..=15.0).contains(&lz_cut)
                && ((0.0..=6.0).contains(&nz_boost) || (0.0..=6.0).contains(&lz_boost)),
        }));
    }

    // ── 4. AUDITION — the actual gate. Raw first (no normalization). ──
    let n = (2.5 * SR) as usize;
    let mats: [(&str, Vec<f32>); 3] = [
        ("sawbass", sig_saw_bass(n)),
        ("drums", sig_drums(n)),
        ("broadband", sig_broadband(n)),
    ];
    let talker = std::fs::read("plugin/presets/bodies/Talker.body240")
        .ok()
        .and_then(|b| PackedCorners::from_body_bytes(&b).ok());
    let vowl = std::fs::read("filters/bodies/VOWL_iy_to_aa.body240")
        .ok()
        .and_then(|b| PackedCorners::from_body_bytes(&b).ok());

    let poses = [
        ("M000_Q000", 0.0, 0.0), ("M050_Q000", 0.5, 0.0), ("M100_Q000", 1.0, 0.0),
        ("M000_Q100", 0.0, 1.0), ("M050_Q100", 0.5, 1.0), ("M100_Q100", 1.0, 1.0),
        ("M025_Q050", 0.25, 0.5), ("M075_Q050", 0.75, 0.5),
    ];
    let mut level_rows = Vec::new();
    let mut worst_clip = 0usize;
    let mut lvl_min = f64::INFINITY;
    let mut lvl_max = f64::NEG_INFINITY;
    for (mat, dry) in &mats {
        let dry_rms = rms_of(dry);
        for (label, m, q) in &poses {
            let wet = render_static(&pc, *m, *q, dry);
            let (pk, rms, clip) = stats(&wet);
            worst_clip += clip;
            let rel = 20.0 * (rms / dry_rms.max(1e-12)).log10();
            lvl_min = lvl_min.min(rel);
            lvl_max = lvl_max.max(rel);
            wav_write(&root.join("audio").join(format!("RAW_{mat}_{label}.wav")), &wet, SR as u32);
            level_rows.push(serde_json::json!({
                "material": mat, "pose": label, "peak": pk, "rms": rms,
                "rms_rel_dry_db": rel, "clip_samples": clip,
            }));
        }
        // the morph journey, eyes closed
        let sweep = render_sweep(&pc, dry, (0.0, 0.35), (1.0, 0.35));
        wav_write(&root.join("audio").join(format!("RAW_{mat}_MORPH_SWEEP.wav")), &sweep, SR as u32);
        let sweep_q = render_sweep(&pc, dry, (0.5, 0.0), (0.5, 1.0));
        wav_write(&root.join("audio").join(format!("RAW_{mat}_Q_SWEEP.wav")), &sweep_q, SR as u32);
        let diagonal = render_sweep(&pc, dry, (0.0, 0.0), (1.0, 1.0));
        wav_write(
            &root.join("audio").join(format!("RAW_{mat}_DIAGONAL_SWEEP.wav")),
            &diagonal,
            SR as u32,
        );
    }
    println!(
        "\naudition (RAW, no normalization): clipped samples {worst_clip} | RMS vs dry spans \
         {lvl_min:+.1} .. {lvl_max:+.1} dB (jump {:.1} dB)",
        lvl_max - lvl_min
    );

    // ── 5. BLIND A/B — one calibration gain per reference body, then fixed. ──
    // Calibration is deterministic broadband at the declared neutral pose
    // M050_Q000.  The gain is never recomputed per material, pose, or render.
    let mut ab = Vec::new();
    let calibration = sig_broadband(n);
    let cal_mouth = render_static(&pc, 0.5, 0.0, &calibration);
    let mut fixed_gains = Vec::new();
    for (name, other) in [("Talker", &talker), ("VOWL_iy_to_aa", &vowl)] {
        let Some(o) = other else { continue };
        let cal_ref = render_static(o, 0.5, 0.0, &calibration);
        let g = (rms_of(&cal_mouth) / rms_of(&cal_ref).max(1e-12)) as f32;
        fixed_gains.push(serde_json::json!({
            "body":name,
            "gain_db":20.0 * (g as f64).log10(),
            "calibration_material":"deterministic broadband",
            "calibration_pose":"M050_Q000",
        }));
        for (mat, dry) in &mats {
            for (label, m, q) in [("M000_Q050", 0.0f64, 0.5), ("M100_Q050", 1.0f64, 0.5)] {
                let a = render_static(&pc, m, q, dry);
                let b = render_static(o, m, q, dry);
                let bm: Vec<f32> = b.iter().map(|&v| v * g).collect();
                wav_write(&root.join("audio").join(format!("AB_{mat}_{label}_A_mouth.wav")), &a, SR as u32);
                wav_write(&root.join("audio").join(format!("AB_{mat}_{label}_B_{name}.wav")), &bm, SR as u32);
                ab.push(serde_json::json!({
                    "material": mat, "pose": label, "against": name,
                    "fixed_calibration_gain_applied_to_B_db": 20.0 * (g as f64).log10(),
                }));
            }
        }
    }

    let compile_pass = rh.median_db <= ACC_MEDIAN_DB
        && rh.p90_db <= ACC_P90_DB
        && rh.phase_rms_deg <= ACC_PHASE_DEG;
    let branch_pass = branch_report
        .iter()
        .all(|r| r["q_useful_here"].as_bool().unwrap_or(false));
    let raw_pass = worst_clip == 0;
    let cart_bytes = std::fs::read(root.join("branching_mouth.cart.json")).unwrap();
    let report = serde_json::json!({
        "schema": "branching-mouth-candidate-v2",
        "verdict": "KILL",
        "verdict_basis": {
            "packed_compile_gate_pass":compile_pass,
            "branch_feature_gate_pass":branch_pass,
            "raw_audio_gate_pass":raw_pass,
            "blind_perceptual_gate":"UNKNOWN — deterministic blind files are prepared, but no human audition result exists",
            "precise_failure":"The packed body is legal and clean, but the structured compiler does not retain the authored continuous surface within the fixed residual gates, and Q produces broad attenuation without the intended restrained positive companion resonance. The required perceptual comparison is also unjudged."
        },
        "product_intent": "Make basses, synths and drums sound as if they are SPEAKING. \
                           Morph = what it becomes (dark/back /a/ -> bright/front /i/). \
                           Q = how strongly it behaves (clean oral -> nasal/lateral branch).",
        "not_this": "NOT a physical or anatomical model, NOT a recovered correspondence, and NOT a \
                     proof that six biquads are optimal. This is one direct AUTHORED, \
                     BRANCH-INSPIRED product candidate.",
        "source_model": Target::describe(&t),
        "source_boundary": "continuous complex H_target from bilinearly interpolated authored root \
                            geometry and dB gain anchors; independent of packed-u16 interpolation",
        "gain_policy": {
            "corner_order":CORNER_LABELS,
            "total_gain_anchor_db":MOUTH_GAIN_DB,
            "provenance":"AUTHORED after total-response inspection; fixed constants, never per-section or per-render normalisation",
            "source_distribution":"lane 0 carries the complete total gain; lanes 1..5 use SCALE=1",
        },
        "hankel_pre_check": {"strongest_lower_bound": floor_best, "at": {"morph": fm, "q": fq}, "status": fl0.status},
        "compile": {
            "solver": "existing structured response-recovery and packed refinement; oracle-free", "runtime_s": secs,
            "fixed_acceptance_thresholds":{"median_db":ACC_MEDIAN_DB,"p90_db":ACC_P90_DB,"phase_rms_deg":ACC_PHASE_DEG},
            "corners":rc.json(),
            "held_out":rh.json(),
            "additive_hinf_error": {"value": linf, "state": linf_state, "hz": linf_hz,
                                    "note": "the SAME norm as the Hankel bound"},
        },
        "legality": legal,
        "response_overlay_plots":overlay_plots,
        "branch_survival": branch_report,
        "audition": {
            "raw_no_normalization": "every RAW_*.wav is absolute: no normalization, no AGC, no drive, \
                                     no boost. These prove the level/clipping gate.",
            "clipped_samples_total": worst_clip,
            "rms_vs_dry_span_db": lvl_max - lvl_min,
            "levels": level_rows,
            "mandatory_sweeps":["MORPH_SWEEP","Q_SWEEP","DIAGONAL_SWEEP"],
            "blind_ab": ab,
            "blind_fixed_calibration_gains":fixed_gains,
            "blind_ab_note": "One gain per reference body is derived once from deterministic broadband \
                              at M050_Q000, then held fixed across every material and pose. No per-render \
                              match. RAW renders remain unity I/O.",
            "blind_result":"UNKNOWN — artifacts prepared; no human perceptual result fabricated",
        },
        "authored_lane_table":mouth_authored_table(),
        "packed_lane_registration": lane_table(&pc),
        "packed_lane_evidence":packed_lane_evidence,
        "body_sha256": sha256_hex(&body),
        "cartridge_sha256":sha256_hex(&cart_bytes),
    });
    std::fs::write(root.join("report.json"), serde_json::to_string_pretty(&report).unwrap()).unwrap();
    std::fs::write(
        root.join("KILL.md"),
        format!(
            "# KILL — Branching Mouth candidate\n\n\
             The body is legal, sampled-stable, finite, wrap-safe, and clips zero raw samples. \
             It is still killed: held-out packed-runtime error is {:.3} dB median / {:.3} dB p90 / \
             {:.3} dB p99 / {:.2}° phase RMS against fixed gates {:.1} / {:.1} / {:.1}°, and the \
             intended companion resonance did not survive as a positive restrained boost. The blind \
             packet exists, but a human perceptual verdict is UNKNOWN. Gates were not weakened.\n",
            rh.median_db, rh.p90_db, rh.p99_db, rh.phase_rms_deg,
            ACC_MEDIAN_DB, ACC_P90_DB, ACC_PHASE_DEG,
        ),
    )
    .unwrap();
    println!("\nbody:   {}", root.join("branching_mouth.body240").display());
    println!("audio:  {}", root.join("audio").display());
    println!("report: {}", root.join("report.json").display());
}

// ── self-checks: every mirror and every generic tool is pinned ──────────────

#[cfg(test)]
mod tests {
    use super::*;

    /// The ONLY piece of algebra in this bin that mirrors a private trench-core
    /// function. Pinned: for any packable (p,q), our classification must equal
    /// what the OWNED decoder reports after a real pack/unpack round trip.
    #[test]
    fn classify_pair_mirrors_stage_law() {
        let mut checked = 0usize;
        for pi in -20..=20 {
            for qi in 0..=20 {
                let (p, q) = (pi as f64 / 10.0, qi as f64 / 20.0);
                let mut s = [p, q, 0.0, 0.0, 1.0];
                clamp_stage(&mut s);
                let ours = classify_pair(s[0], s[1]);
                let theirs = geometry_from_words(stage_words(&s)).zero;
                match (ours, theirs) {
                    (RootPair::Degenerate, RootPair::Degenerate) => {}
                    (RootPair::Conjugate { .. }, RootPair::Conjugate { .. }) => {}
                    (RootPair::RealPair { .. }, RootPair::RealPair { .. }) => {}
                    // Quantization can move a pair across the discriminant
                    // boundary (disc ~ 0). Accept ONLY that documented case.
                    (a, b) => {
                        let disc = s[0] * s[0] - 4.0 * s[1];
                        assert!(
                            disc.abs() < 5e-3,
                            "classification diverged away from the disc~0 boundary: \
                             p={p} q={q} disc={disc} ours={a:?} owned={b:?}"
                        );
                    }
                }
                checked += 1;
            }
        }
        assert!(checked > 400);
    }

    /// Our N-row product must equal the owned 6-row cascade response exactly.
    #[test]
    fn rows_complex_matches_owner() {
        let pc = ExactSix::new().known;
        let rows = pc.interpolate_biquad(0.37, 0.61);
        for k in 0..64 {
            let f = 30.0 * (16_000.0f64 / 30.0).powf(k as f64 / 63.0);
            let a = rows_complex(&rows, f);
            let b = biquad_cascade_complex(&rows, f, SR);
            assert!(
                (a.0 - b.0).abs() < 1e-12 && (a.1 - b.1).abs() < 1e-12,
                "{f} Hz: {a:?} vs {b:?}"
            );
        }
    }

    /// A section-product target's `h` must equal its own rows' response — one
    /// response law, no second engine.
    #[test]
    fn target_h_is_its_rows() {
        let t = OverBudget::new();
        for &(m, q) in &[(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)] {
            let rows = t.rows(m, q).unwrap();
            assert_eq!(rows.len(), 10);
            for k in 0..32 {
                let f = 30.0 * (16_000.0f64 / 30.0).powf(k as f64 / 31.0);
                let a = t.h(f, m, q);
                let b = rows_complex(&rows, f);
                assert_eq!(a, b);
            }
        }
    }

    /// The identity init must pack to the EXACT identity biquad — "off" is a
    /// real runtime state, not an approximation.
    #[test]
    fn identity_init_packs_to_exact_identity() {
        let pc = params_to_packed(&init_identity());
        for ci in 0..4 {
            for si in 0..NUM_STAGES {
                let bq = trench_core::minifloat::stage_words_to_biquad(pc.words[ci][si]);
                assert_eq!(bq, [1.0, 0.0, 0.0, 0.0, 0.0], "corner {ci} lane {si}");
            }
        }
    }

    /// THE DECISIVE REGRESSION FIXTURE — the identifiability boundary itself.
    ///
    /// Pinned: 0.0 dB corner discriminability, ~25.82 dB interior. Permuting one
    /// corner's lanes leaves that corner's transfer function EXACTLY unchanged
    /// while moving the interior enormously. The corner transfer functions do not
    /// contain the registration — this is a mathematical boundary, not a hard
    /// problem. Everything else in the evidence-mode contract rests on it.
    #[test]
    fn identifiability_boundary_zero_db_corners_25db_interior() {
        let pa = Crossing::pairing_a();
        let pb = Crossing::pairing_b();
        let grid = log_frequency_grid(F_LO, F_HI, OBJ_F_BINS);
        let (corner_db, interior_db, worst) = discriminability(&pa, &pb, &grid);
        assert!(
            corner_db < 1e-9,
            "corners discriminated the registration ({corner_db} dB) — the permutation-invariance \
             premise of the whole evidence-mode contract has broken"
        );
        assert!(
            (interior_db - 25.82).abs() < 0.5,
            "interior discriminability drifted from the pinned 25.82 dB: {interior_db} dB \
             at morph {} q {} {:.0} Hz",
            worst.0,
            worst.1,
            worst.2
        );
    }

    /// CONTRACT: under ENDPOINT_ONLY evidence the harness must return AMBIGUOUS
    /// and must NEVER select a permutation. This is the rule that frequency
    /// sorting violates.
    #[test]
    fn endpoint_only_is_ambiguous_and_selects_nothing() {
        let pa = Crossing::pairing_a();
        let pb = Crossing::pairing_b();
        let grid = log_frequency_grid(F_LO, F_HI, OBJ_F_BINS);
        let r = endpoint_only_report(&pa, &pb, &grid);
        assert_eq!(r["verdict"], "AMBIGUOUS");
        assert!(
            r["selected_permutation"].is_null(),
            "ENDPOINT_ONLY selected a permutation — the contract forbids this"
        );
        assert_eq!(r["mode"], "ENDPOINT_ONLY");
        // the class must be reported and non-trivial
        assert_eq!(
            r["equivalence_class"]["distinct_interiors_upper_bound"],
            373_248_000u64
        );
        let changing = r["equivalence_class"]
            ["measured_single_corner_orderings_changing_the_interior"]
            .as_u64()
            .unwrap();
        assert!(
            changing > 100,
            "only {changing}/720 orderings moved the interior"
        );
    }

    /// CONTRACT: OBSERVED_SURFACE ranks against real interior observations, and
    /// REFUSES when the margin is insignificant. Ranking pairing A against
    /// itself-as-observations must pick A by a real margin; two identical
    /// candidates must be REFUSED.
    #[test]
    fn observed_surface_ranks_then_refuses_on_insignificant_margin() {
        let pa = Crossing::pairing_a();
        let pb = Crossing::pairing_b();
        let t = Crossing::new(); // authors pairing A, so its surface observes A
        let surf = sample_surface(&t, 5);
        let grid = log_frequency_grid(F_LO, F_HI, OBJ_F_BINS);

        let r = observed_surface_report(&[("pairing_a", &pa), ("pairing_b", &pb)], &surf, &grid);
        assert_eq!(r["verdict"], "RANKED");
        assert_eq!(
            r["winner"], "pairing_a",
            "interior observations of A must rank A first"
        );

        // identical candidates cannot be separated -> must REFUSE, not guess
        let r2 = observed_surface_report(&[("one", &pa), ("same", &pa)], &surf, &grid);
        assert!(r2["verdict"].as_str().unwrap().starts_with("REFUSED"));
        assert!(r2["winner"].is_null(), "REFUSED must name no winner");
    }

    /// CONTRACT: AUTHORED_TRAJECTORY carries the source model's identities as a
    /// prior labelled AUTHORED, and must never claim recovery.
    #[test]
    fn authored_trajectory_is_labelled_authored_never_recovered() {
        let t = Crossing::new();
        assert_eq!(Target::evidence_mode(&t), EvidenceMode::AuthoredTrajectory);
        let pa = Crossing::pairing_a();
        let pb = Crossing::pairing_b();
        let grid = log_frequency_grid(F_LO, F_HI, OBJ_F_BINS);
        let r = authored_trajectory_report(&t, &pa, &pb, &grid);
        assert_eq!(r["provenance"], "AUTHORED");
        assert_eq!(r["mode"], "AUTHORED_TRAJECTORY");
        let blob = r.to_string();
        assert!(
            !blob.contains("RECOVERED") || blob.contains("never RECOVERED"),
            "AUTHORED_TRAJECTORY must never claim recovery"
        );
        // the identities must actually be carried, and must track the crossing
        let at_m0 = t.authored_lanes(0.0, 0.0).unwrap();
        let at_m1 = t.authored_lanes(1.0, 0.0).unwrap();
        assert!(
            at_m0[0].contains("600") && at_m1[0].contains("2600"),
            "actor A must rise"
        );
        assert!(
            at_m0[1].contains("2400") && at_m1[1].contains("560"),
            "actor B must fall"
        );
    }

    /// The exactly-representable fixture must have a ZERO-error solution: the
    /// known body itself. If this fails, "exactly representable" is a lie.
    #[test]
    fn exact6_truth_has_zero_objective_error() {
        let t = ExactSix::new();
        let surf = sample_surface(&t, 5);
        let mut sq = 0.0f64;
        let mut n = 0usize;
        for st in &surf.states {
            let rows = t.known.interpolate_biquad(st.m as f32, st.q as f32);
            for (i, &f) in surf.freqs.iter().enumerate() {
                let d = cdb(biquad_cascade_complex(&rows, f, SR)) - cdb(st.h[i]);
                sq += d * d;
                n += 1;
            }
        }
        assert!(
            (sq / n as f64).sqrt() < 1e-12,
            "truth is not exact: {}",
            (sq / n as f64).sqrt()
        );
    }

    /// PINNED FINDING: the all-identity init is a permutation-symmetry trap.
    /// Every lane is numerically identical, so the objective is symmetric under
    /// lane permutation and coordinate search cannot differentiate the lanes. It
    /// stalls in that basin at an objective that a 13x larger iteration budget
    /// barely moves (MEASURED: 90 -> 22.01, 300 -> 21.97, 1200 -> 21.88 on
    /// exact6). The target-agnostic spread init escapes it. This test pins the
    /// mechanism so H13 can never be quietly reverted.
    #[test]
    fn blind_identity_init_is_a_symmetry_trap() {
        let ident = init_identity();
        // all six lanes of a corner are numerically identical -> symmetric
        for si in 1..NUM_STAGES {
            assert_eq!(
                ident[0..PPS],
                ident[si * PPS..si * PPS + PPS],
                "identity init lane {si} differs — the symmetry premise changed"
            );
        }
        // the spread init breaks that symmetry
        let spread = init_spread();
        for si in 1..NUM_STAGES {
            assert_ne!(
                spread[0..PPS],
                spread[si * PPS..si * PPS + PPS],
                "spread init lane {si} is NOT distinct — the symmetry trap is back"
            );
        }
        // and it must still be target-agnostic: identical for every fixture
        assert_eq!(init_spread(), spread, "spread init is not deterministic");
    }

    /// The wrap barrier must actually fire on a body that wraps, and stay silent
    /// on one that does not. Without it the optimizer emits illegal bodies.
    #[test]
    fn wrap_penalty_fires_only_on_real_hazard() {
        let clean = params_to_packed(&init_spread());
        assert_eq!(wrap_penalty(&clean), 0.0, "spread init should not wrap");
        assert!(!wrap_hazard(&clean).0);
        let mut bad = clean.clone();
        bad.words[0][0][0] = 0x0000;
        bad.words[1][0][0] = 0xFFFF; // 65535 delta across the morph lerp
        assert!(
            wrap_penalty(&bad) > 0.0,
            "wrap barrier missed a 65535 delta"
        );
        assert!(wrap_hazard(&bad).0);
    }

    /// PINNED: the detector must find resonances at frequencies we PUT there.
    /// Guards the exact bug the naive immediate-neighbour prominence had — it
    /// found 1 of 5 known peaks because it measured sharpness-vs-grid-spacing.
    #[test]
    fn prominence_finds_known_resonances() {
        let want = [220.0f64, 900.0, 3000.0, 9000.0];
        let rows: Vec<[f64; NUM_COEFFS]> = want
            .iter()
            .map(|&f| section_biquad(TYPE_PEAK, f, 4.0, 12.0))
            .collect();
        let freqs = log_frequency_grid(F_LO, F_HI, OBJ_F_BINS);
        let db: Vec<f64> = freqs.iter().map(|&f| cdb(rows_complex(&rows, f))).collect();
        let peaks: Vec<f64> = features(&db, &freqs)
            .iter()
            .filter(|f| f.peak)
            .map(|f| f.hz)
            .collect();
        assert_eq!(
            peaks.len(),
            want.len(),
            "found peaks at {peaks:?}, planted {want:?}"
        );
        for (got, exp) in peaks.iter().zip(&want) {
            assert!(
                (got / exp).log2().abs() < FEATURE_TOL_OCT,
                "peak {got:.0} Hz is not within tolerance of planted {exp:.0} Hz"
            );
        }
    }

    /// Fixture 3 must have measurable features, or feature survival on it is
    /// meaningless. (The first build used bare all-pole lanes and reported ZERO
    /// features at every state — a stack of resonators is a monotone lowpass.)
    #[test]
    fn crossing_fixture_has_detectable_features() {
        let t = Crossing::new();
        let freqs = log_frequency_grid(F_LO, F_HI, OBJ_F_BINS);
        for &(m, q) in &[(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)] {
            let db: Vec<f64> = freqs.iter().map(|&f| cdb(t.h(f, m, q))).collect();
            let peaks = features(&db, &freqs).iter().filter(|f| f.peak).count();
            assert!(peaks >= 3, "crossing at ({m},{q}) has only {peaks} peaks");
        }
    }

    /// GENUINELY ENDPOINT-ONLY OPTIMIZATION TEST.
    ///
    /// Optimize against the FOUR CORNERS ONLY — no interior samples anywhere.
    /// Under that evidence a unique correspondence cannot be claimed, and the
    /// test proves why operationally: pairing A and pairing B score IDENTICALLY
    /// on corner-only evidence, so no objective built from it can prefer either.
    /// Any solver that reports one is reporting an artifact of its own
    /// initialization, not a measurement.
    ///
    /// (This REPLACES an earlier, wrong invariant that required an
    /// INTERIOR-trained solver to remain unresolved. That conflated a solver
    /// deficiency with the identifiability boundary — an interior-trained solver
    /// is expected to resolve. The boundary is about endpoint evidence only.)
    #[test]
    fn endpoint_only_optimization_never_claims_unique_correspondence() {
        let t = Crossing::new();
        // evidence = the four corners and NOTHING else
        let corners_only = corner_only_surface(&t);
        assert_eq!(
            corners_only.states.len(),
            4,
            "this must be endpoint-only evidence"
        );

        let pa = Crossing::pairing_a();
        let pb = Crossing::pairing_b();

        // Both pairings are EXACTLY equally consistent with endpoint evidence.
        let ea = surface_objective(&pa, &corners_only);
        let eb = surface_objective(&pb, &corners_only);
        assert!(
            (ea - eb).abs() < 1e-9,
            "endpoint-only objective separated the pairings ({ea} vs {eb}) — it must not: the \
             corners are permutation-invariant"
        );

        // Therefore optimizing on endpoint-only evidence cannot single one out:
        // whichever it lands nearer is decided by its init, not by the data.
        let grid = log_frequency_grid(F_LO, F_HI, OBJ_F_BINS);
        let r = endpoint_only_report(&pa, &pb, &grid);
        assert_eq!(r["verdict"], "AMBIGUOUS");
        assert!(
            r["selected_permutation"].is_null(),
            "endpoint-only evidence selected a permutation — forbidden"
        );

        // And a real optimizer run on this evidence must not be reported as
        // having identified the registration.
        let run = fit("spread_blind", init_spread(), &corners_only, 40);
        let fitted = params_to_packed(&run.params);
        let da = interior_rms(&fitted, &pa, &grid);
        let db_ = interior_rms(&fitted, &pb, &grid);
        let _ = (da, db_); // recorded, never used to claim a correspondence
        assert_eq!(
            endpoint_only_report(&pa, &pb, &grid)["verdict"],
            "AMBIGUOUS",
            "a corner-only fit must not upgrade the endpoint verdict"
        );
    }

    /// The interior evidence that the solver is EXPECTED to exploit really is
    /// present and sufficient: ranking the pairings against interior
    /// observations separates them cleanly. Any interior-trained solver that
    /// fails to resolve is failing to use available evidence.
    #[test]
    fn interior_evidence_is_sufficient_to_resolve() {
        let t = Crossing::new();
        let surf = sample_surface(&t, OBJ_MQ); // the SAME grid the solver trains on
        let pa = Crossing::pairing_a();
        let pb = Crossing::pairing_b();
        let ea = surface_objective(&pa, &surf);
        let eb = surface_objective(&pb, &surf);
        assert!(
            eb - ea > 1.0,
            "the training grid does NOT separate the pairings (A {ea}, B {eb}) — then a solver \
             cannot be blamed for failing to resolve"
        );
    }

    /// The structured solver's foundation: from a corner spectrum ALONE, does
    /// rational recovery reproduce that corner's transfer function? If this
    /// fails, solver A is built on sand and its benchmark means nothing.
    #[test]
    fn rational_recovery_reproduces_the_corner_spectrum() {
        for (name, t) in [
            ("exact6", Box::new(ExactSix::new()) as Box<dyn Target>),
            ("qual_notchy", Box::new(qual_notchy())),
            ("qual_realroot", Box::new(qual_realroot())),
        ] {
            let freqs = log_frequency_grid(F_LO, F_HI, OBJ_F_BINS);
            for (ci, &(m, q)) in CORNER_MQ.iter().enumerate() {
                let h: Vec<Cf> = freqs.iter().map(|&f| t.h(f, m, q)).collect();
                let cm = recover_corner(&freqs, &h)
                    .unwrap_or_else(|| panic!("{name} corner {ci}: recovery returned None"));
                // rebuild the corner from recovered roots + gain and compare dB
                let rows: Vec<[f64; NUM_COEFFS]> = (0..NUM_STAGES)
                    .map(|i| {
                        let (zp, zq) = cm.zeros[i];
                        let (pp, pq) = cm.poles[i];
                        [1.0, zp, zq, pp, pq]
                    })
                    .collect();
                let mut errs: Vec<f64> = freqs
                    .iter()
                    .enumerate()
                    .map(|(k, &f)| {
                        let got = cdb(rows_complex(&rows, f)) + 20.0 * cm.gain.log10();
                        (got - cdb(h[k])).abs()
                    })
                    .collect();
                errs.sort_by(|a, b| a.partial_cmp(b).unwrap());
                let med = errs[errs.len() / 2];
                let p90 = errs[errs.len() * 9 / 10];
                // The data is NOISELESS and EXACTLY representable, so recovery
                // should be near machine precision. An earlier 0.5 dB threshold
                // was loose enough to PASS while hiding a ~1.7 dB corner failure
                // downstream — a threshold that cannot fail is not a test.
                assert!(
                    med < 1e-3 && p90 < 1e-2,
                    "{name} corner {ci}: recovered spectrum median {med:.3e} dB / p90 {p90:.3e} dB \
                     — recovery is not reproducing the corner it was handed, on noiseless \
                     exactly-representable data"
                );
            }
        }
    }

    /// DIAGNOSTIC (prints; asserts only the mechanism, not a quality bar).
    ///
    /// Recovery is response-exact, yet packed corners land ~0.24 dB off. This
    /// measures the quantity that actually gets ENCODED — the (p,q) quad
    /// coefficients — against the target's true decoded quads. Oracle knowledge
    /// is used HERE ONLY, for diagnosis; the solver never sees it.
    #[test]
    fn diagnose_recovered_quad_precision() {
        let t = ExactSix::new();
        let freqs = log_frequency_grid(F_LO, F_HI, OBJ_F_BINS);
        let h: Vec<Cf> = freqs.iter().map(|&f| t.h(f, 0.0, 0.0)).collect();
        let cm = recover_corner(&freqs, &h).expect("recovery");

        // TRUE quads of corner 0, straight from the target's own decoded rows.
        let rows = t.known.interpolate_biquad(0.0, 0.0);
        let mut true_poles: Vec<(f64, f64)> = rows.iter().map(|r| (r[3], r[4])).collect();
        let mut got_poles = cm.poles.clone();
        let key = |x: &(f64, f64)| x.0;
        true_poles.sort_by(|a, b| key(a).partial_cmp(&key(b)).unwrap());
        got_poles.sort_by(|a, b| key(a).partial_cmp(&key(b)).unwrap());

        println!("\n--- recovered vs TRUE pole quads (corner 0, exact6) ---");
        let mut worst = 0.0f64;
        for (g, tr) in got_poles.iter().zip(&true_poles) {
            let d = (g.0 - tr.0).abs().max((g.1 - tr.1).abs());
            worst = worst.max(d);
            println!(
                "  got (p {:+.9}, q {:+.9})   true (p {:+.9}, q {:+.9})   |d| {:.3e}",
                g.0, g.1, tr.0, tr.1, d
            );
        }
        // The minifloat grid step near a sharp pole's (p+1+q)/4 is ~1e-7, so a
        // (p,q) error above that lands on a DIFFERENT word.
        println!("  worst |d(p,q)| = {worst:.3e}   (minifloat landing step ~1e-7)");

        // zeros: b1/b0, b2/b0 from the target's own decoded rows
        let mut true_zeros: Vec<(f64, f64)> = rows
            .iter()
            .map(|r| {
                if r[0].abs() > 1e-12 {
                    (r[1] / r[0], r[2] / r[0])
                } else {
                    (0.0, 0.0)
                }
            })
            .collect();
        let mut got_zeros = cm.zeros.clone();
        true_zeros.sort_by(|a, b| key(a).partial_cmp(&key(b)).unwrap());
        got_zeros.sort_by(|a, b| key(a).partial_cmp(&key(b)).unwrap());
        println!("--- recovered vs TRUE zero quads ---");
        let mut zworst = 0.0f64;
        for (g, tr) in got_zeros.iter().zip(&true_zeros) {
            let d = (g.0 - tr.0).abs().max((g.1 - tr.1).abs());
            zworst = zworst.max(d);
            println!(
                "  got (p {:+.9}, q {:+.9})   true (p {:+.9}, q {:+.9})   |d| {:.3e}",
                g.0, g.1, tr.0, tr.1, d
            );
        }
        println!("  worst |d(zero p,q)| = {zworst:.3e}");

        // total gain: product of the target's true per-lane b0
        let true_k: f64 = rows.iter().map(|r| r[0]).product();
        println!("--- gain ---");
        println!(
            "  recovered K {:.9}   true prod(b0) {:.9}   ratio {:.6} dB",
            cm.gain,
            true_k,
            20.0 * (cm.gain / true_k).log10()
        );

        // and the decisive number: does the ASSEMBLED+PACKED corner reproduce it?
        let per_lane_scale = cm.gain.max(1e-12).powf(1.0 / NUM_STAGES as f64);
        let mut w = [[[0u16; NUM_COEFFS]; NUM_STAGES]; 4];
        for si in 0..NUM_STAGES {
            let (zp_, zq_) = cm.zeros[si];
            let (pp_, pq_) = cm.poles[si];
            let mut s = [zp_, zq_, pp_, pq_, per_lane_scale];
            clamp_stage(&mut s);
            for ci in 0..4 {
                w[ci][si] = stage_words(&s);
            }
        }
        let asm = PackedCorners { words: w };
        let mut errs: Vec<f64> = freqs
            .iter()
            .enumerate()
            .map(|(k, &f)| {
                let got = mag_at(&asm, 0.0, 0.0, f);
                (got - cdb(h[k])).abs()
            })
            .collect();
        errs.sort_by(|a, b| a.partial_cmp(b).unwrap());
        println!(
            "--- assembled+packed corner 0 error: median {:.4} dB  p90 {:.4}  max {:.4} ---",
            errs[errs.len() / 2],
            errs[errs.len() * 9 / 10],
            errs[errs.len() - 1]
        );
        assert!(worst.is_finite() && zworst.is_finite());
    }

    #[test]
    fn poly_roots_finds_planted_roots() {
        // (x-0.5)(x+0.3)(x^2+0.4x+0.29)  -> roots 0.5, -0.3, -0.2 +- 0.5i
        let a = [1.0f64, -0.5];
        let b = [1.0f64, 0.3];
        let c = [0.29f64, 0.4, 1.0];
        let mul = |p: &[f64], q: &[f64]| -> Vec<f64> {
            let mut r = vec![0.0; p.len() + q.len() - 1];
            for (i, &pi) in p.iter().enumerate() {
                for (j, &qj) in q.iter().enumerate() {
                    r[i + j] += pi * qj;
                }
            }
            r
        };
        // build in ascending powers: (-0.5 + x)(0.3 + x)(0.29 + 0.4x + x^2)
        let p1 = mul(&[-0.5, 1.0], &[0.3, 1.0]);
        let poly = mul(&p1, &c);
        let _ = (a, b);
        let roots = poly_roots(&poly);
        assert_eq!(roots.len(), 4);
        for want in [(0.5, 0.0), (-0.3, 0.0), (-0.2, 0.5), (-0.2, -0.5)] {
            let hit = roots.iter().any(|r| cabs(csub(*r, want)) < 1e-6);
            assert!(hit, "root {want:?} not found in {roots:?}");
        }
    }

    /// CONTRACT: ordinary qualification runs the structured solver ONLY. The
    /// evolutionary solver is REJECTED for routine use (0/12 vs 12/12) and must
    /// never execute by accident — it is reachable only via an explicit opt-in.
    #[test]
    fn routine_qualification_never_runs_the_rejected_solver() {
        assert_eq!(
            ROUTINE_APPROACHES,
            ["structured"],
            "routine qualification must run the structured solver ONLY"
        );
        assert!(
            !ROUTINE_APPROACHES.contains(&"evolutionary"),
            "the REJECTED evolutionary solver is in the routine path"
        );
        // the benchmark path still reaches it, so the negative result stays
        // reproducible rather than being deleted
        assert!(
            BENCHMARK_APPROACHES.contains(&"evolutionary"),
            "the evolutionary negative result must remain reproducible via the explicit benchmark"
        );
        assert!(BENCHMARK_APPROACHES.contains(&"structured"));
    }

    /// The quarantined implementation must still EXIST — quarantine, not deletion.
    #[test]
    fn evolutionary_implementation_is_retained_not_deleted() {
        let t = ExactSix::new();
        let surf = sample_surface(&t, 3);
        // one tiny run purely to prove the code path is alive and callable
        let pc = solver_evolutionary(&surf, 0, 1);
        assert_eq!(pc.to_rom_bytes().len(), 240);
    }

    /// Acceptance thresholds are the values declared BEFORE any solver ran.
    /// Retiring a failed benchmark must never move them.
    #[test]
    fn acceptance_thresholds_are_unchanged() {
        assert_eq!(ACC_MEDIAN_DB, 0.1);
        assert_eq!(ACC_P90_DB, 0.5);
        assert_eq!(ACC_PHASE_DEG, 2.0);
    }

    /// The floor instrument must be FALSIFIABLE. A target built from 5 pole
    /// pairs (10 poles) MUST certify at ~0 — and must be CONVERGED and CAPTURED,
    /// not merely small.
    #[test]
    fn floor_is_zero_for_a_representable_target() {
        for t in [
            Box::new(ExactSix::new()) as Box<dyn Target>,
            Box::new(qual_notchy()),
        ] {
            let fl = destruction_floor(&*t, 0.0, 0.0, 2 * NUM_STAGES);
            let rel = fl.sigma_k1 / fl.sigma[0].max(1e-300);
            println!(
                "{}: mode {} sigma1 {:.3e} sigma13 {:.3e} rel {:.2e} tail {:.2e} converged {}",
                t.name(), fl.mode.label(), fl.sigma[0], fl.sigma_k1, rel, fl.tail_energy_fraction, fl.converged
            );
            assert_eq!(fl.mode, FloorMode::CertifiedMarkovBound, "{}: must certify", t.name());
            assert!(fl.converged, "{}: must be converged+captured, status: {}", t.name(), fl.status);
            assert!(
                rel < 1e-6,
                "{}: sigma_13 is {rel:.3e} of sigma_1 on a target that FITS in 10 poles",
                t.name()
            );
        }
    }

    /// MANDATORY FAILURE FIXTURE 1 — the one that indicted the first build.
    ///
    /// An UNDECLARED pure delay z^-320: a finite section reaching only h[1..639]
    /// DOES now contain h[320], so it must see sigma ~= 1 and NOT report zero.
    /// The old L=160 build read h[1..319], returned 0, and printed "-301 dB, six
    /// destroys nothing" for a system 12 poles cannot touch at all.
    #[test]
    fn undeclared_pure_delay_is_not_reported_as_harmless() {
        let t = PureDelay { d: 320, declare: false };
        let fl = destruction_floor(&t, 0.0, 0.0, 2 * NUM_STAGES);
        println!(
            "undeclared z^-320: sigma1 {:.4e} sigma13 {:.4e} converged {} status {}",
            fl.sigma[0], fl.sigma_k1, fl.converged, fl.status
        );
        // The true Hankel singular values of a d-sample delay are 1 (x d).
        assert!(
            fl.sigma_k1 > 0.5,
            "sigma_13 = {:.3e} for an UNDECLARED 320-sample delay. The truth is 1: a pure delay of \
             320 samples is untouchable by 12 poles. Reporting ~0 here is the exact catastrophe \
             this fixture exists to prevent.",
            fl.sigma_k1
        );
        // And the naive short section must be provably vacuous, not trusted.
        let (short, _) = section_sigma_k1(&t.markov(0.0, 0.0, 8192).unwrap(), 160, 2 * NUM_STAGES);
        assert_eq!(
            short, 0.0,
            "the L=160 section is expected to be VACUOUS here (it never reaches h[320]); if this \
             changes, the fixture no longer pins the failure it was written for"
        );
    }

    /// MANDATORY FAILURE FIXTURE 2 — a DECLARED delay is removed, and ONLY that.
    /// z^-320 declared becomes the identity: genuinely order 0, floor 0.
    #[test]
    fn declared_pure_delay_is_removed_and_only_that() {
        let t = PureDelay { d: 320, declare: true };
        let fl = destruction_floor(&t, 0.0, 0.0, 2 * NUM_STAGES);
        assert_eq!(fl.declared_delay, 320);
        assert!(fl.converged, "declared delay must certify, status: {}", fl.status);
        assert!(
            fl.sigma_k1 < 1e-9,
            "after removing ONLY the declared 320-sample transport delay the system is the \
             identity, so sigma_13 must be 0; got {:.3e}",
            fl.sigma_k1
        );
    }

    /// MANDATORY FAILURE FIXTURE 3 — delay equal to the DFT period aliases to
    /// h[0] in the SAMPLED path. The estimate is therefore wrong, and the mode
    /// label must not dress it up as a bound.
    #[test]
    fn delay_equal_to_dft_period_aliases_and_is_only_an_estimate() {
        let t = PureDelay { d: 8192, declare: false };
        // sampled path: no exact Markov -> must be labelled ESTIMATE, never proven
        let est = destruction_floor(&NoisyMeasurement { eps: 1e-3 }, 0.0, 0.0, 2 * NUM_STAGES);
        assert_eq!(est.mode, FloorMode::SampledSpectrumEstimate);
        assert!(!est.lower_bound.is_finite(), "an estimate must expose NO certified bound");
        assert!(est.status.starts_with("ESTIMATED"));
        // and the aliasing itself: IDFT of z^-8192 at N=8192 folds to h[0]
        let h = impulse_from_spectrum(&t, 0.0, 0.0, 8192);
        assert!(
            h[0].abs() > 0.5,
            "z^-8192 must alias onto h[0] at N=8192 (got {:.3e}) — this is the aliasing failure the \
             SAMPLED_SPECTRUM_ESTIMATE label exists to disclose",
            h[0]
        );
    }

    /// MANDATORY FAILURE FIXTURE 4 — a slowly decaying pole leaves energy beyond
    /// the section's reach. The capture guard must REFUSE rather than certify a
    /// number computed from a section that does not contain the system.
    #[test]
    fn slow_pole_is_refused_not_silently_understated() {
        let t = SlowPole { r: 0.9995 };
        let fl = destruction_floor(&t, 0.0, 0.0, 2 * NUM_STAGES);
        println!(
            "slow pole r=0.9995: tail {:.3e} converged {} status {}",
            fl.tail_energy_fraction, fl.converged, fl.status
        );
        assert!(
            fl.tail_energy_fraction > 1e-9,
            "a pole at r=0.9995 must leave measurable energy beyond h[2L-1]; got tail {:.3e}",
            fl.tail_energy_fraction
        );
        // This target IS order 2, so the truth is sigma_13 = 0 — but the section
        // cannot SHOW that, because it does not contain the system. The honest
        // outcome is VACUOUS ("no conclusion"), never "six destroys nothing".
        assert!(
            !fl.informative,
            "a near-zero bound from a section that does not capture the system must be VACUOUS, \
             not informative; status: {}",
            fl.status
        );
        assert!(fl.status.starts_with("VACUOUS"), "status: {}", fl.status);
    }

    /// MANDATORY FAILURE FIXTURE 5 — a feature narrower than the SAMPLING GRID.
    ///
    /// CORRECTED FRAMING (my first version asserted the wrong thing and failed).
    /// A razor ZERO does not lengthen the impulse response — only poles do — so
    /// with h shorter than N the inverse DFT reconstructs it EXACTLY and nothing
    /// is missed. The narrow-feature failure is therefore NOT an IDFT failure.
    ///
    /// It is a SAMPLING failure, and it bites the fit: the harness's own 192-bin
    /// log grid steps straight over a 0.6 Hz null at 5 kHz, so every sampled
    /// H(f) the solver and the estimate ever see is blind to it. Nothing
    /// downstream can retain a feature the evidence never contained.
    #[test]
    fn narrow_feature_exposes_the_sampled_path() {
        let t = NarrowFeature;
        let grid = log_frequency_grid(F_LO, F_HI, OBJ_F_BINS);
        let on_grid_min = grid
            .iter()
            .map(|&f| cabs(t.h(f, 0.0, 0.0)))
            .fold(f64::INFINITY, f64::min);
        // the truth, swept densely through the null
        let dense_min = (0..40_000)
            .map(|k| {
                let f = 4990.0 + 20.0 * (k as f64 / 40_000.0);
                cabs(t.h(f, 0.0, 0.0))
            })
            .fold(f64::INFINITY, f64::min);
        println!(
            "narrow feature: min|H| seen by the {OBJ_F_BINS}-bin log grid = {on_grid_min:.4e}; \
             true min = {dense_min:.4e}  (grid step at 5 kHz ~ {:.1} Hz)",
            5000.0 * ((F_HI / F_LO).ln() / (OBJ_F_BINS - 1) as f64)
        );
        assert!(
            dense_min < 1e-3,
            "the fixture must actually contain a deep null; got {dense_min:.3e}"
        );
        // BAR: one decade (20 dB) of understatement = "the evidence does not
        // contain this feature". Chosen for interpretability, NOT to pass.
        // DISCLOSURE: my first bar was 1000x, an arbitrary guess, and it failed.
        // MEASURED here: grid min 1.06e-1 vs true 5.26e-4 — a 202x (46 dB)
        // understatement, which is what the physics predicts (a 164 Hz grid step
        // at 5 kHz against a 0.6 Hz null lands ~100 half-bandwidths off centre).
        // The demonstration was always decisive; only my threshold was wrong.
        assert!(
            on_grid_min > 10.0 * dense_min,
            "the sampling grid was expected to MISS the narrow null by >20 dB (grid min \
             {on_grid_min:.3e} vs true min {dense_min:.3e}). If the grid now sees it, this fixture \
             no longer pins the failure that ANY sampled-evidence claim is blind to features \
             between its own samples."
        );
    }

    /// Noisy/interval evidence may NEVER certify.
    #[test]
    fn noisy_measurement_cannot_certify() {
        let t = NoisyMeasurement { eps: 1e-3 };
        let fl = destruction_floor(&t, 0.0, 0.0, 2 * NUM_STAGES);
        assert_eq!(fl.mode, FloorMode::SampledSpectrumEstimate);
        assert!(fl.lower_bound.is_nan(), "noisy evidence produced a certified bound");
        assert!(fl.allowance.is_nan());
    }

    /// The exact Markov reader must agree with the OWNED response engine, or it
    /// is a second kernel telling a different story.
    #[test]
    fn exact_markov_matches_owned_response() {
        let t = ExactSix::new();
        let rows = t.rows(0.0, 0.0).unwrap();
        let n = 8192;
        let h = exact_markov(&rows, n);
        for &hz in &[80.0f64, 500.0, 2000.0, 7000.0, 15000.0] {
            // DFT of the Markov parameters at this frequency
            let w = TAU * hz / SR;
            let mut acc = (0.0f64, 0.0f64);
            for (k, &v) in h.iter().enumerate() {
                let a = -w * k as f64;
                acc = (acc.0 + v * a.cos(), acc.1 + v * a.sin());
            }
            let owned = rows_complex(&rows, hz);
            let d = cabs(csub(acc, owned)) / cabs(owned).max(1e-12);
            assert!(
                d < 1e-8,
                "{hz} Hz: exact_markov DFT {acc:?} disagrees with the owned response {owned:?} \
                 (rel {d:.3e}) — the analysis reader has drifted from the runtime law"
            );
        }
    }

    /// Attribution must be compared in the SAME norm as the bound. This pins the
    /// additive linear H-infinity metric and proves it is NOT the dB ratio.
    #[test]
    fn linf_additive_error_is_the_bound_norm_not_a_db_ratio() {
        let t = ExactSix::new();
        let surf = sample_surface(&t, 3);
        // the target against ITSELF: zero additive error
        let (e, _, _) = linf_additive_error(&t.known, &surf);
        assert!(e < 1e-9, "self-comparison must be 0, got {e:.3e}");
        // the identity body: additive error is a LINEAR magnitude, and must not
        // coincide with the dB-ratio residual (they are different quantities)
        let ident = params_to_packed(&init_identity());
        let (e2, _, _) = linf_additive_error(&ident, &surf);
        let db = residual(&ident, &surf);
        assert!(e2 > 0.0);
        assert!(
            (e2 - db.max_db).abs() > 1e-6,
            "the additive linear H-inf error coincided with the dB-ratio max; one of them is not \
             what it claims to be"
        );
    }

    /// And it must FIRE on a target that genuinely cannot fit. 10 pole pairs =
    /// 20 poles into a 12-pole budget: sigma_13 must be materially non-zero, and
    /// that is the certified minimum destruction.
    #[test]
    fn floor_fires_on_an_over_budget_target() {
        let t = OverBudget::new();
        let fl = destruction_floor(&t, 0.0, 0.0, 2 * NUM_STAGES);
        let rel = fl.sigma_k1 / fl.sigma[0].max(1e-300);
        println!(
            "overbudget: mode {} sigma1 {:.3e} sigma13 {:.3e} rel {:.3e} ({:+.1} dB below peak) \
             converged {} bound {:.3e}",
            fl.mode.label(), fl.sigma[0], fl.sigma_k1, rel,
            20.0 * (fl.sigma_k1 / fl.peak_gain).log10(), fl.converged, fl.lower_bound
        );
        assert!(
            rel > 1e-4,
            "sigma_13 is only {rel:.3e} of sigma_1 on a 20-pole target squeezed into 12 — the \
             instrument failed to detect destruction that is arithmetically certain"
        );
        // A POSITIVE bound is valid by interlacing whatever the omitted tail
        // does — a finite section can only understate. (This target's Q=12 pole
        // at 220 Hz rings ~23k samples, far beyond the section's reach, and the
        // bound is certified anyway. Requiring capture here was my error.)
        assert!(
            fl.informative && fl.lower_bound > 0.0 && fl.lower_bound.is_finite(),
            "a strictly positive finite-section sigma must be certified regardless of the tail; \
             got informative {} bound {:?} status {}",
            fl.informative, fl.lower_bound, fl.status
        );
        assert!(fl.status.starts_with("CERTIFIED (positive)"), "status: {}", fl.status);
    }

    /// Jacobi SVD pinned against planted singular values.
    #[test]
    fn jacobi_singular_values_are_correct() {
        // diag(3,2,1) rotated: singular values must be exactly {3,2,1}
        let c = (0.6f64).acos().cos();
        let s = (1.0f64 - c * c).sqrt();
        let a = vec![
            vec![3.0 * c, -2.0 * s, 0.0],
            vec![3.0 * s, 2.0 * c, 0.0],
            vec![0.0, 0.0, 1.0],
        ];
        let sv = jacobi_singular_values(a);
        for (got, want) in sv.iter().zip(&[3.0, 2.0, 1.0]) {
            assert!((got - want).abs() < 1e-10, "got {sv:?}");
        }
    }

    /// The impulse response must come back real and causal-decaying, and must
    /// reproduce the spectrum it came from (round trip through the owned engine).
    #[test]
    fn impulse_from_spectrum_round_trips() {
        let t = ExactSix::new();
        let h = impulse_from_spectrum(&t, 0.0, 0.0, 2048);
        assert!(h.iter().all(|v| v.is_finite()));
        // energy must decay: the tail is far smaller than the head
        let head: f64 = h[..64].iter().map(|v| v * v).sum();
        let tail: f64 = h[1024..].iter().map(|v| v * v).sum();
        assert!(tail < head * 1e-6, "impulse did not decay: head {head:.3e} tail {tail:.3e}");
    }

    #[test]
    fn sha256_known_vector() {
        assert_eq!(
            sha256_hex(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }

    /// No normalization anywhere: rendering the SAME rows twice with the same
    /// input must be bit-identical, and a louder input must come out louder.
    #[test]
    fn render_is_absolute_not_normalized() {
        let t = ExactSix::new();
        let rows = t.rows(0.5, 0.5).unwrap();
        let dry = dry_signal(4096);
        let a = render_rows(&rows, &dry);
        let b = render_rows(&rows, &dry);
        assert_eq!(a, b, "render is not deterministic");
        let loud: Vec<f32> = dry.iter().map(|&x| x * 2.0).collect();
        let c = render_rows(&rows, &loud);
        let (pa, _, _) = stats(&a);
        let (pcx, _, _) = stats(&c);
        assert!(
            (pcx / pa - 2.0).abs() < 1e-3,
            "gain was normalized away: {pa} vs {pcx}"
        );
    }

    #[test]
    fn mouth_total_gain_is_explicit_and_section_normalization_is_absent() {
        let t = BranchingMouth;
        for (ci, &(m, q)) in CORNER_MQ.iter().enumerate() {
            let rows = t.rows_at(m, q);
            let product = rows.iter().map(|r| r[0]).product::<f64>();
            let expected = 10.0f64.powf(MOUTH_GAIN_DB[ci] / 20.0);
            assert!((product - expected).abs() < 1e-12);
            assert!((rows[0][0] - expected).abs() < 1e-12);
            assert!(rows[1..].iter().all(|r| r[0] == 1.0));
        }
    }

    #[test]
    fn mouth_q0_branch_actors_are_exact_cancellations() {
        let t = BranchingMouth;
        for &m in &[0.0, 1.0] {
            let clear = t.rows_at(m, 0.0);
            for lane in 4..6 {
                assert_eq!(clear[lane], [1.0, clear[lane][3], clear[lane][4], clear[lane][3], clear[lane][4]]);
            }
            let coloured = t.rows_at(m, 1.0);
            assert!(coloured[4][1] != coloured[4][3]);
            assert!(coloured[5][1] != coloured[5][3]);
        }
    }
}
