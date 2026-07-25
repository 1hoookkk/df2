# PRIOR-ART LEDGER — adopt or bury before authoring body one

Drafted 2026-07-03 from the dev/tmp sweep. Every row is a prior body (or method) that
already exists on disk. **Nothing gets authored for the ship 4 until each row carries a
`TYSON:` decision with a written why** — that's the institutional-memory fix this ledger
exists for. Draft recommendations are Claude's; the decision column is taste.

All gate verdicts and copy-risk numbers below were re-proven 2026-07-03 on the packed
runtime (`trench_ffi` + `configs/model/smoke.yaml` corridor; copy-risk = RMS dB of the
Morph×Q response surface to the NEAREST of the 50 P2K refs, ship threshold ≥ 6 dB clear).
Contact sheet: `8_prior_art_ledger.png` (curves + interior heatmaps per body).

---

## 1. ship_iron_mouth — the vowel body the current plan dropped

- artifact: `df2/dev/tmp/exhausted_shipping_filters_locked/ship_iron_mouth/` (.body240,
  compiled-v1 json, runtime_response.png, drums/pink/program renders through SLAM+AGC)
- method: `trench_filters_dvtd_rails` — THIS workspace's rails. refs: s1-01-bahn-tense-a → s2-03-tiere-tense-i
- corridor: **PASS** (2026-07-03) · copy-risk: **15.4 dB clear** (nearest P2k_013 talking_hedz)
- stats on file: morph 21.6 dB, Secondary 5.9 dB, center drift 0.41 cents, wrap risks 0, max r 0.99985
- DRAFT: **ADOPT AS BASELINE.** It is CLAUDE.md's filter #1, finished. Judge plot + renders; if it
  taste-passes, the vowel gap closes for free and the roster contradiction resolves.
- TYSON:

## 2. ship_riot_plate — modal violence without the neural sim

- artifact: `df2/dev/tmp/exhausted_shipping_filters_locked/ship_riot_plate/`
- method: `surfaceforge_three_layer` — recipe `df2/recipes/three_layer_acoustic_forge/generated/recipe_metal_bell_to_free_plate.json`
- corridor: **PASS** · copy-risk: **15.0 dB clear** (nearest P2k_028)
- stats: morph 17.3 dB, Secondary 14.8 dB (real Q-bloom), drift 1.1 cents, wrap 0
- DRAFT: **ADOPT AS BASELINE** for the LucifersQ/violent slot. The "modal well not simmed" blocker
  is half-false: the recipe forge is a working modal path today. Run the neural-resonator sim later
  only if this body's density/taste falls short.
- TYSON:

## 3. ship_drive_teeth — the distortion driver that failed for staticness

- artifact: `df2/dev/tmp/exhausted_shipping_filters_locked/ship_drive_teeth/`
- method: `analytic_rc_driver` (cleanroom RC time constants)
- corridor: **FAIL** — endpoint terrain below floor, no leader canyon/pole motion · copy-risk 12.5 dB clear
- DRAFT: **BURY THE BODY, KEEP THE LESSON.** The FuzziFace redefinition must add MOTION (leader
  lanes that travel ≥1 oct), not a hotter pole. An RC-only small-signal story is proven insufficient —
  consistent with the audit's physics finding (no resonator in a fuzz circuit).
- TYSON:

## 4. ship_pinna_needle — HRTF attempt #1

- artifact: `df2/dev/tmp/exhausted_shipping_filters_locked/ship_pinna_needle/`
- method: `trench_filters_hrtf_rails`. refs: az210_el+00 → az000_el+00
- corridor: **FAIL** — never reaches hot-pole corridor; Secondary contrast too weak (5.21 < 5.7 floor)
  · copy-risk 19.5 dB clear
- but: morph contrast **27.7 dB** (best of the locked four), drift 0.39 cents, wrap 0
- DRAFT: **SALVAGE PARTS.** The direction-pair morph is strong; the failure is exactly the audit's
  Q-void (fig 1). Re-author on the same skeleton with the declared radius policy (comb lanes → r≈0.990)
  and this likely becomes the Alkaline ship body.
- TYSON:

## 5. hrtf_registered_lanes — the "missing" lane lift, already built

- artifact: `df2/dev/tmp/hrtf_registered_lanes/` (.body240, plots, sweep wav, report.json, SUMMARY.md)
- method: notch tracking → body-realizable root-manifold compression → 6 registered pole/zero lanes.
  Proof status PASS; packed notch survival 65% (Q0) / 67.5% (Q100); oracle projection RMS 4.91 dB
- corridor: **FAIL** — morph 4.12 dB and Secondary 2.33 dB both under floors; never reaches hot corridor
  · copy-risk 11.0 dB clear
- DRAFT: **ADOPT THE METHOD, ITERATE THE BODY.** This is the audit's blocking-probe #4 already
  implemented. Combine with pinna_needle's hotter direction pair + radius policy; audit item 5
  (lane correspondence) is solved by this code path, not by new design work.
- TYSON:

## 6. fuzzi_face_01..08 — eight corridor-passing FuzziFaces of unknown lineage

- artifact: `df2/dev/tmp/fuzzi_face/` (8 × .body240 + cart.json + response png + morph/qsweep wavs + fuzzi.html)
- corridor: **ALL 8 PASS** (2026-07-03) · copy-risk: **35–39 dB clear** (nearest is P2k_015, not P2k_007 —
  these are not ROM restatements)
- provenance: cart says `direct-packed-240`, no source tags. **UNKNOWN lineage** — cite-or-refuse
  means none can ship until the authoring method is reconstructed (check the session that made
  them, or re-derive equivalent bodies through morph_designer with citations).
- caution: fuzzi_face_07 peaks near **+100 dB** at M100_Q100 on the packed probe (within the
  corridor's 150 dB span ceiling, but gain-stage carefully at audition — the AGC will be doing
  heavy lifting).
- DRAFT: **AUDITION NOW, RECONSTRUCT LINEAGE BEFORE SHIP.** If one of these is the sound,
  the FuzziFace KILL verdict converts to "re-derive this body legally."
- TYSON:

## 7. Evidence sources to mine (not bodies)

- `trench_re_vault/datasets/talking_hedz_x3_surfaces/` (18 MB, 2026-03-12) — response surfaces
  measured from the real X3. Candidate legal source for archetype-Q policy ("runtime-probed
  aggregate statistics", df2 CLAUDE.md §7) — could upgrade the radius-policy memo from
  ROM-decode-derived to measurement-derived. Also stage0/bracketed_residual captures (~9 MB).
- `trenchwork_clean2|fresh|recovered/datasets/` (~2.2 MB ×3, near-identical) — filter_inventory,
  behavior_targets, atlas_curation, product_specs, p2k_filter_usage. Mine product_specs +
  usage data for the roster decision (audit item 9); then pick ONE copy as canonical and
  mark the other two stale.
- `df2/dev/tmp` holds 327 experiment dirs total. This ledger covers the ship-critical ones;
  `forge_*`, `hedz_slam_*`, `corner_library`, `cleanroom_p2k_replacements` are the next tier
  if a slot still lacks a baseline after the decisions above.

---

## Standing rule this ledger encodes

Before any new body is authored for a slot: search dev/tmp + the vault for prior attempts at
that slot, and either adopt or bury them **in writing, here**. A buried body keeps one line:
what it was, why it died. That line is what stops the next context from rebuilding it.
