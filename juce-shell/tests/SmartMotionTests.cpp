#include <catch2/catch_all.hpp>

#include "SmartMotion.h"
#include "TrenchBodyRoster.h"

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
    REQUIRE (m.divIdx <= 5);
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
