# Forge Snap Modes — spec

Status: design spec for the rewrite (Corner Bank → The Move → Surgical Edit → Packed Proof → Keep/Kill).
Scope: how frequency handles snap while authoring on the log-Hz canvas. Bake target stays legal 4×6 `.body240`.

## Principle

- The authoring canvas is **log Hz × dB**. You drag peaks and cuts by ear.
- Snapping is an **aid, never a cage**. It must never make by-ear work feel dead.
- **Default = Off.** Ghost hints stay visible so you *see* the useful frequencies without being forced onto them.
- **Soft snap** = a gentle pull only when the handle is inside a small window of a target; drag past it and you're free again. **Hard snap** (locked to grid) is opt-in only.
- **Make Room is a one-shot action, not a mode** — it nudges crowded parts apart once, then lets go. Everything stays editable after.

## Human UI

One control near the canvas / selected part:

```
SNAP:   Off  |  Voice  |  Rails  |  ⤢ Make Room
```

- **Off** — free drag (default). Octave + voice ghost hints shown faint.
- **Voice** — soft-snap to formant / vowel anchors.
- **Rails** — soft-snap to learned P2K-ish landing zones.
- **⤢ Make Room** — a *button*, not a persistent state. One-shot Bark/ERB de-crowd.

Power users get the full set behind a small menu: `Free · Octaves · Music · Voice · Rails · Room`.

Best default session state: **Snap Off, ghost hints on.**

## The modes (rule + data)

1. **Free** — no snap. Octave rails + voice anchors drawn faint for reference only.

2. **Octaves** — snap to `20·2^k`: `[20, 40, 80, 160, 320, 640, 1.25k, 2.5k, 5k, 10k, 20k]`. Optional half-octave subdivisions (`×√2`). Soft window ±0.10 oct.

3. **Music** — semitone / note-ratio snap from a chosen **root**: `f = root · 2^(n/12)`. Default root 55 Hz (A1); expose a root picker. Optional ratio set: 12-TET, just intonation, or harmonic series (`n·root`) for combs / metal / modal material. Soft window ±25 cents.

4. **Voice** — snap to formant/table anchors per band:

   | anchor | range (Hz) | center |
   |--------|-----------|--------|
   | sub    | 30–150    | ~70    |
   | F1 throat | 150–950 | ~350  |
   | F2 vowel  | 700–2500 | ~1300 |
   | F3 bite   | 1800–3600 | ~2500 |
   | F4 edge   | 3000–5200 | ~3900 |
   | air    | 5000–12000 | ~8000 |

   Targets come from the canonical vowel/formant table (e.g. `dev/tmp/vocal_filter_atlas/vocal_anchor_grid.json`), not these round numbers. Snap to the nearest in-band anchor. Soft window ±0.15 oct.

5. **Rails** — snap to **learned landing zones**: a generated table of the frequency positions our lawful generators + heritage analysis actually land on (the recurring grid points). This is the P2K "feel" without copying anything — **frequency positions only, never vendor coefficients, curves, names, or preset data** (clean-room rule). Built offline into a rails table. Soft window ±0.10 oct.

6. **Room** (the **Make Room** button) — a one-shot **Bark/ERB spacing** pass. Walk the unlocked peaks low→high; wherever two adjacent peaks sit closer than `MIN_BARK` (≈ 1.0 Bark) apart, push them apart symmetrically until they clear the threshold, clamped to each part's legal range, never crossing into instability. This is the **anti-mush** tool. Runs on click; the result is fully editable.

## Behind the scenes (the human labels map to)

```
Off        = free drag, ghost hints only
Voice      = formant / table anchors
Rails      = learned P2K-ish landing zones (positions, not presets)
Make Room  = Bark / ERB spacing pass
```

Bark/ERB is **analysis/spacing math**, never the authoring grid. The canvas grid stays log-Hz octaves + voice anchors.

## Ghost hints

- Always render octave rails (faint) and voice anchor labels (faint), in **every** mode.
- In Voice / Rails / Music mode, also draw that mode's targets as faint tick ghosts; the nearest target to the held handle brightens.
- Hints are visual only — they never constrain Free mode.

## Where it applies

- Every draggable frequency: each part's **peak** and **cut**, at **both** the HOME and AWAY frames.
- Snap is per-handle, evaluated on drag.
- **Make Room** operates on the whole corner at the current sweep position (and may be applied per-corner).
- **Locked / pinned parts are never moved** by snap or Make Room.

## Pseudocode

```text
snap(hz, mode, ctx):
  Free    -> hz
  Octaves -> nearestWithin(hz, OCTAVE_RAILS, 0.10 oct)
  Music   -> nearestWithin(hz, root * 2^(n/12), 25 cents)
  Voice   -> nearestWithin(hz, VOICE_ANCHORS, 0.15 oct)
  Rails   -> nearestWithin(hz, RAILS_TABLE, 0.10 oct)
  # Room is not a per-drag snap

nearestWithin(hz, targets, window):
  t = argmin_t |log2(hz / t)|
  return (|log2(hz / t)| < window) ? t : hz     # soft: pull only when close

makeRoom(corner):
  ps = unlocked peaks, sorted by freq
  for i in 1..n-1:
    gap = bark(ps[i].f) - bark(ps[i-1].f)
    if gap < MIN_BARK:
      spread ps[i-1], ps[i] symmetrically until gap == MIN_BARK
      clamp each to its legal range; skip locked
  recompile; reject any move that breaks stability
```

## Defaults / open

- `MIN_BARK ≈ 1.0` — tune by ear.
- Music root default 55 Hz (A1); root picker exposed.
- Hard-snap is a separate opt-in toggle, off by default.
- `RAILS_TABLE` is a generated artifact — regenerate when the generators or heritage analysis change.
- In the real bench, **all snap targets come from the exact tables**, not prototype approximations.
- Undo restores pre-snap / pre-Make-Room state.
