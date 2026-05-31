## Why the 8-Corner Cube is Flawed

The 8-corner cube should be torn down as the primary Forge/body representation. It may be useful as a candidate generator or temporary thought experiment, but it is mathematically and workflow-mismatched to DF2’s actual product surface.

### 1. Mathematical dimensional mismatch: the product is 2D, the cube is 3D

**OBSERVED:** The shipped consumer surface is `TYPE + MORPH + SECONDARY`. For one `TYPE`, the listener controls only two continuous dimensions: `MORPH` and `SECONDARY`.

An 8-corner cube defines a trilinear object:

\[
F(x,y,z)
\]

with three hidden axes. But the product only supplies:

\[
G(t,s)
\]

where `t = MORPH` and `s = SECONDARY`.

So the cube must do one of three things:

1. **Fix `z` to a constant.**  
   Then the cube collapses into one interpolated 2D slice. The unused corners are authoring baggage.

2. **Invent a hidden mapping `z = f(t,s)`.**  
   Then a non-performable hidden dimension changes the sound. The author is no longer approving exactly what the user controls; the author is approving a hidden path through a volume.

3. **Expose the whole cube internally while only shipping two controls.**  
   Then most of the cube is unreachable, or worse, indirectly influential without being explicitly auditioned.

In all three cases, the true audible object is not the cube. The true audible object is some 2D surface through or inside the cube. The cube adds a dimension the product does not have.

### 2. It multiplies the known interpolation failure

**OBSERVED:** Excellent endpoint/corner states can produce a poor interpolated middle because interpolation is occurring in a coefficient/encoded state domain, not directly in perceptual response space.

A 4-corner plane already has the central failure mode:

- good corners,
- bad center,
- weak sweeps,
- level loss,
- collapsed character,
- misleading static audition.

An 8-corner cube increases the number of relationships that can fail:

- 8 static corners,
- 12 edges,
- 6 faces,
- face centers,
- body center,
- diagonals,
- hidden cross-blends.

At the cube center, all eight corners contribute. If those eight full zero-bearing 6-SOS states are not mutually compatible, the center can become an average of unrelated filter actors rather than a coherent body.

Because zeros are first-class audible material, this is especially risky. The cube does not merely blend “tone.” It blends numerator and denominator behavior: resonances, notches, cancellations, phase behavior, gain interactions, and drive response. More corners do not create more musical certainty. They create more ways for a strong static set to produce a weak trajectory.

### 3. It confuses `SECONDARY` into a hidden type selector

**OBSERVED:** `TYPE` selects one authored body. `MORPH` and `SECONDARY` perform inside that body.

A cube encourages the author to think in terms of abstract axes:

- X = one kind of change,
- Y = another kind of change,
- Z = some hidden expansion, anchor family, intensity layer, or alternate actor.

That is not the consumer contract.

For DF2, `SECONDARY` should be one coherent performance verb inside the selected body. If the cube’s third dimension contains another identity, another family, or another contrast, the author has accidentally hidden extra `TYPE` behavior inside one `TYPE`.

That limits the author because the work shifts from:

> “Does this body feel iconic under MORPH and SECONDARY?”

to:

> “How do I rationalize eight corners and a hidden axis?”

That is the wrong mental model for one author trying to make 4–7 exceptional bodies by ear.

### 4. It creates a bad authoring workflow: corner collection instead of trajectory approval

The cube seduces the author into filling corners. But the supplied evidence says the failure point is not static corner quality; it is trajectory quality.

A cube-oriented Forge would naturally prioritize:

- finding impressive corners,
- naming or arranging hidden axes,
- expanding anchors,
- browsing volume-like structures,
- trusting the visual metaphor.

But the actual task is:

- audition the reachable surface,
- hear the middle,
- hear the sweeps,
- hear the diagonals,
- hear clean and driven behavior,
- lock only what survives.

For a private one-author bench, the cube is too much structure in the wrong place. It increases cognitive load, visual complexity, and QA burden without proving that the listener gets a better `MORPH` / `SECONDARY` body.

### 5. If the cube is constrained enough to be safe, it stops being a cube

A cube advocate can try to rescue the design by saying:

> “We will author a path or surface through the cube.”

But then the actual body is that path or surface, not the cube.

If the author must explicitly audition the 2D reachable surface, approve its cells, and bake only that surface, then the cube has become proposal infrastructure. It should not be the body representation.

---

# Evidence Status Used for the Decision

## OBSERVED facts from the supplied evidence

