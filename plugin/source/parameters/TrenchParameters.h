#pragma once

#include <juce_audio_processors/juce_audio_processors.h>

namespace ParamID
{
    inline constexpr auto morph     = "morph";
    inline constexpr auto q         = "q";
    inline constexpr auto body      = "body";
    inline constexpr auto slamDrive = "slamDrive";
    inline constexpr auto inputMode = "inputMode";  // 0=OFF, 1=SLAM, 2=EOS (CVSD)
    inline constexpr auto fiveD     = "fiveD";       // 5D / QSound toggle: 0=Off, 1=On
    inline constexpr auto output    = "output";      // final makeup gain, dB
    inline constexpr auto amount    = "amount";      // honest dose: 0 = flat/identity (dry), 1 = full effect (wet)

    // Teleport motion mode — shakes/snaps Morph/Q around the host center.
    inline constexpr auto teleportMode       = "teleportMode";       // 0=Off 1=Noise 2=Strobe 3=Deriv
    inline constexpr auto teleportAmount     = "teleportAmount";     // 0..1
    inline constexpr auto teleportRate       = "teleportRate";       // Hz (Noise/Strobe only)
    inline constexpr auto teleportMorphDepth = "teleportMorphDepth"; // 0..1 fraction of amount on Morph
    inline constexpr auto teleportQDepth     = "teleportQDepth";     // 0..1 fraction of amount on Q

    // KEYFRAME RECORDER — the per-wheel user-authored modulation (the one that
    // actually works). Record A (where the wheel is) and B (where you turned it
    // to), set a musical rate, pick a shape. Tempo-synced, driven by
    // trench_keyframe_value. Independent per wheel: morph and q each have their
    // own recording and clock. This is the intended motion system; the sprawling
    // motion*/teleport* params below are the retiring path.
    inline constexpr auto kfMorphOn   = "kfMorphOn";    // bool: MORPH recording armed
    inline constexpr auto kfMorphA    = "kfMorphA";     // 0..1 endpoint A
    inline constexpr auto kfMorphB    = "kfMorphB";     // 0..1 endpoint B
    inline constexpr auto kfMorphBars = "kfMorphBars";  // choice: 1/4,1/2,1,2,4,8,16 bars (one A->B leg)
    inline constexpr auto kfMorphMode = "kfMorphMode";  // choice: Pendulum,Rise,Saw,OneShot
    inline constexpr auto kfQOn       = "kfQOn";        // bool: Q recording armed
    inline constexpr auto kfQA        = "kfQA";         // 0..1 endpoint A
    inline constexpr auto kfQB        = "kfQB";         // 0..1 endpoint B
    inline constexpr auto kfQBars     = "kfQBars";      // choice, as kfMorphBars
    inline constexpr auto kfQMode     = "kfQMode";      // choice, as kfMorphMode

    // Motion — user-facing mode is a predictable tempo-synced Morph sweep.
    // Advanced/host params still exist for experiments, but the faceplate law
    // is Sine -> Morph only and resets phase when armed.
    inline constexpr auto motionOn           = "motionOn";           // bool: arm Motion
    inline constexpr auto motionTargetM      = "motionTargetM";      // bool: MOVE sweeps the Morph wheel (default on)
    inline constexpr auto motionTargetQ      = "motionTargetQ";      // bool: MOVE sweeps the Q wheel (default off)
    inline constexpr auto motionTile         = "motionTile";         // choice: Riser,Breathe,Adlib Chop,Wobble
    inline constexpr auto motionAmount        = "motionAmount";       // 0..1 sweep depth around the Morph wheel
    inline constexpr auto motionShape         = "motionShape";        // choice: Sine,Ramp,Square,Random (advanced)
    inline constexpr auto motionWarp          = "motionWarp";         // morph-curve warp: Off/SquareUp/SquareDown/Step3/Step4
    inline constexpr auto motionCross         = "motionCross";        // 0..1 Morph<->Q cross-modulation
    inline constexpr auto motionReact         = "motionReact";        // 0..1 input-reactive Q push (self-modulation)
    inline constexpr auto motionBpm           = "motionBpm";          // bool: true=sync, false=free Hz
    inline constexpr auto motionRate          = "motionRate";         // 0.25..20 Hz (free mode)
    inline constexpr auto motionDiv           = "motionDiv";          // choice: 1/4,1/8,1/8T,1/16,1/16T,1/32
    inline constexpr auto motionSync          = "motionSync";         // choice: Key, Freerun
    inline constexpr auto motionSmooth        = "motionSmooth";       // bool (EmuX binary)
    inline constexpr auto motionDir           = "motionDir";          // choice: Fwd,Rev,Pend,Rand,Brown,1Shot
    inline constexpr auto motionLength        = "motionLength";       // 1..64 (count; EmuX uses index)
    inline constexpr auto motionMorphDepth    = "motionMorphDepth";   // -1..1 bipolar
    inline constexpr auto motionQDepth        = "motionQDepth";       // 0..1 (gate push)
    inline constexpr auto motionAccentToDrive = "motionAccentToDrive";// bool: gate -> SLAM burst
    inline constexpr auto motionDriveDepth    = "motionDriveDepth";   // 0..1 (only when AccentToDrive on)

    // MOVE — the Body Gesture engine (Page 2). The main UI exposes MOVE + TIME;
    // the shape/matrix/mode vocabulary stays internal/preset-only.
    inline constexpr auto moveOn      = "moveOn";      // bool: arm the gesture (move_enabled)
    inline constexpr auto moveShape   = "moveShape";   // choice: Rise,Fall,Pulse,Orbit,Teeth,Rand,Draw
    inline constexpr auto moveTension = "moveTension"; // 0..1: visible MOVE amount; FREE uses it as phase + intensity
    inline constexpr auto moveTime    = "moveTime";    // choice: FREE,1/4,1/2,1 BAR,2 BAR,4 BAR,8 BAR
    inline constexpr auto moveRate    = "moveRate";    // choice: AUTO,SNAP,TIGHT,GLIDE — morph approach time (patent menu)
    inline constexpr auto keyTrack    = "keyTrack";    // legacy bool; passive suggestions do not automate Key Snap
    inline constexpr auto keySnap     = "keySnap";     // choice: Off, C..B minor, C..B major — all lane resonances land in one scale
    inline constexpr auto bite        = "bite";        // 0..1: BITE — inter-stage soft-clip drive inside the cascade (0 = linear, bit-exact)
    inline constexpr auto clip        = "clip";        // 0..1: CLIP — post-cascade hard clip (drum-bus crunch); hidden host param, no face control
    inline constexpr auto hdMode      = "hdMode";      // bool: HD island — run the unit at 78125 Hz (words re-derived at load); applied at prepareToPlay
    inline constexpr auto moveRise    = "moveRise";    // bool: synced MOVE arms as a 0->full depth ramp over the chosen TIME
    inline constexpr auto moveMode    = "moveMode";    // internal/preset-only legacy mode
    inline constexpr auto movePhase   = "movePhase";   // 0..1: static phase rotation (optional)
    inline constexpr auto moveSwing   = "moveSwing";   // 0..1: delay off-beats (optional)
    inline constexpr auto moveDrift   = "moveDrift";   // 0..1: scales the DRIFT source
    // The 4x4 routing matrix (16 cells) is NOT automatable in V1 — it lives in plugin
    // state (apvts.state "moveMatrix"), factory defaults per gesture.
}

namespace TrenchParameters
{
    juce::AudioProcessorValueTreeState::ParameterLayout createParameterLayout();
}
