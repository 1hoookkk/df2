# See Your Plugin — Arrange Phase 2b: full Figma-grade edit mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the in-plugin Figma-grade layout edit mode by adding the deferred capabilities on top of the move+snap slice: 8-handle resize, keyboard nudge + keyboard-operable selection, marquee + shift-click multi-select, measure-on-hover distance badges, tap-to-type numeric entry, `ValueTree`/`UndoManager`-backed undo/redo, element lock, align/distribute over a multi-selection, explicit panel-center snapping, and the spec's accessibility requirements (keyboard operability, color-is-never-the-only-signal, visible focus). The iPhone-test surface stays: drag-and-it-snaps with zero instruction; power surfaces only on reach.

**Architecture:** All new *geometry/transform* logic is added as pure free functions in `trench::edit` (in `juce-shell/source/UiLayoutEdit.h`) and unit-tested in `juce-shell/tests/UiLayoutEditTests.cpp` — `resizeFromHandle`, `handleAt`, `nudgeDelta`, `distanceToNeighbor` / `measureBadges`, `marqueeHits`, `alignRects`, `distributeRects`, and `panelCenterRects` (panel-center augmentation of the snap-target set). The *interactive wiring* in `PluginEditor` (8-handle drawing + hit, marquee rubber-band, key routing for nudge/tab/esc/undo, a `juce::ValueTree`+`juce::UndoManager` authoring model that serializes to `UiLayout`, a floating tap-to-type `juce::TextEditor`, lock-on-reach) is exercised by build + explicit **manual** verification (no screenshot capability yet). The selection becomes a **set** (`std::vector<juce::String> selection`) replacing the single `selectedElementId`.

**Tech Stack:** C++20, JUCE 8 (`juce::ValueTree`, `juce::UndoManager`, `juce::TextEditor`, `juce::MouseEvent`, `juce::KeyPress`, `juce::Graphics`, `juce::Rectangle`), Catch2 v3, CMake (Visual Studio 17 2022 generator).

**Depends on:** Phase 1 (`UiLayout.h`: `defaults`/`sourceRectFor`/`fontSizeFor`/`textColourFor`/`fromJson`/`toJsonString`, public `elements` map; `uiLayoutFile`/`loadUiLayoutOrDefaults`/`ensureUiLayoutFileExists`) and Phase 2 (`UiLayoutEdit.h`: `editorToSourceDelta`/`hitTest`/`snapRect`/`SnapResult`; `PluginEditor` edit-mode slice: `editMode` flag, Ctrl+Shift+L toggle, `currentEditorRects()`, `handleEditMouseDown/Drag/Up`, `paintEditOverlay`, `writeLayoutToFile`, `currentLayout`, `selectedElementId`, `draggingElement`, `activeGuideX/Y`; anon-namespace constants `kEditorWidth=360`, `kEditorHeight=560`, `kPanelSourceWidth=1024`, `kPanelSourceHeight=1591`; `sourceRectToEditor`). Both must be implemented and verified before this plan runs.

**Scope note (this plan):** the deferred Figma features only — resize, keyboard nudge + keyboard selection, marquee + multi-select, measure-on-hover, type-exact entry, undo/redo, lock, align/distribute, explicit panel-center snap, accessibility. **Out of scope (do not build here):** anything already in phase 1/2 (layout file, hot-reload, toggle, click-select, drag-move, sibling snap, auto-write); the render/scene/validator tool; the Inspect signal schematic; AI suggestions; adding/removing elements; restyling curated art. Spec: `docs/superpowers/specs/2026-06-19-trench-ui-layout-loop-design.md` (sections 4, 4a, 4b, accessibility, DoD).

**Conventions for every command below:** run from repo root `C:\Users\hooki\df2`. Build tests: `cmake --build juce-shell/build --config Release --target Tests --parallel`. Run one test by name: `juce-shell/build/Release/Tests.exe "<name>"`. Run a tag/wildcard set: `juce-shell/build/Release/Tests.exe "<pattern>"`. Build standalone for manual checks: `cmake --build juce-shell/build --config Release --target TRENCH_Standalone --parallel` (locate the exe with `find juce-shell/build -iname "TRENCH*.exe"`). New test `.cpp`/`source` files are auto-globbed (`CONFIGURE_DEPENDS`); no manual reconfigure. **KNOWN-RED baseline:** the test `Default body roster is the requested two P2K references` already fails for an unrelated reason — it is the only permitted failure. Any *new* failure is disallowed.

---

## File Structure

- **Modify** `juce-shell/source/UiLayoutEdit.h` — add pure free functions to `namespace trench::edit`: `Handle` enum + `handleAt`, `resizeFromHandle`, `nudgeDelta`, `distanceToNeighbor` + `measureBadges`, `marqueeHits`, `AlignMode`/`alignRects`, `distributeRects`, `panelCenterRects`. No JUCE component state — geometry only.
- **Modify** `juce-shell/tests/UiLayoutEditTests.cpp` — Catch2 tests for each new helper (auto-globbed into `Tests`).
- **Modify** `juce-shell/source/PluginEditor.h` — selection-as-set, resize/marquee/undo/lock/type-entry state, new method decls, `juce::ValueTree`/`juce::UndoManager` members, a `juce::TextEditor` member.
- **Modify** `juce-shell/source/PluginEditor.cpp` — handle drawing + hit-test, marquee rubber-band, keyboard nudge/tab/esc/undo, ValueTree authoring model + serialization to `UiLayout`, floating tap-to-type editor, lock-on-reach, align/distribute on reach, panel-center snap wiring, accessibility (focus ring, labels, shape cues).

---

## Task 1: `Handle` enum + `handleAt` (which resize handle is under a point)

**Files:**
- Modify: `juce-shell/source/UiLayoutEdit.h`
- Test: `juce-shell/tests/UiLayoutEditTests.cpp`

- [ ] **Step 1: Write the failing test**

Append to `juce-shell/tests/UiLayoutEditTests.cpp`:

```cpp
TEST_CASE ("handleAt picks the corner/edge handle under a point, else None")
{
    using trench::edit::Handle;
    const juce::Rectangle<float> r { 100.0f, 100.0f, 200.0f, 100.0f }; // x100..300, y100..200
    const float hs = 6.0f; // half-size of a handle hit box

    REQUIRE (trench::edit::handleAt ({ 100.0f, 100.0f }, r, hs) == Handle::topLeft);
    REQUIRE (trench::edit::handleAt ({ 300.0f, 100.0f }, r, hs) == Handle::topRight);
    REQUIRE (trench::edit::handleAt ({ 100.0f, 200.0f }, r, hs) == Handle::bottomLeft);
    REQUIRE (trench::edit::handleAt ({ 300.0f, 200.0f }, r, hs) == Handle::bottomRight);
    REQUIRE (trench::edit::handleAt ({ 200.0f, 100.0f }, r, hs) == Handle::top);
    REQUIRE (trench::edit::handleAt ({ 200.0f, 200.0f }, r, hs) == Handle::bottom);
    REQUIRE (trench::edit::handleAt ({ 100.0f, 150.0f }, r, hs) == Handle::left);
    REQUIRE (trench::edit::handleAt ({ 300.0f, 150.0f }, r, hs) == Handle::right);
    REQUIRE (trench::edit::handleAt ({ 200.0f, 150.0f }, r, hs) == Handle::none); // interior
    REQUIRE (trench::edit::handleAt ({ 0.0f,   0.0f },   r, hs) == Handle::none); // far away
}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Expected: FAIL — compile error, `trench::edit::Handle` / `handleAt` not declared.

- [ ] **Step 3: Write minimal implementation**

In `juce-shell/source/UiLayoutEdit.h`, add inside `namespace trench::edit` (after `snapRect`):

```cpp
enum class Handle
{
    none,
    topLeft, top, topRight,
    left,          right,
    bottomLeft, bottom, bottomRight
};

// Returns the resize handle whose hit box (half-size halfSize, centred on the
// handle point) contains p. Corners win over edges (tested first).
inline Handle handleAt (juce::Point<float> p, juce::Rectangle<float> r, float halfSize)
{
    const float l = r.getX(),  rt = r.getRight();
    const float t = r.getY(),  b  = r.getBottom();
    const float cx = r.getCentreX(), cy = r.getCentreY();

    const auto near = [halfSize] (juce::Point<float> a, float hx, float hy)
    {
        return std::abs (a.x - hx) <= halfSize && std::abs (a.y - hy) <= halfSize;
    };

    if (near (p, l,  t))  return Handle::topLeft;
    if (near (p, rt, t))  return Handle::topRight;
    if (near (p, l,  b))  return Handle::bottomLeft;
    if (near (p, rt, b))  return Handle::bottomRight;
    if (near (p, cx, t))  return Handle::top;
    if (near (p, cx, b))  return Handle::bottom;
    if (near (p, l,  cy)) return Handle::left;
    if (near (p, rt, cy)) return Handle::right;
    return Handle::none;
}
```

- [ ] **Step 4: Run build + test to verify it passes**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe "handleAt picks the corner/edge handle under a point, else None"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/UiLayoutEdit.h juce-shell/tests/UiLayoutEditTests.cpp
git commit -m "feat(edit): Handle enum + handleAt resize-handle picking"
```

---

## Task 2: `resizeFromHandle` (8-handle resize, shift=aspect, alt=from-center)

**Files:**
- Modify: `juce-shell/source/UiLayoutEdit.h`
- Test: `juce-shell/tests/UiLayoutEditTests.cpp`

- [ ] **Step 1: Write the failing tests**

Append to `juce-shell/tests/UiLayoutEditTests.cpp`:

