> ## HANDOFF — to the model picking this up (Mythos / Fable)
>
> You're inheriting df2: a destructive morphing **Z-plane filter** FX plugin. The deliverable is a
> **locked authoring app**. Read `CLAUDE.md` + `AGENTS.md` + the memories first. Below is the kernel
> so you skip the 100-message navigation that produced it.
>
> **Hard-won facts (OBSERVED this session — don't re-derive, do re-verify if you doubt):**
> - **ONE encoder = `trench-core` `compile_body`** (== the forge-web WASM GUI, byte-exact). Rogue
>   `coeffs_to_words` paths once diverged **59 dB**. Pack ONLY through it; **null byte-0 is the gate**
>   (`tools/null_sweep.py`).
> - **Q blooms 6–34 dB** in the real ROM bodies (Talking Hedz +17, Meaty Gizmo +33) — NOT the
>   "0.3–1 dB, Q barely moves" the doctrine claimed. That bent ruler was quietly killing the sound
>   (dead Q knob, starved drive chain). Fixed: `CLAUDE.md`, `smoke.yaml` floor 0.25→5.7, objective.
> - **`plot == engine` to 0.0000 dB** (`forge-web/js/packed.js` mirrors the engine). The plot is the
>   judgment surface — it does not lie.
> - **A body = 24 biquads → 240 bytes** (4 corners × 6). Morph/Q **bilinearly blend the packed
>   minifloat words** — the interior is **emergent** ("magic in the middle"), not dial-precise; the
>   **midpoint is not invertible** (you author, you don't reconstruct).
> - **LPC poles alone = a dark lowpass.** A body that *reads* = LPC poles (real sources) **+ a
>   flat-top low-shelf foundation** (kills the all-pole tilt so formants ride hot) **+ ONE leader**
>   (pole and/or canyon-zero sweeping >1 oct). See `tools/design_corners_lpc.py` (5/6 pass the gate).
>
> **The architecture we LANDED on — but the ask is: FORM YOUR OWN OPINION ON IT. Pressure-test it
> before you build. Agree, disagree, or propose better, and say why.**
> - One core: `trench-core` (Rust) → compiles to **WASM (the UI)** + **DLL (the plugin)** — same bytes,
>   same sound, divergence impossible.
> - **forge-web UI = the entire authoring app** on the WASM core (design / LPC-fit / corridor-gate /
>   audition through the drive chain / save `.body240`). Self-contained, no backend.
> - JUCE plugin just plays `.body240`.
> - **Retire** the Python QD search + ~40 `tools/` (where the rogue encoders + bent gates lived);
>   **port the corridor gate into the UI** so even it is locked.
> - Open questions for you specifically: Is "all authoring in-browser on WASM" the right shape, or does
>   something (heavy fit/search, the gate) belong native? Is killing the QD search correct, or is there
>   value in it once it optimizes the *fixed* target? Is center+throw the right authoring model vs raw
>   4-corner editing? **Don't assume we were right.**
>
> **How Tyson works (read this — it's the real constraint):** non-coder, non-DSP; he owns **taste**.
> He judges by the **plot** (the eye) and the **ear** (audition through AGC→Mackie→QSound), never code.
> Work **one thing at a time**: build a step → he LOOKS / hits play → keep or kill → next. **Tell him
> the cost** of a move ("1-line tweak" vs "rewrite"). **Never sweep-rewrite unprompted** — a stronger
> model makes bigger moves faster, which is exactly the failure mode here. He reaches correctness by
> reacting to what's wrong; honor that in the think phase, stay linear in the build phase.

# Forge editor — spec

The surface for authoring a df2 body. Built one step at a time; each step ships and is proven
(plot / null / gate) before the next. No new doctrine, no mythology — concrete DSP only.

## The object (settled)
A body = **240 bytes = 4 corners × 6 biquads × 5 words.** Corners: `M0·Q0, M100·Q0, M0·Q100,
M100·Q100`. The engine **bilinearly blends the packed words** — Morph blends M0↔M100, Q blends
Q0↔Q100. `plot == engine` to 0.0000 dB. **Pack only through `compile_body`** (the one encoder);
null byte-0 is the gate.

## What we decided (the facts the surface must respect)
- **Stages aren't roles.** The cascade commutes (`H=∏Hₖ`) → slot order is free. The slot index is
  only the **morph-pairing tag**: biquad *i* in corner A blends to biquad *i* in corner B.
- **Q is a co-leader.** Real iconic bodies bloom **6–34 dB** under Q (measured, ROM). Author a real
  bloom, not a subtle one. (`smoke.yaml` floor is now 5.7.)
- **LPC of a real sound = the poles** (one corner's 6 biquads). **Zeros are hand-authored** (character).
  A body that reads = **LPC poles + a flat-top low-shelf foundation** (holds the lows, kills the
  all-pole tilt so formants ride hot) **+ ONE leader** (pole and/or canyon-zero sweeping >1 oct).
- **The midpoint isn't invertible.** The editor **authors**; it does not reconstruct an existing body
  from its center. Designing M50·Q50 + a throw is accurate for the center to ~2 oct of travel.

## Authoring model
- **Primary — center + throw.** Design the **M50·Q50** sound at rest (fit from a real source, or drag
  it). Add a **throw**: per-pole **travel** (Morph) + a global **Q tighten** (the bloom). The 4 corners
  derive as center ± throw and pack to 240 bytes. Coherent throws (move the formant set as a unit)
  keep vowels intact; corners are symmetric — pull one free for an asymmetric move.
- **Direct — edit a corner.** Select any of the 4 corners and drag its 6 biquads.

## Display
- **Bark-scale frequency axis** (perceptual), shared by the z-plane angle and the response x-axis.
- **The response plot is the judgment surface** — lead with it; the z-plane is the secondary map.
- DPR-crisp canvases; hand-drawn aesthetic; numbered biquads; live markers move with Morph/Q.

## Audition
Through the real **AGC → Mackie → QSound** worklet, safe master vol, optional live spectrum behind
the response. The ear confirms last.

## Build order — ONE AT A TIME (each: build → plot/null/gate proof → Tyson check → next)
1. **Center surface.** The response plot is the main editable surface; the live M50·Q50 curve is the
   star; drag a peak (pole) or notch (zero) directly on it. *Proof: drag → repack → curve moves; byte-0 nulls.*
2. **Throw.** Per-pole travel handle (Morph) + global Q tighten → derive + pack the 4 corners.
   *Proof: sweeping Morph/Q glides the live curve between the derived corners; corners differ.*
3. **Flat-top foundation.** Auto low-shelf that holds the lows flat (kills the tilt). Toggle.
   *Proof: plot shows held lows + hot formants, not a dark lowpass.*
4. **Leader canyon.** One authored moving zero sweeping >1 oct. *Proof: passes the leader-zero gate.*
5. **Real-source fit → center.** LPC a dropped audio file / mic into the center's 6 poles.
   *Proof: formant peaks land within ~10% of the source.*
6. **Corridor verdict on save.** `evaluate_body` + `gate_failures` (smoke.yaml) shown live; Save writes
   `.body240` to the corpus; assert byte-0 null vs `compile_body`. *Proof: verdict matches the Python gate.*
7. **Audition.** Play through the drive chain; live spectrum overlay. *Proof: it sounds like the plot.*

Surface: `forge-web/editor.html` (extend, don't rebuild). Encoder: WASM `compile_body` (== Python).
