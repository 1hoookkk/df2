# TRENCH — Ship Checklist

**Drafted:** 2026-07-22 · **Updated:** 2026-07-22 (folded in senior-engineer
adversarial review) · **Target discussed:** mid-July 2026 (already reached).

Grounded in verified state, not optimism. Every ✅ has evidence. This is the
authoritative gate.

**Legend:** ✅ done + proven · 🔶 partial · ⬜ not started · ⛔ Tier-0 blocker (must clear to sell)

---

## 0. SCOPE DECISION — this sets the date

**The single biggest lever on the timeline. Decide before anything else:**

> **Is v1 Windows-VST3-only, or full multi-platform (macOS + AU + Apple Silicon)?**

- **Windows-VST3 first:** fastest path; misses ~half the market (Logic/AU users), but many indie plugins launch this way and add Mac later.
- **Full multi-platform:** the professional launch, but adds a real **7–10 days** (cross-compile, `auval`, notarization) plus a wider host matrix.

Everything below is scoped for **both**; the platform items (§8) only apply if you
choose full multi-platform. **This decision moves the ship date by weeks — make it explicitly.**

---

## 1. Modulation UX — the distinguishing feature (main concern)

Shipping the weak chip-menu modulation on the best feature undersells the product.

| Item | Status | Evidence / note |
|---|---|---|
| Phosphor wake (movement made visible) | ✅ | live `GraphDisplay` persistence; 33-frame sweep GIF |
| Axis-locked hard-snap rate gesture (no SLAM collision) | ✅ | FaceShot `RATE … PASS` (h-pull rate only, v-pull slam only) |
| SLAM first-run onboarding (one-time, persisted, floats) | ✅ | FaceShot `SLAMHINT armed=1 retire=1 persisted=1 PASS` |
| Triplet timing bug fix (1/8T=0.375 → 0.333) | ⛔ | breaks host sync; foundation for the S/T/D feel toggle |
| Move 1 — TRIGGER selector (ENV·SYNC·RISER) | ⛔ | core value prop; verbs exist (FOLLOW/SWEEP/RISE), need one clean 3-state |
| Move 2 — SPEED strip (visible notched rate + S/T/D) | ⛔ | core value prop; snap gesture built, on-glass strip + feel toggle not wired |
| Move 3 — DEPTH window (min→max travel) | ⬜ | net-new engine + reconcile with AMOUNT + wheel-cap rule (fast-follow OK) |
| Rate-gesture onboarding | 🔶 | fast-follow (power users cope; reuse SLAM-hint pattern) |
| Phosphor / oscilloscope font on readouts | 🔶 | fast-follow cosmetic |

---

## 2. DSP / bodies

| Item | Status | Evidence / note |
|---|---|---|
| **Gain bounding on ship set (crown ≤+27 dB)** | ⛔ | **Tier-0 SAFETY** — corpus logged median 43 dB, peaks to 107 dB; unbounded = blown monitors/headphones day one |
| Ship set defined (ear-approved only) | 🔶 | only 2 families pass: `ship_v2`, `master_body_trial` — thin; launch needs 20–30 solid bounded presets across them |
| Roster single source of truth (generators frozen) | 🔶 | `approved_bodies.txt` (notebook L8) — confirm regenerators neutered |
| Triplet timing correctness | ⛔ | same fix as §1 |
| Sample-rate scaling (44.1 / 48 / 96 / 192 kHz) | ⬜ | bodies authored at 39062.5 Hz; verify poles don't cram/blow at 192k (`SCALE` re-derives per rate — confirm) |
| Stability certification (grid) | ✅ | `body-from-geometry` 25×25 certify on emitted bodies |
| Compiler modulation-capabilities report | ✅ | authoring aid built this session (bonus) |

---

## 3. Legal / IP — ⛔ ship blockers

| Item | Status | Evidence / note |
|---|---|---|
| Display-glass **plate bitmap** redraw (`display_bitmap4613`) | ⛔ | E-mu-derived asset — redraw clean; needs provenance decl + pixel-diff proving zero overlap with E-mu binaries |
| Log-frequency grid ruling | ✅ | functional/generic, not copyrightable expression (Tyson call 2026-07-22) — not a risk |
| No ROM-derived bodies ship | ✅ | locked decision; measured-authoring path only (notebook §5) |
| Audit remaining screen assets for X3-copied pixels | ⬜ | confirm nothing else is a lightly-processed dump |
| Body extraction hardening (memory-dump) | 🔶 | nice-to-have, NOT a blocker — every plugin's presets are dumpable by a determined RE |

---

## 4. UI / face — mostly banked

