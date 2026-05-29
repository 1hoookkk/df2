---
description: Audit duplicate implementations of the packed-math kernel (the "can of worms" — packed-16 minifloat encode/decode/lerp + DF2T biquad cascade) reimplemented across Python and Rust. Maps copies to the canonical trench-core FFI owner.
argument-hint: "[symbol]  (optional — defaults to the packed-math suspects)"
---

You are auditing **duplicate function implementations** of the packed-math
kernel across the df2 codebase. The user's `packed-math-triplicated` memory
flags this as THE can of worms: packed-body/morph math is reimplemented in
Python (`pyruntime/` + ~30 tools), Rust runtime (`trench-core/`), and Rust
forge (`forge/`), no single owner, drift = "judging different versions of the
same corner." Recent commits (`80d7822 ffi: make trench-core the one owner of
the packed math`, `d56672b ffi: migrate corner.py onto the packed-math owner`)
have started consolidating onto a trench-core FFI owner. This command finds
what's left.

## Suspect set (default — covers the known triplication)

If no `$ARGUMENTS`, audit all of these:

1. **Minifloat encode/decode** — `u16 ↔ f64` for the packed-16 word format
   (`trench-core/src/minifloat.rs`). Suspect names: `decode`, `encode`,
   `decode_u16`, `encode_u16`, `minifloat_to_f64`, `pack_word`, `unpack_word`,
   `pack_to_u16`.
2. **Packed-domain bilinear lerp** — the `FUN_1802c3d40` formula (int16
   truncate delta, then add base; wraps, no clamp). Suspect names:
   `lerp_u16`, `packed_lerp`, `packed_bilinear`, `bilinear_pack`,
   `interp_packed`, `morph_pack`.
3. **Coefficient-domain bilinear** — the shipping morph: Q-lerp the two morph
   edges then morph-lerp (see `Cartridge::interpolate`,
   `trench-core/src/cartridge.rs:197`). Suspect names: `interpolate`,
   `interp_corners`, `bilinear`, `morph_interp`, `compute_coeffs`,
   `corner_interp`.
4. **Raw → encoded** (`raw_to_encoded` family) — the kernel coefficient
   derivation. Suspect names: `raw_to_encoded`, `kernel_coeffs`,
   `coeffs_from_raw`, `to_encoded`.
5. **DF2T biquad kernel** — `b0=c4, b1=(c0-2)c4, b2=(1-c1)c4, a1=c2-2,
   a2=1-c3`. Suspect names: `df2t`, `biquad`, `cascade`, `process_block`,
   `run_cascade`, `apply_filter`.
6. **240-byte body bytes ↔ packed words** — `from_rom_bytes` / its inverse.
   Suspect names: `from_rom_bytes`, `to_rom_bytes`, `body_bytes`,
   `bytes_from_cart`, `body_bytes_from_cart`, `cart_to_bytes`.

If `$ARGUMENTS` is provided, treat it as the symbol/concept to audit
(e.g., `lerp_u16` or `df2t`). Use it as the seed for step 1.

## Search territory

- `trench-core/src/` (Rust — the **canonical owner**; everything else should call it via FFI)
- `forge/src/` (Rust — must call trench-core, not reimplement)
- `pyruntime/` (Python — FFI wrapper layer; some legacy reimpls remain)
- `tools/` (Python — biggest sprawl; ~30 files)
- `juce-shell/source/` (C++ — must use the cartridge interpolation in the kernel; flag if it reimplements)

Skip: `juce-shell/build/`, `juce-shell/modules/`, `target/`, `dev/tmp/`,
`ref/`, `vault/`, `bodies/`, `legacy/` (the stage-first quarantine).

## Workflow

1. **Search by suspect name** — for each suspect in §1–6, use Grep across the
   five search areas. Capture `file:line` of every `def`/`fn`/`function`
   match. Cast wide on names; the same logic gets renamed across languages.

2. **Open each hit and extract a fingerprint** (read the function body —
   usually 5–40 lines):
   - Signature (arg names + types if obvious)
   - 3–5 most distinctive operation lines (e.g., `int16(b - a)`, `& 0xFFFF`,
     `c4 * (c0 - 2.0)`, `np.cumsum`, `wrapping_add`).
   - Whether it calls into `trench_core` / `trench_ffi` / the FFI layer
     (= it's a wrapper, not a duplicate).

3. **Cluster** — group implementations whose fingerprints match the same
   algorithm. One cluster per algorithm.

4. **For each cluster, identify the OWNER**:
   - If a `trench-core/src/*` impl exists → that's the owner.
   - Otherwise the impl with the most callers or in the most authoritative
     module is the de facto owner.

5. **Output report** at `dev/tmp/packed_math_dup_audit_<YYYYMMDD>.md` with:

   ```
   # Packed-math duplicate audit — <date>

   ## Cluster N: <algorithm name, e.g. "Minifloat u16 ↔ f64">
   - **Owner (canonical):** `trench-core/src/minifloat.rs:42` — `pub fn decode(w: u16) -> f64`
   - **Duplicates / re-impls:**
     - `pyruntime/packed_interp.py:18` — `def decode_u16(w)` — DOES NOT call FFI; pure Python reimpl
     - `tools/corner_bench.py:91` — local `_unpack(w)` — pure Python reimpl
   - **Wrappers (OK, leave alone):**
     - `pyruntime/trench_ffi.py:55` — `def decode(w)` — calls trench-core via FFI

   ## Cluster M: ...
   ```

6. **Surface the headline counts** in the chat: total clusters, total
   duplicates, total wrappers, suggested consolidation order (start with the
   cluster that has the most duplicates AND a trench-core owner — that's the
   cheapest migration).

## Hard rules

- **Do NOT auto-migrate / refactor.** This is an audit, not a fixer. Drift
  in packed math has already cost the project ("judging different versions of
  the same corner" — [packed-math-triplicated]). Migration needs the user's
  eyes on each call site. Just report.
- **Do NOT mark wrappers as duplicates.** A Python function that calls
  `trench_ffi.foo(...)` is the right shape — it's the FFI gateway. Only
  flag impls that re-derive the math.
- **Do NOT search `legacy/`, `dev/tmp/`, `bodies/`, or build artifacts.**
  Stage-first is intentionally quarantined ([stage-first-retired-command-center]).
- **The DF2T biquad math is allowed to live in multiple places** if all of
  them are kept bit-identical to `trench-core/src/cascade.rs`. The hazard
  is divergent re-derivations, not the formula appearing twice. Note any
  divergence (different rounding, different state-var order) loudly.
- **Test files (`*_test.rs`, `tests/`, `test_*.py`) are allowed to reimplement
  for parity checking.** Don't count them as drift.

## What "good" looks like

A clean report has 0 duplicates outside `trench-core` — every Python tool is
a thin `trench_ffi` wrapper, forge calls trench-core, JUCE calls trench-core.
Recent commits suggest the user is heading there; this audit measures how
far there is to go.