- DF2 ships as a **VST3 insert FX**.
- The consumer surface is **`TYPE + MORPH + SECONDARY`**.
- `TYPE` selects one authored body.
- `MORPH` and `SECONDARY` perform inside that body.
- The goal is **4–7 original iconic bodies**, not a large preset library.
- The Forge is private/internal and is not a shipped general preset editor.
- The human ear is the taste authority.
- AI and mathematical systems may propose raw material, diagnostics, bridges, sparse candidates, and warnings.
- AI must not silently approve, assemble, or publish finished bodies.
- Third-party coefficients, names, extracted bytes, reverse-engineered artifacts, and copied preset material are disallowed.
- The baseline filter is a cascade of **6 second-order sections**.
- Each section stores numerator and denominator information: `b0,b1,b2,a1,a2`.
- Zeros matter. Pole-only modeling was rejected because it produced misleading low-pass-like renders.
- The current 4-corner plane is a **240-byte packed plane** using encoded-domain interpolation.
- Encoded-domain interpolation is used because naive direct-form denominator interpolation can warp pole paths and cause level loss during morphs.
- Encoded-domain interpolation is still not proven to be perceptually ideal.
- Static corners can be rendered, clustered, audited, and browsed.
- Excellent static corners can produce poor interpolated middles.
- Clean and driven previews answer different listening questions.
- A pre-cascade saturator plus automatic-gain / drive stage materially shapes perceived character.
- Authoring happens at a fixed internal rate; the supplied correction states the actual authoring rate is **39062.5 Hz**.
- Runtime resamples around the internal rate.
- A zero-bearing static candidate corpus/quarry exists or is intended.
- The quarry’s static-state quality does not prove body-trajectory quality.

## ENGINEERING INFERENCE

The correct Forge representation should be the smallest auditable object that matches the actual product controls:

> one `TYPE` = one explicitly auditioned `MORPH × SECONDARY` performance surface made of complete zero-bearing engine states.

The body should not be a cube, graph, embedding, modifier stack, or hidden manifold. Those can suggest material, but the shipped/auditioned body should be the actual 2D surface the listener controls.

## SPECULATION

My expectation is that many successful bodies will fit into a very small surface: often a 2×2 plane, a 3×2 two-rail surface, or occasionally a slightly larger surface. That expectation is plausible but not proven. It remains **[NEEDS VERIFICATION]**.

---

# 1. Concise Verdict: Rebuild the Forge Around a Rail-First Ear-Locked 2D Surface

## ENGINEERING INFERENCE — final recommendation

The rebuilt Forge should use a:

> **rail-first, ear-locked adaptive `MORPH × SECONDARY` surface of complete zero-bearing states.**

In plain language:

1. Build the main `MORPH` story first.
2. Define `SECONDARY` as one coherent performance verb.
3. Build a matching secondary deviation rail.
4. Audition the actual 2D surface the consumer will play.
5. Lock stations and cells only by human ear.
6. Bake the smallest passing representation.

This is a stricter version of “station-locked sheet”:

- not a fixed 5×3 grid,
- not a general 2D preset editor,
- not a cube slice,
- not a learned latent map,
- not an automatic modifier system,
- not a graph traversal.

The correct body object is:

> a compact piecewise 2D control surface in the actual public control coordinates.

Each station stores a complete zero-bearing filter state. The initial interpolation parameterization should use the existing complete packed/encoded engine state path as the baseline so the first test isolates representation from parameterization. But the packed plane is not doctrine. It is the degenerate 2×2 case and the first comparison target.

If a simple 2×2 plane passes blind listening, bake the simple plane.

If it fails but a small adaptive surface passes, bake the small adaptive surface.

If even the adaptive surface repeatedly needs many knots to avoid failure, do not keep expanding the grid forever. Suspect one of these instead:

- the candidate states,
- the interpolation parameterization,
- the drive/headroom interaction,
- the body brief,
- or the attempted `SECONDARY` verb.

The Forge should therefore be rebuilt as a **body audition and locking bench**, not as a cube editor.

---

# 2. Strongest Alternatives and What Each Gets Wrong

