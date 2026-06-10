# DF2 PRIVATE FORGE: DEFINITIVE STAGE-COMPOSER SPEC

Recovered from two incomplete GPT-5.5 Pro reasoning summaries and checked
against the locked DF2 runtime constraints. This is an implementation
specification, not a finished visual design.

## 1. VERDICT

**OBSERVED:** A shipping DF2 body is exactly four corners ordered
`M0_S0`, `M1_S0`, `M0_S1`, `M1_S1`. Each corner contains six serialized DF2T
biquads. Each stage compiles to five packed `u16` words. The shipping artifact
is exactly `240` bytes.

**RECOMMENDED:** Build the Forge as a private root-domain stage composer with an
always-on packed-runtime audit. Do not build a coefficient editor, a generic EQ,
an atlas, or an AI preset selector.

**RECOMMENDED:** The Forge has two complementary paths:

1. Insert lawful deterministic constructors that create editable stage rows or
   stage bundles.
2. Directly manipulate the resulting six serialized pole-zero stages across the
   four-corner surface.

**RECOMMENDED:** Batch generation remains useful only as deterministic macro
sweeps over lawful programs. It proposes plot contact sheets. The human selects
and finishes bodies.

## 2. WHAT THE AUTHOR EDITS

**RECOMMENDED:** The normal editable representation is a root-domain stage
surface. For each of the six serialized stage slots and each corner, store:

- pole root kind: complex-conjugate pair or real pair;
- pole frequency or real-root position;
- pole radius or bandwidth;
- zero root kind: complex-conjugate pair or real pair;
- zero frequency or real-root position;
- zero radius;
- stage gain and normalization policy;
- enabled state, role label, lock state, and constructor provenance.

Use log-frequency coordinates for spectral handles. Show radius or bandwidth as
a musical side control and as a vertical or wheel gesture. Display both pole and
zero handles whenever a stage is selected.

**RECOMMENDED:** Treat decoded direct-form coefficients, kernel `c0..c4`, and
packed `w0..w4` words as read-only diagnostics. Packed words are authoritative
for runtime proof but are not a humane editing surface.

**RECOMMENDED:** A stage slot remains the same serialized actor across all four
corners. Its roots may move dramatically. Its zero may stay near its pole or
travel remotely. Do not force a universal pole-zero hugging rule.

## 3. SCREEN ANATOMY

### Header

- body name;
- compile state;
- active corner;
- sticky edit scope;
- clean or driven preview;
- save, compile, hot reload, and export.

### Body Surface

- four corner miniplots in runtime order;
- one large packed-runtime response plot;
- `MORPH` and `SECONDARY` sliders;
- current runtime point;
- center and edge-midpoint overlays;
- a nine-curve contact strip for the four corners, four edge midpoints, and
  center;
- optional selected-path overlay and denser audit grid.

### Stage Composer

- six serialized lanes labeled `1..6`;
- per-lane mini response;
- selected-stage numerator, denominator, and combined response;
- pole and zero handles;
- isolate, bypass-to-identity, lock, duplicate, and role label;
- local-zero versus remote-zero annotation;
- selected-stage ghost handles for the other three corners.

### Constructor Palette

- lawful starter operations only;
- inserted rows immediately become ordinary editable stage lanes;
- generated values never remain hidden behind a macro.

### Audit Panel

- hard export gates;
- warnings;
- checkpoint list;
- packed-runtime response headroom;
- pole-radius and collision annotations;
- compiled artifact hash.

## 4. FOUNDATION OPERATIONS

**RECOMMENDED:** Start v0 with a small constructor vocabulary. Each constructor
creates original editable rows; it does not copy reference templates.