```cpp
TEST_CASE ("resizeFromHandle drags a corner, keeping the opposite corner fixed")
{
    using trench::edit::Handle;
    const juce::Rectangle<float> start { 100.0f, 100.0f, 200.0f, 100.0f };
    // Drag bottomRight by (+20,+10): width 220, height 110, origin unchanged.
    const auto r = trench::edit::resizeFromHandle (start, Handle::bottomRight,
                                                   { 20.0f, 10.0f },
                                                   /*aspect*/ false, /*fromCenter*/ false,
                                                   /*minSize*/ 4.0f);
    REQUIRE (r.getX() == Catch::Approx (100.0f));
    REQUIRE (r.getY() == Catch::Approx (100.0f));
    REQUIRE (r.getWidth()  == Catch::Approx (220.0f));
    REQUIRE (r.getHeight() == Catch::Approx (110.0f));
}

TEST_CASE ("resizeFromHandle topLeft moves origin and shrinks toward bottomRight")
{
    using trench::edit::Handle;
    const juce::Rectangle<float> start { 100.0f, 100.0f, 200.0f, 100.0f };
    const auto r = trench::edit::resizeFromHandle (start, Handle::topLeft,
                                                   { 10.0f, 10.0f },
                                                   false, false, 4.0f);
    REQUIRE (r.getX() == Catch::Approx (110.0f));
    REQUIRE (r.getY() == Catch::Approx (110.0f));
    REQUIRE (r.getRight()  == Catch::Approx (300.0f)); // opposite edge fixed
    REQUIRE (r.getBottom() == Catch::Approx (200.0f));
}

TEST_CASE ("resizeFromHandle left edge changes only x and width")
{
    using trench::edit::Handle;
    const juce::Rectangle<float> start { 100.0f, 100.0f, 200.0f, 100.0f };
    const auto r = trench::edit::resizeFromHandle (start, Handle::left,
                                                   { 30.0f, 999.0f }, // dy ignored for a vertical edge
                                                   false, false, 4.0f);
    REQUIRE (r.getX() == Catch::Approx (130.0f));
    REQUIRE (r.getWidth() == Catch::Approx (170.0f));
    REQUIRE (r.getY() == Catch::Approx (100.0f));
    REQUIRE (r.getHeight() == Catch::Approx (100.0f));
}

TEST_CASE ("resizeFromHandle enforces a minimum size and never inverts")
{
    using trench::edit::Handle;
    const juce::Rectangle<float> start { 100.0f, 100.0f, 200.0f, 100.0f };
    // Drag bottomRight far negative: clamps to minSize, origin fixed.
    const auto r = trench::edit::resizeFromHandle (start, Handle::bottomRight,
                                                   { -500.0f, -500.0f },
                                                   false, false, 4.0f);
    REQUIRE (r.getWidth()  == Catch::Approx (4.0f));
    REQUIRE (r.getHeight() == Catch::Approx (4.0f));
    REQUIRE (r.getX() == Catch::Approx (100.0f));
    REQUIRE (r.getY() == Catch::Approx (100.0f));
}

TEST_CASE ("resizeFromHandle aspect lock keeps the start aspect ratio on a corner")
{
    using trench::edit::Handle;
    const juce::Rectangle<float> start { 0.0f, 0.0f, 200.0f, 100.0f }; // ratio 2:1
    // Drag bottomRight by (+100,+0); aspect lock should grow both to keep 2:1.
    const auto r = trench::edit::resizeFromHandle (start, Handle::bottomRight,
                                                   { 100.0f, 0.0f },
                                                   /*aspect*/ true, false, 4.0f);
    REQUIRE ((r.getWidth() / r.getHeight()) == Catch::Approx (2.0f));
    REQUIRE (r.getX() == Catch::Approx (0.0f));
    REQUIRE (r.getY() == Catch::Approx (0.0f));
}

TEST_CASE ("resizeFromHandle from-center grows symmetrically around the centre")
{
    using trench::edit::Handle;
    const juce::Rectangle<float> start { 100.0f, 100.0f, 200.0f, 100.0f }; // centre (200,150)
    const auto r = trench::edit::resizeFromHandle (start, Handle::bottomRight,
                                                   { 20.0f, 10.0f },
                                                   false, /*fromCenter*/ true, 4.0f);
    REQUIRE (r.getCentreX() == Catch::Approx (200.0f));
    REQUIRE (r.getCentreY() == Catch::Approx (150.0f));
    REQUIRE (r.getWidth()  == Catch::Approx (240.0f)); // +20 each side
    REQUIRE (r.getHeight() == Catch::Approx (120.0f)); // +10 each side
}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Expected: FAIL — compile error, `trench::edit::resizeFromHandle` not declared.

- [ ] **Step 3: Write minimal implementation**

In `juce-shell/source/UiLayoutEdit.h`, add inside `namespace trench::edit` (after `handleAt`):

```cpp
// Resize `start` by dragging `handle` with source-space delta `delta`.
//  - aspect:     preserve start's width/height ratio (corner handles only)
//  - fromCenter: keep the centre fixed; both opposing edges move symmetrically
//  - minSize:    minimum width/height; the rect never inverts
// The edge/corner opposite the dragged handle stays fixed (unless fromCenter).
inline juce::Rectangle<float> resizeFromHandle (juce::Rectangle<float> start,
                                                Handle handle,
                                                juce::Point<float> delta,
                                                bool aspect,
                                                bool fromCenter,
                                                float minSize)
{
    const bool movesLeft   = handle == Handle::topLeft || handle == Handle::left || handle == Handle::bottomLeft;
    const bool movesRight  = handle == Handle::topRight || handle == Handle::right || handle == Handle::bottomRight;
    const bool movesTop    = handle == Handle::topLeft || handle == Handle::top || handle == Handle::topRight;
    const bool movesBottom = handle == Handle::bottomLeft || handle == Handle::bottom || handle == Handle::bottomRight;
    const bool isCorner    = (movesLeft || movesRight) && (movesTop || movesBottom);

    float left = start.getX(), right = start.getRight();
    float top = start.getY(),  bottom = start.getBottom();

    float dx = delta.x;
    float dy = delta.y;

    if (aspect && isCorner)
    {
        // Drive both axes from the larger-magnitude drag, preserving start ratio.
        const float ratio = start.getHeight() > 0.0f ? start.getWidth() / start.getHeight() : 1.0f;
        // sign of the width change implied by the active horizontal handle
        const float sx = movesRight ? 1.0f : -1.0f;
        const float sy = movesBottom ? 1.0f : -1.0f;
        const float dW = sx * dx;
        const float dH = sy * dy;
        if (std::abs (dW) >= std::abs (dH * ratio))
            dy = sy * (sx * dx) / ratio; // width drives height
        else
            dx = sx * (sy * dy) * ratio; // height drives width
    }

    if (fromCenter)
    {
        if (movesLeft)   { left  += dx; right -= dx; }
        if (movesRight)  { right += dx; left  -= dx; }
        if (movesTop)    { top   += dy; bottom -= dy; }
        if (movesBottom) { bottom += dy; top   -= dy; }
    }
    else
    {
        if (movesLeft)   left   += dx;
        if (movesRight)  right  += dx;
        if (movesTop)    top    += dy;
        if (movesBottom) bottom += dy;
    }

    // Clamp to minSize without inverting: pin the fixed edge.
    if (right - left < minSize)
    {
        if (fromCenter)        { const float cx = (left + right) * 0.5f; left = cx - minSize * 0.5f; right = cx + minSize * 0.5f; }
        else if (movesLeft)    left  = right - minSize;
        else                   right = left + minSize;
    }
    if (bottom - top < minSize)
    {
        if (fromCenter)        { const float cy = (top + bottom) * 0.5f; top = cy - minSize * 0.5f; bottom = cy + minSize * 0.5f; }
        else if (movesTop)     top    = bottom - minSize;
        else                   bottom = top + minSize;
    }

    return juce::Rectangle<float>::leftTopRightBottom (left, top, right, bottom);
}
```

- [ ] **Step 4: Run build + tests to verify they pass**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe "resizeFromHandle*"`
Expected: PASS — all six resizeFromHandle cases.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/UiLayoutEdit.h juce-shell/tests/UiLayoutEditTests.cpp
git commit -m "feat(edit): resizeFromHandle 8-handle resize (aspect/from-center/min-size)"
```

---

## Task 3: `nudgeDelta` (keyboard arrow nudge in source px)

**Files:**
- Modify: `juce-shell/source/UiLayoutEdit.h`
- Test: `juce-shell/tests/UiLayoutEditTests.cpp`

- [ ] **Step 1: Write the failing test**

Append to `juce-shell/tests/UiLayoutEditTests.cpp`:

```cpp
TEST_CASE ("nudgeDelta returns 1 source px per arrow, 10 with shift")
{
    using trench::edit::nudgeDelta;
    REQUIRE (nudgeDelta (-1,  0, false) == juce::Point<float> (-1.0f, 0.0f));   // left
    REQUIRE (nudgeDelta ( 1,  0, false) == juce::Point<float> ( 1.0f, 0.0f));   // right
    REQUIRE (nudgeDelta ( 0, -1, false) == juce::Point<float> ( 0.0f, -1.0f));  // up
    REQUIRE (nudgeDelta ( 0,  1, false) == juce::Point<float> ( 0.0f, 1.0f));   // down
    REQUIRE (nudgeDelta (-1,  0, true)  == juce::Point<float> (-10.0f, 0.0f));  // shift+left
    REQUIRE (nudgeDelta ( 0,  1, true)  == juce::Point<float> ( 0.0f, 10.0f));  // shift+down
}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Expected: FAIL — compile error, `trench::edit::nudgeDelta` not declared.

- [ ] **Step 3: Write minimal implementation**

In `juce-shell/source/UiLayoutEdit.h`, add inside `namespace trench::edit`:

```cpp
// Keyboard nudge in source space. dirX/dirY are -1/0/+1; coarse = shift (x10).
inline juce::Point<float> nudgeDelta (int dirX, int dirY, bool coarse)
{
    const float step = coarse ? 10.0f : 1.0f;
    return { (float) dirX * step, (float) dirY * step };
}
```

- [ ] **Step 4: Run build + test to verify it passes**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe "nudgeDelta returns 1 source px per arrow, 10 with shift"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/UiLayoutEdit.h juce-shell/tests/UiLayoutEditTests.cpp
git commit -m "feat(edit): nudgeDelta keyboard arrow nudge (1px / shift 10px)"
```

---

## Task 4: `panelCenterRects` (augment snap targets with panel center lines)

**Files:**
- Modify: `juce-shell/source/UiLayoutEdit.h`
- Test: `juce-shell/tests/UiLayoutEditTests.cpp`

- [ ] **Step 1: Write the failing test**

Append to `juce-shell/tests/UiLayoutEditTests.cpp`:

```cpp
TEST_CASE ("panelCenterRects adds zero-size rects on the panel centre lines")
{
    // For a 1024x1591 source panel, centre is (512, 795.5).
    const auto extra = trench::edit::panelCenterRects (1024.0f, 1591.0f);
    REQUIRE (extra.size() == 2);
    // A vertical centre line: a degenerate rect whose centreX == 512.
    REQUIRE (extra[0].getCentreX() == Catch::Approx (512.0f));
    // A horizontal centre line: a degenerate rect whose centreY == 795.5.
    REQUIRE (extra[1].getCentreY() == Catch::Approx (795.5f));
}

TEST_CASE ("snapRect can snap to a panel-center pseudo-rect")
{
    // candidate centreX = 500; panel vertical centre at 512; distance 12 > 10 won't snap,
    // but 503 -> centreX 503, distance 9 <= 10 snaps to 512.
    juce::Rectangle<float> candidate { 0.0f, 0.0f, 6.0f, 6.0f }; // centreX 3
    auto others = trench::edit::panelCenterRects (1024.0f, 1591.0f); // vertical centre 512
    // Move candidate near the centre line so the test is meaningful.
    candidate.setX (512.0f - 3.0f - 4.0f); // centreX = 505, distance 7 <= 10
    const auto r = trench::edit::snapRect (candidate, others, 10.0f);
    REQUIRE (r.guideX.has_value());
    REQUIRE (*r.guideX == Catch::Approx (512.0f));
    REQUIRE (r.rect.getCentreX() == Catch::Approx (512.0f));
}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Expected: FAIL — compile error, `trench::edit::panelCenterRects` not declared.

