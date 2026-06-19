# See Your Plugin — Arrange Phase 3 (render + scene + validator + resolver) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. TDD every pure function before its implementation.

**Goal:** Give Claude (and the edit-mode snap engine) an assist/verify layer for the TRENCH layout. Expose the editor's live layout as a structured `getUiDebugTree()`, render the real editor offscreen to a render bundle (`clean.png` 360x560, `overlay.png` with labelled rects, `last.png` before/after, `scene.json`, `validation.json`), and back it with a **pure, unit-tested** validator (overlap / off-canvas / malformed / unknown-rule-id / text-clip / curated-art-hash / rule-within-tolerance) and a **pure, unit-tested** resolver (mutate rects to satisfy a rule, then write `ui_layout.json` — the only write path).

**Architecture:** All decision logic lives in a new header-only `trench` namespace in `juce-shell/source/UiLayoutValidate.h` as free functions over plain data structs (`UiSceneElement`, `UiScene`, `UiRule`, `UiGroup`, `ValidationIssue`, `ValidationReport`). These are pure — no JUCE component, no file I/O, no rendering — so they are fully Catch2-testable. `PluginEditor::getUiDebugTree()` builds a `UiScene` from the *same* `currentLayout` + well functions the painter uses (view of truth, not a reconstruction). A new console target `TrenchRender` (links the existing `SharedCode` interface) constructs `PluginProcessor` + `PluginEditor` under `juce::ScopedJuceInitialiser_GUI`, snapshots the editor into a `juce::Image`, and emits the bundle. The resolver reuses `UiLayout::toJsonString` + `uiLayoutFile`. Rules/groups are parsed by extending `UiLayout` (runtime still ignores them; only the tools read them).

**Tech Stack:** C++20, JUCE 8 (`juce::Component::createComponentSnapshot`, `juce::Image`, `juce::PNGImageFormat`, `juce::Graphics`, `juce::JSON`, `juce::var`, `juce::File`, `juce::Rectangle`, `juce::ScopedJuceInitialiser_GUI`), Pamplejuce, Catch2 v3, CMake (Visual Studio 17 2022 generator).

**depends-on:** `docs/superpowers/plans/2026-06-19-see-your-plugin-arrange-phase1.md` (the `trench::UiLayout` value type + wells-read-layout wiring — already landed; see `juce-shell/source/UiLayout.h` and `PluginEditor.{h,cpp}`). This plan does **not** depend on the edit-mode plan (phase 2).

**Scope note (in / out):**
- **In:** `getUiDebugTree()`; offscreen render bundle; pure validator; pure resolver (single write path); rules/groups parsing in `UiLayout`; before/after image-diff note + semantic rect diff; the `TrenchRender` console target.
- **Out:** interactive edit mode (select/drag/resize/snap/undo — phase 2); the Inspect DSP schematic; AI layout suggestions; any trench-core / packed-coefficient / DSP work. **This is a UI-scene phase (rectangles, overlap, alignment) only — no DSP coefficients are touched.**

**Conventions for every command below:** run from the repo root `C:\Users\hooki\df2` using the Bash tool (Git Bash / POSIX sh). New test `.cpp` files are auto-globbed into `Tests` (the Tests CMake uses `CONFIGURE_DEPENDS`), so no manual reconfigure for test changes. Adding the new `TrenchRender` target **does** require one CMake reconfigure (Task 9).

**KNOWN-RED baseline:** the test `"Default body roster is the requested two P2K references"` already fails on this branch for unrelated reasons. It must stay the *only* failing test — any **new** failure is disallowed. Verify the baseline before starting:
```
cmake --build juce-shell/build --config Release --target Tests --parallel
juce-shell/build/Release/Tests.exe
# Expected: 1 failing test, exactly "Default body roster is the requested two P2K references".
```

---

## File Structure

- **Create** `juce-shell/source/UiLayoutValidate.h` — pure, header-only `trench` types + free functions: scene structs, rule/group structs, scene<->JSON (`sceneToJson`), validator (`validateScene`), report->text (`validationReportToText`), report->JSON (`validationReportToJson`), resolver (`resolveRule` / `resolveAllRules`), and semantic rect diff (`diffScenes`). No JUCE `Component`, no file I/O, no PNG. Header-only inline, matching `UiLayout.h`/`TrenchBodyRoster.h` style.
- **Create** `juce-shell/tests/UiLayoutValidateTests.cpp` — Catch2 unit tests for every pure function above (auto-globbed into `Tests`).
- **Create** `juce-shell/source/TrenchRender.cpp` — the console render harness `main()`: parse `--out <dir>`, init GUI, build processor+editor, snapshot, draw overlay, emit `clean.png`/`overlay.png`/`last.png`/`scene.json`/`validation.json`. Glue only — not unit-tested (manual + build verification).
- **Modify** `juce-shell/source/UiLayout.h` — add `groups` + `rules` parsing (`UiRule`, `UiGroup`) so the tools can read them; runtime keeps reading rect+style only.
- **Modify** `juce-shell/source/PluginEditor.h` — declare `trench::UiScene getUiDebugTree() const;` (public) and a small `panelArtHash() const` helper used by the curated-art check.
- **Modify** `juce-shell/source/PluginEditor.cpp` — implement `getUiDebugTree()` (sourced from `currentLayout` + the well functions) and `panelArtHash()`.
- **Modify** `juce-shell/CMakeLists.txt` — add the `TrenchRender` console target linking `SharedCode`.

---

## Data model (used across all tasks — keep types identical everywhere)

```cpp
// in juce-shell/source/UiLayoutValidate.h, namespace trench

struct UiSceneElement
{
    juce::String id;
    juce::Rectangle<float> sourceRect;          // 1024x1591 source space
    juce::Rectangle<float> editorRect;          // 360x560 editor space
    bool visible = true;
    int zIndex = 0;
    juce::String text;                          // current/sample text drawn, "" if none
    float fontSize = 0.0f;                      // 0 = not text-bearing / default
    juce::String textColour;                    // "aarrggbb" hex, "" if none
    bool rectValid = true;                      // false => missing/malformed rect
};

struct UiScene
{
    int sourceW = 1024;
    int sourceH = 1591;
    int editorW = 360;
    int editorH = 560;
    juce::String panelArtHash;                  // curated-art fingerprint, "" if unknown
    std::vector<UiSceneElement> elements;
};

struct UiRule
{
    juce::String type;                          // sameX|sameY|sameWidth|sameHeight|centerX|centerY
    std::vector<juce::String> elements;         // sameX/Y/Width/Height: 2+ ids
    juce::String a, b;                          // centerX/centerY: a vs b
};

struct UiGroup
{
    juce::String name;
    std::vector<juce::String> elements;
};
```

`UiRule`/`UiGroup` are also added to `UiLayout` (Task 0) so the loader carries them.

---

## Task 0: Parse `groups` + `rules` in `UiLayout` (tools-only)

**Files:**
- Modify: `juce-shell/source/UiLayout.h`
- Test: `juce-shell/tests/UiLayoutValidateTests.cpp`

The plugin runtime ignores groups/rules; the validator/resolver need them. Parse them into `UiLayout` so the loader is the single source.

- [ ] **Step 1: Write the failing test**

Create `juce-shell/tests/UiLayoutValidateTests.cpp` with:

```cpp
#include <catch2/catch_all.hpp>

#include "UiLayout.h"

using trench::UiLayout;

TEST_CASE ("UiLayout parses optional groups and rules; runtime rect-only is untouched")
{
    const auto d = UiLayout::defaults();
    const auto json = juce::JSON::parse (R"({
        "version": 1,
        "groups": { "readouts": ["morphReadout", "qReadout"] },
        "rules": [
            { "type": "sameWidth", "elements": ["morphReadout", "qReadout"] },
            { "type": "centerY", "a": "morphReadout", "b": "morphWheel" }
        ],
        "elements": { "morphReadout": { "rect": [600, 700, 160, 70] } }
    })");
    const auto l = UiLayout::fromJson (json, d);

    // rect override still applies (runtime path unchanged)
    REQUIRE (l.sourceRectFor ("morphReadout") == juce::Rectangle<float> (600, 700, 160, 70));

    // groups parsed
    REQUIRE (l.groups.size() == 1);
    REQUIRE (l.groups[0].name == juce::String ("readouts"));
    REQUIRE (l.groups[0].elements.size() == 2);

    // rules parsed
    REQUIRE (l.rules.size() == 2);
    REQUIRE (l.rules[0].type == juce::String ("sameWidth"));
    REQUIRE (l.rules[0].elements.size() == 2);
    REQUIRE (l.rules[1].type == juce::String ("centerY"));
    REQUIRE (l.rules[1].a == juce::String ("morphReadout"));
    REQUIRE (l.rules[1].b == juce::String ("morphWheel"));
}

TEST_CASE ("Missing or malformed groups/rules leave empty collections, never throw")
{
    const auto d = UiLayout::defaults();

    const auto none = UiLayout::fromJson (juce::JSON::parse (R"({ "version": 1, "elements": {} })"), d);
    REQUIRE (none.groups.empty());
    REQUIRE (none.rules.empty());

    // rules not an array, group entry not an array, rule missing type -> skipped, no throw
    const auto junk = UiLayout::fromJson (juce::JSON::parse (R"({
        "version": 1,
        "groups": { "bad": 7, "ok": ["morphWheel"] },
        "rules": "not-an-array",
        "elements": {}
    })"), d);
    REQUIRE (junk.rules.empty());
    REQUIRE (junk.groups.size() == 1);
    REQUIRE (junk.groups[0].name == juce::String ("ok"));
}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Expected: FAIL — compile error, `UiLayout` has no member `groups`/`rules`. (`UiRule`/`UiGroup` are referenced via `l.groups[0].name` etc.)

- [ ] **Step 3: Write minimal implementation**

In `juce-shell/source/UiLayout.h`, add `#include <vector>` to the includes. Add the two structs **above** `class UiLayout` (after `struct UiElementLayout`):

