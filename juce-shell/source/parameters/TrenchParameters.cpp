#include "parameters/TrenchParameters.h"
#include "TrenchBodyRoster.h"

namespace TrenchParameters
{

juce::AudioProcessorValueTreeState::ParameterLayout createParameterLayout()
{
    juce::AudioProcessorValueTreeState::ParameterLayout layout;

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::morph, 1 },
        "Morph",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.5f));  // demo default: useful middle static tone.

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::q, 1 },
        "Q",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.0f));

    layout.add (std::make_unique<juce::AudioParameterInt> (
        juce::ParameterID { ParamID::body, 1 },
        "Body",
        trench::kNoFilterIndex,                    // -1 = No Filter (true bypass) — the clean default
        juce::jmax (1, trench::bodyCount() - 1),
        trench::kDefaultBodyIndex));                // open on Bite Static; motion is opt-in through TYPE.

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::output, 1 },
        "Output",
        juce::NormalisableRange<float> { -24.0f, 24.0f, 0.1f },
        0.0f));  // final user makeup gain, dB — the only level control after the engine.

    // AMOUNT — the honest dose. Crossfades the flat/identity dry signal (0) to the
    // full effect (1). Not a volume knob: it doses effect intensity so the weirdness
    // stays usable in a session. Default 1.0 = full effect (no change to existing sound).
    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::amount, 1 },
        "Amount",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        1.0f));

    // PL-1: extras parameters live behind TRENCH_PLAYER_EXTRAS.
    //
    // Shipping build: these parameters do not exist. The plug-in surface is
    // body / Morph / Q / Output, period — the smallest honest player runtime.
    // Diagnostic / dev build: the parameters are present and processBlock's
    // extras branches run when clean_audio::kEnabled() is flipped off.
    //
    // Legacy host/input selector. The shipped processor keeps the Mackie
    // front-end in circuit and uses Slam as the one input-gain control; true
    // clean is plug-in bypass, not Slam=0.
    layout.add (std::make_unique<juce::AudioParameterChoice> (
        juce::ParameterID { ParamID::inputMode, 1 },
        "Input",
        juce::StringArray { "OFF", "SLAM" },
        0));  // default = OFF — clean input reaches the selected body directly.

    // SLAM is output-only in the plug-in. Slam=0 is clean unity after the body;
    // higher values add post-body rounded pressure without changing filter excitation.
    // Default 0.25 gives a mild +3 dB push.
    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::slamDrive, 1 },
        "Slam",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.25f));

    // Continuous QSound SPACE depth (the engine's set_space takes 0..1; the old
    // Bool quantized it to on/off). 0 = true bypass (spatial stage Off). The
    // voicing rig sweeps this so per-preset depths can be chosen by ear.
    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::fiveD, 1 },
        "Space",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.0f));

    // ── Motion ────────────────────────────────────────────────────────────────
    // Faceplate behavior: a predictable tempo-synced Sine sweep on Morph only,
    // with phase reset when armed. The 64-step pattern machinery remains below
    // for recall/host experiments, but Q/drive/chaos are not secretly enabled by
    // the visible Motion button.
    layout.add (std::make_unique<juce::AudioParameterBool> (
        juce::ParameterID { ParamID::motionOn, 1 },
        "Motion",
        false));  // default = Off — no motion until armed.

    // Explicit tile pick — replaces the old body-name-based auto-selection.
    // Grid position is fixed across all bodies; the curated values behind
    // each name are per-body (see SmartMotion.h kTileAmount).
    layout.add (std::make_unique<juce::AudioParameterChoice> (
        juce::ParameterID { ParamID::motionTile, 1 },
        "Motion Tile",
        juce::StringArray { "Riser", "Breathe", "Adlib Chop", "Wobble" },
        0));  // default = Riser.

    // The one public Motion lever. Scales the Morph sweep from still (0) to full
    // (1). amount=0 nulls even when armed.
    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::motionAmount, 1 },
        "Motion Amt",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.5f));  // default = half — an armed Cord audibly moves immediately.

    // Advanced LFO shape. The faceplate always writes Sine; hosts can still
    // automate/store other choices deliberately.
    layout.add (std::make_unique<juce::AudioParameterChoice> (
        juce::ParameterID { ParamID::motionShape, 1 },
        "Motion Shape",
        juce::StringArray { "Sine", "Ramp", "Square", "Random" },
        0));  // default = Sine.

    layout.add (std::make_unique<juce::AudioParameterBool> (
        juce::ParameterID { ParamID::motionBpm, 1 },
        "M.BPM",
        true));  // default = sync to host BPM.

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::motionRate, 1 },
        "M.Rate",
        juce::NormalisableRange<float> { 0.25f, 20.0f, 0.01f, 0.5f }, // skew toward slow
        4.0f));  // 4 Hz default in free mode.

    layout.add (std::make_unique<juce::AudioParameterChoice> (
        juce::ParameterID { ParamID::motionDiv, 1 },
        "M.Div",
        juce::StringArray { "1/4", "1/8", "1/8T", "1/16", "1/16T", "1/32", "1/2", "1 BAR", "2 BAR", "4 BAR" },
        3));  // default = 1/16. Bar values appended at the end (6-9) so the
              // existing 0-5 fast-subdivision indices keep their meaning.

    layout.add (std::make_unique<juce::AudioParameterChoice> (
        juce::ParameterID { ParamID::motionSync, 1 },
        "M.Sync",
        juce::StringArray { "Key", "Free" },
        1));  // default = Free (freerun from play start).

    layout.add (std::make_unique<juce::AudioParameterBool> (
        juce::ParameterID { ParamID::motionSmooth, 1 },
        "M.Smooth",
        false));  // EmuX smooth is binary; default stepped.

    layout.add (std::make_unique<juce::AudioParameterChoice> (
        juce::ParameterID { ParamID::motionDir, 1 },
        "M.Dir",
        juce::StringArray { "Fwd", "Rev", "Pend", "Rand", "Brown", "1Shot" },
        0));  // default = Forward.

    layout.add (std::make_unique<juce::AudioParameterInt> (
        juce::ParameterID { ParamID::motionLength, 1 },
        "M.Len",
        1, 64,
        16));  // default = 16 active steps.

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::motionMorphDepth, 1 },
        "M.Morph",
        juce::NormalisableRange<float> { -1.0f, 1.0f, 0.001f },
        0.0f));  // bipolar; 0 = null.

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::motionQDepth, 1 },
        "M.Q",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.0f));  // gate/accent push; 0 = null.

    layout.add (std::make_unique<juce::AudioParameterBool> (
        juce::ParameterID { ParamID::motionAccentToDrive, 1 },
        "M.Acc->Drv",
        false));  // advanced: gate -> explicit SLAM burst. Off by default.

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::motionDriveDepth, 1 },
        "M.Drv",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.5f));  // only active when AccentToDrive is on.

    // ── Motion "abuse" cluster — host/advanced only ───────────────────────────
    // All default neutral. The faceplate also rewrites these to neutral on arm
    // so the visible control never feels random.
    layout.add (std::make_unique<juce::AudioParameterChoice> (
        juce::ParameterID { ParamID::motionWarp, 1 },
        "Motion Warp",
        juce::StringArray { "Off", "Square Up", "Square Down", "Step 3", "Step 4" },
        0));  // Off = linear morph trajectory.

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::motionCross, 1 },
        "Motion Cross",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.0f));  // 0 = no Morph<->Q cross-coupling.

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::motionReact, 1 },
        "Motion React",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.0f));  // 0 = filter does not react to input level.

    // ── MOVE — the Body Gesture engine (Page 2) ───────────────────────────────
    layout.add (std::make_unique<juce::AudioParameterBool> (
        juce::ParameterID { ParamID::moveOn, 1 },
        "Move",
        false));  // internal/preset-only; FREE+Move=0 is clean on load.

    layout.add (std::make_unique<juce::AudioParameterChoice> (
        juce::ParameterID { ParamID::moveShape, 1 },
        "Shape",
        juce::StringArray { "Lift", "Suck", "Wash", "Orbit", "Pulse", "Teeth", "Drift" },
        0));  // default = Lift (build). Section-movement jobs.

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::moveTension, 1 },
        "Move",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.0f));  // default = still; in FREE this is direct gesture phase + intensity.

    layout.add (std::make_unique<juce::AudioParameterChoice> (
        juce::ParameterID { ParamID::moveTime, 1 },
        "Time",
        juce::StringArray { "FREE", "1/4", "1/2", "1 BAR", "2 BAR", "4 BAR", "8 BAR" },
        0));  // default = FREE: no timeline, MOVE is manual.

    layout.add (std::make_unique<juce::AudioParameterChoice> (
        juce::ParameterID { ParamID::moveMode, 1 },
        "Move Mode",
        juce::StringArray { "Arm", "Live", "Hold", "Loop" },
        3));  // internal/preset-only; synced Page 2 uses LOOP in V1.

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::movePhase, 1 },
        "Move Phase",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.0f));  // static phase rotation of the gesture.

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::moveSwing, 1 },
        "Move Swing",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.0f));  // 0 = straight; delays off-beats on rhythmic shapes.

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::moveDrift, 1 },
        "Move Drift",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.0f));  // scales the DRIFT source feeding the matrix.
    // NOTE: the 16 matrix cells are state, not params (V1) — no route_* automation.

#ifdef TRENCH_PLAYER_EXTRAS
    // ── Teleport motion mode ──────────────────────────────────────────────────
    layout.add (std::make_unique<juce::AudioParameterChoice> (
        juce::ParameterID { ParamID::teleportMode, 1 },
        "Teleport",
        juce::StringArray { "Off", "Noise", "Strobe", "Deriv" },
        0));  // default = Off — violent motion is opt-in.

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::teleportAmount, 1 },
        "Tport Amount",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.0f));  // zero by default — no motion until the user dials it in.

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::teleportRate, 1 },
        "Tport Rate",
        juce::NormalisableRange<float> { 0.1f, 30.0f, 0.01f, 0.4f }, // skew toward low rates
        4.0f));  // 4 Hz default — slow enough to hear the snap clearly.

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::teleportMorphDepth, 1 },
        "Tport M.Depth",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        1.0f));  // full morph-axis depth when active.

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::teleportQDepth, 1 },
        "Tport Q.Depth",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        1.0f));  // full Q-axis depth when active.
#endif // TRENCH_PLAYER_EXTRAS

    return layout;
}

} // namespace TrenchParameters