| Candidate representation | What it gets right | What it gets wrong | Decision |
|---|---|---|---|
| **Simple 4-corner plane** | Smallest possible 2-control body. Already aligned with `MORPH × SECONDARY`. Easy to bake and QA. | Static corner quality does not prove the middle. One global bilinear interpolation can collapse character, lose level, or blur zero/pole relationships. | Keep as the baseline and degenerate bake target. It can win per body, but it must win blind. |
| **8-corner cube** | Gives the illusion of richer hidden structure. May produce interesting candidate contrasts. | Adds a hidden third dimension the product does not expose. Multiplies interpolation failure. Encourages corner collection over trajectory approval. | Reject as body representation. Proposal/debug only, if used at all. |
| **Anchor-expanded cube** | More disciplined than arbitrary cube filling. Anchors can preserve intentional landmarks. | Assumes expansion preserves identity. The expansion axes may not commute perceptually. Once the reachable surface is auditioned, the cube is irrelevant. | Use only to propose candidate stations or rails. Bake the resulting approved 2D surface, not the cube. |
| **Anchor-only body** | Human-selected anchors are useful. Avoids raw parameter editing. | Anchors alone do not prove trajectories. Endpoint and station approval does not prove cell centers, sweeps, or diagonals. | Use anchors as locked stations, not as the whole representation. |
| **Endpoint spine / 1D morph rail** | Correctly emphasizes the main `MORPH` story. Very small. | Ignores `SECONDARY` as a full performance dimension. Can repeat the known endpoint-middle failure if not station-audited. | Use as the first authoring step, then extend to secondary rail and cell audit. |
| **Ribbon** | Good metaphor for “one body with one main story and one controlled deviation.” | If it is only a visual curve or hidden path, it hides the same interpolation risks. | Accept only when formalized as actual locked stations and approved cells in `MORPH × SECONDARY`. |
| **General station-locked sheet** | Honest: it matches the public 2D controls and exposes the playable middle. | If treated as a fixed grid or mini preset editor, it bloats fast and weakens the body concept. A fixed 5×3 is not proven. | Use a rail-first adaptive version only. Start sparse. Add structure only after audible failure. |
| **Actor-preserving modifier system** | Potentially compact. Could make `SECONDARY` coherent if the modifier truly preserves identity. | “Preserving the actor” is a perceptual claim, not a math guarantee. Modifiers can break zeros, phase behavior, gain, drive response, or morph identity. | Candidate-generation tool only. Approved output must be baked into explicit states/cells. |
| **Graph-backed path/ribbon** | Useful for finding bridge states, nearest contrasts, sparse regions, and alternatives. | A graph is not a continuous performance surface. Graph distance is not guaranteed to equal musical morph quality. | Use as search infrastructure. Do not let the graph define runtime motion. |
| **Analytical behavior embedding** | Valuable for quarry novelty search, duplicate control, outlier discovery, and retrieval. | Descriptor smoothness does not guarantee coefficient-interpolation smoothness or musical trajectory. Visible projections are lossy. | Use below the Forge for candidate search and diagnostics. Never as body authority. |
| **Learned audio embedding** | Could find perceptual relationships missed by hand-built descriptors. | May cluster by probe content, level, or broad timbre rather than filter character. Legal/clean-room acceptability and usefulness are unproven. | Optional future advisory coordinate only after a controlled test. |
| **Response-space interpolation** | Theoretically attractive because it targets sounded curves more directly. | Stable reconstruction into the actual zero-bearing 6-SOS runtime with preserved phase/drive behavior is unresolved in the supplied evidence. | Separate R&D path. Do not base the Forge rewrite on it now. |
| **Pole/zero/gain interpolation** | More semantically meaningful than raw direct-form coefficients. Preserves the fact that zeros matter. | Requires section matching, angle wrapping, gain policy, handling of zeros outside/near the unit circle, and proof that motion sounds better. | Worth a later parameterization bakeoff if packed/encoded interpolation repeatedly fails. |
| **Rail-first adaptive 2D surface** | Matches the product controls, starts minimal, forces audition of the middle, preserves full states, and keeps human taste central. | Can still bloat if the author keeps adding knots instead of killing weak bodies. Still depends on interpolation parameterization. | Recommended architecture. |

---

# 3. Recommended Representation

## ENGINEERING INFERENCE

Each `TYPE` body should be represented as a compact approved surface in the actual `MORPH × SECONDARY` space.

Conceptually, one body contains:

- body brief,
- clean-room provenance,
- `MORPH` knot positions,
- `SECONDARY` knot positions,
- complete zero-bearing station states,
- approval status for each local cell,
- deterministic render/audition records,
- optional human-approved control remap,
- final bake target.

A **station** is not a raw parameter point shown to the human. It is an audible state at a specific `MORPH` / `SECONDARY` coordinate.

A **cell** is the local four-station region between neighboring knots. The cell is only valid if its holds, sweeps, center, and relevant gestures have been audition-approved.

Runtime/evaluation concept:

1. Receive public `MORPH` and `SECONDARY`.
2. Locate the approved local cell.
3. Interpolate the four complete encoded station states for that cell.
4. Decode through the real engine path.
5. Process through the actual filter/drive/gain behavior.
6. Apply any approved smoothing/remapping only if separately auditioned.

The key architectural rule:

> The body is the approved audible surface, not the proposal mechanism that found it.

## Important correction versus a naive “sheet” recommendation

Do **not** build a general 2D editor where the author paints arbitrary states.

The recommended workflow is rail-first:

1. First make the base `MORPH` rail strong.
2. Then define one coherent `SECONDARY` verb.
3. Then build the high-secondary rail.
4. Then only add extra knots or lanes where the actual rendered middle fails.

This prevents `SECONDARY` from becoming “another preset selector” and prevents the sheet from becoming a hidden library.

