# NOW

The only file that changes session-to-session. Rewrite the top half
every time. Keep the bottom half stable.

---

## This session — 2026-05-28 late (next AI: start here)

**READ STATE.md TOP ENTRY FIRST.** It has the full picture. Brief summary:

**Strategic position:** Tyson is exhausted, wants a fresh-eyes audit of the
codebase. A complete audit prompt for an external AI is in the conversation
transcript — proposes three rebuild paths. My read is Option B (rewrite the
JUCE shell, keep `trench-core`) — every bug found today lives in the JUCE C++,
the Rust core is solid.

**What shipped:** 7 new originals baked into the player (Voice Walk, Mason
Tube, Knock Burst, Metal Scream, Phaser Slide, Cut Edge, Maul). Plus a body-
strip bug fix that unlocked the other 45 baked bodies (clicks were collapsing
to index 0 or 1 only). VST3 rebuilt + installed to Program Files.

**The real blocker:** FL Studio was running continuously since May 25 — every
rebuild today was loaded into a process that wouldn't release the cached DLL.
Tyson needs to kill `FL64.exe` in Task Manager and reopen FL to actually load
today's work.

**Critical things to know next session:**
- AGC engages at +22 to +28 dB filter peaks (table indices 4–7). Below +15 dB
  it's dormant and bodies sound clinical.
