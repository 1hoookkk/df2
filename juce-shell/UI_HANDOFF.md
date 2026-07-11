# TRENCH UI — Handoff for autonomous continuation

> Hand this to the next agent. The DSP and the current SEED/TAKE workflow are **real and
> build-verified**. This handoff is ONLY the **visual/UI/product model** of the JUCE editor.
> The operator is the sole acceptance test — judge by eye on real screenshots, iterate fast.

## Mission
Make the TRENCH plugin UI genuinely good: **bold, confident, coherent, free of AI slop.**
Currently it reads amateur. Custom canvas painting only — **no generic JUCE LookAndFeel
defaults, no generic "dark mode", no weak/muddy gradients.**

## The product (context)
TRENCH = a Z-plane morphing **body filter** (E-mu lineage; Rust `trench-core` DSP, JUCE 8 UI).
Faceplate behaviors: **TYPE** (pick a body) · **MORPH** (morph axis) · **Q** (pressure/secondary) ·
**MOVE** (one curated performance verb, mainly Morph motion) · **SEED** (deal a related recipe/sibling) ·
**TAKE** (drag/capture what was actually heard). Pitch: "choose the body, perform Morph/Q, deal takes."

## Product model lock (2026-07-08)
Tyson corrected the model with the Emulator X3 reference. The right product is:

**Emulator X3's filter page, possessed by a highly opinionated recipe engine.**

Do **not** redesign the hierarchy into a modern macro workstation. Preserve the X3 skeleton:
- TYPE at top.
- hero response screen.
- MORPH roller + numeric readout.
- Q roller + numeric readout.

MORPH + Q are sacred. Q is not a minor trim, not something to demote, and not a spare slot for
MOVE/SEED/TAKE. The cream readout boxes are instrument meters; keep them numeric except for brief
feedback flashes that immediately return to value truth.

The new model lives around the skeleton:
- **MOVE**: small state chip/list, one authored verb, no matrix. V1 truth: MOVE performs MORPH.
- **USER**: alt-drag MORPH teaches the only custom gesture.
- **SEED**: final intent is "deal me a related performance recipe from this TYPE" - sibling body plus
  bounded MORPH/Q point, MOVE/timing/envelope, AMOUNT/SLAM taste, maybe rare 5D. It must feel authored
  and family-related, not random FX.
- **TAKE**: commit the thing just heard; drag/capture, no recorder page or export dialog.

Commercial loop: **TYPE -> MORPH/Q -> MOVE -> SEED until it knocks -> TAKE -> SEED -> TAKE**.
Every visible verb must do something audible or visibly honest immediately. If two choices sound the
same, fix one or kill one.

## HARD RULES
- **LOCKED — never touch:** (1) the faceplate art `juce-shell/assets/ui/df2_panel_shadow.png`
  (RGB, baked dark wells, **no alpha**); (2) the **rollers** (thumbwheel filmstrips). Finished assets.
- **KEEP as-is conceptually:** the **numeric readouts**, the **TYPE selection** paradigm, and the
  MORPH/Q two-roller X3 structure.
- **REMAKE (your job):** the screen/display, the header text, the dropdown rendering
  (custom-paint — NO generic JUCE popup), the accent/colour treatment, labels — everything not locked/kept.

## Reference: the real Emulator X3 panel  ← OPERATOR WILL ATTACH THIS SCREENSHOT
It shows TYPE ("Talking Hedz"), the teal log-grid display, two **horizontal** MORPH/Q thumbwheels,
white readouts. **It is the reference for STRUCTURE + RESTRAINT only** — the type selector, white
readouts, log-grid display, horizontal thumbwheels. **Do NOT copy its brushed-metal skin** — we
have our own locked faceplate and our own aesthetic.

Critical interpretation: the X3 reference proves the product hierarchy. Do not "improve" it by making
Q secondary, moving MOVE into the readouts, or replacing the two rollers with a recipe/action row.
SEED and TAKE should become official small soft keys around this skeleton, not a new hierarchy.

## THE THUMBWHEEL — read this; it has blocked every AI (incl. Gemini, Codex) for a year
- It is a **HORIZONTAL roller.** You spin it **LEFT↔RIGHT** and see only its **front face.** The
  rib/window pattern **phase-shifts horizontally** under **fixed** grey material light. An internal
  **cyan emitter** travels horizontally **behind the mask, visible only through the rib openings**
  (short hot bead + uneven trail — **never** a straight line, dot-row, or bead chain). The glow
  **grows/moves as the value goes up.**
