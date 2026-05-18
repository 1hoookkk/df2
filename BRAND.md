# BRAND.md — Trenchwork / df2

The single source of truth for everything visual, verbal, and experiential
across the project. Brand and UI are not separated here, because they are
the same decision: the chassis color is the brand and the brand is the
chassis. If a design question has a visual answer, look here first.

---

## 0. North star

> **df2 is a flat institutional-green computational instrument:**
> **dead chassis, live math.**

This sentence governs every decision in this document. When a proposed
element makes the chassis feel less dead-flat, or makes the math feel less
alive, it is wrong.

The discipline behind it is: **vague on purpose.** No tooltips, no
onboarding, no feature lists, no documentation for outsiders, no public
Discord, no FAQ. Clarity is reserved for *function* and *transaction* —
the plugin works, the audio is good, purchases work, cartridges load.
*Meaning* and *context* stay vague. Trust is built through audio quality
and aesthetic consistency, not through documentation.

---

## 1. Names

| Name              | Role                          | Status                       |
|-------------------|-------------------------------|------------------------------|
| **Trenchwork**    | Maker (the company brand)     | Public; the umbrella         |
| **df2**           | The plugin product            | Public; ships commercially   |
| **Filter Factory**| The private authoring tool    | Never released; visible only in short-form content |
| **1hook**         | Music producer identity       | Separate brand; releases only |
| **Speaker Knockerz** | Body 1 — bass / cone        | Ships in df2 v1              |
| **Aluminum Siding**  | Body 2 — mid-scoop / metallic | Ships in df2 v1            |
| **Small Talk**       | Body 3 — vocal / formant    | Ships in df2 v1              |
| **Cul-De-Sac**       | Body 4 — comb / enclosure   | Ships in df2 v1              |

### Naming principles for future bodies

A body name must be:

- **A concrete noun** (person, place, thing, or moment) — never an
  adjective, never a description of audio behavior
- **Structurally honest** — the thing the name evokes shares structure
  with the filter's sonic character
- **Culturally specific without being a quote** — evokes a register
  without name-dropping a specific work
- **Pronounceable in one breath** — survives in conversation and search
- **Visually distinct from the existing four** — different shape of
  name, not a parallel construction

Test the candidate name against: *would a producer remember this six
months after hearing it once?* If no, it's not a body name yet.

---

## 2. The single committed weird element

**Chassis color: flat muted institutional green.**

This is df2's signature. Not red, not amber, not black, not bone. Green.
Specifically the muted institutional green of old calibration equipment,
archive cabinets, industrial lab walls, forgotten government software.

```
Chassis primary:        #4A5348   (the institutional green substrate)
Chassis shadow:         #3F4943   (slightly darker for any subtle inset)
Chassis lift:           #525B50   (slightly lighter, used minimally)
```

These are the locked anchors. Pick whichever feels right within this
family, but the chassis must read as *green* immediately, even at
thumbnail size. **Never drift toward neutral grey, olive, military
green, or Xbox green.**

### What flat green means

- One solid color across the entire chassis substrate
- Very subtle procedural noise at most (to avoid banding at large flat regions)
- No gradients suggesting curved surfaces
- No baked lighting direction
- Generated in code; never a photographic or imported asset

### What flat green does NOT mean

- ❌ Weathered military green with scratches, paint chips, or rust
- ❌ Fake metal surface that happens to be green-painted
- ❌ Textured "industrial" surface
- ❌ Embossed bevels or recessed panels
- ❌ Fake screws, rivets, ventilation slots, military stencils
- ❌ Glow, bloom, or neon edge — the green is dead, not lit

The green is the color of the *software surface*, not the color of an
imagined physical chassis. Computational green, not material green.

### Do not add a second weird element

The green is *the* weird element. Not one of several. The discipline is
to commit to one bold choice and let everything else recede. **No
barcodes, stamps, hand-drawn marks, asymmetric cuts, fake labels, slab
serifs, or any other "distinctive flourish" added on top of the green.**

---

## 3. Palette