- [ ] **Step 3: Write minimal implementation**

In `juce-shell/source/UiLayoutEdit.h`, add inside `namespace trench::edit`:

```cpp
// Degenerate "rects" sitting on the panel centre lines, so snapRect can snap a
// dragged element to the panel's vertical/horizontal centre. The first rect's
// left/centreX/right all equal the panel centre X; the second's top/centreY/
// bottom all equal the panel centre Y. Returned in {vertical, horizontal} order.
inline std::vector<juce::Rectangle<float>> panelCenterRects (float panelWidth, float panelHeight)
{
    const float cx = panelWidth  * 0.5f;
    const float cy = panelHeight * 0.5f;
    return {
        juce::Rectangle<float> { cx, 0.0f, 0.0f, panelHeight }, // vertical centre line
        juce::Rectangle<float> { 0.0f, cy, panelWidth, 0.0f },  // horizontal centre line
    };
}
```

- [ ] **Step 4: Run build + tests to verify they pass**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe "*panel-center*" "panelCenterRects*"`
Expected: PASS — both cases. (`snapRect` already snaps to any rect's left/centreX/right and top/centreY/bottom, so the degenerate rects work without changing `snapRect`.)

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/UiLayoutEdit.h juce-shell/tests/UiLayoutEditTests.cpp
git commit -m "feat(edit): panelCenterRects so snapRect snaps to panel centre lines"
```

---

## Task 5: `distanceToNeighbor` + `measureBadges` (measure-on-hover distances)

**Files:**
- Modify: `juce-shell/source/UiLayoutEdit.h`
- Test: `juce-shell/tests/UiLayoutEditTests.cpp`

- [ ] **Step 1: Write the failing tests**

Append to `juce-shell/tests/UiLayoutEditTests.cpp`:

```cpp
TEST_CASE ("distanceToNeighbor measures the source-space gaps to the panel edges")
{
    // Panel 1024x1591. Element at x=100,y=200,w=300,h=100 -> right gap 624, bottom gap 1291.
    const juce::Rectangle<float> r { 100.0f, 200.0f, 300.0f, 100.0f };
    const auto m = trench::edit::distanceToNeighbor (r, {}, 1024.0f, 1591.0f);
    REQUIRE (m.left   == Catch::Approx (100.0f));
    REQUIRE (m.top    == Catch::Approx (200.0f));
    REQUIRE (m.right  == Catch::Approx (1024.0f - 400.0f)); // 624
    REQUIRE (m.bottom == Catch::Approx (1591.0f - 300.0f)); // 1291
}

TEST_CASE ("distanceToNeighbor prefers the nearest sibling over the panel edge")
{
    const juce::Rectangle<float> r { 100.0f, 200.0f, 100.0f, 100.0f }; // right edge 200
    std::vector<juce::Rectangle<float>> others {
        { 260.0f, 200.0f, 50.0f, 50.0f }, // 60px to the right of r's right edge
    };
    const auto m = trench::edit::distanceToNeighbor (r, others, 1024.0f, 1591.0f);
    REQUIRE (m.right == Catch::Approx (60.0f)); // sibling closer than the 824px panel gap
}

TEST_CASE ("measureBadges emits a badge per finite gap")
{
    const juce::Rectangle<float> r { 100.0f, 200.0f, 100.0f, 100.0f };
    const auto badges = trench::edit::measureBadges (r, {}, 1024.0f, 1591.0f);
    // Four sides, each a finite gap -> four badges.
    REQUIRE (badges.size() == 4);
    // Each badge carries a non-empty text and an anchor point inside the panel.
    for (const auto& b : badges)
    {
        REQUIRE (b.text.isNotEmpty());
        REQUIRE (b.anchor.x >= 0.0f);
        REQUIRE (b.anchor.y >= 0.0f);
    }
}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Expected: FAIL — compile error, `trench::edit::distanceToNeighbor` / `measureBadges` not declared.

- [ ] **Step 3: Write minimal implementation**

In `juce-shell/source/UiLayoutEdit.h`, add inside `namespace trench::edit`:

```cpp
struct Measurements
{
    float left = 0.0f, top = 0.0f, right = 0.0f, bottom = 0.0f; // source-space gaps
};

// Source-space gap from each side of `r` to the nearest blocker on that side:
// either an overlapping-on-the-perpendicular-axis sibling, or the panel edge.
inline Measurements distanceToNeighbor (juce::Rectangle<float> r,
                                        const std::vector<juce::Rectangle<float>>& others,
                                        float panelWidth, float panelHeight)
{
    Measurements m;
    m.left   = r.getX();
    m.top    = r.getY();
    m.right  = panelWidth  - r.getRight();
    m.bottom = panelHeight - r.getBottom();

    for (const auto& o : others)
    {
        const bool overlapY = o.getBottom() > r.getY() && o.getY() < r.getBottom();
        const bool overlapX = o.getRight()  > r.getX() && o.getX() < r.getRight();

        if (overlapY)
        {
            if (o.getRight() <= r.getX()) m.left  = juce::jmin (m.left,  r.getX() - o.getRight());
            if (o.getX() >= r.getRight()) m.right = juce::jmin (m.right, o.getX() - r.getRight());
        }
        if (overlapX)
        {
            if (o.getBottom() <= r.getY()) m.top    = juce::jmin (m.top,    r.getY() - o.getBottom());
            if (o.getY() >= r.getBottom()) m.bottom = juce::jmin (m.bottom, o.getY() - r.getBottom());
        }
    }
    return m;
}

struct MeasureBadge
{
    juce::String text;            // e.g. "624"
    juce::Point<float> anchor;    // source-space point to draw the badge near
};

// One badge per side, anchored at the midpoint of the gap on that side.
inline std::vector<MeasureBadge> measureBadges (juce::Rectangle<float> r,
                                                const std::vector<juce::Rectangle<float>>& others,
                                                float panelWidth, float panelHeight)
{
    const auto m = distanceToNeighbor (r, others, panelWidth, panelHeight);
    const auto px = [] (float v) { return juce::String (juce::roundToInt (v)); };

    std::vector<MeasureBadge> badges;
    badges.push_back ({ px (m.left),   { r.getX() - m.left * 0.5f,        r.getCentreY() } });
    badges.push_back ({ px (m.right),  { r.getRight() + m.right * 0.5f,   r.getCentreY() } });
    badges.push_back ({ px (m.top),    { r.getCentreX(),                  r.getY() - m.top * 0.5f } });
    badges.push_back ({ px (m.bottom), { r.getCentreX(),                  r.getBottom() + m.bottom * 0.5f } });
    return badges;
}
```

- [ ] **Step 4: Run build + tests to verify they pass**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe "distanceToNeighbor*" "measureBadges*"`
Expected: PASS — all three cases.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/UiLayoutEdit.h juce-shell/tests/UiLayoutEditTests.cpp
git commit -m "feat(edit): distanceToNeighbor + measureBadges (measure-on-hover distances)"
```

---

## Task 6: `marqueeHits` (marquee-drag selection)

**Files:**
- Modify: `juce-shell/source/UiLayoutEdit.h`
- Test: `juce-shell/tests/UiLayoutEditTests.cpp`

- [ ] **Step 1: Write the failing tests**

Append to `juce-shell/tests/UiLayoutEditTests.cpp`:

```cpp
TEST_CASE ("marqueeHits returns ids of rects intersecting the marquee")
{
    std::map<juce::String, juce::Rectangle<float>> rects {
        { "a", {   0.0f,   0.0f, 50.0f, 50.0f } },
        { "b", { 100.0f,   0.0f, 50.0f, 50.0f } },
        { "c", { 100.0f, 100.0f, 50.0f, 50.0f } },
    };
    // Marquee covering a and b but not c.
    const auto hits = trench::edit::marqueeHits ({ -10.0f, -10.0f, 170.0f, 70.0f }, rects);
    REQUIRE (hits.size() == 2);
    REQUIRE (std::find (hits.begin(), hits.end(), juce::String ("a")) != hits.end());
    REQUIRE (std::find (hits.begin(), hits.end(), juce::String ("b")) != hits.end());
    REQUIRE (std::find (hits.begin(), hits.end(), juce::String ("c")) == hits.end());
}

TEST_CASE ("marqueeHits is empty when the marquee touches nothing")
{
    std::map<juce::String, juce::Rectangle<float>> rects {
        { "a", { 0.0f, 0.0f, 50.0f, 50.0f } },
    };
    const auto hits = trench::edit::marqueeHits ({ 500.0f, 500.0f, 10.0f, 10.0f }, rects);
    REQUIRE (hits.empty());
}
```

`<algorithm>` must be included for `std::find`. The test file should `#include <algorithm>` near the top (add it if not present).

- [ ] **Step 2: Run build to verify it fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Expected: FAIL — compile error, `trench::edit::marqueeHits` not declared.

- [ ] **Step 3: Write minimal implementation**

In `juce-shell/source/UiLayoutEdit.h`, add inside `namespace trench::edit`:

```cpp
// Ids of every element whose rect intersects the marquee rectangle.
inline std::vector<juce::String> marqueeHits (juce::Rectangle<float> marquee,
                                              const std::map<juce::String, juce::Rectangle<float>>& rects)
{
    std::vector<juce::String> hits;
    for (const auto& [id, r] : rects)
        if (marquee.intersects (r))
            hits.push_back (id);
    return hits;
}
```

- [ ] **Step 4: Run build + tests to verify they pass**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe "marqueeHits*"`
Expected: PASS — both cases.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/UiLayoutEdit.h juce-shell/tests/UiLayoutEditTests.cpp
git commit -m "feat(edit): marqueeHits rubber-band selection geometry"
```

---

## Task 7: `alignRects` + `distributeRects` (align/distribute over a set)

**Files:**
- Modify: `juce-shell/source/UiLayoutEdit.h`
- Test: `juce-shell/tests/UiLayoutEditTests.cpp`

These map to the spec's `rules` vocabulary: `AlignMode::sameX` ≙ `sameX`, `sameWidth` ≙ `sameWidth`, `centerY` ≙ `centerY`, etc. The functions operate on a set of rects (multi-selection) and return the transformed set in input order.

- [ ] **Step 1: Write the failing tests**

Append to `juce-shell/tests/UiLayoutEditTests.cpp`:

```cpp
TEST_CASE ("alignRects sameX moves every rect to the leftmost x")
{
    using trench::edit::AlignMode;
    std::vector<juce::Rectangle<float>> rs {
        { 100.0f, 0.0f, 50.0f, 50.0f },
        {  30.0f, 200.0f, 60.0f, 40.0f },
        { 200.0f, 400.0f, 20.0f, 20.0f },
    };
    const auto out = trench::edit::alignRects (rs, AlignMode::sameX);
    REQUIRE (out[0].getX() == Catch::Approx (30.0f));
    REQUIRE (out[1].getX() == Catch::Approx (30.0f));
    REQUIRE (out[2].getX() == Catch::Approx (30.0f));
    // y/size untouched
    REQUIRE (out[2].getY() == Catch::Approx (400.0f));
    REQUIRE (out[0].getWidth() == Catch::Approx (50.0f));
}

TEST_CASE ("alignRects sameWidth sets every width to the first rect's width")
{
    using trench::edit::AlignMode;
    std::vector<juce::Rectangle<float>> rs {
        { 0.0f, 0.0f, 100.0f, 50.0f },
        { 0.0f, 0.0f,  60.0f, 50.0f },
    };
    const auto out = trench::edit::alignRects (rs, AlignMode::sameWidth);
    REQUIRE (out[0].getWidth() == Catch::Approx (100.0f));
    REQUIRE (out[1].getWidth() == Catch::Approx (100.0f));
    REQUIRE (out[1].getX() == Catch::Approx (0.0f)); // x preserved
}

TEST_CASE ("alignRects centerX aligns centres to the mean centre")
{
    using trench::edit::AlignMode;
    std::vector<juce::Rectangle<float>> rs {
        {   0.0f, 0.0f, 100.0f, 10.0f }, // centreX 50
        { 100.0f, 0.0f, 100.0f, 10.0f }, // centreX 150
    };
    const auto out = trench::edit::alignRects (rs, AlignMode::centerX);
    REQUIRE (out[0].getCentreX() == Catch::Approx (100.0f)); // mean of 50,150
    REQUIRE (out[1].getCentreX() == Catch::Approx (100.0f));
}

TEST_CASE ("distributeRects evens horizontal gaps between three rects")
{
    std::vector<juce::Rectangle<float>> rs {
        {   0.0f, 0.0f, 20.0f, 10.0f }, // left fixed
        {  30.0f, 0.0f, 20.0f, 10.0f }, // middle moves
        { 200.0f, 0.0f, 20.0f, 10.0f }, // right fixed
    };
    const auto out = trench::edit::distributeRects (rs, /*horizontal*/ true);
    // Outer rects stay; the gap between successive rects becomes equal.
    REQUIRE (out[0].getX() == Catch::Approx (0.0f));
    REQUIRE (out[2].getX() == Catch::Approx (200.0f));
    const float gap0 = out[1].getX() - out[0].getRight();
    const float gap1 = out[2].getX() - out[1].getRight();
    REQUIRE (gap0 == Catch::Approx (gap1));
}

TEST_CASE ("distributeRects is a no-op for fewer than three rects")
{
    std::vector<juce::Rectangle<float>> rs {
        { 0.0f, 0.0f, 20.0f, 10.0f },
        { 50.0f, 0.0f, 20.0f, 10.0f },
    };
    const auto out = trench::edit::distributeRects (rs, true);
    REQUIRE (out == rs);
}
```

- [ ] **Step 2: Run build to verify it fails**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Expected: FAIL — compile error, `trench::edit::AlignMode` / `alignRects` / `distributeRects` not declared.

- [ ] **Step 3: Write minimal implementation**

In `juce-shell/source/UiLayoutEdit.h`, add inside `namespace trench::edit`:

```cpp
enum class AlignMode
{
    sameX, sameY, sameWidth, sameHeight, centerX, centerY
};

// Apply an alignment over a set of rects. sameX/sameY/sameWidth/sameHeight take
// their value from the leftmost/topmost (sameX/sameY) or the first rect (sizes);
// centerX/centerY align centres to the mean centre. Returns rects in input order.
inline std::vector<juce::Rectangle<float>> alignRects (std::vector<juce::Rectangle<float>> rs,
                                                       AlignMode mode)
{
    if (rs.size() < 2)
        return rs;

    switch (mode)
    {
        case AlignMode::sameX:
        {
            float minX = rs.front().getX();
            for (const auto& r : rs) minX = juce::jmin (minX, r.getX());
            for (auto& r : rs) r.setX (minX);
            break;
        }
        case AlignMode::sameY:
        {
            float minY = rs.front().getY();
            for (const auto& r : rs) minY = juce::jmin (minY, r.getY());
            for (auto& r : rs) r.setY (minY);
            break;
        }
        case AlignMode::sameWidth:
        {
            const float w = rs.front().getWidth();
            for (auto& r : rs) r.setWidth (w);
            break;
        }
        case AlignMode::sameHeight:
        {
            const float h = rs.front().getHeight();
            for (auto& r : rs) r.setHeight (h);
            break;
        }
        case AlignMode::centerX:
        {
            float sum = 0.0f;
            for (const auto& r : rs) sum += r.getCentreX();
            const float mean = sum / (float) rs.size();
            for (auto& r : rs) r.setX (mean - r.getWidth() * 0.5f);
            break;
        }
        case AlignMode::centerY:
        {
            float sum = 0.0f;
            for (const auto& r : rs) sum += r.getCentreY();
            const float mean = sum / (float) rs.size();
            for (auto& r : rs) r.setY (mean - r.getHeight() * 0.5f);
            break;
        }
    }
    return rs;
}

// Even the gaps between successive rects along one axis. Outer rects (by leading
// edge) stay fixed; interior rects are repositioned for equal gaps. <3 = no-op.
inline std::vector<juce::Rectangle<float>> distributeRects (std::vector<juce::Rectangle<float>> rs,
                                                            bool horizontal)
{
    if (rs.size() < 3)
        return rs;

    // Index order sorted by leading edge along the axis.
    std::vector<size_t> order (rs.size());
    for (size_t i = 0; i < rs.size(); ++i) order[i] = i;
    std::sort (order.begin(), order.end(), [&] (size_t a, size_t b)
    {
        return horizontal ? rs[a].getX() < rs[b].getX() : rs[a].getY() < rs[b].getY();
    });

    float extent = 0.0f; // total size of the inner+outer rects along the axis
    for (auto i : order) extent += horizontal ? rs[i].getWidth() : rs[i].getHeight();

    const auto& first = rs[order.front()];
    const auto& last  = rs[order.back()];
    const float span  = horizontal ? (last.getRight() - first.getX())
                                   : (last.getBottom() - first.getY());
    const float gap = (span - extent) / (float) (rs.size() - 1);

    float cursor = horizontal ? first.getRight() : first.getBottom();
    for (size_t k = 1; k + 1 < order.size(); ++k)
    {
        const size_t idx = order[k];
        cursor += gap;
        if (horizontal) { rs[idx].setX (cursor); cursor += rs[idx].getWidth(); }
        else            { rs[idx].setY (cursor); cursor += rs[idx].getHeight(); }
    }
    return rs;
}
```

`<algorithm>` is needed for `std::sort`/`std::find`; add `#include <algorithm>` to `UiLayoutEdit.h`'s includes if not already present.

- [ ] **Step 4: Run build + tests to verify they pass**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe "alignRects*" "distributeRects*"`
Expected: PASS — all five cases.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/UiLayoutEdit.h juce-shell/tests/UiLayoutEditTests.cpp
git commit -m "feat(edit): alignRects + distributeRects over a multi-selection"
```

---

## Task 8: Selection-as-set + ValueTree/UndoManager authoring model (state only)

**Files:**
- Modify: `juce-shell/source/PluginEditor.h`
- Modify: `juce-shell/source/PluginEditor.cpp`

This task replaces the single `selectedElementId` with a selection **set** and introduces the `juce::ValueTree`+`juce::UndoManager` authoring model that all subsequent mutations route through. Verified by build + the full test suite still passing (no behavior change yet for a single selection).

- [ ] **Step 1: Update the header**

In `juce-shell/source/PluginEditor.h`:

Add to the includes (after `#include "UiLayoutEdit.h"` if present, else after `#include "UiLayout.h"`):

```cpp
#include <juce_data_structures/juce_data_structures.h>
#include <vector>
```

Replace the member `juce::String selectedElementId;` with:

```cpp
    std::vector<juce::String> selection;          // multi-selection (was selectedElementId)
```

Add these members after `std::optional<float> activeGuideY;`:

```cpp
    // Authoring model: the layout lives in a ValueTree under an UndoManager so
    // every mutation is undoable. It is the source of truth during edit mode and
    // is serialized into currentLayout/ui_layout.json after each commit.
    juce::UndoManager undoManager;
    juce::ValueTree layoutTree { "layout" };
    bool transactionOpen = false;                 // a drag/resize transaction is in flight

    // Resize state
    trench::edit::Handle activeHandle = trench::edit::Handle::none;
    juce::Rectangle<float> resizeStartSourceRect;

    // Marquee state
    bool marqueeActive = false;
    juce::Point<float> marqueeStart;
    juce::Rectangle<float> marqueeRect;           // editor-space

    // Lock + type-entry + focus
    std::set<juce::String> lockedElements;
    juce::String keyboardFocusId;                 // element with keyboard focus (tab target)
    std::unique_ptr<juce::TextEditor> valueEditor; // floating tap-to-type editor
    juce::String valueEditorElementId;
    int valueEditorField = -1;                     // 0=x 1=y 2=w 3=h
```

Add `#include <set>` to the header includes.

Add these private method declarations (near the existing edit-mode decls):

```cpp
    void syncTreeFromLayout();                          // currentLayout -> layoutTree
    void syncLayoutFromTree();                          // layoutTree -> currentLayout (+ resized/repaint)
    void beginEditTransaction (const juce::String& name);
    void setElementRect (const juce::String& id, juce::Rectangle<float> sourceRect, bool asTransaction);
    void commitEditTransaction();
    bool isLocked (const juce::String& id) const;
    void selectOnly (const juce::String& id);
    void toggleInSelection (const juce::String& id);
    bool isSelected (const juce::String& id) const;
    std::vector<juce::Rectangle<float>> otherSourceRects (const juce::String& excludeId) const;
    void openValueEditor (const juce::String& id, int field, juce::Rectangle<float> editorAnchor);
    void closeValueEditor (bool commit);
    void nudgeSelection (int dirX, int dirY, bool coarse);
    void cycleKeyboardFocus (bool backwards);
    void alignSelection (trench::edit::AlignMode mode);
    void distributeSelection (bool horizontal);
    void toggleLockOnSelection();
```

- [ ] **Step 2: Implement the ValueTree bridge + selection helpers**

In `juce-shell/source/PluginEditor.cpp`, add these members (after the existing `writeLayoutToFile()` definition). The ValueTree mirrors `currentLayout.elements`: one child node `element` per id with `x`/`y`/`w`/`h` properties.