| Constructor | Slots | Purpose | Editable controls |
| --- | ---: | --- | --- |
| Manual pole-zero stage | 1 | Blank stage actor | pole freq/radius, zero freq/radius, gain, normalization |
| LP or HP cliff | 1 / 2 / 3 | 2-, 4-, or 6-pole descending or rising foundation | cutoff, order, resonance distribution, gain |
| BP window | 1 / 2 | 2- or 4-pole bandpass foundation | center, width, radius, gain |
| Opposed window or hollow | 2 | Crossing contrast field | two centers, widths, gains, direction |
| Peak or canyon actor | 1 | Local mountain, notch, or pole-zero tear | pole position/radius, zero position/radius, gain |
| Swept-EQ actor | 1 | Moving peak or cut with width law | start/end center, boost/cut, width law |
| Shelf or tilt actor | 1 | Broad remote-zero slope, cap, or lift | corner frequency, slope, zero position, gain |

**RECOMMENDED:** Add `Contrary` as a named operation over two editable rows: move
the two actors in opposing directions across Morph. It is a fast way to create
crossing tension without inventing a new runtime type.

**RECOMMENDED:** Treat Peak/Shelf Morph as a v1 experiment, not a v0 promise.
The local tutorial proves the musical value of a compact two-frame operation,
but the clean-room implementation still needs a bounded original constructor
and packed-runtime plot validation.

**RECOMMENDED:** Add deterministic physical skeleton starters in v1.1:
measured-vowel postures, tubes, modal objects, and broad analog-like slope
programs. They create editable rows and never approve bodies.

## 5. FOUR-CORNER EDIT SEMANTICS

**OBSERVED:** The shipping surface is `MORPH x SECONDARY`, not a cube editor.

**RECOMMENDED:** Default drag scope is:

`current corner -> selected stage -> selected pole or zero pair only`

No hidden propagation occurs during a normal drag.

Provide an explicit sticky scope selector:

- `Corner`;
- `Morph Edge`;
- `Secondary Edge`;
- `Whole Stage Field`.

**RECOMMENDED:** Constructors may initially write a two-frame Morph program by
copying `S0` into `S1`. Mark this visibly as `SECONDARY: DEGENERATE`. The copies
are not hidden live links.

Provide `EXPAND SECONDARY`: clone the current Morph edge into `S1`, then expose
both Secondary corners for deliberate editing.

**RECOMMENDED:** Copy and live-link are separate actions. Live links require an
explicit chain indicator. Touching a copied corner edits only that corner.

**RECOMMENDED:** Deleting a stage replaces it with a compiled identity stage.
It never changes serialized order or stage count.

**RECOMMENDED:** Warn on actor-role discontinuity, pole fusion, fragile
near-cancellation, and large midpoint changes. Do not auto-fix them. Useful
violence must remain authorable.

## 6. ALWAYS-ON PACKED AUDIT

**OBSERVED:** Release truth is the packed interpolation path through
`trench_core`, not an approximate authoring plot.

**RECOMMENDED:** Recompile and redraw after every edit. Use a quick nine-point
preview:

- four corners;
- four edge midpoints;
- center.

Before export, run a packed `5 x 5` surface grid through the release FFI path.

### Hard Export Gates

- exact corner order;
- exact `4 x 6 x 5 x 2 = 240` byte artifact;
- finite encoded and decoded values;
- successful pack and decode;
- finite packed-runtime response across the export grid;
- stable decoded poles across the export grid;
- no missing serialized slots; identity rows are valid.

### Warnings Only

- near-unit pole radius;
- large response headroom;
- sub-200 Hz pole fusion;
- near pole-zero cancellation;
- remote zero;
- abrupt checkpoint delta;
- Secondary still degenerate;
- role-label mismatch.

Warnings inform taste. They do not certify or reject musical quality.

## 7. AUTHORING DOCUMENT SCHEMA

**RECOMMENDED:** Store an editable, versioned `*.df2forge.json` document:

```text
format_version
body_id
body_name
authoring_sample_rate
notes
corners[4]                 // M0_S0, M1_S0, M0_S1, M1_S1
  stages[6]
    enabled
    role_label
    lock_state
    pole_root_kind
    pole_parameters
    zero_root_kind
    zero_parameters
    stage_gain
    normalization_policy
links[]
constructor_history[]
last_compile
  packed_body_hash
  audit_summary
```