| Item | Status | Evidence / note |
|---|---|---|
| Wheels read machined, not toys | ✅ | Tyson: "look great" |
| Screen frame depth + readout recess | ✅ | Tyson: "looks good"; additive ink, curated assets untouched |
| BODY selector | ✅ | kept as-is (08-09 vibe) — Tyson locked |
| KEY module (detect + snap) | ✅ | FaceShot KEY proofs PASS |
| FaceShot harness green (no regressions) | ✅ | all proofs PASS, exit 0 — **note: headless render pass ≠ DAW/GPU pass** (see §7) |

---

## 5. Engine / build

| Item | Status | Evidence / note |
|---|---|---|
| Release VST3 build + install (dev machine) | 🔶 | `build_install_vst3.ps1` copies to one machine — **not a release pipeline** (see §8) |
| Standalone build | ✅ | builds + launches (used this session) |
| Loads + runs in FL (basic) | 🔶 | instantiates at 44.1k/512 — NOT stress-tested (see §7) |

---

## 6. Packaging / release

| Item | Status | Evidence / note |
|---|---|---|
| Product name / branding final | ⬜ | — |
| Demo material (the "loop → melody" hook) | ⬜ | queued a prior session; not done |
| Pricing / positioning | 🔶 | RC1 notes exist ($49–79 pack / $149 plugin — `trench_money_pack_rc1`) |
| Preset pack / factory bodies finalized | ⬜ | depends on §2 ship-set lock |

---

## 7. Real-time & host hardening (was entirely missing — engineer catch)

| Item | Status | Evidence / note |
|---|---|---|
| **Audio-thread safety audit** | ⛔ | Tier-0 — no `malloc`/lock/disk I/O on the RT thread during MORPH mod, preset change, or HUD update = no stutters/pops |
| Denormal floats / FTZ-DAZ flags | ⬜ | recursive biquads can denormal on silence → CPU spike; enforce FTZ/DAZ on the audio thread |
| State save / recall (`getState`/`setState`) | ⬜ | every param (MORPH, Q, MIX, mod mode/speed/depth) recalls byte-exact after reopen/duplicate |
| Automation smoothing / zipper noise | ⬜ | rapid MORPH/MIX automation must not click — verify the 32-sample coeff ramp holds |
| Latency reporting (PDC) | ⬜ | report any processing latency to the host, or confirm zero |
| Multi-instance CPU under load | ⬜ | many instances in a real project without dropouts |

---

## 8. Platform / installer / signing (applies if §0 = multi-platform)

| Item | Status | Evidence / note |
|---|---|---|
| macOS build (VST3 + AU `.component`, `auval` clean) | ⬜ | ~half the market is AU/Logic |
| Apple Silicon native (M-series) | ⬜ | — |
| Windows EV code signing (blocks SmartScreen) | ⬜ | unsigned = OS security warning on install |
| macOS notarization (blocks Gatekeeper) | ⬜ | — |
| Signed installer (WiX/Inno / pkg) | ⬜ | not "copy a .vst3 by hand" |

---

## Tier-0 blockers (must clear to sell)
1. **Display plate bitmap redraw** (legal) — §3
2. **Gain bounding ≤+27 dB on ship set** (safety — blown monitors) — §2
3. **Triplet timing fix** (host sync) — §1
4. **Modulation 3-Move controls: Trigger + Speed on the face** (core value) — §1
5. **Audio-thread safety audit** (no allocs/locks) — §7
6. **Code signing + signed installers** (OS compliance) — §8, *if multi-platform*

## Fast-follow (Day-30)
Rate-gesture onboarding · phosphor font · Move 3 (Depth window) · expansion preset packs.

---

## The honest bottom line

- **Mid-July (now) is impossible.** Shipping today = Windows-only, copyright-risk
  asset, potential monitor-blowing gain, broken triplet timing, missing core
  modulation controls.
- **The date is set by §0 (the scope decision).**

**Engineering horizon (full commercial multi-platform):**

| Phase | Effort |
|---|---|
| Fix math & DSP (triplet, gain-bound ship set, denormal/audio-thread) | 5–7 d |
| Wire modulation 3-Move (Trigger + Speed on face) | 5–7 d |
| Asset & legal clean-room (redraw plate bitmap + pixel audit) | 3–4 d |
| Host matrix & recall (state, automation, FL/Ableton/Logic stress) | 5–7 d |
| Multi-platform build + code signing (mac AU/VST3, notarize, Win installer) | 7–10 d |
| Preset roster lock + final audition (25+ bounded, ear-approved) | 3–5 d |
| **Total** | **~4–5 weeks** |

- **Full multi-platform → target late Aug / early Sept 2026.**
- **Windows-VST3-first → drop the 7–10 day platform phase → target early–mid August.**

**Recommendation:** don't ship the weak modulation. Take the weeks, launch it
*built* and *safe*. Pick the scope (§0) first — that's the fork that sets the date.