```cpp
void PluginEditor::syncTreeFromLayout()
{
    layoutTree = juce::ValueTree ("layout");
    for (const auto& [id, element] : currentLayout.elements)
    {
        juce::ValueTree node ("element");
        node.setProperty ("id", id, nullptr);
        node.setProperty ("x", element.sourceRect.getX(), nullptr);
        node.setProperty ("y", element.sourceRect.getY(), nullptr);
        node.setProperty ("w", element.sourceRect.getWidth(), nullptr);
        node.setProperty ("h", element.sourceRect.getHeight(), nullptr);
        layoutTree.appendChild (node, nullptr);
    }
}

void PluginEditor::syncLayoutFromTree()
{
    for (int i = 0; i < layoutTree.getNumChildren(); ++i)
    {
        const auto node = layoutTree.getChild (i);
        const juce::String id = node.getProperty ("id").toString();
        const auto it = currentLayout.elements.find (id);
        if (it == currentLayout.elements.end())
            continue;

        it->second.sourceRect = juce::Rectangle<float> (
            (float) node.getProperty ("x"), (float) node.getProperty ("y"),
            (float) node.getProperty ("w"), (float) node.getProperty ("h"));
    }
    resized();
    repaint();
}

void PluginEditor::beginEditTransaction (const juce::String& name)
{
    undoManager.beginNewTransaction (name);
    transactionOpen = true;
}

void PluginEditor::setElementRect (const juce::String& id, juce::Rectangle<float> sourceRect, bool asTransaction)
{
    auto node = layoutTree.getChildWithProperty ("id", id);
    if (! node.isValid())
        return;

    auto* um = asTransaction ? &undoManager : nullptr;
    node.setProperty ("x", sourceRect.getX(), um);
    node.setProperty ("y", sourceRect.getY(), um);
    node.setProperty ("w", sourceRect.getWidth(), um);
    node.setProperty ("h", sourceRect.getHeight(), um);
    syncLayoutFromTree();
}

void PluginEditor::commitEditTransaction()
{
    transactionOpen = false;
    writeLayoutToFile();
}

bool PluginEditor::isLocked (const juce::String& id) const
{
    return lockedElements.find (id) != lockedElements.end();
}

bool PluginEditor::isSelected (const juce::String& id) const
{
    return std::find (selection.begin(), selection.end(), id) != selection.end();
}

void PluginEditor::selectOnly (const juce::String& id)
{
    selection.clear();
    if (id.isNotEmpty() && ! isLocked (id))
        selection.push_back (id);
    keyboardFocusId = id;
}

void PluginEditor::toggleInSelection (const juce::String& id)
{
    if (id.isEmpty() || isLocked (id))
        return;
    const auto it = std::find (selection.begin(), selection.end(), id);
    if (it == selection.end()) selection.push_back (id);
    else                       selection.erase (it);
    keyboardFocusId = id;
}

std::vector<juce::Rectangle<float>> PluginEditor::otherSourceRects (const juce::String& excludeId) const
{
    std::vector<juce::Rectangle<float>> others;
    for (const auto& [id, element] : currentLayout.elements)
        if (id != excludeId)
            others.push_back (element.sourceRect);
    for (const auto& extra : trench::edit::panelCenterRects (kPanelSourceWidth, kPanelSourceHeight))
        others.push_back (extra);
    return others;
}
```

Add `#include <algorithm>` and `#include <set>` to `PluginEditor.cpp`'s includes if not present.

- [ ] **Step 3: Initialize the tree on construct and on hot-reload**

In `juce-shell/source/PluginEditor.cpp`, in the constructor, immediately after `currentLayout = trench::loadUiLayoutOrDefaults();`, add:

```cpp
    syncTreeFromLayout();
```

In `reloadLayoutIfChanged()`, after `currentLayout = trench::loadUiLayoutOrDefaults();`, add:

```cpp
    syncTreeFromLayout();
    undoManager.clearUndoHistory(); // an external file change is a new baseline
```

- [ ] **Step 4: Migrate existing single-selection paint/drag to the set**

In `juce-shell/source/PluginEditor.cpp`, update the phase-2 code that used `selectedElementId`:

In `handleEditMouseDown` (existing), replace the selection assignment block with:

```cpp
    const auto pos = event.getEventRelativeTo (this).position;
    const auto id = trench::edit::hitTest (pos, currentEditorRects());

    if (event.mods.isShiftDown())
        toggleInSelection (id);
    else if (! isSelected (id))
        selectOnly (id);
    else
        keyboardFocusId = id;

    draggingElement = id.isNotEmpty() && ! isLocked (id);
    if (draggingElement)
    {
        beginEditTransaction ("move");
        dragStartMouse = pos;
        dragStartSourceRect = currentLayout.sourceRectFor (id);
    }
    activeGuideX.reset();
    activeGuideY.reset();
    repaint();
```

In `paintEditOverlay` (existing), replace the `if (selectedElementId.isNotEmpty())` block guard so it iterates the selection set:

```cpp
    auto editorRects = currentEditorRects();
    for (const auto& selId : selection)
    {
        const auto er = editorRects[selId];
        g.setColour (juce::Colours::cyan);
        g.drawRect (er, 2.0f);
    }
```

(Leave the live-coords badge logic; rebind it to the first selected id — `selection.empty() ? juce::String() : selection.front()` — wherever it referenced `selectedElementId`.)

In `toggleEditMode` (existing), in the `if (! editMode)` cleanup block add:

```cpp
        selection.clear();
        marqueeActive = false;
        closeValueEditor (false);
```

(If `closeValueEditor` is not yet defined at this point, add a forward-safe empty body now and fill it in Task 12; or order Task 12 before this build. For a clean single-pass build, define `closeValueEditor` as a stub here that does nothing when `valueEditor == nullptr`.)

- [ ] **Step 5: Build the Tests target and run the full suite**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe`
Expected: PASS — all tests except the known-red `Default body roster is the requested two P2K references`. No new failures.

- [ ] **Step 6: Build the standalone**

Run: `cmake --build juce-shell/build --config Release --target TRENCH_Standalone --parallel`
Expected: build succeeds.

- [ ] **Step 7: Manual verification — selection set unchanged for single click**

1. Launch, Ctrl+Shift+L.
2. Click the morph wheel → bright cyan outline (single selection still works).
3. Drag it → still moves and snaps as before; on release `ui_layout.json` updates.

- [ ] **Step 8: Commit**

```bash
git add juce-shell/source/PluginEditor.h juce-shell/source/PluginEditor.cpp
git commit -m "feat(edit): selection-as-set + ValueTree/UndoManager authoring model"
```

---

## Task 9: Undo/redo (Cmd/Ctrl+Z, Cmd/Ctrl+Shift+Z)

**Files:**
- Modify: `juce-shell/source/PluginEditor.cpp`

Drag-move now opens a transaction (Task 8). Wire the keys so a move can be undone/redone.

- [ ] **Step 1: Route the keys**

In `juce-shell/source/PluginEditor.cpp`, in `keyPressed`, before the final `return false;`, add:

```cpp
    if (editMode)
    {
        const bool cmdOrCtrl = key.getModifiers().isCommandDown() || key.getModifiers().isCtrlDown();
        if (cmdOrCtrl && key.getKeyCode() == 'Z')
        {
            if (key.getModifiers().isShiftDown()) undoManager.redo();
            else                                  undoManager.undo();
            syncLayoutFromTree();
            writeLayoutToFile();
            return true;
        }
    }
```

- [ ] **Step 2: Make `setElementRect` during a drag NOT spam transactions**

In `handleEditMouseDrag` (existing), ensure the drag writes through `setElementRect (id, snap.rect, /*asTransaction*/ true)` rather than assigning `currentLayout.elements[...]` directly, so the move is captured in the open transaction. Replace the existing assignment line with:

```cpp
    setElementRect (selection.front(), snap.rect, /*asTransaction*/ true);
```

(Guard with `if (selection.empty()) return;` at the top of `handleEditMouseDrag`. `beginNewTransaction` was already called once in `mouseDown`, so all the drag's property writes coalesce into that one undoable transaction.)

- [ ] **Step 3: Commit the transaction on mouseUp**

In `handleEditMouseUp` (existing), replace the `writeLayoutToFile();` call with `commitEditTransaction();`.

- [ ] **Step 4: Build the standalone**

Run: `cmake --build juce-shell/build --config Release --target TRENCH_Standalone --parallel`
Expected: build succeeds.

- [ ] **Step 5: Manual verification — undo/redo**

1. Launch, Ctrl+Shift+L, drag the Q readout to a new spot, release.
2. Press **Ctrl+Z** → the Q readout jumps back to its previous position; `ui_layout.json` reflects the revert.
3. Press **Ctrl+Shift+Z** → it returns to the dragged position.
4. Make three separate drags, then Ctrl+Z three times → each undoes one drag in reverse order.

- [ ] **Step 6: Commit**

```bash
git add juce-shell/source/PluginEditor.cpp
git commit -m "feat(edit): undo/redo via UndoManager (Ctrl+Z / Ctrl+Shift+Z)"
```

---

## Task 10: Keyboard nudge + keyboard-operable selection (tab/esc/arrows)

**Files:**
- Modify: `juce-shell/source/PluginEditor.cpp`

This satisfies the spec's accessibility "keyboard-operable" requirement: select via Tab, deselect via Esc, move via arrows, all without the mouse.

- [ ] **Step 1: Implement nudge + focus cycling**

In `juce-shell/source/PluginEditor.cpp`, add:

```cpp
void PluginEditor::nudgeSelection (int dirX, int dirY, bool coarse)
{
    if (selection.empty())
        return;

    beginEditTransaction ("nudge");
    const auto d = trench::edit::nudgeDelta (dirX, dirY, coarse);
    for (const auto& id : selection)
    {
        if (isLocked (id))
            continue;
        const auto moved = currentLayout.sourceRectFor (id).translated (d.x, d.y);
        setElementRect (id, moved, /*asTransaction*/ true);
    }
    commitEditTransaction();
}

void PluginEditor::cycleKeyboardFocus (bool backwards)
{
    // Stable order = currentEditorRects() key order.
    std::vector<juce::String> ids;
    for (const auto& [id, r] : currentEditorRects())
    {
        juce::ignoreUnused (r);
        ids.push_back (id);
    }
    if (ids.empty())
        return;

    int idx = -1;
    for (int i = 0; i < (int) ids.size(); ++i)
        if (ids[(size_t) i] == keyboardFocusId) { idx = i; break; }

    idx = backwards ? (idx <= 0 ? (int) ids.size() - 1 : idx - 1)
                    : (idx + 1) % (int) ids.size();
    selectOnly (ids[(size_t) idx]);
    repaint();
}
```

- [ ] **Step 2: Route the keys**

In `keyPressed`, inside the existing `if (editMode)` block (after the undo handling), add:

```cpp
        if (key == juce::KeyPress::escapeKey)
        {
            selection.clear();
            keyboardFocusId.clear();
            closeValueEditor (false);
            repaint();
            return true;
        }
        if (key == juce::KeyPress::tabKey)
        {
            cycleKeyboardFocus (key.getModifiers().isShiftDown());
            return true;
        }

        const bool coarse = key.getModifiers().isShiftDown();
        if (key == juce::KeyPress::leftKey)  { nudgeSelection (-1, 0, coarse); return true; }
        if (key == juce::KeyPress::rightKey) { nudgeSelection ( 1, 0, coarse); return true; }
        if (key == juce::KeyPress::upKey)    { nudgeSelection ( 0, -1, coarse); return true; }
        if (key == juce::KeyPress::downKey)  { nudgeSelection ( 0,  1, coarse); return true; }
