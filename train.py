#!/usr/bin/env python3
"""Single production authoring entry point. Hydra config is the run truth."""
from __future__ import annotations

import hydra
from omegaconf import DictConfig

from src.models.quality_diversity import run


@hydra.main(version_base="1.3", config_path="configs", config_name="train")
def main(cfg: DictConfig) -> None:
    run(cfg)


if __name__ == "__main__":
    main()
