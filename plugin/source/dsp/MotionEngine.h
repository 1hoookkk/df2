#pragma once

#include <array>
#include <cmath>
#include <cstring>
#include <juce_audio_basics/juce_audio_basics.h>

namespace trench
{

struct MotionResult { float morph = 0.0f; float q = 0.0f; float drive = 0.0f; };

// Block-rate step-sequencer motion engine, distilled from the Emulator X
// Function Generator: 64 steps, bipolar 1/64-quantized values, per-step
// trigger/gate, smooth/stepped, end-step, direction modes, BPM sync.
//
// The host Morph/Q/Drive are the center; Motion offsets around that center
// additively, then jlimit-clamps — identical convention to the former
// applyLfoMatrix. All modes run at block granularity; no per-sample work.
//
// A 4 ms one-pole sits on the engine's *output* so stepped patterns do not
// click the filter. EmuX targets sampler voices with envelopes; DF2 hits the
// filter cascade directly, so this structural smoother is mandatory.
class MotionEngine
{
public:
    static constexpr int kSteps = 64;

    MotionEngine() = default;

    void prepare (double sampleRate) noexcept
    {
        sr = sampleRate;
        resetPlaybackPosition();
        rng.setSeedRandomly();
    }

    void resetPlaybackPosition() noexcept
    {
        step = 0;
        phase = 0.0;
        pendulumDir = 1;
        oneShotDone = false;
        prevTransportPlaying = false;
        smoothedOffsetMorph = 0.0f;
        smoothedOffsetQ = 0.0f;
    }

    // direction: 0=Fwd 1=Rev 2=Pend 3=Rand 4=Brown 5=1Shot
    // sync:      0=Key (restart on transport start) 1=Freerun
    // divisionIndex indexes kDivisionRatios.
    // values:     64 signed bytes, -64..+64 (raw EmuX value * 64)
    // triggerBytes: 8 bytes, bitfield over 64 steps (bit s set = gate on)
    MotionResult apply (bool on, bool bpmSync, float rateHz, int divisionIndex,
                        int sync, bool smooth, int direction, int length,
                        float morphDepth, float qDepth,
                        bool accentToDrive, float driveDepth,
                        const juce::int8* values, const juce::uint8* triggerBytes,
                        double hostBpm, bool transportPlaying,
                        float centerMorph, float centerQ, float centerDrive,
                        int blockSize) noexcept
    {
        if (! on)
            return { centerMorph, centerQ, centerDrive };

        const bool morphActive = std::abs (morphDepth) > 0.0005f;
        const bool qActive = qDepth > 0.0005f;
        const bool driveActive = accentToDrive && driveDepth > 0.0005f;
        if (! morphActive && ! qActive && ! driveActive)
            return { centerMorph, centerQ, centerDrive };

        const int len = juce::jlimit (1, kSteps, length);
        const int dir = juce::jlimit (0, 5, direction);

        // Key sync: reset on transport start edge.
        const bool transportJustStarted = transportPlaying && ! prevTransportPlaying;
        prevTransportPlaying = transportPlaying;
        if (sync == 0 && transportJustStarted)
        {
            step = 0;
            phase = 0.0;
            pendulumDir = 1;
            oneShotDone = false;
        }

        // Step duration: BPM-synced division or free Hz.
        const double stepDur = (bpmSync && hostBpm > 0.0)
            ? (60.0 / hostBpm) * kDivisionRatios[juce::jlimit (0, numDivs - 1, divisionIndex)]
            : 1.0 / (double) juce::jmax (0.01f, rateHz);

        const double inc = (double) blockSize / sr / juce::jmax (1.0e-9, stepDur);
        const double prevPhase = phase;
        phase += inc;
        const bool crossed = std::floor (phase) > std::floor (prevPhase);
        if (phase >= 1.0) phase -= std::floor (phase);

        if (crossed && ! oneShotDone)
            advanceStep (dir, len);

        // Read pattern value (bipolar -1..+1, EmuX 1/64 quantization).
        const int s = juce::jlimit (0, kSteps - 1, step);
        float v = (float) values[s] / 64.0f;

        if (smooth)
        {
            const int nextS = juce::jlimit (0, kSteps - 1, nextStepForInterp (dir, s, len));
            const float vNext = (float) values[nextS] / 64.0f;
            const float frac = (float) (phase - std::floor (phase));
            v = v + (vNext - v) * frac;
        }

        const bool gate = (triggerBytes[s >> 3] & (1u << (s & 7))) != 0;

        // 15 ms one-pole on the offsets — anti-click for stepped patterns.
        // EmuX targets sampler voices with amplitude envelopes; DF2 hits the
        // filter cascade directly with continuous audio, so this structural
        // smoother is mandatory. 15 ms preserves the stepped feel while
        // preventing discontinuities at block boundaries.
        const double blockSec = (double) blockSize / sr;
        const float alpha = (float) (1.0 - std::exp (-blockSec / 0.015));
        smoothedOffsetMorph += (v - smoothedOffsetMorph) * alpha;
        smoothedOffsetQ += ((gate ? 1.0f : 0.0f) - smoothedOffsetQ) * alpha;

        return {
            juce::jlimit (0.0f, 1.0f, centerMorph + smoothedOffsetMorph * morphDepth),
            juce::jlimit (0.0f, 1.0f, centerQ     + smoothedOffsetQ    * qDepth),
            driveActive
                ? juce::jlimit (0.0f, 1.0f, centerDrive + smoothedOffsetQ * driveDepth)
                : centerDrive
        };
    }