```
Chassis primary:        #4A5348    Main substrate
Chassis shadow:         #3F4943    Slight elevation
Chassis lift:           #525B50    Slight relief

Text primary:           #1A1F1B    Near-black with green undertone
Text dim:               #6E756C    Muted grey-green
Text faint:             #3E443E    Very dim (technical readouts only)

Curve background:       #0A0E0B    Dark green-tinted near-black
                                   (the "window" inside the chassis)

Body accent colors — drive the visualization region only:
  Speaker Knockerz:     #E04030    Deep saturated red
  Aluminum Siding:      #D8E0E8    Cool silver-white
  Small Talk:           #F4B440    Warm amber
  Cul-De-Sac:           #50D090    Cool green-blue
```

### Palette discipline

- The **chassis green** is the only chromatic element *outside* the
  visualization region
- The **body accent color** is the only chromatic element *inside* the
  visualization region
- Two contained color regions, one neutral text/structure palette
  holding them together
- Body color transitions on switch: ~600ms ease-in-out, per-channel
  RGB lerp across the visualization region only — the chassis green
  does not change

### 60:30:10 ratio

- **60% chassis green** (substrate dominates)
- **30% neutral text / inset region** (typography, dark visualization rectangle)
- **10% body color** (curve, fill, slider indicator, active body marker)

---

## 4. Typography

**Heavy, utility-coded, with character.** Not Geist, not Inter, not any
typeface that reads as "tech product" or "design system."

### Display typeface (locked candidates)

In order of preference:

1. **Söhne Breit** (Klim) — commercial, heavy, characterful
2. **Apfel Grotezk** (Collletttivo) — free, has weight and slight oddness
3. **Authentic Sans 90** (Authentic Studio) — free, utility-industrial
4. **Migra** (Pangram Pangram) — free for personal, serious
5. **Diatype Mono** (Dinamo) — commercial, mono with character

### Banned typefaces

Geist, Inter, Roboto, Open Sans, Montserrat, Manrope, Plus Jakarta Sans,
Onest, Space Grotesk, DM Sans, Helvetica, Arial, system-ui fonts, and any
"Display" variant of the above. These are the AI-default-font tells. The
moment any of them appears, the plugin reads as generic web UI.

### Sizing

- **Body name:** 24–28px, weight 700–800, characterful, sits as a label
  not a headline (do not let it dominate the curve)
- **Body index** ("013", "047"): 12px, weight 500, letter-spacing
  0.15em, uppercase, color text faint
- **Slider labels** ("MORPH", "CONE"): 14px, weight 600, letter-spacing
  0.12em, uppercase, color text primary
- **Body selector items:** 14–16px, weight 600, letter-spacing 0.05em,
  uppercase — text dim (inactive), text primary (active)
- **Footer mark "df2":** 18px, weight 700, no letter-spacing adjustment,
  lowercase, color text primary

### Implementation

- Web prototype: load via `@font-face` from a self-hosted file (do not
  rely on Google Fonts CDN — too easy for the wrong font to substitute)
- Production: bundle the variable font into the plugin binary; do not
  load at runtime
- All typography is black-on-green against the chassis, not white-on-dark
- Contrast is high, palette is restricted

---

## 5. Layout

Plugin window is **4:5 aspect ratio** (taller than wide). Fixed internal grid:

```
┌──────────────────────────────────────┐
│  speaker knockerz             013    │  ← header, ~6-8%
├──────────────────────────────────────┤
│ ┌──────────────────────────────────┐ │
│ │                                  │ │
│ │   [response curve on dark        │ │
│ │    inset region — the only       │ │  ← visualization, ~62-65%
│ │    live element in the plugin]   │ │
│ │                                  │ │
│ └──────────────────────────────────┘ │
├──────────────────────────────────────┤
│  MORPH    ▌▌▌▌▌▌▌█▌▌▌▌▌▌▌▌▌▌▌▌     │  ← controls, ~18%
│  CONE     ▌▌▌█▌▌▌▌▌▌▌▌▌▌▌▌▌▌▌▌     │
├──────────────────────────────────────┤
│  speaker knockerz  ●                 │  ← body list, ~8-10%
│  aluminum siding                     │     vertical, never pill row
│  small talk                          │
│  cul-de-sac                          │
├──────────────────────────────────────┤
│  df2                                 │  ← footer, ~3-4%
└──────────────────────────────────────┘
```

