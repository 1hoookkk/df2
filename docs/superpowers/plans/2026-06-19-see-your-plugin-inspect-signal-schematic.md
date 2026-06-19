# See Your Plugin — Inspect View (live signal schematic) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an **Inspect view** to `forge-web/bench` — a live, read-only *signal schematic* of the real TRENCH chain (`[Morph]+[Secondary/Q] → packed interp over 4 corners → Stage 1…Stage 6 serial DF2T → out`). Clicking a node drills down through three depths of transparency (plain-language sentence → curve + poles/zeros + stability ρ → raw `b0 b1 b2 a1 a2`), shows **cumulative** magnitude after each stage ("where the energy is shaped"), and updates live as Morph/Secondary move. It is a **schematic, not a node editor**: fixed structure, no rewiring, never implies wiring that isn't real.

**Architecture:** Three new *pure* ES modules under `forge-web/js/` carry all the logic and are unit-tested with `node`:
1. `schematic-graph.mjs` — `buildSchematicNodes()` returns the fixed node list + edges (no DSP, pure data) and `validateBodyBytes()` coerces/validates raw body bytes to exactly 240 (handles short/malformed without throwing).
2. `signal-chain.mjs` — `stageBiquadsAt(words,m,q)`, `cumulativeStageDb(...)`, `poleRadius(a1,a2)`, `stageContributionDb(...)` — all built **on top of the canonical packed math in `packed.js`** (no packed math reimplemented).
3. `describe-stage.mjs` — `describeStageFromCurve(curve)` turns a *measured* magnitude curve into one evidence-derived plain-language sentence (numbers come from the curve, never invented).

The bench page itself (`build_bench.py` → `bench.html`) gains a new **schematic canvas + interaction layer** that imports those modules and reuses the existing in-page renderers (`drawResp`, `drawZ`) for the drill-down. The only genuinely new rendering is the node-graph layer; everything else is reused.

**Tech Stack:** Plain ES modules (`.mjs`), `node` (built-in `assert`) for unit tests, HTML5 Canvas 2D, Python 3 (`build_bench.py` is the page generator). No new dependencies. The page runs the same trench-core via the existing WASM/closed-form path already in `bench.html`.

