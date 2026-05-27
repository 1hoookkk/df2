# tools/legacy — retired stage-first body generators (quarantine)

Quarantined 2026-05-27. These generated bodies by designing **individual stages
/ per-stage roles** — the rejected trap. Stages are bookkeeping; the real target
is the full cascade response. The response-first replacements live in `tools/`:
`vocal_rack2.py`, `vocal_rack2_low_to_high.py`, `metal_rack.py` (whole-corner
constellation → factor to 6 biquads, judged by `response_budget.py`).

- `vocal_rack.py` — six named "bones" per corner (sub / F1 throat / F2 tongue /
  F3 presence / edge / air). The literal role-anatomy method. Superseded by `vocal_rack2.py`.
- `vocal_rack3.py` — response-first framing but places per-stage character
  ("sheen up top", per-stage anti-formant); deprecated as "too filled-in".
- `tube_pairs.py` — couples zeros onto specific F1/F2/F3 named formant stages
  (imports `vocal_rack`).
- `floor_transfer.py` — sculpts per-row gain as the design act.

Not stage-first, so NOT moved here (separate "dead/duplicate" clutter to triage
later if desired): `corner_hunt_batch.py` (dup of `body_candidate_rack.py`),
`compile_raw.py` (superseded by `author_body.py`), the physical-corners faucet
cluster (`weapons.py`/`corners_from_middle.py`/`design_middle.py`/`plot_corners.py`/
`bake_well_corners.py`), the `spellcast*` reel-content tools, and the LPC/test-source
fixtures (`make_test_sounds.py`/`stage_sustained.py`/`lpc_test_input_gen.py`/`lpc_verify_plot.py`).