### One asymmetric move

Pick one and commit. Options:

- Body name as a vertical spine label on the left edge (rotated 90°),
  visualization takes full upper region without a header strip eating space
- Visualization weighted off-center to the right, body list on the left edge
- Slider labels offset to one side, controls extending asymmetrically

**Do not pile asymmetric moves.** One choice. Commit. Everything else
remains grid-aligned and predictable.

### Layout rules

- **No card framing.** No shadows under regions. No recessed wells, no
  beveled edges
- **No rounded corners on chassis panels.** Sharp 0px radius, or at most
  2px on the visualization region's edge
- The visualization region is a flat dark rectangle inset into the
  green chassis — a different color region, not a skeuomorphic recess
- Regions are separated by spacing and color contrast, not by visual chrome
- No uniform padding everywhere (the Tailwind-default tell)
- No equal-width column grids

---

## 6. The visualization (the live math)

The response curve of the current filter, rendered in real time as the
user adjusts Morph and Q. This is the **only live element in the plugin.**
The chassis is dead; the curve breathes.

### Components

**Background:** `#0A0E0B` — dark green-tinted near-black. A flat rectangle
inset into the chassis (geometric inset, not skeuomorphic recess).

**Log frequency grid:**
- 9 vertical lines at 50, 100, 250, 500, 1k, 2k, 4k, 8k, 16k Hz
- Lines at 100 / 1k / 10k slightly more visible (decade boundaries)
- All lines tinted with current body color at 6–8% opacity
- One horizontal reference at 0dB (vertical center) at 5% body color opacity
- **No labels, no numeric markings** — the grid is for spatial reference,
  not measurement

**Curve fill** (below the curve line):
- Gradient from body color at curve line (18% opacity) fading to
  body color at 0% opacity at the bottom edge

**Curve glow stack:**
- Outer halo: body color at 18% opacity, line width 10px, blurred
- Mid glow: body color at 40% opacity, line width 4px
- Core line: body color brightened (+30 to each RGB channel), line width
  1.8px, sharp

**Resonance peak bloom:**
- Local maxima above +4dB get a radial bloom: white center → body color
  → transparent
- Bloom intensity scales with peak height
- Bloom radius ~18px

**Operating point marker:**
- A small white dot (~2.5px diameter) with body-color glow halo (~14px)
- X position derives from Morph value
- Y position follows the curve at that x
- Travels along the curve as the user sweeps Morph

**Continuous breathing:**
- Micro-oscillation on Morph and Q values, amplitude ~0.5%, driven by a
  slow noise function (period ~1–2 seconds)
- The curve gently breathes even when the user isn't touching anything
- Easy to miss but makes the visualization feel alive
- In production: tied to actual audio passing through the filter via a
  lock-free ring buffer (see ARCHITECTURE.md), so the breathing responds
  to signal as well as to time

### Hard rules for the visualization

- **No axis labels** (no "20Hz", no "10dB", nothing numeric)
- **No legend, no tooltip on hover, no decorative elements**
- **No play/pause icon, no bypass indicator inside the visualization region**
- The curve is the entire content of the region

---

## 7. Controls

Two horizontal slider tracks. Stack vertically with ~20px gap. Both
controls have **visual weight** — these are not hairline web sliders.

### Slider track

- **Track height: 32px.** Substantial. The control occupies real space.
- Track is a flat darker region (`#3F4943` — chassis shadow color) inset
  into the green. Not a bevel. Not a shadow. Just a different-colored
  rectangle.
- No border-radius beyond 1px
- Track width: full available column width minus label gutter

### Slider fill

- Portion of the track from left to handle position is filled with body
  accent color at full saturation
