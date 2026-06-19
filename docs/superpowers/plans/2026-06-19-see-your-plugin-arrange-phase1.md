# See Your Plugin — Arrange Phase 1 (layout file + hot-reload) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the TRENCH plugin read control positions/sizes/text-style from an on-disk `ui_layout.json` and hot-reload it, falling back to today's exact hardcoded values when the file is absent or malformed — so layout can change without a rebuild.

**Architecture:** A small header-only `trench::UiLayout` value type owns the five element rects (+ optional readout text style) and all JSON parsing/validation, with the current shipped rects as its `defaults()`. `PluginEditor`'s five "well" functions become members that read the live `UiLayout`; the existing 24 Hz timer reloads the file when its modification time changes. The plugin runtime reads only rects + style; it ignores any future `groups`/`rules`.

**Tech Stack:** C++20, JUCE 8 (`juce::JSON`, `juce::var`, `juce::File`, `juce::Rectangle`, `juce::Colour`), Pamplejuce, Catch2 v3, CMake (Visual Studio 17 2022 generator).

**Scope note:** This is the foundation only. The interactive Figma-grade edit mode, the render/scene/validator tool, and the Inspect signal schematic are each separate plans built on top of this one. See `docs/superpowers/specs/2026-06-19-trench-ui-layout-loop-design.md`.

**Conventions for every command below:** run from the repo root `C:\Users\hooki\df2`. The first `Tests` build is slow (JUCE compiles). New test `.cpp` files are picked up automatically (the test CMake uses `CONFIGURE_DEPENDS` globbing), so no manual reconfigure is needed.

---

## File Structure

- **Create** `juce-shell/source/UiLayout.h` — the `trench::UiLayout` value type: defaults, accessors, JSON parse/validate, file load. One responsibility: own layout data and its parsing. Header-only inline, matching the existing `TrenchBodyRoster.h` style.
- **Create** `juce-shell/tests/UiLayoutTests.cpp` — Catch2 unit tests for `UiLayout` (auto-globbed into the `Tests` target).
- **Create** `juce-shell/assets/ui/ui_layout.seed.json` — a template equal to the defaults, to copy to `~/Documents/TRENCH/ui_layout.json`.
- **Modify** `juce-shell/source/PluginEditor.h` — add the `UiLayout.h` include, the five well member declarations, `reloadLayoutIfChanged()`, and the `currentLayout` + `layoutFileModTime` members.
- **Modify** `juce-shell/source/PluginEditor.cpp` — remove the five free well functions; add member well functions reading `currentLayout`; load layout in the constructor; reload on timer; apply readout text style.

---

## Task 1: `UiLayout` defaults + accessors

**Files:**
- Create: `juce-shell/source/UiLayout.h`
- Test: `juce-shell/tests/UiLayoutTests.cpp`

- [ ] **Step 1: Write the failing test**

Create `juce-shell/tests/UiLayoutTests.cpp`:

```cpp
#include <catch2/catch_all.hpp>

#include "UiLayout.h"

using trench::UiLayout;

TEST_CASE ("Default UI layout matches the shipped well rectangles")
{
    const auto d = UiLayout::defaults();
    REQUIRE (d.sourceRectFor ("morphWheel")   == juce::Rectangle<float> (127, 694, 423, 101));
    REQUIRE (d.sourceRectFor ("qWheel")       == juce::Rectangle<float> (127, 871, 423, 101));
    REQUIRE (d.sourceRectFor ("typeSelector") == juce::Rectangle<float> (230, 142, 672, 73));
    REQUIRE (d.sourceRectFor ("morphReadout") == juce::Rectangle<float> (603, 712, 168, 77));
    REQUIRE (d.sourceRectFor ("qReadout")     == juce::Rectangle<float> (602, 889, 169, 79));
    REQUIRE (d.sourceRectFor ("unknownId")    == juce::Rectangle<float> ()); // fallback default
}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Expected: FAIL — compile error, `UiLayout.h` not found (header does not exist yet).

- [ ] **Step 3: Write minimal implementation**

Create `juce-shell/source/UiLayout.h`:

```cpp
#pragma once

#include <juce_core/juce_core.h>
#include <juce_graphics/juce_graphics.h>