```cpp
struct UiRule
{
    juce::String type;                          // sameX|sameY|sameWidth|sameHeight|centerX|centerY
    std::vector<juce::String> elements;         // sameX/Y/Width/Height
    juce::String a, b;                          // centerX/centerY
};

struct UiGroup
{
    juce::String name;
    std::vector<juce::String> elements;
};
```

Add public members to `class UiLayout` (next to `std::map<...> elements;`):

```cpp
    std::vector<UiGroup> groups;
    std::vector<UiRule> rules;
```

In `fromJson`, after the elements loop and before `return result;`, add:

```cpp
        result.groups = parseGroups (json.getProperty ("groups", juce::var()));
        result.rules  = parseRules  (json.getProperty ("rules",  juce::var()));
```

Add these private static helpers (next to `parseColour`):

```cpp
    static std::vector<juce::String> parseStringArray (const juce::var& v)
    {
        std::vector<juce::String> out;
        if (const auto* arr = v.getArray())
            for (const auto& e : *arr)
                if (e.isString())
                    out.push_back (e.toString());
        return out;
    }

    static std::vector<UiGroup> parseGroups (const juce::var& v)
    {
        std::vector<UiGroup> out;
        if (auto* obj = v.getDynamicObject())
            for (const auto& [key, value] : obj->getProperties())
            {
                auto ids = parseStringArray (value);
                if (! ids.empty())
                    out.push_back ({ key.toString(), std::move (ids) });
            }
        return out;
    }

    static std::vector<UiRule> parseRules (const juce::var& v)
    {
        std::vector<UiRule> out;
        const auto* arr = v.getArray();
        if (arr == nullptr)
            return out;

        for (const auto& entry : *arr)
        {
            if (! entry.isObject())
                continue;
            const auto type = entry.getProperty ("type", juce::var());
            if (! type.isString())
                continue;

            UiRule rule;
            rule.type = type.toString();
            rule.elements = parseStringArray (entry.getProperty ("elements", juce::var()));

            const auto a = entry.getProperty ("a", juce::var());
            const auto b = entry.getProperty ("b", juce::var());
            if (a.isString()) rule.a = a.toString();
            if (b.isString()) rule.b = b.toString();

            out.push_back (std::move (rule));
        }
        return out;
    }
```

- [ ] **Step 4: Run build + tests to verify they pass**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe "UiLayout parses optional groups and rules; runtime rect-only is untouched" "Missing or malformed groups/rules leave empty collections, never throw"`
Expected: PASS — 2 test cases, all assertions.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/UiLayout.h juce-shell/tests/UiLayoutValidateTests.cpp
git commit -m "feat(ui-layout): parse optional groups + rules (tools-only; runtime still rect+style only)"
```

---

## Task 1: Scene struct + `sceneToJson` (pure)

**Files:**
- Create: `juce-shell/source/UiLayoutValidate.h`
- Test: `juce-shell/tests/UiLayoutValidateTests.cpp`

- [ ] **Step 1: Write the failing test**

Append to `juce-shell/tests/UiLayoutValidateTests.cpp`:

```cpp
#include "UiLayoutValidate.h"

using trench::UiScene;
using trench::UiSceneElement;

namespace
{
UiScene seedScene()
{
    // Mirrors the shipped defaults mapped to editor space (360x560 over 1024x1591).
    UiScene s;
    const auto src = UiLayout::defaults();
    const auto toEditor = [] (juce::Rectangle<float> r)
    {
        return juce::Rectangle<float> { r.getX() * 360.0f / 1024.0f, r.getY() * 560.0f / 1591.0f,
                                        r.getWidth() * 360.0f / 1024.0f, r.getHeight() * 560.0f / 1591.0f };
    };
    for (const char* id : { "morphWheel", "qWheel", "typeSelector", "morphReadout", "qReadout" })
    {
        UiSceneElement e;
        e.id = id;
        e.sourceRect = src.sourceRectFor (id);
        e.editorRect = toEditor (e.sourceRect);
        e.visible = true;
        e.zIndex = 0;
        s.elements.push_back (e);
    }
    s.panelArtHash = "seedhash";
    return s;
}
}

TEST_CASE ("sceneToJson emits one object per element with both rects and metadata")
{
    const auto s = seedScene();
    const auto json = trench::sceneToJson (s);
    REQUIRE (json.isObject());
    REQUIRE ((int) json.getProperty ("sourceW", -1) == 1024);
    REQUIRE ((int) json.getProperty ("editorH", -1) == 560);
    REQUIRE (json.getProperty ("panelArtHash", juce::var()).toString() == juce::String ("seedhash"));

    const auto* arr = json.getProperty ("elements", juce::var()).getArray();
    REQUIRE (arr != nullptr);
    REQUIRE (arr->size() == 5);

    const auto& first = (*arr)[0];
    REQUIRE (first.getProperty ("id", juce::var()).toString() == juce::String ("morphWheel"));
    const auto* sr = first.getProperty ("sourceRect", juce::var()).getArray();
    REQUIRE (sr != nullptr);
    REQUIRE (sr->size() == 4);
    REQUIRE ((float) (*sr)[0] == Catch::Approx (127.0f));
    const auto* er = first.getProperty ("editorRect", juce::var()).getArray();
    REQUIRE (er != nullptr);
    REQUIRE (er->size() == 4);
    REQUIRE (first.getProperty ("visible", juce::var()).operator bool());
}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Expected: FAIL — compile error, `UiLayoutValidate.h` not found.

- [ ] **Step 3: Write minimal implementation**

Create `juce-shell/source/UiLayoutValidate.h`:

```cpp
#pragma once

#include "UiLayout.h"

#include <juce_core/juce_core.h>
#include <juce_graphics/juce_graphics.h>

#include <algorithm>
#include <cmath>
#include <vector>

namespace trench
{

struct UiSceneElement
{
    juce::String id;
    juce::Rectangle<float> sourceRect;          // 1024x1591 source space
    juce::Rectangle<float> editorRect;          // 360x560 editor space
    bool visible = true;
    int zIndex = 0;
    juce::String text;                          // current/sample text drawn, "" if none
    float fontSize = 0.0f;                      // 0 = not text-bearing / default
    juce::String textColour;                    // "aarrggbb" hex, "" if none
    bool rectValid = true;                      // false => missing/malformed rect
};

struct UiScene
{
    int sourceW = 1024;
    int sourceH = 1591;
    int editorW = 360;
    int editorH = 560;
    juce::String panelArtHash;
    std::vector<UiSceneElement> elements;
};

inline juce::var rectToVar (juce::Rectangle<float> r)
{
    juce::Array<juce::var> a;
    a.add (r.getX());
    a.add (r.getY());
    a.add (r.getWidth());
    a.add (r.getHeight());
    return a;
}

inline juce::var sceneToJson (const UiScene& scene)
{
    auto* root = new juce::DynamicObject();
    root->setProperty ("sourceW", scene.sourceW);
    root->setProperty ("sourceH", scene.sourceH);
    root->setProperty ("editorW", scene.editorW);
    root->setProperty ("editorH", scene.editorH);
    root->setProperty ("panelArtHash", scene.panelArtHash);

    juce::Array<juce::var> elements;
    for (const auto& e : scene.elements)
    {
        auto* o = new juce::DynamicObject();
        o->setProperty ("id", e.id);
        o->setProperty ("sourceRect", rectToVar (e.sourceRect));
        o->setProperty ("editorRect", rectToVar (e.editorRect));
        o->setProperty ("visible", e.visible);
        o->setProperty ("zIndex", e.zIndex);
        o->setProperty ("text", e.text);
        o->setProperty ("fontSize", e.fontSize);
        o->setProperty ("textColour", e.textColour);
        o->setProperty ("rectValid", e.rectValid);
        elements.add (juce::var (o));
    }
    root->setProperty ("elements", elements);

    return juce::var (root);
}

} // namespace trench
```

- [ ] **Step 4: Run build + test to verify it passes**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe "sceneToJson emits one object per element with both rects and metadata"`
Expected: PASS — 1 test case.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/UiLayoutValidate.h juce-shell/tests/UiLayoutValidateTests.cpp
git commit -m "feat(ui-validate): UiScene structs + sceneToJson (pure)"
```

---

## Task 2: Rule math — `ruleHolds` + violation magnitude (pure)

**Files:**
- Modify: `juce-shell/source/UiLayoutValidate.h`
- Test: `juce-shell/tests/UiLayoutValidateTests.cpp`

The single math kernel both the validator and (later) the snap engine share: does a rule hold within tolerance, and by how many source px is it off. Operates on **source-space** rects (the contract space).

- [ ] **Step 1: Write the failing tests**

Append to `juce-shell/tests/UiLayoutValidateTests.cpp`:

```cpp
using trench::UiRule;

