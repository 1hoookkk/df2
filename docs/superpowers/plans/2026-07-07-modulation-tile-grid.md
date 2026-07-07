# Modulation Tile Grid Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Modulation's hidden body-name-based auto-selection with an
explicit CRT-transition 2x2 tile grid (Riser/Breathe/Adlib Chop/Wobble) of
per-body curated moves, and give 5D a per-body baked base amount plus
ride-along with whichever tile is armed.

**Architecture:** No new DSP engine — `MotionEngine` and `qsound_spatial.rs`
already do everything needed. This is: (a) one new APVTS parameter
(`motionTile`) that becomes the explicit selector `PluginProcessor` already
had implicitly via name-matching; (b) a `SmartMotion.h` refactor from
"one curated identity per body" to "one fixed-shape archetype per tile,
scaled by a per-body Amount table"; (c) a small `ModulatedControls`-free
5D ride-along computed from the morph/Q offset already produced by
`applyMotion`; (d) a UI mode-switch inside `GraphDisplay` (curve vs. 2x2
grid) with a CRT-collapse/expand transition, replacing `ModulateTag`'s
direct param-writing with a callback into that grid.

**Tech Stack:** JUCE 8 (C++20), Catch2 v3 (existing `Tests` target).

**Pre-existing discrepancy fixed in Task 1:** `SmartMotion.h`'s comments and
`switch (bodyIndex % 4)` reference 4 bodies ("Talking Hedz, Millennium, Ear
Bender, Lucifer's Q"), but the actual shipping roster
(`TrenchBodyRoster.h:63-75`, `bakedRoster`) has **3** named bodies: Meaty
Gizmo, Talking Hedz, Lucifers Q (index 0, 1, 2). "Millennium" and "Ear
Bender" do not exist in the shipped roster. This plan corrects the mapping
to the real 3 bodies instead of perpetuating the stale 4-body comment.

---

### Task 1: Extend `TypeBehavior` with Wobble, refactor `SmartMotion.h` to the archetype + per-body Amount table

**Files:**
- Modify: `juce-shell/source/TrenchBodyRoster.h:27-33`
- Modify: `juce-shell/source/SmartMotion.h` (full rewrite of `smartMotionFor` and helpers)
- Test: `juce-shell/tests/SmartMotionTests.cpp` (new file)

- [ ] **Step 1: Add `Wobble` to the `TypeBehavior` enum**

In `juce-shell/source/TrenchBodyRoster.h:27-33`, change:

```cpp
enum class TypeBehavior : int
{
    Static = 0,
    Dynamic,
    AutoQuarter,
    AutoHalf,
};
```

to:

```cpp
enum class TypeBehavior : int
{
    Static = 0,
    Dynamic,     // Adlib Chop — envelope-follower reactive
    AutoQuarter, // Breathe — pendulum, tempo-synced
    AutoHalf,    // Riser — forward, tempo-synced
    Wobble,      // Random/Brownian step, tempo-synced
};
```

- [ ] **Step 2: Write the failing test for the new archetype/table model**

Create `juce-shell/tests/SmartMotionTests.cpp`:

```cpp
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
    // Every (body, tile) pair must produce a nonzero, distinct-from-each-other
    // depth so the table is actually wired (not all defaulting to the same number).
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
```

- [ ] **Step 3: Run the test to verify it fails to compile (SmartMotion.h doesn't yet support this shape)**

Run: `cmake --build build --target Tests` (or the project's existing build
script — see `juce-shell/build-standalone.ps1` for the sanctioned build
invocation).
Expected: FAIL — either a compile error (old `smartMotionFor` still keys off
name-matching internals) or logical test failures, since `TypeBehavior::Wobble`
has no case yet.

- [ ] **Step 4: Rewrite `SmartMotion.h`**

Replace the full file content with:

```cpp
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
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cmake --build build --target Tests && ctest --test-dir build -R smartmotion --output-on-failure`
Expected: PASS — all 4 `TEST_CASE`s in `SmartMotionTests.cpp` green.

- [ ] **Step 6: Commit**

```bash
git add juce-shell/source/TrenchBodyRoster.h juce-shell/source/SmartMotion.h juce-shell/tests/SmartMotionTests.cpp
git commit -m "Add Wobble behavior, refactor SmartMotion to per-body Amount table"
```

---

### Task 2: Add the `motionTile` parameter

**Files:**
- Modify: `juce-shell/source/parameters/TrenchParameters.h:23-42`
- Modify: `juce-shell/source/parameters/TrenchParameters.cpp:79-187`
- Test: `juce-shell/tests/SmartMotionTests.cpp` (append)

- [ ] **Step 1: Write the failing test**

Append to `juce-shell/tests/SmartMotionTests.cpp`:

```cpp
#include "parameters/TrenchParameters.h"

TEST_CASE ("motionTile parameter exists with 4 choices, default Riser", "[params]")
{
    auto layout = TrenchParameters::createParameterLayout();
    auto* param = layout.getParameter (ParamID::motionTile);
    REQUIRE (param != nullptr);
    auto* choice = dynamic_cast<juce::AudioParameterChoice*> (param);
    REQUIRE (choice != nullptr);
    REQUIRE (choice->choices.size() == 4);
    REQUIRE (choice->choices[0] == "Riser");
    REQUIRE (choice->choices[1] == "Breathe");
    REQUIRE (choice->choices[2] == "Adlib Chop");
    REQUIRE (choice->choices[3] == "Wobble");
    REQUIRE (choice->getIndex() == 0);
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cmake --build build --target Tests`
Expected: FAIL to compile — `ParamID::motionTile` does not exist.

- [ ] **Step 3: Add the parameter ID**

In `juce-shell/source/parameters/TrenchParameters.h`, after line 26
(`motionOn`), add:

```cpp
    inline constexpr auto motionTile         = "motionTile";         // choice: Riser,Breathe,Adlib Chop,Wobble
```

- [ ] **Step 4: Add the parameter layout entry**

In `juce-shell/source/parameters/TrenchParameters.cpp`, immediately after the
`motionOn` block (after line 87, before the `motionAmount` block), add:

```cpp
    // Explicit tile pick — replaces the old body-name-based auto-selection.
    // Grid position is fixed across all bodies; the curated values behind
    // each name are per-body (see SmartMotion.h kTileAmount).
    layout.add (std::make_unique<juce::AudioParameterChoice> (
        juce::ParameterID { ParamID::motionTile, 1 },
        "Motion Tile",
        juce::StringArray { "Riser", "Breathe", "Adlib Chop", "Wobble" },
        0));  // default = Riser.
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cmake --build build --target Tests && ctest --test-dir build -R params --output-on-failure`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add juce-shell/source/parameters/TrenchParameters.h juce-shell/source/parameters/TrenchParameters.cpp juce-shell/tests/SmartMotionTests.cpp
git commit -m "Add motionTile parameter for explicit Riser/Breathe/Adlib Chop/Wobble pick"
```

---

### Task 3: Rewire `PluginProcessor` behavior selection to the explicit tile, add Wobble to the transport gate, add 5D per-body base amount + ride-along

**Files:**
- Modify: `juce-shell/source/PluginProcessor.h`
- Modify: `juce-shell/source/PluginProcessor.cpp:269-435,655-672`
- Test: `juce-shell/tests/ModulationTileTests.cpp` (new file)

- [ ] **Step 1: Write the failing tests**

Create `juce-shell/tests/ModulationTileTests.cpp`:

```cpp
#include <catch2/catch_all.hpp>

#include "PluginProcessor.h"
#include "TrenchBodyRoster.h"

#include <cmath>

namespace
{
void setParam (PluginProcessor& p, const char* id, float value)
{
    if (auto* param = p.apvts.getParameter (id))
        param->setValueNotifyingHost (param->convertTo0to1 (value));
}

void setChoice (PluginProcessor& p, const char* id, int index)
{
    if (auto* param = p.apvts.getParameter (id))
        param->setValueNotifyingHost (param->convertTo0to1 ((float) index));
}
}

TEST_CASE ("getModulationBehaviorForUi reads the explicit tile, not the body name", "[modulation]")
{
    juce::ScopedJuceInitialiser_GUI juce;
    PluginProcessor processor;

    setParam (processor, ParamID::motionOn, 1.0f);

    setChoice (processor, ParamID::motionTile, 0); // Riser
    REQUIRE (processor.getModulationBehaviorForUi() == trench::TypeBehavior::AutoHalf);

    setChoice (processor, ParamID::motionTile, 1); // Breathe
    REQUIRE (processor.getModulationBehaviorForUi() == trench::TypeBehavior::AutoQuarter);

    setChoice (processor, ParamID::motionTile, 2); // Adlib Chop
    REQUIRE (processor.getModulationBehaviorForUi() == trench::TypeBehavior::Dynamic);

    setChoice (processor, ParamID::motionTile, 3); // Wobble
    REQUIRE (processor.getModulationBehaviorForUi() == trench::TypeBehavior::Wobble);

    setParam (processor, ParamID::motionOn, 0.0f);
    REQUIRE (processor.getModulationBehaviorForUi() == trench::TypeBehavior::Static);
}

TEST_CASE ("Wobble rests at center when transport is stopped, like Riser/Breathe", "[modulation]")
{
    juce::ScopedJuceInitialiser_GUI juce;
    constexpr double sampleRate = 48000.0;
    constexpr int blockSize = 512;

    PluginProcessor processor;
    processor.setRateAndBufferSizeDetails (sampleRate, blockSize);
    processor.prepareToPlay (sampleRate, blockSize);
    setParam (processor, ParamID::motionOn, 1.0f);
    setChoice (processor, ParamID::motionTile, 3); // Wobble

    juce::AudioBuffer<float> buffer (2, blockSize);
    juce::MidiBuffer midi;
    for (int b = 0; b < 24; ++b)
    {
        buffer.clear();
        processor.processBlock (buffer, midi);
    }
    REQUIRE (processor.getMotionStepForUi() == 0);
    REQUIRE_FALSE (processor.isMorphModulatedForUi());

    processor.releaseResources();
}

TEST_CASE ("5D rides along with an armed tile only when 5D's own base is nonzero", "[modulation][5d]")
{
    juce::ScopedJuceInitialiser_GUI juce;
    constexpr double sampleRate = 48000.0;
    constexpr int blockSize = 512;

    auto runAndReadSpace = [&] (bool fiveDOn, bool motionOn) -> float
    {
        PluginProcessor processor;
        processor.setRateAndBufferSizeDetails (sampleRate, blockSize);
        processor.prepareToPlay (sampleRate, blockSize);
        setParam (processor, ParamID::fiveD, fiveDOn ? 1.0f : 0.0f);
        setParam (processor, ParamID::motionOn, motionOn ? 1.0f : 0.0f);
        setChoice (processor, ParamID::motionTile, 0); // Riser

        juce::AudioBuffer<float> buffer (2, blockSize);
        juce::MidiBuffer midi;
        float lastSpace = 0.0f;
        for (int b = 0; b < 8; ++b)
        {
            for (int ch = 0; ch < 2; ++ch)
                for (int i = 0; i < blockSize; ++i)
                    buffer.setSample (ch, i, std::sin ((float) (i + 1) * 0.071f) * 0.5f);
            processor.processBlock (buffer, midi);
            lastSpace = processor.getEffectiveSpaceForUi();
        }
        processor.releaseResources();
        return lastSpace;
    };

    // 5D off: no ride-along possible, must stay exactly 0 regardless of Motion.
    REQUIRE (runAndReadSpace (false, true) == Catch::Approx (0.0f));

    // 5D on, Motion off: space sits at its static base, no motion offset.
    const float staticSpace = runAndReadSpace (true, false);
    REQUIRE (staticSpace > 0.0f);

    // 5D on, Motion on (Riser): space must be finite and bounded 0..1. It is
    // allowed to equal the static value at any single instant (the offset is
    // signal-dependent), so this only asserts safety, not movement.
    const float riddenSpace = runAndReadSpace (true, true);
    REQUIRE (std::isfinite (riddenSpace));
    REQUIRE (riddenSpace >= 0.0f);
    REQUIRE (riddenSpace <= 1.0f);
}

TEST_CASE ("motionTile survives full processor save/restore", "[modulation][recall]")
{
    juce::ScopedJuceInitialiser_GUI juce;

    PluginProcessor dirty;
    setParam (dirty, ParamID::motionOn, 1.0f);
    setChoice (dirty, ParamID::motionTile, 3); // Wobble

    juce::MemoryBlock state;
    dirty.getStateInformation (state);

    PluginProcessor restored;
    restored.setStateInformation (state.getData(), (int) state.getSize());

    REQUIRE (restored.getModulationBehaviorForUi() == trench::TypeBehavior::Wobble);
}

TEST_CASE ("Switching tiles while armed produces finite output with no discontinuity blow-up", "[modulation]")
{
    juce::ScopedJuceInitialiser_GUI juce;
    constexpr double sampleRate = 48000.0;
    constexpr int blockSize = 512;

    PluginProcessor processor;
    processor.setRateAndBufferSizeDetails (sampleRate, blockSize);
    processor.prepareToPlay (sampleRate, blockSize);
    setParam (processor, ParamID::motionOn, 1.0f);
    setChoice (processor, ParamID::motionTile, 0); // Riser

    juce::AudioBuffer<float> buffer (2, blockSize);
    juce::MidiBuffer midi;
    auto fillSine = [] (juce::AudioBuffer<float>& b)
    {
        for (int ch = 0; ch < b.getNumChannels(); ++ch)
            for (int i = 0; i < b.getNumSamples(); ++i)
                b.setSample (ch, i, std::sin ((float) (i + 1) * 0.071f) * 0.5f);
    };

    for (int b = 0; b < 8; ++b) { fillSine (buffer); processor.processBlock (buffer, midi); }

    // Switch tiles mid-stream (Riser -> Adlib Chop -> Wobble), one block each.
    for (int tile : { 2, 3, 1, 0 })
    {
        setChoice (processor, ParamID::motionTile, tile);
        fillSine (buffer);
        processor.processBlock (buffer, midi);
        for (int ch = 0; ch < 2; ++ch)
        {
            const auto* d = buffer.getReadPointer (ch);
            for (int i = 0; i < blockSize; ++i)
            {
                REQUIRE (std::isfinite (d[i]));
                REQUIRE (std::abs (d[i]) < 8.0f);
            }
        }
    }

    processor.releaseResources();
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cmake --build build --target Tests`
Expected: FAIL — `getModulationBehaviorForUi` still does name-matching (test 1
fails on Wobble/Adlib Chop expectations), and `getEffectiveSpaceForUi` does
not exist yet (compile error).

- [ ] **Step 3: Replace `getModulationBehaviorForUi` and `applyModulationBehavior`**

In `juce-shell/source/PluginProcessor.cpp`, replace lines 389-435
(`getModulationBehaviorForUi` through the end of `applyModulationBehavior`)
with:

```cpp
trench::TypeBehavior PluginProcessor::getModulationBehaviorForUi() const noexcept
{
    const bool on = apvts.getRawParameterValue (ParamID::motionOn)->load() > 0.5f;
    if (! on)
        return trench::TypeBehavior::Static;

    const int tile = (int) apvts.getRawParameterValue (ParamID::motionTile)->load();
    switch (juce::jlimit (0, 3, tile))
    {
        case 0: return trench::TypeBehavior::AutoHalf;    // Riser
        case 1: return trench::TypeBehavior::AutoQuarter; // Breathe
        case 2: return trench::TypeBehavior::Dynamic;     // Adlib Chop
        default: return trench::TypeBehavior::Wobble;     // Wobble
    }
}

// Called when the grid picks a tile (see GraphDisplay::tileTapped). Arms
// Motion with that tile for the given body. `behavior` is derived by the
// caller from the tile index via getModulationBehaviorForUi's mapping.
void PluginProcessor::applyModulationBehavior (trench::TypeBehavior behavior, int bodyIndex)
{
    juce::ignoreUnused (bodyIndex);
    setParameterDenormalized (ParamID::moveOn, 0.0f);
    setParameterDenormalized (ParamID::moveTension, 0.0f);
    setParameterDenormalized (ParamID::motionWarp, 0.0f);
    setParameterDenormalized (ParamID::motionCross, 0.0f);
    setParameterDenormalized (ParamID::motionBpm, 1.0f);
    setParameterDenormalized (ParamID::motionSync, 0.0f); // predictable play-start reset.

    if (behavior == trench::TypeBehavior::Static)
    {
        setParameterDenormalized (ParamID::motionOn, 0.0f);
        return;
    }

    setParameterDenormalized (ParamID::motionOn, 1.0f);
    // Amount/React stay at the curated defaults baked into SmartMotion's
    // kTileAmount table; the public Motion Amt knob still scales on top of
    // that (see applyMotion's `amount` read), matching today's behavior.
    setParameterDenormalized (ParamID::motionAmount, 1.0f);
    setParameterDenormalized (ParamID::motionReact,
                              behavior == trench::TypeBehavior::Dynamic ? 0.85f : 0.0f);
}
```

- [ ] **Step 4: Add Wobble to the transport-stopped gate**

In `juce-shell/source/PluginProcessor.cpp`, lines 336-342, change:

```cpp
    if ((typeBehavior == trench::TypeBehavior::AutoQuarter
         || typeBehavior == trench::TypeBehavior::AutoHalf)
        && ! transportPlaying)
```

to:

```cpp
    if ((typeBehavior == trench::TypeBehavior::AutoQuarter
         || typeBehavior == trench::TypeBehavior::AutoHalf
         || typeBehavior == trench::TypeBehavior::Wobble)
        && ! transportPlaying)
```

- [ ] **Step 5: Add the 5D per-body base amount table and ride-along**

In `juce-shell/source/SmartMotion.h`, after the `kNumTileAmountBodies`
constant, add:

```cpp
// Per-body baked 5D (Space) base amount — what FiveDTag snaps to on click,
// instead of a hardcoded 1.0. PLACEHOLDER values; tune by ear with the
// existing dev RigPanel slider (RigPanel.h, wired straight to ParamID::fiveD)
// and write the result back here.
inline constexpr float kFiveDBaseAmount[3] = {
    /* Meaty Gizmo */  0.60f,
    /* Talking Hedz */ 0.75f,
    /* Lucifers Q   */ 0.50f,
};

inline float fiveDBaseAmountFor (int bodyIndex) noexcept
{
    const int row = (bodyIndex >= 0 && bodyIndex < kNumTileAmountBodies) ? bodyIndex : 0;
    return kFiveDBaseAmount[row];
}
```

In `juce-shell/source/PluginProcessor.h`, add two new public accessors near
the other `...ForUi()` methods (find `isMorphModulatedForUi` and add
alongside it):

```cpp
    float getEffectiveSpaceForUi() const noexcept { return lastSpaceSent.load (std::memory_order_relaxed); }
```

and a new private member near `lastRigPanSent`:

```cpp
    std::atomic<float> lastSpaceSent { 0.0f };
```

In `juce-shell/source/PluginProcessor.cpp`, replace lines 656-661 area
context and the fiveD block at lines 669-672:

```cpp
    // Continuous QSound depth (SPACE). 0 = hard bypass (spatial stage Off).
    const float space = juce::jlimit (0.0f, 1.0f, apvts.getRawParameterValue (ParamID::fiveD)->load());
    params.fiveD = space;
    dspBridge.setSpatialMode (space > 0.001f ? 0 /*QSound*/ : kSpatialOff);
```

with:

```cpp
    // Continuous QSound depth (SPACE). 0 = hard bypass (spatial stage Off).
    // When Motion is armed and 5D's own base is nonzero, Space rides the
    // same morph/Q offset Motion is already producing on this block — the
    // offset magnitude (mod.morph - smoothedMorph, mod.q - smoothedQ) is a
    // direct measure of "how much motion is happening right now" that both
    // the Dynamic (envelope-follower) and Auto*/Wobble (tempo-synced) paths
    // already populate, so no new plumbing is needed to read it.
    const float fiveDBase = juce::jlimit (0.0f, 1.0f, apvts.getRawParameterValue (ParamID::fiveD)->load());
    float space = fiveDBase;
    if (fiveDBase > 0.001f && apvts.getRawParameterValue (ParamID::motionOn)->load() > 0.5f)
    {
        const float offset = std::abs (mod.morph - smoothedMorph) + std::abs (mod.q - smoothedQ);
        space = juce::jlimit (0.0f, 1.0f, fiveDBase + offset);
    }
    params.fiveD = space;
    lastSpaceSent.store (space, std::memory_order_relaxed);
    dspBridge.setSpatialMode (space > 0.001f ? 0 /*QSound*/ : kSpatialOff);
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cmake --build build --target Tests && ctest --test-dir build -R modulation --output-on-failure`
Expected: PASS — all 3 `TEST_CASE`s in `ModulationTileTests.cpp` green, plus
the existing `[motion]`-tagged suite (if re-enabled — see Task 1's note that
`MotionTests.cpp` is currently disabled by a missing-header guard, out of
scope for this plan to fix) unaffected.

- [ ] **Step 7: Commit**

```bash
git add juce-shell/source/PluginProcessor.h juce-shell/source/PluginProcessor.cpp juce-shell/source/SmartMotion.h juce-shell/tests/ModulationTileTests.cpp
git commit -m "Drive Modulation behavior from explicit tile param; add 5D per-body base + ride-along"
```

---

### Task 4: `FiveDTag` recalls the per-body baked amount instead of hardcoded 1.0

**Files:**
- Modify: `juce-shell/source/ui/FiveDTag.h:19-49`

- [ ] **Step 1: Add body lookup and change the click target**

In `juce-shell/source/ui/FiveDTag.h`, add the include and constructor wiring
needed to read the current body index, then change `mouseDown`.

Add near the top includes:

```cpp
#include "../SmartMotion.h"
```

Change the constructor (lines 19-33) to also grab the body parameter:

```cpp
    FiveDTag (juce::AudioProcessorValueTreeState& apvts, const Theme& theme)
        : state (apvts), t (theme)
    {
        param = state.getParameter (ParamID::fiveD);
        if (param != nullptr)
        {
            attachment = std::make_unique<juce::ParameterAttachment> (
                *param, [this] (float) { repaint(); });
            attachment->sendInitialUpdate();
        }
        bodyParam = state.getParameter (ParamID::body);
        setInterceptsMouseClicks (true, false);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        setTitle ("5D");
        setHelpText ("Toggle 5D spatial (QSound)");
    }
```

Change `mouseDown` (lines 43-49):

```cpp
    void mouseDown (const juce::MouseEvent&) override
    {
        if (param == nullptr || attachment == nullptr)
            return;
        const int bodyIndex = bodyParam != nullptr
            ? juce::roundToInt (bodyParam->convertFrom0to1 (bodyParam->getValue()))
            : 0;
        const float onAmount = trench::fiveDBaseAmountFor (bodyIndex);
        attachment->setValueAsCompleteGesture (param->convertFrom0to1 (isOn() ? 0.0f : onAmount));
        repaint();
    }
```

Add the new member near `param`/`attachment` (private section):

```cpp
    juce::RangedAudioParameter* bodyParam = nullptr;
```

- [ ] **Step 2: Manual verification (no new automated test — this is a UI
  click-target change with no new observable DSP behavior beyond what
  Task 3's 5D tests already cover)**

Build the standalone/plugin per `juce-shell/build-standalone.ps1`, load each
of the 3 shipping bodies, click 5D on for each, and confirm (via the
existing dev `RigPanel`, or a temporary log) that the `fiveD` parameter
lands on that body's `kFiveDBaseAmount` row value, not `1.0`.

- [ ] **Step 3: Commit**

```bash
git add juce-shell/source/ui/FiveDTag.h
git commit -m "5D recalls the per-body baked amount instead of always snapping to max"
```

---

### Task 5: `ModulateTag` becomes a trigger, not a direct param-writer

**Files:**
- Modify: `juce-shell/source/ui/ModulateTag.h`

- [ ] **Step 1: Replace direct behavior-setting with a callback**

The tag no longer decides *which* behavior to arm (that's now the grid's
job) — it only reflects armed/disarmed state and, on click, asks something
else (the grid) to open. Replace the whole file:

```cpp
#pragma once

#include "Theme.h"
#include "../TrenchBodyRoster.h"
#include "../parameters/TrenchParameters.h"

#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_gui_basics/juce_gui_basics.h>
#include <functional>
#include <memory>

namespace trench::ui
{

// Seated MOTION switch on the graph glass. Clicking it no longer arms a
// behavior directly (that decision moved to the tile grid on GraphDisplay,
// via onRequestGrid) — it only reflects the current armed/disarmed state.
class ModulateTag : public juce::Component
{
public:
    static inline const juce::Colour kQuietInk { 0xffd9bcc4 };

    std::function<void()> onRequestGrid; // set by PluginEditor -> graph->openTileGrid()

    ModulateTag (juce::AudioProcessorValueTreeState& apvts, const Theme& theme)
        : state (apvts), t (theme)
    {
        motionOnParam = state.getParameter (ParamID::motionOn);
        if (motionOnParam != nullptr)
        {
            attachment = std::make_unique<juce::ParameterAttachment> (
                *motionOnParam, [this] (float) { repaint(); });
            attachment->sendInitialUpdate();
        }

        setInterceptsMouseClicks (true, false);
        setMouseCursor (juce::MouseCursor::PointingHandCursor);
        setTitle ("Motion");
        setHelpText ("Open the Modulation tile grid");
    }

    void mouseEnter (const juce::MouseEvent&) override { hover = true; repaint(); }
    void mouseExit  (const juce::MouseEvent&) override { hover = false; repaint(); }

    bool hitTest (int x, int y) override
    {
        return wordHitBounds().contains ((float) x, (float) y);
    }

    void mouseDown (const juce::MouseEvent&) override
    {
        down = true;
        repaint();
        if (onRequestGrid)
            onRequestGrid();
    }

    void mouseUp (const juce::MouseEvent&) override
    {
        down = false;
        repaint();
    }

    void paint (juce::Graphics& g) override
    {
        const bool on = isOn();
        const auto b = getLocalBounds().toFloat();
        const auto amberOrange = t.amber();
        const auto dotRect = lampBounds (b);

        if (on)
        {
            g.setColour (amberOrange.withAlpha (0.22f));
            g.fillEllipse (dotRect.expanded (5.5f));
            g.setColour (amberOrange.withAlpha (0.50f));
            g.fillEllipse (dotRect.expanded (2.5f));
            g.setColour (amberOrange.brighter (0.35f));
            g.fillEllipse (dotRect);
        }
        else
        {
            g.setColour (kQuietInk.withAlpha (0.88f));
            g.fillEllipse (dotRect);
        }

        const auto textRect = wordHitBounds().expanded (0.0f, 3.0f);
        auto font = displayFont (12.5f, false).withStyle (juce::Font::italic);
        g.setFont (font);

        if (on)
        {
            g.setColour (amberOrange.withAlpha (0.35f));
            g.drawText ("Modulation", textRect.translated (0.0f, 1.0f), juce::Justification::centredLeft);
            g.setColour (juce::Colour (0xfffbeadd).withAlpha (hover ? 1.0f : 0.96f));
        }
        else
            g.setColour (kQuietInk.withAlpha (hover ? 1.0f : 0.88f));

        g.drawText ("Modulation", textRect, juce::Justification::centredLeft);
    }

private:
    static juce::Rectangle<float> lampBounds (juce::Rectangle<float> b)
    {
        constexpr float dotSize = 8.0f;
        return juce::Rectangle<float> (dotSize, dotSize)
            .withCentre ({ b.getX() + dotSize / 2.0f + 2.0f, b.getCentreY() });
    }

    juce::Rectangle<float> wordHitBounds() const
    {
        const auto b = getLocalBounds().toFloat();
        const auto font = displayFont (12.5f, false).withStyle (juce::Font::italic);
        const auto dot = lampBounds (b);
        const float w = juce::GlyphArrangement::getStringWidth (font, "Modulation") + 8.0f;
        const float h = juce::jmax (16.0f, font.getHeight() + 4.0f);
        return { dot.getRight() + 4.0f, b.getCentreY() - h * 0.5f, w, h };
    }

    bool isOn() const { return motionOnParam != nullptr && motionOnParam->getValue() > 0.5f; }

    juce::AudioProcessorValueTreeState& state;
    Theme t;
    juce::RangedAudioParameter* motionOnParam = nullptr;
    std::unique_ptr<juce::ParameterAttachment> attachment;
    bool hover = false;
    bool down = false;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ModulateTag)
};

} // namespace trench::ui
```

Note: this drops the old `currentBehavior()`/`autoBehaviorForCurrentBody()`/
`defaultOnBehaviorForCurrentBody()`/`setBehavior()` name-matching entirely —
that logic is now obsolete (Task 3 replaced its call site) and is not needed
anywhere else (`Grep` confirms `ModulateTag` methods are not called outside
this file and `PluginEditor.cpp`, which Task 7 updates).

- [ ] **Step 2: Commit**

```bash
git add juce-shell/source/ui/ModulateTag.h
git commit -m "ModulateTag triggers the tile grid instead of picking a behavior itself"
```

---

### Task 6: CRT transition + 2x2 tile grid in `GraphDisplay`

**Files:**
- Modify: `juce-shell/source/ui/GraphDisplay.h`

This is the largest single change. `GraphDisplay` gains a screen-mode state
machine (`Curve` -> `Collapsing` -> `Grid` -> `Expanding` -> back to
`Curve`), driven by the existing `juce::Timer` it already inherits (reused,
not duplicated).

- [ ] **Step 1: Add includes, mode enum, and new public API**

At the top of `GraphDisplay.h`, add:

```cpp
#include "../parameters/TrenchParameters.h"
#include "../SmartMotion.h"
```

Inside the class, add a public method (near `setMotionState`):

```cpp
    // Called by ModulateTag::onRequestGrid. Starts the CRT-collapse; the
    // grid itself appears once the collapse finishes (see timerCallback).
    void openTileGrid()
    {
        if (screenMode != ScreenMode::Curve)
            return;
        screenMode = ScreenMode::Collapsing;
        transitionProgress = 0.0f;
        startTimer (16); // ~60 fps
    }
```

- [ ] **Step 2: Add the mode/transition state and constructor wiring**

Add to the private section (near `bool motionActive`):

```cpp
    enum class ScreenMode { Curve, Collapsing, Grid, Expanding };
    ScreenMode screenMode = ScreenMode::Curve;
    float transitionProgress = 0.0f; // 0..1 within the current Collapsing/Expanding phase
    static constexpr float kTransitionSeconds = 0.18f;

    juce::RangedAudioParameter* motionOnParamForTiles = nullptr;
    juce::RangedAudioParameter* motionTileParamForTiles = nullptr;
```

Change the constructor signature and body to also capture these (the
constructor already receives `apvts` — it just wasn't stored before):

```cpp
    GraphDisplay (juce::Image grid, const Theme& theme,
                  juce::AudioProcessorValueTreeState& apvts, const juce::String& canvasParamId)
        : gridImage (std::move (grid)), t (theme)
    {
        canvasParam = apvts.getParameter (canvasParamId);
        if (canvasParam != nullptr)
        {
            canvasAtt = std::make_unique<juce::ParameterAttachment> (*canvasParam, [this] (float)
            {
                meterAlpha = 1.0f;
                if (! pressing) startTimer (30);
                repaint();
            });
            canvasDefault = canvasParam->getDefaultValue();
            setMouseCursor (juce::MouseCursor::UpDownResizeCursor);
        }
        motionOnParamForTiles = apvts.getParameter (ParamID::motionOn);
        motionTileParamForTiles = apvts.getParameter (ParamID::motionTile);
        setInterceptsMouseClicks (canvasParam != nullptr, false);
    }
```

- [ ] **Step 3: Add tile hit-testing and tap handling**

`GraphDisplay::mouseDown` currently drives SLAM unconditionally when
`canvasParam != nullptr`. Grid-mode taps must intercept first. Change
`mouseDown` (existing lines 157-168):

```cpp
    void mouseDown (const juce::MouseEvent& e) override
    {
        if (screenMode == ScreenMode::Grid)
        {
            tileTapped (tileIndexAt (e.position));
            return;
        }
        if (screenMode != ScreenMode::Curve)
            return; // mid-transition: ignore input
        if (canvasParam == nullptr) return;
        pressing = true;
        stopTimer();
        meterAlpha = 1.0f;
        dragStartY = e.position.y;
        dragPos = e.position;
        canvasAtStart = canvasParam->getValue();
        if (canvasAtt != nullptr) canvasAtt->beginGesture();
        repaint();
    }
```

Guard `mouseDrag`, `mouseUp`, `mouseWheelMove`, `mouseDoubleClick` the same
way — each should no-op when `screenMode != ScreenMode::Curve`. Add at the
top of each of those four methods:

```cpp
        if (screenMode != ScreenMode::Curve) return;
```

(Insert this as the first line of `mouseDrag`, `mouseUp`,
`mouseDoubleClick`, and `mouseWheelMove`, before their existing bodies.)

Add the new private helpers (near `plotBounds()`):

```cpp
    // 2x2 grid: 0=Riser (top-left), 1=Breathe (top-right),
    //           2=Adlib Chop (bottom-left), 3=Wobble (bottom-right).
    int tileIndexAt (juce::Point<float> p) const
    {
        const auto plot = plotBounds();
        if (! plot.contains (p))
            return -1;
        const int col = (p.x < plot.getCentreX()) ? 0 : 1;
        const int row = (p.y < plot.getCentreY()) ? 0 : 1;
        return row * 2 + col;
    }

    juce::Rectangle<float> tileBounds (int index) const
    {
        const auto plot = plotBounds();
        const float w = plot.getWidth() * 0.5f;
        const float h = plot.getHeight() * 0.5f;
        const int col = index % 2;
        const int row = index / 2;
        return { plot.getX() + col * w, plot.getY() + row * h, w, h };
    }

    void tileTapped (int index)
    {
        if (index < 0 || index > 3 || motionOnParamForTiles == nullptr || motionTileParamForTiles == nullptr)
        {
            screenMode = ScreenMode::Expanding;
            transitionProgress = 0.0f;
            startTimer (16);
            return;
        }

        const bool alreadyArmed = motionOnParamForTiles->getValue() > 0.5f;
        const int currentTile = juce::roundToInt (motionTileParamForTiles->convertFrom0to1 (motionTileParamForTiles->getValue()));

        if (alreadyArmed && currentTile == index)
        {
            motionOnParamForTiles->setValueNotifyingHost (0.0f); // off
        }
        else
        {
            motionTileParamForTiles->setValueNotifyingHost (motionTileParamForTiles->convertTo0to1 ((float) index));
            motionOnParamForTiles->setValueNotifyingHost (1.0f); // on
        }

        screenMode = ScreenMode::Expanding;
        transitionProgress = 0.0f;
        startTimer (16);
    }
```

- [ ] **Step 4: Drive the transition and grid content in `paint()`**

Replace the `paint()` method (existing lines 204-228):

```cpp
    void paint (juce::Graphics& g) override
    {
        const float rad = 9.0f;
        const auto screen = getLocalBounds().toFloat();

        juce::Path face;
        face.addRoundedRectangle (screen, rad);
        juce::Graphics::ScopedSaveState save (g);
        g.reduceClipRegion (face);

        armed = canvasParam != nullptr
                    ? juce::jlimit (0.0f, 1.0f, (canvasParam->getValue() - 0.15f) / 0.60f)
                    : 0.0f;

        if (screenMode == ScreenMode::Curve)
        {
            drawResponseTrace (g);
            drawSlamReadout (g, screen);
            return;
        }

        // Collapsing/Expanding: vertical squeeze toward a bright horizontal
        // line (classic CRT power-off/-on), then blank at zero height.
        const float collapse = (screenMode == ScreenMode::Collapsing)
            ? transitionProgress : (1.0f - transitionProgress);
        const float lineHeight = juce::jmax (1.0f, screen.getHeight() * (1.0f - collapse));
        const auto squeezed = screen.withSizeKeepingCentre (screen.getWidth(), lineHeight);

        juce::Graphics::ScopedSaveState squeezeSave (g);
        g.reduceClipRegion (squeezed.toNearestInt());

        if (screenMode == ScreenMode::Grid || collapse < 0.98f)
        {
            if (screenMode == ScreenMode::Grid)
                drawTileGrid (g, screen);
            else
                drawResponseTrace (g); // curve visible through the still-open slit
        }

        // Hot phosphor line at the collapsing edge.
        g.setColour (juce::Colour (0xfffff7fa).withAlpha (juce::jlimit (0.0f, 1.0f, collapse) * 0.9f));
        g.fillRect (squeezed.withHeight (juce::jmin (2.0f, squeezed.getHeight())).withCentre (squeezed.getCentre()));
    }
```

- [ ] **Step 5: Add `drawTileGrid` and the `timerCallback` transition driver**

Add the drawing method (near `drawSlamReadout`):

```cpp
    // Crude pictogram + label per tile — deliberately simple line-glyphs,
    // matching the faceplate's "quiet, utilitarian" line language rather
    // than full icon artwork.
    void drawTileGrid (juce::Graphics& g, juce::Rectangle<float> screen) const
    {
        juce::ignoreUnused (screen);
        static constexpr const char* kNames[4] = { "Riser", "Breathe", "Adlib Chop", "Wobble" };
        const int activeTile = (motionOnParamForTiles != nullptr && motionOnParamForTiles->getValue() > 0.5f
                                 && motionTileParamForTiles != nullptr)
            ? juce::roundToInt (motionTileParamForTiles->convertFrom0to1 (motionTileParamForTiles->getValue()))
            : -1;

        for (int i = 0; i < 4; ++i)
        {
            const auto r = tileBounds (i).reduced (6.0f);
            const bool lit = (i == activeTile);

            g.setColour (t.curveColour().withAlpha (lit ? 0.16f : 0.06f));
            g.fillRoundedRectangle (r, 4.0f);

            const auto glyph = r.reduced (r.getWidth() * 0.28f, r.getHeight() * 0.34f);
            g.setColour (t.curveColour().withAlpha (lit ? 0.95f : 0.55f));
            juce::Path p;
            switch (i)
            {
                case 0: // Riser: ascending line
                    p.startNewSubPath (glyph.getBottomLeft());
                    p.lineTo (glyph.getTopRight());
                    break;
                case 1: // Breathe: single hump
                    p.startNewSubPath (glyph.getBottomLeft());
                    p.quadraticTo (glyph.getCentreX(), glyph.getY(), glyph.getBottomRight().x, glyph.getBottomRight().y);
                    break;
                case 2: // Adlib Chop: jagged pulse
                    p.startNewSubPath (glyph.getX(), glyph.getBottom());
                    p.lineTo (glyph.getX() + glyph.getWidth() * 0.25f, glyph.getY());
                    p.lineTo (glyph.getX() + glyph.getWidth() * 0.5f, glyph.getBottom());
                    p.lineTo (glyph.getX() + glyph.getWidth() * 0.75f, glyph.getY());
                    p.lineTo (glyph.getRight(), glyph.getBottom());
                    break;
                default: // Wobble: random zigzag
                    p.startNewSubPath (glyph.getX(), glyph.getCentreY());
                    p.lineTo (glyph.getX() + glyph.getWidth() * 0.3f, glyph.getY());
                    p.lineTo (glyph.getX() + glyph.getWidth() * 0.6f, glyph.getBottom());
                    p.lineTo (glyph.getRight(), glyph.getCentreY() - glyph.getHeight() * 0.2f);
                    break;
            }
            g.strokePath (p, { 1.4f, juce::PathStrokeType::curved, juce::PathStrokeType::rounded });

            g.setFont (displayFont (10.0f, false));
            g.setColour (t.curveColour().withAlpha (lit ? 0.95f : 0.6f));
            g.drawText (kNames[i], r.withTop (r.getBottom() - 14.0f), juce::Justification::centred, false);
        }
    }
```

Replace the existing `timerCallback` (lines 410-415, the one used for
`meterAlpha` fade) to also drive the transition:

```cpp
    void timerCallback() override
    {
        if (screenMode == ScreenMode::Collapsing || screenMode == ScreenMode::Expanding)
        {
            transitionProgress += (float) (16.0 / 1000.0) / kTransitionSeconds;
            if (transitionProgress >= 1.0f)
            {
                transitionProgress = 1.0f;
                if (screenMode == ScreenMode::Collapsing)
                {
                    screenMode = ScreenMode::Grid;
                }
                else // Expanding finished
                {
                    screenMode = ScreenMode::Curve;
                    stopTimer();
                }
            }
            repaint();
            return;
        }

        meterAlpha = juce::jmax (0.0f, meterAlpha - 0.05f);
        if (meterAlpha <= 0.01f) stopTimer();
        repaint();
    }
```

Note: while `screenMode == ScreenMode::Grid`, the timer is stopped (no
`startTimer` call keeps it running), so the grid sits still until a tile is
tapped (`tileTapped` calls `startTimer (16)` again to drive the Expanding
phase) — this matches the "auto closes on selection" decision.

- [ ] **Step 6: Manual verification (UI code — no automated test; per
  project law this must be checked in a real build screenshot, not claimed
  from source alone)**

Build per `juce-shell/build-standalone.ps1`. In a real running instance:
1. Screenshot the curve view.
2. Click Modulation; screenshot mid-collapse (catch a frame where the line
   is visibly thin) and the settled 2x2 grid.
3. Tap each of the 4 tiles in turn; confirm each returns to the curve view
   with Modulation lit, and the graph's existing `setMotionState` LED/step
   readout (already wired at `PluginEditor.cpp:289-292`) reflects the newly
   armed tile.
4. Tap the lit tile's position again (re-open the grid via Modulation,
   then tap the same tile); confirm Modulation turns off.

- [ ] **Step 7: Commit**

```bash
git add juce-shell/source/ui/GraphDisplay.h
git commit -m "Add CRT-transition 2x2 tile grid to GraphDisplay"
```

---

### Task 7: Wire the grid trigger in `PluginEditor`

**Files:**
- Modify: `juce-shell/source/PluginEditor.cpp`

- [ ] **Step 1: Connect `ModulateTag::onRequestGrid` to `GraphDisplay::openTileGrid`**

In `juce-shell/source/PluginEditor.cpp`, after line 31
(`fiveDTag = std::make_unique<FiveDTag> (...)`), add:

```cpp
    modulateTag->onRequestGrid = [this] { graph->openTileGrid(); };
```

(`graph` is already constructed above `modulateTag` at line 28, so it is
valid at this point.)

- [ ] **Step 2: Build and manually verify the wiring**

Build the standalone/plugin. Click Modulation; confirm the grid opens (this
exercises the same real-build check as Task 6 Step 6, now through the
actual click path rather than calling `openTileGrid()` directly).

- [ ] **Step 3: Commit**

```bash
git add juce-shell/source/PluginEditor.cpp
git commit -m "Wire ModulateTag click to open the GraphDisplay tile grid"
```

---

### Task 8: Full verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `cmake --build build --target Tests && ctest --test-dir build --output-on-failure`
Expected: PASS — all new tests (`SmartMotionTests.cpp`,
`ModulationTileTests.cpp`) plus every previously-passing test, unaffected.

- [ ] **Step 2: Real-build screenshot walkthrough (per project law — no
  claim without a real 1:1 screenshot)**

For each of the 3 shipping bodies (Meaty Gizmo, Talking Hedz, Lucifers Q):
1. Screenshot the curve view, Modulation off.
2. Open the grid; screenshot all 4 tiles visible.
3. Arm each of the 4 tiles in turn; screenshot the curve view with
   Modulation lit and confirm the response curve visibly moves over ~2-4
   seconds (Riser/Breathe/Wobble) or reacts to a played sound (Adlib Chop).
4. With 5D on, confirm the QSound-processed output audibly widens/narrows
   in time with whichever tile is armed (ride-along) versus staying static
   with Modulation off.
5. Disarm via tapping the lit tile again; confirm Modulation turns off and
   5D returns to its static per-body base amount.

- [ ] **Step 3: By-ear tuning pass on the two new placeholder tables**

`kTileAmount` (`SmartMotion.h`) and `kFiveDBaseAmount` (`SmartMotion.h`) ship
with placeholder starting values (Task 1 Step 4, Task 3 Step 5). This step
is Tyson's own pass, not automatable: audition each (body, tile) pair on
real program material (per CLAUDE.md §11.5's audition classes) and adjust
the two tables' numbers directly in `SmartMotion.h` until each of the 12
combinations (3 bodies x 4 tiles) sounds right, plus the 3 `kFiveDBaseAmount`
values. No plot or test gates this — it is an ear judgment, per the
project's "taste is his by ear" law.

- [ ] **Step 4: Final commit (only if Step 3 changed values)**

```bash
git add juce-shell/source/SmartMotion.h
git commit -m "Tune per-body tile Amount and 5D base amount tables by ear"
```
