# Modulation overlay: synced LFO / envelope-follower source

## Problem

Modulation today (`ModulateTag.h`) is a binary arm/disarm switch that recalls a
curated per-body `SmartMotion` preset (fixed morph/Q depth + BPM-synced step
pattern via `MotionEngine`). There is no way to see or shape rate/depth, and
no envelope-follower option — every riser, rhythmic vowel-wah adlib chop, or
evolving texture that isn't a pre-baked step pattern has to be built by hand
with host automation. A visible, adjustable, tempo-synced source turns that
from manual labor into a one-control demo.

Separately, 5D (`FiveDTag.h`) is a static on/off toggle for QSound spatial
width with no motion of its own — a "loose end" on the face.

## Decision (from brainstorm with Tyson, 2026-07-07)

1. **Interaction**: clicking the Modulation tag keeps its existing arm/disarm
   behavior and additionally opens a small transient overlay anchored to the
   tag (`juce::CallOutBox`), containing:
   - LFO / Follower radio (2-way choice)
   - Rate slider (meaning depends on mode, see below)
   - Depth slider (existing `motionAmount` param, exposed here — see Grounding)
   The overlay dismisses on click-away; it does not resize the editor or
   become a docked panel. Disarming Modulation closes it.

2. **5D stays on the faceplate, unchanged.** No new checkbox, no relocation.
   When Modulation is armed **and** 5D is on, Space (`ParamID::fiveD`) rides
   the same active source (LFO or Follower) at the same Rate/Depth as
   Morph/Q. When 5D is off, Space is untouched (as today). This is the
   entire scope of "5D gets a real job" — a behavior, not a new control.
   Rejected alternative: a per-target destination checkbox — adds UI for no
   product gain, since Space-riding-along is unconditional on 5D's own
   existing switch.

3. **Two source modes**, both driving the existing modulation-application
   path (`PluginProcessor.cpp` `applyModulationBehavior`, which already
   scales curated `morphDepth`/`qDepth` by `motionAmount`):
   - **LFO**: today's `MotionEngine` BPM-synced step engine. Rate = tempo
     division / free-Hz (existing sync vocabulary — implementation stage
     confirms exact param). This mode reproduces current behavior exactly
     when left at defaults, so arming Modulation does not change the sound
     of any existing preset/session by default.
   - **Follower**: new. A lightweight one-pole peak/RMS envelope follower
     on the plugin's own input (no sidechain), written directly alongside
     `MotionEngine` in C++ — not by wiring the unused Rust `PhantomEnvelope`
     (dead code, not FFI-exported; pulling it in is a bigger lift than a
     ~20-line follower that plugs into the same 0..1 modulation-value slot
     `MotionEngine` already fills). Rate = release time (how long the
     modulation takes to fall back after a transient); attack is fixed
     fast. This is a deliberate simplification of `PhantomEnvelope`'s
     6-stage design — "tailor to what we have," not port the full model.

## Grounding (confirmed in code, not assumed)

- Space is **already continuous end-to-end** in the DSP and parameter layer:
  `qsound_spatial.rs::set_space(f32 0..1)` is a genuine wet/dry mix
  (`qsound_spatial.rs:349-351,442-467`), and `ParamID::fiveD` is already an
  `AudioParameterFloat` 0..1 (`TrenchParameters.cpp:73-77`, comment: "The old
  Bool quantized it to on/off"). Only `FiveDTag.h`'s `mouseDown` snaps it to
  0/1 on click. A dev-only continuous slider on the same param already exists
  (`RigPanel.h:30-33`). **Conclusion: making Space a modulation destination
  is a pure control-routing change — zero new DSP work on the Space side.**
- `motionAmount` (`TrenchParameters.cpp:91-95`, float 0..1, default 0.5) is
  already the global depth multiplier applied on top of curated per-body
  `morphDepth`/`qDepth` (`PluginProcessor.cpp:303-304`). The overlay's
  "Depth" slider is this existing parameter, not a new one.
- Curated per-body depths range morphDepth 0.18–0.85, qDepth 0.00–0.85
  (`SmartMotion.h:56-123`) — these stay as the per-body character; Depth
  scales them, it doesn't replace them.
- No generic overlay/modal component exists yet. Three bespoke patterns are
  in use (native `ComboBox` popup in `TypeSelectorView.h`; docked drawer
  `ForgeView` toggled via `setVisible`+editor resize; floating
  `juce::DocumentWindow` in `AuthorView.h`'s `LabWindow`). None fit a small
  transient rate/depth/radio popover without resizing the editor or opening
  a whole OS window, so this introduces one new lightweight
  `juce::CallOutBox` usage — standard JUCE, not new machinery.

## Non-goals

- No per-target destination checkboxes (Morph/Q always modulated when
  armed; Space conditional only on 5D's existing switch).
- No full 6-stage envelope (attack/decay/sustain/release/curve) — single
  Rate (release) knob only.
- No sidechain input — Follower reads the plugin's own signal.

## Verification

- Real build screenshot of the overlay at 1:1, both radio states, per
  project UI law (no mockup claims).
- Packed-runtime/DSP: Schur-stability not applicable (this doesn't touch
  filter coefficients), but the new envelope follower must be checked for
  nonfinite output and sane behavior on silence/full-scale input.
- A/B: bypass vs armed, LFO mode, Follower mode, 5D off vs on while armed,
  slow/fast Rate in both modes — confirms the riser and rhythmic-adlib use
  cases actually work one-control, no hand automation required.