namespace
{
UiSceneElement makeEl (const char* id, float x, float y, float w, float h)
{
    UiSceneElement e;
    e.id = id;
    e.sourceRect = { x, y, w, h };
    e.editorRect = {};
    return e;
}

UiScene sceneOf (std::vector<UiSceneElement> els)
{
    UiScene s;
    s.elements = std::move (els);
    return s;
}
}

TEST_CASE ("ruleViolation measures sameWidth / sameX in source px")
{
    const auto s = sceneOf ({ makeEl ("a", 10, 10, 100, 50),
                              makeEl ("b", 10, 90, 101, 50) });

    UiRule sameW; sameW.type = "sameWidth"; sameW.elements = { "a", "b" };
    REQUIRE (trench::ruleViolation (s, sameW) == Catch::Approx (1.0f));

    UiRule sameX; sameX.type = "sameX"; sameX.elements = { "a", "b" };
    REQUIRE (trench::ruleViolation (s, sameX) == Catch::Approx (0.0f));

    REQUIRE_FALSE (trench::ruleHolds (s, sameW, 0.5f));
    REQUIRE (trench::ruleHolds (s, sameW, 1.5f));
    REQUIRE (trench::ruleHolds (s, sameX, 0.5f));
}

TEST_CASE ("ruleViolation measures centerX / centerY between a and b")
{
    // a centerY = 10 + 50/2 = 35 ; b centerY = 80 + 40/2 = 100 ; diff = 65
    const auto s = sceneOf ({ makeEl ("a", 0, 10, 100, 50),
                              makeEl ("b", 0, 80, 100, 40) });
    UiRule cY; cY.type = "centerY"; cY.a = "a"; cY.b = "b";
    REQUIRE (trench::ruleViolation (s, cY) == Catch::Approx (65.0f));

    // a centerX = 50 ; b centerX = 50 ; diff = 0
    UiRule cX; cX.type = "centerX"; cX.a = "a"; cX.b = "b";
    REQUIRE (trench::ruleViolation (s, cX) == Catch::Approx (0.0f));
}

TEST_CASE ("ruleViolation on an unknown id or unknown type signals invalid (negative)")
{
    const auto s = sceneOf ({ makeEl ("a", 0, 0, 10, 10) });

    UiRule missing; missing.type = "sameX"; missing.elements = { "a", "ghost" };
    REQUIRE (trench::ruleViolation (s, missing) < 0.0f);

    UiRule badType; badType.type = "diagonalish"; badType.elements = { "a" };
    REQUIRE (trench::ruleViolation (s, badType) < 0.0f);

    UiRule badCenter; badCenter.type = "centerY"; badCenter.a = "a"; badCenter.b = "ghost";
    REQUIRE (trench::ruleViolation (s, badCenter) < 0.0f);
}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Expected: FAIL — compile error, `trench::ruleViolation` / `trench::ruleHolds` not declared.

- [ ] **Step 3: Write minimal implementation**

In `juce-shell/source/UiLayoutValidate.h`, before the closing `} // namespace trench`, add:

```cpp
inline const UiSceneElement* findElement (const UiScene& scene, const juce::String& id)
{
    const auto it = std::find_if (scene.elements.begin(), scene.elements.end(),
                                  [&] (const UiSceneElement& e) { return e.id == id; });
    return it != scene.elements.end() ? &(*it) : nullptr;
}

// Returns the rule's violation magnitude in source px, or a negative sentinel
// (kRuleInvalid) when the rule references an unknown id or an unknown type.
inline constexpr float kRuleInvalid = -1.0f;

inline float ruleViolation (const UiScene& scene, const UiRule& rule)
{
    const auto extentOf = [] (const UiSceneElement& e, const juce::String& type) -> float
    {
        const auto& r = e.sourceRect;
        if (type == "sameX")      return r.getX();
        if (type == "sameY")      return r.getY();
        if (type == "sameWidth")  return r.getWidth();
        if (type == "sameHeight") return r.getHeight();
        return 0.0f;
    };

    if (rule.type == "sameX" || rule.type == "sameY"
        || rule.type == "sameWidth" || rule.type == "sameHeight")
    {
        if (rule.elements.size() < 2)
            return kRuleInvalid;

        const auto* first = findElement (scene, rule.elements.front());
        if (first == nullptr)
            return kRuleInvalid;

        const float ref = extentOf (*first, rule.type);
        float worst = 0.0f;
        for (size_t i = 1; i < rule.elements.size(); ++i)
        {
            const auto* e = findElement (scene, rule.elements[i]);
            if (e == nullptr)
                return kRuleInvalid;
            worst = std::max (worst, std::abs (extentOf (*e, rule.type) - ref));
        }
        return worst;
    }

    if (rule.type == "centerX" || rule.type == "centerY")
    {
        const auto* a = findElement (scene, rule.a);
        const auto* b = findElement (scene, rule.b);
        if (a == nullptr || b == nullptr)
            return kRuleInvalid;

        const float ca = rule.type == "centerX" ? a->sourceRect.getCentreX() : a->sourceRect.getCentreY();
        const float cb = rule.type == "centerX" ? b->sourceRect.getCentreX() : b->sourceRect.getCentreY();
        return std::abs (ca - cb);
    }

    return kRuleInvalid; // unknown type
}

inline bool ruleHolds (const UiScene& scene, const UiRule& rule, float tolerance)
{
    const float v = ruleViolation (scene, rule);
    return v >= 0.0f && v <= tolerance;
}
```

- [ ] **Step 4: Run build + tests to verify they pass**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe "ruleViolation measures sameWidth / sameX in source px" "ruleViolation measures centerX / centerY between a and b" "ruleViolation on an unknown id or unknown type signals invalid (negative)"`
Expected: PASS — 3 test cases.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/UiLayoutValidate.h juce-shell/tests/UiLayoutValidateTests.cpp
git commit -m "feat(ui-validate): ruleViolation/ruleHolds source-px math kernel (pure)"
```

---

## Task 3: Validator — `validateScene` (pure)

**Files:**
- Modify: `juce-shell/source/UiLayoutValidate.h`
- Test: `juce-shell/tests/UiLayoutValidateTests.cpp`

Produces a `ValidationReport` (pass flag + list of `ValidationIssue{ code, elementId, message }`). Checks, each with its own `code`:
- `overlap` — non-ancestor visible elements whose editorRects intersect. (v1: all five wells are siblings, so any intersection between two distinct visible elements is an overlap.)
- `offCanvas` — any sourceRect outside `[0,sourceW] x [0,sourceH]`.
- `malformedRect` — `rectValid == false` or non-positive w/h.
- `unknownRuleId` — a rule references an id not in the scene.
- `textClip` — a text-bearing element whose longest expected text would not fit (estimated width; see helper).
- `artHashChanged` — current `panelArtHash` != the baseline passed in (curated panel pixels must not move).
- `ruleViolation` — a declared rule is off by more than tolerance.

- [ ] **Step 1: Write the failing tests**

Append to `juce-shell/tests/UiLayoutValidateTests.cpp`:

```cpp
using trench::ValidationReport;

namespace
{
bool hasIssue (const ValidationReport& r, const juce::String& code)
{
    for (const auto& i : r.issues)
        if (i.code == code)
            return true;
    return false;
}
}

TEST_CASE ("Seed-like scene with matching rules and art hash validates PASS")
{
    auto s = seedScene();
    std::vector<UiRule> rules;
    UiRule sw; sw.type = "sameWidth"; sw.elements = { "morphWheel", "qWheel" }; rules.push_back (sw);
    UiRule sx; sx.type = "sameX"; sx.elements = { "morphWheel", "qWheel" };     rules.push_back (sx);

    const auto report = trench::validateScene (s, rules, /*baselineArtHash*/ "seedhash", /*tolerance*/ 0.75f);
    INFO (trench::validationReportToText (report).toStdString());
    REQUIRE (report.pass);
    REQUIRE (report.issues.empty());
}

TEST_CASE ("Validator flags overlap between two siblings")
{
    auto s = sceneOf ({ makeEl ("a", 0, 0, 100, 100), makeEl ("b", 50, 50, 100, 100) });
    s.elements[0].editorRect = { 0, 0, 100, 100 };
    s.elements[1].editorRect = { 50, 50, 100, 100 };
    const auto report = trench::validateScene (s, {}, "", 0.5f);
    REQUIRE_FALSE (report.pass);
    REQUIRE (hasIssue (report, "overlap"));
}

TEST_CASE ("Validator flags off-canvas and malformed rects")
{
    auto s = sceneOf ({ makeEl ("a", -5, 0, 100, 50),       // off-canvas (x<0)
                        makeEl ("b", 0, 0, 100, 50) });
    s.elements[1].rectValid = false;                         // malformed
    const auto report = trench::validateScene (s, {}, "", 0.5f);
    REQUIRE_FALSE (report.pass);
    REQUIRE (hasIssue (report, "offCanvas"));
    REQUIRE (hasIssue (report, "malformedRect"));
}

TEST_CASE ("Validator flags unknown rule id and rule violation")
{
    auto s = sceneOf ({ makeEl ("a", 0, 0, 100, 50), makeEl ("b", 0, 200, 120, 50) });
    s.elements[0].editorRect = { 0, 0, 10, 10 };
    s.elements[1].editorRect = { 0, 200, 10, 10 };

    UiRule ghost; ghost.type = "sameX"; ghost.elements = { "a", "ghost" };
    UiRule sw;    sw.type = "sameWidth"; sw.elements = { "a", "b" };          // 100 vs 120 -> off by 20
    const auto report = trench::validateScene (s, { ghost, sw }, "", 0.5f);
    REQUIRE_FALSE (report.pass);
    REQUIRE (hasIssue (report, "unknownRuleId"));
    REQUIRE (hasIssue (report, "ruleViolation"));
}

TEST_CASE ("Validator flags curated-art-hash change")
{
    auto s = seedScene();                 // panelArtHash = "seedhash"
    const auto report = trench::validateScene (s, {}, /*baseline*/ "DIFFERENT", 0.5f);
    REQUIRE_FALSE (report.pass);
    REQUIRE (hasIssue (report, "artHashChanged"));
}

TEST_CASE ("Validator flags text clipping when text cannot fit")
{
    auto s = sceneOf ({ makeEl ("readout", 0, 0, 8, 20) }); // 8 src px wide, far too narrow
    s.elements[0].editorRect = { 0, 0, 3, 8 };
    s.elements[0].text = "100.0";
    s.elements[0].fontSize = 13.0f;
    const auto report = trench::validateScene (s, {}, "", 0.5f);
    REQUIRE_FALSE (report.pass);
    REQUIRE (hasIssue (report, "textClip"));
}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Expected: FAIL — compile error, `ValidationReport` / `validateScene` / `validationReportToText` not declared.

- [ ] **Step 3: Write minimal implementation**

In `juce-shell/source/UiLayoutValidate.h`, before the closing `} // namespace trench`, add:

```cpp
struct ValidationIssue
{
    juce::String code;          // overlap|offCanvas|malformedRect|unknownRuleId|textClip|artHashChanged|ruleViolation
    juce::String elementId;     // "" when not element-scoped
    juce::String message;
};

struct ValidationReport
{
    bool pass = true;
    std::vector<ValidationIssue> issues;
};

// Conservative text-width estimate: average glyph advance ~0.6 of font height in
// editor px. Intentionally generous (only flags clearly-too-small wells) so the
// designer is warned, never silently blocked. fontSize is in editor px.
inline float estimateTextWidth (const juce::String& text, float fontSize)
{
    return (float) text.length() * fontSize * 0.6f;
}

inline ValidationReport validateScene (const UiScene& scene,
                                       const std::vector<UiRule>& rules,
                                       const juce::String& baselineArtHash,
                                       float tolerance)
{
    ValidationReport report;
    const auto fail = [&] (const juce::String& code, const juce::String& id, const juce::String& msg)
    {
        report.pass = false;
        report.issues.push_back ({ code, id, msg });
    };

    // malformed + off-canvas
    for (const auto& e : scene.elements)
    {
        const auto& r = e.sourceRect;
        if (! e.rectValid || r.getWidth() <= 0.0f || r.getHeight() <= 0.0f
            || ! std::isfinite (r.getX()) || ! std::isfinite (r.getY())
            || ! std::isfinite (r.getWidth()) || ! std::isfinite (r.getHeight()))
        {
            fail ("malformedRect", e.id, e.id + " has a missing or malformed rect");
            continue; // a malformed rect can't be meaningfully bounds/overlap-checked
        }

        if (r.getX() < 0.0f || r.getY() < 0.0f
            || r.getRight() > (float) scene.sourceW || r.getBottom() > (float) scene.sourceH)
            fail ("offCanvas", e.id,
                  e.id + " extends outside the " + juce::String (scene.sourceW) + "x"
                       + juce::String (scene.sourceH) + " canvas");
    }

    // overlap (visible, valid, distinct siblings)
    for (size_t i = 0; i < scene.elements.size(); ++i)
        for (size_t j = i + 1; j < scene.elements.size(); ++j)
        {
            const auto& a = scene.elements[i];
            const auto& b = scene.elements[j];
            if (! a.visible || ! b.visible || ! a.rectValid || ! b.rectValid)
                continue;
            if (a.editorRect.getWidth() <= 0.0f || b.editorRect.getWidth() <= 0.0f)
                continue;
            if (a.editorRect.intersects (b.editorRect))
                fail ("overlap", a.id, a.id + " overlaps " + b.id);
        }

    // text clip
    for (const auto& e : scene.elements)
    {
        if (e.text.isEmpty() || e.fontSize <= 0.0f || ! e.rectValid)
            continue;
        if (estimateTextWidth (e.text, e.fontSize) > e.editorRect.getWidth())
            fail ("textClip", e.id, e.id + " text \"" + e.text + "\" does not fit its width");
    }

    // rules: unknown id + violation
    for (const auto& rule : rules)
    {
        const float v = ruleViolation (scene, rule);
        if (v < 0.0f)
            fail ("unknownRuleId", "", "rule " + rule.type + " references an unknown id or is malformed");
        else if (v > tolerance)
            fail ("ruleViolation", "",
                  "rule " + rule.type + " is off by " + juce::String (v, 2) + " source px");
    }

    // curated art unchanged (only checked when a baseline is supplied)
    if (baselineArtHash.isNotEmpty() && scene.panelArtHash != baselineArtHash)
        fail ("artHashChanged", "", "panel artwork hash changed (curated art must not move)");

    return report;
}

inline juce::String validationReportToText (const ValidationReport& report)
{
    juce::StringArray lines;
    lines.add (report.pass ? "PASS" : "FAIL");
    for (const auto& i : report.issues)
        lines.add ("- " + i.message);
    return lines.joinIntoString ("\n");
}

inline juce::var validationReportToJson (const ValidationReport& report)
{
    auto* root = new juce::DynamicObject();
    root->setProperty ("pass", report.pass);
    juce::Array<juce::var> issues;
    for (const auto& i : report.issues)
    {
        auto* o = new juce::DynamicObject();
        o->setProperty ("code", i.code);
        o->setProperty ("elementId", i.elementId);
        o->setProperty ("message", i.message);
        issues.add (juce::var (o));
    }
    root->setProperty ("issues", issues);
    return juce::var (root);
}
```

- [ ] **Step 4: Run build + tests to verify they pass**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe "[.]" ; juce-shell/build/Release/Tests.exe "Seed-like scene with matching rules and art hash validates PASS" "Validator flags overlap between two siblings" "Validator flags off-canvas and malformed rects" "Validator flags unknown rule id and rule violation" "Validator flags curated-art-hash change" "Validator flags text clipping when text cannot fit"`
Expected: PASS — 6 validator test cases.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/UiLayoutValidate.h juce-shell/tests/UiLayoutValidateTests.cpp
git commit -m "feat(ui-validate): validateScene (overlap/off-canvas/malformed/unknown-id/text-clip/art-hash/rule)"
```

---

## Task 4: Resolver — `resolveRule` / `resolveAllRules` (pure)

**Files:**
- Modify: `juce-shell/source/UiLayoutValidate.h`
- Test: `juce-shell/tests/UiLayoutValidateTests.cpp`

