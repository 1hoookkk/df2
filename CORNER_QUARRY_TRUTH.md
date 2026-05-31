# CORNER QUARRY TRUTH — DF2 Original Static-State Miner

> **Status: ACTIVE DESIGN SOURCE OF TRUTH.**
>
> This document governs the raw-material layer below body authoring. Its central
> direction is final: generate original signed pole-zero divisors with a compact
> continuous singularity-field program; mine them using hidden behavior-space
> novelty; expose a simple lossy browse projection; let the human ear promote
> material.
>
> Apply these implementation corrections when turning the reconstruction into
> code:
>
> 1. Use the actual authoring rate: `39062.5 Hz`.
> 2. Export and validate packed words through the existing `trench-core` FFI
>    owner. Do not create another codec or packed-interpolation implementation.
> 3. Preserve generator slot identity as provenance metadata. Do not
>    destructively reorder stages by frequency if that would erase later
>    actor-continuity options for morph authorship.
> 4. Treat zeros outside the unit circle as experimental candidates. Admit them
>    only after packed-format and real-engine gates prove their behavior.
> 5. The analytical atlas and visible map are separate. Never rank-spread the
>    analytical coordinates merely to make the screen look full.
> 6. Claims marked `[NEEDS VERIFICATION]` remain prototype test obligations.
>
> Direct Tyson instruction overrides this document. Static-corner quality does
> not prove body-trajectory quality; use `gpt55-pro-report-destruction.md` above this
> layer.

# 1. `KEY INSIGHT`

The compact solved reconstruction is:

> Treat every static corner as a **signed pole-zero divisor** in the complex plane, not as a named filter type, coefficient vector, preset, or point on a pretty 2D map. Generate original divisors with a tiny continuous “singularity-field” program, then quarry them with **hidden behavior-space novelty search**. The visible map is only a browse projection.

That is the hidden move.

The quarry should not be built by inventing more filter families, nor by throwing random coefficients at hard gates. It should generate complete zero-bearing rational filters, render/analyze them, and maintain an illumination archive whose purpose is:

1. keep all mathematically valid original candidates;
2. identify genuinely sparse behavioral regions in high-dimensional analysis space;
3. preserve violent outliers under quota rather than averaging them away;
4. present a compact human-browsable tray.

The key distinction is:

```text
Generation space:      pole-zero singularity fields
Validity space:        hard mathematical / numerical gates
Search space:          hidden analytical behavior descriptors
Visible browse space:  simple lossy semantic projection
Final authority:       human ear
```

The quarry is therefore not “a map of filters.” It is a **behavioral atlas of original pole-zero states**, with several projections.

A simple visible `LOW <-> HIGH` / `CLOSED <-> OPEN` map is acceptable as a front door. It is actively misleading if used as the actual diversity metric, because two states can occupy the same visible cell while differing radically in notch structure, phase/group delay, pole-zero cancellation, comb behavior, driven response, or high-Q violence.

---

# 2. `SOLVED QUARRY`

The solved quarry is a two-layer archive:

```text
Raw archive:
    every hard-valid original static corner

Illuminated shortlist:
    novelty-balanced, redundancy-capped, outlier-preserving browse tray
```

Pipeline:

```text
clean seed / internal parent IDs
        ↓
singularity-field generator
        ↓
canonical pole-zero-gain state
        ↓
derived 6-SOS zero-bearing cascade
        ↓
hard mathematical rejection
        ↓
response + render analysis
        ↓
hidden behavior-space indexing
        ↓
novelty / sparsity / duplicate control
        ↓
compact human audition tray
```

No external coefficients, presets, extracted tables, reverse-engineered structures, or third-party templates are generative inputs.

The system does not try to decide what is “iconic.” It tries to produce a quarry where iconic bodies become possible later.

It should generate:

- central useful material;
- coherent oddities;
- high-violence edge cases;
- sparse-region probes;
- siblings around human-starred states;
- hybrids between internally generated states.

It should not silently delete strange states because they score poorly on conventional metrics. Hard gates reject only unsafe or invalid states. Everything aesthetic is advisory.

