# TRENCH UI Layout Loop — design

Date: 2026-06-19
Status: approved (brainstorming)

## Problem

When Claude builds the TRENCH plugin UI, control placement is done **blind**.
Positions live as hardcoded source-space rectangles in
`juce-shell/source/PluginEditor.cpp` (`morphWheelWell`, `qWheelWell`,
`typeSelectorWell`, `morphReadoutWell`, `qReadoutWell`). Claude edits those
numbers, but neither Claude nor the user can see the result without a full
build + launch. So controls sometimes land wrong — misaligned, overlapping,
nudged off — and the loop to notice and correct it is slow.

The user's words: "those times things just aren't placed properly."

This is a **feedback-loop problem**, not a missing-design-tool problem. The fix
is to (1) let Claude *see* the rendered UI so placement can be verified and
self-corrected, and (2) make moving a control cheap (no recompile).

## Goal

Give the user **direct manual control** of UI layout, live in the running
plugin — and back it with an engine that lets Claude see and verify the same
layout. The user drives; Claude assists.

1. **Manual edit mode (the headline)** — a key flips the running plugin into
   layout-edit mode. Every control is outlined and grabbable: drag to move,
   handles to resize, arrow keys nudge 1 px (shift+arrow 10 px). Snap guides
   appear against sibling controls; a held modifier ignores snapping for exact
   by-eye placement. Live and audible — the plugin keeps running in the DAW
   while it is rearranged. Every move auto-writes `ui_layout.json`.
2. **Hot-reloaded layout** — positions/sizes (and a small set of style props)
   of the existing controls live in `ui_layout.json`, read at runtime and
   reloaded when it changes. So edits — by hand, by Claude, or by file — apply
   without a rebuild.
3. **Render + scene + validator (the engine, serving the surface)** — render
   the actual editor to a PNG plus structured `scene.json`/`validation.json`.
   This powers the snap guides and alignment hints under the user's hands, and
   lets Claude *see* and verify the same layout when asked to help.