#include <map>
#include <optional>

namespace trench
{

struct UiElementLayout
{
    juce::Rectangle<float> sourceRect;          // 1024x1591 source space
    std::optional<float> fontSize;              // text-style overrides (readouts)
    std::optional<juce::Colour> textColour;
};

class UiLayout
{
public:
    // Single source of truth for the shipped defaults (mirrors the rects that
    // were hardcoded in PluginEditor.cpp).
    static UiLayout defaults()
    {
        UiLayout layout;
        layout.elements["morphWheel"]   = { { 127.0f, 694.0f, 423.0f, 101.0f }, {}, {} };
        layout.elements["qWheel"]       = { { 127.0f, 871.0f, 423.0f, 101.0f }, {}, {} };
        layout.elements["typeSelector"] = { { 230.0f, 142.0f, 672.0f, 73.0f },  {}, {} };
        layout.elements["morphReadout"] = { { 603.0f, 712.0f, 168.0f, 77.0f },  {}, {} };
        layout.elements["qReadout"]     = { { 602.0f, 889.0f, 169.0f, 79.0f },  {}, {} };
        return layout;
    }

    juce::Rectangle<float> sourceRectFor (const juce::String& id,
                                          juce::Rectangle<float> fallback = {}) const
    {
        const auto it = elements.find (id);
        return it != elements.end() ? it->second.sourceRect : fallback;
    }

    std::optional<float> fontSizeFor (const juce::String& id) const
    {
        const auto it = elements.find (id);
        return it != elements.end() ? it->second.fontSize : std::nullopt;
    }

    std::optional<juce::Colour> textColourFor (const juce::String& id) const
    {
        const auto it = elements.find (id);
        return it != elements.end() ? it->second.textColour : std::nullopt;
    }

    std::map<juce::String, UiElementLayout> elements;
};

} // namespace trench
```

- [ ] **Step 4: Run build + test to verify it passes**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe "Default UI layout matches the shipped well rectangles"`
Expected: PASS (1 test case).

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/UiLayout.h juce-shell/tests/UiLayoutTests.cpp
git commit -m "feat(ui-layout): UiLayout defaults + accessors for the five wells"
```

---

## Task 2: JSON parse, merge, and validation

**Files:**
- Modify: `juce-shell/source/UiLayout.h`
- Test: `juce-shell/tests/UiLayoutTests.cpp`

- [ ] **Step 1: Write the failing tests**

Append to `juce-shell/tests/UiLayoutTests.cpp`:

```cpp
TEST_CASE ("Malformed or versionless JSON falls back to defaults")
{
    const auto d = UiLayout::defaults();

    // Void var (e.g. parse failure) -> defaults unchanged.
    REQUIRE (UiLayout::fromJson (juce::var(), d).sourceRectFor ("morphWheel")
             == d.sourceRectFor ("morphWheel"));

    // Object without version -> defaults unchanged.
    auto* obj = new juce::DynamicObject();
    obj->setProperty ("elements", juce::var());
    REQUIRE (UiLayout::fromJson (juce::var (obj), d).sourceRectFor ("qWheel")
             == d.sourceRectFor ("qWheel"));
}

TEST_CASE ("A valid override changes only the named element")
{
    const auto d = UiLayout::defaults();
    const auto json = juce::JSON::parse (R"({
        "version": 1,
        "elements": { "morphReadout": { "rect": [600, 700, 160, 70] } }
    })");
    const auto l = UiLayout::fromJson (json, d);
    REQUIRE (l.sourceRectFor ("morphReadout") == juce::Rectangle<float> (600, 700, 160, 70));
    REQUIRE (l.sourceRectFor ("qReadout")     == d.sourceRectFor ("qReadout"));
    REQUIRE (l.sourceRectFor ("morphWheel")   == d.sourceRectFor ("morphWheel"));
}

TEST_CASE ("Unknown element ids are ignored")
{
    const auto d = UiLayout::defaults();
    const auto json = juce::JSON::parse (R"({ "version": 1, "elements": { "foobar": { "rect": [1,2,3,4] } } })");
    const auto l = UiLayout::fromJson (json, d);
    REQUIRE (l.elements.find ("foobar") == l.elements.end());
    REQUIRE (l.sourceRectFor ("morphWheel") == d.sourceRectFor ("morphWheel"));
}