- Engine ceiling: 12 poles + 12 zeros per corner (240-byte format, X3 parity
  is the patent anchor — don't break).
- Mud is broad-Q low-freq peaks, not narrow razor poles. Balance rule (low-mid
  peak ≤ mid+treble peak) is the real cull.
- Dev iteration must use Standalone or AudioPluginHost — never FL. Windows
  caches DLLs in the host process until full exit.
- Latent display bug still in `TrenchResponseDisplay.cpp` (`kBodyNames[4]`
  hardcoded). Cosmetic, not blocking.

**DO NEXT:**
1. Confirm `FL64.exe` is killed and FL reopened so the rebuilt plugin actually
   loads.
2. Have Tyson audition the 7 originals + Forge Audition vocal swaps on real
   source (808 / vocal / drum loop), not synthetic test tones.
3. If Tyson decides on the rebuild, hand him the audit prompt from the
   transcript and let an external AI produce the AUDIT.md + REBUILD_PLAN.md.
4. Otherwise: fix the `TrenchResponseDisplay` latent display bug, sort the
   two-VST3-install-path issue (delete LOCALAPPDATA copy), and start working
   through the bodies he marks as KEEP.

---

## ARCHIVE: previous "This session" — 2026-05-28 evening (FILTER TYPE CARDS)

**MISSION: a body is a named FILTER TYPE. The producer picks a class + card, optionally
a reference inside it, and listens. Code generates, culls, and frames as named machines.
Do NOT invent another authoring engine — this is a front door over the proven generators.**

**Read first:** `CLAUDE.md` (doctrine) -> `STATE.md` top entry -> this file.

**THE ONE WORKFLOW (producer front door):**
1. `python -m tools.make_class_bodies --list` (cards) · `--list-classes` (taxonomy).
2. `python -m tools.make_class_bodies --class EQ_CUT --campaign razor_shell --count 64 --seed 1001`
   -> whole 4-corner bodies, hard-culls broken, publishes survivors to
   `bodies/generated/gen_<campaign>_s<seed>_NN.bin`, writes a **purely musical**
   `dev/tmp/target_browser/<campaign>_s<seed>/audition.html` (card header + Candidate NN +
   KEEP/MAYBE/REJECT — no DSP on the surface).
   Add `--reference [slug]` to shape the card from a P2K reference (A/B preview page, never copied).
3. Listen, mark KEEP/MAYBE/REJECT, then:
   `python -m tools.make_class_bodies --keep <run_dir> cand_07 --notes "why it wins"`.

**v1 CARDS (`tools/filter_type_cards.json`):** speaker_knockerz · small_talk · razor_shell ·
aluminum_siding · cul_de_sac · glass_throat. Each maps to a `target_templates` archetype +
internal class tags + an optional reference inspiration.

**REFERENCE→ORIGINAL path (`tools/reference_brief.py`):** `--reference razor_blades` extracts a
musical brief from `bodies/rom/P2k_*.json`, generates ORIGINAL bodies, and **rejects any too close
to the reference**. Behaviour only — never copy coefficients/curves/names.

**VERIFIED RUN:** `make_class_bodies --class EQ_CUT --campaign razor_shell --count 64 --seed 1001`
-> 51/64 survived, 51 presets published, audition page DSP-clean.

**HARD RULES:**
- A body is the whole Morph/Q surface: M0_Q0(HOME), M100_Q0(AWAY), M0_Q100(TIGHT HOME),
  M100_Q100(TIGHT AWAY). Generate from cards/archetypes; the 4 corners are KIN by construction.
- NO stage roles / topology-locked pole bands (the stage-authoring trap — rejected this session).
- Gates cull broken only (unstable/non-finite/pedestal/clip/no-motion). Drift/chaos/off-target +
  similarity are advisory. The EAR is the boss; the avoided step is curation, not more generators.
- No coefficients/poles/packed words/stages/Q-numbers on the producer surface. No E-mu/Morpheus/
  Z-plane branding product-facing. Commercial release needs legal review.

**OVERNIGHT SWEEP DONE — audition queue waiting:** `dev/tmp/sweep/roster_0528/audition.html`.
Six families (Vocal/Cavity/Resonant/Knock/Comb/Cut), bold twin-anchor (HOME & AWAY genuinely
different, ~32 dB apart; tame→violent), 900 survivors / 1152, 16 shortlisted each (96 total),
all stable. Per-family readouts in `dev/tmp/sweep/roster_0528/families/*.md`.

**DO NEXT:** open `dev/tmp/sweep/roster_0528/audition.html`, A/B HOME→AWAY (should be genuinely
different now), mark KEEP/MAYBE/REJECT, run the per-body keep command shown on each card to lock a
v1 body per family. The shortlist order is a soft pre-sort, not a verdict — the ear chooses.
Re-run a family bolder/again: `python -m tools.sweep_roster --sweep <id> --family <fam> --seeds .. --count ..`
then `--merge`. Do not promote bodies before the ear chooses.

---

## v1 boundary

Four bodies shipped in compiled-v1 cartridges, loaded by the JUCE shell.
Personal distribution / closed beta first. wgpu visualization is not
present in this checkout and should not block the first body audition.

| Ships in v1                  | Defer to v1.5+              |
|------------------------------|-----------------------------|
| 4 bodies                     | Snapshot capture plugin     |
| JUCE shell + cartridge load  | Public forge / Filter Factory release |
| JUCE response display        | More bodies                 |
| Internal forge (Tyson only)  | Inspect panels / diagnostics UI |

**4 bodies target:** Speaker Knockerz, Aluminum Siding, Small Talk,
Cul-De-Sac. Current tracked body+cartridge pairs exist for Small Talk
and Speaker Knockerz; see `bodies/` for truth.

---

## Strategic pin

- **Revenue model:** plugin once, cartridges recurring.
- **Moat:** Filter Factory is private. The fact that only Trenchwork
  can produce Trenchwork bodies is the product.
- **Risk surface:** Rossum US10,514,883 active ~2038. Rossum Electro
  actively sells Morpheus Eurorack. Personal-distribution beta is the
  low-risk path; commercial release needs attorney.
- **Audience filter:** plugin is opaque on purpose. If a producer needs
  it explained, they're not the buyer.
- **Names:** Trenchwork (company), df2 (product), 1hook (music). No
  E-mu / Z-plane / Morpheus references in anything user-facing.

---

## Out of scope this quarter

PhantomVoice. QSound. MorphDesigner. Type 2/Type 3 compiler. template
parsing. SQLite archaeology. Public Forge. Inspect. UI metaphor work.
Brand exploration. ARMA extractor (gated by synthetic notch test that
hasn't been justified yet).

If one of these comes up: not now.