The primary surface is **manual, in-plugin, live**. The render/scene/validator
engine is built to serve that surface (and Claude's verification), not to be the
star. Claude assists; the user controls.

## Design principle: ultra-efficient collab surface

The user's hands are the primary editor; Claude is an assistant on the same
state, not the driver. Every design choice is judged by how tight it makes the
loop and how directly the user can control placement:

- **One shared document.** A single `ui_layout.json` is the source of truth,
  read *and* written by both sides. The user drags → Claude reads the result
  and refines; Claude edits numbers → the user sees them in-plugin. One file,
  two editors — like a single Figma file, not edits thrown over a wall.
- **One shared picture with shared names.** The render carries a labeled
  overlay (each control's `id` + rect drawn on it) so both sides use the exact
  same vocabulary — `morphReadout`, not "the bottom-right box." Zero ambiguity
  per turn.
- **One-turn iterations.** A nudge in plain words → Claude edits JSON →
  renders → shows the PNG, all in a single reply. The loop is gated by a
  sub-second offscreen render, never a rebuild.
- **Visible diffs.** The render tool keeps the prior PNG so a change reads as a
  before/after, not a guess.

## Non-goals (v1)

- Adding brand-new controls or removing existing ones.
- Swapping or regenerating the panel artwork (curated asset — never touched
  procedurally; see memory `ui-changes-additive-keep-assets`).
- AI auto-restyle of the look. Any future AI assist only *proposes* layout for
  the user to accept/reject; it never rewrites curated art.
- A browser drag-and-drop canvas. Rejected because a browser is a second
  renderer that drifts from JUCE; the plugin's own renderer must be the source
  of truth. Manual editing lives **in the plugin** — that is the headline
  surface, not a deferred extra.
- A separate standalone design window (assumed not wanted). Manual control is
  in the running plugin, live in the DAW. Revisit only if the user prefers a
  dedicated window.

## Architecture

Three units, each independently testable.

### 1. Layout file — `ui_layout.json` (the contract)

Location: `~/Documents/TRENCH/ui_layout.json` (same on-disk override dir the
plugin already uses for `authoring_slot.json`, per `TrenchBodyRoster.h`).

Owns **appearance + placement only**. Behavior (DSP, parameter wiring) stays in
C++.

Each entry is keyed by a stable element id the plugin knows. Rects are in the
existing **1024×1591 source space** so they scale exactly like today's
hardcoded rects (`sourceRectToEditor`). Element ids and their current defaults:

| id             | source rect (x, y, w, h)        |
|----------------|---------------------------------|
| `morphWheel`   | 127, 694, 423, 101              |
| `qWheel`       | 127, 871, 423, 101              |
| `typeSelector` | 230, 142, 672, 73               |
| `morphReadout` | 603, 712, 168, 77               |
| `qReadout`     | 602, 889, 169, 79               |

Schema (v1):

```json
{
  "version": 1,
  "sourceSpace": [1024, 1591],
  "groups": {
    "wheels":   ["morphWheel", "qWheel"],
    "readouts": ["morphReadout", "qReadout"]
  },
  "rules": [
    { "type": "sameX",     "elements": ["morphWheel", "qWheel"] },
    { "type": "sameWidth", "elements": ["morphWheel", "qWheel"] },
    { "type": "sameX",     "elements": ["morphReadout", "qReadout"] },
    { "type": "sameWidth", "elements": ["morphReadout", "qReadout"] },
    { "type": "centerY",   "a": "morphReadout", "b": "morphWheel" },
    { "type": "centerY",   "a": "qReadout",     "b": "qWheel" }
  ],
  "elements": {
    "morphWheel":   { "rect": [127, 694, 423, 101] },
    "qWheel":       { "rect": [127, 871, 423, 101] },
    "typeSelector": { "rect": [230, 142, 672, 73] },
    "morphReadout": { "rect": [603, 712, 168, 77], "fontSize": 13, "textColor": "ff000000" },
    "qReadout":     { "rect": [602, 889, 169, 79], "fontSize": 13, "textColor": "ff000000" }
  }
}
```

- `rect` is required per element. `fontSize` / `textColor` are optional style
  overrides (v1 limits style to readout/selector text; the rest of the styling
  stays in C++ to keep scope tight).
- `groups` name sets of elements so Claude/user can reason at the group level
  ("the readouts") instead of per element.
- `rules` are **named relationships**, not a general constraint solver. The same
  declaration serves two cheap jobs: the **validator checks** whether a rule
  holds (within tolerance) and reports violations, and a one-shot **resolver**
  can snap rects to satisfy a rule on request. This buys ~90% of "stop thinking
  in raw x,y,w,h" without an optimizer. Supported v1 rule types: `sameX`,
  `sameY`, `sameWidth`, `sameHeight`, `centerY` (a vs b), `centerX` (a vs b).
- `groups` and `rules` are optional. Absent → plain rect behavior. The plugin
  runtime ignores them entirely; they are consumed only by the render tool's
  validator/resolver. The plugin reads `elements[*].rect` and style only.
- Unknown ids are ignored. Missing ids fall back to the C++ default.
- A missing or malformed file means the plugin uses **today's hardcoded values
  exactly** — shipped behavior is unchanged until the user opts in.

A seed `ui_layout.json` containing the current defaults is generated so the
designer/render tool and the plugin agree on pixel one.

### 2. Render tool (built first)

A small harness that constructs `PluginProcessor` + `PluginEditor`, renders the
editor into a `juce::Image`, and emits a **render bundle** Claude can read after
any layout change. The PNG is necessary but not sufficient — the structured
outputs are what let Claude *reason* instead of inferring everything from pixels.

Reads the same `ui_layout.json` the plugin reads, so every output reflects the
live layout. Behavior is read-only: it renders/validates, it never writes the
layout (the resolver, see below, is an explicit separate command).

Outputs per render:

- `clean.png` — deterministic, true editor size (360×560).
- `overlay.png` — each element's `id` + rect drawn on a faint outline of its
  bounds. Shared-vocabulary surface for the collab loop.
- `scene.json` — structured truth, sourced from the editor itself via a
  `getUiDebugTree()` accessor so the overlay is a *view of truth*, not
  reconstructed. Per element: `id`, `sourceRect`, `editorRect`, `visible`,
  `zIndex`, `acceptsMouse`, `text`, `fontSize`, `textColour`.
- `validation.json` — output of the validator (below).
- `last.png` — the prior `clean.png`, preserved so a change reads as a
  before/after diff.

Render form: offscreen (construct editor, `paintEntireComponent` /
`createComponentSnapshot` into an `Image`, write PNG) so no DAW/standalone
window is needed. If offscreen proves impractical in JUCE, fall back to
launching `TrenchStandaloneApp` and screenshotting — but offscreen is the
target.

### 2a. Validator + resolver

The validator reads `scene.json` + the layout's `rules`/`groups` and emits a
blunt pass/fail with reasons. v1 checks:

- overlap between non-ancestor elements (e.g. `morphReadout` vs `morphWheel`)
- any rect off the source-space canvas
- missing / malformed rect
- unknown element id referenced by a rule
- text clipping (readout text at its longest expected value)
- curated-art hash unchanged (panel pixels must not move)
- each declared `rule` holds within tolerance

Output shape:

```txt
FAIL
- qReadout is 1 source px wider than morphReadout (rule sameWidth)
- morphReadout centerY is 3.4 source px above morphWheel centerY (rule centerY)
```

The **resolver** is the inverse: given a rule (or "apply all rules"), it mutates
the rects to satisfy it and writes the updated `ui_layout.json`. This is the only
write path in the tool, invoked explicitly — never as a side effect of render.

### 3. Plugin runtime (layout-driven wells)

`PluginEditor`:

- On construction and on `timerCallback` (already runs at 24 Hz): if
  `ui_layout.json` exists and its mtime changed since last load, parse it into
  an in-memory layout map; on parse failure, keep the previous good layout (or
  defaults) and do not crash.
- The well functions (`morphWheelWell`, etc.) become lookups: return the
  layout's rect for that id if present, else the hardcoded default. This is the
  single integration point — `resized()`, `paint()`, and hit-testing all flow
  through the well functions already, so they pick up the override for free.
- Style overrides (`fontSize`, `textColor`) applied where readouts/selector
  text are drawn.

### 4. In-plugin manual edit mode (the headline surface)

A layout-edit mode inside `PluginEditor`, toggled by a key chord (e.g.
Ctrl+Shift+L). When active:

- Every known element draws a selectable outline with its `id`.
- Click to select; drag to move; corner/edge handles to resize; arrow keys
  nudge 1 source px, shift+arrow 10.
- **Snap guides** against sibling edges/centers (driven by the same `rules`/
  `scene` geometry the validator uses). A held modifier (e.g. Alt) disables
  snapping for exact by-eye placement.
- Selected element shows its live source-space and editor-space rect.
- Normal plugin behavior (DSP, sound, parameter motion) keeps running — edit
  mode overlays, it does not stop the audio or the wheels.
- Every committed move writes `ui_layout.json` (debounced), so the change
  persists and Claude can read it immediately. Exiting edit mode is just a
  toggle; the layout is already saved.
- Edit mode is dev/author-facing and off by default in shipped builds (gated by
  a build flag or hidden chord) — end users get the fixed, designed layout.

Internally this mutates a `ValueTree` model under a `UndoManager` (so undo/redo
is real — see UX below), then serializes the tree to `ui_layout.json`.

### 4a. Figma-grade interaction vocabulary

The edit mode targets the direct-manipulation feel users already know from
Figma. Adopt the patterns that fit a fixed 360×560 panel of ~5 elements; drop
the ones that don't.

**Core (must feel like Figma):**

- **Selection** — click to select, click empty space to deselect, **shift-click
  to add/remove** from a multi-selection, **marquee drag** (rubber-band) to
  select within a region.
- **Move** — drag to move; **arrow** nudges 1 px, **shift+arrow** 10 px; **hold
  shift while dragging constrains to one axis** (pure horizontal/vertical).
- **Resize** — 8 handles (4 corners + 4 edges); **shift = preserve aspect
  ratio**; **alt = resize from center**.
- **Smart guides + snapping** — red alignment lines when an edge/center lines up
  with a sibling or the panel center; snap to those lines; **hold a modifier
  (alt) to suppress snapping** for exact by-eye placement.
- **Measure on hover** — hold a key and hover/select to show **px distance
  badges** to neighboring elements and panel edges. This is the feature that
  turns "feels slightly off" into an exact number.
- **Properties inspector** — a small panel showing the selection's **X / Y / W /
  H (source space), typeable** for pixel-exact entry; also font size / text
  colour for readouts.
- **Align & distribute** — with a multi-selection: align left/right/top/bottom/
  centers, match width/height, distribute spacing. These map onto the `rules`
  vocabulary (`sameX`, `sameWidth`, `centerY`, …) — one click writes a rule's
  effect.
- **Undo / redo** — Cmd/Ctrl+Z, Cmd/Ctrl+Shift+Z, backed by `UndoManager`.
- **Lock** — lock an element so it can't be selected/moved (protect a placed
  control while nudging others).

**Nice-to-have (add if cheap, not gating):**

- Zoom/magnify for pixel work (scroll-zoom, fit, zoom-to-selection) — useful but
  the panel is small and fixed, so secondary.
- Copy/paste of a position; nudge-repeat.
- A faint pixel grid toggle.

**Explicitly out (Figma features that don't apply here):**

- Adding/removing/duplicating elements (v1 edits the fixed set).
- Components/variants, auto-layout, vector/pen editing, multiple pages/frames,
  comments, real-time multiplayer cursors.
- Restyling curated panel artwork.

### Data flow

```
USER (primary): edit mode in running plugin ─► drag/resize/nudge/snap
                                              ─► auto-writes ui_layout.json
                                                       │
ui_layout.json (shared truth) ◄────────────────────────┘
   │
   ├─► plugin Timer sees mtime change ─► wells return new rects ─► repaint
   │       (so file/Claude edits also apply live, no rebuild)
   │
   └─► render tool (assist/verify) ─► clean.png + overlay.png
                                      + scene.json + validation.json
                                              │
                                    Claude reads pixels + structure,
                                    runs validator, may call resolver
                                    (writes layout) when asked to help
```

## Error handling

- Missing file → defaults, silent (the common shipped case).
- Malformed JSON / missing `version` / bad rect → keep last good layout (or
  defaults), do not throw into the audio/UI path.
- Out-of-range rect → applied as-is (designer's responsibility); render tool
  makes a bad rect visible so it is caught by eye, not by clamping silently.
- Render tool failure → non-zero exit + stderr; never writes a partial PNG.

## Testing

- **Layout parse**: valid file → expected rect map; malformed → falls back to
  defaults without throwing; unknown id ignored; missing id uses default.
- **Well lookup**: with override present, well returns override rect; absent,
  returns hardcoded default (regression-guards the no-file shipped path).
- **Seed round-trip**: seed JSON equals the hardcoded defaults (so opting in
  changes nothing until a value is edited).
- **Render tool**: produces a 360×560 PNG; re-rendering the seed matches the
  current shipped layout within tolerance.
- **Scene output**: `scene.json` element rects match what the editor's well
  functions return for the same layout.
- **Validator**: a layout with a known overlap / off-canvas / broken rule is
  reported FAIL with the right reason; the seed layout reports PASS.
- **Resolver**: applying a `sameWidth` rule to mismatched rects makes them equal
  and leaves a still-valid layout.
- **Hot-reload**: editing the file changes the rendered rect on next timer tick.

## Phasing

1. **Layout file + hot-reload.** Seed `ui_layout.json`; plugin reads layout on
   construct; wells return override-or-default; timer mtime reload. (The
   foundation manual edits and Claude edits both write to.)
2. **Manual edit mode (the headline), Figma-grade.** In-plugin toggle with the
   Figma interaction vocabulary: marquee + shift multi-select, drag (shift =
   axis lock), 8 resize handles (shift = aspect, alt = from center), arrow/
   shift-arrow nudge, smart guides + snapping (alt suppresses), measure-on-hover
   distance badges, typeable X/Y/W/H inspector, align/distribute, undo/redo,
   lock. `ValueTree`+`UndoManager` model, auto-writes JSON. This is the thing
   the user actually wanted — hands-on control that feels like Figma.
3. **Render + scene + validator (assist/verify).** `clean.png`, `overlay.png`,
   `scene.json`, `validation.json`; rule resolver. Powers snap geometry/hints
   for edit mode and lets Claude see and verify.
4. **AI layout *suggestions*.** Propose rects/rule-fixes, gated by user accept —
   never auto-restyle curated art.

(Note: a thin render-to-PNG can be built alongside phase 1 if Claude needs to
verify the layout before edit mode exists; the full scene/validator engine is
phase 3.)

### Later (earns its place after the spine renders)

Not rejected — deferred until the render→scene→validate loop exists and reveals
what is actually missing. Building these first is premature abstraction:

- persistent render daemon (vs per-call harness)
- candidate generation: N variants scored + contact sheet
- operation log with actor/reason, blame, replay, "back to last good"
- full multi-state render matrix (hover/drag/open/disabled/long-text)
- zoom/magnify, pixel-grid toggle, copy/paste position (edit-mode nice-to-haves)

## Definition of done (v1 = phases 1–2: layout file + manual edit mode)

- [ ] `ui_layout.json` schema (elements + optional groups/rules) + seed matching
      current hardcoded defaults
- [ ] Plugin reads layout; absent/malformed → exact current behavior
- [ ] Plugin runtime ignores groups/rules (reads rect + style only)
- [ ] Well functions return override-or-default
- [ ] Hot-reload via timer mtime check
- [ ] In-plugin edit-mode toggle (dev/author-gated; off in shipped builds)
- [ ] Selection: click, click-empty deselect, shift multi-select, marquee
- [ ] Move: drag, shift axis-lock, arrow 1px / shift-arrow 10px
- [ ] Resize: 8 handles, shift aspect-lock, alt from-center
- [ ] Smart guides + snapping to siblings/panel center; alt suppresses snapping
- [ ] Measure-on-hover distance badges
- [ ] Properties inspector: typeable X/Y/W/H + readout font/colour
- [ ] Align/distribute on multi-selection (maps to rule effects)
- [ ] Undo/redo via `ValueTree`+`UndoManager`
- [ ] Lock an element
- [ ] Every committed move auto-writes `ui_layout.json` (debounced)
- [ ] Audio/wheels keep running while edit mode is active
- [ ] Tests: parse, well lookup, seed round-trip, hot-reload, edit-mode write,
      undo/redo round-trip
- [ ] Quitting/reopening restores the edited layout

## Definition of done (phase 3: render + scene + validator)

- [ ] `getUiDebugTree()` accessor on the editor
- [ ] Render tool emits `clean.png`, `overlay.png`, `scene.json`,
      `validation.json`, `last.png`
- [ ] Validator catches overlap, off-canvas, missing/malformed rect, text clip,
      curated-art-hash change, and rule violations
- [ ] Rule resolver applies a rule and writes a still-valid layout
- [ ] Snap guides in edit mode use the same geometry as the validator
- [ ] Before/after diff = image diff + semantic rect diff
- [ ] Tests: parse, well lookup, seed round-trip, scene output, validator,
      resolver, hot-reload
- [ ] Claude can patch → render → read PNG + scene.json + validation.json →
      state whether the change passed