---

# 3. `CORNER REPRESENTATION`

The canonical mathematical representation of one generated corner is a factored zero-pole-gain form:

\[
H(z)
=
g
\prod_{i=1}^{6}
\frac{
1 - 2\rho_i \cos(\psi_i) z^{-1} + \rho_i^2 z^{-2}
}{
1 - 2r_i \cos(\theta_i) z^{-1} + r_i^2 z^{-2}
}
\]

where each section represents one conjugate zero pair and one conjugate pole pair.

For each section:

```text
pole pair:
    p_i, p_i* = r_i exp(±j θ_i)

zero pair:
    z_i, z_i* = ρ_i exp(±j ψ_i)

gain:
    g ∈ R, stored separately and deterministically distributed when exporting SOS
```

Hard stability condition:

```text
0 <= r_i < r_safe < 1
```

Zeros may be inside, on, or moderately outside the unit circle if coefficient and renderability gates pass. Numerator zeros are not decorative; they are first-class creative material.

The derived SOS form is:

```text
b0_i, b1_i, b2_i
a1_i, a2_i
```

with real finite coefficients. Stage order is canonicalized for storage, for example by increasing pole frequency and then radius. The quarry identity is the factored divisor plus gain; the SOS is a deterministic render/export realization.

A minimal stored corner therefore contains:

```text
CornerState {
    sample_rate_authoring
    gain
    poles[6]  // radius, angle
    zeros[6]  // radius, angle
    sos[6][5] // derived b0,b1,b2,a1,a2
}
```

This representation avoids the two bad extremes:

- coefficient vectors, which are poor semantic objects;
- pole-only models, which erase numerator behavior and misdescribe the sound.

---

# 4. `GENERATION AND HYBRIDIZATION`

The minimal generator is not a taxonomy. It is one compact continuous program:

```text
six singularity slots
+ frequency skeleton
+ pole-radius field
+ zero-shadow field
+ gain normalizer
```

## 4.1 Frequency skeleton

Generate six log-frequency positions over the usable band.

Do not choose from named low-pass / high-pass / vocal / comb / acid / formant templates. Instead use a mixture of:

- repulsive log-frequency placement to avoid accidental duplicates;
- occasional clustered placement for dense resonant regions;
- smooth frequency warps;
- optional ratio-biased placement for quasi-harmonic or inharmonic stacks.

These are mathematical priors, not copied structures.

## 4.2 Pole-radius field

Define a smooth-plus-sparse field over log frequency:

```text
R_p(x) = broad curvature + local spikes + stress term
```

Then map it into stable pole radii:

```text
r_i = stable_radius_map(R_p(x_i))
```

This lets the generator create:

- broad warm humps;
- narrow violent needles;
- grouped resonances;
- upper-band emergence;
- dull, hollow, nasal, metallic, or unstable-feeling-but-stable shapes.

The important point is that radii are field-correlated. They are not six unrelated random Q values. That is what makes states coherent.

## 4.3 Zero-shadow field

For each pole region, generate a zero relation:

```text
ψ_i = θ_i + angular_offset_field(x_i)
ρ_i = zero_radius_field(x_i)
```

The zero may shadow a pole, oppose it, notch near it, sit on/near the unit circle, or drift away to expose a resonance.

This is where a lot of “destructive morphing filter” character lives. The zero field creates antiresonance, hollowness, cancellation, phase color, nasal cavities, comb-like teeth, and ripped-open high bands.

## 4.4 Gain normalization

Normalize gain for renderability, not politeness.

A good default is robust response normalization: set median or weighted-band loudness near a target, then apply a safety peak guard. Do not normalize every state into the same timid shape. A high-Q violent outlier should still sound violent after normalization.

Exact gain policy is `[NEEDS VERIFICATION]`.

## 4.5 Hybridization

Hybrids are made at the divisor-field level, not by averaging coefficients or splicing named categories.

Given two internally generated parent states A and B:

1. choose a log-frequency mask;
2. take lower-band singularity structure from A;
3. take upper-band radius/zero-shadow behavior from B;
4. use optimal assignment in log-frequency to keep six pole-zero sections;
5. locally optimize only enough to pass gates and preserve the intended response regions.