- Solid color, no gradient
- Fill animates exactly with the handle (no easing — direct response)

### Slider handle

- **A vertical block: 8px wide × 28px tall** (sits inside the track height)
- Color: text primary (`#1A1F1B`, near-black)
- No drop shadow, no bevel, no border-radius beyond 1px
- On hover: handle widens to 10px, no color change
- On drag: handle widens to 10px, cursor becomes grabbing

The handle is a *solid black bar* on a *body-color fill* against a *dark
inset region* in a *green chassis*. Maximum clarity, minimum chrome.

### Label

- Left of the track, ~100px wide column
- Display typeface, 14px, weight 600, uppercase, letter-spacing 0.12em
- Color: text primary
- Vertically aligned to track center

### No numeric value readout

Producers operate by sound and visual feedback, not by number. This is a
deliberate differentiation from data-display UI conventions.

### The Q-axis label changes per body

| Body              | Q-axis label |
|-------------------|--------------|
| Speaker Knockerz  | CONE         |
| Aluminum Siding   | STRESS       |
| Small Talk        | CAVITY       |
| Cul-De-Sac        | COMB         |

These labels never get explained. Producers infer from listening.

---

## 8. Body selector

**Vertical text list**, not a horizontal pill row. Position: below the
controls, above the footer.

- Each body name on its own line
- Display typeface, 14–16px, weight 600
- **Inactive items:** text dim color (`#6E756C`)
- **Active item:** text primary (`#1A1F1B`) with a small filled circle (●)
  to the right in the body's accent color
- Items have ~6–8px vertical spacing
- Click switches body with the 600ms color transition

If more than 4–5 bodies exist (cartridges), the list scrolls vertically.
The active body stays visible. **No dropdown. No menu. No icons. No
thumbnails.** Just names in a vertical column.

---

## 9. The one orchestrated reveal

When the plugin first loads, run **one** sequence (~600ms total). After
that, only the visualization breathes — no hover bounces, no scattered
transitions, no micro-interactions elsewhere.

```
0ms:    plugin window appears (instant)
0–150:  chassis green fades in from slightly darker shade
150–300: typography fades in (body name, slider labels, footer mark)
300–500: visualization curve draws itself left-to-right, body color
         blooming as it traces
500–600: operating point marker appears at current Morph position
600+:    continuous breathing motion begins; static otherwise
```

This is the plugin's calling card. Producers will record their first
load for short-form content. Make it deliberate.

---

## 10. Interactions

### Slider drag
- Click anywhere on a track moves the handle to that position and begins drag
- Drag continues until mouse/touch release
- Pointer events (unified mouse + touch + pen) — not separate handlers
- Body color fill updates in real time
- Curve updates immediately (zero latency on parameter atomics; see
  ARCHITECTURE.md)

### Body switch
- Click any body name in the vertical list
- 600ms ease-in-out cross-fade: visualization region only
- Body color smoothly interpolates per-channel RGB
- Q-axis label updates (CONE → STRESS → CAVITY → COMB)
- Chassis stays green throughout

### Continuous render
- Visualization redraws every animation frame (requestAnimationFrame in
  web; wgpu render thread in production)
- Breathing micro-oscillation runs continuously
- Operating point marker updates every frame
- Audio ring buffer (lock-free) feeds recent samples into the breathing
  amplitude so the visualization responds to signal

---

## 11. Anti-patterns

### Typography bans (AI-slop tells)
Inter, Roboto, Open Sans, Montserrat, Poppins, Lato, Nunito, Geist,
Space Grotesk, DM Sans, Plus Jakarta, Manrope, Onest, Helvetica, Arial,
system-ui fonts, any "Display" variant of the above.

### Color bans
Purple-to-blue gradients, cyan/teal accents (the SaaS palette), Slack
purple, Discord blurple, sunset gradients, neon green on dark, "Y
Combinator orange," "Stripe purple-pink," pure white text `#FFFFFF`
(use `#E8E8EC` or lighter text-on-green), pure black backgrounds
`#000000` (use `#0A0E0B`).

