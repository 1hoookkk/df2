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
        0.0f));  // load at M0.

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::q, 1 },
        "Q",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.0f));

    layout.add (std::make_unique<juce::AudioParameterInt> (
        juce::ParameterID { ParamID::body, 1 },
        "Body",
        0,
        juce::jmax (1, trench::bodyCount() - 1),
        0));

    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::output, 1 },
        "Output",
        juce::NormalisableRange<float> { -24.0f, 24.0f, 0.1f },
        0.0f));  // final user makeup gain, dB — the only level control after the engine.

    // PL-1: extras parameters live behind TRENCH_PLAYER_EXTRAS.
    //
    // Shipping build: these parameters do not exist. The plug-in surface is
    // body / Morph / Q / Output, period — the smallest honest player runtime.
    // Diagnostic / dev build: the parameters are present and processBlock's
    // extras branches run when clean_audio::kEnabled() is flipped off.
    //
    // Input character: OFF (clean identity) or SLAM. EOS/CVSD removed 2026-05-29
    // (dead — the processor derives the input stage from the Slam knob, never
    // CVSD). The two optional effects are SLAM (below) and QSound/5D; everything
    // else loads neutral.
    layout.add (std::make_unique<juce::AudioParameterChoice> (
        juce::ParameterID { ParamID::inputMode, 1 },
        "Input",
        juce::StringArray { "OFF", "SLAM" },
        0));  // default = OFF — clean input reaches the selected body directly.

    // SLAM (Mackie desk drive) + 5D (QSound width) are the only first-class user
    // effects. Both default to a clean bypass — Slam 0 engages no input character,
    // 5D Off is a true spatial bypass — so the resting plug-in stays transparent
    // (neutral default state) until the user reaches for them.
    layout.add (std::make_unique<juce::AudioParameterFloat> (
        juce::ParameterID { ParamID::slamDrive, 1 },
        "Slam",
        juce::NormalisableRange<float> { 0.0f, 1.0f, 0.001f },
        0.0f));

    layout.add (std::make_unique<juce::AudioParameterChoice> (
        juce::ParameterID { ParamID::fiveD, 1 },
        "5D",
        juce::StringArray { "Off", "Narrow", "Wide", "Full" },
        0));  // default = Off — QSound depth is opt-in; Off is a true bypass.

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