The resolver mutates **source-space** rects of a `UiLayout` to satisfy a rule, returning a new `UiLayout`. Convention (deterministic): the **first** element of a `sameX/Y/Width/Height` rule is the anchor; the rest are snapped to it. For `centerX/centerY`, `a` is moved so its center matches `b`'s center (b is the anchor). Unknown ids => no-op (the validator reports the unknown id; the resolver never invents an element). This task does NOT write a file (Task 5 wires the single write path).

- [ ] **Step 1: Write the failing tests**

Append to `juce-shell/tests/UiLayoutValidateTests.cpp`:

```cpp
TEST_CASE ("resolveRule sameWidth snaps followers to the anchor width")
{
    auto layout = UiLayout::defaults();
    layout.elements["qReadout"].sourceRect = { 602, 889, 200, 79 }; // wider than morphReadout (168)

    UiRule sw; sw.type = "sameWidth"; sw.elements = { "morphReadout", "qReadout" };
    const auto out = trench::resolveRule (layout, sw);

    REQUIRE (out.sourceRectFor ("qReadout").getWidth()
             == Catch::Approx (out.sourceRectFor ("morphReadout").getWidth()));
    // anchor untouched
    REQUIRE (out.sourceRectFor ("morphReadout").getWidth() == Catch::Approx (168.0f));
    // non-width fields of follower preserved
    REQUIRE (out.sourceRectFor ("qReadout").getX() == Catch::Approx (602.0f));
}

TEST_CASE ("resolveRule centerY moves a to match b's center; b is anchor")
{
    auto layout = UiLayout::defaults();
    UiRule cy; cy.type = "centerY"; cy.a = "morphReadout"; cy.b = "morphWheel";
    const auto out = trench::resolveRule (layout, cy);
    REQUIRE (out.sourceRectFor ("morphReadout").getCentreY()
             == Catch::Approx (out.sourceRectFor ("morphWheel").getCentreY()));
    // b untouched
    REQUIRE (out.sourceRectFor ("morphWheel") == layout.sourceRectFor ("morphWheel"));
}

TEST_CASE ("resolveRule with unknown id is a no-op")
{
    auto layout = UiLayout::defaults();
    UiRule ghost; ghost.type = "sameWidth"; ghost.elements = { "morphReadout", "ghost" };
    const auto out = trench::resolveRule (layout, ghost);
    REQUIRE (out.sourceRectFor ("morphReadout") == layout.sourceRectFor ("morphReadout"));
}

TEST_CASE ("resolveAllRules satisfies every rule (validator passes after)")
{
    auto layout = UiLayout::defaults();
    layout.elements["qReadout"].sourceRect = { 700, 889, 200, 90 };

    std::vector<UiRule> rules;
    UiRule sx; sx.type = "sameX"; sx.elements = { "morphReadout", "qReadout" };     rules.push_back (sx);
    UiRule sw; sw.type = "sameWidth"; sw.elements = { "morphReadout", "qReadout" }; rules.push_back (sw);

    const auto out = trench::resolveAllRules (layout, rules);

    // Build a minimal scene from out's source rects to re-validate the rules.
    trench::UiScene s;
    for (const char* id : { "morphReadout", "qReadout", "morphWheel" })
    {
        trench::UiSceneElement e;
        e.id = id;
        e.sourceRect = out.sourceRectFor (id);
        e.editorRect = { 0, 0, 1, 1 }; // overlap not under test here
        s.elements.push_back (e);
    }
    REQUIRE (trench::ruleHolds (s, sx, 0.001f));
    REQUIRE (trench::ruleHolds (s, sw, 0.001f));
}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Expected: FAIL — compile error, `trench::resolveRule` / `trench::resolveAllRules` not declared.

- [ ] **Step 3: Write minimal implementation**

In `juce-shell/source/UiLayoutValidate.h`, before the closing `} // namespace trench`, add:

```cpp
inline UiLayout resolveRule (const UiLayout& layout, const UiRule& rule)
{
    UiLayout out = layout;

    const auto get = [&out] (const juce::String& id) -> UiElementLayout*
    {
        const auto it = out.elements.find (id);
        return it != out.elements.end() ? &it->second : nullptr;
    };

    if (rule.type == "sameX" || rule.type == "sameY"
        || rule.type == "sameWidth" || rule.type == "sameHeight")
    {
        if (rule.elements.size() < 2)
            return out;

        auto* anchor = get (rule.elements.front());
        if (anchor == nullptr)
            return out;

        for (size_t i = 1; i < rule.elements.size(); ++i)
        {
            auto* e = get (rule.elements[i]);
            if (e == nullptr)
                return layout; // unknown follower -> no-op (don't half-apply)
            auto r = e->sourceRect;
            if (rule.type == "sameX")      r.setX (anchor->sourceRect.getX());
            if (rule.type == "sameY")      r.setY (anchor->sourceRect.getY());
            if (rule.type == "sameWidth")  r.setWidth (anchor->sourceRect.getWidth());
            if (rule.type == "sameHeight") r.setHeight (anchor->sourceRect.getHeight());
            e->sourceRect = r;
        }
        return out;
    }

    if (rule.type == "centerX" || rule.type == "centerY")
    {
        auto* a = get (rule.a);
        auto* b = get (rule.b);
        if (a == nullptr || b == nullptr)
            return layout; // no-op

        auto r = a->sourceRect;
        if (rule.type == "centerX") r.setX (b->sourceRect.getCentreX() - r.getWidth() * 0.5f);
        else                        r.setY (b->sourceRect.getCentreY() - r.getHeight() * 0.5f);
        a->sourceRect = r;
        return out;
    }

    return out; // unknown type -> no-op
}

inline UiLayout resolveAllRules (const UiLayout& layout, const std::vector<UiRule>& rules)
{
    UiLayout out = layout;
    for (const auto& rule : rules)
        out = resolveRule (out, rule);
    return out;
}
```

- [ ] **Step 4: Run build + tests to verify they pass**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe "resolveRule sameWidth snaps followers to the anchor width" "resolveRule centerY moves a to match b's center; b is anchor" "resolveRule with unknown id is a no-op" "resolveAllRules satisfies every rule (validator passes after)"`
Expected: PASS — 4 test cases.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/UiLayoutValidate.h juce-shell/tests/UiLayoutValidateTests.cpp
git commit -m "feat(ui-validate): resolveRule/resolveAllRules pure rect-snapping resolver"
```

---

## Task 5: Resolver write path — `writeResolvedLayout` (single write path)

**Files:**
- Modify: `juce-shell/source/UiLayoutValidate.h`
- Test: `juce-shell/tests/UiLayoutValidateTests.cpp`

The only function in this layer that touches the filesystem. Serializes a resolved `UiLayout` via the existing `UiLayout::toJsonString` and writes it to a target file. Tolerates write failure (returns `false`, never throws). Render NEVER calls this.

- [ ] **Step 1: Write the failing test**

Append to `juce-shell/tests/UiLayoutValidateTests.cpp`:

```cpp
TEST_CASE ("writeResolvedLayout round-trips through the file and tolerates a bad path")
{
    auto layout = UiLayout::defaults();
    layout.elements["qReadout"].sourceRect = { 700, 889, 200, 90 };
    UiRule sw; sw.type = "sameWidth"; sw.elements = { "morphReadout", "qReadout" };
    const auto resolved = trench::resolveRule (layout, sw);

    auto temp = juce::File::createTempFile (".json");
    REQUIRE (trench::writeResolvedLayout (resolved, temp));

    const auto reloaded = trench::loadUiLayoutFromFile (temp);
    REQUIRE (reloaded.sourceRectFor ("qReadout").getWidth()
             == Catch::Approx (reloaded.sourceRectFor ("morphReadout").getWidth()));
    temp.deleteFile();

    // A non-writable / nonexistent-parent path returns false, does not throw.
    juce::File bad ("Z:/definitely/not/writable/trench_x.json");
    REQUIRE_FALSE (trench::writeResolvedLayout (resolved, bad));
}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Expected: FAIL — compile error, `trench::writeResolvedLayout` not declared.

- [ ] **Step 3: Write minimal implementation**

In `juce-shell/source/UiLayoutValidate.h`, before the closing `} // namespace trench`, add:

```cpp
// The ONLY write path in the assist/verify layer. Best-effort and atomic-ish:
// writes to a sibling temp then moves it into place, so a failed write never
// leaves a partial ui_layout.json. Returns false on any failure (never throws).
inline bool writeResolvedLayout (const UiLayout& layout, const juce::File& target)
{
    if (target.getFullPathName().isEmpty())
        return false;

    const auto parent = target.getParentDirectory();
    if (! parent.exists() && ! parent.createDirectory())
        return false;

    const auto tmp = target.getSiblingFile (target.getFileNameWithoutExtension()
                                            + ".tmp" + juce::String (juce::Random::getSystemRandom().nextInt (1 << 30)));
    if (! tmp.replaceWithText (layout.toJsonString()))
        return false;

    if (! tmp.moveFileTo (target))
    {
        tmp.deleteFile();
        return false;
    }
    return true;
}
```