Example: a “vocal-like lower / synthetic upper” hybrid is not built from a vocal-tract template. It is produced by selecting an internally generated lower structure with grouped low-mid resonances and antiresonances, then applying an upper-band stress field whose pole radii increase and whose zero shadows move away under a latent intensity value.

Each sampled intensity is still a complete static corner. The stored quarry item is not a parametric body. The latent program is provenance and sibling retrieval metadata.

## 4.6 Sparse-region exploration

The generator is coupled to novelty search.

Process:

```text
1. Generate initial hard-valid population.
2. Analyze each state into hidden descriptors.
3. Estimate local density / kNN distance in hidden behavior space.
4. Select sparse or underrepresented regions.
5. Mutate or optimize generator programs toward those regions.
6. Add hard-valid results to archive.
7. Repeat until novelty yield saturates.
```

This is why the solution is not “more random generation.” Randomness proposes. Hidden behavior-space scarcity directs the mining.

Numerical optimization is allowed offline, but its objective should be:

```text
validity + novelty + target descriptor reach
```

not “make a good preset.”

---

# 5. `ANALYTICAL INDEX VS VISIBLE MAP`

The quarry should use **separate hidden analytical coordinates and visible display coordinates**, plus linked retrieval views.

One coordinate system is not enough.

## 5.1 Hidden analytical coordinates

The hidden vector should include response and signal-derived behavior, for example:

```text
Magnitude response:
    log-magnitude on ERB/log-frequency bands
    tilt / centroid / bandwidth
    low/mid/high energy ratios
    peak count, peak height, peak spacing
    notch count, notch depth, notch spacing
    ripple / combness / roughness proxies

Phase / time behavior:
    group delay bands
    group delay peakiness
    phase curvature proxies

Pole-zero structure:
    pole radius quantiles
    radius distribution by band
    zero radius quantiles
    pole-zero proximity
    cancellation / anti-cancellation measures
    frequency clustering entropy

Rendered probes:
    clean probe descriptors
    driven probe descriptors, if the real surrounding drive path is available
```

The exact descriptor set is `[NEEDS VERIFICATION]`, but it must include enough information that zero-bearing states with similar magnitude but different phase/zero behavior are not collapsed blindly.

## 5.2 Visible display coordinates

A simple visible map may use axes such as:

```text
LOW  <-> HIGH
CLOSED <-> OPEN
```

This is good enough as a hand-legible browse surface if the author understands that it is a projection.

It is insufficient as the quarry’s real index.

It becomes actively misleading if:

- sparse-region search fills the visible grid instead of hidden space;
- candidates are warped on-screen to make the map look full;
- distance on the 2D screen is treated as perceptual similarity;
- overlapping hidden families are hidden behind one dot;
- outliers are discarded because they clutter the display.

Visible axes should be derived from simple descriptors:

```text
low-high:
    centroid / dominant-band / peak-weighted frequency

closed-open:
    high-band transmission / broadband energy / notch penalty
```

But the hidden atlas should remain authoritative for duplicate detection and sparse search.

## 5.3 Linked maps

Use one hidden metric atlas and multiple lightweight visible views:

```text
default visible map:
    low-high vs closed-open

secondary projection:
    hidden PCA/UMAP-like behavior view, marked "analytical projection"

outlier tray:
    highest novelty, highest violence, rare phase/zero cases

family labels:
    emergent cluster tags, not generation templates
```

Discrete labels are useful only after the fact:

```text
hollow
needle upper
wide vowel-ish
broken comb
low chest
airless
ripped open
phase smear
```

These labels help humans browse. They should not become a brittle source taxonomy.

## 5.4 Learned audio embeddings

A learned audio embedding such as CLAP is not part of the core solved quarry now.

It may become useful later as an advisory retrieval coordinate if it passes a minimum experiment:

1. render every candidate through the same clean synthetic probe set;
2. collect human triplet judgments: “A is closer in filter character to B than C”;
3. compare learned embedding distance against the analytical descriptor baseline;
4. test invariance across probe material, level, and clean/driven rendering;
5. verify it finds human-starred candidates missed by analytical search without merely clustering by source content.

Until then, use it only as optional side metadata, never as a hard gate or primary sparse-region engine. Its usefulness and clean-room/legal acceptability are `[NEEDS VERIFICATION]`.

---

# 6. `GATES VS ADVISORY RANKING`

Hard gates reject only states that should not enter the quarry at all.

## Hard rejection gates

```text
Provenance:
    no external coefficients, preset data, extracted tables, or copied structures
    reproducible from internal seed / internal parent IDs / clean algorithm version

Mathematics:
    exactly six second-order sections derivable
    real finite coefficients
    poles strictly inside unit circle
    no NaN / Inf
    no denormal-prone pathological coefficient set beyond engineering limits
    response finite on dense frequency grid

Numerical renderability:
    impulse/probe render completes
    no overflow / NaN / Inf
    bounded output after declared preview normalization
    coefficient magnitudes within implementation safety envelope

State integrity:
    zeros preserved
    gain stored
    no pole-only surrogate
    no response-only surrogate
```

Exact thresholds are `[NEEDS VERIFICATION]`.

## Advisory ranking signals

These may rank, color, warn, or create trays. They must not silently delete.

```text
novelty / hidden sparsity
near-duplicate distance
timidity
violence
headroom risk
drive excitement
drive danger
peak sharpness
notch extremity
vocal-ish / metallic / hollow / airy labels
phase weirdness
family membership
human stars
human rejects
learned embedding similarity, if later adopted
```

Near-duplicates should be throttled in the shortlist, not necessarily erased from the raw archive.

Violent states should be red-tagged and quota-managed, not normalized out of existence.

---

# 7. `HUMAN AUDITION LOOP`

The quarry should remain useful before any learned taste model exists.

Division of labor:

```text
Procedurally generated:
    initial pole-zero field programs
    mutations
    synthetic probe renders
    siblings around starred states

Numerically optimized:
    sparse-region searches
    local hybrid repair
    gain normalization
    target descriptor reaching
    validity repair within safe bounds

Retrieved by similarity:
    nearest neighbors
    farthest contrasts
    same-family variants
    hidden outliers
    siblings from same latent program
    candidates similar to human-starred states

Chosen by human ear:
    musical value
    emotional surprise
    whether violent is useful or merely broken
    whether a state deserves later body-authoring attention
    final shortlist promotion
```

The human should browse compact trays, not thousands of dots.

A practical tray could contain:

```text
core tray:
    novelty-balanced medoids

sparse tray:
    candidates from low-density hidden regions

violent tray:
    safety-passed high-risk outliers

star-neighborhood tray:
    siblings and contrasts around human favorites

reject-neighborhood tray:
    similar states to suppress in future browse trays
```

Outliers are preserved by quotas:

```text
keep all hard-valid outliers in raw archive
show only a capped rotating subset
never let average advisory score erase top novelty
allow "more like this" retrieval from any outlier
```

The quarry must not pretend static-corner quality proves later morph quality. It only supplies raw corner material.

---

# 8. `MINIMAL OUTPUT SCHEMA`

A minimal clean-room candidate record:

