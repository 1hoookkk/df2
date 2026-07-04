# AUTHORING_CORPUS_DIGEST — the authoring literature, dated, judged, extracted

Written 2026-07-04 ahead of the ship-bodies phase (4 originals: DJ Alkaline /
FuzziFace / LucifersQ / Meaty Gizmo rebuilt on measured wells). Ground truth for
every verdict below: `CLAUDE.md` (constitution), `LAWS.md` (case law),
`STATE.md` (2026-07-04 live cache), `trench-filters/{archetypes/ARCHETYPES.md,
REFERENCE.md, AUDIT_SHIP_BODIES_PROMPT.md}`. Evidence labels: OBSERVED = the doc
literally says it / a file proves it; INFERRED = judgment call stated as such.

---

## 1. PER-DOC LEDGER

| Doc | What it is | Era | STATUS |
|---|---|---|---|
| `CLARITY.md` | The one authoring model: 6 stages × SHAPE/FREQ/GAIN at LO/HI frames, Q = per-shape pole radius, 4 corners DERIVED; names the dead-ends (firmware-integer, generic pressurize, free four-corner) | 2026-06-12 (sanitise-morph-designer) | **LIVE.** Matches CLAUDE.md §6/§8 verbatim in substance; `tools/morph_designer.py` is its reference implementation and is the tool the pending audit names. |
| `DATASETS.md` | The grounded-tables spine: every pole/zero/freq is looked up (tables/, P2K atlas aggregates, trench-core as sole engine), never invented | 2026-06-13 | **LIVE.** Restates CLAUDE.md §7 (evidence discipline) as a file map. Use as the index to `tables/*.json`. |
| `BODY_TAXONOMY.md` | 4-Materials naming proposal (Flesh&Breath / Wood&Metal / Mirrors&Glass / Silicon&Wire) + MASS×ENERGY picker axes, for the Forge GEN menu | 2026-05-31 (NotebookLM distillation) | **HISTORICAL-ONLY.** Self-declares "NOT ACTIVE DESIGN AUTHORITY" in its own header. Its 5 guardrails (6 biquads not 14; whole corners; middle is read-only; clean-room; SLAM=drive not unstable poles) all survive in CLAUDE.md. The taxonomy/UI plan is dead (Forge egui era). |
| `NOW.md` | Layered session log, top block = 2026-05-31 Forge-bench state; claims to be "the one current-state file" | 2026-05-28→05-31 | **SUPERSEDED-BY STATE.md (2026-07-04).** Its "8-corner cube IS the architecture" lock, 14-pole/7-biquad v2 plan, CLAP/gradient authoring track, and v1 body list (Speaker Knockerz / Aluminum Siding / Small Talk / Cul-De-Sac) are ALL superseded — see contradictions §3. Read only for the clean-room path inventory and the strategic pin (revenue/patent/naming), which still hold. |
| `PRODUCTION_AUTHORING.md` | The QD-search production pipeline: `train.py model=v1`, 50-slot `full_bank.yaml`, archive cells → packed-runtime gate → export | 2026-06-02 | **SUPERSEDED-BY CLARITY.md + the morph_designer/trench-filters path** for the ship-4 phase. The packed-runtime gate + `scripts/export.py` promotion discipline it describes is still the law (CLAUDE.md §9–10); the *search-generates-bodies* framing is the pre-"provide data, don't bake" era. 50-slot bank ≠ ship-4 roster. |
| `desk/RECIPES.md` | The authoring cookbook: radius math, Peterson&Barney + Klatt tables, tube/metal physics, 7 families, P2K vocal law, iconic corridor, q_radius table, 6 worked recipes | 2026-06-11 (post Q-bloom correction — carries "Q bloom 6–34 dB") | **LIVE as the data summary** (all values table-pulled, provenance-tagged). Two stale edges: the Forge clamp block (pole r ≤ 0.9992, gain −26…+12) is the old zedit forge's, and corridor maxR 0.985–0.988 conflicts with the newer per-corner decodes — see §3. |
| `recipes/PRISTINE_PRESET_STACK.md` | Keep/move rule for recipe folders + the "Good Preset Test" + reject list | 2026-06-13 | **LIVE** (its reject list and Good Preset Test restate CLAUDE.md §2/§6/§13). The `section-law-v1` seeds in `recipes/laws/*.json` and `three_layer_acoustic_forge/` are HISTORICAL candidate seeds — clean-room-tagged, but from the pre-morph_designer compile path; audition-only, not ship inputs. |
| `docs/archive/### Permanent Master Acoustic Dictionary.txt` | NotebookLM behavioral spec of ~20 legacy Z-plane filters (acoustic target / Morph / FreqTrack / Transform2 per filter) | ≤2026-05-30 | **HISTORICAL-ONLY, study-grade.** Behavior prose only — clean-room usable. Hazards: many entries are 14-pole (df2 = 6 stages, CLAUDE.md §2); it covers LucifersQ + FuzziFace but NOT Meaty Gizmo or DJ Alkaline; provenance is NotebookLM, so treat every number in it as UNVERIFIED unless it reappears in a measured file. |
| `docs/archive/FIT_METHOD_HANDOFF.md` | The LPC/ARMA fit-real-audio method + the bent-audit breakthrough + Talking Hedz structure | 2026-06-08 | **SUPERSEDED-BY trench-filters/REFERENCE.md** (dvtd_rails/hrtf_rails are this method, matured). Contains one claim now REJECTED: "Q contrast 0.3–1 dB (Q barely moves)" — corrected 2026-06-09 to Q bloom 6–34 dB (desk/RECIPES.md §7 carries the fix). Its `/fitbody` bake-server was also corrected by the "provide DATA, don't bake bodies" verdict (2026-06-28). Method core (Dirac IR fits, DC-pin, foundation-is-a-choice, ruler-first) survives. |
| `docs/archive/AUTHORING_BRIEF.md` | The 6-lane pole+zero authoring brief: trajectory is the product, roles by ablation, fit-poles/carve-zeros collapsed model | 2026-06-08 | **SUPERSEDED-BY CLAUDE.md §5–§6** (which absorbed its lane law, zeros-first-class, packed-geometric-morph facts). Mostly compatible; its strict "zeros = the ONLY authoring act / poles read-only" is the Shape-Forge-era stance, softened by current law to "poles table/rail-sourced, never invented; all lane params exposed with provenance." Good teaching doc for trajectory thinking. |
| `docs/archive/gpt55-pro-coefficient-forge-spec-salvage-prompt.md` | Prompt to an external model to finish a Forge stage-composer spec | 2026-06-01 | **HISTORICAL-ONLY.** Prompt artifact; its locked constraints (240 B, 6 stages, corner order, packed-domain proof) match CLAUDE.md, so it poisons nothing, but authors nothing either. |
| `docs/archive/gpt55-pro-constructor-palette-prompt.md` | Prompt: adjudicate the minimal constructor palette over the observed Type 1/2/3 grammar | 2026-06-01 | **HISTORICAL-ONLY, with one live payload:** its OBSERVED Type 1/2/3 zero-treatment grammar (zero AT / near-Nyquist / deep-low) is real and now lives in `tables/morph_designer_type_primitives.json`. Its "gain g ∈ [0,4] hard ceiling" is a `compile_body`-path fact — that path is REJECTED for authoring (use morph_designer). |
| `CLAUDE.md` / `LAWS.md` / `STATE.md` / `ARCHETYPES.md` / `REFERENCE.md` / `AUDIT_SHIP_BODIES_PROMPT.md` | Ground truth set | 2026-06-29 → 07-04 | **LIVE.** All conflicts below resolve toward these. |

