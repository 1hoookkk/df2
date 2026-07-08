#include <catch2/catch_all.hpp>

#include "SmartMotion.h"
#include "TrenchBodyRoster.h"
#include "PluginProcessor.h"
#include "parameters/TrenchParameters.h"

#include <cmath>

using trench::SmartMotion;
using trench::TypeBehavior;
using trench::smartMotionFor;

namespace
{
constexpr int kNumShippingBodies = 3; // Meaty Gizmo, Talking Hedz, Lucifers Q

void requireFiniteAndBounded (const SmartMotion& m)
{
    REQUIRE (std::isfinite (m.morphDepth));
    REQUIRE (std::isfinite (m.qDepth));
    REQUIRE (m.morphDepth >= -1.0f);
    REQUIRE (m.morphDepth <= 1.0f);
    REQUIRE (m.qDepth >= 0.0f);
    REQUIRE (m.qDepth <= 1.0f);
    REQUIRE (m.divIdx >= 0);
    REQUIRE (m.divIdx <= 9); // 10 divisions as of the bar-length TIME extension
    REQUIRE (m.direction >= 0);
    REQUIRE (m.direction <= 5);
    REQUIRE (m.length >= 1);
    REQUIRE (m.length <= trench::MotionEngine::kSteps);
}
}

TEST_CASE ("smartMotionFor returns finite, bounded values for every body x tile", "[smartmotion]")
{
    for (int body = 0; body < kNumShippingBodies; ++body)
    {
        for (auto behavior : { TypeBehavior::AutoHalf, TypeBehavior::AutoQuarter,
                               TypeBehavior::Dynamic, TypeBehavior::Wobble })
        {
            INFO ("body=" << body << " behavior=" << (int) behavior);
            requireFiniteAndBounded (smartMotionFor (body, behavior));
        }
    }
}

TEST_CASE ("smartMotionFor Static always returns a null identity", "[smartmotion]")
{
    for (int body = 0; body < kNumShippingBodies; ++body)
    {
        const auto m = smartMotionFor (body, TypeBehavior::Static);
        REQUIRE (m.morphDepth == Catch::Approx (0.0f));
        REQUIRE (m.qDepth == Catch::Approx (0.0f));
    }
}

TEST_CASE ("Riser is a forward sweep, Breathe is a pendulum, Wobble is random/brownian", "[smartmotion]")
{
    for (int body = 0; body < kNumShippingBodies; ++body)
    {
        REQUIRE (smartMotionFor (body, TypeBehavior::AutoHalf).direction == 0);   // Fwd
        REQUIRE (smartMotionFor (body, TypeBehavior::AutoQuarter).direction == 2); // Pend
        const int wobbleDir = smartMotionFor (body, TypeBehavior::Wobble).direction;
        REQUIRE ((wobbleDir == 3 || wobbleDir == 4)); // Rand or Brown
    }
}

TEST_CASE ("Amount table scales depth without changing direction/division", "[smartmotion]")
{
    bool anyDistinct = false;
    const auto ref = smartMotionFor (0, TypeBehavior::AutoHalf);
    for (int body = 1; body < kNumShippingBodies; ++body)
    {
        const auto m = smartMotionFor (body, TypeBehavior::AutoHalf);
        REQUIRE (m.direction == ref.direction);
        REQUIRE (m.divIdx == ref.divIdx);
        if (std::abs (m.morphDepth - ref.morphDepth) > 0.001f)
            anyDistinct = true;
    }
    REQUIRE (anyDistinct);
}

TEST_CASE ("motionTile parameter exists with 5 choices, default Riser", "[params]")
{
    juce::ScopedJuceInitialiser_GUI juce;
    PluginProcessor processor;
    auto* param = processor.apvts.getParameter (ParamID::motionTile);
    REQUIRE (param != nullptr);
    auto* choice = dynamic_cast<juce::AudioParameterChoice*> (param);
    REQUIRE (choice != nullptr);
    REQUIRE (choice->choices.size() == 5);
    REQUIRE (choice->choices[0] == "Riser");
    REQUIRE (choice->choices[1] == "Breathe");
    REQUIRE (choice->choices[2] == "Chop");
    REQUIRE (choice->choices[3] == "Wobble");
    REQUIRE (choice->choices[4] == "User");
    REQUIRE (choice->getIndex() == 0);
}

TEST_CASE ("USER motion is silent/flat before any recording exists", "[motion][user]")
{
    // An unrecorded MotionPattern is all zeros -- buildUserMotion must not
    // fabricate motion from that; every step should decode to zero offset.
    const trench::MotionPattern unrecorded;
    const auto m = trench::smartMotionForUser (unrecorded);
    requireFiniteAndBounded (m);
    REQUIRE (m.qDepth == 0.0f);
    for (auto v : m.pattern.values)
        REQUIRE (v == 0);
}

TEST_CASE ("USER motion plays back a real recorded shape, forward then reverse", "[motion][user]")
{
    trench::MotionPattern recorded;
    for (int i = 0; i < trench::MotionEngine::kSteps; ++i)
        recorded.values[(size_t) i] = (juce::int8) (i - trench::MotionEngine::kSteps / 2);
    const auto m = trench::smartMotionForUser (recorded);
    requireFiniteAndBounded (m);
    REQUIRE (m.direction == 2); // Pendulum: forward then reverse
    REQUIRE (m.morphDepth > 0.0f);
    REQUIRE (m.qDepth == 0.0f); // recording only ever drives Morph, never Q
    bool anyNonZero = false;
    for (auto v : m.pattern.values)
        if (v != 0) anyNonZero = true;
    REQUIRE (anyNonZero);
}