## What happens to the current 240-byte plane?

The existing 240-byte plane should be treated as:

- an observed incumbent,
- a useful baseline,
- the degenerate 2×2 body case,
- a bake target when it passes.

It should **not** be treated as doctrine.

If the smallest listening bakeoff shows that the best bodies need more than one global 4-corner plane, the runtime/body format should support compact piecewise surfaces. The existing implementation is useful only if it carries the winning bodies.

---

# 4. Exact Authoring Sequence for One Body: From Quarry to Baked `TYPE`

This is the recommended sequence for one body. It assumes the quarry supplies original zero-bearing static states, but the body Forge remains a separate, smaller bench.

## Step 0 — Open a clean-room body session

**Goal:** Start one original `TYPE` candidate with a clear artistic intention and clean provenance.

**AI may propose:**

- generic descriptive language,
- possible broad emotional directions,
- possible search prompts for the quarry,
- warnings if the brief sounds like multiple bodies.

**Math derives:**

- empty body record,
- provenance ledger,
- internal sample-rate/render settings,
- clean-room source checks.

**Human decides:**

- whether this body is worth starting,
- the initial body brief,
- the audition material,
- what “too derivative” or “not this body” means for the session.

**Exit condition:**  
One clean-room body brief exists. No external coefficients, copied names, extracted bytes, or third-party artifacts enter the session.

---

## Step 1 — Pull static raw material from the quarry

**Goal:** Assemble a small audition tray of original static zero-bearing candidate states.

**Quarry/math derives:**

- hard-valid 6-SOS zero-bearing states,
- packed/encoded export through the real engine-owned path,
- response descriptors,
- novelty/sparsity scores,
- duplicate warnings,
- outlier trays,
- clean and driven static previews,
- authoring-rate validation at the stated internal rate.

**AI may propose:**

- generator mutations,
- sparse-region probes,
- sibling searches around human-starred states,
- contrasting candidates,
- bridge-candidate searches.

**Human decides:**

- star,
- maybe,
- reject,
- “more like this,”
- “less like this,”
- which states have enough emotional charge to enter body authoring.

**Exit condition:**  
A short candidate shelf exists. These are not yet body stations. They are raw material.

---

## Step 2 — Choose the main `MORPH` contrast

**Goal:** Find the primary story of the body.

**Human decides:**

- rough `MORPH = 0` home candidate,
- rough `MORPH = 1` away candidate,
- whether the contrast feels like one body rather than two unrelated ideas.

**AI may propose:**

- candidate pairings,
- likely bridges,
- alternate away states,
- warnings about likely weak middle behavior.

**Math derives:**

- direct clean sweep,
- direct driven sweep,
- midpoint hold,
- level/headroom warnings,
- response-change diagnostics,
- duplicate/similarity warnings.

**Human decides after listening:**

- keep the pair,
- replace one endpoint,
- search for a bridge,
- abandon the contrast.

**Exit condition:**  
A main `MORPH` direction exists, or the body is killed early.

---

## Step 3 — Lock the base `MORPH` rail

**Goal:** Make the primary `MORPH` rail musically strong before adding `SECONDARY`.

Start with the smallest possible rail:

- `MORPH = 0`
- `MORPH = 1`

Render the direct midpoint and sweep.

If the direct midpoint is strong, do **not** insert a station just for symmetry.

If the direct midpoint fails, add a bridge station, usually near:

- `MORPH = 0.5`

Then audition the two local segments.

Add `0.25`, `0.75`, or other knots only when a specific local segment fails or when the author deliberately wants a staged transformation.

**AI may propose:**

- bridge states,
- replacements for weak stations,
- forks of the rail,
- nearby variants of a strong station.

**Math derives:**

- local midpoint holds,
- local sweeps,
- clean/driven comparisons,
- headroom warnings,
- collapse/popping/level-loss warnings,
- response and pole/zero advisory diagnostics.

**Human decides:**

- lock station,
- replace station,
- add knot,
- fork the rail,
- reject the rail.

**Exit condition:**  
The base `MORPH` rail works by ear clean and driven.

---

## Step 4 — Define the `SECONDARY` verb

**Goal:** Prevent `SECONDARY` from becoming another hidden `TYPE`.

The human must be able to complete the sentence:

> “In this body, `SECONDARY` adds ______.”

Acceptable internal descriptors are generic:

- pressure,
- bite,
- hollowing,
- weight,
- openness,
- tearing,
- edge,
- density,
- airlessness,
- nasal focus,
- smear,
- strain.

No third-party preset names or copied categories should be used.

**AI may propose:**

- candidate verbs based on starred states,
- possible deviations around the locked morph rail,
- warnings if the proposed secondary direction sounds like a separate body.

**Math derives:**

