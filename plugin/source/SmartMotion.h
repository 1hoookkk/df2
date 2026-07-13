#pragma once

#include "TrenchBodyRoster.h"
#include "dsp/MotionEngine.h"

#include <cmath>

namespace trench
{

struct SmartMotion
{
    float morphDepth = 0.0f;
    float qDepth = 0.0f;
    int divIdx = 3;
    int direction = 0;
    int length = 16;
    bool smooth = true;
    MotionPattern pattern;
};

namespace smart_detail
{
inline void sineValues (MotionPattern& pattern, int length, float amplitude) noexcept
{
    const auto count = juce::jlimit (1, MotionEngine::kSteps, length);
    for (int i = 0; i < count; ++i)
    {
        const auto phase = (double) i / (double) count;
        const auto value = std::sin (juce::MathConstants<double>::twoPi * phase) * amplitude;
        pattern.values[(size_t) i] = (juce::int8) juce::jlimit (-64, 64, (int) std::lround (value * 64.0));
    }
}

inline void gateEvery (MotionPattern& pattern, int length, int every) noexcept
{
    const auto count = juce::jlimit (1, MotionEngine::kSteps, length);
    for (int i = 0; i < count; i += juce::jmax (1, every))
        pattern.setGate (i, true);
}

inline void wobbleValues (MotionPattern& pattern, int length) noexcept
{
    const auto count = juce::jlimit (1, MotionEngine::kSteps, length);
    juce::uint32 state = 0x9E3779B9u;
    for (int i = 0; i < count; ++i)
    {
        state ^= state << 13;
        state ^= state >> 17;
        state ^= state << 5;
        const auto value = (float) (state % 2000u) / 1000.0f - 1.0f;
        pattern.values[(size_t) i] = (juce::int8) juce::jlimit (-64, 64, (int) std::lround (value * 64.0f));
    }
}

inline SmartMotion build (TypeBehavior behavior, float amount) noexcept
{
    SmartMotion motion;
    switch (behavior)
    {
        case TypeBehavior::AutoHalf:
            motion.morphDepth = 0.85f * amount;
            motion.qDepth = 0.15f * amount;
            motion.length = 8;
            sineValues (motion.pattern, motion.length, 1.0f);
            gateEvery (motion.pattern, motion.length, 4);
            break;
        case TypeBehavior::AutoQuarter:
            motion.morphDepth = 0.55f * amount;
            motion.qDepth = 0.30f * amount;
            motion.direction = 2;
            motion.length = 4;
            sineValues (motion.pattern, motion.length, 1.0f);
            gateEvery (motion.pattern, motion.length, 4);
            break;
        case TypeBehavior::Dynamic:
            motion.morphDepth = 0.30f * amount;
            motion.qDepth = 0.85f * amount;
            break;
        case TypeBehavior::Wobble:
            motion.morphDepth = 0.50f * amount;
            motion.qDepth = 0.50f * amount;
            motion.direction = 3;
            motion.smooth = false;
            wobbleValues (motion.pattern, motion.length);
            gateEvery (motion.pattern, motion.length, 3);
            break;
        default:
            break;
    }
    return motion;
}
}

inline SmartMotion smartMotionFor (int bodyIndex, TypeBehavior behavior) noexcept
{
    juce::ignoreUnused (bodyIndex);
    return smart_detail::build (behavior, 0.7f);
}

inline SmartMotion smartMotionForUser (const MotionPattern& recorded) noexcept
{
    SmartMotion motion;
    motion.pattern = recorded;
    motion.morphDepth = 1.0f;
    motion.direction = 2;
    motion.length = MotionEngine::kSteps;
    return motion;
}

} // namespace trench
