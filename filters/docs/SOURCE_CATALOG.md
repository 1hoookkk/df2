# Source catalog and neutral evidence boundary

The catalog is the index between “a file exists” and “this is safe input to a
preset.” It is deliberately separate from `geometry.schema.json`:

- `geometry.schema.json` describes the six-lane, four-corner authoring IR.
- `source-catalog.schema.json` describes where evidence came from, what it is,
  what conversion it needs, and what it is allowed to influence.

The catalog uses neutral record types. A historical or product reference is a
`study_reference` with `ship_allowed: false`; it may describe behavior or method
but cannot carry bytes, coefficient rows, preset identifiers, or become a body
source. This keeps non-project lore available for context without letting it
silently become runtime material.

## The usable path

```text
source file
  -> catalog record
  -> explicit conversion to transfer-function evidence
  -> four authored corner geometry
  -> tools/filter_cli.py pack
  -> packed-runtime proof and listening
```

The catalog is read-only with respect to source roots. It records a relative
path, optional SHA-256, and a short decision. It does not copy external data or
move scratch artifacts.

## Record meanings

| record type | useful as preset input? | default interpretation |
|---|---:|---|
| `measured_ir` | conditional | controlled impulse/deconvolved sweep; confirm metadata first |
| `measured_tf` | conditional | already a frequency response; select the two physical axes |
| `simulated_tf` | conditional | spectrum/absorption from a simulation; document the adapter |
| `modal_evidence` | conditional | modes can synthesize a TF, but are not an IR by themselves |
| `authored_geometry` | yes, as an authoring candidate | must still pack and run all proof gates |
| `body_artifact` | no, as an IR | compiled output; never reverse-label it as source evidence |
| `audio_render` | no by default | listening/proof output; raw audio is not automatically an IR |
| `proof_bundle` | no | evidence about a candidate, not the source |
| `study_reference` | never | behavior/method context only; non-project lore boundary |

## Physical organization without moving the current tree

Keep the existing locations stable and use the catalog as the virtual filing
system:

```text
wav-source-library/       original local measurements
surface-forge/data/       external read-only datasets
dev/tmp/                  scratch, candidates, renders, sessions, proofs
filters/                 canonical geometry, tables, rails, and bodies
recipe-index/             named recipes that point to catalog records
```

For a source card, fill in only these decisions first:

1. Is it a real IR, a direct TF table, a modal table, a simulation spectrum,
   or only a render/reference?
2. What controlled conversion produces `freqs_hz` and `mag_db`?
3. What are the two measured/authored axes, and how will all four corners be
   authored without deriving Q100 silently?
4. Which source revision, relative path, hash, license, and adapter produced
   the result?
5. Has the packed runtime—not just the source fit—passed stability, finiteness,
   byte, and audio checks?

If any answer is unknown, the record stays `quarantined` or `classified` and
cannot be treated as a preset source.

## Current high-value shortlist

The read-only scan found these classes worth promoting into source cards:

- Surface Forge `.sofa` files: direct HRIR evidence, then `sofa_to_tf` and axis
  selection. Do not treat the generated `out/` bodies or plots as source.
- Surface Forge `*-vvtf-measured.txt`: direct TF tables with a small parser
  adapter. The documented `scripts/fit_data.py` entry point is currently
  absent, so this is not yet a one-command path.
- Surface Forge phononic and aeroacoustic CSVs: spectra/simulation evidence;
  inspect units and frequency mapping before fitting.
- `wav-source-library/measured_objects/ir_library` and `openair` WAVs: the
  strongest local IR intake, still conditional on acquisition metadata and
  license/provenance.
- Other WAV folders in the local library and `dev/tmp`: raw audio, generated
  tests, or audition material until a source card proves controlled excitation.
- `dev/tmp/measured_objects` WAV/JSON: possible local measurements/modal
  evidence, but the WAVs need acquisition metadata before `tf_ingest.py` can
  call them an IR.
- `dev/tmp/tf_oracle`: valuable fit/session/proof bundles; its rendered WAVs
  are not new measured IRs.

The large `dev/tmp/forge_all` body gallery and Surface Forge `out/` body gallery
are candidate/output banks. They are useful for audition and comparison, not
for sourcing a new IR.