```

Note: `KeyPress::tabKey` is consumed only in edit mode; in normal play mode `keyPressed` returns false so JUCE's default focus traversal is unaffected.

- [ ] **Step 3: Build the standalone**

Run: `cmake --build juce-shell/build --config Release --target TRENCH_Standalone --parallel`
Expected: build succeeds.

- [ ] **Step 4: Manual verification — keyboard operability**

1. Launch, Ctrl+Shift+L. Without touching the mouse, press **Tab** → an element gets the selection outline; Tab again → focus advances; **Shift+Tab** → reverses.
2. With an element focused, press **Right arrow** → it moves 1 source px right (visible small shift); **Shift+Right** → moves 10 px.
3. Press **Ctrl+Z** → the nudge is undone (nudge is a transaction).
4. Press **Esc** → selection clears.
5. Confirm in normal (non-edit) mode the arrow keys / Tab do nothing special to the layout.

- [ ] **Step 5: Commit**

```bash
git add juce-shell/source/PluginEditor.cpp
git commit -m "feat(edit): keyboard nudge + tab/esc selection (keyboard-operable a11y)"
```

---

## Task 11: 8-handle resize wiring (handles draw + drag)

**Files:**
- Modify: `juce-shell/source/PluginEditor.cpp`

Handles appear only on a single selected element (spec: "Affordances only on the selected thing").

- [ ] **Step 1: Draw handles on the single selected element**

In `juce-shell/source/PluginEditor.cpp`, in `paintEditOverlay`, after the selection-outline loop, add a handle-drawing block that runs only when exactly one element is selected:

```cpp
    if (selection.size() == 1 && ! isLocked (selection.front()))
    {
        const auto er = editorRects[selection.front()];
        const float hs = 4.0f; // handle half-size in editor px
        const float xs[3] = { er.getX(), er.getCentreX(), er.getRight() };
        const float ys[3] = { er.getY(), er.getCentreY(), er.getBottom() };
        g.setColour (juce::Colours::white);
        for (float hx : xs)
            for (float hy : ys)
            {
                if (hx == er.getCentreX() && hy == er.getCentreY())
                    continue; // no centre handle
                const juce::Rectangle<float> box (hx - hs, hy - hs, hs * 2.0f, hs * 2.0f);
                g.fillRect (box);
                g.setColour (juce::Colours::black);
                g.drawRect (box, 1.0f); // outline so handles read on any background (a11y: not colour-only)
                g.setColour (juce::Colours::white);
            }
    }
```

- [ ] **Step 2: Detect a handle hit before a move in mouseDown**

In `handleEditMouseDown`, before computing `draggingElement`, add a handle check (only meaningful for a single selection):

```cpp
    activeHandle = trench::edit::Handle::none;
    if (selection.size() == 1 && ! isLocked (selection.front()))
    {
        const auto er = currentEditorRects()[selection.front()];
        activeHandle = trench::edit::handleAt (pos, er, 6.0f);
        if (activeHandle != trench::edit::Handle::none)
        {
            beginEditTransaction ("resize");
            dragStartMouse = pos;
            resizeStartSourceRect = currentLayout.sourceRectFor (selection.front());
            draggingElement = false; // resizing, not moving
            repaint();
            return;
        }
    }
```

(Place this right after `keyboardFocusId`/selection is resolved and before the `draggingElement = ...` line; if a handle was hit we `return` early so the move path does not also run.)

- [ ] **Step 3: Resize on drag**

In `handleEditMouseDrag`, before the existing move logic, add a resize branch:

```cpp
    if (activeHandle != trench::edit::Handle::none && selection.size() == 1)
    {
        const auto pos = event.getEventRelativeTo (this).position;
        const auto srcDelta = trench::edit::editorToSourceDelta (
            pos - dragStartMouse, (float) kEditorWidth, (float) kEditorHeight,
            kPanelSourceWidth, kPanelSourceHeight);

        const auto resized = trench::edit::resizeFromHandle (
            resizeStartSourceRect, activeHandle, { srcDelta.x, srcDelta.y },
            event.mods.isShiftDown(), event.mods.isAltDown(), /*minSize*/ 8.0f);

        setElementRect (selection.front(), resized, /*asTransaction*/ true);
        return;
    }
```

- [ ] **Step 4: Clear the handle on mouseUp**

In `handleEditMouseUp`, change the body so a resize also commits and clears:

```cpp
void PluginEditor::handleEditMouseUp (const juce::MouseEvent&)
{
    if (transactionOpen)
        commitEditTransaction();

    draggingElement = false;
    activeHandle = trench::edit::Handle::none;
    activeGuideX.reset();
    activeGuideY.reset();
    repaint();
}
```

- [ ] **Step 5: Build the standalone**

Run: `cmake --build juce-shell/build --config Release --target TRENCH_Standalone --parallel`
Expected: build succeeds.

- [ ] **Step 6: Manual verification — resize**

1. Launch, Ctrl+Shift+L, click the type selector (single selection) → eight white handles with dark outlines appear at its corners/edge midpoints.
2. Drag the bottom-right handle → width and height grow, top-left corner stays put; `ui_layout.json` updates on release.
3. Hold **Shift** while dragging a corner → aspect ratio is preserved.
4. Hold **Alt** while dragging → it grows symmetrically about the centre.
5. Drag a handle far inward → it stops at the minimum size, never inverting.
6. **Ctrl+Z** → the resize is undone in one step.

- [ ] **Step 7: Commit**

```bash
git add juce-shell/source/PluginEditor.cpp
git commit -m "feat(edit): 8-handle resize wiring (aspect/from-center, undoable)"
```

---

## Task 12: Type-exact numeric entry (tap a floating number to edit)

**Files:**
- Modify: `juce-shell/source/PluginEditor.cpp`

Progressive disclosure: while an element is selected, its X/Y/W/H float near it; clicking a number opens an inline `juce::TextEditor` to type an exact value. No standing inspector panel.

- [ ] **Step 1: Implement open/close + commit**

In `juce-shell/source/PluginEditor.cpp`, add:

```cpp
void PluginEditor::openValueEditor (const juce::String& id, int field, juce::Rectangle<float> editorAnchor)
{
    if (id.isEmpty() || isLocked (id))
        return;

    closeValueEditor (false);
    valueEditorElementId = id;
    valueEditorField = field;

    const auto sr = currentLayout.sourceRectFor (id);
    const float current[4] = { sr.getX(), sr.getY(), sr.getWidth(), sr.getHeight() };

    valueEditor = std::make_unique<juce::TextEditor>();
    valueEditor->setText (juce::String (juce::roundToInt (current[field])), false);
    valueEditor->setInputRestrictions (6, "0123456789-");
    valueEditor->setBounds (editorAnchor.toNearestInt());
    valueEditor->setColour (juce::TextEditor::backgroundColourId, juce::Colours::black);
    valueEditor->setColour (juce::TextEditor::textColourId, juce::Colours::white);
    valueEditor->selectAll();
    valueEditor->onReturnKey  = [this] { closeValueEditor (true); };
    valueEditor->onEscapeKey  = [this] { closeValueEditor (false); };
    valueEditor->onFocusLost  = [this] { closeValueEditor (true); };
    addAndMakeVisible (*valueEditor);
    valueEditor->grabKeyboardFocus();
}

void PluginEditor::closeValueEditor (bool commit)
{
    if (valueEditor == nullptr)
        return;

    if (commit && valueEditorElementId.isNotEmpty() && valueEditorField >= 0)
    {
        const auto text = valueEditor->getText().trim();
        if (text.containsOnly ("0123456789-") && text.isNotEmpty())
        {
            auto sr = currentLayout.sourceRectFor (valueEditorElementId);
            const float v = (float) text.getIntValue();
            switch (valueEditorField)
            {
                case 0: sr.setX (v); break;
                case 1: sr.setY (v); break;
                case 2: sr.setWidth  (juce::jmax (8.0f, v)); break; // never invert
                case 3: sr.setHeight (juce::jmax (8.0f, v)); break;
                default: break;
            }
            beginEditTransaction ("type value");
            setElementRect (valueEditorElementId, sr, /*asTransaction*/ true);
            commitEditTransaction();
        }
    }

    auto e = std::move (valueEditor);
    valueEditor.reset();
    valueEditorElementId.clear();
    valueEditorField = -1;
    repaint();
}
```

- [ ] **Step 2: Draw the four floating numbers and route clicks to them**

In `paintEditOverlay`, when exactly one element is selected, draw four small number chips (X/Y/W/H) above the element, each labeled so it is not colour-only (accessibility). First, store their editor-space rects as members so `mouseDown` can hit-test them. Add to the header (`PluginEditor.h`) after `valueEditorField`:

```cpp
    std::array<juce::Rectangle<float>, 4> valueChips {}; // x,y,w,h chip rects (editor space)
```

Add `#include <array>` to the header.

In `paintEditOverlay`, inside the single-selection block (after handles), add:

```cpp
        const auto sr = currentLayout.sourceRectFor (selection.front());
        const juce::String labels[4] = { "X", "Y", "W", "H" };
        const int vals[4] = { juce::roundToInt (sr.getX()), juce::roundToInt (sr.getY()),
                              juce::roundToInt (sr.getWidth()), juce::roundToInt (sr.getHeight()) };
        const float chipW = 40.0f, chipH = 14.0f, gap = 2.0f;
        float chipX = er.getX();
        const float chipY = juce::jmax (0.0f, er.getY() - chipH - 2.0f);
        g.setFont (10.0f);
        for (int i = 0; i < 4; ++i)
        {
            valueChips[(size_t) i] = { chipX, chipY, chipW, chipH };
            g.setColour (juce::Colours::black.withAlpha (0.8f));
            g.fillRect (valueChips[(size_t) i]);
            g.setColour (juce::Colours::white);
            g.drawRect (valueChips[(size_t) i], 1.0f); // border = not colour-only
            g.drawText (labels[i] + " " + juce::String (vals[i]),
                        valueChips[(size_t) i].reduced (2.0f, 0.0f),
                        juce::Justification::centredLeft);
            chipX += chipW + gap;
        }
```

(When not exactly one element is selected, reset the chips so stale rects cannot be clicked: at the top of `paintEditOverlay` add `if (selection.size() != 1) for (auto& c : valueChips) c = {};`.)