### Visual element bans
Glassmorphism, neumorphism, gradient meshes, animated backgrounds,
particle systems as ambience, floating geometric shapes, aurora washes,
animated blob shapes, 3D rendered abstract objects, isometric illustrations.

### Layout bans
Card-on-page composition with shadows, pill components (rounded-full),
hairline borders with low opacity as primary structure, centered hero
composition, uniform 16/24/32px padding (the Tailwind-default tell),
equal-width column grids, sticky headers with backdrop-blur, "hero +
features + CTA" structure, dashboard card grids.

### Component bans
Circular slider handles with shadows, iOS-style toggle switches, generic
checkboxes with animations, dropdowns with chevrons, search bars with
magnifying-glass icons, notification bells, gear icons, hamburger menus,
avatar circles, loading spinners, skeleton states, tooltip popovers with
arrows, modal dialogs with backdrop dim, toast notifications.

### Effect bans
Default Material Design easing, Lottie animations, parallax scrolling,
scroll-triggered fade-ins, number-ticker counting animations, generic
hover states (scale 1.05, brightness 110%), bounce/wobble physics,
"pulse" animations on CTAs, confetti.

### Iconography bans
Lucide, Heroicons, Feather, Material Icons, Font Awesome, emoji as UI.
df2 uses no icons. Words and shapes only.

### Conceptual bans
Dark/light mode toggle, theme variants, decorative ARIA, microcopy
explaining UI ("Click here to morph"), onboarding tour overlays, empty
states with illustrations, error messages with "helpful" suggestions,
loading states that say "Loading…", version numbers visible in UI.

### Aesthetic register bans
Anything that reads as: SaaS product page, Figma design system showcase,
crypto/web3 app, fintech dashboard, productivity tool (Notion / Linear /
Things), developer tool (Vercel / Stripe Dashboard / Railway), portfolio
site.

### Chassis personality bans
**No barcodes, stamps, hand-drawn marks, asymmetric cuts, fake labels,
slab serifs, or other "weird element" added on top of the green.** The
green is the weird element. Adding more dilutes the discipline.

---

## 12. Voice

### Plugin UI
- No tooltips. No "what does this do" text. No onboarding.
- Body names are not described. Q-axis labels are not explained.
- Producers either understand or they don't. df2 filters its audience
  through opacity.

### Marketing
- No feature lists. No "12-stage DF2T biquad cascade with 4-corner
  bilinear interpolation" — that's the engineering, not the pitch.
- Short. Evocative. Assumes the reader is already in the world.
- "Four bodies. More coming." is a complete pitch for the right audience.

### Body and cartridge release copy
- A name. An audio demo. A price.
- No "we improved the high-frequency response in this release."
- If producers can hear the difference, they hear it. If they can't,
  the release wasn't for them.

### Talking about Trenchwork
- A name on a thing. Not explained as "a one-person indie plugin
  developer specializing in reverse-engineered filter algorithms."
- When pressed, the answer is short. The maker is visible enough to be
  human, vague enough to be interesting.

### Filter Factory in content
- Visible but never explained as a tool.
- Producers see a green workspace, hear something happening, infer.
- Never captioned "the tool I built." Never frame implies a release is
  coming.

### Default to no
- "Should we explain X?" → no
- "Should we add a description to Y?" → no
- "Should we have a FAQ for Z?" → no
- "Should we run an onboarding tour?" → no

If after six months something is genuinely confusing the *right*
audience, add one sentence. Never more.

---

## 13. Implementation framework (as of 2026)

### Production target (the plugin)

See `ARCHITECTURE.md` for full detail. In summary:

- **Rust core** (`trench-core`): all DSP, all rendering logic, lock-free
  parameter atomics, audio ring buffer
- **wgpu**: rendering via Metal on macOS, Vulkan/DX12 on Windows, Vulkan
  on Linux. Single cross-platform shader codebase.
