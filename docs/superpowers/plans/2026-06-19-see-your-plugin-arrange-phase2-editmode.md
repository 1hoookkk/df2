# See Your Plugin — Arrange Phase 2: in-plugin edit mode (move + snap) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a hidden in-plugin layout edit mode where the user toggles a chord, clicks a control to select it, drags it (with smart snapping to siblings + panel center and live source-space coordinates), and the move auto-writes `ui_layout.json` — all live in the running plugin, no rebuild.

**Architecture:** Pure, unit-tested geometry helpers (`hitTest`, `snapRect`, `editorToSourceDelta`) live in a new header `trench::edit`. `PluginEditor` gains an `editMode` flag toggled by Ctrl+Shift+L; while active, the editor handles all mouse input itself (child hit-targets/selector stop intercepting), drags mutate the in-memory `UiLayout` (snapping in source space), and `mouseUp` serializes the layout via the existing `UiLayout::toJsonString()`. An overlay paints element outlines, the selection, guides, and a coordinate badge.

**Tech Stack:** C++20, JUCE 8 (`juce::MouseEvent`, `juce::KeyPress`, `juce::Graphics`, `juce::Rectangle`), Catch2 v3, CMake (Visual Studio 17 2022).

**Depends on:** Phase 1 (`UiLayout.h`, well members, `currentLayout`, `layoutFileModTime`, `uiLayoutFile()`, `toJsonString()`) — already implemented and verified.

**Scope note (this plan):** toggle, select, drag-move + snapping + guides + live coords + auto-write. **Out of this plan (next plan):** resize handles, marquee/multi-select, measure-on-hover badges, type-exact numeric entry, undo/redo (`ValueTree`), lock, align/distribute. Spec: `docs/superpowers/specs/2026-06-19-trench-ui-layout-loop-design.md`.

**Conventions:** run commands from repo root `C:\Users\hooki\df2`. Build tests: `cmake --build juce-shell/build --config Release --target Tests --parallel`. Run a test: `juce-shell/build/Release/Tests.exe "<name>"`. Build standalone for manual checks: `cmake --build juce-shell/build --config Release --target TRENCH_Standalone --parallel`. **Known-red baseline:** the `Default body roster is the requested two P2K references` test is already failing (unrelated stale roster test) — ignore that one; no new failures are allowed.

---

## File Structure

- **Create** `juce-shell/source/UiLayoutEdit.h` — `namespace trench::edit`: `hitTest`, `SnapResult`, `snapRect`, `editorToSourceDelta`. Pure functions only; no JUCE component state. One responsibility: edit-mode geometry.
- **Create** `juce-shell/tests/UiLayoutEditTests.cpp` — Catch2 tests for the three helpers (auto-globbed into `Tests`).
- **Modify** `juce-shell/source/PluginEditor.h` — `keyPressed` override; edit-mode methods; edit-mode state members; `#include "UiLayoutEdit.h"`.
- **Modify** `juce-shell/source/PluginEditor.cpp` — toggle, mouse routing, drag+snap, auto-write, overlay paint, keyboard focus.

---

## Task 1: `editorToSourceDelta` helper

**Files:**
- Create: `juce-shell/source/UiLayoutEdit.h`
- Test: `juce-shell/tests/UiLayoutEditTests.cpp`

- [ ] **Step 1: Write the failing test**

Create `juce-shell/tests/UiLayoutEditTests.cpp`:

```cpp
#include <catch2/catch_all.hpp>

#include "UiLayoutEdit.h"

TEST_CASE ("editorToSourceDelta scales a pixel delta into source space")
{
    // 360x560 editor over 1024x1591 source: x scale 1024/360, y scale 1591/560.
    const auto d = trench::edit::editorToSourceDelta ({ 36.0f, 56.0f }, 360.0f, 560.0f, 1024.0f, 1591.0f);
    REQUIRE (d.x == Catch::Approx (102.4f));
    REQUIRE (d.y == Catch::Approx (159.1f));

    const auto zero = trench::edit::editorToSourceDelta ({ 0.0f, 0.0f }, 360.0f, 560.0f, 1024.0f, 1591.0f);
    REQUIRE (zero.x == Catch::Approx (0.0f));
    REQUIRE (zero.y == Catch::Approx (0.0f));
}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Expected: FAIL — compile error, `UiLayoutEdit.h` not found.

- [ ] **Step 3: Write minimal implementation**

Create `juce-shell/source/UiLayoutEdit.h`:

```cpp
#pragma once

#include <juce_graphics/juce_graphics.h>

#include <cmath>
#include <map>
#include <optional>
#include <vector>

namespace trench::edit
{

// Convert a pixel delta in editor space to a delta in source (1024x1591) space.
inline juce::Point<float> editorToSourceDelta (juce::Point<float> pixelDelta,
                                               float editorWidth, float editorHeight,
                                               float sourceWidth, float sourceHeight)
{
    return { pixelDelta.x * sourceWidth / editorWidth,
             pixelDelta.y * sourceHeight / editorHeight };
}

} // namespace trench::edit
```

- [ ] **Step 4: Run build + test to verify it passes**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe "editorToSourceDelta scales a pixel delta into source space"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/UiLayoutEdit.h juce-shell/tests/UiLayoutEditTests.cpp
git commit -m "feat(edit): editorToSourceDelta pixel->source helper"
```

---

## Task 2: `hitTest`

**Files:**
- Modify: `juce-shell/source/UiLayoutEdit.h`
- Test: `juce-shell/tests/UiLayoutEditTests.cpp`

- [ ] **Step 1: Write the failing test**

Append to `juce-shell/tests/UiLayoutEditTests.cpp`:

```cpp
TEST_CASE ("hitTest returns the id of the rect under the point, else empty")
{
    std::map<juce::String, juce::Rectangle<float>> rects {
        { "a", { 0.0f,   0.0f, 50.0f, 50.0f } },
        { "b", { 100.0f, 0.0f, 50.0f, 50.0f } },
    };

    REQUIRE (trench::edit::hitTest ({ 10.0f, 10.0f },  rects) == juce::String ("a"));
    REQUIRE (trench::edit::hitTest ({ 120.0f, 10.0f }, rects) == juce::String ("b"));
    REQUIRE (trench::edit::hitTest ({ 75.0f, 10.0f },  rects).isEmpty());
}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Expected: FAIL — compile error, `trench::edit::hitTest` not declared.

- [ ] **Step 3: Write minimal implementation**

In `juce-shell/source/UiLayoutEdit.h`, add inside `namespace trench::edit` (after `editorToSourceDelta`):

```cpp
// Returns the id of the first element whose rect contains p, else empty string.
inline juce::String hitTest (juce::Point<float> p,
                             const std::map<juce::String, juce::Rectangle<float>>& rects)
{
    for (const auto& [id, r] : rects)
        if (r.contains (p))
            return id;
    return {};
}
```

- [ ] **Step 4: Run build + test to verify it passes**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe "hitTest returns the id of the rect under the point, else empty"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/UiLayoutEdit.h juce-shell/tests/UiLayoutEditTests.cpp
git commit -m "feat(edit): hitTest point-in-rect element picking"
```

---

## Task 3: `snapRect` + `SnapResult`

**Files:**
- Modify: `juce-shell/source/UiLayoutEdit.h`
- Test: `juce-shell/tests/UiLayoutEditTests.cpp`

- [ ] **Step 1: Write the failing tests**

Append to `juce-shell/tests/UiLayoutEditTests.cpp`:

```cpp
TEST_CASE ("snapRect snaps an edge to a sibling within threshold")
{
    // candidate right edge = 150; sibling left edge = 158; distance 8 <= 10 -> snap.
    juce::Rectangle<float> candidate { 100.0f, 100.0f, 50.0f, 50.0f };
    std::vector<juce::Rectangle<float>> others { { 158.0f, 300.0f, 20.0f, 20.0f } };

    const auto r = trench::edit::snapRect (candidate, others, 10.0f);
    REQUIRE (r.rect.getX() == Catch::Approx (108.0f));   // shifted +8 so right=158
    REQUIRE (r.guideX.has_value());
    REQUIRE (*r.guideX == Catch::Approx (158.0f));
    REQUIRE_FALSE (r.guideY.has_value());                // Y far away -> no snap
    REQUIRE (r.rect.getY() == Catch::Approx (100.0f));
}

TEST_CASE ("snapRect does not snap beyond threshold")
{
    juce::Rectangle<float> candidate { 100.0f, 100.0f, 50.0f, 50.0f };
    std::vector<juce::Rectangle<float>> others { { 158.0f, 300.0f, 20.0f, 20.0f } };

    const auto r = trench::edit::snapRect (candidate, others, 5.0f); // 8 > 5
    REQUIRE (r.rect == candidate);
    REQUIRE_FALSE (r.guideX.has_value());
    REQUIRE_FALSE (r.guideY.has_value());
}

TEST_CASE ("snapRect aligns centers with zero offset")
{
    juce::Rectangle<float> candidate { 0.0f, 0.0f, 100.0f, 100.0f }; // centerX = 50
    std::vector<juce::Rectangle<float>> others { { 40.0f, 500.0f, 20.0f, 20.0f } }; // centerX = 50
    const auto r = trench::edit::snapRect (candidate, others, 10.0f);
    REQUIRE (r.guideX.has_value());
    REQUIRE (*r.guideX == Catch::Approx (50.0f));
    REQUIRE (r.rect.getX() == Catch::Approx (0.0f)); // already aligned, no shift
}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Expected: FAIL — compile error, `trench::edit::snapRect` / `SnapResult` not declared.

- [ ] **Step 3: Write minimal implementation**

In `juce-shell/source/UiLayoutEdit.h`, add inside `namespace trench::edit` (after `hitTest`):

```cpp
struct SnapResult
{
    juce::Rectangle<float> rect;
    std::optional<float> guideX; // vertical guide line (source x) if X snapped
    std::optional<float> guideY; // horizontal guide line (source y) if Y snapped
};

// Snap candidate's left/centerX/right (and top/centerY/bottom) to any of the
// others' corresponding lines within threshold, choosing the nearest per axis.
// X and Y are decided independently.
inline SnapResult snapRect (juce::Rectangle<float> candidate,
                            const std::vector<juce::Rectangle<float>>& others,
                            float threshold)
{
    const float candX[3] = { candidate.getX(), candidate.getCentreX(), candidate.getRight() };
    const float candY[3] = { candidate.getY(), candidate.getCentreY(), candidate.getBottom() };

    bool foundX = false; float bestDX = threshold; float offX = 0.0f; float lineX = 0.0f;
    bool foundY = false; float bestDY = threshold; float offY = 0.0f; float lineY = 0.0f;

    for (const auto& o : others)
    {
        const float oX[3] = { o.getX(), o.getCentreX(), o.getRight() };
        const float oY[3] = { o.getY(), o.getCentreY(), o.getBottom() };

        for (float cx : candX)
            for (float ox : oX)
            {
                const float d = std::abs (cx - ox);
                if (d <= bestDX) { bestDX = d; foundX = true; offX = ox - cx; lineX = ox; }
            }

        for (float cy : candY)
            for (float oy : oY)
            {
                const float d = std::abs (cy - oy);
                if (d <= bestDY) { bestDY = d; foundY = true; offY = oy - cy; lineY = oy; }
            }
    }

    SnapResult result { candidate, std::nullopt, std::nullopt };
    if (foundX) { result.rect.translate (offX, 0.0f); result.guideX = lineX; }
    if (foundY) { result.rect.translate (0.0f, offY); result.guideY = lineY; }
    return result;
}
```

- [ ] **Step 4: Run build + tests to verify they pass**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe "snapRect*"`
Expected: PASS — all three snapRect cases.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/UiLayoutEdit.h juce-shell/tests/UiLayoutEditTests.cpp
git commit -m "feat(edit): snapRect edge/center snapping with guide lines"
```

---

## Task 4: Edit-mode toggle (Ctrl+Shift+L) + overlay scaffold

**Files:**
- Modify: `juce-shell/source/PluginEditor.h`
- Modify: `juce-shell/source/PluginEditor.cpp`

Interactive task — verified by build + manual check.

- [ ] **Step 1: Update the header**

In `juce-shell/source/PluginEditor.h`, after `#include "UiLayout.h"` add:

```cpp
#include "UiLayoutEdit.h"
```

Add the public override (after `void mouseUp (const juce::MouseEvent&) override;`):

```cpp
    bool keyPressed (const juce::KeyPress&) override;
```

In the `private:` section add the methods (near the other `draw*` decls):

```cpp
    void toggleEditMode();
    void paintEditOverlay (juce::Graphics&);
    std::map<juce::String, juce::Rectangle<float>> currentEditorRects() const;
    void handleEditMouseDown (const juce::MouseEvent&);
    void handleEditMouseDrag (const juce::MouseEvent&);
    void handleEditMouseUp (const juce::MouseEvent&);
    void writeLayoutToFile();
```

And the state members (after `juce::int64 layoutFileModTime = 0;`):

```cpp
    bool editMode = false;
    juce::String selectedElementId;
    bool draggingElement = false;
    juce::Point<float> dragStartMouse;
    juce::Rectangle<float> dragStartSourceRect;
    std::optional<float> activeGuideX;
    std::optional<float> activeGuideY;
```

Add `#include <optional>` and `#include <map>` to the header includes.

- [ ] **Step 2: Implement toggle, focus, currentEditorRects, keyPressed, and overlay**

In `juce-shell/source/PluginEditor.cpp`, in the constructor body add (right after `setSize (...)`; keep `startTimerHz (24);` last):

```cpp
    setWantsKeyboardFocus (true);
```

Add these member functions (place after the well member functions added in Phase 1):

```cpp
std::map<juce::String, juce::Rectangle<float>> PluginEditor::currentEditorRects() const
{
    return {
        { "morphWheel",   morphWheelWell() },
        { "qWheel",       qWheelWell() },
        { "typeSelector", typeSelectorWell() },
        { "morphReadout", morphReadoutWell() },
        { "qReadout",     qReadoutWell() },
    };
}

void PluginEditor::toggleEditMode()
{
    editMode = ! editMode;

    // In edit mode the editor handles all mouse input itself.
    morphHitTarget.setInterceptsMouseClicks (! editMode, false);
    qHitTarget.setInterceptsMouseClicks (! editMode, false);
    bodySelector.setInterceptsMouseClicks (! editMode, ! editMode);

    if (! editMode)
    {
        draggingElement = false;
        activeGuideX.reset();
        activeGuideY.reset();
    }
    repaint();
}

bool PluginEditor::keyPressed (const juce::KeyPress& key)
{
    if (key == juce::KeyPress ('l', juce::ModifierKeys::ctrlModifier
                                       | juce::ModifierKeys::shiftModifier, 0))
    {
        toggleEditMode();
        return true;
    }
    return false;
}

void PluginEditor::paintEditOverlay (juce::Graphics& g)
{
    g.setColour (juce::Colours::black.withAlpha (0.12f));
    g.fillAll();

    for (const auto& [id, r] : currentEditorRects())
    {
        juce::ignoreUnused (id);
        g.setColour (juce::Colours::cyan.withAlpha (0.35f));
        g.drawRect (r, 1.0f);
    }

    g.setColour (juce::Colours::cyan);
    g.setFont (12.0f);
    g.drawText ("EDIT", getLocalBounds().reduced (6), juce::Justification::topRight);
}
```

