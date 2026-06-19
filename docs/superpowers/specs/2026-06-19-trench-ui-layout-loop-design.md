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

Close the loop between editing UI layout and seeing the result:

1. **Render-to-PNG** — render the actual plugin editor to an image Claude can
   look at after every change, and verify placement against intent.
2. **Hot-reloaded layout** — positions/sizes (and a small set of style props)
   of the existing controls live in a `ui_layout.json` that the plugin reads
   at runtime and reloads when it changes. Moving a control = edit a number +
   reload, no rebuild.
3. **Drag-correct (phase 2)** — the user grabs the one control that's still
   slightly off and nudges it; the nudge writes back to the same JSON.

The render-to-PNG loop is built **first** — it is the capability that has been
missing.

## Design principle: ultra-efficient collab surface

This is a collaboration tool between the user and Claude, not a one-way editor.
Every design choice is judged by how tight it makes the user↔Claude loop:

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
  of truth. Drag-correct, when built, lives in-plugin.

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
- Unknown ids are ignored. Missing ids fall back to the C++ default.
- A missing or malformed file means the plugin uses **today's hardcoded values
  exactly** — shipped behavior is unchanged until the user opts in.

A seed `ui_layout.json` containing the current defaults is generated so the
designer/render tool and the plugin agree on pixel one.

### 2. Render tool (built first)

A small harness that constructs `PluginProcessor` + `PluginEditor`, renders the
editor into a `juce::Image`, and writes a PNG. Driven by a script Claude can run
after any layout change.

- Reads the same `ui_layout.json` the plugin reads, so the PNG reflects the live
  layout.
- Output: a deterministic PNG at the true editor size (360×560) that Claude
  inspects with the Read tool to verify placement.
- **Labeled overlay mode** (flag): renders a second PNG with each element's
  `id` and rect drawn on a faint outline of its bounds. This is the shared
  vocabulary surface for the collab loop — both sides reference controls by id.
- **Before/after**: the tool preserves the previous render (e.g.
  `last.png`) so a change can be shown as a visible diff.
- Preferred form: an offscreen render (construct editor, `paintEntireComponent`
  into an `Image`, write PNG) so no DAW/standalone window is needed. If
  offscreen proves impractical in JUCE, fall back to launching
  `TrenchStandaloneApp` and screenshotting — but offscreen is the target.
- Behavior is read-only: it never writes the layout, only renders it.

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

### Data flow

```
Claude edits ui_layout.json  ─┐
                              ├─► render tool ─► PNG ─► Claude verifies ─► (loop)
plugin Timer sees mtime change┘                                         │
   └─► re-reads layout ─► wells return new rects ─► repaint ◄───────────┘
(phase 2) user drag-corrects in-plugin ─► writes ui_layout.json ─► same loop
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
- **Hot-reload**: editing the file changes the rendered rect on next timer tick.

## Phasing

1. **Render-to-PNG** + seed `ui_layout.json` + plugin reads layout on
   construct. (The missing capability — Claude can see and self-correct.)
2. **Hot-reload** on timer mtime check.
3. **Drag-correct** in-plugin edit mode writing back to the JSON.
4. (Later, optional) AI layout *suggestions*, gated by user accept — never
   auto-restyle.

## Definition of done (v1 = phases 1–2)

- [ ] `ui_layout.json` schema + seed file matching current hardcoded defaults
- [ ] Plugin reads layout; absent/malformed → exact current behavior
- [ ] Well functions return override-or-default
- [ ] Hot-reload via timer mtime check
- [ ] Render tool emits a 360×560 PNG from the live layout
- [ ] Render tool has a labeled-overlay mode (id + rect per control)
- [ ] Tests: parse, well lookup, seed round-trip, hot-reload, render output
- [ ] Claude can run the render tool and read the PNG to verify placement