**Scope note:** This is the **Inspect view only**, built in the web bench. OUT: the in-plugin layout edit mode, the render/scene/validator C++ tool, AI suggestions, and porting the schematic into the C++ plugin (an explicit later step using the same FFI values already mapped in the spec's reuse ledger). See `docs/superpowers/specs/2026-06-19-trench-ui-layout-loop-design.md` ("Inspect view — live signal schematic", the truth-source map, "schematic not a node editor", "progressive technical transparency", "track the signal", "evidence first", and "Definition of done (Inspect view …)").

**depends-on:** none in C++. Reuses `forge-web/js/packed.js` (canonical packed-16 codec, verbatim) and the existing `bench.html` renderers. Does not depend on the Arrange Phase-1 plan.

**Conventions for every command below:** run from the repo root `C:\Users\hooki\df2`. JS unit tests run with `node forge-web/js/<name>.test.mjs` (exits non-zero on failure, prints `OK <name>` on success). The page is built with `python forge-web/build_bench.py`, then open the generated `forge-web/bench.html` in a browser (or serve `forge-web/` over `http://localhost:8130` so ES-module imports resolve — `file://` blocks module imports in most browsers, so a static server is required for the manual steps).

---

## Why standalone modules (testability)

`bench.html` is generated JS-in-a-Python-string, so its inline functions cannot be unit-tested directly. Every piece of *logic* in this plan is therefore extracted into a real `.mjs` module under `forge-web/js/` with a Node-runnable `.test.mjs` beside it. The page then `import`s those modules (the bench template gets `<script type="module">`). Visual/interactive parts (canvas drawing, clicking nodes) are covered by explicit **MANUAL verification** steps.

`packed.js` is the canonical owner of the packed-16 math (`wordsFromBytes`, `wordsAt`, `stageWordsToKernel`, `kernelToBiquad`, `biquadDbCoeffs`). This plan **calls** it and never re-derives `lerp_u16` / decode / morph-first interpolation (the documented "can of worms" — see memory `find-duplicate-functions` and the spec's engineering doctrine).

---

## File Structure

- **Create** `forge-web/js/schematic-graph.mjs` — pure graph builder + body-bytes validator.
- **Create** `forge-web/js/schematic-graph.test.mjs` — Node tests for the above.
- **Create** `forge-web/js/signal-chain.mjs` — live per-stage biquads, cumulative dB, pole radius ρ, per-stage contribution (built on `packed.js`).
- **Create** `forge-web/js/signal-chain.test.mjs` — Node tests for the above.
- **Create** `forge-web/js/describe-stage.mjs` — evidence-derived plain-language sentence from a measured curve.
- **Create** `forge-web/js/describe-stage.test.mjs` — Node tests for the above.
- **Modify** `forge-web/build_bench.py` — make the template a module, import the three modules, add the schematic canvas + drill-down panel + interaction, and wire it into the existing `redraw()` so it is live.

---

## Task 1: Body-bytes validation + fixed graph builder (`schematic-graph.mjs`)

**Files:**
- Create: `forge-web/js/schematic-graph.mjs`
- Test: `forge-web/js/schematic-graph.test.mjs`

This module is pure data + validation. No DSP. It owns (a) coercing any raw body input to exactly 240 bytes without throwing, and (b) the fixed schematic topology (the real chain), so the page never invents wiring.

- [ ] **Step 1: Write the failing test**

Create `forge-web/js/schematic-graph.test.mjs`:

```js
import assert from "node:assert/strict";
import { validateBodyBytes, buildSchematicNodes, SCHEMATIC_EDGES } from "./schematic-graph.mjs";

// --- validateBodyBytes ---
{
  // Exact 240 -> returned as a 240-length Uint8Array, ok:true.
  const exact = new Uint8Array(240).fill(7);
  const r = validateBodyBytes(exact);
  assert.equal(r.ok, true);
  assert.equal(r.bytes.length, 240);
  assert.equal(r.bytes[0], 7);
  assert.equal(r.reason, "");
}
{
  // Short input -> padded to 240 with zeros, ok:false + reason, never throws.
  const short = new Uint8Array([1, 2, 3]);
  const r = validateBodyBytes(short);
  assert.equal(r.bytes.length, 240);
  assert.equal(r.bytes[0], 1);
  assert.equal(r.bytes[2], 3);
  assert.equal(r.bytes[3], 0);
  assert.equal(r.ok, false);
  assert.match(r.reason, /240/);
}
{
  // Too long -> truncated to 240, ok:false.
  const long = new Uint8Array(260).fill(9);
  const r = validateBodyBytes(long);
  assert.equal(r.bytes.length, 240);
  assert.equal(r.ok, false);
}
{
  // Null / undefined / non-array -> all-zero 240, ok:false, no throw.
  for (const bad of [null, undefined, 42, {}, "deadbeef"]) {
    const r = validateBodyBytes(bad);
    assert.equal(r.bytes.length, 240);
    assert.equal(r.ok, false);
  }
}
{
  // Regular Array of numbers (not typed) is accepted and coerced.
  const r = validateBodyBytes(Array.from({ length: 240 }, () => 5));
  assert.equal(r.ok, true);
  assert.equal(r.bytes[239], 5);
}

// --- buildSchematicNodes ---
{
  const g = buildSchematicNodes();
  // Fixed structure: morph, q, interp, 6 stages, out = 10 nodes.
  assert.equal(g.length, 10);
  const ids = g.map((n) => n.id);
  assert.deepEqual(ids, [
    "morph", "q", "interp",
    "stage0", "stage1", "stage2", "stage3", "stage4", "stage5",
    "out",
  ]);
  // Stage nodes carry a stable 1-based label and a stage index.
  const s2 = g.find((n) => n.id === "stage2");
  assert.equal(s2.kind, "stage");
  assert.equal(s2.stageIndex, 2);
  assert.equal(s2.label, "S3"); // 1-based, label never relies on colour alone
  // Control + interp + out kinds present.
  assert.equal(g.find((n) => n.id === "morph").kind, "control");
  assert.equal(g.find((n) => n.id === "q").kind, "control");
  assert.equal(g.find((n) => n.id === "interp").kind, "interp");
  assert.equal(g.find((n) => n.id === "out").kind, "output");
  // Every node has a human label and a drill-down capability flag.
  for (const n of g) {
    assert.equal(typeof n.label, "string");
    assert.ok(n.label.length > 0);
    assert.equal(typeof n.inspectable, "boolean");
  }
}
{
  // Edges describe the REAL chain only (no rewiring): audio in -> stage0 -> ... -> stage5 -> out,
  // and the two controls + interp feed the stage block.
  const froms = SCHEMATIC_EDGES.map((e) => e.from);
  const tos = SCHEMATIC_EDGES.map((e) => e.to);
  // serial stage path present
  assert.ok(SCHEMATIC_EDGES.some((e) => e.from === "stage0" && e.to === "stage1"));
  assert.ok(SCHEMATIC_EDGES.some((e) => e.from === "stage4" && e.to === "stage5"));
  assert.ok(SCHEMATIC_EDGES.some((e) => e.from === "stage5" && e.to === "out"));
  // controls feed interp; interp parameterizes the stage block (drawn as control edges)
  assert.ok(SCHEMATIC_EDGES.some((e) => e.from === "morph" && e.to === "interp"));
  assert.ok(SCHEMATIC_EDGES.some((e) => e.from === "q" && e.to === "interp"));
  assert.ok(SCHEMATIC_EDGES.some((e) => e.from === "interp" && e.to === "stage0" && e.kind === "control"));
  // no stage points back to an earlier stage (no rewiring / no cycles)
  for (const e of SCHEMATIC_EDGES) {
    if (e.from.startsWith("stage") && e.to.startsWith("stage")) {
      assert.ok(Number(e.to.slice(5)) > Number(e.from.slice(5)));
    }
  }
}

console.log("OK schematic-graph");
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node forge-web/js/schematic-graph.test.mjs`
Expected: FAIL — `Cannot find module './schematic-graph.mjs'` (module does not exist yet).

- [ ] **Step 3: Write the implementation**

Create `forge-web/js/schematic-graph.mjs`:

```js
// Pure schematic data + body-bytes validation. NO DSP here.
// The graph is the REAL, fixed TRENCH chain — it never implies rewiring.

export const STAGES = 6;
export const BODY_BYTES = 240;

// Coerce any raw body input to exactly BODY_BYTES bytes without throwing.
// Returns { ok, bytes:Uint8Array(240), reason }. ok===false means the caller
// should surface a warning but the schematic can still render (zeros are safe).
export function validateBodyBytes(input) {
  const out = new Uint8Array(BODY_BYTES); // zero-filled, always safe to decode
  let src = null;
  if (input instanceof Uint8Array) src = input;
  else if (Array.isArray(input)) {
    // accept a plain Array of finite numbers
    if (input.every((v) => typeof v === "number" && Number.isFinite(v))) {
      src = Uint8Array.from(input.map((v) => v & 0xff));
    }
  } else if (input && typeof input.length === "number" && typeof input !== "string") {
    // array-like (e.g. Buffer); guard against strings
    try { src = Uint8Array.from(input); } catch { src = null; }
  }

  if (src === null) {
    return { ok: false, bytes: out, reason: `expected ${BODY_BYTES} bytes, got non-byte input` };
  }
  const n = Math.min(src.length, BODY_BYTES);
  for (let i = 0; i < n; i++) out[i] = src[i] & 0xff;
  if (src.length === BODY_BYTES) return { ok: true, bytes: out, reason: "" };
  return {
    ok: false,
    bytes: out,
    reason: `expected ${BODY_BYTES} bytes, got ${src.length} (coerced)`,
  };
}

// The fixed node list. Order is the visual left-to-right order of the chain.
export function buildSchematicNodes() {
  const nodes = [
    { id: "morph", kind: "control", label: "Morph", inspectable: false },
    { id: "q", kind: "control", label: "Secondary / Q", inspectable: false },
    { id: "interp", kind: "interp", label: "Interp (4 corners)", inspectable: true },
  ];
  for (let s = 0; s < STAGES; s++) {
    nodes.push({
      id: `stage${s}`,
      kind: "stage",
      stageIndex: s,
      label: `S${s + 1}`, // 1-based text label; never colour-only identification
      inspectable: true,
    });
  }
  nodes.push({ id: "out", kind: "output", label: "Out", inspectable: true });
  return nodes;
}

// The real signal edges. kind:"signal" = audio path; kind:"control" = parameter
// path (drawn distinctly, e.g. dashed). Audio enters at stage0.
export const SCHEMATIC_EDGES = (() => {
  const edges = [
    { from: "in", to: "stage0", kind: "signal" },
    { from: "morph", to: "interp", kind: "control" },
    { from: "q", to: "interp", kind: "control" },
  ];
  for (let s = 0; s < STAGES - 1; s++) {
    edges.push({ from: `stage${s}`, to: `stage${s + 1}`, kind: "signal" });
  }
  edges.push({ from: `stage${STAGES - 1}`, to: "out", kind: "signal" });
  // interp parameterizes the whole stage block — draw to stage0 as the anchor.
  edges.push({ from: "interp", to: "stage0", kind: "control" });
  return edges;
})();
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `node forge-web/js/schematic-graph.test.mjs`
Expected: `OK schematic-graph` and exit code 0.

- [ ] **Step 5: Commit**

```bash
git add forge-web/js/schematic-graph.mjs forge-web/js/schematic-graph.test.mjs
git commit -m "feat(inspect): schematic graph builder + 240-byte validation (pure, tested)"
```

---

## Task 2: Live signal-chain math on top of `packed.js` (`signal-chain.mjs`)

**Files:**
- Create: `forge-web/js/signal-chain.mjs`
- Test: `forge-web/js/signal-chain.test.mjs`

Cumulative track-the-signal + per-stage contribution + closed-form pole radius ρ. All built on the canonical `packed.js` — no packed math re-derived.

- [ ] **Step 1: Write the failing test**

Create `forge-web/js/signal-chain.test.mjs`:

```js
import assert from "node:assert/strict";
import {
  wordsFromBytes,
  wordsAt,
  stageWordsToKernel,
  kernelToBiquad,
  biquadDbCoeffs,
} from "./packed.js";
import {
  stageBiquadsAt,
  cumulativeStageDb,
  stageContributionDb,
  poleRadius,
  STAGE_COUNT,
} from "./signal-chain.mjs";

// Build a deterministic body: 240 bytes with a simple repeating pattern so the
// kernels decode to finite biquads. (Exact dB values are not asserted — we assert
// STRUCTURE and the cumulative/contribution INVARIANTS, which is what the view promises.)
const bytes = new Uint8Array(240);
for (let i = 0; i < 240; i++) bytes[i] = (i * 37 + 11) & 0xff;
const words = wordsFromBytes(bytes);
const m = 0.5, q = 0.5;
const F = [60, 200, 800, 2400, 8000];

// --- stageBiquadsAt matches packed.js stage-by-stage (no re-derivation) ---
{
  const got = stageBiquadsAt(words, m, q);
  assert.equal(got.length, STAGE_COUNT);
  const ref = wordsAt(words, m, q).map((row) => kernelToBiquad(stageWordsToKernel(row)));
  for (let s = 0; s < STAGE_COUNT; s++) {
    for (let k = 0; k < 5; k++) {
      assert.equal(got[s][k], ref[s][k], `stage ${s} coeff ${k} must equal packed.js`);
    }
  }
}

// --- cumulativeStageDb: cumulative[k] == sum of stage contributions 0..k ---
{
  const bqs = stageBiquadsAt(words, m, q);
  for (const f of F) {
    const cum = cumulativeStageDb(bqs, f); // length STAGE_COUNT
    assert.equal(cum.length, STAGE_COUNT);
    let running = 0;
    for (let s = 0; s < STAGE_COUNT; s++) {
      running += biquadDbCoeffs(bqs[s], f);
      assert.ok(Math.abs(cum[s] - running) < 1e-9, `cumulative after stage ${s} @ ${f}Hz`);
    }
    // Final cumulative == full cascade dB (what a plain response plot shows).
    let full = 0;
    for (const bq of bqs) full += biquadDbCoeffs(bq, f);
    assert.ok(Math.abs(cum[STAGE_COUNT - 1] - full) < 1e-9, "final cumulative == cascade");
  }
}

// --- stageContributionDb: a single stage's own magnitude curve ---
{
  const bqs = stageBiquadsAt(words, m, q);
  const freqs = F;
  const curve = stageContributionDb(bqs, 2, freqs); // [{f, db}, ...]
  assert.equal(curve.length, freqs.length);
  for (let i = 0; i < freqs.length; i++) {
    assert.equal(curve[i].f, freqs[i]);
    assert.ok(Math.abs(curve[i].db - biquadDbCoeffs(bqs[2], freqs[i])) < 1e-9);
  }
}

// --- poleRadius: closed-form max |root| of z^2 + a1 z + a2 ---
{
  // Known case: a1=0, a2=0.81 -> complex roots, |root| = sqrt(0.81) = 0.9
  assert.ok(Math.abs(poleRadius(0, 0.81) - 0.9) < 1e-9);
  // Real distinct roots: z^2 - 0.7 z + 0.1 = (z-0.5)(z-0.2) -> max |root| = 0.5
  assert.ok(Math.abs(poleRadius(-0.7, 0.1) - 0.5) < 1e-9);
  // Degenerate a2=0 -> roots 0 and -a1 -> max |root| = |a1|
  assert.ok(Math.abs(poleRadius(-0.4, 0) - 0.4) < 1e-9);
  // Never NaN for finite input
  assert.ok(Number.isFinite(poleRadius(1.9, 0.95)));
}

// --- stability flag derivable: rho < 1 for a sane stage of this body ---
{
  const bqs = stageBiquadsAt(words, m, q);
  for (let s = 0; s < STAGE_COUNT; s++) {
    const rho = poleRadius(bqs[s][3], bqs[s][4]);
    assert.ok(Number.isFinite(rho), `rho finite for stage ${s}`);
  }
}

console.log("OK signal-chain");
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node forge-web/js/signal-chain.test.mjs`
Expected: FAIL — `Cannot find module './signal-chain.mjs'`.

- [ ] **Step 3: Write the implementation**

Create `forge-web/js/signal-chain.mjs`:

```js
// Live signal-chain math for the Inspect view. Built ENTIRELY on the canonical
// packed-16 codec in packed.js — this file re-derives NONE of the packed math.
import {
  wordsAt,
  stageWordsToKernel,
  kernelToBiquad,
  biquadDbCoeffs,
} from "./packed.js";

export const STAGE_COUNT = 6;

// The 6 live DF2T biquads [b0,b1,b2,a1,a2] at (morph, q), via packed.js verbatim.
export function stageBiquadsAt(words, morph, q) {
  return wordsAt(words, morph, q).map((row) => kernelToBiquad(stageWordsToKernel(row)));
}

// Cumulative magnitude (dB) AFTER each stage at frequency f.
// cum[k] = sum of stage dB contributions 0..k. cum[5] == full cascade dB.
// This is the "track the signal" surface: WHERE energy is shaped, not just the end.
export function cumulativeStageDb(biquads, f) {
  const cum = new Array(biquads.length);
  let running = 0;
  for (let s = 0; s < biquads.length; s++) {
    running += biquadDbCoeffs(biquads[s], f);
    cum[s] = running;
  }
  return cum;
}

// Cumulative curve after stage `k` across a frequency list -> [{f, db}, ...].
// Use index -1 (or any < 0) to mean "input" = flat 0 dB (incoming signal).
export function cumulativeCurve(biquads, stageIndex, freqs) {
  return freqs.map((f) => {
    if (stageIndex < 0) return { f, db: 0 };
    const cum = cumulativeStageDb(biquads, f);
    return { f, db: cum[Math.min(stageIndex, cum.length - 1)] };
  });
}

// One stage's OWN magnitude curve (its isolated contribution) -> [{f, db}, ...].
export function stageContributionDb(biquads, stageIndex, freqs) {
  const bq = biquads[stageIndex];
  return freqs.map((f) => ({ f, db: biquadDbCoeffs(bq, f) }));
}

// Closed-form stability margin: max |root| of z^2 + a1 z + a2 = 0.
// rho >= 1 is unstable (CLAUDE.md runtime gate). Never returns NaN for finite input.
export function poleRadius(a1, a2) {
  const disc = a1 * a1 - 4 * a2;
  if (disc < 0) {
    // complex conjugate roots: |root| = sqrt(a2) (a2 = product of roots' magnitudes^2)
    return Math.sqrt(Math.max(a2, 0));
  }
  const sq = Math.sqrt(disc);
  const r1 = Math.abs((-a1 + sq) / 2);
  const r2 = Math.abs((-a1 - sq) / 2);
  return Math.max(r1, r2);
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `node forge-web/js/signal-chain.test.mjs`
Expected: `OK signal-chain` and exit code 0.

- [ ] **Step 5: Commit**

```bash
git add forge-web/js/signal-chain.mjs forge-web/js/signal-chain.test.mjs
git commit -m "feat(inspect): cumulative/contribution dB + pole-radius rho on packed.js (tested)"
```

---

## Task 3: Evidence-derived plain-language describer (`describe-stage.mjs`)

**Files:**
- Create: `forge-web/js/describe-stage.mjs`
- Test: `forge-web/js/describe-stage.test.mjs`

Depth-1 of progressive transparency: one sentence whose Hz/dB are **read from a measured curve**, never invented (CLAUDE.md: OBSERVED, no invented numbers). The input is the stage's own contribution curve `[{f, db}, ...]` computed in Task 2.

- [ ] **Step 1: Write the failing test**

Create `forge-web/js/describe-stage.test.mjs`:

```js
import assert from "node:assert/strict";
import { describeStageFromCurve, formatHz } from "./describe-stage.mjs";

// formatHz: kHz above 1000, Hz below; rounded, never bogus precision.
assert.equal(formatHz(2400), "2.4 kHz");
assert.equal(formatHz(800), "800 Hz");
assert.equal(formatHz(55), "55 Hz");
assert.equal(formatHz(12000), "12 kHz");

// A clear boost: peak +6 dB at 2400 Hz -> "boosts ... ~2.4 kHz by ~6 dB".
{
  const curve = [
    { f: 200, db: 0 }, { f: 800, db: 1 }, { f: 2400, db: 6 }, { f: 8000, db: -1 },
  ];
  const s = describeStageFromCurve(curve, 3); // label "S3" -> 1-based via stageIndex+1? pass label text
  assert.match(s, /S3/);
  assert.match(s, /boost/i);
  assert.match(s, /2\.4 kHz/);
  assert.match(s, /6 dB/);
}

// A clear cut: deepest -8 dB at 800 Hz -> "cuts ... ~800 Hz by ~8 dB".
{
  const curve = [
    { f: 200, db: 0 }, { f: 800, db: -8 }, { f: 2400, db: -1 }, { f: 8000, db: 0 },
  ];
  const s = describeStageFromCurve(curve, 1);
  assert.match(s, /cut/i);
  assert.match(s, /800 Hz/);
  assert.match(s, /8 dB/);
}

// Essentially flat -> says "leaves the signal roughly unchanged", no fake numbers.
{
  const curve = [
    { f: 200, db: 0.1 }, { f: 800, db: -0.1 }, { f: 2400, db: 0.05 },
  ];
  const s = describeStageFromCurve(curve, 4);
  assert.match(s, /unchanged|flat/i);
  assert.doesNotMatch(s, /\d+ dB by/); // no invented magnitude claim
}

// Empty / malformed curve -> safe fallback string, never throws.
for (const bad of [[], null, undefined, [{ f: NaN, db: NaN }]]) {
  const s = describeStageFromCurve(bad, 0);
  assert.equal(typeof s, "string");
  assert.ok(s.length > 0);
}

console.log("OK describe-stage");
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node forge-web/js/describe-stage.test.mjs`
Expected: FAIL — `Cannot find module './describe-stage.mjs'`.

- [ ] **Step 3: Write the implementation**

Create `forge-web/js/describe-stage.mjs`:

```js
// Depth-1 plain language for the Inspect view. Every number is READ FROM the
// measured curve passed in — nothing is invented (CLAUDE.md: OBSERVED only).

const FLAT_DB = 1.0; // below this peak/dip magnitude the stage is "roughly unchanged"

export function formatHz(hz) {
  if (!Number.isFinite(hz) || hz <= 0) return "?";
  if (hz >= 1000) {
    const k = hz / 1000;
    // 1 decimal, but drop a trailing .0 (12.0 -> "12 kHz")
    const s = (Math.round(k * 10) / 10).toString();
    return `${s} kHz`;
  }
  return `${Math.round(hz)} Hz`;
}

// curve: [{f, db}, ...] = the stage's own contribution. stageLabelOrIndex is used
// only to name the stage in the sentence ("S3"); pass the 1-based number you show.
export function describeStageFromCurve(curve, stageNumber) {
  const label = `S${Number.isFinite(stageNumber) ? stageNumber : "?"}`;
  if (!Array.isArray(curve) || curve.length === 0) {
    return `${label}: no response data.`;
  }
  // Find measured extremes from valid samples only.
  let peak = null, dip = null;
  for (const p of curve) {
    if (!p || !Number.isFinite(p.f) || !Number.isFinite(p.db)) continue;
    if (peak === null || p.db > peak.db) peak = p;
    if (dip === null || p.db < dip.db) dip = p;
  }
  if (peak === null || dip === null) {
    return `${label}: no usable response data.`;
  }

  const boost = peak.db;
  const cut = -dip.db;
  if (boost < FLAT_DB && cut < FLAT_DB) {
    return `${label} leaves the signal roughly unchanged (flat to within ${FLAT_DB.toFixed(0)} dB).`;
  }
  // Report the larger-magnitude feature; it is the dominant audible move.
  if (boost >= cut) {
    return `${label} boosts around ${formatHz(peak.f)} by ~${Math.round(boost)} dB.`;
  }
  return `${label} cuts around ${formatHz(dip.f)} by ~${Math.round(cut)} dB.`;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `node forge-web/js/describe-stage.test.mjs`
Expected: `OK describe-stage` and exit code 0.

- [ ] **Step 5: Run all three module tests together (regression)**

Run:
```bash
node forge-web/js/schematic-graph.test.mjs && node forge-web/js/signal-chain.test.mjs && node forge-web/js/describe-stage.test.mjs
```
Expected: three `OK ...` lines, exit code 0.

- [ ] **Step 6: Commit**

```bash
git add forge-web/js/describe-stage.mjs forge-web/js/describe-stage.test.mjs
git commit -m "feat(inspect): evidence-derived plain-language stage describer (tested)"
```

---

## Task 4: Render the schematic layer + drill-down panel in `bench.html`

**Files:**
- Modify: `forge-web/build_bench.py`

Add the only genuinely-new rendering (the node graph) plus the three-depth drill-down panel, reusing the existing in-page `drawResp`/`drawZ`. The bench script writes `bench.html`; make its `<script>` a module so it can `import` the three `.mjs` files, and serve `forge-web/` so imports resolve.

> NOTE: keep all existing bench behavior (body select, Morph/Q sliders, play, response, z-plane, grid, safety, nums) intact. This task ADDS to the page; it removes nothing.

- [ ] **Step 1: Convert the page script to a module and import the modules**

In `forge-web/build_bench.py`, in the `TEMPLATE` string, change the opening script tag from:

```html
<script>
const SR=39062.5, TAU=Math.PI*2, STAGES=6, WORDS=5;
const BODIES = __BODIES__;
```

to:

```html
<script type="module">
import { buildSchematicNodes, SCHEMATIC_EDGES, validateBodyBytes } from "./js/schematic-graph.mjs";
import { stageBiquadsAt, cumulativeCurve, stageContributionDb, poleRadius, STAGE_COUNT } from "./js/signal-chain.mjs";
import { describeStageFromCurve } from "./js/describe-stage.mjs";
const SR=39062.5, TAU=Math.PI*2, STAGES=6, WORDS=5;
const BODIES = __BODIES__;
```

(The page already computes `bqsAt` inline for its own renderers; the imported `stageBiquadsAt` is byte-identical via `packed.js` and is what the schematic uses. Both coexist — no behavior change to the existing panels.)

- [ ] **Step 2: Add the schematic canvas + drill-down DOM**

In `forge-web/build_bench.py` `TEMPLATE`, immediately after the existing `<div id=nums></div>` line, insert:

```html
<div class=lab style="margin-top:14px">SIGNAL SCHEMATIC &nbsp;·&nbsp; the real chain you are hearing (read-only) &nbsp;·&nbsp; click a node</div>
<div class=wrap>
 <canvas id=schem width=760 height=150 tabindex=0 role=img aria-label="TRENCH signal schematic: Morph and Secondary into corner interpolation into six serial stages into output"></canvas>
 <div id=drill style="flex:1;min-width:320px;background:#0d1311;border:1px solid #1c2722;border-radius:5px;padding:10px 12px">
  <div id=drillPlain style="color:#cfe9df;font-size:13px;margin-bottom:6px">Click a node to inspect it.</div>
  <div id=drillWarn class=bad style="font-size:11px;margin-bottom:6px"></div>
  <button id=drillToggle style="display:none">show curve + poles/zeros + &rho;</button>
  <div id=drillDeep style="display:none;margin-top:8px">
   <canvas id=drillResp width=360 height=180></canvas>
   <canvas id=drillZ width=180 height=180></canvas>
   <div id=drillRho class=lab style="margin-top:4px"></div>
   <button id=drillCoeffsToggle style="margin-top:6px">show raw coefficients</button>
   <div id=drillCoeffs style="display:none;font-size:11px;white-space:pre;margin-top:6px;color:#9fb"></div>
  </div>
 </div>
</div>
```

Add to the `<style>` block (so control edges read differently from signal edges, and selection is shown by outline + label, not colour alone):

```css
 #schem{cursor:pointer}
 #schem:focus{outline:2px solid #5bef6f}
```

- [ ] **Step 3: Add the schematic renderer + interaction (new code)**

In `forge-web/build_bench.py` `TEMPLATE`, add the following just before the final `redraw();` call line at the end of the script (so the helpers are defined, then `redraw()` runs):

```js
// ---- SIGNAL SCHEMATIC (the only new rendering) ----
const schem = document.getElementById('schem');
const sx = schem.getContext('2d');
const NODES = buildSchematicNodes();
// Fixed left-to-right layout. Controls stacked on the far left, interp, then 6
// stages in a row, then out. Positions in canvas px; recomputed on each draw.
let SEL = 'out';        // selected node id (track-the-signal defaults to final)
let DEEP = false;       // depth-2 open?
let COEFFS = false;     // depth-3 open?
let nodeHits = [];      // [{id, x, y, w, h}] for hit-testing + keyboard order

function layoutNodes(W, H){
  const hits = [];
  const place = (id, x, y, w, h) => hits.push({ id, x, y, w, h });
  // controls (left column)
  place('morph', 8, 24, 92, 26);
  place('q',     8, 64, 92, 26);
  place('interp',112, 44, 96, 40);
  // 6 stages in a row
  const x0 = 224, gap = 78, sw = 64, sy = 44, sh = 40;
  for (let s = 0; s < 6; s++) place('stage'+s, x0 + s*gap, sy, sw, sh);
  place('out', x0 + 6*gap, sy, 60, sh);
  nodeHits = hits;
  return hits;
}
function nodeById(id){ return NODES.find(n => n.id === id); }
function hitAt(hits, id){ return hits.find(h => h.id === id); }

function drawSchem(bqs){
  const W = schem.width, H = schem.height;
  sx.clearRect(0,0,W,H);
  const hits = layoutNodes(W, H);
  // edges first
  for (const e of SCHEMATIC_EDGES){
    if (e.from === 'in') continue; // 'in' has no node box; draw a stub into stage0
    const a = hitAt(hits, e.from), b = hitAt(hits, e.to);
    if (!a || !b) continue;
    sx.strokeStyle = e.kind === 'control' ? '#3a5' : '#2a6a44';
    sx.lineWidth = e.kind === 'control' ? 1 : 1.6;
    sx.setLineDash(e.kind === 'control' ? [4,3] : []);
    sx.beginPath();
    sx.moveTo(a.x + a.w, a.y + a.h/2);
    sx.lineTo(b.x, b.y + b.h/2);
    sx.stroke();
  }
  sx.setLineDash([]);
  // audio-in stub
  const s0 = hitAt(hits, 'stage0');
  sx.strokeStyle = '#2a6a44'; sx.lineWidth = 1.6;
  sx.beginPath(); sx.moveTo(s0.x - 18, s0.y + s0.h/2); sx.lineTo(s0.x, s0.y + s0.h/2); sx.stroke();
  sx.fillStyle = '#56685e'; sx.font = '9px ui-monospace'; sx.textAlign='right';
  sx.fillText('audio in', s0.x - 20, s0.y + s0.h/2 + 3); sx.textAlign='left';
  // nodes
  for (const h of hits){
    const n = nodeById(h.id);
    const isStage = n.kind === 'stage';
    const stageRho = isStage ? poleRadius(bqs[n.stageIndex][3], bqs[n.stageIndex][4]) : null;
    const unstable = stageRho !== null && stageRho >= 1;
    // fill: stage colour for stages (identity), neutral for the rest
    sx.fillStyle = isStage ? STAGE[n.stageIndex] : '#1c3a2c';
    sx.globalAlpha = isStage ? 0.22 : 1;
    sx.fillRect(h.x, h.y, h.w, h.h);
    sx.globalAlpha = 1;
    // border — selection shown by THICK outline (not colour alone, a11y)
    sx.strokeStyle = unstable ? '#ff5a44' : (h.id === SEL ? '#fff' : '#2a5a3c');
    sx.lineWidth = h.id === SEL ? 2.5 : 1;
    sx.strokeRect(h.x, h.y, h.w, h.h);
    // text label (always present — never colour-only)
    sx.fillStyle = '#cfe9df'; sx.font = '11px ui-monospace'; sx.textAlign='center';
    sx.fillText(n.label, h.x + h.w/2, h.y + h.h/2 + 4);
    if (isStage){ sx.font='8px ui-monospace'; sx.fillStyle='#8aa';
      sx.fillText('ρ '+stageRho.toFixed(3), h.x + h.w/2, h.y + h.h - 4); }
  }
  sx.textAlign='left';
}

// Reuse the existing in-page response renderer for a single curve (the stage's
// own contribution OR the cumulative-through-stage curve). Draws on drillResp.
const dResp = document.getElementById('drillResp'), drx = dResp.getContext('2d');
const dZ = document.getElementById('drillZ');
function drawDrillCurve(curve){
  const W=dResp.width, H=dResp.height, DMX=24, DMN=-72;
  drx.clearRect(0,0,W,H);
  drx.strokeStyle='#243'; const y0=H-(0-DMN)/(DMX-DMN)*H;
  drx.beginPath(); drx.moveTo(0,y0); drx.lineTo(W,y0); drx.stroke();
  drx.strokeStyle='#dff'; drx.lineWidth=1.6; drx.beginPath();
  curve.forEach((p,i)=>{ const x=W*(Math.log10(p.f/40)/Math.log10(400));
    const y=H-(Math.max(DMN,Math.min(DMX,p.db))-DMN)/(DMX-DMN)*H; i?drx.lineTo(x,y):drx.moveTo(x,y); });
  drx.stroke();
}

function refreshDrill(bqs){
  const n = nodeById(SEL);
  const plain = document.getElementById('drillPlain');
  const toggle = document.getElementById('drillToggle');
  const deep = document.getElementById('drillDeep');
  const rhoEl = document.getElementById('drillRho');
  const coeffsEl = document.getElementById('drillCoeffs');
  const FR=[]; for(let i=0;i<440;i++) FR.push(40*Math.pow(400,i/439));

  if (n.kind === 'stage'){
    const si = n.stageIndex;
    const own = stageContributionDb(bqs, si, FR);
    plain.textContent = describeStageFromCurve(own, si+1)
      + '  (cumulative: this is where stage '+(si+1)+' shapes the running signal)';
    toggle.style.display='';
    toggle.textContent = DEEP ? 'hide curve + poles/zeros + ρ' : 'show curve + poles/zeros + ρ';
    deep.style.display = DEEP ? '' : 'none';
    if (DEEP){
      // depth-2: cumulative-through-this-stage curve + this stage's poles/zeros + rho
      drawDrillCurve(cumulativeCurve(bqs, si, FR));
      drawZ.call(null, [bqs[si]], dZ);  // reuse z-plane renderer for one stage
      const rho = poleRadius(bqs[si][3], bqs[si][4]);
      rhoEl.innerHTML = 'stability ρ = <b>'+rho.toFixed(4)+'</b> '
        + (rho>=1?'<span class=bad>UNSTABLE (ρ≥1)</span>':'<span class=ok>stable</span>');
      const [b0,b1,b2,a1,a2]=bqs[si];
      coeffsEl.textContent = 'b0='+b0.toFixed(6)+'  b1='+b1.toFixed(6)+'  b2='+b2.toFixed(6)
        +'\na1='+a1.toFixed(6)+'  a2='+a2.toFixed(6);
      document.getElementById('drillCoeffs').style.display = COEFFS ? '' : 'none';
      document.getElementById('drillCoeffsToggle').textContent = COEFFS ? 'hide raw coefficients' : 'show raw coefficients';
    }
  } else if (n.id === 'interp'){
    plain.textContent = 'Interp blends 4 corners (C0=LOW.Q0, C1=HIGH.Q0, C2=LOW.Q100, C3=HIGH.Q100) '
      + 'morph-first, then Secondary. Now at Morph '+(M*100).toFixed(0)+'%, Secondary '+(Q*100).toFixed(0)+'%.';
    toggle.style.display='none'; deep.style.display='none';
  } else if (n.id === 'out'){
    const full = cumulativeCurve(bqs, STAGE_COUNT-1, FR);
    plain.textContent = 'Output: the full cascade after all 6 stages (this is the final response curve).';
    toggle.style.display=''; deep.style.display = DEEP ? '' : 'none';
    toggle.textContent = DEEP ? 'hide final curve' : 'show final curve';
    if (DEEP){ drawDrillCurve(full); dZ.getContext('2d').clearRect(0,0,dZ.width,dZ.height);
      rhoEl.textContent=''; document.getElementById('drillCoeffs').style.display='none'; }
  } else {
    plain.textContent = (n.id==='morph' ? 'Morph' : 'Secondary / Q')
      + ' is a control input — it parameterizes the corner interpolation. Now at '
      + (n.id==='morph' ? (M*100).toFixed(0) : (Q*100).toFixed(0)) + '%.';
    toggle.style.display='none'; deep.style.display='none';
  }
}

document.getElementById('drillToggle').onclick = ()=>{ DEEP=!DEEP; redraw(); };
document.getElementById('drillCoeffsToggle').onclick = ()=>{ COEFFS=!COEFFS; redraw(); };

schem.addEventListener('click', (ev)=>{
  const r = schem.getBoundingClientRect();
  const px = (ev.clientX-r.left)*(schem.width/r.width);
  const py = (ev.clientY-r.top)*(schem.height/r.height);
  for (const h of nodeHits){
    if (px>=h.x && px<=h.x+h.w && py>=h.y && py<=h.y+h.h){
      if (h.id!==SEL){ SEL=h.id; DEEP=false; COEFFS=false; } redraw(); schem.focus(); return;
    }
  }
});
// Keyboard navigation: arrows move selection along the node order; Enter toggles depth-2.
schem.addEventListener('keydown', (ev)=>{
  const order = nodeHits.map(h=>h.id);
  let i = order.indexOf(SEL); if (i<0) i=0;
  if (ev.key==='ArrowRight'||ev.key==='ArrowDown'){ i=Math.min(order.length-1,i+1); SEL=order[i]; DEEP=false; COEFFS=false; ev.preventDefault(); redraw(); }
  else if (ev.key==='ArrowLeft'||ev.key==='ArrowUp'){ i=Math.max(0,i-1); SEL=order[i]; DEEP=false; COEFFS=false; ev.preventDefault(); redraw(); }
  else if (ev.key==='Enter'||ev.key===' '){ DEEP=!DEEP; ev.preventDefault(); redraw(); }
});
```

- [ ] **Step 4: Make `drawZ` reusable on an arbitrary canvas and a subset of stages**

The existing `drawZ(bqs)` draws onto the fixed `zc` canvas. To reuse it for the single-stage drill-down on the `drillZ` canvas, generalize it to accept an optional target canvas. In `forge-web/build_bench.py` `TEMPLATE`, change the `drawZ` signature line from:

```js
function drawZ(bqs){const W=zc.width,cx=W/2,cy=W/2,R=W*0.42;zx.clearRect(0,0,W,W);
```

to:

```js
function drawZ(bqs,targetCanvas){const cnv=targetCanvas||zc;const ctx2=cnv.getContext('2d');const W=cnv.width,cx=W/2,cy=W/2,R=W*0.42;ctx2.clearRect(0,0,W,W);
```

Then within `drawZ`, replace every remaining use of `zx` with `ctx2`. (There are ~12 `zx.` references in the function body; replace them all. The default `targetCanvas` undefined → uses `zc`/`ctx2`-on-`zc`, so the existing main z-plane panel is unchanged.)

> Verification that this refactor is safe is the manual step below: the main z-plane must look identical, and the drill-down z-plane must render one stage's poles/zeros.

- [ ] **Step 5: Wire the schematic into the live `redraw()`**

In `forge-web/build_bench.py` `TEMPLATE`, change the existing `redraw()` body from:

```js
function redraw(){const bqs=bqsAt(cur.words,M,Q);drawResp(bqs);drawZ(bqs);drawNums(bqs);drawGrid();safety();if(playing)rebuildAudio(bqs);}
```

to:

```js
function redraw(){
 // validate the body bytes to 240 (never throw); warn in the drill panel if coerced
 const warn=document.getElementById('drillWarn');
 if(cur && cur.bytes){const v=validateBodyBytes(cur.bytes); if(warn) warn.textContent=v.ok?'':('body bytes: '+v.reason);}
 else if(warn){warn.textContent='';}
 const bqs=bqsAt(cur.words,M,Q);
 drawResp(bqs);drawZ(bqs);drawNums(bqs);drawGrid();safety();
 const schemBqs=stageBiquadsAt(cur.words,M,Q); // packed.js-backed, == bqs
 drawSchem(schemBqs); refreshDrill(schemBqs);
 if(playing)rebuildAudio(bqs);
}
```

(Existing bodies carry `words` not `bytes`; the `cur.bytes` guard is a no-op for them and exercises validation only when a body is loaded as raw bytes — the validator never throws either way.)

- [ ] **Step 6: Build the page**

Run: `python forge-web/build_bench.py`
Expected: `wrote <repo>/forge-web/bench.html  (N bodies, K KB, self-contained)` with a non-zero N.

- [ ] **Step 7: MANUAL verification (open in a browser)**

Because the page now uses ES-module imports, serve the folder (file:// blocks module imports):

```bash
python -m http.server 8130 --directory forge-web
```
Then open `http://localhost:8130/bench.html`.

Verify, in order:
1. **Existing panels unchanged:** body dropdown, Morph/Q sliders, response curve, z-plane (numbered S1–S6), Morph×Q grid, safety strip, nums — all render exactly as before. (Regression check on the `drawZ` refactor: the main z-plane looks identical.)
2. **Schematic present:** below `nums`, a horizontal graph: `Morph` / `Secondary/Q` (left, dashed control edges) → `Interp (4 corners)` → `S1 … S6` (solid signal edges, audio-in stub) → `Out`. Each stage box shows its `ρ` value and a stage-coloured fill with a text `S#` label.
3. **Click a stage (e.g. S3):** the drill panel's depth-1 line reads an evidence sentence like "S3 boosts around ~X kHz by ~Y dB" where X/Y match the visible response peak; selection shows as a thick white outline on S3.
4. **Depth-2:** click "show curve + poles/zeros + ρ" → a curve (cumulative through S3), a one-stage z-plane, and "stability ρ = …" appear.
5. **Depth-3:** click "show raw coefficients" → `b0 b1 b2 a1 a2` appear; click again to hide. (Numbers hidden by default, one click away, never removed.)
6. **Track-the-signal:** click S1 then S2 then S6 with depth-2 open; the curve grows the cumulative shaping (S6 == the full response shown in the main panel).
7. **Interp node:** click `Interp` → text names the 4 corners (C0..C3) and the current Morph/Secondary blend %, with no curve (it is not a stage).
8. **Live:** move the Morph slider while a stage is selected with depth-2 open → the schematic ρ values, the drill curve, and the evidence sentence all update.
9. **Accessibility:** click the schematic to focus it (green focus ring), then use Left/Right arrows to move selection node-to-node and Enter to toggle depth-2 — no mouse needed. Confirm stage identity is readable from the `S#` text label (not colour alone).

Expected: all nine behaviors hold. If module imports fail, confirm you are loading over `http://localhost:8130`, not `file://`.

- [ ] **Step 8: Re-run the unit tests (no regression in the modules)**

Run:
```bash
node forge-web/js/schematic-graph.test.mjs && node forge-web/js/signal-chain.test.mjs && node forge-web/js/describe-stage.test.mjs
```
Expected: three `OK ...` lines.

- [ ] **Step 9: Commit**

```bash
git add forge-web/build_bench.py forge-web/bench.html
git commit -m "feat(inspect): live signal schematic in bench — node graph + 3-depth drill-down"
```

---

## Self-Review

**Spec coverage (against `2026-06-19-trench-ui-layout-loop-design.md`, "Inspect view" + its Definition of done):**
- Node graph of the real chain (Morph/Q → interp(4 corners) → 6 stages → out) → Task 1 (`buildSchematicNodes`/`SCHEMATIC_EDGES`) + Task 4 (`drawSchem`).
- Built by extending `forge-web/bench`; reuses curve/z-plane renderers + the packed codec → Task 4 reuses `drawResp` math + `drawZ` (generalized) + `packed.js`.
- Reads live coeffs/ρ verbatim; reimplements no packed math → Task 2 is entirely on top of `packed.js`; ρ is closed-form from `a1,a2` (allowed cheap math per the reuse ledger), not a packed re-derivation.
- **Schematic, not a node editor** → fixed `buildSchematicNodes`/`SCHEMATIC_EDGES`, no drag/rewire; test asserts no stage→earlier-stage edge (no cycles).
- Click a stage → poles/zeros + `b0..b2,a1,a2` + stage curve + ρ → Task 4 depths 2 & 3.
- Click interp node → 4 corners + (Morph,Secondary) blend shown → Task 4 `refreshDrill` interp branch.
- Track-the-signal (cumulative after each stage) → Task 2 `cumulativeCurve`/`cumulativeStageDb` + Task 4 depth-2 uses cumulative.
- Progressive transparency, 3 depths, numbers hidden-by-default/one-click-away/never-removed → Task 3 (depth-1 sentence) + Task 4 toggles (depth-2, depth-3).
- Evidence-first: plain language derived from measured curve, no invented Hz/dB → Task 3 reads extremes from the curve; test forbids invented magnitude on flat input.
- Live as Morph/Secondary change → Task 4 Step 5 wires schematic into `redraw()`.
- Keyboard-operable; colour never the sole signal → Task 4 keydown navigation + `S#` text labels + selection-by-outline; canvas `role=img`/`aria-label`.
- Handles malformed/short body bytes without throwing (validate to 240) → Task 1 `validateBodyBytes` (tested: short/long/null/non-array) + Task 4 Step 5 surfaces the reason.

**Out of scope (correctly excluded):** in-plugin layout edit mode, render/scene/validator C++ tool, AI suggestions, and porting the schematic into the C++ plugin — each is a separate plan; the spec marks the C++ port as an explicit later step.

**Placeholder scan:** no TBD/TODO; every code step shows complete code (full modules, full `drawSchem`/`refreshDrill`, exact template edits); every command has expected output. ✓

**Consistency:** module names (`schematic-graph.mjs`, `signal-chain.mjs`, `describe-stage.mjs`), exports (`validateBodyBytes`, `buildSchematicNodes`, `SCHEMATIC_EDGES`, `stageBiquadsAt`, `cumulativeCurve`, `cumulativeStageDb`, `stageContributionDb`, `poleRadius`, `STAGE_COUNT`, `describeStageFromCurve`, `formatHz`), node ids (`morph`, `q`, `interp`, `stage0..5`, `out`), and the four corner keys (`M0_Q0`, `M100_Q0`, `M0_Q100`, `M100_Q100`, from `packed.js`) are used identically across tasks and tests. The `drawZ(bqs, targetCanvas)` refactor is consumed by Task 4's drill-down and is regression-checked by manual Step 7.1. ✓

**Accessibility / validation (not cut):** validation lives in `validateBodyBytes` (coerce, never throw) with explicit short/long/null/non-array tests, and is surfaced (not swallowed) via `drillWarn`. Accessibility: keyboard node navigation (arrows + Enter), visible focus ring, text `S#` labels + outline-based selection (never hue-only), canvas `aria-label`. Stability ρ is shown per stage and flagged red when ρ≥1 (the CLAUDE.md runtime gate). ✓
