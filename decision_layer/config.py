from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class DecisionLayerConfig:
    enabled: bool = True
    shadow_mode: bool = True
    max_supporting: int = 5
    max_contradictory: int = 5
    max_invalidators: int = 5

    @classmethod
    def from_env(cls) -> "DecisionLayerConfig":
        return cls(
            enabled=_env_bool("TDOS_DECISION_LAYER_ENABLED", True),
            shadow_mode=_env_bool("TDOS_DECISION_LAYER_SHADOW_MODE", True),
        )