- [ ] **Step 4: Run build + test to verify it passes**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe "writeResolvedLayout round-trips through the file and tolerates a bad path"`
Expected: PASS — 1 test case.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/UiLayoutValidate.h juce-shell/tests/UiLayoutValidateTests.cpp
git commit -m "feat(ui-validate): writeResolvedLayout — single atomic-ish write path (tolerates failure)"
```

---

## Task 6: Semantic rect diff — `diffScenes` (pure)

**Files:**
- Modify: `juce-shell/source/UiLayoutValidate.h`
- Test: `juce-shell/tests/UiLayoutValidateTests.cpp`

Backs the "before/after = image diff note + semantic rect diff" requirement. Lists which element source rects changed and by how much (the image-diff note itself is emitted by the render harness in Task 8).

- [ ] **Step 1: Write the failing test**

Append to `juce-shell/tests/UiLayoutValidateTests.cpp`:

```cpp
TEST_CASE ("diffScenes lists only changed rects with deltas")
{
    auto before = seedScene();
    auto after = before;
    after.elements[3].sourceRect.translate (10.0f, -4.0f); // move morphReadout

    const auto diffs = trench::diffScenes (before, after, 0.5f);
    REQUIRE (diffs.size() == 1);
    REQUIRE (diffs[0].id == before.elements[3].id);
    REQUIRE (diffs[0].dx == Catch::Approx (10.0f));
    REQUIRE (diffs[0].dy == Catch::Approx (-4.0f));

    // identical scenes -> no diffs
    REQUIRE (trench::diffScenes (before, before, 0.5f).empty());
}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Expected: FAIL — compile error, `trench::diffScenes` / `trench::SceneRectDiff` not declared.

- [ ] **Step 3: Write minimal implementation**

In `juce-shell/source/UiLayoutValidate.h`, before the closing `} // namespace trench`, add:

```cpp
struct SceneRectDiff
{
    juce::String id;
    float dx = 0.0f, dy = 0.0f, dw = 0.0f, dh = 0.0f;
};

inline std::vector<SceneRectDiff> diffScenes (const UiScene& before, const UiScene& after, float epsilon)
{
    std::vector<SceneRectDiff> diffs;
    for (const auto& a : after.elements)
    {
        const auto* b = findElement (before, a.id);
        if (b == nullptr)
            continue; // element set is fixed in v1; ignore adds/removes here
        const float dx = a.sourceRect.getX() - b->sourceRect.getX();
        const float dy = a.sourceRect.getY() - b->sourceRect.getY();
        const float dw = a.sourceRect.getWidth() - b->sourceRect.getWidth();
        const float dh = a.sourceRect.getHeight() - b->sourceRect.getHeight();
        if (std::abs (dx) > epsilon || std::abs (dy) > epsilon
            || std::abs (dw) > epsilon || std::abs (dh) > epsilon)
            diffs.push_back ({ a.id, dx, dy, dw, dh });
    }
    return diffs;
}

inline juce::String diffScenesToText (const std::vector<SceneRectDiff>& diffs)
{
    if (diffs.empty())
        return "no rect changes";
    juce::StringArray lines;
    for (const auto& d : diffs)
        lines.add (d.id + ": dx=" + juce::String (d.dx, 1) + " dy=" + juce::String (d.dy, 1)
                   + " dw=" + juce::String (d.dw, 1) + " dh=" + juce::String (d.dh, 1));
    return lines.joinIntoString ("\n");
}
```

- [ ] **Step 4: Run build + test to verify it passes**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe "diffScenes lists only changed rects with deltas"`
Expected: PASS — 1 test case.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/UiLayoutValidate.h juce-shell/tests/UiLayoutValidateTests.cpp
git commit -m "feat(ui-validate): diffScenes semantic rect diff (before/after)"
```

---

## Task 7: `getUiDebugTree()` on the editor (view of truth)

**Files:**
- Modify: `juce-shell/source/PluginEditor.h`
- Modify: `juce-shell/source/PluginEditor.cpp`
- Test: `juce-shell/tests/UiLayoutValidateTests.cpp`

The scene must be sourced from the **same** `currentLayout` + well functions the painter uses, so the overlay/scene is a view of truth. The test constructs a `PluginProcessor` + `PluginEditor` (GUI-initialised, exactly as the existing silence tests do) and asserts the scene rects equal what the well functions return.

- [ ] **Step 1: Write the failing test**

Append to `juce-shell/tests/UiLayoutValidateTests.cpp`:

```cpp
#include "PluginEditor.h"
#include "PluginProcessor.h"

TEST_CASE ("getUiDebugTree mirrors the editor's well rects and canvas size")
{
    juce::ScopedJuceInitialiser_GUI gui;

    PluginProcessor processor;
    PluginEditor editor (processor);

    const auto scene = editor.getUiDebugTree();
    REQUIRE (scene.sourceW == 1024);
    REQUIRE (scene.sourceH == 1591);
    REQUIRE (scene.editorW == 360);
    REQUIRE (scene.editorH == 560);
    REQUIRE (scene.elements.size() == 5);

    const auto* morph = trench::findElement (scene, "morphWheel");
    REQUIRE (morph != nullptr);
    // source rect is whatever the live layout holds (defaults when no file edited)
    REQUIRE (morph->sourceRect.getWidth() > 0.0f);
    // editor rect equals the source rect scaled to 360x560
    REQUIRE (morph->editorRect.getX()
             == Catch::Approx (morph->sourceRect.getX() * 360.0f / 1024.0f).margin (0.01));
    REQUIRE (morph->editorRect.getWidth()
             == Catch::Approx (morph->sourceRect.getWidth() * 360.0f / 1024.0f).margin (0.01));

    // readouts carry sample text + font size for the text-clip check
    const auto* readout = trench::findElement (scene, "morphReadout");
    REQUIRE (readout != nullptr);
    REQUIRE (readout->text.isNotEmpty());
    REQUIRE (readout->fontSize > 0.0f);

    // panel art hash is populated (non-empty) so the curated-art check has a baseline
    REQUIRE (scene.panelArtHash.isNotEmpty());
}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Expected: FAIL — compile error, `PluginEditor` has no member `getUiDebugTree`.

- [ ] **Step 3: Update the header**

In `juce-shell/source/PluginEditor.h`:
- add the include after `#include "UiLayout.h"`:

```cpp
#include "UiLayoutValidate.h"
```

- in the `public:` section (after `~PluginEditor() override;`), declare:

```cpp
    // View of truth for the render/scene/validator tooling: built from the same
    // currentLayout + well functions the painter uses. Read-only.
    trench::UiScene getUiDebugTree() const;
```

- in the `private:` section (near the other small helpers), declare:

```cpp
    juce::String panelArtHash() const;
```

- [ ] **Step 4: Implement in the .cpp**

In `juce-shell/source/PluginEditor.cpp`, add near the bottom (after `reloadLayoutIfChanged()`):

```cpp
juce::String PluginEditor::panelArtHash() const
{
    // Fingerprint the curated panel bytes from BinaryData (the bytes never change
    // unless the asset is re-baked). This is the curated-art baseline the
    // validator compares against — pixels must not move.
    juce::MD5 md5 (BinaryData::df2_panel_shadow_png,
                   (size_t) BinaryData::df2_panel_shadow_pngSize);
    return md5.toHexString();
}

trench::UiScene PluginEditor::getUiDebugTree() const
{
    trench::UiScene scene;
    scene.sourceW = 1024;
    scene.sourceH = 1591;
    scene.editorW = kEditorWidth;
    scene.editorH = kEditorHeight;
    scene.panelArtHash = panelArtHash();

    struct Entry { const char* id; juce::Rectangle<float> editorRect; };
    const Entry entries[] = {
        { "morphWheel",   morphWheelWell() },
        { "qWheel",       qWheelWell() },
        { "typeSelector", typeSelectorWell() },
        { "morphReadout", morphReadoutWell() },
        { "qReadout",     qReadoutWell() },
    };

    for (const auto& entry : entries)
    {
        trench::UiSceneElement e;
        e.id = entry.id;
        e.sourceRect = currentLayout.sourceRectFor (entry.id);
        e.editorRect = entry.editorRect;
        e.rectValid = e.sourceRect.getWidth() > 0.0f && e.sourceRect.getHeight() > 0.0f;
        e.visible = true;
        e.zIndex = 0;

        // Readouts/selector carry sample text + style so the text-clip check has
        // the longest expected value to measure against.
        if (e.id == "morphReadout" || e.id == "qReadout")
        {
            e.text = "100.0"; // longest readout value (percentage, one decimal)
            e.fontSize = currentLayout.fontSizeFor (entry.id).value_or (13.0f);
            const auto colour = currentLayout.textColourFor (entry.id).value_or (juce::Colours::black);
            e.textColour = colour.toDisplayString (true);
        }
        else if (e.id == "typeSelector")
        {
            e.text = "Talking Hedz"; // a representative long body name
            e.fontSize = 12.0f;
            e.textColour = juce::Colours::black.toDisplayString (true);
        }

        scene.elements.push_back (e);
    }

    return scene;
}
```