- similarity-to-base diagnostics,
- driven-risk warnings,
- response-change summaries.

**Human decides:**

- the `SECONDARY` meaning,
- the acceptable intensity range,
- whether the idea should instead become another `TYPE`.

**Exit condition:**  
One clear `SECONDARY` verb exists.

---

## Step 5 — Build the high-secondary rail

**Goal:** Create the `SECONDARY = 1` version of the locked base rail.

For each locked `MORPH` station on the base rail, find a corresponding deviated state at high `SECONDARY`.

The high rail should feel like the same body under a stronger or different condition, not a new body.

**AI may propose:**

- deviated states for each station,
- families of deviations,
- matching high-rail candidates,
- replacement candidates where the deviation breaks identity.

**Math derives:**

- vertical `SECONDARY` sweeps at each `MORPH` station,
- high-secondary `MORPH` sweep,
- midpoint holds between low/high rails,
- clean/driven render comparisons,
- level/headroom warnings,
- coherence diagnostics.

**Human decides:**

- whether each high-secondary station preserves the body,
- whether `SECONDARY` remains a coherent verb,
- whether a station should be replaced,
- whether the secondary idea should split into another `TYPE`.

**Exit condition:**  
A two-rail candidate exists: base rail plus high-secondary rail.

---

## Step 6 — Audit the actual 2D surface

**Goal:** Prove the surface, not just the stations.

For every local cell, audition at minimum:

- cell-center hold,
- `MORPH` sweep along the low side,
- `MORPH` sweep along the high side,
- `SECONDARY` sweep at the left station,
- `SECONDARY` sweep at the right station,
- diagonal low-left to high-right,
- diagonal high-left to low-right,
- relevant clean previews,
- relevant driven previews.

Also audition at least one slow gesture and one faster performance gesture through the actual intended control path before final approval.

**AI may propose:**

- replacements for failed cell corners,
- bridge stations,
- alternate high-rail versions,
- reasons a cell may be failing.

**Math derives:**

- deterministic render pack,
- cell-center files,
- sweep files,
- diagonal files,
- level/headroom warnings,
- driven-risk flags,
- response diagnostics.

**Human decides:**

- pass cell,
- fail cell,
- replace a station,
- add a knot,
- insert a secondary middle lane,
- kill the body.

**Exit condition:**  
Every used cell is approved by human listening.

---

## Step 7 — Repair only where the ear proves failure

**Goal:** Prevent the surface from bloating into a preset grid.

Repair order should be:

1. Replace a weak station.
2. Try a better bridge state.
3. Add a local `MORPH` knot if a specific segment fails.
4. Add a secondary middle lane only if vertical interpolation repeatedly fails.
5. Split or kill the body if the required surface becomes too large or incoherent.

Do **not** add knots just because the UI looks sparse.

Do **not** expand to a fixed 5×3 grid by default.

Do **not** preserve a body that only works because the author has overfit many small cells.

**Exit condition:**  
The surface is either compact and strong, or the body is abandoned.

---

## Step 8 — Reduction check before baking

**Goal:** Make sure the body is not more complex than necessary.

Before final bake, compare the approved surface against simpler approximations:

- the best 2×2 plane version,
- the previous smaller rail version,
- possibly a reduced-knot version.

Use randomized renders where practical.

**Math derives:**

- reduced versions,
- matched render sets,
- state count,
- cell count,
- rescue-edit count.

**Human decides:**

- whether the extra stations are audible and valuable,
- whether the simple version is equally good,
- whether the body should bake small.

**Exit condition:**  
The smallest passing representation is identified.

---

## Step 9 — Bake the deterministic `TYPE`

**Goal:** Freeze one body for product evaluation.

**Math derives:**

- final encoded station states,
- knot table,
- approved cell list,
- final render pack,
- provenance record,
- runtime validation through the real engine path,
- clean/driven QA renders,
- optional approved control remap if used.

**AI may propose:**

- internal descriptive notes,
- non-infringing label ideas,
- redundancy warnings versus other bodies.

**AI may not:**

- approve the body,
- publish the body,
- hide failed renders,
- silently assemble a final body,
- introduce third-party names or references.

**Human decides:**

- bake,
- revise,
- reject,
- reserve for later,
- include in final `TYPE` set.

**Exit condition:**  
One deterministic `TYPE` candidate exists.

---

## Step 10 — Curate against the full 4–7 body set

**Goal:** Prevent a set of individually good bodies from becoming redundant.

**AI may propose:**

- overlap warnings,
- ordering suggestions,
- generic internal descriptions.

**Math derives:**

- similarity summaries,
- render packs across all bodies,
- redundancy diagnostics.

**Human decides:**

- final `TYPE` count,
- cuts,
- ordering,
- naming direction,
- product readiness.

**Exit condition:**  
The body either earns a place in the 4–7 set or is cut.

