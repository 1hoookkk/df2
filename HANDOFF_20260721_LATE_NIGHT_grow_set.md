# TRENCH handoff — 2026-07-21 late night — GROW THE SET

Read in this order: `FILTER_NOTEBOOK.md` PART 1 (the canon — rebuilt this session;
PART 2 is demoted history), `plugin/presets/approved_bodies.txt` (the curation
authority), then this file. Background: `HANDOFF_20260721_NIGHT_shipping.md`.

---

## 0. DONE this session (proofs, not claims)

- **df2 snapshot committed** — `C:/Users/hooki/df2` HEAD `d0a87561`, 0 uncommitted.
- **Roster frozen.** `PresetRoster.inc` + `PresetRosterSignature.inc` are
  hand-maintained from `approved_bodies.txt`. `preset_gain_fix.rs` roster output
  retargeted to `gain-fix-roster.inc` (scratch; `cargo check` passes).
  `build_measured_cross.py` no longer writes the roster (prints the line for
  manual curation). `.prompts/002-measured-cross-presets.md` = DO-NOT-RUN banner
  (its output IS the rejected measured-cross set; its 20:34 roster append was
  reverted). NOTE: `bank.rs:1586` is a roster READER, not a writer — the old
  handoff was wrong. `consolidate_library.py` / `build_shipping_presets.py`
  do not touch the `.inc` files in current code.
- **Canon rebuilt.** Every claim in FILTER_NOTEBOOK PART 1 tagged
  [LIT]/[PROOF]/[MEASURED]/[LOST]; every cited path verified to exist.
- **Why-pass probe run** (n=18, packed-runtime decode): signature recorded as
  canon **L9**. Analyzer: `dev/tmp/why_pass_20260721/analyze.py` (reuses
  `tools/prove_master_body.py` bindings; run: `python dev/tmp/why_pass_20260721/analyze.py`).

## 1. STATE you can rely on

- Approved = 2 families: `ship_v2` (11 bodies, in `plugin/presets/bodies/`) and
  `master_body_trial` (9 bodies, in `dev/tmp/master_body_trial_20260720/` —
  NOT currently in the plugin bodies dir; the Documents\TRENCH shelf folders
  from the old handoff are gone).
- Roster `.inc` files currently hold the committed 19 rejected heroes — that's
  the stale committed state, not approval. Approval lives ONLY in
  `approved_bodies.txt`. Selector work (Phase 3) reconciles this.
- **"Hedz to Gong" has NO artifact** — no such stem anywhere. Tyson floated
  "hedz to bell?" — unconfirmed either way. Do not ship `hedz_vowel_ah_ee`
  (explicitly failed). If the name matters it must be AUTHORED, then pass the
  gates below, then his ear.

## 2. THE NEXT PHASE — grow the ship set (Phase 2 of the agreed plan)

Tyson locked: **grow first, then ship.** Three workstreams, cheapest first:

### A. Surgical candidates (cheapest path to approval #3/#4)
`tube_shout` and `throat_bend` pass every mechanical gate (L9: live Q, moving
morph, bounded crown) and were still ear-rejected — the failure is character,
not geometry. Lead from the session log: janky top-end = the zeros/Q100
geometry fix (carve valleys via zeros, never uniform-radius pole surgery —
that was ear-killed). One change per ear round, per Tyson's loop rules.

### B. New measured bodies to the L9 signature
Author through the measured path that produced the passing families
(Dvtd rails / HRTF rails → `tools/compile_frame_voice.py` →
`python -m tools.filter_cli pack`). Every candidate MUST pass the probe
(`analyze.py`) BEFORE it costs Tyson a listen:
- live Q scene — authored Q100 pose, Q travel ≥ ~0.09 oct (L1)
- morph that moves — jerk ≥ ~20 dB across the sweep
- crown ≤ +27 dB — body-wide SCALE trim only (L3/L4)
The probe kills; it never promotes. Promotion = Tyson's ear only.

### C. Ear-cull + graduation
Tournament/audition at the live plugin (broadband material). Each keeper gets
added to `approved_bodies.txt` under `[top_level]` — that file is the only
graduation path. Record verdict with date + material (canon §6).

## 3. BANNED moves (all proven tonight or earlier)

- No roster regeneration by any tool. No appending to the `.inc` files.
- Do NOT run `.prompts/002` or author measured crosses of unrelated objects
  (dead Q + jammed material — rejected class).
- Do NOT reopen the ROM-fundamental / frame+voice stage-authoring path
  (verdict 2026-07-21: zero passing presets — "was for nothing").
- Do NOT bound/reshape the 141-body bulk (curation before bounding; bounding
  is Phase 5, on the approved set only).
- Do NOT author from ROM bytes/names (clean-room lock: no ROM-derived ships).
- RULE #1 stands: every number from a table or the toolchain.

## 4. LATER phases (do not start early)

- **Phase 3 — selector:** manifest drives the roster; approved top-level, rest
  dropdowns (`plugin/source/ui/TypeSelectorView.h`). FaceShot at true scale.
- **Phase 4 — selector redesign:** ONE strong tactile/novel prototype, creative
  latitude granted, true plugin scale, then Tyson's verdict.
- **Phase 5 — ship mechanics:** bound approved set only; screen-texture IP
  redraw (`display_bitmap4613.png` et al. are E-mu dump copies — standing
  exposure); UI acceptance gate; packaging.

## 5. OPEN for Tyson (ask when he appears)

1. "Hedz to Gong" vs "hedz to bell" — which name, and does it get authored?
2. Workstream order: surgical (tube_shout/throat_bend) before new authoring?
3. Target set size before Phase 3 selector work starts.

## 6. WARNINGS

- A concurrent agent/session was writing this worktree tonight (minted the 6
  rejected crosses, deleted 9 bodies from `plugin/presets/bodies/` — those
  deletions are uncommitted and LEFT AS-IS; verify `git status` before
  touching anything). If roster files changed under you, `approved_bodies.txt`
  is the authority — restore from it.
- The 6 measured-cross `.body240` files are still on disk in
  `plugin/presets/bodies/` (untracked). Demoted ≠ deleted; leave them.

## ONE-LINE STATE

Foundation is locked (snapshot, roster freeze, canon, manifest). The pass
signature is measured and recorded (L9). Next: grow the approved set through
the measured pipeline with the probe as the pre-ear gate — surgical fixes on
tube_shout/throat_bend first, then new measured bodies. The ear promotes;
nothing else does.
