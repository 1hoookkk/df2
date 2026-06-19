# See Your Plugin — TRENCH UI layout loop + signal schematic — design

Date: 2026-06-19
Status: approved (brainstorming)

North star:

> **See Your Plugin makes TRENCH transparent: Arrange shows where the interface
> lives; Inspect shows where the sound goes. Both are live, exact, and editable
> only where editing is truthful.**

The doctrine under it is not "AI edits the plugin" — it is **the plugin exposes
itself**, so Claude operates on visible, structured truth instead of guessing.
Three modes of one environment:

- **Play** — normal use: move Morph/Q, hear it.
- **Arrange** — dev/author mode: grab UI elements in the real plugin, fix layout
  by hand, no rebuild. The headline v1.
- **Inspect** — a live, transparent signal *schematic* (not a node editor): see
  the actual DSP path stage by stage, with drill-down to the real values.

Both authored views ride on values and rendering that already exist (see Reuse
ledger), per the engineering doctrine.

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
- A node *editor* / freeform DSP patcher. Inspect is a fixed-structure
  schematic of the real chain; it never lets the user rewire the DSP or imply a
  wiring that isn't real. (This is not Max/MSP.)

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

### 4a. UX doctrine — hide complexity behind simple interactions (the iPhone test)

Figma-grade describes the *capability*. This doctrine governs the *surface*. The
test: someone who has never seen it should be able to fix their layout in ten
seconds without instruction. All the machinery (snapping geometry, rules,
validator, `ValueTree`, JSON) stays invisible.

Rules of the surface:

- **One gesture in, no manual out.** Entering edit mode is a single chord; the
  panel gently lifts to show that things are grabbable. There is no Save button,
  ever — it is always saved.
- **The whole tutorial is "drag."** Default interaction is grab-and-move. That
  is all a first-time user must know. Everything else is discovered, not taught.
- **It aligns *for* you.** No align/distribute toolbar. Snapping is on by
  default and is the star: drag near alignment and it clicks into place with a
  guide line. You never push an "align" button — the thing *wants* to be tidy.
  (The `rules` engine drives this automatically; it is never shown as UI.)
- **Numbers on touch, then gone.** No permanent inspector panel. The X/Y/W/H and
  the distance-to-neighbor badges **float next to the element only while you are
  dragging/holding it**, then disappear. Want an exact value? Tap the floating
  number to type it. Progressive disclosure — clutter appears only on demand.
- **Affordances only on the selected thing.** Resize handles show on the
  selected element only, subtle; nothing is always-on chrome.
- **Forgiving and unbreakable.** Undo is silent insurance (Cmd/Ctrl+Z), no
  visible chrome. You cannot corrupt the layout; bad states fall back to last
  good.
- **Quiet defaults, depth on reach.** Power (multi-select, lock, type-exact,
  match-size) exists but never crowds the surface — it surfaces when the user
  reaches toward it (e.g. shift-click reveals multi-select; long-press reveals
  lock), not as buttons competing for attention.

### 4b. The engine the simple gestures ride on

These are the full-capability behaviors. Each is exposed through a simple gesture
above, not its own control. Adopt the ones that fit a fixed 360×560 panel of ~5
elements; drop the ones that don't.

- **Selection** — click select, click-empty deselect, shift-click multi-select,
  marquee drag. (Surface: just click and drag.)
- **Move** — drag; arrow 1 px, shift+arrow 10 px; shift-drag axis-lock.
- **Resize** — 8 handles; shift aspect-lock; alt from-center. (Surface: handles
  appear only when selected.)
- **Smart guides + snapping** — alignment lines vs siblings/panel center; snap;
  alt suppresses for by-eye. (Surface: automatic; this *is* "align for you.")
- **Measure** — px distance badges to neighbors/edges. (Surface: float on
  drag/hold, then vanish.)
- **Type-exact** — source-space X/Y/W/H + readout font/colour. (Surface: tap a
  floating number to edit; no standing panel.)
- **Align/distribute** — maps to `rules` (`sameX`, `sameWidth`, `centerY`, …).
  (Surface: happens via snapping; an explicit "tidy these" only on reach.)
- **Undo/redo** — `UndoManager`. (Surface: invisible, Cmd/Ctrl+Z.)
- **Lock** — protect a placed element. (Surface: on reach, e.g. long-press.)

**Nice-to-have (if cheap, not gating):** zoom/magnify, copy/paste position,
faint pixel-grid toggle.