TEST_CASE ("Invalid rect leaves that element at its default")
{
    const auto d = UiLayout::defaults();
    const auto json = juce::JSON::parse (R"({
        "version": 1,
        "elements": {
            "morphWheel":   { "rect": [1, 2, 3] },
            "qWheel":       { "rect": [1, 2, 0, 10] },
            "typeSelector": { "rect": [1, 2, 3, "x"] }
        }
    })");
    const auto l = UiLayout::fromJson (json, d);
    REQUIRE (l.sourceRectFor ("morphWheel")   == d.sourceRectFor ("morphWheel"));
    REQUIRE (l.sourceRectFor ("qWheel")       == d.sourceRectFor ("qWheel"));
    REQUIRE (l.sourceRectFor ("typeSelector") == d.sourceRectFor ("typeSelector"));
}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Expected: FAIL — compile error, `UiLayout::fromJson` not declared.

- [ ] **Step 3: Write minimal implementation**

In `juce-shell/source/UiLayout.h`, add `#include <cmath>` to the includes, then add the public static `fromJson` method and the private helpers inside `class UiLayout` (place `fromJson` right after `textColourFor`, and add a `private:` section before the closing `};`):

```cpp
    // Build from parsed JSON, starting from `fallback` and overriding only the
    // elements the JSON validly specifies. Any structural problem (not an
    // object, or version != 1) returns `fallback` unchanged.
    static UiLayout fromJson (const juce::var& json, const UiLayout& fallback)
    {
        if (! json.isObject())
            return fallback;
        if ((int) json.getProperty ("version", juce::var()) != 1)
            return fallback;

        UiLayout result = fallback;
        const auto elementsVar = json.getProperty ("elements", juce::var());
        if (auto* obj = elementsVar.getDynamicObject())
        {
            for (const auto& kv : obj->getProperties())
            {
                const juce::String id = kv.name.toString();
                if (result.elements.find (id) == result.elements.end())
                    continue; // unknown id ignored
                applyElement (result.elements[id], kv.value);
            }
        }
        return result;
    }

private:
    static void applyElement (UiElementLayout& target, const juce::var& elementVar)
    {
        if (! elementVar.isObject())
            return;
        if (auto rect = parseRect (elementVar.getProperty ("rect", juce::var())))
            target.sourceRect = *rect;
    }

    static std::optional<juce::Rectangle<float>> parseRect (const juce::var& rectVar)
    {
        auto* arr = rectVar.getArray();
        if (arr == nullptr || arr->size() != 4)
            return std::nullopt;

        float v[4];
        for (int i = 0; i < 4; ++i)
        {
            const auto& e = (*arr)[i];
            if (! (e.isDouble() || e.isInt()))
                return std::nullopt;
            v[i] = (float) e;
            if (! std::isfinite (v[i]))
                return std::nullopt;
        }
        if (v[2] <= 0.0f || v[3] <= 0.0f) // width/height must be positive
            return std::nullopt;

        return juce::Rectangle<float> { v[0], v[1], v[2], v[3] };
    }
```

Note: the `std::map<...> elements;` member must remain `public` — move it above the new `private:` line if needed so the existing `defaults()`/accessor tests still reach `.elements`.

- [ ] **Step 4: Run build + tests to verify they pass**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe "[.]" "*override*" "*Malformed*" "*Unknown*" "*Invalid rect*"`
Simpler: run the whole UiLayout suite by running all tests and confirming none fail:
`juce-shell/build/Release/Tests.exe`
Expected: PASS — all assertions, including the four new cases.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/UiLayout.h juce-shell/tests/UiLayoutTests.cpp
git commit -m "feat(ui-layout): JSON parse, per-element merge over defaults, rect validation"
```

---

## Task 3: Readout text-style overrides (fontSize, textColor)

**Files:**
- Modify: `juce-shell/source/UiLayout.h`
- Test: `juce-shell/tests/UiLayoutTests.cpp`

- [ ] **Step 1: Write the failing tests**

Append to `juce-shell/tests/UiLayoutTests.cpp`:

```cpp
TEST_CASE ("Readout style overrides parse")
{
    const auto d = UiLayout::defaults();
    const auto json = juce::JSON::parse (R"({
        "version": 1,
        "elements": { "morphReadout": { "rect": [603,712,168,77], "fontSize": 15, "textColor": "ff112233" } }
    })");
    const auto l = UiLayout::fromJson (json, d);
    REQUIRE (l.fontSizeFor ("morphReadout").has_value());
    REQUIRE (*l.fontSizeFor ("morphReadout") == Catch::Approx (15.0f));
    REQUIRE (l.textColourFor ("morphReadout").has_value());
    REQUIRE (*l.textColourFor ("morphReadout") == juce::Colour (0xff112233));
}

TEST_CASE ("Invalid style values are ignored")
{
    const auto d = UiLayout::defaults();
    const auto json = juce::JSON::parse (R"({
        "version": 1,
        "elements": { "qReadout": { "rect": [602,889,169,79], "fontSize": -3, "textColor": "nothex" } }
    })");
    const auto l = UiLayout::fromJson (json, d);
    REQUIRE_FALSE (l.fontSizeFor ("qReadout").has_value());
    REQUIRE_FALSE (l.textColourFor ("qReadout").has_value());
}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe "Readout style overrides parse"`
Expected: FAIL — assertion fails (`has_value()` is false; style not parsed yet).

- [ ] **Step 3: Write minimal implementation**

In `juce-shell/source/UiLayout.h`, extend `applyElement` (after the rect block) and add a `parseColour` helper:

```cpp
        const auto fs = elementVar.getProperty ("fontSize", juce::var());
        if (fs.isDouble() || fs.isInt())
        {
            const float v = (float) fs;
            if (std::isfinite (v) && v > 0.0f)
                target.fontSize = v;
        }

        const auto tc = elementVar.getProperty ("textColor", juce::var());
        if (tc.isString())
            if (auto colour = parseColour (tc.toString()))
                target.textColour = *colour;
```

Add this private helper next to `parseRect`:

```cpp
    static std::optional<juce::Colour> parseColour (const juce::String& hex)
    {
        const auto trimmed = hex.trim();
        if (trimmed.isEmpty() || trimmed.length() > 8)
            return std::nullopt;
        for (auto c : trimmed)
            if (! juce::CharacterFunctions::isHexDigit (c))
                return std::nullopt;
        return juce::Colour ((juce::uint32) trimmed.getHexValue64());
    }
```

- [ ] **Step 4: Run build + tests to verify they pass**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe`
Expected: PASS — all cases including the two new style cases.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/UiLayout.h juce-shell/tests/UiLayoutTests.cpp
git commit -m "feat(ui-layout): validated readout fontSize + textColor overrides"
```

---

## Task 4: File path + load-from-file with fallback

**Files:**
- Modify: `juce-shell/source/UiLayout.h`
- Test: `juce-shell/tests/UiLayoutTests.cpp`

- [ ] **Step 1: Write the failing test**

Append to `juce-shell/tests/UiLayoutTests.cpp`:

```cpp
TEST_CASE ("loadUiLayoutFromFile reads overrides and falls back when absent")
{
    const auto d = UiLayout::defaults();

    auto temp = juce::File::createTempFile (".json");
    temp.replaceWithText (R"({ "version": 1, "elements": { "qReadout": { "rect": [10,20,30,40] } } })");
    const auto loaded = trench::loadUiLayoutFromFile (temp);
    REQUIRE (loaded.sourceRectFor ("qReadout") == juce::Rectangle<float> (10, 20, 30, 40));
    REQUIRE (loaded.sourceRectFor ("morphWheel") == d.sourceRectFor ("morphWheel"));
    temp.deleteFile();

    auto missing = juce::File::getSpecialLocation (juce::File::tempDirectory)
                       .getChildFile ("trench_nonexistent_layout_xyz.json");
    missing.deleteFile();
    REQUIRE (trench::loadUiLayoutFromFile (missing).sourceRectFor ("morphWheel")
             == d.sourceRectFor ("morphWheel"));
}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Expected: FAIL — compile error, `trench::loadUiLayoutFromFile` not declared.

- [ ] **Step 3: Write minimal implementation**

In `juce-shell/source/UiLayout.h`, after the closing `};` of `class UiLayout` (still inside `namespace trench`), add:

```cpp
inline juce::File uiLayoutFile()
{
    return juce::File::getSpecialLocation (juce::File::userDocumentsDirectory)
               .getChildFile ("TRENCH")
               .getChildFile ("ui_layout.json");
}

