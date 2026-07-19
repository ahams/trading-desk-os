"""
TDOS Phase-1 reasoning/decision layer.

Shadow-mode contract:
- interprets existing engine output;
- never changes the legacy decision;
- never raises into analysis_service;
- returns JSON-safe dictionaries.
"""

from .committee import build_reasoning
from .config import DecisionLayerConfig

__all__ = ["build_reasoning", "DecisionLayerConfig"]