```json
{
  "id": "corner_00012345",
  "schema_version": 1,

  "authoring_sample_rate": 48000,
  "created_utc": "ISO-8601",

  "provenance": {
    "source": "procedural",
    "algorithm": "singularity_field_v1",
    "code_hash": "hash",
    "random_seed": "seed",
    "parent_ids": [],
    "optimization": {
      "used": false,
      "objective": null,
      "iterations": 0
    },
    "external_coefficients_used": false,
    "external_presets_used": false,
    "notes": "clean-room generated"
  },

  "canonical_state": {
    "gain": 0.123,
    "poles": [
      {"radius": 0.91, "angle_rad": 0.18}
    ],
    "zeros": [
      {"radius": 1.00, "angle_rad": 0.21}
    ]
  },

  "derived_sos": [
    {
      "b0": 1.0,
      "b1": -1.8,
      "b2": 0.81,
      "a1": -1.7,
      "a2": 0.83
    }
  ],

  "hard_validation": {
    "passed": true,
    "max_pole_radius": 0.97,
    "coefficients_finite": true,
    "response_finite": true,
    "render_finite": true,
    "warnings": []
  },

  "analysis": {
    "hidden_descriptor_vector_ref": "descriptors/corner_00012345.npy",
    "visible": {
      "low_high": 0.63,
      "closed_open": 0.28
    },
    "novelty": {
      "knn_distance": 2.41,
      "density_percentile": 0.94
    },
    "advisory": {
      "violence": 0.78,
      "timidity": 0.05,
      "headroom_risk": 0.42,
      "duplicate_risk": 0.11
    },
    "labels": ["hollow", "upper-needle"]
  },

  "renders": {
    "impulse_wav": "renders/corner_00012345_impulse.wav",
    "noise_clean_wav": "renders/corner_00012345_noise_clean.wav",
    "probe_driven_wav": "renders/corner_00012345_probe_driven.wav"
  },

  "human": {
    "audition_status": "unheard",
    "stars": 0,
    "reject": false,
    "notes": ""
  }
}
```

The numbers above are illustrative placeholders, not recommended thresholds or known values.

---

# 9. `CLAUDE CODE PROTOTYPE`

Implement one bounded falsification prototype:

```text
Name:
    static_corner_quarry_miner

Language:
    Python + NumPy/SciPy or equivalent

No external audio.
No learned embeddings.
No external coefficients.
No preset imports.
```

## Prototype task

Generate, analyze, and shortlist original static corners.

Suggested bounded run:

```text
authoring sample rate: fixed, e.g. 48 kHz [NEEDS VERIFICATION]
candidate attempts:    20,000 [NEEDS VERIFICATION]
hard-valid target:     at least 5,000 [NEEDS VERIFICATION]
browse shortlist:      192 candidates [NEEDS VERIFICATION]
```

## Required implementation pieces

1. **Factored state class**

```text
PoleZeroCorner:
    gain
    six pole radius/angle pairs
    six zero radius/angle pairs
    method: to_sos()
    method: response(freq_grid)
    method: render_probe()
```

2. **Singularity-field generator**

Generate six log-frequency slots, pole-radius field, zero-shadow field, and gain.

3. **Hard gates**

Reject unstable, non-finite, non-renderable states.

4. **Descriptor extractor**

Compute hidden descriptor vectors from:

```text
log magnitude response
response derivatives
peak/notch summaries
group delay summary
pole/zero structural stats
clean synthetic probe render stats
optional driven render stats if available
```

5. **Hidden novelty archive**

Use robust whitening, k-nearest-neighbor distance, and farthest-first or CVT-like selection.

Do not select by visible map fullness.

6. **Sparse search loop**

After the first population:

```text
select high-novelty parents
mutate their generator programs
accept hard-valid children that increase hidden novelty or fill underrepresented hidden neighborhoods
```

7. **Hybrid pass**

Create a small batch of internal-parent hybrids using masked divisor-field recombination:

```text
lower region from parent A
upper radius/zero-shadow behavior from parent B
six-section reassignment
local validity repair
```

8. **Output**

```text
archive.jsonl
shortlist.json
descriptor arrays
response plots
simple HTML browser
visible low-high/open-closed map
hidden analytical projection
WAV previews from synthetic probes
```

## Prototype falsification test

Create three blind audition trays from the same hard-valid archive:

```text
Tray A:
    random hard-valid states

Tray B:
    states chosen to fill the visible low-high/open-closed grid

Tray C:
    states chosen by hidden novelty / sparsity with outlier quota
```

The reconstruction is supported if Tray C gives the human:

```text
more starred candidates
fewer timid near-duplicates
more useful violent outliers
more "I would build from this" reactions
better sparse-region discovery
```

The reconstruction is weakened or falsified if Tray B or random Tray A is equally good or better under the same listening time.

Minimum listening protocol:

```text
randomized filenames
same probe material
level-matched previews
clean previews required
driven previews optional but recommended
human marks:
    star / maybe / reject
    duplicate? yes/no
    useful outlier? yes/no
    too broken? yes/no
    short free-text note
```

This prototype proves or falsifies the central claim without touching body architecture.

---

# 10. `KILL CRITERIA`

Kill or redesign this reconstruction if:

1. hidden-novelty trays do not beat random or visible-grid trays in blind human audition;
2. the generator mostly produces mathematically valid but musically dead material;
3. sparse search mostly discovers numerical pathologies rather than useful perceptual regions;
4. hybrids routinely lose identity and produce incoherent mush;
5. the visible map causes the author to miss important hidden outliers;
6. advisory ranking suppresses states the human later finds valuable;
7. hard gates are so strict that violent but renderable states disappear;
8. hard gates are so loose that previews overflow, explode, or waste audition time;
9. the human hears thousands of near-duplicates despite novelty controls;
10. provenance cannot prove clean-room generation;
11. learned embeddings, if tested, correlate more with probe content than filter character;
12. the author must think in raw pole/zero/coefficient terms to browse effectively.

---

# 11. `SEDUCTIVE WRONG APPROACHES`

## Wrong: generate lots of named filter families

A bigger taxonomy feels controllable, but it becomes brittle and derivative. It also biases the quarry toward familiar shapes instead of sparse surprises.

## Wrong: random coefficients plus stability test

Stable random SOS coefficients produce many valid filters but poor coverage, many near-duplicates, and many arbitrary numerical accidents. Coefficient distance is not perceptual distance.

## Wrong: pole-only generation

Zeros materially shape the sound. Pole-only models erase notches, antiresonance, cancellation, phase behavior, and many destructive-filter identities.

## Wrong: response-only storage

A response curve may help analysis, but the corner must remain a complete zero-bearing state. Reconstructing later from magnitude alone loses phase and zero structure.

## Wrong: fill the pretty 2D map

A full screen is not a full quarry. Low-high/open-closed is a lossy view. Real sparse regions live in hidden response and signal-behavior space.

## Wrong: let metrics silently cull ugly states

The whole point is to preserve strange material. Metrics can warn, sort, and quota. They must not decide taste.

## Wrong: optimize everything toward “pleasant”

Pleasantness optimization creates timid sameness. The quarry needs useful danger.

## Wrong: start with CLAP or another learned embedding

A learned embedding may become useful later, but if adopted too early it may cluster by probe content or broad timbre rather than filter character `[NEEDS VERIFICATION]`.

## Wrong: copy or approximate third-party presets

Clean-room safety requires original generation from internal algorithms and seeds. Similar-sounding outcomes may occur accidentally, but copied coefficients, extracted tables, preset names, or reverse-engineered structures are banned.

## Wrong: confuse corner quality with body-trajectory quality

A great static corner may make a terrible interpolated body. This quarry only supplies static raw material.

---

# 12. `NEEDS VERIFICATION`

The reconstruction above is technically coherent, but these details must be tested:

1. exact stability margins, coefficient bounds, and render safety thresholds;
2. best gain normalization policy for violent but usable states;
3. descriptor weights and whether they match human perception of filter-character distance;
4. whether group-delay and zero-structure descriptors materially improve retrieval;
5. whether the singularity-field generator yields enough emotionally useful material;
6. whether masked divisor-field hybrids produce coherent surprises at useful rates;
7. how many candidates are needed before novelty yield saturates;
8. ideal shortlist size for fast human browsing;
9. whether driven synthetic probes predict real artistic usefulness;
10. whether learned embeddings such as CLAP add value beyond analytical descriptors;
11. clean-room/legal acceptability of any third-party learned embedding;
12. whether visible `LOW/HIGH` and `CLOSED/OPEN` are the right default browse axes;
13. whether human-starred quarry states later survive body-authoring trajectories.

The decisive first test is not whether the map looks good. It is whether the hidden-novelty shortlist produces more human-starred, non-duplicate, musically dangerous static corners than random valid generation or visible-grid filling under equal blind audition time.
