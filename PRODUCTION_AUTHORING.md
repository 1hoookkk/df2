# Production Authoring

DF2 does not ship a neural network. Its runtime truth is:

```text
240-byte packed body -> 4 corners -> Morph/Q interpolation -> 6 biquads -> AGC -> audio
```

The production authoring workflow mirrors a disciplined ML repository without inventing a model that the product does not use.

| Phase | Command or owner | Output |
| --- | --- | --- |
| Configuration | `configs/` and Hydra overrides | Reproducible resolved YAML |
| Calibration I/O | `src/datamodules/calibration.py` | Aggregate-only ROM corridor metrics |
| Mathematical architecture | `src/architectures/trajectory_program.py` | Lawful joint four-corner pole-zero programs |
| Search | `src/models/quality_diversity.py` | Diverse high-scoring archive cells |
| Telemetry | `src/utils/telemetry.py` | Immutable JSONL, archive checkpoint, and W&B offline artifact mirror |
| Runtime gate | `src/utils/packed_runtime.py` | Shipped `trench_core.dll` Morph/Q proof |
| Export | `src/utils/export_runtime.py` and `scripts/export.py` | `.body240`, `compiled-v1`, plots, WAVs |

Run the production search:

```powershell
python train.py model=v1
```

Run a fast structural proof:

```powershell
python train.py model=smoke telemetry.mode=disabled export.render_audio=false run_name=smoke_verify
```

Promote a verified run:

```powershell
python scripts/export.py <verified-run-directory>
```

Prove the complete persisted run and promoted bytes:

```powershell
python scripts/verify_run.py <verified-run-directory> --promotion-dir <promotion-directory>
```

Study utilities and source-fit experiments remain under `tools/`. They can inform new constructors, but they cannot bypass the packed-runtime production gate.

The production bank is role-complete by construction: `configs/specialists/full_bank.yaml`
defines 50 original DF2 specialist slots. A full `model=v1` run fails unless one
jointly authored packed-runtime survivor for every slot passes the final `17x17`
Morph/Q audit.