Missing files: none — everything requested exists. `recipes/` resolved to the
directory `recipes/{laws/, PRISTINE_PRESET_STACK.md, three_layer_acoustic_forge/}`
plus the cookbook at `desk/RECIPES.md`.

---

## 2. THE LOAD-BEARING EXTRACT (what the ship-4 phase actually needs)

Everything below is OBSERVED in the cited doc — no invented numbers.

### 2.1 The authoring model (CLARITY.md + CLAUDE.md §6)
- Author exactly TWO frames (LOW/HIGH) × 6 ordered lanes; each lane = pole f/r,
  zero f/r, gain, provenance tag. Q100 corners are DERIVED; Secondary may change
  radius/depth/gain, never center frequencies. Corner order M0_Q0, M100_Q0,
  M0_Q100, M100_Q100; 240 bytes; morph-first packed bilinear lerp (CLAUDE.md §2–3).
- Q = per-shape pole radius: `bandwidth = f/Q`, `r = exp(−π·B/SR)`, SR = 39062.5
  (CLARITY.md "Q is pole radius"; desk/RECIPES.md §1; quick estimate Q ≈ 1/(2(1−r))).
- Serial cascade: sections multiply, dB adds; every section flat off-resonance or
  it buries the chain; foundation = flat-topped low shelf, NOT a lowpass
  (CLARITY.md SHAPES; RECIPES §1; FIT_METHOD "sub mountain").