- It is **NOT** a vertical spinning drum, **NOT** a 3D cylinder/barrel, **NOT** a 360 spin.
  **Treat it as a 2D phase-shift sprite — never a 3D object.**
- *Why every AI gets it wrong:* "thumbwheel/synth" primes a vertical mod wheel; ~zero training data
  for this obscure object; image→3D (Trellis) reconstructs a ribbed strip as a cylinder and bakes the
  spin in. Don't fall in.
- Filmstrip facts: 129 frames; frame 0 == frame 128 (byte-identical, no glow). Frames have **invisible
  transparent padding** → measure each frame's real opaque content bounds and **seat the roller FLUSH
  in the well**; don't just blit the frame rect.
- Wheels want a subtle **half-oval edge shadow** for depth (study the X3 wheel shadows; if you can't
  render it cleanly, leave it).
- **Study these** (operator pointed here): `df2/dev/tmp/thumbwheel_blender/` (iterations, frames,
  strips, `.blend`s, and the failure docs `CODEX_FAILURE_REPORT_2026-06-15.md`,
  `GEMINI_THUMBWHEEL_FAILURE_HANDOFF_2026-06-14.md`); `juce-shell/tools/thumbwheel/`
  (`thumbwheel_spec.md`, `thumbwheel_geometry_spec.json`, the struggle/handoff docs). The **accepted
  direction** was `gemini_handoff_bitmaps/frame_base_frosted_clean.png` (frosted grey body) + a **2D
  raster teal glow wash** (NOT Blender glow geometry, NOT beads).

## Ground-truth measurements (the wells)
Faceplate is **1024×1591 "source space"**, mapped to the **360×560** editor by
`Theme::sourceRectToEditor`. Wells measured to-the-edge from the baked dark cutouts (lum<70) and
locked in `UiLayout::defaults()` (source space x,y,w,h):
- screen `116,245,799,384` · TYPE `223,137,687,79` · MORPH wheel `118,684,436,114` ·
  Q wheel `118,864,436,112` · MORPH readout `601,709,173,82` · Q readout `601,887,174,82`.
A control **fills the dark recess; the faceplate's bevel just outside it stays as the edge.**

## Aesthetic direction (operator's)
- **60:30:10, bold + confident.** 60% = the warm **brown faceplate** (locked, dominant). 30% = the
  **screen** = the **REAL emu log grid** (authentic log spacing — operator insists on the real grid,
  recolored, **not procedural**) rendered as a **warm, desaturated, GREEN-PHOSPHOR LCD** (lit/light,
  like a backlit display — **NOT a dark OLED, NOT cold teal**). Target: `df2/dev/tmp/emu_grid_measure/
  measured_with_emu_log_grid_green_phosphor.png`. 10% = a bold accent (lime/phosphor-green curve;
  amber for interactive states).
- Response curve = phosphor/lime green; it **must FIT the screen** (dB window is ±40 because real peaks
  hit +39 dB — keep it fitting, no through-the-roof clamp).