**Explicitly out (don't apply here):** adding/removing/duplicating elements;
components/variants, auto-layout, vector editing, pages, comments, multiplayer;
restyling curated panel artwork.

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

## Engineering doctrine (lazy senior engineer + Rossum verbatim)

- **Reuse before build.** The best code is the code not written. Find the
  canonical owner and call it; extend what exists before authoring anew.
- **Verbatim, not re-derived (Rossum).** Do not recompute what the engine already
  computes. Read live values; prefer cheap closed-form math (quadratic pole
  roots, closed-form biquad magnitude) over pulling in machinery.
- **Never duplicate the packed math.** The packed-16 decode / `lerp_u16` /
  morph-first interpolation is the documented "can of worms" with a single
  canonical owner (`trench-core`). The schematic and tools call it
  (`trench_engine_get_coeffs`, `trench_packed_probe`, forge-web `packed.js`) and
  never reimplement it. See memory `find-duplicate-functions`.
- **Minimal but complete.** Write only what the task needs — and never cut
  validation, error handling, security, or accessibility. The code is small
  because it is necessary, not because it is golfed.

## Reuse ledger (what already exists — verified by exploration)

Live DSP values, read verbatim (no recompute):

| Need | Call / read | Where |
|------|-------------|-------|
| 6 stages' live DF2T coeffs + output gain, per frame, lock-free | `TrenchDspBridge::getSmoothedCoeffsForUI` → `trench_engine_get_coeffs` | `juce-shell/source/dsp/TrenchDspBridge.h:100`; `trench-core/src/ffi.rs:465` |
| stability margin ρ per stage | `pole_radius(a1,a2)` (8-line closed form) or `trench_packed_probe` | `trench-core/src/minifloat.rs:309`; `ffi.rs:255` |
| per-stage / cascade magnitude curve | closed-form biquad magnitude from the live coeffs | math of `trench-core/src/response.rs:229` (reimplement only the cheap formula, not the packed path) |
| live Morph / Secondary | `PluginProcessor::smoothedMorph` / `smoothedQ` | `juce-shell/source/PluginProcessor.h:118` |
| interpolated corners (authoring/tools only) | `trench_packed_interpolate` | `trench-core/src/ffi.rs:213` |

Rendering primitives, reuse (web / forge-web):

| Need | Reuse | Where |
|------|-------|-------|
| dB-vs-log-Hz response curve | `drawResp` / `drawResponsePath` | `forge-web/build_bench.py` (bench.html); `forge-web/js/forge.js:591` |
| z-plane poles/zeros, stability rings | `drawZ` | bench.html template |
| Morph×Q heatmap / grid | `drawField` / `drawGrid` | `forge-web/js/forge.js:614`; bench.html |
| freq↔pixel mapping, dB↔pixel | `fx/fy/xToF/yToDb` | `forge-web/js/forge.js:41` |
| packed body → dB codec (WASM, same trench-core) | `packed.js` + `forge-web/wasm` | `forge-web/js/packed.js` |
| stage / corner color identity | existing palettes | `forge.js`; `forge-gpu-painter/src/painter/theme.rs` |
| play a body through the real engine | `forge-worklet.js` | `forge-web/js/forge-worklet.js` |

New code, genuinely (nothing to reuse): the **node-graph / signal-flow layout
layer** itself, and the **in-plugin layout edit mode**.

## Inspect view — live signal schematic

The second view of "See Your Plugin": a node-based diagram of the actual TRENCH
signal chain, governed by the transparency doctrine (entirely transparent, no
black boxes; cleverly abstracted, not dumbed down).

Nodes (the real chain): `[Morph]` + `[Secondary/Q]` → `[packed interp over 4
corners C0..C3]` → `Stage 1 … Stage 6` (serial DF2T biquads) → `out`; audio in
feeds Stage 1.

**It is a schematic, not a node editor.** Fixed structure first: it shows the
real, mostly-fixed chain — "here is the signal chain you are hearing" — never
"build/rewire your own." No freeform draggable nodes, no implying the DSP is
wired differently than it is. (Visual rearrangement of an unchanged graph is a
possible far-later nicety; rewiring DSP is out, full stop.)

Behavior:

- **Read-only over verbatim values.** It displays the live coeffs / ρ / curves
  from the reuse ledger. It does not author or recompute the packed math.
- **Progressive technical transparency.** Three depths, truth staged not removed:
  1. plain language from measured values — e.g. "Stage 3 boosts ~2.4 kHz by
     ~6 dB vs the previous stage" (the Hz/dB come from the actual curve, never
     invented).
  2. one click → that stage's response curve (before/after contribution),
     poles/zeros on the z-plane (reused `drawZ`), ρ stability margin.
  3. one click deeper → raw `b0 b1 b2 a1 a2`.
  The non-technical user is never blocked by coefficients; the coefficients are
  never removed.