- Tool: `tools/morph_designer.py` (run PYTHONUTF8=1). NOT `compile_body`
  (GAIN_MAX=4 clamp + DC-norm), not ad-hoc RBJ (memory + AUDIT prompt).

### 2.2 The 4 ship targets — decoded moves (ARCHETYPES.md, behavior-only spec)
- **FuzziFace (P2k_007, DST):** one razor ~4 kHz/Q≈190 riding a 320–600 Hz
  cluster; morph glides the stack up ~1 oct; HOT at Q0; Q = mid-freq tone control.
- **LucifersQ (P2k_029, REZ):** tame-ish at Q0; Q100 ignites Q40–80 mid peaks
  across 250 Hz–5 kHz simultaneously; manual warns "care with Q 40-90".
- **Meaty Gizmo (P2k_004):** pole centers ~static; identity = pure Q contrast
  Q~4–37 → Q~2000–3400 (r → 0.9997). Body-to-needle.
- **DJ Alkaline (P2k_015):** already sharp at baseline (Q80–120 @ Q0), peaks
  spread 1.7–13.5 kHz, blooming to Q1000+.
- Acoustic Dictionary corroborations (behavior prose): LucifersQ "violently
  resonant mid-band… T2 modulates the extreme Q"; FuzziFace "clipped fuzz in the
  topology… T2 = Q as mid-frequency tone control". `.4` convention: Transform2
  defaults to internal distortion.

### 2.3 Calibrations that gate the build (trench-filters/REFERENCE.md)
- **Baseline-Q policy (Talking Hedz decode):** musical authored frame sits at
  r ≈ 0.95–0.99 (bw 100–660 Hz); razor r 0.999+ belongs ONLY at the Q extreme.
  DVTD rails capped r ≤ 0.990 for this reason.
- **Type-3 freq compression:** compile-time only; trigger packed_freq ≥ 118 ≈
  7152 Hz @ 39062.5; deep high cuts get pulled toward 220. Any 8–13 kHz cut/notch
  lane (Alkaline territory) must route around it. Probe:
  `df2/dev/tmp/type3_compression/probe.py`.
- **lerp_u16 wraps i16, no clamp** — large LOW↔HIGH packed deltas zipper
  mid-morph; interior probe is mandatory, coeff-space plots miss it.
- **AGC** is drive-dependent ducking (table `[1.0001,…,0.120×8]`) — "the
  character"; engine-side, never baked into a body.
- **Storage-layers law:** ROM / X3-parametric / p2k_skins / df2-canon are 4
  non-interconvertible representations; name the layer in every claim; no
  layer's bytes ship.
- **Q was note-on-only on all E-mu hardware** → live-Q sweep is novel territory;
  fast-Q-sweep is THE §11.5 gate.
- **Zeros census (all 50 ROMs):** 40% unit-circle notch / 36% gain shaping /
  13% DC / 11% pole-paired EQ / 0.0% non-min-phase. Measured wells' non-min-phase
  zeros (HRTF pinna notches, DVTD antiformants) are material P2K never had.
- **Wells readiness:** DVTD 44 rails DONE, HRTF 48 rails DONE; circuit (FuzziFace)
  and modal (LucifersQ/Meaty) sims NOT RUN.

### 2.4 Measured/physics tables (desk/RECIPES.md, all provenance-tagged)
- **Vowels (Peterson & Barney 1952, male):** F1/F2/F3 + B1/B2/B3 for 10 vowels
  (e.g. iy 270/2290/3010, uw 300/870/2240); female ×1.16, child ×1.25; talking
  morph pairs oo→ee, ah→ee, oo→ah, ee→ah.
- **Klatt 1980:** 4-vowel calibration set + bandwidth tables; F4 = 3300 Hz /
  B4 = 250 Hz held constant (license for a fixed presence section); nasal pole
  270 Hz/BW 100 cancelled by a zero at 270; nasalize = F1 +~100 Hz + zero at
  mean(F1+100, 270); nasal murmur = widen B2/B3, not extra poles.
- **Radius ladder:** B 8→400 Hz ⇒ r 0.99936→0.96834 with character labels
  (ringing metal → broad body).