    int getCurrentStepForUi() const noexcept { return step; }

private:
    // Division ratios (relative to one quarter note, 4/4 time):
    // 1/4, 1/8, 1/8T, 1/16, 1/16T, 1/32, 1/2, 1 BAR, 2 BAR, 4 BAR
    // ...plus three weird/specific times appended (2026-07-17, "they might
    // sound cool"): 3/16 dotted-eighth, 5/16 polymeter, 1/6 quarter-triplet.
    static constexpr double kDivisionRatios[] = { 1.0, 0.5, 0.375, 0.25, 0.1875, 0.125, 2.0, 4.0, 8.0, 16.0,
                                                  0.75, 1.25, 2.0 / 3.0 };
    static constexpr int numDivs = 13;

    int nextStepForInterp (int dir, int s, int len) const noexcept
    {
        switch (dir)
        {
            case 1: return (s - 1 + len) % len;
            case 2: return juce::jlimit (0, len - 1, s + pendulumDir);
            case 3:
            case 4: return s; // Rand/Brown: interp to self (stepped feel preserved)
            default: return (s + 1) % len;
        }
    }

    void advanceStep (int dir, int len) noexcept
    {
        switch (dir)
        {
            case 0: // Fwd
                step = (step + 1) % len;
                break;
            case 1: // Rev
                step = (step - 1 + len) % len;
                break;
            case 2: // Pendulum
                step += pendulumDir;
                if (step >= len) { step = len - 1; pendulumDir = -1; }
                else if (step < 0) { step = 0; pendulumDir = 1; }
                break;
            case 3: // Random
                step = rng.nextInt (len);
                break;
            case 4: // Brownian
                step = juce::jlimit (0, len - 1, step + (rng.nextBool() ? 1 : -1));
                break;
            case 5: // One-shot
                if (step < len - 1) ++step;
                else oneShotDone = true;
                break;
        }
    }

    double sr = 44100.0;
    double phase = 0.0;
    int step = 0;
    int pendulumDir = 1;
    bool oneShotDone = false;
    bool prevTransportPlaying = false;
    float smoothedOffsetMorph = 0.0f;
    float smoothedOffsetQ = 0.0f;
    juce::Random rng;

    JUCE_DECLARE_NON_COPYABLE (MotionEngine)
};

// 64-step pattern: bipolar 1/64-quantized values + per-step gate bits + seed.
// 64 + 8 + 4 = 76 bytes. Serialized as a string property on the APVTS state.
struct MotionPattern
{
    std::array<juce::int8, 64> values {};     // -64..+64
    std::array<juce::uint8, 8> triggers {};   // bitfield, bit s = gate for step s
    juce::uint32 seed = 0x5EED1234u;

    void clear() noexcept
    {
        values.fill (0);
        triggers.fill (0);
    }

    bool getGate (int step) const noexcept
    {
        return (triggers[(juce::uint32) step >> 3] & (1u << (step & 7))) != 0;
    }

    void setGate (int step, bool on) noexcept
    {
        if (on) triggers[(juce::uint32) step >> 3] |= (1u << (step & 7));
        else    triggers[(juce::uint32) step >> 3] &= ~(1u << (step & 7));
    }
};

// Compact base64 serialization of MotionPattern (76 bytes -> ~104 chars).
// Round-trips exactly so recall restores byte-identical.
inline juce::String encodeMotionPattern (const MotionPattern& p)
{
    const juce::uint8 bytes[] = {
        1u, // format version
    };
    juce::MemoryBlock mb;
    mb.append (bytes, 1);
    mb.append (p.values.data(), p.values.size());
    mb.append (p.triggers.data(), p.triggers.size());
    mb.append (&p.seed, sizeof (p.seed));
    return mb.toBase64Encoding();
}

inline MotionPattern decodeMotionPattern (const juce::String& s)
{
    MotionPattern p;
    if (s.isEmpty()) return p;
    juce::MemoryBlock mb;
    mb.fromBase64Encoding (s);
    if (mb.getSize() < 1 + 64 + 8 + 4) return p;
    auto* data = (const juce::uint8*) mb.getData();
    if (data[0] != 1u) return p; // unknown format version
    std::memcpy (p.values.data(),   data + 1, 64);
    std::memcpy (p.triggers.data(), data + 65, 8);
    std::memcpy (&p.seed,           data + 73, 4);
    return p;
}

} // namespace trench