- **Track the signal (cumulative).** Tap input → incoming signal; tap Stage 1 →
  the result *after* Stage 1; Stage 2 → cumulative after Stage 2; … output →
  final. A final curve says *what* happened; this says **where** it happened.
- **Live.** The graph moves as the plugin moves: changing Morph/Secondary updates
  the corner blend, stage curves, and output — "looking inside the instrument
  while you play it."
- **Evidence first, language second (CLAUDE.md contract).** Every visual is
  source-backed; Claude may *translate* ("that ~2.4 kHz bump is the bite you
  hear") but never asserts unmeasured claims. OBSERVED before INFERRED; no
  invented Hz/dB.

Truth-source map (no visual invents a value):

| Visual | Truth source (canonical, verbatim) |
|--------|-----------------------------------|
| stage coefficients | live engine coeffs (`trench_engine_get_coeffs`) |
| Morph / Secondary | live smoothed params |
| corner blend | canonical packed interpolation |
| stability ρ | canonical pole-radius / probe |
| stage response curve | closed-form biquad magnitude from live coeffs |
| cascade response | product of the actual stage responses |

Home: **extend `forge-web/bench`** (reuses every rendering primitive above and
runs the same trench-core via WASM = verbatim-accurate). Only the node-graph
layer is new. Porting the proven view in-plugin (for live-in-DAW) is a later
step, using the same FFI values already mapped — not paid for until the cheap
version proves the design. Unified "See Your Plugin" is the north star, not a v1
constraint.

This view is **separate from the layout-designer v1** and gets its own
phase/plan; it is specified here so the two views share one doctrine and one
reuse ledger.

## Accessibility (not cut — applies to both views)

- Edit mode fully **keyboard-operable**: select, nudge (arrows/shift-arrows),
  type-exact entry, undo — not mouse-only.
- **Color is never the only signal**: stages/corners carry text labels and shape,
  not just hue (color-blind safe); selection shown by outline, not color alone.
- Readable contrast for floating numbers/badges; focus is visible.
- Screen-reader names for controls where JUCE accessibility supports it.

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
2. **Manual edit mode (the headline) — simple surface, Figma engine.** One chord
   in, no save button. The whole tutorial is "drag"; it snaps itself into
   alignment; numbers float on touch and vanish; handles show only on the
   selected element; undo is silent. Underneath: marquee/shift multi-select,
   axis-lock drag, 8-handle resize (aspect/from-center), nudge, smart guides +
   snapping, measure badges, type-exact, align via rules, lock, all on a
   `ValueTree`+`UndoManager` model auto-writing JSON. Hands-on control that
   feels obvious (iPhone test) with Figma power on reach.
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
- [ ] In-plugin edit-mode toggle (one chord; dev/author-gated; off in shipped)
- [ ] No save button — every committed move auto-writes `ui_layout.json`
- [ ] iPhone test: drag-and-it-snaps works with zero instruction
- [ ] Snapping on by default; clicks into sibling/panel-center alignment with a
      guide line (this is "align for you" — no align toolbar); alt suppresses
- [ ] Numbers (X/Y/W/H + distance badges) float on drag/hold, vanish on release
- [ ] Tap a floating number to type an exact value (no standing inspector panel)
- [ ] Resize handles appear only on the selected element
- [ ] Underneath: shift multi-select + marquee, axis-lock drag, 8-handle resize
      (aspect/from-center), arrow 1px / shift-arrow 10px, lock on reach
- [ ] Undo/redo silent via `ValueTree`+`UndoManager` (Cmd/Ctrl+Z)
- [ ] Audio/wheels keep running while edit mode is active
- [ ] Edit mode fully keyboard-operable; color never the sole signal
- [ ] Malformed/partial layout writes never corrupt state (atomic write +
      last-good fallback)
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

## Definition of done (Inspect view — live signal schematic, own plan)

- [ ] Node graph of the real chain (Morph/Q → interp(4 corners) → 6 stages → out)
- [ ] Built by extending `forge-web/bench`; reuses curve/z-plane/heatmap/codec
- [ ] Reads live coeffs/ρ verbatim; reimplements no packed math (calls canonical)
- [ ] Click a stage → real poles/zeros + `b0..b2,a1,a2` + stage curve + ρ
- [ ] Click interp node → 4 corners + (Morph,Secondary) blend shown
- [ ] Track-the-signal: magnitude after each stage
- [ ] Numbers hidden by default, one click away (transparent, not dumbed down)
- [ ] Keyboard-operable; color never the sole signal
- [ ] Handles malformed/short body bytes without throwing (validate to 240)