- **Tubes:** open f_n = n·c/2L, closed f_n = (2n−1)·c/4L, worked rows 10–50 cm;
  morph = length change or open↔closed.
- **Metal ratios:** free bar 1/2.756/5.404/8.933/13.34; clamped bar 1/6.267/
  17.55/34.39; free plate 1/1.73/2.33/2.65/3.5/3.93/4.81; bell 0.5/1/1.2/1.5/2/…
  (tierce = the sadness); gong row. Ringing B≈8 Hz, damped B≈25, thud B≈90.
- **P2K vocal law (clean-room):** stage-1 throat pole 200–580 Hz; one deep zero
  (r 0.9–1.0) beside each formant pole; motion = log-slide the constellation,
  never rank-swap.
- **q_radius table (measured, 45/512 indices):** q0 → r 0.9863 (132 corpus hits)
  down to q104 → r 0.124; the iconic bodies live at the top of the schedule.
- **Iconic corridor (evaluate_body over iconic-15):** span 40–120 dB; Q bloom
  6–34 dB rms (Talking Hedz 6.3, Meaty 33.9); anchor+mover — ONE leader pole +
  ONE leader zero travel 1–5.6 oct; low body held as flat-topped shelf. (maxR
  0.985–0.988 line: stale — see §3 row C.)
- **Worked recipes §8:** vowel glide, tube stretch, metal strike, resonant LP
  sweep (3 stacked poles, zeros parked 14 kHz, 110 Hz→3.5 kHz leader), notch
  comb (zeros at odd f0 multiples r 0.99, near-allpass poles just below), and
  bass-safe rule (S1 always flat-topped shelf).

### 2.5 Structure & method fragments still worth carrying
- **Talking Hedz anatomy (FIT_METHOD_HANDOFF):** a crossing formant pair + 2 held
  sharp bite anchors + a moving broad body (low-mid sweeps ~25 dB) + an air kill.
  The template for "the middle matters."
- **Fit method (FIT_METHOD → REFERENCE.md):** Dirac IRs are the cleanest fit
  source; DC-pin every section; the foundation is a CHOICE (none / sub shelf /
  low hump / 808 / tube), picked by ear, never computed. Ruler-first: validate
  gates against known-good before trusting them (now LAWS.md L16).
- **Type 1/2/3 grammar (constructor prompt + tables/morph_designer_type_primitives.json):**
  three zero treatments of one pole+zero actor — zero AT the pole (peak/notch),
  zero pinned near Nyquist (shelf/LP edge), zero pinned deep-low ~57 Hz r~0.99
  (sub-carve/HP body). Useful as authoring vocabulary.
- **Good Preset Test (PRISTINE_PRESET_STACK):** protected low foundation, 1–2
  obvious moving actors, first-class zero canyons, Q pressure without frequency
  drift, the midpoint must matter; packed audit (240 B, 0 unstable, 0 nonfinite)
  before listening.
- **Trajectory law (AUTHORING_BRIEF):** the authored object is the PATH each lane
  travels A→B; packed morph is geometric/log (400→4000 Hz passes ~1274 Hz at
  M50) — reason in octaves, never linear Hz; roles proven by ablation
  (mute-and-judge), not labels.
- **Copy-risk gate:** ship ≥ ~6 dB clear of all 50 P2K (`dev/tmp/copy_risk.py`;
  LAWS L21).

---

## 3. CONTRADICTIONS TABLE

