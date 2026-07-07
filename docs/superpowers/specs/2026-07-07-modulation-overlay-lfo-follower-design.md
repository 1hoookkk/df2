# Modulation grid: CRT-transition, per-body curated moves

## Problem

Modulation today (`ModulateTag.h`) is a binary arm/disarm switch. Clicking it
silently auto-selects one of two hidden engines based on the current body's
*name* (`defaultOnBehaviorForCurrentBody()`: bodies named "smooth"/"rise" get
a BPM-synced sweep; everything else gets an envelope-follower reactive mode)
with fixed, non-adjustable depth. There is no way to see or choose the
behavior, and no envelope-follower option is exposed as such — every riser,
rhythmic vowel-wah adlib chop, or evolving texture that isn't the one
auto-picked pattern has to be built by hand with host automation.

## Decision (brainstorm with Tyson, 2026-07-07 — supersedes the original
overlay/radio-button draft of this spec)

1. **Interaction**: clicking the Modulation tag triggers an old-CRT
   power-off transition on the main screen (`GraphDisplay` — the response
   curve view), then that same screen shows a **2x2 grid of four crude
   pictogram tiles** instead of the curve. Tapping a tile arms Modulation
   with that move and CRT-transitions back to the curve. Tapping the
   currently-lit tile again turns Modulation off (same tap-to-toggle
   language the switch already uses today) and returns to the curve. This
   is a deliberate, scoped exception to the LOCKED "quiet glass, one trace"
   screen law (CLAUDE.md §0.1.5) for the duration of this one interaction —
   the curve view itself is unchanged; nothing is permanently added to it.

2. **Four tiles, fixed identity and position across every body** (so the
   grid stays learnable — you always know where "Riser" is):
   - **Riser** — today's `AutoHalf` behavior (Fwd direction, ascending,
     tempo-synced).
   - **Breathe** — today's `AutoQuarter` behavior (Pendulum direction, slow
     evolving swell, tempo-synced).
   - **Adlib Chop** — today's `Dynamic` behavior (envelope-follower
     reactive; follows the plugin's own input transients, not tempo).
   - **Wobble** — **new**. Random/Brownian step direction
     (`MotionEngine::advanceStep` cases 3/4 — fully implemented, never
     invoked by any curated preset today). Unpredictable jump character,
     distinct from Adlib Chop's smooth envelope-follow and from Riser/
     Breathe's tempo-locked sweep.
   - (Considered and dropped for this pass: **Swell** / one-shot direction
     — needs retrigger semantics the other three don't; out of scope for a
     2x2.)

3. **Content is curated per body**, extending the existing per-body switch
   in `SmartMotion.h` (`smartMotionFor`, currently one curated identity per
   body via `switch (bodyIndex % 4)`) from one entry to four — one per tile,
   tuned to that body's character, the same way Talking Hedz/Millennium/
   Ear Bender/Lucifer's Q already get distinct morph/Q depths and patterns
   today. The tile *label and position* stay fixed; the *values underneath*
   are body-specific.

   To keep authoring tractable (16 total: 4 bodies x 4 tiles), each tile is
   a **fixed shape** — direction, division, pattern, and a fixed morph:Q
   ratio that is the same for every body (e.g. Riser is always mostly-morph,
   Adlib Chop is always mostly-Q). The only per-body-per-tile authored value
   is a single **Amount** scalar (0.0-1.0) that scales that fixed shape up
   or down — the same semantics as the existing public `motionAmount`
   lever, just captured in a small per-body-per-tile table instead of one
   global slider:

   ```
                    Riser   Breathe   AdlibChop   Wobble
   Talking Hedz      ?         ?          ?           ?
   Millennium        ?         ?          ?           ?
   Ear Bender        ?         ?          ?           ?
   Lucifer's Q       ?         ?          ?           ?
   ```

   Tyson fills this table in by ear once the mechanism is running; the plan
   ships with placeholder Amount values (reusing each body's existing single
   curated depth as the starting point for all 4 tiles) that are explicitly
   marked as starting points, not final tuning.

4. **5D unchanged on the faceplate.** No new checkbox, no relocation. When
   Modulation is armed (any tile) **and** 5D is on, Space (`ParamID::fiveD`)
   rides the same modulation offset as Morph/Q. When 5D is off, Space is
   untouched. This is the entire scope of "5D gets a real job."

5. **No separate Rate/Depth sliders.** Each tile already encodes a
   complete, tuned move (direction, division, depths, pattern). The
   existing `motionAmount` parameter remains the one continuous "how much"
   lever exactly as it works today — untouched by this feature, not part of
   the new grid.

