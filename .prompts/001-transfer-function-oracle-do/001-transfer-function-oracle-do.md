<objective>
Build and run an end-to-end, clean-room-capable transfer-function system-identification pipeline for TRENCH in `C:\Users\hooki\df2-workstation`.

The pipeline must turn controlled black-box dry/wet captures at fixed Morph/Q positions into:

1. a reproducible complex transfer-function dataset;
2. a jointly fitted four-corner, six-lane packed `.body240` candidate;
3. packed-runtime training and held-out validation metrics;
4. audio/null proof and a versioned proof bundle.

This is an implementation task. Do not stop at research, a plan, an architecture memo, or a list of choices. Inspect the live repository, select the smallest repo-native implementation, build it, test it, and run it end to end. If the real black-box target cannot be automated on this machine, complete and verify the entire pipeline against a synthetic hidden-body oracle, then leave one exact capture command/workflow as the only external blocker. Never invent target measurements.
</objective>

<authority_and_scope>
Before editing:

1. Read `C:\Users\hooki\df2-workstation\AGENTS.md` completely.
2. Inspect `git status`, relevant concurrent processes, retained runtime APIs, existing CLIs/tests, and generated-artifact conventions.
3. Work only in `C:\Users\hooki\df2-workstation`.
4. Preserve all unrelated dirty work. Do not modify memory, lockfiles, UI, docs unrelated to this implementation, or restore deleted applications/tools from Git history.

The live workstation contract overrides stale material elsewhere:

- exactly 240 bytes = 4 corners x 6 stages x 5 u16 words x 2 bytes;
- corner order: `M0_Q0`, `M100_Q0`, `M0_Q100`, `M100_Q100`;
- all four corners are authored; Q100 is not derived;
- stage index is sacred correspondence across corners;
- packed-u16 Morph-first, then Q interpolation is authoritative;
- runtime decode yields direct `[b0,b1,b2,a1,a2]` DF2T sections;
- six sections form one serial cascade;
- `trench-core` is the only owner of packing, interpolation, response, certification, and audio-engine behavior.

Do not create a second DSP kernel, alternate packer, alternate interpolator, or surrogate response engine.
</authority_and_scope>

<clean_room_boundary>
This pipeline may observe a target only through black-box controls and audio I/O.

Do not read, import, decode, or copy:

- ROM/preset bytes;
- coefficient or packed-word tables;
- decoded pole/zero rows;
- P2K Atlas data;
- bank rips or memory dumps;
- protected preset names;
- source/compiler code from `C:\Users\hooki\trench-filters` or another branch.

Keep target identifiers anonymous (`target_001`, etc.). Record target binary/plugin hashes and capture provenance without extracting implementation data.

At the beginning, record whether this chat/agent has previously seen exact target bytes or coefficients. If exposed, it may build and validate the generic pipeline but must not label a fitted target body “strict clean room.” Produce a fresh-run handoff for an unexposed implementer. Do not weaken or silently omit this provenance boundary.
</clean_room_boundary>

<core_principle>
The target is the sampled complex transfer-function field:

`H_target(f; morph, q)`

The candidate is judged as:

`H_trench(f; morph, q)`

Do not optimise a special “middle.” The center is only one sample. Fit a distributed training grid and validate against held-out interior positions.

Corner transfer functions alone are insufficient because a static cascade is permutation-invariant while packed stage interpolation is not. Include a regression test proving that an endpoint-preserving stage permutation leaves the corner transfer functions unchanged but changes at least one interior transfer function. Endpoint-only scoring must be impossible.
</core_principle>

<capture_system>
Implement a deterministic capture/session workflow with commands equivalent to:

- `prepare`: create the excitation WAV, grid manifest, and capture instructions/jobs;
- `capture` or `ingest`: automate the black-box target when possible, otherwise validate externally bounced wet WAVs;
- `estimate`: align dry/wet audio and estimate the complex transfer functions;
- `fit`: jointly fit and pack one four-corner body through `trench-core`;
- `verify`: evaluate training, held-out, certification, and audio/null gates;
- `bundle`: persist the candidate, session, metrics, plots, audio, logs, and hashes.

Reuse existing commands and modules where they genuinely satisfy these roles. Create only the missing pieces.

Capture requirements:

- Use BODY SOLO/cascade-only behavior at unity I/O whenever the target provides it.
- Disable AGC, saturation, normalisation, automatic make-up gain, dynamics, and modulation. If any cannot be disabled, detect and report that the target is not an LTI capture rather than pretending otherwise.
- Verify the engine’s actual internal rate and host-rate SRC path from live code. Record both rates. Do not assume the rate from stale prose.
- Use a deterministic broadband excitation suited to complex transfer-function estimation. Select one primary method after inspecting available tooling—prefer a repeated broadband sequence or sweep with explicit inverse/estimation—and document why it is correct for this path.
- Capture at two safe excitation levels plus repeats at the corners and center to test linearity, time invariance, repeatability, clipping, and noise floor.
- Preserve absolute amplitude. No per-render normalisation.
- Estimate and preserve latency. Remove only a measured pure transport delay for phase comparison; retain raw phase and recorded delay in the session.
- Compute complex `H(f)` using a defensible estimator such as `Sxy/Sxx`, with coherence and an explicit confidence mask. Persist raw spectra rather than only plots.
- Keep magnitude, unwrapped phase, complex response, coherence, group delay, and absolute gain.

Use this initial grid exactly unless live runtime control quantisation proves a point cannot be represented:

`morph, q = {0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1}`

That is an 81-state 9x9 capture. Use a deterministic checkerboard split:

- training: `(m_index + q_index) % 2 == 0`;
- held out: `(m_index + q_index) % 2 == 1`.

Held-out states must never enter the fitting objective or permutation selection.
</capture_system>

<session_contract>
Every capture session must be immutable/versioned and contain at least:

- schema/tool version and timestamp;
- anonymous target ID;
- target/plugin hash and black-box host version;
- internal and host sample rates;
- block size and channel routing;
- BODY SOLO/product state and every relevant bypass;
- exact Morph/Q values and control quantisation/readback;
- excitation parameters and SHA-256;
- dry/wet WAV paths and SHA-256 values;
- raw level, peak, RMS, clipping count, and repeat index;
- measured latency/alignment;
- estimator/window/overlap/FFT settings;
- complex transfer-function arrays, coherence, and confidence mask;
- training/held-out designation;
- all warnings and provenance/contamination status.

No hidden correction, smoothing, gain compensation, or repair is allowed. Every transformation from WAV to `H(f)` must be represented in the manifest.
</session_contract>

<fitter>
Implement joint packed-runtime fitting, not four independent magnitude fits.

Required behavior:

1. Optimisation variables represent all four authored poses and six registered lanes per pose, including pole geometry, zero geometry, SCALE/b0, identity state, and real-root versus conjugate-root type.
2. Independent real-root pairs must remain explicit and must never be silently forced through conjugate controls.
3. Stage correspondence is a discrete hidden variable. Do not frequency-sort corners. Do not use nearest-frequency pairing as the final rule. Search or optimise correspondence using training-grid transfer-function error.
4. Corner factorisation, pole-to-zero association, per-stage gain allocation, and cross-corner transport must be treated as ambiguity—not assumed known from endpoint curves.
5. Every candidate evaluation must follow the real loop:

   `proposal -> trench-core pack -> packed interpolation -> runtime decode -> serial response -> objective`

6. Unpacked/root-domain response may be used only for initialisation and diagnostics. It cannot decide the winner.
7. The objective must compare complex response across all training states and preserve absolute gain. Use coherence/confidence weighting and a declared perceptual frequency weight, but do not peak-normalise either target or candidate.
8. Report separate metrics for magnitude RMS/max error, complex relative error, phase/group-delay error, and time-domain null. Do not collapse everything into one flattering score.
9. Do not add a special center penalty. The center participates only according to the same grid/weighting rule as other training states.
10. Keep optimisation reproducible: fixed seeds, persisted configuration, persisted initialisation, and resumable checkpoints.

Use `trench-core` APIs directly or through one thin repo-native bridge. If a bridge is required, it must expose existing pack/interpolate/response/certify/render behavior without duplicating its math.
</fitter>

<verification_and_gates>
Before declaring completion, prove all of the following with persisted artifacts and automated tests:

Capture/estimator gates:

- dry loopback recovers unity magnitude and the measured pure delay within tolerances derived and recorded from the loopback fixture;
- repeat captures meet an empirically derived repeatability tolerance;
- coherence/confidence coverage is reported over the usable band;
- the two-level test demonstrates an LTI operating range or explicitly fails;
- raw audio is never replaced by normalised audio.

Runtime/body gates:

- candidate is exactly 240 bytes;
- no-op load/save is byte-identical;
- raw body and JSON `packedWords` converge to identical packed corners if both forms are emitted;
- a declared edit changes only declared corners/lanes/words;
- real-root rows cannot silently enter the conjugate path;
- all plots and responses come from packed/runtime-decoded coefficients;
- shared dB axes are used for comparisons;
- body/cart parity passes;
- a dense 33x33 Morph×Q certification has zero unstable rows and zero nonfinite rows;
- endpoint-preserving permutation regression passes and proves interior sensitivity.