| # | Conflict | Sides | Winner + why |
|---|---|---|---|
| A | Engine order: "14 was the winner" / 7-biquad v2, and Dictionary's 14-pole entries | NOW.md 2026-05-31 roadmap; Dictionary | **CLAUDE.md §2**: 6 stages, never a hidden seventh. The 7-stage plan was never executed; every live tool and test asserts 6×5×4×2=240. Dictionary entries are behavior-only study. |
| B | "Q barely moves (0.3–1 dB)" vs "Q blooms 6–34 dB" | FIT_METHOD_HANDOFF (06-08) vs desk/RECIPES §7 + memory correction (06-09) + ARCHETYPES (Meaty Q4→3400) | **Bloom wins** — the 0.3–1 dB figure was the bent-ruler artifact its own doc warned about; corrected against the iconic-15 the next day. Any gate or law citing "subtle Q" is poison. |
| C | Corridor maxR 0.985–0.988 vs decoded per-corner maxR 0.9983–0.9997 (FuzziFace, Meaty) and Talking Hedz Q100 r 0.999+ | RECIPES §7 / FIT_METHOD vs ARCHETYPES.md + REFERENCE.md (06-29→07-03) | **Newer decodes win as facts.** INFERRED reconciliation: 0.985–0.988 was an aggregate metric over the iconic-15 at baseline, not a per-corner ceiling. Consequence: the corridor gate needs re-derivation before it can veto a ship body — exactly AUDIT prompt item 1 (ruler first). Do not treat 0.988 as a radius cap. |
| D | Old zedit-forge clamps (pole r ≤ 0.9992, gain −26…+12 dB) vs Meaty's identity needing r ~0.9997 | RECIPES §1 clamp block vs ARCHETYPES Meaty | **ARCHETYPES (the target) wins the requirement**; the clamp is a stale tool limit, not law. Whether the packer + Schur gate ADMIT r 0.9997 is an open probe (AUDIT item 3). |
| E | Authoring path: QD search / `train.py` / 50-slot bank; `compile_body` + `/fitbody` bake server; g ∈ [0,4] ceiling | PRODUCTION_AUTHORING.md, FIT_METHOD, gpt55 prompts | **morph_designer path wins** (CLARITY.md + AUDIT prompt + "provide data, don't bake" verdict 06-28). compile_body's GAIN_MAX=4 clamp + DC-norm is the documented reason surface-forge exports broke. QD/search survives only as a candidate-proposer, never a body-author. |
| F | Ship-4 roster: Speaker Knockerz / Aluminum Siding / Small Talk / Cul-De-Sac vs Alkaline / FuzziFace / LucifersQ / Meaty | NOW.md "v1 boundary" vs STATE.md open-thread #1 + ARCHETYPES | **STATE.md wins** (2026-06-29 decision: rebuild the moves of Tyson's 4 P2K favourites on measured wells). |
| G | Architecture: 8-corner cube + Path slider "LOCKED" vs 4-corner two-frame model, two wheels = MORPH+Q, SLAM = canvas drag | NOW.md vs CLAUDE.md §2/§6 + trench-v1 + richness-pass verdicts | **Current law wins.** The cube/Path era ended with the V1 two-page lock (06-27) and the 07-02 interaction remap. Z-crossfade code may exist but is not the ship model. |
| H | "Whole corners, never per-stage authoring; no assign-the-6-slots UI" vs 6-lane authored frames with per-lane provenance | BODY_TAXONOMY guardrail 2 vs CLAUDE.md §6 / CLARITY | **CLAUDE.md wins.** The taxonomy's target was a *user-facing generator UI*; authoring law is per-lane with provenance. No real conflict once scoped, but quoting guardrail 2 against morph_designer would be a mistake — flag it. |
| I | "Zeros are the ONLY authoring act; poles read-only" vs zeros first-class AND poles authored-from-tables | AUTHORING_BRIEF §10 / Shape-Forge era vs CLAUDE.md §6 + DATASETS | **CLAUDE.md wins**: both poles and zeros are authored, both cite provenance; poles default onto rails, never invented. The brief's stance is a valid workflow subset, not a law. |
| J | Secondary must not move centers (invariant) vs teacher filters where "Q SHIFTS ring frequency" (DJAlkaline manual note) / "filter INVERTS at mid-Q" (Meaty) | CLAUDE.md §6 vs REFERENCE.md manual facts | **CLAUDE.md wins for OUR bodies** — the decoded DJ Alkaline Q0→Q100 pole freqs barely drift (11617→11747 etc.), so the perceptual "shift" emerges from radius/gain change; author within the invariant. If a rebuild cannot read right without center drift, that's a REJECT, not an exception. AUDIT item 3 touches this boundary. |
| K | NOW.md: "STATE.md = older worklog, archive" | NOW.md header vs STATE.md header ("this file is the live cache") | **STATE.md wins** — roles inverted since May. Anyone routed by NOW.md's header lands in the wrong decade of the project. |
| L | Dictionary/taxonomy sourced from NotebookLM prose (unverified Hz, e.g. ShakuFilter peak list) vs cite-or-refuse | Dictionary vs CLAUDE.md §1/§7 | **Cite-or-refuse wins**: dictionary numbers are UNVERIFIED provenance — usable as *intent* language only; any Hz that ends up in a lane must re-source from tables/ or a measured rail. |

---

## 4. GAPS — what ship-4 needs that NONE of these docs provide