In `handleEditMouseDown`, before the handle check, add a chip check:

```cpp
    if (selection.size() == 1)
    {
        for (int i = 0; i < 4; ++i)
        {
            if (! valueChips[(size_t) i].isEmpty() && valueChips[(size_t) i].contains (pos))
            {
                openValueEditor (selection.front(), i, valueChips[(size_t) i]);
                return;
            }
        }
    }
```

- [ ] **Step 3: Replace the Task 8 `closeValueEditor` stub**

If Task 8 used a stub, this real definition supersedes it (delete the stub). Ensure `toggleEditMode`'s cleanup `closeValueEditor (false);` still compiles.

- [ ] **Step 4: Build the standalone**

Run: `cmake --build juce-shell/build --config Release --target TRENCH_Standalone --parallel`
Expected: build succeeds.

- [ ] **Step 5: Manual verification — type-exact**

1. Launch, Ctrl+Shift+L, click the morph readout → four chips (`X …`, `Y …`, `W …`, `H …`) appear above it.
2. Click the `X` chip → an inline editor opens with the current value selected; type `503`, press **Enter** → the readout jumps to x=503; `ui_layout.json` updates.
3. Click the `W` chip, type `5`, Enter → width clamps to the minimum (8), never inverting.
4. Open a chip and press **Esc** → no change is applied.
5. **Ctrl+Z** after a typed change → it reverts in one step.

- [ ] **Step 6: Commit**

```bash
git add juce-shell/source/PluginEditor.h juce-shell/source/PluginEditor.cpp
git commit -m "feat(edit): tap-to-type X/Y/W/H numeric entry (progressive disclosure)"
```

---

## Task 13: Marquee drag + shift-click multi-select wiring

**Files:**
- Modify: `juce-shell/source/PluginEditor.cpp`

Shift-click toggling already landed in Task 8. This task adds the rubber-band marquee on empty-space drag.

- [ ] **Step 1: Start a marquee on empty-space mouseDown**

In `handleEditMouseDown`, after the chip + handle checks, where `id` is empty (no element under the cursor), start a marquee instead of clearing immediately:

```cpp
    if (id.isEmpty() && activeHandle == trench::edit::Handle::none)
    {
        if (! event.mods.isShiftDown())
            selection.clear();
        marqueeActive = true;
        marqueeStart = pos;
        marqueeRect = { pos.x, pos.y, 0.0f, 0.0f };
        draggingElement = false;
        repaint();
        return;
    }
```

(Ensure this runs only when `id.isEmpty()`; the element-hit path below is unchanged.)

- [ ] **Step 2: Grow the marquee on drag**

In `handleEditMouseDrag`, before the resize/move branches, add:

```cpp
    if (marqueeActive)
    {
        const auto pos = event.getEventRelativeTo (this).position;
        marqueeRect = juce::Rectangle<float>::leftTopRightBottom (
            juce::jmin (marqueeStart.x, pos.x), juce::jmin (marqueeStart.y, pos.y),
            juce::jmax (marqueeStart.x, pos.x), juce::jmax (marqueeStart.y, pos.y));
        repaint();
        return;
    }
```

- [ ] **Step 3: Commit the marquee selection on mouseUp**

In `handleEditMouseUp`, at the very top (before the transaction commit), add:

```cpp
    if (marqueeActive)
    {
        const auto hits = trench::edit::marqueeHits (marqueeRect, currentEditorRects());
        for (const auto& hid : hits)
            if (! isLocked (hid) && ! isSelected (hid))
                selection.push_back (hid);
        if (! selection.empty())
            keyboardFocusId = selection.front();
        marqueeActive = false;
        marqueeRect = {};
        repaint();
        return;
    }
```

- [ ] **Step 4: Draw the marquee**

In `paintEditOverlay`, at the end, add:

```cpp
    if (marqueeActive)
    {
        g.setColour (juce::Colours::cyan.withAlpha (0.15f));
        g.fillRect (marqueeRect);
        g.setColour (juce::Colours::cyan.withAlpha (0.8f));
        g.drawRect (marqueeRect, 1.0f);
    }
```

- [ ] **Step 5: Build the standalone**

Run: `cmake --build juce-shell/build --config Release --target TRENCH_Standalone --parallel`
Expected: build succeeds.

- [ ] **Step 6: Manual verification — marquee + multi-select**

1. Launch, Ctrl+Shift+L. Drag from empty space across the two wheels → a translucent cyan rubber-band appears; on release both wheels are outlined (multi-selected).
2. **Shift-click** the type selector → it joins the selection; shift-click it again → it leaves.
3. With two wheels selected, press an arrow → both nudge together (Task 10 nudge over the set).
4. Click empty space (no drag) → selection clears.

- [ ] **Step 7: Commit**

```bash
git add juce-shell/source/PluginEditor.cpp
git commit -m "feat(edit): marquee rubber-band multi-select wiring"
```

---

## Task 14: Measure-on-hover distance badges wiring

**Files:**
- Modify: `juce-shell/source/PluginEditor.cpp`

Spec: distance badges float while dragging/holding, then vanish. Draw them for the single selected element while a move/resize is in flight.

- [ ] **Step 1: Draw measure badges during a drag**

In `paintEditOverlay`, inside the single-selection block, add a measure-badge draw gated on an active drag/resize:

```cpp
        if (transactionOpen) // only while actively moving/resizing
        {
            const auto badges = trench::edit::measureBadges (
                currentLayout.sourceRectFor (selection.front()),
                otherSourceRects (selection.front()),
                kPanelSourceWidth, kPanelSourceHeight);

            g.setFont (10.0f);
            for (const auto& bdg : badges)
            {
                const float ex = bdg.anchor.x * (float) kEditorWidth / kPanelSourceWidth;
                const float ey = bdg.anchor.y * (float) kEditorHeight / kPanelSourceHeight;
                const juce::Rectangle<float> chip (ex - 14.0f, ey - 7.0f, 28.0f, 14.0f);
                g.setColour (juce::Colours::black.withAlpha (0.75f));
                g.fillRect (chip);
                g.setColour (juce::Colours::yellow);
                g.drawRect (chip, 1.0f); // border so it reads without relying on hue (a11y)
                g.drawText (bdg.text, chip, juce::Justification::centred);
            }
        }
```

Note: `otherSourceRects` (added in Task 8) already appends panel-center pseudo-rects; for measurement the panel edges are computed inside `measureBadges` from `panelWidth/panelHeight`, so the zero-size center rects do not distort gap readings (they never sit between the element and an edge on the perpendicular-overlap test).

- [ ] **Step 2: Build the standalone**

Run: `cmake --build juce-shell/build --config Release --target TRENCH_Standalone --parallel`
Expected: build succeeds.

- [ ] **Step 3: Manual verification — measure badges**

1. Launch, Ctrl+Shift+L, click the morph readout, and begin dragging it.
2. While dragging, four yellow distance chips appear (one per side) showing source-px gaps to the nearest sibling or panel edge, updating live.
3. Release → the chips vanish (badges only while a transaction is open).
4. Drag it near the Q readout → the gap on that side shrinks toward 0 as they approach.

- [ ] **Step 4: Commit**

```bash
git add juce-shell/source/PluginEditor.cpp
git commit -m "feat(edit): measure-on-drag distance badges to neighbors/panel edges"
```

---

## Task 15: Lock on reach + align/distribute on reach

**Files:**
- Modify: `juce-shell/source/PluginEditor.cpp`

Spec: lock surfaces "on reach" (a key); align/distribute is an explicit "tidy these" only on reach (not a standing toolbar).

- [ ] **Step 1: Implement lock toggle + align/distribute over the selection**

In `juce-shell/source/PluginEditor.cpp`, add:

```cpp
void PluginEditor::toggleLockOnSelection()
{
    for (const auto& id : selection)
    {
        if (lockedElements.count (id)) lockedElements.erase (id);
        else                           lockedElements.insert (id);
    }
    // Locked elements cannot stay selected (they are unmovable).
    selection.erase (std::remove_if (selection.begin(), selection.end(),
                     [this] (const juce::String& id) { return isLocked (id); }),
                     selection.end());
    repaint();
}

void PluginEditor::alignSelection (trench::edit::AlignMode mode)
{
    if (selection.size() < 2)
        return;

    std::vector<juce::Rectangle<float>> rs;
    for (const auto& id : selection)
        rs.push_back (currentLayout.sourceRectFor (id));

    const auto out = trench::edit::alignRects (rs, mode);

    beginEditTransaction ("align");
    for (size_t i = 0; i < selection.size(); ++i)
        if (! isLocked (selection[i]))
            setElementRect (selection[i], out[i], /*asTransaction*/ true);
    commitEditTransaction();
}

void PluginEditor::distributeSelection (bool horizontal)
{
    if (selection.size() < 3)
        return;

    std::vector<juce::Rectangle<float>> rs;
    for (const auto& id : selection)
        rs.push_back (currentLayout.sourceRectFor (id));

    const auto out = trench::edit::distributeRects (rs, horizontal);

    beginEditTransaction ("distribute");
    for (size_t i = 0; i < selection.size(); ++i)
        if (! isLocked (selection[i]))
            setElementRect (selection[i], out[i], /*asTransaction*/ true);
    commitEditTransaction();
}
```

Add `#include <algorithm>` to `PluginEditor.cpp` if not already present (for `std::remove_if`).

- [ ] **Step 2: Route the reach keys**

In `keyPressed`, inside the `if (editMode)` block (after the nudge keys), add:

```cpp
        // Lock on reach: 'K' toggles lock on the current selection.
        if (key.getKeyCode() == 'K' && ! key.getModifiers().isCommandDown()
            && ! key.getModifiers().isCtrlDown())
        {
            toggleLockOnSelection();
            return true;
        }
        // Align/distribute on reach (explicit "tidy these"):
        if (key == juce::KeyPress ('1')) { alignSelection (trench::edit::AlignMode::sameX);      return true; }
        if (key == juce::KeyPress ('2')) { alignSelection (trench::edit::AlignMode::sameY);      return true; }
        if (key == juce::KeyPress ('3')) { alignSelection (trench::edit::AlignMode::sameWidth);  return true; }
        if (key == juce::KeyPress ('4')) { alignSelection (trench::edit::AlignMode::sameHeight); return true; }
        if (key == juce::KeyPress ('5')) { alignSelection (trench::edit::AlignMode::centerX);    return true; }
        if (key == juce::KeyPress ('6')) { alignSelection (trench::edit::AlignMode::centerY);    return true; }
        if (key == juce::KeyPress ('7')) { distributeSelection (/*horizontal*/ true);            return true; }
        if (key == juce::KeyPress ('8')) { distributeSelection (/*horizontal*/ false);           return true; }
```

- [ ] **Step 3: Show lock state in the overlay (not colour-only)**

