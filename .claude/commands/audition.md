---
description: Render every body through the shipped engine and open the audition page. The listen-loop one-keystroke escape from FL/DLL caching purgatory.
argument-hint: "[bodies-dir]  (optional, default: bodies/crazy)"
---

You are running the **listen loop**: render → audition → human ear judges. This
is the only fitness function for df2 bodies. Do NOT score, rank, or grade — the
ear chooses.

## What this does

`tools/render_audition.py` runs an 808 through every body in `bodies/crazy/`
(plus `bodies/proofs/metallic_vowel_target.json` if present) via the SHIPPED
engine (AGC + saturate, through `trench_ffi`), at 5 positions back-to-back:

  HOME · MORPH · TENSION · MORPH+TENSION · MIDDLE

Output lands in `dev/tmp/audition/` as one WAV per body plus an `audition.html`
page that lets the user A/B them.

## Steps

1. **If user passed `$ARGUMENTS`** (a different directory like `bodies/factory`
   or a campaign like `dev/tmp/sweep/roster_0528`), point them at the right
   tool — `render_audition.py` is currently hardcoded to `bodies/crazy/`.
   If `tools/sweep_roster.py` or a per-campaign `audition.html` already exists
   in that path, just open it. Don't silently render the wrong directory.

2. **Verify pyruntime FFI is reachable** before rendering. If `trench_ffi.engine_available()`
   returns False the script falls back to a Python cascade (no AGC). That fallback
   is fine for a sanity check but **WARN the user** — the AGC is where the E-mu
   character lives (table indices 4–7, mults 0.92 / 0.50 / 0.20 / 0.16). Without
   AGC bodies sound clinical/dry. Do not let the user judge in fallback mode.

3. **Run the renderer**:
   ```bash
   python -m tools.render_audition
   ```
   Surface the path it printed (`open: …/dev/tmp/audition/audition.html`).

4. **Do NOT** rebuild the VST3, restart FL, or touch the JUCE shell. This is
   the audition path — it bypasses the host entirely.

5. **Report**: how many clips, whether the SHIPPED engine path was used
   (look for "SHIPPED engine (AGC+saturate)" in stdout vs. "Python cascade
   fallback"), and the audition.html path. Nothing else.

## Hard rules

- **Do not rank.** No "the best is body X." The ear is the boss
  ([forge-interactive-judgment-not-scoring]). Render, surface, let the user
  pick.
- **Do not propose new generators.** The listen loop's job is to find what
  *already* exists that hits. New mechanisms are a different command.
- **Do not break the body strip path.** The player has ONE load path
  (`Body strip → roster → loadCartridge`). Audition output stays in
  `dev/tmp/audition/` — never copied into `juce-shell/assets/cartridges/`
  without the user explicitly marking KEEP.

## If something's broken

- `pyruntime/trench_ffi` import error → the FFI binding fell out of sync with
  `trench-core`. Check `cargo build --manifest-path trench-core/Cargo.toml`
  succeeded recently. Suggest a rebuild, don't silently fall back.
- Empty `bodies/crazy/` → nothing to audition. Surface this, ask what
  campaign/directory the user actually wants to listen to.

## After the page opens

The producer (Tyson) marks KEEP / MAYBE / TRASH by ear. *That's the input to
the next round.* Wait for him to come back with picks. Don't ask leading
questions ("what did you think of N?"); let the ear decide.
