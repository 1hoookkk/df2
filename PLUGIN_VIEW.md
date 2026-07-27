# PLUGIN VIEW — the TRENCH surface, for humans and agents

One page: every control, what it drives, its range, and how to describe plugin
state in a chat message. Update this file when the surface changes — it is the
context agents read before touching UI or parameters.

## State line

To communicate an exact plugin state (instead of a screenshot), write one line:

```
TRENCH{body:Hedz Bottle Mouth; morph:68; q:30; mix:100; slam:0; out:0dB; mod:SYNC 1/16 Shark Tooth d40; key:OFF}
```

Omit anything at default. `mod:` is `OFF` | `AUTO d<depth>` | `RISE <rate> d<depth>`
| `SYNC <rate> [TRIPLET|DOTTED] <shape-or-phrase> d<depth>`.

## Controls → parameters

| control (face) | param id | range / choices | default | notes |
|---|---|---|---|---|
| BODY dropdown | `body` | roster index, frozen range | NO FILTER (0) | switch keeps ALL other settings (law 07-27). NO FILTER = identity body = "nothing but the distortion" mode |
| MORPH wheel | `morph` | 0–100 % | 0 | drags on X. Every position is a real filter (pose). Re-placing restarts modulation cycle |
| Q wheel | `q` | 0–100 % | 30 | drives CHEW: chew = bite + 0.55·Q² |
| MIX thin wheel | `amount` | 0–100 % | 100 | master dry/wet over EVERYTHING (filter+CHEW+SLAM). 0 = bit-dry (−300 dB proven). Reports on screen only while dragged |
| SLAM (screen drag UP) | `slamDrive` | 0–100 % | 0 | wet-voice desk pressure, +12 dB into rounded limit, knee 0.72. 0 = hard bypass |
| TAKE (drag OFF screen) | — | gesture | — | resamples last 0.6–8 s to `Documents\TRENCH\takes`, external drag-drop. 12 px sideways, 1.8:1 vs vertical |
| KEY selector | `keySnap` | OFF + 24 keys | OFF | detector suggests; **functionality story currently OPEN** |
| MODULATION chip | `modOn`,`modTrigger` | OFF / AUTO(env) / SYNC / RISE | OFF | dropdown on the chip |
| rate (in chip menu) | `modNote`,`modFeel` | 4 BAR..1/16 (+feel), host-locked | 1/16 | for phrases: one rate unit = ONE pattern STEP |
| PHRASE (in chip menu) | `modShape` | 6 waves + 6 grammars: BREATHE, RHYTHM, RISE, WANDER, ANSWER, STABS | SINE | one representative per movement grammar (E-MU factory tables; git archives all 58). WAVE returns to plain shapes |
| depth | `modDepth` | 0–100 % | 50 | travel from home (wheel); patterns peak-normalised. **Lost its UI with page 2 — needs a home or a baked default. OPEN** |
| CHEW | — | — | — | CHEW is Q's law: 0.55·Q², no separate dial anywhere |
| TRENCH badge | — | click / shift-click | — | click cycles the face: CORAL BOUTIQUE (ships) ⇄ SAGE LCD — signal tokens + both baked bitmaps swap live. Shift-click replays the onboarding tour (5 steps, demo body, lands on NO FILTER). The pick is a UI setting (`uiSkin` on the APVTS state tree), not a host parameter |

Buried 07-27 (decision-bandwidth pass): `clip`, `bite`, `inputMode`
(slam-into-filter), `keyTrack`, `output`, `fiveD`, `modSync`, `modRate`, and the whole page-2 system (TakeView tray / MoveView / SlotPad — one face, no pages). AGC/routing are implementation choices, not
parameters. `hdMode` SURVIVES by Tyson's verdict — 78125 clean vs 39062.5
vintage island rate is a sound choice (host-only for now; needs a home story).
Controls live in the UI, not host lists.

## Gestures on THE SCREEN

- **drag UP/DOWN** — SLAM (shift = fine, scroll adjusts, double-click resets)
- **drag OFF the screen** — TAKE (capture + drag into DAW). Classified after
  12 px horizontal beating vertical 1.8:1; SLAM restored to press value on take
- **MIX readout** appears in-screen only while the MIX wheel is dragged

## Laws that bind any change here

- Every wheel position is a real filter; the ramp carries the ring
- Arrive-sit-move for modulation; downbeat sacred; phrases not waveforms; no drawable editors
- Settings persist across body switch; anything audible must sit before the MIX blend
- No faceplate additions without an explicit go
- Judge UI at true scale via `TRENCH_FaceShot` (ONBOARD/MIX/RATE/TYPE iter modes)

## Open on the bench (2026-07-27)

KEY's job undefined · preset cycling sometimes jarring (re-judge post
settings-persistence) · CHEW 55% ceiling + morph unevenness unheard · AGC −24 dB
null at full scale on NO FILTER · six grammar representatives awaiting ear
verdict (BREATHE/RHYTHM/RISE/WANDER/ANSWER/STABS; 58 archived in git) · DEPTH vs
TARGET-pose decision.
