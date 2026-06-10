# DF2 Authoring Doctrine: Independent Second Opinion

You are reviewing a live repository, not brainstorming from scratch.

Your job is to give a skeptical second opinion on the **private DF2 Forge
authoring doctrine**. Do not implement code. Do not preserve a prior idea merely
because another model wrote it. Do not inflate this into a broad roadmap.

The repository contains several rounds of thinking, including deliberately
deleted doctrine. Some files are current authority, some are background
evidence, and some are superseded experiments. Read them in the order below,
separate observed facts from recommendations, and then land one practical
answer.

## Product

DF2 is a destructive morphing filter insert FX plugin for 808s, bass, vocals,
drums, and buses.

The shipping plugin needs a small set of original, iconic, commercially useful
bodies. The private Forge is an internal single-author instrument used to make
those bodies. It is not a public modular editor and not an academic emulator.

The author owns taste. Automation may propose lawful original material, compile
it, render it, plot it, and warn about failures. It must not silently approve
finished bodies.

## Locked Runtime Facts

Treat these as hard constraints unless the live code proves the repository has
already changed:

- A shipping body is exactly four corners ordered
  `M0_S0, M1_S0, M0_S1, M1_S1`.
- Each corner has exactly six serialized DF2T biquad stages.
- Each stage compiles to five packed `u16` words.
- The shipping artifact is exactly `4 x 6 x 5 x 2 = 240` bytes.
- Numerator and denominator behavior both matter. Zeros are first-class.
- Shipping truth is the packed-domain interpolation and decode path owned by
  `trench-core`, not an approximate authoring plot.
- `.df2forge.json` is editable authoring source. `.body240` is shipping truth.
- The authoring sample rate is `39062.5 Hz`.
- The X3 software and DLL-derived packed words are the historical runtime
  oracle. Do not drift into hardware folklore.
- ROM bodies, reverse-engineered bytes, vendor names, and extracted tables are
  study-only. Original shipping bodies must be clean-room authored.

## Current Preferred Doctrine

The current repository contract says the Forge should be a:

> root-domain six-stage composer with an always-on packed-runtime plot audit

The author edits one explicit `MORPH x SECONDARY` four-corner body through six
serialized pole-zero stage lanes. Lawful deterministic constructors insert
editable rows or bundles. The packed-runtime response plot is the hero
instrument. Batch generation is subordinate: deterministic macro sweeps can
propose contact sheets, but the author selects and finishes bodies.

This is the current preferred model, not an answer you must rubber-stamp.

## Read First: Current Authority

Read these completely:

1. `CLAUDE.md`
2. `gpt55-pro-report-coefficient-forge-spec.md`
3. `.claude/skills/df2-operator/SKILL.md`

Inspect the live implementation only enough to verify factual claims:

4. `trench-core/src/minifloat.rs`
5. `trench-core/src/cartridge.rs`
6. `trench-core/src/cascade.rs`
7. `cartridge.schema.json`
8. `forge-clean/` if present

## Read Second: Important Background Arguments

These are not allowed to silently override current authority, but they contain
important arguments that must be pressure-tested:

1. `gpt55-pro-report-destruction.md`
   - argues against the old 8-corner cube;
   - recommends an ear-locked rail-first 2D surface;
   - emphasizes trajectory approval over static corner collection.
2. `gpt55-pro-report-ui-pass.md`
   - critiques proposal-space leakage and overbuilt UX;
   - proposes a compact `FIND -> MORPH -> BEND -> PROVE -> KEEP` workflow.
3. `CORNER_QUARRY_TRUTH.md`
   - describes a clean-room static-corner quarry;
   - treat it only as an optional raw-material layer below body authoring.
4. `ref/morpheus_authoring_doctrine.md`
   - study-only historical/reference doctrine.
5. `gpt55-pro-cleanroom-authoring-doctrine-prompt.md`
6. `gpt55-pro-constructor-palette-prompt.md`

Also inspect the other `gpt55-pro-*.md` files if a claim depends on them.
Prompts and reasoning summaries are evidence of how conclusions were reached,
not automatic authority.

## Read Third: Deleted Historical Layer

Commit `8116f38` deliberately deleted the older `NOW.md`, `STATE.md`,
`REBUILD_PLAN.md`, `BODY_TAXONOMY.md`, session logs, and the previous `forge/`.
They are archaeology, not current instructions.

Use Git to inspect them:

```powershell
git show 8116f38^:NOW.md
git show 8116f38^:STATE.md
git show 8116f38^:REBUILD_PLAN.md
git show 8116f38^:BODY_TAXONOMY.md
git show --stat --oneline 8116f38
```

The deleted layer contains useful evidence and several superseded branches:

- an 8-corner cube and hidden path idea;
- response-first and whole-corner authoring ideas;
- quarry / atlas / CLAP taste-model ideas;
- rail-first trajectory approval;
- Forge/player/capture separation;
- one-owner packed math and exact 240-byte body truth;
- player cleanup and runtime simplification concerns.

Do not revive a deleted branch merely because it is interesting. State whether
it belongs in the active Forge, below it as optional infrastructure, or nowhere.

## The Question

Give a proper second opinion on this:

> Is the current root-domain six-stage composer with an always-on packed-runtime
> audit the right smallest serious private Forge for producing 4-7 original,
> iconic DF2 bodies? If not, what should replace it?

You must adjudicate these tensions:

1. **Stage composer vs response-first workflow**
   - Should the author directly shape serialized pole-zero actors?
   - Should response plots remain the hero while stages stay the editable
     substrate?
   - Is a response-target fitter useful as a subordinate operation, or is it a
     better primary authoring model?

2. **Explicit four-corner body vs rail-first surface**
   - Is the locked four-corner `MORPH x SECONDARY` body sufficient if the Forge
     continuously audits corners, edges, and center?
   - Does the rail-first doctrine add essential workflow discipline without
     requiring a new runtime format?

3. **Constructors**
   - What is the smallest lawful original constructor palette?
   - Are physical skeletons, Bark/ERB grids, and Type 1/2/3-inspired zero
     treatments useful starter operations beneath direct editing?
   - Which ideas are redundant or too abstract?

4. **Quarry / atlas / CLAP**
   - Should static-corner mining exist only as an optional raw-material source?
   - Should analytical or learned embeddings be deferred until the manual
     composer proves itself?

5. **UX scope**
   - What is the smallest recordable private Forge workflow?
   - Which diagnostics must stay visible?
   - Which concepts should remain invisible or deferred?

## Evidence Discipline

For every major claim, label it:

- `OBSERVED`
- `INFERRED`
- `RECOMMENDED`
- `REJECTED`
- `UNKNOWN`

When repository documents disagree:

1. distinguish runtime fact from authoring recommendation;
2. distinguish current authority from deleted historical material;
3. prefer the smallest falsifiable experiment over a larger theory;
4. do not rewrite the runtime to rescue an authoring metaphor;
5. do not copy vendor material into clean-room shipping bodies.

## Required Output

Write a compact report titled:

`DF2 PRIVATE FORGE: INDEPENDENT DOCTRINE REVIEW`

Use exactly these sections:

### 1. Verdict

One decisive paragraph. State whether the current six-stage root-domain composer
is correct, needs a narrow correction, or should be replaced.

### 2. Keep / Demote / Reject

Use a table. Classify the major ideas:

- six-stage root-domain composer;
- hero packed-runtime response plot;
- four-corner `MORPH x SECONDARY` body;
- rail-first authoring discipline;
- response-target fitting;
- deterministic constructors;
- static-corner quarry;
- analytical atlas;
- CLAP taste model;
- 8-corner cube;
- AI keeper ranking.

### 3. Minimum Useful Forge

Describe the smallest authoring loop that should actually be built and used.
Keep it to one screen model and one body-making loop.

### 4. Constructor Palette

Specify the smallest serious constructor set. Explain what each constructor adds
that another does not.

### 5. Falsification Gate

Give at most five bounded tests or listening bakeoffs that would prove your
recommendation wrong or reveal the next blocker.

### 6. Immediate Next Move

Name exactly one implementation slice or experiment to do next. It must fit
within one focused session.

### 7. Do Not Do

List at most eight concrete failure modes to avoid.

## Hard Forbids

- No code changes.
- No broad multi-month roadmap.
- No runtime rewrite unless you prove the locked runtime facts are false.
- No 8-corner cube revival without a decisive falsification argument.
- No vendor coefficient reproduction.
- No random root spraying.
- No AI taste approval.
- No treating deleted `NOW.md` or `STATE.md` as current authority.
- No pretending that a polished UI concept proves a musical workflow.
- No generic best-practice filler.

Be blunt. Compress the answer. The goal is one usable second opinion, not
another doctrine pile.