Fit-quality gates:

- report training and held-out results separately;
- held-out results are not materially worse than training without explicitly flagging overfit;
- compare against a deterministic neutral/baseline body and prove meaningful improvement;
- render matched dry input through target and candidate at representative training and held-out states;
- latency-align without gain normalisation and report wet null depth plus residual spectra;
- do not claim continuum proof; call grid results sampled certification.

Derive numerical tolerances from loopback, repeatability, and a synthetic hidden-body recovery fixture. Do not invent confidence thresholds merely to obtain PASS.
</verification_and_gates>

<synthetic_end_to_end_fixture>
The implementation is not complete until it can run without the external target.

Create a deterministic synthetic black-box fixture using an existing legal/original `.body240` or a test-only generated body. The capture side may render it, but the fitting process must receive only dry/wet audio and the anonymous session manifest—not its body bytes or decoded coefficients.

Run the complete workflow:

`prepare -> capture/render -> estimate -> fit -> verify -> bundle`

The fixture must exercise:

- all four authored corners;
- nontrivial Morph and Q motion;
- at least one deliberate lane crossing;
- meaningful zeros;
- endpoint-preserving permutation ambiguity;
- held-out interior validation.

Use it to calibrate estimator and fit tolerances. Do not claim exact byte recovery; success is recovery of held-out transfer-function behavior through the packed runtime.
</synthetic_end_to_end_fixture>

<artifacts>
After inspecting existing conventions, keep implementation code in the smallest appropriate existing `tools/`, `workstation/src/bin/`, or `trench-core` integration locations. Do not create a parallel application.

Generated sessions and proof must live below:

`C:\Users\hooki\df2-workstation\dev\tmp\tf_oracle\<session_id>\`

Each proof bundle must include:

- `session.json`;
- excitation and raw capture hashes;
- raw/estimated complex transfer-function data;
- fit configuration and checkpoints;
- fitted `.body240` and, if used, matching cartridge JSON;
- certification report;
- training-versus-held-out metrics;
- shared-scale plots;
- representative target/candidate/residual WAVs;
- null report;
- provenance/contamination statement;
- exact reproduction commands;
- `SUMMARY.md` with the substantive result, files created/modified, decisions needed, blockers, and next command.

Also create:

`.prompts/001-transfer-function-oracle-do/SUMMARY.md`

using the same required summary sections.
</artifacts>

<execution_discipline>
- Maintain a short working plan, but do not ask the user to choose between architectures.
- Make one scoped change per verification step.
- Use parallel read-only inspection where independent.
- Prefer existing repository contracts and tests over new abstractions.
- Label conclusions `OBSERVED`, `INFERRED`, `UNKNOWN`, or `REJECTED`.
- If a command fails, diagnose and continue; do not convert implementation work into another doctrine document.
- Do not stop after compilation. Run the synthetic end-to-end fixture and inspect the resulting metrics, plots, and audio artifacts.
- Do not commit, push, install, or publish unless explicitly requested.
</execution_discipline>

<final_response>
Lead with the outcome. State:

1. whether the full synthetic pipeline ran successfully;
2. whether a real black-box target capture was completed or the exact external capture action still required;
3. training and held-out transfer-function/null results;
4. packed certification result;
5. concrete files and proof-bundle paths;
6. provenance/clean-room status;
7. the single next command, if anything remains.

Do not end by offering multiple directions or asking what to do next.
</final_response>

<success_criteria>
- One reproducible command chain produces a versioned capture-to-proof bundle.
- The stored target evidence is complex transfer-function data with absolute gain, phase, coherence, and provenance—not magnitude screenshots.
- Fitting is joint across the sampled field and evaluates only packed/runtime-decoded TRENCH candidates.
- Stage correspondence is solved from training interior behavior, never inferred from frequency sorting or endpoints alone.
- Held-out points remain untouched until verification.
- Synthetic hidden-body recovery runs end to end and demonstrates functional improvement over baseline.
- The candidate passes exact 240-byte, parity, stability, finite, and sampled-grid gates.
- No second DSP kernel, protected bytes, copied preset data, per-render normalisation, or fake clean-room claim is introduced.
- The implementation and proof artifacts are sufficient for a fresh unexposed agent/operator to run the actual anonymous target capture without further architectural decisions.
- `.prompts/001-transfer-function-oracle-do/SUMMARY.md` is created with a substantive one-line result and exact artifact paths.
</success_criteria>
