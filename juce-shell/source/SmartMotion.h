#pragma once

#include "dsp/MotionEngine.h"
#include "TrenchBodyRoster.h"

#include <cmath>

namespace trench
{

// A curated per-body Motion identity: one of 4 fixed-shape "tiles" (Riser,
// Breathe, Adlib Chop, Wobble), each scaled to fit the current body by a
// single per-body-per-tile Amount (0..1) — the same lever as the public
// Motion Amt knob, just captured per body instead of globally. The tile's
// SHAPE (direction, division, pattern, morph:Q ratio) never changes between
// bodies; only its Amount does. See docs/superpowers/specs/
// 2026-07-07-modulation-overlay-lfo-follower-design.md for the authoring model.
struct SmartMotion
{
    float morphDepth = 0.0f;   // scales the pattern VALUE -> Morph offset (bipolar sweep)
    float qDepth     = 0.0f;   // scales the per-step GATE -> Q push (pulse/breath)
    int   divIdx     = 3;      // 0..5 -> 1/4, 1/8, 1/8T, 1/16, 1/16T, 1/32
    int   direction  = 0;      // 0=Fwd 1=Rev 2=Pend 3=Rand 4=Brown 5=1Shot
    int   length     = 16;     // active steps
    bool  smooth     = true;   // true = continuous glide, false = stepped
    MotionPattern pattern;     // curated 64-step values (+ gates)
};

namespace smart_detail
{
    inline void sineValues (MotionPattern& p, int length, int cycles, float amp) noexcept
    {
        const int n = juce::jlimit (1, MotionEngine::kSteps, length);
        for (int i = 0; i < n; ++i)
        {
            const double ph = (double) (i * cycles) / (double) n;
            const double v  = std::sin (juce::MathConstants<double>::twoPi * ph) * (double) amp;
            p.values[(size_t) i] = (juce::int8) juce::jlimit (-64, 64, (int) std::lround (v * 64.0));
        }
    }

    inline void gateEvery (MotionPattern& p, int length, int every, int offset) noexcept
    {
        const int n = juce::jlimit (1, MotionEngine::kSteps, length);
        for (int i = offset; i < n; i += juce::jmax (1, every))
            p.setGate (i, true);
    }

    // Deterministic "random-looking" bipolar walk for Wobble — allocation-free,
    // audio-thread-safe (no juce::Random state to carry), seeded from length so
    // repeated calls are stable across blocks.
    inline void wobbleValues (MotionPattern& p, int length, float amp) noexcept
    {
        const int n = juce::jlimit (1, MotionEngine::kSteps, length);
        juce::uint32 x = 0x9E3779B9u;
        for (int i = 0; i < n; ++i)
        {
            x ^= x << 13; x ^= x >> 17; x ^= x << 5; // xorshift32
            const float u = (float) (x % 2000u) / 1000.0f - 1.0f; // -1..1
            p.values[(size_t) i] = (juce::int8) juce::jlimit (-64, 64, (int) std::lround ((double) (u * amp) * 64.0));
        }
    }

    // Fixed shape for each tile: direction/division/length/smooth/pattern-generator
    // and a fixed morph:Q ratio. Only `amount` varies per body — see kTileAmount.
    inline SmartMotion buildRiser (float amount) noexcept
    {
        SmartMotion m;
        m.morphDepth = 0.85f * amount;
        m.qDepth     = 0.15f * amount;
        m.divIdx = 3; m.direction = 0 /*Fwd*/; m.length = 8; m.smooth = true;
        sineValues (m.pattern, 8, 1, 1.0f);
        gateEvery  (m.pattern, 8, 4, 0);
        return m;
    }

    inline SmartMotion buildBreathe (float amount) noexcept
    {
        SmartMotion m;
        m.morphDepth = 0.55f * amount;
        m.qDepth     = 0.30f * amount;
        m.divIdx = 3; m.direction = 2 /*Pend*/; m.length = 4; m.smooth = true;
        sineValues (m.pattern, 4, 1, 1.0f);
        gateEvery  (m.pattern, 4, 4, 0);
        return m;
    }

    inline SmartMotion buildAdlibChop (float amount) noexcept
    {
        SmartMotion m;
        // Dynamic/Adlib Chop reads morphDepth/qDepth directly (see
        // PluginProcessor::applyMotion's Dynamic branch) — divIdx/direction/
        // pattern are unused for this tile (envelope-follower path, not
        // MotionEngine's step sequencer), left at struct defaults.
        m.morphDepth = 0.30f * amount;
        m.qDepth     = 0.85f * amount;
        return m;
    }

    inline SmartMotion buildWobble (float amount) noexcept
    {
        SmartMotion m;
        m.morphDepth = 0.50f * amount;
        m.qDepth     = 0.50f * amount;
        m.divIdx = 3; m.direction = 3 /*Rand*/; m.length = 16; m.smooth = false;
        wobbleValues (m.pattern, 16, 1.0f);
        gateEvery    (m.pattern, 16, 3, 1);
        return m;
    }
}

// Per-body-per-tile Amount (0..1). PLACEHOLDER starting values, seeded from
// each body's old single curated depth as a reasonable starting point — to
// be tuned by ear per docs/superpowers/specs/
// 2026-07-07-modulation-overlay-lfo-follower-design.md's authoring table.
// Row index = bodyIndex (0 Meaty Gizmo, 1 Talking Hedz, 2 Lucifers Q).
// Column order = Riser, Breathe, Adlib Chop, Wobble.
inline constexpr float kTileAmount[3][4] = {
    /* Meaty Gizmo */ { 0.70f, 0.70f, 0.70f, 0.70f },
    /* Talking Hedz */ { 0.85f, 0.55f, 0.50f, 0.60f },
    /* Lucifers Q   */ { 0.60f, 0.45f, 0.90f, 0.75f },
};

inline constexpr int kNumTileAmountBodies = 3;

// Pure + deterministic, allocation-free -> safe to call on the audio thread.
// `bodyIndex` is the roster index; out-of-range indices (diagnostics-only
// bodies) fall back to row 0 rather than guessing.
inline SmartMotion smartMotionFor (int bodyIndex, TypeBehavior behavior) noexcept
{
    using namespace smart_detail;

    if (behavior == TypeBehavior::Static)
        return {};

    const int row = (bodyIndex >= 0 && bodyIndex < kNumTileAmountBodies) ? bodyIndex : 0;

    switch (behavior)
    {
        case TypeBehavior::AutoHalf:    return buildRiser     (kTileAmount[row][0]);
        case TypeBehavior::AutoQuarter: return buildBreathe    (kTileAmount[row][1]);
        case TypeBehavior::Dynamic:     return buildAdlibChop  (kTileAmount[row][2]);
        case TypeBehavior::Wobble:      return buildWobble     (kTileAmount[row][3]);
        default:                        return {};
    }
}

} // namespace trench