inline UiLayout loadUiLayoutFromFile (const juce::File& file)
{
    const auto defaults = UiLayout::defaults();
    if (! file.existsAsFile())
        return defaults;
    return UiLayout::fromJson (juce::JSON::parse (file.loadFileAsString()), defaults);
}

inline UiLayout loadUiLayoutOrDefaults()
{
    return loadUiLayoutFromFile (uiLayoutFile());
}
```

- [ ] **Step 4: Run build + test to verify it passes**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe "loadUiLayoutFromFile reads overrides and falls back when absent"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/UiLayout.h juce-shell/tests/UiLayoutTests.cpp
git commit -m "feat(ui-layout): ui_layout.json path + load-from-file with defaults fallback"
```

---

## Task 5: Wire `UiLayout` into `PluginEditor` (wells read the layout)

**Files:**
- Modify: `juce-shell/source/PluginEditor.h`
- Modify: `juce-shell/source/PluginEditor.cpp`

This task is verified by a clean build and the existing test suite still passing (interactive painting is not unit-testable; correctness here = "compiles, no behavior change when no file is present").

- [ ] **Step 1: Update the header**

In `juce-shell/source/PluginEditor.h`, after `#include "PluginProcessor.h"` add:

```cpp
#include "UiLayout.h"
```

In the `private:` section, add the five well declarations and the reload method (place above `void timerCallback() override;`):

```cpp
    juce::Rectangle<float> morphWheelWell() const;
    juce::Rectangle<float> qWheelWell() const;
    juce::Rectangle<float> typeSelectorWell() const;
    juce::Rectangle<float> morphReadoutWell() const;
    juce::Rectangle<float> qReadoutWell() const;
    void reloadLayoutIfChanged();
```

And add the data members (place after `juce::Image thumbwheelStrip;`):

```cpp
    trench::UiLayout currentLayout { trench::UiLayout::defaults() };
    juce::int64 layoutFileModTime = 0;
```

- [ ] **Step 2: Remove the free well functions in the .cpp**

In `juce-shell/source/PluginEditor.cpp`, delete these five free functions from the anonymous namespace (lines ~40–63): `morphWheelWell()`, `qWheelWell()`, `typeSelectorWell()`, `morphReadoutWell()`, `qReadoutWell()`. Keep `sourceRectToEditor`, `thumbwheelBodyBounds`, `thumbwheelSliderBounds`, and `displayFont` exactly as they are.

- [ ] **Step 3: Add member well functions**

In `juce-shell/source/PluginEditor.cpp`, immediately after the constructor/destructor (after `PluginEditor::~PluginEditor()` body), add:

```cpp
juce::Rectangle<float> PluginEditor::morphWheelWell() const
{
    return sourceRectToEditor (currentLayout.sourceRectFor ("morphWheel"));
}

juce::Rectangle<float> PluginEditor::qWheelWell() const
{
    return sourceRectToEditor (currentLayout.sourceRectFor ("qWheel"));
}

juce::Rectangle<float> PluginEditor::typeSelectorWell() const
{
    return sourceRectToEditor (currentLayout.sourceRectFor ("typeSelector"));
}

juce::Rectangle<float> PluginEditor::morphReadoutWell() const
{
    return sourceRectToEditor (currentLayout.sourceRectFor ("morphReadout"));
}

juce::Rectangle<float> PluginEditor::qReadoutWell() const
{
    return sourceRectToEditor (currentLayout.sourceRectFor ("qReadout"));
}
```

- [ ] **Step 4: Load the layout in the constructor**

In `juce-shell/source/PluginEditor.cpp`, at the very start of the `PluginEditor::PluginEditor (...)` body (before `panelImage = ...`), add:

```cpp
    currentLayout = trench::loadUiLayoutOrDefaults();
    {
        const auto f = trench::uiLayoutFile();
        layoutFileModTime = f.existsAsFile() ? f.getLastModificationTime().toMilliseconds() : 0;
    }
```

- [ ] **Step 5: Build the Tests target and run the full suite**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe`
Expected: PASS — all existing tests plus the UiLayout suite. (No `ui_layout.json` exists in `~/Documents/TRENCH/`, so the editor uses defaults; behavior is unchanged.)

- [ ] **Step 6: Build the plugin to confirm the editor compiles**

Run: `cmake --build juce-shell/build --config Release --target TRENCH_VST3 --parallel`
Expected: build succeeds (no errors). This confirms all callers of the well functions resolved to the new members.

- [ ] **Step 7: Commit**

```bash
git add juce-shell/source/PluginEditor.h juce-shell/source/PluginEditor.cpp
git commit -m "feat(editor): wells read live UiLayout; load ui_layout.json on construct"
```

---

## Task 6: Hot-reload on the existing timer

**Files:**
- Modify: `juce-shell/source/PluginEditor.cpp`

- [ ] **Step 1: Implement `reloadLayoutIfChanged()`**

In `juce-shell/source/PluginEditor.cpp`, add this member function (place near `timerCallback`):

```cpp
void PluginEditor::reloadLayoutIfChanged()
{
    const auto file = trench::uiLayoutFile();
    const auto mod = file.existsAsFile() ? file.getLastModificationTime().toMilliseconds() : 0;
    if (mod == layoutFileModTime)
        return;

    layoutFileModTime = mod;
    currentLayout = trench::loadUiLayoutOrDefaults();
    resized();
    repaint();
}
```

- [ ] **Step 2: Call it from the timer**

In `juce-shell/source/PluginEditor.cpp`, in `PluginEditor::timerCallback()`, add `reloadLayoutIfChanged();` as the first line of the body (before `syncBodySelectorToParameter();`).

- [ ] **Step 3: Build the plugin**

Run: `cmake --build juce-shell/build --config Release --target TRENCH_VST3 --parallel`
Expected: build succeeds.

- [ ] **Step 4: Build the standalone for manual verification**

Run: `cmake --build juce-shell/build --config Release --target TRENCH_Standalone --parallel`
Expected: build succeeds.

- [ ] **Step 5: Manual hot-reload verification**

This is a manual integration check (file watching is glue over already-tested logic):

1. Copy the seed (created in Task 7) to the live path:
   `mkdir -p ~/Documents/TRENCH && cp juce-shell/assets/ui/ui_layout.seed.json ~/Documents/TRENCH/ui_layout.json`
   (If Task 7 is not done yet, write the same JSON content there directly.)
2. Launch the standalone: `juce-shell/build/Release/TRENCH.exe` (path may vary; locate with `find juce-shell/build -iname "TRENCH*.exe"`).
3. Confirm the UI looks identical to before (seed == defaults).
4. Edit `~/Documents/TRENCH/ui_layout.json` — change `morphReadout`'s rect `x` from `603` to `503` and save.
5. Within ~1 second the morph readout shifts left in the running app. Restore the value and confirm it shifts back.

Expected: the control moves on save with no rebuild; an absent or deleted file restores the default layout on next tick.

- [ ] **Step 6: Commit**

```bash
git add juce-shell/source/PluginEditor.cpp
git commit -m "feat(editor): hot-reload ui_layout.json via the editor timer (mtime check)"
```

---

## Task 7: Seed file + usage doc

**Files:**
- Create: `juce-shell/assets/ui/ui_layout.seed.json`
- Modify: `juce-shell/source/PluginEditor.cpp` — apply readout text style

- [ ] **Step 1: Create the seed file**

Create `juce-shell/assets/ui/ui_layout.seed.json` (equal to the defaults so opting in changes nothing until edited):

```json
{
  "version": 1,
  "sourceSpace": [1024, 1591],
  "elements": {
    "morphWheel":   { "rect": [127, 694, 423, 101] },
    "qWheel":       { "rect": [127, 871, 423, 101] },
    "typeSelector": { "rect": [230, 142, 672, 73] },
    "morphReadout": { "rect": [603, 712, 168, 77], "fontSize": 13, "textColor": "ff000000" },
    "qReadout":     { "rect": [602, 889, 169, 79], "fontSize": 13, "textColor": "ff000000" }
  }
}
```

- [ ] **Step 2: Apply readout text style in the editor**

In `juce-shell/source/PluginEditor.cpp`, update the two `drawReadout` calls inside `drawSelectorAndReadouts` to pass the element id instead of the display label:

```cpp
    drawReadout (g, morphReadoutWell(), "morphReadout", readParameter (ParamID::morph));
    drawReadout (g, qReadoutWell(),     "qReadout",     readParameter (ParamID::q));
