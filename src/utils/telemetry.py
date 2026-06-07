"""Local immutable telemetry with optional W&B offline mirroring."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


class Telemetry:
    def __init__(self, run_dir: Path, cfg: Any, run_name: str) -> None:
        self.run_dir = run_dir
        self.events = run_dir / "events.jsonl"
        self.wandb_run = None
        mode = str(cfg.mode)
        if mode != "disabled":
            import wandb
            self.wandb_run = wandb.init(
                project=str(cfg.project),
                entity=None if cfg.entity is None else str(cfg.entity),
                name=run_name,
                dir=str(run_dir),
                mode=mode,
                config={},
                reinit="finish_previous",
            )

    def log(self, event: str, payload: dict[str, Any], *, step: int | None = None) -> None:
        row = {
            "at": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "step": step,
            "payload": payload,
        }
        with self.events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        if self.wandb_run is not None:
            flat = {f"{event}/{key}": value for key, value in payload.items()
                    if isinstance(value, (int, float, bool))}
            if flat:
                self.wandb_run.log(flat, step=step)

    def log_artifact(self, name: str, paths: list[Path]) -> None:
        if self.wandb_run is None:
            return
        import wandb
        artifact_manifest = self.run_dir / "wandb_artifact_manifest.json"
        artifact_manifest.write_text(json.dumps({
            "artifact": name,
            "type": "production-authoring-run",
            "paths": [str(path.relative_to(self.run_dir)).replace("\\", "/") for path in paths],
        }, indent=2) + "\n", encoding="utf-8")
        artifact = wandb.Artifact(name=name, type="production-authoring-run")
        artifact.add_file(str(artifact_manifest), name=artifact_manifest.name)
        for path in paths:
            if path.is_dir():
                artifact.add_dir(str(path), name=path.name)
            else:
                artifact.add_file(str(path), name=path.name)
        self.wandb_run.log_artifact(artifact)

    def finish(self) -> None:
        if self.wandb_run is not None:
            self.wandb_run.finish()