(`BinaryData.h` is already included at the top of `PluginEditor.cpp`.)

- [ ] **Step 5: Run build + test to verify it passes**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe "getUiDebugTree mirrors the editor's well rects and canvas size"`
Expected: PASS — 1 test case.

- [ ] **Step 6: Confirm no NEW regressions**

Run: `juce-shell/build/Release/Tests.exe`
Expected: exactly one failing test — the known-red `"Default body roster is the requested two P2K references"`. No other failures.

- [ ] **Step 7: Commit**

```bash
git add juce-shell/source/PluginEditor.h juce-shell/source/PluginEditor.cpp juce-shell/tests/UiLayoutValidateTests.cpp
git commit -m "feat(editor): getUiDebugTree() scene from live wells + curated-art hash baseline"
```

---

## Task 8: Render harness `TrenchRender.cpp` (glue — no unit test)

**Files:**
- Create: `juce-shell/source/TrenchRender.cpp`

This is the offscreen render: construct processor+editor, snapshot to a `juce::Image`, draw the labelled overlay, and emit the bundle. Glue over already-tested logic — verified by build + manual inspection (Task 10), not by automated image assertion.

- [ ] **Step 1: Write the harness**

Create `juce-shell/source/TrenchRender.cpp`:

```cpp
// Offscreen render harness for the TRENCH layout loop (assist/verify).
// Constructs the real PluginEditor, snapshots it, and emits a render bundle:
//   clean.png   - the editor at true 360x560
//   overlay.png - clean.png + each element id + rect on a faint outline
//   last.png    - the previous clean.png (preserved before overwrite)
//   scene.json  - getUiDebugTree() serialized (view of truth)
//   validation.json - validateScene() over the live scene + layout rules
// READ-ONLY: never writes ui_layout.json (the resolver is a separate path).

#include "PluginEditor.h"
#include "PluginProcessor.h"
#include "UiLayout.h"
#include "UiLayoutValidate.h"

#include <juce_gui_basics/juce_gui_basics.h>

namespace
{
constexpr int kEditorWidth = 360;
constexpr int kEditorHeight = 560;

bool writePng (const juce::Image& image, const juce::File& file)
{
    file.deleteFile();
    juce::FileOutputStream stream (file);
    if (! stream.openedOk())
        return false;
    juce::PNGImageFormat png;
    return png.writeImageToStream (image, stream);
}

void drawOverlay (juce::Graphics& g, const trench::UiScene& scene)
{
    for (const auto& e : scene.elements)
    {
        const auto r = e.editorRect;
        g.setColour (juce::Colours::lime.withAlpha (0.85f));
        g.drawRect (r, 1.0f);

        // Label background for legibility against the panel art.
        const auto labelH = 11.0f;
        juce::Rectangle<float> label (r.getX(), juce::jmax (0.0f, r.getY() - labelH),
                                      juce::jmax (40.0f, (float) e.id.length() * 6.0f + 4.0f), labelH);
        g.setColour (juce::Colours::black.withAlpha (0.7f));
        g.fillRect (label);
        g.setColour (juce::Colours::lime);
        g.setFont (juce::Font (juce::FontOptions (9.0f)));
        g.drawText (e.id, label.reduced (2.0f, 0.0f), juce::Justification::centredLeft, false);
    }
}

int run (const juce::String& outDirPath)
{
    if (outDirPath.isEmpty())
    {
        std::fprintf (stderr, "TrenchRender: missing --out <dir>\n");
        return 2;
    }

    juce::File outDir (outDirPath);
    if (! outDir.createDirectory())
    {
        std::fprintf (stderr, "TrenchRender: cannot create output dir: %s\n", outDirPath.toRawUTF8());
        return 3;
    }

    PluginProcessor processor;
    PluginEditor editor (processor);
    editor.setSize (kEditorWidth, kEditorHeight);

    // Snapshot the real editor offscreen (no DAW/standalone window).
    const juce::Image clean = editor.createComponentSnapshot (
        juce::Rectangle<int> (0, 0, kEditorWidth, kEditorHeight), false, 1.0f);
    if (! clean.isValid() || clean.getWidth() != kEditorWidth || clean.getHeight() != kEditorHeight)
    {
        std::fprintf (stderr, "TrenchRender: snapshot failed or wrong size\n");
        return 4;
    }

    // Preserve the prior clean.png as last.png (before/after).
    const auto cleanFile = outDir.getChildFile ("clean.png");
    const auto lastFile = outDir.getChildFile ("last.png");
    if (cleanFile.existsAsFile())
    {
        lastFile.deleteFile();
        cleanFile.copyFileTo (lastFile);
    }

    if (! writePng (clean, cleanFile))
    {
        std::fprintf (stderr, "TrenchRender: failed to write clean.png\n");
        return 5;
    }

    // Overlay = clean + labelled rects.
    juce::Image overlay = clean.createCopy();
    {
        juce::Graphics g (overlay);
        drawOverlay (g, editor.getUiDebugTree());
    }
    if (! writePng (overlay, outDir.getChildFile ("overlay.png")))
    {
        std::fprintf (stderr, "TrenchRender: failed to write overlay.png\n");
        return 6;
    }

    // scene.json (view of truth)
    const auto scene = editor.getUiDebugTree();
    if (! outDir.getChildFile ("scene.json")
              .replaceWithText (juce::JSON::toString (trench::sceneToJson (scene))))
    {
        std::fprintf (stderr, "TrenchRender: failed to write scene.json\n");
        return 7;
    }

    // validation.json — validate the live scene against the file's rules + the
    // curated-art baseline (the live panel hash IS the baseline; an external
    // edit that changes panel bytes would change this and be caught downstream).
    const auto layout = trench::loadUiLayoutOrDefaults();
    const auto report = trench::validateScene (scene, layout.rules,
                                               scene.panelArtHash, /*tolerance*/ 1.0f);
    if (! outDir.getChildFile ("validation.json")
              .replaceWithText (juce::JSON::toString (trench::validationReportToJson (report))))
    {
        std::fprintf (stderr, "TrenchRender: failed to write validation.json\n");
        return 8;
    }

    std::printf ("TrenchRender: wrote bundle to %s\n%s\n",
                 outDir.getFullPathName().toRawUTF8(),
                 trench::validationReportToText (report).toRawUTF8());
    return 0;
}
}