6. **5D gets a per-body baked base amount, not just max-on.** Today
   `FiveDTag::mouseDown` (`FiveDTag.h:43-49`) snaps the continuous `fiveD`
   parameter to a hardcoded `0.0f`/`1.0f` on click — "on" is always full.
   Instead, "on" should snap to a **per-body curated amount** (a small
   table, same shape as the Amount table above), so each body/preset's 5D
   can be dialed to whatever depth suits it. The dev-only `RigPanel.h`
   slider (already wired straight to `fiveD` for exactly this "audition by
   ear, then bake it" workflow) is the tool Tyson uses to find each body's
   number; this feature just makes `FiveDTag` recall that number when
   toggled on instead of always jumping to 1.0. This is independent of, and
   stacks with, decision 4's ride-along (ride-along adds an offset on top
   of whichever base amount is active).

## Grounding (confirmed in code)

- `TypeBehavior` (`TrenchBodyRoster.h:27-33`) currently has 4 values:
  Static, Dynamic, AutoQuarter, AutoHalf. Adding **Wobble** as a 5th value.
- `ModulateTag::mouseDown`/`setBehavior` (`ModulateTag.h:48-59,180-209`)
  currently picks Dynamic vs Auto* by string-matching the body's display
  name (`defaultOnBehaviorForCurrentBody`, `autoBehaviorForCurrentBody`).
  This logic is replaced by an explicit tile pick from the new grid.
- `SmartMotion.h:53-126` (`smartMotionFor`) already curates morphDepth/
  qDepth/divIdx/direction/length/smooth/pattern per body for whichever
  single behavior is active. Extending its `switch (bodyIndex % 4)` cases to
  return one of 4 tuned identities per body (selected by the new tile
  index) is the only content-authoring work required — no new DSP.
- `MotionEngine::advanceStep` (`MotionEngine.h:152-178`) already implements
  all 6 direction modes including Random (case 3) and Brownian (case 4).
  Wobble uses these directly — zero engine changes needed, only a new
  curated `SmartMotion` entry with `direction = 3` or `4`.
- Space (`ParamID::fiveD`) is **already continuous end-to-end**:
  `qsound_spatial.rs::set_space` is a genuine wet/dry mix
  (`qsound_spatial.rs:349-351,442-467`), `ParamID::fiveD` is already an
  `AudioParameterFloat` 0..1 (`TrenchParameters.cpp:73-77`). Only
  `FiveDTag.h:47`'s `mouseDown` snaps it to 0/1 on click — the tag itself is
  unchanged by this feature; the ride-along logic reads/writes the existing
  continuous parameter alongside Morph/Q in `applyMotion`.
- `PluginProcessor::applyMotion` (`PluginProcessor.cpp:269-380`) already
  computes a per-block modulation offset for both the Dynamic (`push`,
  line 315) and Auto* (`r`/`smoothedOffsetMorph`/`smoothedOffsetQ`, lines
  344-350) paths; this needs a 4th `ModulatedControls` field (`space
  offset`) so the fiveD-read call site (`PluginProcessor.cpp:669-672`) can
  apply the same offset to Space when 5D is on.
- No generic overlay/modal component exists in `juce-shell/source/ui/`.
  This feature introduces a new `GraphDisplay`-owned mode switch (curve vs.
  grid) plus a small CRT-transition helper, not a popup/CallOutBox.

## Non-goals

- No Rate/Depth sliders, no LFO-vs-Follower radio (superseded by the tile
  model).
- No per-target destination checkboxes for 5D (unconditional ride-along
  only, per decision 4).
- No Swell/one-shot tile in this pass.
- No changes to Page 2 MOVE (separate, already-shipped system; not reused
  or absorbed here).

## Verification

- Real build screenshot at 1:1: curve view, CRT-collapse mid-transition,
  grid view, each of the 4 tiles lit, per project UI law (no mockup
  claims).
- Per body (all 4 shipping bodies): confirm each of the 4 tiles sounds
  distinct and fits that body's character — this is an ear judgment, not a
  plot.
- DSP: `applyMotion`'s new Wobble branch and the new `space` output field
  must be checked for nonfinite output and sane behavior on silence/full-
  scale input, same bar as the existing Dynamic/Auto* branches.
- A/B: bypass vs each tile armed, 5D off vs on while armed, tile-to-tile
  switching, tap-lit-tile-to-disarm.