- **JUCE C++ shell** (~5% of codebase): plugin format wrappers (VST3,
  AU, CLAP, AAX), DAW window lifecycle, parameter automation, FFI bridge
  to Rust via `cxx`

All assets generated in code — no PNG/JPG/SVG image files. The chassis
green is a solid color. The curve is rendered by shader. The typography
is bundled variable fonts.

### Web prototype (for iteration and Filter Factory's authoring surface)

- **HTML + Canvas2D** for the visualization (WebGPU has uneven support
  in Safari as of 2026; Canvas2D is universal and fast enough for one
  curve at 60fps)
- **Pointer events** for all interaction (not separate mouse/touch handlers)
- **CSS variables** for the palette so it's trivial to retune
- **No build step required.** Single HTML file, open in any browser.
- **Variable fonts** loaded via `@font-face` from a local file
- **`requestAnimationFrame`** for the render loop, with explicit timing
  control — do not use CSS transitions for the live elements

### What modern web tech makes possible (and what to ignore)

**Use:**
- Canvas2D's `globalCompositeOperation` for the glow stack
- `OffscreenCanvas` if performance demands it (probably not needed)
- `AudioWorklet` if the web tool needs to audition cartridges through
  the actual `trench-core` runtime (compile Rust to Wasm, host in worklet)
- `Pointer Events API` for unified input
- `ResizeObserver` for responsive canvas sizing

**Ignore:**
- React, Vue, Svelte, anything with a virtual DOM — overkill for one
  panel with two sliders and a vertical list
- Tailwind, CSS-in-JS, design systems — they all leak SaaS vocabulary
  into the output
- Web Components — not needed at this scale
- Animation libraries (Framer Motion, GSAP) — `requestAnimationFrame`
  + math is enough

The principle: **the tech serves the design.** Pick the smallest stack
that renders the spec faithfully. Every framework you adopt smuggles in
its own defaults, and df2's defaults are explicitly contrary to most
framework defaults.

### Performance targets

- Visualization at 60fps minimum, 120fps preferred where the display
  supports it
- Resolution-independent: render correctly at 100%, 150%, 200% scaling
- Plugin startup to "first curve drawn" under 100ms
- Parameter change to visible response under 16ms (one frame at 60fps)

---

## 14. UX summary (the whole interaction surface)

The complete user experience of df2:

**Load:**
- Producer opens df2 in a DAW. Sees the green chassis, body name, curve,
  two sliders, body list, "df2" mark.
- Orchestrated 600ms reveal plays once.

**Audition a body:**
- Click a body name in the vertical list
- Curve crossfades to the body's color and shape over 600ms
- Q-axis label updates
- Audio passing through morphs to the new body

**Shape the sound within a body:**
- Drag Morph slider → curve responds in real time
- White-cored marker slides along the curve showing the current operating point
- Drag Q-axis slider → curve reshapes
- Audio responds to both with zero latency

**That's the entire interaction surface.** No menus. No tooltips. No
preset browser. No technical readouts. No mode switches. No version
indicators. Four bodies, two controls per body, one curve showing what's
happening.

**The discipline is in what's NOT there.** Every feature that wasn't
included is part of the brand.

---

## 15. Future-proofing rules

When new bodies (cartridges) are added later:
- The body color is the only chromatic change
- The Q-axis label changes per body's character (per naming principles)
- The chassis stays green, the layout stays identical, the typography
  stays identical
- New body names follow the naming principles in §1

When new controls might be considered later:
- Default position is **no**
- Two controls per body is the design, not a limitation
- If a future cartridge needs a third dimension, that's a new body
  category, not a new control axis — design the body's character to fit
  the existing surface

When platform expansions happen later (iPad, web, mobile):
- The visual identity does not change
- The chassis green is the chassis green at every resolution
- The interaction model adapts to the input device (touch handles
  bigger; otherwise identical)
- The plugin reads as df2 from across the room on any platform

---

## 16. The one sentence that resolves any future question

> *Does this make the chassis feel less dead, or the math feel less alive?*

If yes, it's wrong. If no, it's allowed.

Everything in this document descends from that question.