---

# 5. Exact Boundary Between AI Proposal, Mathematical Derivation, and Human Taste

## Non-negotiable rule

> AI proposes. Math derives. Human approves.

No body is finished until the human locks stations, approves cells, and accepts the baked `TYPE` by ear.

| Area | AI may propose | Math may derive | Human must decide |
|---|---|---|---|
| Body brief | Generic descriptors, possible directions, warnings that the brief is too broad | Clean-room session record, provenance state | Whether the body idea is worth pursuing |
| Static candidate generation | Search directions, mutations, sibling ideas, sparse-region suggestions | Valid zero-bearing states, hard gates, descriptors, novelty, renders | Which candidates are emotionally interesting |
| Candidate ranking | “Try these” trays, possible contrasts, possible bridges | Stability, finite renderability, duplicate risk, response descriptors, headroom warnings | Star / maybe / reject |
| Main `MORPH` story | Endpoint pairings, bridge suggestions, alternates | Direct sweeps, midpoints, clean/driven previews, diagnostics | Which stations lock and whether the story is one body |
| `SECONDARY` verb | Possible deviation concepts, candidate high rails | Similarity-to-base, vertical sweeps, driven risk, coherence diagnostics | What `SECONDARY` means and how intense it should be |
| Cell repair | Replacement candidates, knot suggestions, alternate rails | Cell-center renders, diagonal renders, level/headroom warnings | Pass/fail/replace/add knot/kill |
| Reduction | Candidate simplifications, alternate descriptions | Matched renders, state count, rescue-edit count | Whether complexity is justified |
| Baking | Label drafts, notes, overlap warnings | Deterministic body data, render pack, provenance, runtime validation | Bake / revise / reject / publish |
| Product curation | Ordering suggestions, similarity warnings | Redundancy summaries, full-set render packs | Final 4–7 bodies |

## Forbidden automation

The Forge should not have:

- “AI build body,”
- “AI approve,”
- “auto-publish,”
- silent station insertion,
- silent cell repair,
- silent aesthetic deletion,
- hidden third-party references,
- hidden learned-embedding authority,
- hidden cube-axis behavior.

## Hard gates versus taste

Math may hard-reject invalid or unsafe states:

- unstable poles,
- non-finite coefficients,
- failed renders,
- overflow/NaN/Inf,
- invalid packed export,
- provenance failure.

Math should not hard-reject merely because a state is ugly, violent, strange, sparse, or unfashionable. Those are taste decisions.

---

# 6. What Should and Should Not Appear Visually in the Private Recordable Forge

The Forge is private, but it is also intended to be recordable. The visual surface should therefore communicate the real authoring act without exposing misleading abstractions or prohibited material.

## Should appear visually

### 1. The actual `MORPH × SECONDARY` surface

The primary view should be a 2D plane:

- horizontal axis: `MORPH`,
- vertical axis: `SECONDARY`,
- no hidden cube axis,
- no fake third dimension.

Stations should appear as audible locked points.

Cells should show status:

- unchecked,
- rendered,
- failed,
- human-approved,
- needs repair.

The author should see the real surface the listener will play.

### 2. Rail-first structure

The UI should make the authoring order obvious:

1. base `MORPH` rail,
2. `SECONDARY` verb,
3. high-secondary rail,
4. cell audit,
5. bake.

This prevents the Forge from becoming a general grid editor.

### 3. Clean and driven audition controls

Because clean and driven previews answer different questions, both should be first-class:

- clean preview,
- driven preview,
- matched render set,
- headroom/drive warning lamps.

The author should not be able to accidentally approve a body only clean if the driven path fails.

### 4. Candidate trays, not raw parameter dumps

The Forge should show compact trays such as:

- starred quarry states,
- bridge candidates,
- high-secondary candidates,
- sparse/outlier candidates,
- sibling candidates,
- rejects/suppressed-nearby candidates.

These can include advisory labels like:

- hollow,
- sharp,
- heavy,
- torn,
- closed,
- open,
- unstable-feeling,
- high-risk.

But the labels must remain generic and original.

### 5. A clear approval ledger

Every station and cell should have an explicit human status:

- unheard,
- auditioned,
- locked,
- failed,
- replaced,
- baked.

This is more important than a beautiful map.

### 6. Blind audition mode

The Forge should support randomized render comparison without displaying representation type, station count, or AI suggestions during scoring.

This is essential for deciding whether the adaptive surface is actually better than a simple plane.

### 7. Provenance / clean-room indicator

The Forge should show enough provenance to prove:

- internally generated state,
- internal parent IDs/seeds where relevant,
- no external coefficients,
- no imported presets,
- no extracted tables,
- no third-party names.

For recordable mode, this can be a simple clean-room badge rather than a technical dump.

### 8. Advisory diagnostics

