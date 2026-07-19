from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional

from .models import Witness


IMPORTANCE = {
    "fundamental": 0.78,
    "technical": 0.72,
    "trend_quality": 0.76,
    "entry_quality": 0.86,
    "leadership": 0.74,
    "liquidity": 0.86,
    "options": 0.78,
    "game": 0.70,
    "catalyst": 0.82,
    "expectation": 0.94,
    "merton": 0.92,
    "neocloud": 0.84,
    "optionality": 0.76,
}

LABELS = {
    "fundamental": "Fundamental",
    "technical": "Technical",
    "trend_quality": "Trend quality",
    "entry_quality": "Entry quality",
    "leadership": "Leadership",
    "liquidity": "Liquidity",
    "options": "Options",
    "game": "Participant behavior",
    "catalyst": "Catalyst",
    "expectation": "Expectation",
    "merton": "Capital structure",
    "neocloud": "Greenfield / NeoCloud",
    "optionality": "Optionality",
}


def _float(value: Any, default: float = 50.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _list_text(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        return [f"{key}: {val}" for key, val in value.items() if val is not None]
    if isinstance(value, Iterable):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value)]


def _direction(score: float) -> str:
    if score >= 60:
        return "bullish"
    if score <= 40:
        return "bearish"
    return "neutral"


def _claim(engine: str, score: float, meta: Dict[str, Any], summary: Dict[str, Any]) -> str:
    candidates = [
        meta.get("summary"),
        meta.get("signal"),
        meta.get("expectation_read"),
        meta.get("participant_read"),
        meta.get("catalyst_read"),
        meta.get("options_read"),
        summary.get(engine),
        summary.get("game_theory") if engine == "game" else None,
        summary.get("merton") if engine == "merton" else None,
        summary.get("neocloud") if engine == "neocloud" else None,
    ]
    for candidate in candidates:
        text = _text(candidate)
        if text:
            return text

    label = LABELS.get(engine, engine.replace("_", " ").title())
    if score >= 70:
        return f"{label} evidence is strongly constructive."
    if score >= 60:
        return f"{label} evidence is constructive."
    if score <= 30:
        return f"{label} evidence is strongly adverse."
    if score <= 40:
        return f"{label} evidence is adverse."
    return f"{label} evidence is mixed or inconclusive."


def _evidence(meta: Dict[str, Any]) -> List[str]:
    fields = (
        "flags",
        "reasons",
        "fundamental_reasons",
        "expectation_reasons",
        "options_reasons",
        "bull_points",
        "bear_points",
        "negative_flags",
    )
    items: List[str] = []
    for field in fields:
        items.extend(_list_text(meta.get(field)))
    # De-duplicate while preserving order.
    return list(dict.fromkeys(items))[:8]


def _invalidators(engine: str, score: float, meta: Dict[str, Any]) -> List[str]:
    supplied = _list_text(meta.get("invalidators"))
    if supplied:
        return supplied[:5]

    defaults = {
        "technical": "Price loses the technical invalidation level or trend structure.",
        "trend_quality": "Trend structure breaks and relative strength deteriorates.",
        "entry_quality": "The entry fails confirmation or breaches the planned stop.",
        "leadership": "The stock loses theme/sector leadership.",
        "liquidity": "Accumulation reverses into sustained distribution.",
        "options": "Options positioning turns materially defensive or destabilizing.",
        "catalyst": "The catalyst is delayed, rejected, diluted, or already fully discounted.",
        "expectation": "Market-implied expectations rise beyond what operating evidence can support.",
        "merton": "Refinancing, dilution, leverage, or default risk deteriorates.",
        "neocloud": "Funding, utilization, customer concentration, or execution risk worsens.",
        "optionality": "The market stops assigning value to future growth options.",
        "fundamental": "Revenue, margin, cash-flow, or balance-sheet quality deteriorates.",
        "game": "Participant incentives and forced-flow dynamics turn adverse.",
    }
    item = defaults.get(engine)
    return [item] if item and score != 50 else []


def adapt_engine_outputs(result: Dict[str, Any]) -> List[Witness]:
    scores = result.get("scores") or {}
    metas = result.get("metas") or {}
    summary = result.get("summary") or {}

    engine_keys = [
        "fundamental",
        "technical",
        "trend_quality",
        "entry_quality",
        "leadership",
        "liquidity",
        "options",
        "game",
        "catalyst",
        "expectation",
        "merton",
        "neocloud",
        "optionality",
    ]

    witnesses: List[Witness] = []
    for engine in engine_keys:
        if engine not in scores and engine not in metas:
            continue

        score = _float(scores.get(engine, (metas.get(engine) or {}).get("score", 50.0)))
        score = max(0.0, min(100.0, score))
        meta = metas.get(engine) or {}

        # Confidence grows with distance from neutral but is capped because
        # Phase 1 is heuristic and intentionally conservative.
        confidence = min(0.92, 0.52 + abs(score - 50.0) / 100.0)
        importance = IMPORTANCE.get(engine, 0.70)
        direction = _direction(score)

        if direction == "bullish":
            role = "supporting"
        elif direction == "bearish":
            role = "contradictory"
        else:
            role = "context"

        witnesses.append(
            Witness(
                engine=engine,
                claim=_claim(engine, score, meta, summary),
                direction=direction,
                score=round(score, 2),
                confidence=round(confidence, 3),
                importance=importance,
                role=role,
                evidence=_evidence(meta),
                invalidators=_invalidators(engine, score, meta),
                metadata={
                    "signal": meta.get("signal"),
                    "trade_impact": meta.get("trade_impact"),
                },
            )
        )

    return witnesses