- **Top header** currently "Z-PLANE SYNTHESIS FILTER" (tiny centered caps) = **bad/placeholder.**
  Replace with a confident **TRENCH wordmark** (the one bold typographic moment). It's a drawn overlay
  (the faceplate's baked title is masked + redrawn), editable without touching the locked panel.
- **Dropdowns:** fully custom-painted (the TYPE ComboBox popup must NOT look like generic JUCE).
- **Q control:** add a subtle outline/affordance hinting it's clickable.

## Code map (`juce-shell/source/`)
- `PluginEditor.{h,cpp}` — wires views; `layoutComponents()` positions via `theme.rect(id)`; VBlank
  live updates; + a (dead-ish) diagnostics bridge.
- `PluginProcessor.{h,cpp}` — params→dsp→roster; `seedCurrentBody()`/`exportCurrentBody()`; tracks
  `currentBodyBytes`.
- `UiLayout.h` — baked geometry/colour/param tokens (`defaults()`) + `fromJson()` (dead tool).
- `ui/Theme.h` — token accessors + `sourceRectToEditor` + `drawWell`/`drawAliasedText`.
- `ui/GraphDisplay.h` — the screen (rewritten: draws the green grid bitmap + lime curve).
- `ui/WheelControl.h` — roller filmstrip control (asset locked; the draw/flush logic is yours to fix).
- `ui/FaceplateView.h` — draws the locked panel + masks the baked title.
- `ui/TypeSelectorView.h` — TYPE ComboBox only; old action callbacks are unused/dead plumbing.
- `ui/MoveChip.h` — current MOVE chip/list; keep it small and curated, not a modulation matrix.
- `ui/SeedButton.h`, `ui/TakeButton.h` — current SEED/TAKE hardware buttons.
- `ui/ValueReadout.h` (white readouts — KEEP), `ui/LabelsLayer.h` (text overlay incl. the header),
  `ui/DecalsLayer.h`.

## Architecture notes (honest)
- Component layer is **good** (lock-free coeff seqlock, VBlank, proper `ParameterAttachment`) — keep it.
- **Cruft:** the "See Your Plugin" layout bridge (`UiLayout::fromJson` + `Documents/TRENCH/ui_layout.json`
  hot-reload + a `render.jpg` writer in PluginEditor, gated by `TRENCH_PLAYER_DIAGNOSTICS`) is dead
  tooling — the vector a prior agent used to wreck the layout. **No live `ui_layout.json` exists**, so
  `defaults()` IS what runs. `runtime_layout.json` is a dead leftover. Recommend: make `defaults()` the
  single source of truth, delete the bridge. The 1024×1591→360×560 indirection is over-engineered for a
  fixed-size plugin (consider authoring in editor space).

## Build + screenshot loop (the ONLY acceptance test = the operator's eye)
- Build: `pwsh juce-shell/build-standalone.ps1` (Ninja/MSVC; dev standalone = `TRENCH_PLAYER_DIAGNOSTICS=ON`).
  Output: `juce-shell/build-ninja/TRENCH_artefacts/Release/Standalone/TRENCH.exe`. Assets bake into
  BinaryData at build → **rebuild to see asset changes.** Kill any running `TRENCH` first.
- Gotcha: `LNK1104: cannot open TRENCH_SharedCode.lib` = transient file lock → kill `TRENCH.exe` + retry.
- Screenshot: the window opens **behind** others → use **PrintWindow** (`SetWindowPos` HWND_TOPMOST,
  then `PrintWindow(hwnd, hdc, 2)` = PW_RENDERFULLCONTENT). Do NOT use CopyFromScreen.
- Always crop+zoom the region you changed — controls are tiny at 362×562.

## Current state (changed this session — revert freely)
- `GraphDisplay.h`: green-phosphor grid bitmap + bold lime curve; plot dB window ±40, clips clean.
- `UiLayout.h`: wells re-measured + locked (above); `curveDbTop/Bottom = 40/-40`.
- `assets/ui/display_log_grid.png` recolored teal→green-phosphor. Backups in `juce-shell/_asset_backups/`
  (`display_log_grid_teal.png`, `display_log_grid_prephosphor.png`).
- DSP / current SEED / TAKE paths are real. Latest hardening: `seedCurrentBody()` returns success, and
  SEED pulse/chip feedback only fires after a certified sibling is actually staged.

## Open punch list
1. **Make SEED/TAKE feel official** without breaking the X3 skeleton. They are small soft keys, not grey utility pills.
2. **Fix or kill duplicate CHOP.** `CHOP 1/16` and `CHOP 1/32` cannot sound identical in an opinionated verb list.
3. **SEED recipe model.** Current seed mutates a certified body; final SEED should deal a bounded related recipe.
4. **Live verify** MOVE popup, USER alt-drag, SEED pulse, TAKE drag in the real standalone by hand.
5. **Top → TRENCH wordmark** if still unresolved in the current build.
6. **Custom-paint the dropdowns** if the current popup regresses to generic JUCE.

## Operating principles
Bold over timid; intentional over templated. Judge by eye on real screenshots; iterate in fast loops;
don't over-detail; never declare it done from a contact sheet. Operator's stated dislikes: generic dark,
AI slop, weak gradients, templated centered-caps headers, anything that "looks amateur."
