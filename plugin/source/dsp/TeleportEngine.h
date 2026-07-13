#pragma once

#include <cmath>
#include <juce_audio_basics/juce_audio_basics.h>

namespace trench {

struct TeleportResult { float morph = 0.0f; float q = 0.0f; };

// Block-rate Morph/Q motion engine.
// The host Morph/Q are the center; Teleport shakes or snaps around that center.
// All modes run at block granularity — no per-sample processing.
class TeleportEngine
{
public:
    TeleportEngine() = default;

    void prepare (double sampleRate) noexcept
    {
        sr      = sampleRate;
        phase   = 0.0;
        heldM   = 0.0f;
        heldQ   = 0.0f;
        derivScale = 1.0e-6f;
        rng.setSeedRandomly(); // unique seed per instance
    }

    // Compute derivative RMS of a mono block. Call before apply() for Deriv mode.
    static float blockDerivRms (const float* data, int n) noexcept
    {
        if (n <= 1) return 0.0f;
        float sumSq = 0.0f;
        for (int i = 1; i < n; ++i)
        {
            const float d = data[i] - data[i - 1];
            sumSq += d * d;
        }
        return std::sqrt (sumSq / (float) (n - 1));
    }

    // mode: 0=Off, 1=Noise, 2=Strobe, 3=Derivative
    TeleportResult apply (int mode, float amount, float rateHz,
                          float morphDepth, float qDepth,
                          float centerMorph, float centerQ,
                          float derivRms, int blockSize) noexcept
    {
        if (mode == 0 || amount <= 0.0f)
            return { centerMorph, centerQ };

        float mOff = 0.0f, qOff = 0.0f;

        if (mode == 1) // Noise: sample-and-hold random, changes at rateHz
        {
            advance (rateHz, blockSize);
            if (crossed)
            {
                heldM = rng.nextFloat() * 2.0f - 1.0f;
                heldQ = rng.nextFloat() * 2.0f - 1.0f;
            }
            mOff = heldM;
            qOff = heldQ;
        }
        else if (mode == 2) // Strobe: hard square at rateHz, snaps ±1 each half-cycle
        {
            advance (rateHz, blockSize);
            mOff = phase < 0.5 ? 1.0f : -1.0f;
            qOff = phase < 0.5 ? 1.0f : -1.0f;
        }
        else if (mode == 3) // Derivative: input amplitude slope drives offset
        {
            const float alpha = 0.04f; // ~25-block follower
            derivScale = derivScale * (1.0f - alpha) + derivRms * alpha + 1.0e-9f;
            const float norm = juce::jlimit (-1.0f, 1.0f, derivRms / (derivScale * 1.5f));
            mOff = std::tanh (norm * 2.5f);
            qOff = norm; // Q tracks amplitude derivative linearly
        }

        return {
            juce::jlimit (0.0f, 1.0f, centerMorph + mOff * amount * morphDepth),
            juce::jlimit (0.0f, 1.0f, centerQ     + qOff * amount * qDepth),
        };
    }

private:
    void advance (float rateHz, int blockSize) noexcept
    {
        const double inc = (double) juce::jmax (0.01f, rateHz) * (double) blockSize / sr;
        const double prev = phase;
        phase += inc;
        crossed = (std::floor (phase) > std::floor (prev));
        if (phase >= 1.0) phase -= std::floor (phase);
    }

    double      sr         = 44100.0;
    double      phase      = 0.0;
    bool        crossed    = false;
    float       heldM      = 0.0f;
    float       heldQ      = 0.0f;
    float       derivScale = 1.0e-6f;
    juce::Random rng;

    JUCE_DECLARE_NON_COPYABLE (TeleportEngine)
};

} // namespace trench
