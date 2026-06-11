---
name: production-authoring
description: Use for every DF2 production body generation, search, audit, or promotion task.
---

# DF2 Production Authoring

Read `AGENTS.md` and `PRODUCTION_AUTHORING.md` before editing authoring code.

Use only:

```powershell
python train.py model=smoke telemetry.mode=disabled export.render_audio=false run_name=smoke_verify
python train.py model=v1
python scripts/export.py <verified-run-directory>
python scripts/verify_run.py <verified-run-directory> --promotion-dir <promotion-directory>
```

Never author production bodies through a one-off `tools/` script. Never fit four corners independently. Never use reference coefficients as a design surface. Every promoted body must be a clean-room joint trajectory program that passes the shipped `trench_core.dll` audit.

`configs/specialists/full_bank.yaml` is the required original DF2 bank catalog.
Full `model=v1` production fails unless all 50 specialist slots export one final
`17x17`-audited packed body.