Do not store reference bytes, reference endpoint rows, or copied tables in an
authored DF2 document.

**RECOMMENDED:** Store compiled output separately as `*.body240`. It is the
authoritative shipping artifact and runtime proof input.

## 8. COMPILE AND PREVIEW PATH

**RECOMMENDED:**

```text
*.df2forge.json
  -> resolve explicit links and constructor outputs
  -> validate root representation
  -> convert roots and gain to real biquad coefficients
  -> encode through the single owned packer
  -> assemble four corners in runtime order
  -> produce *.body240
  -> plot and audit through trench_core FFI packed interpolation
  -> hot reload safe preview
  -> export only after hard gates pass
```

The authoring document is editable truth. The packed `*.body240` is shipping
truth. Every important plot must come from the latter.

## 9. FIRST IMPLEMENTATION SEQUENCE

### v0: Minimum Useful Composer

- define `*.df2forge.json`;
- implement root-domain stage representation;
- compile one stage into the existing owned 240-byte path;
- render four corner cards and one large packed-runtime plot;
- add six stage lanes;
- expose pole and zero handles;
- add Corner-only drag scope;
- add identity, LP/HP cliff, BP window, opposed hollow, and peak/canyon
  constructors;
- add nine-point packed preview;
- add compile and export gates.

Acceptance:

- edit a zero independently and see the packed-runtime plot change;
- insert a 6-pole cliff and see three editable serialized rows;
- create an opposed hollow and see both rows;
- compile exactly `240` bytes;
- reject unstable or nonfinite exports.

### v1: Full Four-Corner Field Editing

- add explicit edit scopes;
- add copied-versus-linked state;
- add `EXPAND SECONDARY`;
- add stage ghost handles across corners;
- add Swept-EQ actor;
- add contact strip and selected-path overlays;
- add `5 x 5` export audit;
- add clean and driven preview modes.

Acceptance:

- start with a degenerate two-frame program;
- expand Secondary deliberately;
- edit a remote zero in one corner only;
- observe packed center and edge changes immediately;
- export a valid body without hidden corner propagation.

### v1.1: Deterministic Skeleton Starters

- add measured-vowel, tube, modal, and broad-slope starters;
- add contact-sheet batch sweeps over meaningful macros;
- keep every survivor editable as ordinary rows;
- require human selection.

Acceptance:

- generate varied lawful plot sheets without random roots;
- open any candidate in the same stage composer;
- preserve zero visibility and packed-runtime auditing.

## 10. REJECTED APPROACHES

- editing packed words as the normal workflow;
- editing `c0..c4` or direct coefficients as the normal workflow;
- pole-only models;
- zeros as decoration;
- random poles, zeros, or coordinate jitter;
- generating four unrelated corners independently;
- six identical cavities as a universal recipe;
- automatic collision avoidance;
- generic parametric-EQ UI;
- cube editor as the shipping authoring surface;
- AI ranking or blessing finished bodies;
- copying reference template rows into authored bodies;
- diagnostics pretending to measure taste.

## 11. OPEN EXPERIMENTS

Collect only these bounded captures:

| Priority | Capture | Decision settled |
| --- | --- | --- |
| Before v0 | Packed FFI response and decoded stage roots at the nine preview points for one known body | Confirms endpoint order, packed interpolation, and plot API |
| Before v0 | Root -> pack -> decode round-trip sweep for pole, zero, and gain extremes | Confirms editable root ranges and quantization behavior |
| Before v0 | LP/HP cliff constructors at 2-, 4-, and 6-pole settings across cutoff extremes | Confirms lawful foundation constructors and frequency limits |
| Before v0 | BP window and opposed contrary motion across a Morph sweep | Confirms one-row versus two-row contrast operations |
| After v0 | Peak/Shelf two-frame sweep with clean and driven preview | Determines original clean-room Peak/Shelf constructor semantics |
| After v0 | Dense-grid audit versus nine-point preview on deliberately violent bodies | Determines whether export grid should exceed `5 x 5` |