int main (int argc, char* argv[])
{
    juce::ScopedJuceInitialiser_GUI gui;

    juce::String outDir;
    for (int i = 1; i < argc; ++i)
    {
        const juce::String arg (argv[i]);
        if (arg == "--out" && i + 1 < argc)
            outDir = juce::String (argv[++i]);
    }

    if (outDir.isEmpty())
        outDir = juce::File::getCurrentWorkingDirectory().getChildFile ("render_bundle").getFullPathName();

    return run (outDir);
}
```

Notes:
- `createComponentSnapshot` runs the real `paint()` path, so `clean.png` is exactly what the plugin draws. It requires `ScopedJuceInitialiser_GUI` (set up in `main`).
- The validator's curated-art baseline is `scene.panelArtHash` itself here (the live bytes). The check earns its keep when a future caller passes a *recorded* baseline; the harness wires the plumbing so that comparison is one argument away.
- The harness never writes `ui_layout.json` (read-only contract).

- [ ] **Step 2: (build verification happens in Task 9 after the CMake target exists)**

No commit yet — `TrenchRender.cpp` does not build until the target is added.

---

## Task 9: CMake target `TrenchRender` (links existing `SharedCode`)

**Render-home decision:** a dedicated console executable `TrenchRender` that links the existing `SharedCode` INTERFACE library. **Why this over the alternatives:**
- `SharedCode` already aggregates every plugin source (`PluginEditor`, `PluginProcessor`, `UiLayout.h`) + trench-core + the JUCE GUI modules and is consumed by both the plugin and the `Tests` target — so the render harness runs the *exact same* editor code with zero duplication.
- Extending `TRENCH_Standalone` with a hidden `--render` flag would mean wedging headless, message-loop-free snapshot logic into the custom standalone wrapper (`TrenchStandaloneApp.cpp`) and a real app window/`JUCEApplication` lifecycle — strictly more coupling for the same result.
- A console exe gives a clean `--out <dir>` CLI, deterministic exit codes, and no window — the lowest-friction home for a sub-second offscreen render.

**Files:**
- Modify: `juce-shell/CMakeLists.txt`

- [ ] **Step 1: Add the target**

In `juce-shell/CMakeLists.txt`, immediately **before** `include(PamplejuceIPP)` (near the bottom, after the `TRENCH_CAPTURE` block), add:

```cmake
# --- TrenchRender: offscreen layout render harness (assist/verify) ---
# Console exe that links SharedCode (the same plugin sources the VST3/Standalone
# build) so it renders the real PluginEditor. Emits the render bundle; never
# writes ui_layout.json. Build: --target TrenchRender.
juce_add_console_app(TrenchRender PRODUCT_NAME "TrenchRender")
target_sources(TrenchRender PRIVATE source/TrenchRender.cpp)
target_compile_features(TrenchRender PRIVATE cxx_std_20)
target_link_libraries(TrenchRender PRIVATE SharedCode)
```

- [ ] **Step 2: Reconfigure (new target requires a CMake configure)**

Run: `cmake -S juce-shell -B juce-shell/build`
Expected: configure succeeds, `TrenchRender` appears in the generated solution. (If the generator must be specified, match the existing build: `cmake -S juce-shell -B juce-shell/build -G "Visual Studio 17 2022"`.)

- [ ] **Step 3: Build the render target**

Run: `cmake --build juce-shell/build --config Release --target TrenchRender --parallel`
Expected: build succeeds; produces `juce-shell/build/TrenchRender_artefacts/Release/TrenchRender.exe` (JUCE console-app artefact path; if it differs, locate with `find juce-shell/build -iname "TrenchRender*.exe"`).

- [ ] **Step 4: Confirm Tests still build + only known-red fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe`
Expected: exactly one failing test — the known-red `"Default body roster is the requested two P2K references"`.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/CMakeLists.txt juce-shell/source/TrenchRender.cpp
git commit -m "feat(render): TrenchRender console target — offscreen layout render bundle"
```

---

## Task 10: MANUAL verification of the render bundle

**Files:** none (manual integration check; there is no automated image assertion in this phase).

- [ ] **Step 1: Run the render harness**

Run (locate the exe first if the path differs):
```bash
RENDER_EXE=$(find juce-shell/build -iname "TrenchRender*.exe" | head -1)
"$RENDER_EXE" --out juce-shell/build/render_out
```
Expected stdout: `TrenchRender: wrote bundle to .../render_out` followed by `PASS` (the shipped seed/default layout validates clean) and an empty issue list.

- [ ] **Step 2: Confirm the bundle exists**

Run: `ls -la juce-shell/build/render_out`
Expected: `clean.png`, `overlay.png`, `scene.json`, `validation.json` present. (`last.png` appears only on the *second* run.)

- [ ] **Step 3: MANUAL — open `clean.png`**

Open `juce-shell/build/render_out/clean.png`.
Confirm by eye:
- Image is exactly **360x560** (check the file properties / image viewer dimensions).
- It looks like the real plugin faceplate (panel art + two thumbwheels + type selector + two readouts).

- [ ] **Step 4: MANUAL — open `overlay.png`**

Open `juce-shell/build/render_out/overlay.png`.
Confirm by eye:
- A faint green outline sits on each of the five elements.
- Each outline carries a readable label with the element **id** (`morphWheel`, `qWheel`, `typeSelector`, `morphReadout`, `qReadout`).
- Labels match the elements they sit on (shared vocabulary).

- [ ] **Step 5: MANUAL — read `scene.json` + `validation.json`**

Run: `cat juce-shell/build/render_out/scene.json` and `cat juce-shell/build/render_out/validation.json`.
Confirm:
- `scene.json` has 5 elements, each with `sourceRect` + `editorRect` (4 numbers each), and `panelArtHash` is a non-empty hex string.
- `validation.json` has `"pass": true` and an empty `"issues"` array for the shipped layout.

- [ ] **Step 6: MANUAL — before/after diff**

1. Edit `~/Documents/TRENCH/ui_layout.json` (created by the plugin; or copy the seed there) and move `morphReadout`'s rect x by +30.
2. Re-run the harness: `"$RENDER_EXE" --out juce-shell/build/render_out`.
3. Confirm `last.png` now holds the previous render and `clean.png` shows the shifted readout — the pair reads as a before/after.
4. Restore the value.

Expected: the move is visible across `last.png` -> `clean.png`; if the move pushed `morphReadout` into another element, `validation.json` reports an `overlap` issue.

- [ ] **Step 7: No commit** (verification only).

---

## Self-Review

**Spec coverage** (against `docs/superpowers/specs/2026-06-19-trench-ui-layout-loop-design.md`, "Definition of done (phase 3: render + scene + validator)"):
- `getUiDebugTree()` accessor on the editor → Task 7 (sourced from the same `currentLayout` + well functions; per-element `id`, `sourceRect`, `editorRect`, `visible`, `zIndex`, `text`, `fontSize`, `textColour`, plus `rectValid`).
- Render tool emits `clean.png`, `overlay.png`, `scene.json`, `validation.json`, `last.png` → Task 8 (`createComponentSnapshot` offscreen; `last.png` preserved before overwrite).
- Validator catches overlap, off-canvas, missing/malformed rect, text clip, curated-art-hash change, rule violations, **and** unknown rule id → Task 3 (each a distinct `code`).
- Rule resolver applies a rule and writes a still-valid layout → Tasks 4 (pure resolve) + 5 (single write path via `UiLayout::toJsonString` + atomic-ish write to `uiLayoutFile`); render NEVER writes (Task 8 note).
- Snap guides in edit mode use the same geometry as the validator → Task 2 exposes `ruleViolation`/`ruleHolds` as the shared source-px kernel the phase-2 snap engine consumes (documented; the edit mode itself is out of scope here).
- Before/after diff = image diff + semantic rect diff → Task 6 (`diffScenes`/`diffScenesToText`) + Task 8/10 (`last.png` image pair).
- Tests: parse, well lookup, seed round-trip, scene output, validator, resolver, hot-reload → groups/rules parse (Task 0), scene output + getUiDebugTree well-lookup parity (Tasks 1, 7), validator (Task 3), resolver + round-trip (Tasks 4, 5); parse/well/seed/hot-reload are covered by the phase-1 plan/tests (`UiLayoutTests.cpp`) and not re-implemented here.
- Claude can patch → render → read PNG + scene.json + validation.json → state pass/fail → Tasks 8 + 10 (the harness prints the verdict; the bundle is the read surface).

**Render-home decision recorded:** dedicated `TrenchRender` console app linking the existing `SharedCode` interface (Task 9), justified vs. a Standalone `--render` flag.

**Placeholder scan:** no TBD/TODO/`...`; every code step is complete and compilable; every command has an expected output; the only intentional non-coded steps are the MANUAL image-inspection steps (Task 10) which by the format requirements are explicit manual verification, not code.

**Type consistency:** the `UiScene`/`UiSceneElement`/`UiRule`/`UiGroup`/`ValidationIssue`/`ValidationReport`/`SceneRectDiff` structs and the free functions (`sceneToJson`, `ruleViolation`, `ruleHolds`, `findElement`, `validateScene`, `validationReportToText`/`Json`, `resolveRule`, `resolveAllRules`, `writeResolvedLayout`, `diffScenes`/`diffScenesToText`) carry identical signatures across the test calls and the implementations. `UiRule`/`UiGroup` are declared once (in `UiLayout.h`, Task 0) and reused by `UiLayoutValidate.h` (which includes `UiLayout.h`) — no duplicate definitions. The five element ids (`morphWheel`, `qWheel`, `typeSelector`, `morphReadout`, `qReadout`) match `UiLayout::defaults()`, `getUiDebugTree()`, and every test. Source space is 1024x1591; editor space 360x560 — consistent with `PluginEditor.cpp` constants.

**Validation / safety (never cut):**
- All decision logic is pure and unit-tested; malformed/unknown input is handled without throwing (`parseRules`/`parseGroups` skip junk; `ruleViolation` returns a negative sentinel; `validateScene` continues past a malformed rect; `resolveRule` no-ops on unknown ids; `diffScenes` ignores adds/removes).
- The **only** write path is `writeResolvedLayout` (atomic-ish temp-then-move; returns `false` on failure, never throws) — render is strictly read-only.
- The render harness validates snapshot validity + size, returns distinct non-zero exit codes per failure, and never writes a partial PNG (`deleteFile` then stream, checked).
- Curated art is protected by an MD5 hash baseline (Task 7) surfaced as the `artHashChanged` check — panel pixels moving is a FAIL, honoring the `ui-changes-additive-keep-assets` doctrine.
- No DSP / trench-core coefficients are touched anywhere in this phase (scene = rectangles only), per the scope constraint.

**Known-red baseline honored:** every "run the suite" step states the expected single pre-existing failure (`"Default body roster is the requested two P2K references"`) and disallows any new failure.