```

Then replace the body of `PluginEditor::drawReadout` with:

```cpp
void PluginEditor::drawReadout (juce::Graphics& g, juce::Rectangle<float> bounds, const juce::String& elementId, float value)
{
    drawDisplayWell (g, bounds);

    const auto pct = juce::jlimit (0.0f, 1.0f, value) * 100.0f;
    const auto numeric = juce::String (pct, 1);

    const float fontSize = currentLayout.fontSizeFor (elementId).value_or (13.0f);
    const auto colour    = currentLayout.textColourFor (elementId).value_or (juce::Colours::black);

    g.setFont (displayFont (fontSize, false));
    g.setColour (colour);
    g.drawFittedText (numeric, bounds.toNearestInt(), juce::Justification::centred, 1);
}
```

(The header signature `void drawReadout (juce::Graphics&, juce::Rectangle<float>, const juce::String&, float);` is unchanged — the third parameter is now used as the element id.)

- [ ] **Step 3: Build the plugin**

Run: `cmake --build juce-shell/build --config Release --target TRENCH_VST3 --parallel`
Expected: build succeeds. With the seed (or no file), `fontSize`/`textColour` fall back to `13.0f` / black — the current look is preserved.

- [ ] **Step 4: Run the full test suite (regression guard)**

Run: `juce-shell/build/Release/Tests.exe`
Expected: PASS — nothing in the audio/processor tests changed.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/assets/ui/ui_layout.seed.json juce-shell/source/PluginEditor.cpp
git commit -m "feat(ui-layout): seed file + readout text-style overrides applied in editor"
```

---

## Self-Review

**Spec coverage (against `2026-06-19-trench-ui-layout-loop-design.md`, Phase 1 + the rect/style runtime parts of Phase 2 DoD):**
- `ui_layout.json` schema + seed matching defaults → Tasks 1, 7.
- Plugin reads layout; absent/malformed → exact current behavior → Tasks 2, 4, 5 (fallback) + Task 5 Step 5/6 (no-file build/run).
- Plugin runtime reads rect + style only, ignores groups/rules → `fromJson` only consumes `version`/`elements`; `groups`/`rules` are never read.
- Well functions return override-or-default → Task 5.
- Hot-reload via timer mtime check → Task 6.
- Atomic/last-good fallback (no corruption) → `fromJson` returns `fallback` on any structural failure; `loadUiLayoutFromFile` returns defaults when absent (Tasks 2, 4).
- Style (fontSize/textColor) → Tasks 3, 7.

**Deferred to later plans (correctly out of this plan):** the interactive edit mode (select/drag/resize/snap/undo), render/scene/validator, Inspect schematic, and auto-deriving elements from parameters. Each is its own plan.

**Placeholder scan:** no TBD/TODO; every code step shows complete code; every command has expected output. ✓

**Type consistency:** `UiLayout::defaults()`, `sourceRectFor(id, fallback={})`, `fontSizeFor(id)`, `textColourFor(id)`, `fromJson(var, fallback)`, `loadUiLayoutFromFile(File)`, `loadUiLayoutOrDefaults()`, `uiLayoutFile()` are used identically across tasks. The five element ids (`morphWheel`, `qWheel`, `typeSelector`, `morphReadout`, `qReadout`) match the defaults, the JSON, the seed, and the editor calls. ✓

**Accessibility/validation (not cut):** validation lives in `parseRect`/`parseColour`/`fromJson` with explicit tests; malformed input can never corrupt state. Keyboard/contrast accessibility belongs to the interactive edit-mode plan (no new interactive surface is introduced here). ✓