Useful visual warnings:

- stability pass/fail,
- finite render pass/fail,
- level drift,
- headroom risk,
- duplicate risk,
- drive danger,
- cell not yet auditioned,
- cell center failed,
- diagonal failed.

Diagnostics should warn, not decide taste.

### 9. Optional quarry projections, clearly labeled as projections

A simple browse map such as low/high versus closed/open is acceptable as a front door to the quarry.

A hidden analytical projection can be shown if clearly labeled:

> retrieval projection, not musical truth.

It should not be visually rank-spread to look full.

---

## Should not appear visually

### 1. No cube as the authoritative body

Do not show an 8-corner cube as the main Forge metaphor. It will mislead the author into thinking the volume matters.

If a cube-like generator exists internally, it should not be the body view.

### 2. No hidden X/Y/Z body axes

The product has `MORPH` and `SECONDARY`. The Forge should not ask the author to reason about hidden axes that the consumer cannot perform.

### 3. No raw coefficient editing

The human taste authority should not edit:

- SOS coefficient tables,
- raw packed words,
- direct-form `a1/a2`,
- numerator arrays,
- denominator arrays.

Raw values can exist in diagnostic files, but they should not be the taste interface.

### 4. No pole-only display as if complete

Pole/zero structure may be useful for internal diagnostics, but pole-only visuals are misleading because zeros are audible and already observed to matter.

### 5. No third-party names, presets, artifacts, or references

The Forge should not display:

- third-party preset names,
- extracted byte names,
- reverse-engineered labels,
- copied product names,
- imported coefficient provenance.

### 6. No “AI approved” body state

AI suggestions should be visually marked as suggestions. Only human locks and approvals should produce approved status.

### 7. No beautiful map that pretends to be truth

A visible low/high versus closed/open map is useful for browsing, but dangerous if it implies:

- distance equals musical similarity,
- empty screen regions are truly sparse,
- a filled screen means a full quarry,
- hidden outliers do not matter.

### 8. No graph spaghetti as the body

A graph can help find bridges. It should not be the performance representation. The author should not approve a graph; the author should approve rendered cells and gestures.

### 9. No modifier panel that implies guaranteed identity preservation

If modifiers are used internally to propose states, the UI should not imply that a “bite” or “pressure” modifier is automatically safe. The resulting surface must still be auditioned.

### 10. No over-polished general preset editor

The Forge should not become a consumer preset browser, macro editor, or large library manager. Its job is narrow:

> help one author make 4–7 exceptional bodies by ear.

---

# 7. Smallest Listening Bakeoff That Could Falsify This Recommendation

This should happen before a polished Forge rewrite.

## Purpose

Falsify or support the claim that a rail-first adaptive 2D surface is a better authoring representation than a simple 4-corner plane or cube-based body under equal listening discipline.

## Critical constraint

Keep interpolation parameterization constant for this bakeoff.

Use the same complete zero-bearing packed/encoded engine-state interpolation for all variants.

Do **not** simultaneously test:

- pole/zero interpolation,
- response-space interpolation,
- learned embeddings,
- new drive behavior,
- new runtime smoothing,
- new candidate-generation strategy.

The bakeoff should isolate body representation.

## Materials

Use:

- one original body brief,
- one fixed clean-room static candidate pool,
- same audition source material,
- same clean and driven preview conditions,
- same author,
- same time budget per variant,
- randomized filenames,
- no third-party coefficients,
- no third-party names,
- no extracted data,
- no reverse-engineered artifacts.

The candidate pool can come from the quarry, but the quarry should not be the variable in this test.

## Build three variants

### Variant A — Best simple 4-corner plane

Build the strongest possible 2×2 `MORPH × SECONDARY` body.

Do not make it a straw man.

Allow the author to choose the best four states from the same pool.

### Variant B — Best cube or anchor-expanded cube

Let the cube advocate build the strongest cube-based version.

Rules:

- eight states maximum for the cube body,
- hidden mapping to public `MORPH × SECONDARY` must be declared before blind renders,
- same candidate pool,
- same time budget,
- same clean/driven checks.

This tests whether the cube’s extra structure actually helps.

### Variant C — Recommended rail-first adaptive surface

Start as small as possible.

Suggested starting point:

- base `MORPH` rail with endpoints,
- add a midpoint only if the direct middle fails,
- build one high-secondary rail against the locked morph stations,
- add a secondary middle lane only if vertical interpolation fails.

Log:

- state count,
- knot count,
- failed cells,
- rescue edits,
- authoring time.

Do not allow unlimited grid growth.

## Render minimum blind set

For each variant, render the same set, clean and driven:

1. center hold at the body’s effective middle,
2. `MORPH` sweep at low `SECONDARY`,
3. `MORPH` sweep at high `SECONDARY`,
4. `SECONDARY` sweep at low `MORPH`,
5. `SECONDARY` sweep at middle `MORPH`,
6. `SECONDARY` sweep at high `MORPH`,
7. diagonal sweep low-left to high-right,
8. diagonal sweep high-left to low-right.

That produces a small but meaningful set:

- 8 gestures × 2 drive conditions = 16 renders per variant,
- 48 renders total for three variants.

If this is too much for one sitting, split across sessions but keep randomization and scoring consistent.

## Blind scoring

For each randomized render, the human scores:

- **publish desire:** yes / maybe / no,
- **middle integrity:** strong / acceptable / failed,
- **boldness:** iconic / useful / timid,
- **secondary clarity:** clear / inconsistent / confusing,
- **drive behavior:** exciting / acceptable / bad,
- **gesture feel:** playable / awkward / broken,
- **rescue edits required:** count,
- **time to acceptable:** logged.

Free-text notes are allowed, but final comparison should not be based only on explanation. It should be based on what the human wanted to keep blind.

## Falsification rule

The rail-first adaptive surface recommendation is falsified if Variant A or Variant B:

1. is preferred blind by the human,
2. has equal or better middle integrity,
3. has equal or clearer `SECONDARY` behavior,
4. survives both clean and driven audition,
5. requires no more rescue time,
6. and feels at least as bold/iconic.

If the simple 4-corner plane wins, the Forge should not be rebuilt around a larger body format. It should become a disciplined plane-audition and QA tool.

If the cube wins, the cube hypothesis earns further work, but only with explicit proof that its public `MORPH × SECONDARY` mapping is what won — not merely impressive static corners.

If none of the variants produces a strong body, do not conclude that the surface idea failed by itself. The next suspects are:

- candidate quality,
- interpolation parameterization,
- drive/headroom behavior,
- body brief,
- `SECONDARY` verb,
- runtime smoothing/sample-rate behavior.

---

# 8. Claims That Remain [NEEDS VERIFICATION]

1. **Best interpolation parameterization.**  
   Existing packed/encoded interpolation is the correct baseline for the first representation bakeoff, but it is not proven to be the most musical parameterization.

2. **Exact knot counts.**  
   A 2×2, 3×2, 3×3, or larger surface may be appropriate per body. No fixed grid size is proven.

3. **Whether secondary middle lanes are commonly needed.**  
   A `SECONDARY = 0.5` lane should be inserted only if vertical interpolation fails or if the author wants an audible staged middle.

4. **Practical knot cap before killing a body.**  
   The recommendation is to avoid bloat, but the exact “too many stations” threshold is not proven.

5. **Compatibility metrics.**  
   Spectral distance, pole/zero motion, group delay, headroom, level drift, hidden descriptors, and novelty metrics may help suggest candidates, but none is proven to predict a strong morph relationship.

6. **Static quarry yield.**  
   The singularity-field / hidden-novelty quarry approach may produce better raw material than random or visible-map filling, but that must be tested by blind human audition.

7. **AI proposal value.**  
   AI may speed bridge discovery, sparse searches, and candidate variations, but the quality/time gain is unproven.

8. **Learned embedding usefulness and acceptability.**  
   Learned embeddings may or may not improve retrieval. They may cluster by probe content rather than filter character, and clean-room/legal acceptability remains unproven.

9. **Drive/headroom interaction.**  
   Clean approval is insufficient. Each body must survive driven audition through the real surrounding drive/gain behavior.

10. **Runtime smoothing and sample-rate behavior.**  
   Final bodies must be tested through the actual VST3 runtime path, including control movement, internal-rate processing, and resampling behavior.

11. **Control remapping.**  
   Nonlinear `MORPH` or `SECONDARY` mapping may improve playability, but it must be human-approved by audition, not applied automatically.

12. **Forge visual effectiveness.**  
   A 2D surface view is the honest representation, but its speed and usefulness for one author should still be measured against simpler blind-render workflows.

13. **Iconic quality of the final 4–7 bodies.**  
   Engineering can improve the odds and remove bad abstractions. Only human listening and curation can decide whether the final bodies are exceptional.

---

# Final Architecture Decision

## ENGINEERING INFERENCE — decisive recommendation

Rebuild the DF2 Forge as a **rail-first ear-locked adaptive `MORPH × SECONDARY` surface authoring bench**.

For each `TYPE`:

- use complete zero-bearing states,
- author the base `MORPH` rail first,
- define one coherent `SECONDARY` verb,
- build the high-secondary rail,
- audition every local cell and gesture clean and driven,
- add knots only when the sounded middle fails,
- bake the smallest representation that survives blind listening.

Use the quarry, AI, graphs, anchors, modifiers, analytical descriptors, and embeddings only to propose or retrieve raw material.

The body itself is not any of those things.

The body is the human-approved playable surface.