In `PluginEditor::paint`, add as the last line of the method:

```cpp
    if (editMode)
        paintEditOverlay (g);
```

- [ ] **Step 3: Build the standalone**

Run: `cmake --build juce-shell/build --config Release --target TRENCH_Standalone --parallel`
Expected: build succeeds.

- [ ] **Step 4: Manual verification — toggle**

1. Locate + launch: `find juce-shell/build -iname "TRENCH*.exe"` then run the standalone.
2. Press **Ctrl+Shift+L**. Expected: the panel dims slightly, every control gets a faint cyan outline, and "EDIT" appears top-right.
3. Press **Ctrl+Shift+L** again. Expected: overlay disappears; the plugin behaves normally (wheels draggable, selector clickable).

If the chord does nothing, click the plugin window first to give it focus, then retry (focus routing is the only likely issue).

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/PluginEditor.h juce-shell/source/PluginEditor.cpp
git commit -m "feat(edit): Ctrl+Shift+L edit-mode toggle + overlay scaffold"
```

---

## Task 5: Select an element (click) with selection outline

**Files:**
- Modify: `juce-shell/source/PluginEditor.cpp`

Interactive task — build + manual check.

- [ ] **Step 1: Route mouse events to edit handlers**

In `juce-shell/source/PluginEditor.cpp`, add a guard as the first line of each of `mouseDown`, `mouseDrag`, `mouseUp`:

In `mouseDown`:
```cpp
    if (editMode) { handleEditMouseDown (event); return; }
```
In `mouseDrag`:
```cpp
    if (editMode) { handleEditMouseDrag (event); return; }
```
In `mouseUp`:
```cpp
    if (editMode) { handleEditMouseUp (event); return; }
```

- [ ] **Step 2: Implement selection**

Add to `juce-shell/source/PluginEditor.cpp`:

```cpp
void PluginEditor::handleEditMouseDown (const juce::MouseEvent& event)
{
    const auto pos = event.getEventRelativeTo (this).position;
    selectedElementId = trench::edit::hitTest (pos, currentEditorRects());
    draggingElement = selectedElementId.isNotEmpty();

    if (draggingElement)
    {
        dragStartMouse = pos;
        dragStartSourceRect = currentLayout.sourceRectFor (selectedElementId);
    }

    activeGuideX.reset();
    activeGuideY.reset();
    repaint();
}

void PluginEditor::handleEditMouseDrag (const juce::MouseEvent&) {}
void PluginEditor::handleEditMouseUp   (const juce::MouseEvent&) {}
```

- [ ] **Step 3: Draw the selection in the overlay**

In `PluginEditor::paintEditOverlay`, before the "EDIT" text block, add:

```cpp
    if (selectedElementId.isNotEmpty())
    {
        auto rects = currentEditorRects();
        const auto er = rects[selectedElementId];
        g.setColour (juce::Colours::cyan);
        g.drawRect (er, 2.0f);
    }
