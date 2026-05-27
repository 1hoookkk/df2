# Filter Design Desk

Draw a magnitude target per corner → compile through the **real** forge → validate
against the **real** stability rules → write the live slot the plugin hot-reloads.
No fake compiler path: the only added DSP is the standard min-phase reconstruction
that bridges a magnitude-only drawing to the complex target `forge_fit` wants.

## Run it

```powershell
cd C:\Users\hooki\df2
python -m uvicorn pyruntime.api:app --host 127.0.0.1 --port 8137
```

Then open **http://127.0.0.1:8137/desk** in a browser.

## The loop

1. **Draw** — pick a corner tab (`M0_Q0` / `M100_Q0` / `M0_Q100` / `M100_Q100`),
   drag the 14 points vertically to shape its magnitude (20 Hz–20 kHz, −36…+36 dB).
   Do all four corners — Morph X = the glide, Q Y = the tighten.
2. **Compile** — `~15–20s`. Runs the real `pyruntime.forge_fit.fit_corner` per corner:
   drawn curve → min-phase complex target → 6-biquad cascade fit → packed words.
   Green = your target, amber = what the forge actually solved, red = the error.
3. **Validate** — checks structure + pole stability (`r < 1.0`, finite) across the
   whole packed Morph×Q surface (17×17). Must pass before you can write.
4. **Write Live** — writes `~\Documents\TRENCH\authoring_slot.json`. The plugin
   watches this file and hot-reloads it. Audition in the player.
5. **Load Live** — pull the current live cartridge back in as editable curves.

## What's real (discovered from the repo, not invented)

| Piece | Source of truth |
|---|---|
| Solver | `pyruntime/forge_fit.py` — `fit_corner` (complex LSQ, the only fitter) |
| Cartridge format | `compiled-v1` + `authoringModel: response-surface-v1`, 6 stages × 5 coeffs |
| Packed words | `pyruntime/packed_interp.py` (`coeffs_to_words`), 6×5 u16 |
| Stability rule | pole radius `< 1.0` over the packed bilinear surface |
| Live slot path | `~\Documents\TRENCH\authoring_slot.json` (the plugin's audition slot) |

## Speed note

`compile_design` runs **forge_fit (light)** — the same real solver at a smaller fit
grid (`N_FIT=512`) and fewer restarts (`n_restarts=2`, `max_nfev=300`). A drawn
curve converges in ~2 restarts because the peak-picked seed already lands the
resonances; nulls come in around −26 dB, stable. The heavy defaults
(`n_restarts=16`, `max_nfev=1500`, `tol=1e-10`) are still there for measured-transfer
fits — they're just not what an interactive draw needs.

Backend: `pyruntime/desk_compile.py` · routes appended to `pyruntime/api.py`
(`/desk`, `/desk/health`, `/desk/live`, `/desk/compile`, `/desk/validate`,
`/desk/write-live`).
