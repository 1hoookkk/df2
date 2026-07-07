// AMOUNT — the honest dose. Proves:
//   amount=0  -> output is CLOSE to the flat/identity dry signal, delayed by the
//               island's SRC latency so it aligns with the wet path.
//   amount=1  -> output is the full effect (the body actually changed the signal).
// Implementation: a per-stage coefficient blend toward identity inside the
// engine (trench-core FilterEngine::set_amount), not a post-filter audio
// crossfade — so the on-screen curve (read from the same coefficients) moves
// with Amount too. Because AGC sits DOWNSTREAM of the cascade in this engine
// (cascade -> AGC -> boost -> DC blocker), amount=0 is not bit-exact dry: AGC
// is a dynamic, signal-dependent stage that still processes the now-identity-
// filtered signal. 0.06 is the measured, real bound for this architecture,
// not an arbitrary tolerance — bypassing AGC too at low Amount is a separate,
// bigger decision this test intentionally does not make.
// Runs at host rate 44100 (!= the 39062.5 internal rate) so the SRC + its latency
// are genuinely engaged and the latency-matched dry-delay is exercised.

#include <catch2/catch_all.hpp>

#include "PluginProcessor.h"
#include "TrenchBodyRoster.h"

#include <cmath>
#include <vector>

namespace
{
void setP (PluginProcessor& p, const char* id, float v)
{
    if (auto* prm = p.apvts.getParameter (id))
        prm->setValueNotifyingHost (prm->convertTo0to1 (v));
}

std::vector<float> makeInput (int nSamples)
{
    std::vector<float> s ((size_t) nSamples);
    for (int n = 0; n < nSamples; ++n)
        s[(size_t) n] = 0.3f * std::sin (n * 0.05f) + 0.15f * std::sin (n * 0.211f);
    return s;
}

// Run `nBlocks` of `block` samples through the processor at a fixed amount, return
// the mono (L) output concatenated. Smoothers settle within the first few blocks.
std::vector<float> runAmount (PluginProcessor& proc, float amount, const std::vector<float>& in, int block)
{
    setP (proc, ParamID::amount, amount);
    const int nBlocks = (int) in.size() / block;
    std::vector<float> out;
    out.reserve (in.size());
    for (int b = 0; b < nBlocks; ++b)
    {
        juce::AudioBuffer<float> buf (2, block);
        for (int i = 0; i < block; ++i)
        {
            const float x = in[(size_t) (b * block + i)];
            buf.setSample (0, i, x);
            buf.setSample (1, i, x);
        }
        juce::MidiBuffer midi;
        proc.processBlock (buf, midi);
        for (int i = 0; i < block; ++i)
            out.push_back (buf.getSample (0, i));
    }
    return out;
}

double relError (const std::vector<float>& a, const std::vector<float>& ref, int start, int count, int refShift)
{
    double err = 0.0, e = 0.0;
    for (int i = start; i < start + count; ++i)
    {
        const double r = ref[(size_t) (i - refShift)];
        const double d = a[(size_t) i] - r;
        err += d * d;
        e   += r * r;
    }
    return std::sqrt (err / juce::jmax (1.0e-12, e));
}
} // namespace

TEST_CASE ("AMOUNT=0 is honest identity (latency-matched dry); AMOUNT=1 is full effect", "[amount]")
{
    juce::ScopedJuceInitialiser_GUI juce;

    constexpr double sampleRate = 44100.0;   // != internal 39062.5 -> SRC + latency engaged
    constexpr int    block      = 512;

    PluginProcessor proc;
    proc.setRateAndBufferSizeDetails (sampleRate, block);
    proc.prepareToPlay (sampleRate, block);

    // Load a real filtering body and settle the async load.
    setP (proc, ParamID::body, (float) trench::kDefaultBodyIndex);
    juce::MessageManager::getInstance()->runDispatchLoopUntil (80);

    // Isolate the dose: no slam push, unity output, no motion/move.
    setP (proc, ParamID::slamDrive, 0.0f);
    setP (proc, ParamID::output, 0.0f);
    setP (proc, ParamID::motionOn, 0.0f);
    setP (proc, ParamID::moveTension, 0.0f);
    setP (proc, ParamID::fiveD, 0.0f);

    const int latency = proc.getLatencySamples();
    INFO ("island latency = " << latency << " samples");
    REQUIRE (latency >= 0);

    const int nBlocks = 28;
    const auto in = makeInput (nBlocks * block);

    const auto out0 = runAmount (proc, 0.0f, in, block);
    const auto out1 = runAmount (proc, 1.0f, in, block);

    // Settled analysis window: past the latency and the 20 ms amount ramp.
    const int start = latency + 6 * block;
    const int count = 12 * block;
    REQUIRE (start + count < (int) out0.size());

    // amount=0 -> output is close to the dry input delayed by `latency` (identity
    // cascade; residual is AGC still running downstream — see file header).
    const double relIdentity = relError (out0, in, start, count, latency);
    INFO ("amount=0 rel error vs delayed dry = " << relIdentity);
    REQUIRE (relIdentity < 0.06);

    // amount=1 -> the body actually filtered the signal: output clearly differs from dry.
    const double relEffect = relError (out1, in, start, count, latency);
    INFO ("amount=1 rel diff vs delayed dry = " << relEffect);
    REQUIRE (relEffect > 0.10);
}

TEST_CASE ("AMOUNT monotonically approaches flat as it decreases (no mid-sweep bump)", "[amount]")
{
    juce::ScopedJuceInitialiser_GUI juce;

    constexpr double sampleRate = 44100.0;
    constexpr int    block      = 512;

    PluginProcessor proc;
    proc.setRateAndBufferSizeDetails (sampleRate, block);
    proc.prepareToPlay (sampleRate, block);

    setP (proc, ParamID::body, (float) trench::kDefaultBodyIndex);
    juce::MessageManager::getInstance()->runDispatchLoopUntil (80);
    setP (proc, ParamID::slamDrive, 0.0f);
    setP (proc, ParamID::output, 0.0f);
    setP (proc, ParamID::motionOn, 0.0f);
    setP (proc, ParamID::moveTension, 0.0f);
    setP (proc, ParamID::fiveD, 0.0f);

    const int latency = proc.getLatencySamples();
    const int nBlocks = 28;
    const auto in = makeInput (nBlocks * block);
    const int start = latency + 6 * block;
    const int count = 12 * block;
    REQUIRE (start + count < (int) in.size());

    // Deviation from dry at each amount step must be non-increasing as amount
    // decreases toward 0 — no overshoot/bump in the middle of the taper.
    double prevDeviation = 1.0e9;
    for (float amt : { 1.0f, 0.75f, 0.5f, 0.25f, 0.0f })
    {
        PluginProcessor p2;
        p2.setRateAndBufferSizeDetails (sampleRate, block);
        p2.prepareToPlay (sampleRate, block);
        setP (p2, ParamID::body, (float) trench::kDefaultBodyIndex);
        juce::MessageManager::getInstance()->runDispatchLoopUntil (80);
        setP (p2, ParamID::slamDrive, 0.0f);
        setP (p2, ParamID::output, 0.0f);
        setP (p2, ParamID::motionOn, 0.0f);
        setP (p2, ParamID::moveTension, 0.0f);
        setP (p2, ParamID::fiveD, 0.0f);

        const auto out = runAmount (p2, amt, in, block);
        const double deviation = relError (out, in, start, count, latency);
        INFO ("amount=" << amt << " deviation from dry = " << deviation);
        REQUIRE (deviation <= prevDeviation + 0.02); // small slack for measurement noise
        prevDeviation = deviation;
    }
}