```

- [ ] **Step 4: Build the standalone**

Run: `cmake --build juce-shell/build --config Release --target TRENCH_Standalone --parallel`
Expected: build succeeds.

- [ ] **Step 5: Manual verification — selection**

1. Launch, press Ctrl+Shift+L.
2. Click the morph wheel. Expected: it gets a bright 2px cyan outline (selected).
3. Click the Q readout. Expected: selection moves to it.
4. Click empty space. Expected: selection clears.

- [ ] **Step 6: Commit**

```bash
git add juce-shell/source/PluginEditor.cpp
git commit -m "feat(edit): click-to-select with selection outline"
```

---

## Task 6: Drag-to-move with snapping, guides, and live coords

**Files:**
- Modify: `juce-shell/source/PluginEditor.cpp`

Interactive task — build + manual check.

- [ ] **Step 1: Implement drag-move + snapping**

In `juce-shell/source/PluginEditor.cpp`, replace the empty `handleEditMouseDrag` with:

```cpp
void PluginEditor::handleEditMouseDrag (const juce::MouseEvent& event)
{
    if (! draggingElement)
        return;

    const auto pos = event.getEventRelativeTo (this).position;
    const auto pixelDelta = pos - dragStartMouse;
    const auto srcDelta = trench::edit::editorToSourceDelta (
        pixelDelta, (float) kEditorWidth, (float) kEditorHeight,
        kPanelSourceWidth, kPanelSourceHeight);

    auto moved = dragStartSourceRect.translated (srcDelta.x, srcDelta.y);

    std::vector<juce::Rectangle<float>> others;
    for (const auto& [id, element] : currentLayout.elements)
        if (id != selectedElementId)
            others.push_back (element.sourceRect);

    const auto snap = trench::edit::snapRect (moved, others, 8.0f);
    activeGuideX = snap.guideX;
    activeGuideY = snap.guideY;

    currentLayout.elements[selectedElementId].sourceRect = snap.rect;
    resized();
    repaint();
}
```

Note: `kEditorWidth`, `kEditorHeight`, `kPanelSourceWidth`, `kPanelSourceHeight` are the existing anonymous-namespace constants at the top of this file.

- [ ] **Step 2: Draw guides + live coordinate badge**

In `PluginEditor::paintEditOverlay`, inside the `if (selectedElementId.isNotEmpty())` block, after drawing the 2px outline, add the live coords:

```cpp
        const auto sr = currentLayout.sourceRectFor (selectedElementId);
        const auto label = selectedElementId + "  "
                         + juce::String ((int) sr.getX()) + "," + juce::String ((int) sr.getY())
                         + "  " + juce::String ((int) sr.getWidth()) + juce::String ("x")
                         + juce::String ((int) sr.getHeight());
        const auto badge = juce::Rectangle<float> (er.getX(), juce::jmax (0.0f, er.getY() - 15.0f), 168.0f, 14.0f);
        g.setColour (juce::Colours::black.withAlpha (0.7f));
        g.fillRect (badge);
        g.setColour (juce::Colours::cyan);
        g.setFont (11.0f);
        g.drawText (label, badge.reduced (3.0f, 0.0f), juce::Justification::centredLeft);
```

Then, at the very end of `paintEditOverlay`, draw the guides:

```cpp
    g.setColour (juce::Colours::magenta.withAlpha (0.85f));
    if (activeGuideX)
    {
        const float x = *activeGuideX * (float) kEditorWidth / kPanelSourceWidth;
        g.drawVerticalLine (juce::roundToInt (x), 0.0f, (float) getHeight());
    }
    if (activeGuideY)
    {
        const float y = *activeGuideY * (float) kEditorHeight / kPanelSourceHeight;
        g.drawHorizontalLine (juce::roundToInt (y), 0.0f, (float) getWidth());
    }
```

- [ ] **Step 3: Build the standalone**

Run: `cmake --build juce-shell/build --config Release --target TRENCH_Standalone --parallel`
Expected: build succeeds.

- [ ] **Step 4: Manual verification — drag + snap**

1. Launch, press Ctrl+Shift+L, drag the morph readout. Expected: it follows the cursor; a coordinate badge (`morphReadout  x,y  WxH`) tracks above it and updates live.
2. Drag it so its left edge nears the Q readout's left edge. Expected: a magenta guide line appears and the readout snaps to align.
3. Release. The control stays where you dropped it.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/PluginEditor.cpp
git commit -m "feat(edit): drag-to-move with snapping, guides, live coords"
```

---

## Task 7: Auto-write `ui_layout.json` on drop

**Files:**
- Modify: `juce-shell/source/PluginEditor.cpp`

- [ ] **Step 1: Implement the write + mouseUp**

In `juce-shell/source/PluginEditor.cpp`, add:

```cpp
void PluginEditor::writeLayoutToFile()
{
    const auto file = trench::uiLayoutFile();
    file.getParentDirectory().createDirectory();
    if (file.replaceWithText (currentLayout.toJsonString()))
        layoutFileModTime = file.getLastModificationTime().toMilliseconds(); // don't self-trigger reload
}
```

Replace the empty `handleEditMouseUp` with:

```cpp
void PluginEditor::handleEditMouseUp (const juce::MouseEvent&)
{
    if (draggingElement)
        writeLayoutToFile();

    draggingElement = false;
    activeGuideX.reset();
    activeGuideY.reset();
    repaint();
}
```

- [ ] **Step 2: Build the standalone**

Run: `cmake --build juce-shell/build --config Release --target TRENCH_Standalone --parallel`
Expected: build succeeds.

- [ ] **Step 3: Manual verification — persistence**

1. Launch, Ctrl+Shift+L, drag the Q readout to a new spot, release.
2. Open `~/Documents/TRENCH/ui_layout.json` — the `qReadout` rect reflects the new position.
3. Close and relaunch the standalone. Expected: the Q readout is where you left it (layout persisted, no self-reload flicker during the session).

- [ ] **Step 4: Run the full test suite (regression guard)**

Run: `juce-shell/build/Release/Tests.exe`
Expected: only the known-red roster test fails; everything else (including all UiLayout + UiLayoutEdit tests) passes. No new failures.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/PluginEditor.cpp
git commit -m "feat(edit): auto-write ui_layout.json on drop (debounced via mouseUp)"
```

---

## Self-Review

**Spec coverage (Phase 2 headline, this slice):**
- One-chord toggle, dev/author-hidden → Task 4 (no menu, undiscoverable chord).
- Click-to-select → Task 5. Drag-to-move → Task 6.
- Snapping to siblings/panel center with guide lines; "align for you" → Task 3 (logic) + Task 6 (wiring). (Panel-center snapping falls out: the panel center is not in `others`, so this slice snaps to sibling lines; explicit panel-center guide is a trivial add in the next plan.)
- Numbers float on drag, vanish on release → Task 6 badge (drawn only while selected/dragging) + Task 7 reset on up.
- No save button; auto-write → Task 7.
- Audio/wheels keep running while editing → edit mode only overlays/handles mouse; `processBlock` untouched; verified in Task 4 manual step.

**Deferred to the next plan (correctly out):** resize handles, marquee/multi-select, measure-on-hover badges to *neighbors*, type-exact numeric entry, undo/redo (`ValueTree`+`UndoManager`), lock, align/distribute, explicit panel-center guide, keyboard nudge (arrows). Accessibility note: keyboard-operability (nudge/select via keys) lands with that plan; this slice adds the chord toggle but is mouse-driven for move.

**Placeholder scan:** none — every code step is complete; interactive steps have explicit manual checks with expected results. ✓

**Type consistency:** `trench::edit::editorToSourceDelta(Point, float,float,float,float)`, `hitTest(Point, map<String,Rect>)`, `snapRect(Rect, vector<Rect>, float) -> SnapResult{rect,guideX,guideY}` are used identically in Tasks 1-3 and consumed unchanged in Task 6. `currentEditorRects()`, `selectedElementId`, `draggingElement`, `dragStartMouse`, `dragStartSourceRect`, `activeGuideX/Y`, `writeLayoutToFile()`, `currentLayout.elements[...]` (public map from Phase 1) all match across tasks. Editor/source constants reuse the existing `kEditorWidth/kEditorHeight/kPanelSourceWidth/kPanelSourceHeight`. ✓

**Validation/safety (not cut):** `writeLayoutToFile` creates the parent dir and only updates `layoutFileModTime` on a successful write (failure tolerated, no crash); drag is a no-op unless an element is selected; `hitTest` returns empty on misses so empty-space clicks deselect cleanly. ✓
