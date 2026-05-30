---
created: 2026-05-30T17:50:38.255Z
title: Re-index and audit the Forge corner library
area: forge
files:
  - dev/tmp/arma_source_pack/corners_audio_only/ (_rom/_design/_physics/_heritage[69]/_authored/_reference/_voice)
  - dev/tmp/*.body240
  - dev/tmp/emu_vet/vet_library.py (reusable audit gate)
  - forge/src/forge_core.rs (available_sources/available_presets/scan_bins/scan_p2k_variants/collect_wavs/collect_corners, legisign_prime_dir ~1399-1420)
  - forge/src/main.rs (duplicated source_pos placement heuristic ~629 & ~678)
  - forge/src/generators.rs (16 synthetic Architecture recipes — to be superseded)
---

## Problem

The Forge corner library is scattered and the navigation is messy. The authentic
corners live in `dev/tmp/arma_source_pack/corners_audio_only/` across loose,
inconsistent category folders (`_rom`, `_design`, `_physics`, `_heritage` = 69 E-mu
preset subfolders, `_authored` = low/high × open/closed, `_reference`, `_voice`) plus
loose `dev/tmp/*.body240` files. The Forge indexes them through several scattered
scanners (`available_sources`, `available_presets`, `scan_bins`, `scan_p2k_variants`,
`collect_corners`) and a placement heuristic (`source_pos`) that is COPY-PASTED in two
places in `main.rs` (~629 and ~678). Nothing audits a corner for quality on the way in,
and the navigation/picker is built on top of this mess. Authentic corners are meant to
SUPERSEDE the synthetic `Architecture` generators (NOW.md roadmap #3).

## Solution

One integrated, smooth change spanning dev/tmp + forge — "audit them in as they go":

1. **Strip + re-index:** pull every corner out of the scattered categories into a
   single re-index pass.
2. **Audit on ingest:** gate each corner with the existing vet logic
   (`dev/tmp/emu_vet/vet_library.py` — finite / alive / stable poles<1 / ≥2 peaks / sane
   peak level, rendered through the REAL engine). Reject junk; surface pass/fail per
   corner as they go.
3. **Organise properly:** survivors land in ONE clean canonical indexed structure.
   Corner schema is compiled-v1 `.corner.json`: `format` / `name` / `sampleRate`
   39062.5 / `stages` 6 / `keyframes[{label, boost, stages[c0..c4]}]` (verified against
   `_rom/talking_hedz_*` and `_design/speaker_knockerz`).
4. **Fix the navigation:** collapse the scattered scanners + the duplicated `source_pos`
   heuristic into a single `CornerLibrary` index built once; point the Forge picker/nav
   at the clean index.

Keep the 69 forge tests green; do not touch frozen trench-core; CLAP/atlas track stays
parked but this pairs with it (clean indexed library = the corpus the deep audio model
would later embed — see memory `deep-model-abstracts-corpus`). TDD the new index +
audit-gate. Smallest reversible commits: dev/tmp re-index+audit tool first, then forge
index, then nav.