1. **Circuit + modal well data.** FuzziFace (SPICE/WDF FRF) and LucifersQ/Meaty
   (modal/neural-resonator FRF) sims are NOT RUN (REFERENCE.md inventory). Three
   of four bodies currently have no admissible evidence surface.
2. **The lane-correspondence lift procedure.** Rails are fit per-direction/
   per-posture independently; no doc defines how lane i LOW maps to lane i HIGH
   (nearest-frequency matching alone is forbidden, CLAUDE.md §5). AUDIT item 5
   flags it; nothing specifies it.
3. **A Q-radius law with Meaty-scale contrast.** No doc bridges "authored frame
   r 0.95–0.99" (REFERENCE calibration) to "Q100 razor r 0.9997 / Q~3400"
   (ARCHETYPES) inside packer precision + Schur margin. RECIPES' "shrink (1−r)
   by ~⅓" cannot produce it. Needs a per-body Q policy + probe.
4. **Concrete §11.5 thresholds.** τ_level, τ_peak, τ_jump, τ_schur etc. are
   symbolic everywhere; CLAUDE.md says set them from listening/gain-staging —
   never done. Blocked partly by the open plugin-chain leveler case (LAWS open
   cases): shipped-chain gain staging isn't yet trustworthy as a ruler.
5. **Re-validated corridor/gates.** The ruler (smoke.yaml corridor,
   evaluate_body) hasn't been re-run since the newer decodes exposed the maxR
   discrepancy (§3 C). AUDIT item 1 demands it; no doc records a current pass.
6. **HRTF→Alkaline Q story.** HRTF rails are smooth (RMS 0.5–5.9 dB); the
   archetype baseline is Q80–120. No doc states the admissible transform (if
   any) from measured pinna Q to that baseline without inventing radii — the
   audit's own suspicion, unresolved.
7. **Type-3 avoidance recipe.** REFERENCE documents the >~7152 Hz compression;
   no doc gives the authoring-path routing rule for Alkaline's 8–13 kHz lanes
   (which word/type each high lane should compile through).
8. **Copy-risk threshold formalized.** The ~6 dB clearance lives in memory/AUDIT
   prompt only — not in any corpus doc as a numbered gate with its measurement
   procedure.
9. **Live-Q sweep qualification.** Q was note-on-only historically (REFERENCE);
   no doc defines the fast-Q-sweep acceptance procedure for the 4 bodies beyond
   naming it as "the gate."

---

## 5. NOTEBOOK PACK VERDICT

**UPLOAD (clean, current, mutually consistent):**
- `CLAUDE.md`, `LAWS.md` — the law.
- `trench-filters/archetypes/ARCHETYPES.md`, `trench-filters/REFERENCE.md`,
  `trench-filters/AUDIT_SHIP_BODIES_PROMPT.md` — the ship-phase spec + facts.
- `desk/RECIPES.md` — the data cookbook (strip or annotate the Forge-clamp block
  and the maxR 0.985–0.988 line per §3 C/D).
- `CLARITY.md`, `DATASETS.md`, `recipes/PRISTINE_PRESET_STACK.md` — model, data
  spine, hygiene test.
- `### Permanent Master Acoustic Dictionary.txt` — ONLY with a caveat header
  ("behavior-only; 14-pole ≠ our 6-stage engine; numbers unverified"): its
  LucifersQ/FuzziFace/Transform2 prose is genuinely useful intent language.
- Optional: `docs/archive/AUTHORING_BRIEF.md` (trajectory/ablation thinking —
  mostly law-compatible), this digest.

**DO NOT UPLOAD (would poison retrieval with stale authoritative-sounding claims):**
- `NOW.md` — presents the 8-corner cube, 7-biquad v2, CLAP pipeline, and the old
  ship roster as "locked"; its header even mis-routes to itself over STATE.md.
- `FIT_METHOD_HANDOFF.md` — carries the REJECTED "Q barely moves" recipe line
  verbatim; a notebook will quote it.
- `PRODUCTION_AUTHORING.md` — QD-search-as-author framing + 50-slot bank.
- `BODY_TAXONOMY.md` — self-archived; guardrail 2 quotes against per-lane authoring.
- Both `gpt55-pro-*` prompts — prompt scaffolding + the g≤4 compile_body ceiling.
- `STATE.md` — live but volatile; snapshots go stale in days. Link, don't upload.
- `recipes/laws/*.json`, `three_layer_acoustic_forge/**` — machine seeds, not
  literature; retrieval noise.