In `paintEditOverlay`, in the per-element outline loop, draw a small padlock glyph (a "L" tag) on locked elements so lock is visible by shape/label, not hue:

```cpp
    for (const auto& [id, r] : editorRects)
    {
        g.setColour (juce::Colours::cyan.withAlpha (0.35f));
        g.drawRect (r, 1.0f);
        if (isLocked (id))
        {
            g.setColour (juce::Colours::orange);
            g.setFont (10.0f);
            g.drawText ("LOCK", r.removeFromTop (12.0f).reduced (2.0f, 0.0f),
                        juce::Justification::topLeft); // text label, not colour alone
        }
    }
```

(If the existing outline loop differs, fold the `isLocked` tag into it; the point is the lock state is shown with a text label.)

- [ ] **Step 4: Build the standalone**

Run: `cmake --build juce-shell/build --config Release --target TRENCH_Standalone --parallel`
Expected: build succeeds.

- [ ] **Step 5: Manual verification — lock + align/distribute**

1. Launch, Ctrl+Shift+L, select the type selector, press **K** → a "LOCK" tag appears; clicking it no longer selects/moves it; dragging it does nothing.
2. Press **K** again with it focused via Tab → unlocks (selectable again).
3. Marquee-select the two readouts, press **3** (sameWidth) → both take the first's width; `ui_layout.json` updates; **Ctrl+Z** reverts in one step.
4. Marquee-select both wheels + the type selector (3 items), press **8** (distribute vertical) → vertical gaps even out; outer two stay; **Ctrl+Z** reverts.
5. Lock one of a multi-selection, then align → the locked one stays put while the others align.

- [ ] **Step 6: Commit**

```bash
git add juce-shell/source/PluginEditor.cpp juce-shell/source/PluginEditor.h
git commit -m "feat(edit): lock on reach + align/distribute on reach (rules vocabulary)"
```

---

## Task 16: Wire panel-center snapping into drag + accessibility focus polish

**Files:**
- Modify: `juce-shell/source/PluginEditor.cpp`

Panel-center pseudo-rects are already produced by `panelCenterRects` and included by `otherSourceRects` (Task 8). This task makes the *move drag* use `otherSourceRects` (so it snaps to panel center, not only siblings), and finalizes the accessibility surface (visible focus ring, color-never-alone, screen-reader names).

- [ ] **Step 1: Use panel-center-augmented others in the move drag**

In `handleEditMouseDrag`, in the move branch, replace the local `others` construction with the shared helper so panel-center snapping is active:

```cpp
    const auto others = otherSourceRects (selection.front());
    const auto snap = trench::edit::snapRect (moved, others, 8.0f);
```

(The `snapRect` and guide-drawing logic are unchanged; the only difference is panel-center lines are now snap targets.)

- [ ] **Step 2: Draw a visible focus ring for the keyboard-focused element**

In `paintEditOverlay`, after the selection-outline loop, add a distinct focus ring (dashed-look via a double rectangle, so it differs from selection by *shape* not only colour — accessibility):

```cpp
    if (keyboardFocusId.isNotEmpty())
    {
        const auto fr = editorRects[keyboardFocusId];
        g.setColour (juce::Colours::white);
        g.drawRect (fr.expanded (2.0f), 1.0f);
        g.setColour (juce::Colours::black);
        g.drawRect (fr.expanded (3.0f), 1.0f); // outer dark ring -> readable on any bg
    }
```

- [ ] **Step 3: Screen-reader names (where JUCE supports it)**

In the constructor, give the editor and child controls accessible titles so a screen reader announces them. After `setWantsKeyboardFocus (true);` add:

```cpp
    setTitle ("TRENCH plugin editor");
    setDescription ("Press Ctrl+Shift+L to toggle layout edit mode.");
    morphHitTarget.setTitle ("Morph wheel");
    qHitTarget.setTitle ("Q wheel");
    bodySelector.setTitle ("Filter type selector");
```

(If any of these accessor calls are unavailable on a control type, drop just that line; never block the build on it.)

- [ ] **Step 4: Build the standalone + run the full test suite**

Run: `cmake --build juce-shell/build --config Release --target TRENCH_Standalone --parallel`
Then: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe`
Expected: standalone builds; tests PASS except the known-red roster test. No new failures.

- [ ] **Step 5: Manual verification — panel-center snap + focus**

1. Launch, Ctrl+Shift+L, drag the type selector so its centre nears the panel's horizontal centre (x≈512 source / ≈180 editor px) → a magenta guide snaps it to panel centre.
2. Tab to an element → a white-on-black double-ring focus indicator appears, visually distinct from the cyan selection outline.
3. Toggle edit mode off → all overlays, focus ring, and any open value editor disappear; the plugin plays normally.

- [ ] **Step 6: Commit**

```bash
git add juce-shell/source/PluginEditor.cpp
git commit -m "feat(edit): panel-center snap in drag + visible focus ring + a11y names"
```

---

## Task 17: Full regression sweep + persistence check

**Files:** none (verification only)

- [ ] **Step 1: Run the full unit suite**

Run: `cmake --build juce-shell/build --config Release --target Tests --parallel`
Then: `juce-shell/build/Release/Tests.exe`
Expected: every test passes except the single known-red `Default body roster is the requested two P2K references`. Confirm all `UiLayoutEdit` cases from Tasks 1-7 are present and green (`juce-shell/build/Release/Tests.exe "*resizeFromHandle*" "*handleAt*" "*nudgeDelta*" "*panelCenterRects*" "*distanceToNeighbor*" "*measureBadges*" "*marqueeHits*" "*alignRects*" "*distributeRects*"`).

- [ ] **Step 2: Manual end-to-end persistence**

1. Launch standalone, Ctrl+Shift+L. Resize a wheel, nudge a readout with arrows, type an exact W on the selector, align the two readouts.
2. Confirm `~/Documents/TRENCH/ui_layout.json` reflects every change.
3. Close and relaunch → the edited layout is restored exactly (no flicker, no self-reload).
4. Ctrl+Z several times in a fresh session is a no-op (history cleared on load) — layout stays as saved.

- [ ] **Step 3: Manual audio-keeps-running check**

While in edit mode with audio playing through the standalone, resize/drag/nudge → the wheels keep animating and audio is uninterrupted (edit mode only overlays + handles input; `processBlock` untouched).

- [ ] **Step 4: Commit (if any doc/notes changed; otherwise skip)**

```bash
git add -A
git commit -m "chore(edit): phase 2b regression sweep notes" || echo "nothing to commit"
```

---

## Self-Review

**Spec coverage (against `2026-06-19-trench-ui-layout-loop-design.md` §4, §4a, §4b, accessibility, v1 DoD):**

| Spec item (§4b engine / DoD) | Task |
|---|---|
| Resize — 8 handles; shift aspect-lock; alt from-center | Task 1 (`handleAt`), Task 2 (`resizeFromHandle`), Task 11 (wiring) |
| Move — arrow 1px, shift+arrow 10px | Task 3 (`nudgeDelta`), Task 10 (wiring) |
| Selection — shift-click multi-select, marquee | Task 6 (`marqueeHits`), Task 8 (shift toggle), Task 13 (marquee wiring) |
| Smart guides + snapping vs panel center | Task 4 (`panelCenterRects`), Task 16 (drag wiring) |
| Measure — px distance badges to neighbors/edges | Task 5 (`distanceToNeighbor`/`measureBadges`), Task 14 (wiring) |
| Type-exact — tap a floating number to edit | Task 12 |
| Align/distribute → rules vocabulary | Task 7 (`alignRects`/`distributeRects`), Task 15 (on-reach wiring) |
| Undo/redo via ValueTree+UndoManager | Task 8 (model), Task 9 (keys) |
| Lock on reach | Task 8 (state), Task 15 (toggle + visual) |
| Numbers float on touch, vanish (progressive disclosure) | Task 12 chips + Task 14 badges (drawn only while selected/transaction open) |
| Handles only on the selected thing | Task 11 (single-selection gate) |
| Keyboard-operable (a11y) | Task 10 (tab/esc/arrows), Task 9 (undo) |
| Color never the only signal | Task 11 (handle outlines), Task 12/14 (bordered chips), Task 15 ("LOCK" text), Task 16 (focus ring shape) |
| Visible focus | Task 16 (double-ring focus indicator) |
| Screen-reader names | Task 16 (`setTitle`/`setDescription`) |

**Explicitly out (and not implemented here):** layout file/hot-reload/toggle/click-select/drag-move/sibling-snap/auto-write (phase 1/2); render/scene/validator tool; Inspect schematic; AI suggestions; add/remove elements; restyling curated art. Per the scope note.

**Placeholder scan:** every code step contains complete code; no TODO/TBD/"similar to above". Interactive steps carry explicit manual checks with expected on-screen results. The only deliberate forward-reference is the Task 8 `closeValueEditor` stub, which Task 12 replaces with the full body — flagged in both tasks. ✓

**Type consistency:** new pure functions — `handleAt(Point,Rect,float)->Handle`, `resizeFromHandle(Rect,Handle,Point,bool,bool,float)->Rect`, `nudgeDelta(int,int,bool)->Point`, `panelCenterRects(float,float)->vector<Rect>`, `distanceToNeighbor(Rect,vector<Rect>,float,float)->Measurements`, `measureBadges(...)->vector<MeasureBadge>`, `marqueeHits(Rect,map<String,Rect>)->vector<String>`, `alignRects(vector<Rect>,AlignMode)->vector<Rect>`, `distributeRects(vector<Rect>,bool)->vector<Rect>` — are each called with matching signatures in their wiring task. `selection` (vector<String>) replaces `selectedElementId` consistently across paint/mouse/keyboard. `setElementRect`/`beginEditTransaction`/`commitEditTransaction`/`syncTreeFromLayout`/`syncLayoutFromTree` are the single mutation path; every interactive task routes through them so undo always works. Reuses existing `kEditorWidth/kEditorHeight/kPanelSourceWidth/kPanelSourceHeight`, `sourceRectToEditor`, `currentEditorRects()`, `currentLayout` (public `elements`), `writeLayoutToFile()`, and phase-2 `editorToSourceDelta`/`hitTest`/`snapRect`/`SnapResult`. ✓

**Accessibility / validation (not cut):** keyboard operability (Task 10), color-never-alone via borders/labels/shape (Tasks 11/12/14/15/16), visible focus ring (Task 16), screen-reader titles (Task 16). Validation: `resizeFromHandle`/type-entry enforce a minimum size and never invert; nudge/resize/align/distribute skip locked elements; `setElementRect` no-ops on unknown ids; `writeLayoutToFile` (phase 1/2) creates the parent dir and tolerates write failure; undo history is cleared on external file reload so a stale undo cannot corrupt a freshly loaded layout; the layout always serializes through the validated `UiLayout::toJsonString`, so malformed state can never reach disk. ✓
