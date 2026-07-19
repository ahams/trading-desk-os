from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .adapters import adapt_engine_outputs
from .config import DecisionLayerConfig
from .models import Witness

logger = logging.getLogger("trading_desk.decision_layer")


REGIME_MULTIPLIERS = {
    "RISK_OFF": {
        "merton": 1.35,
        "liquidity": 1.20,
        "expectation": 1.15,
        "options": 1.10,
        "entry_quality": 1.10,
    },
    "RISK_ON": {
        "leadership": 1.22,
        "trend_quality": 1.18,
        "liquidity": 1.15,
        "optionality": 1.08,
    },
    "VOL_EXPANSION": {
        "options": 1.30,
        "liquidity": 1.20,
        "entry_quality": 1.18,
        "game": 1.12,
    },
    "VOL_COMPRESSION": {
        "entry_quality": 1.20,
        "technical": 1.12,
        "catalyst": 1.10,
    },
    "CHOP": {
        "entry_quality": 1.28,
        "liquidity": 1.15,
        "expectation": 1.12,
    },
}


def _regime_multiplier(engine: str, regime: str) -> float:
    return REGIME_MULTIPLIERS.get(regime.upper(), {}).get(engine, 1.0)


def _adjusted_strength(witness: Witness, regime: str) -> float:
    return witness.strength * _regime_multiplier(witness.engine, regime)


def _rank(witnesses: List[Witness], regime: str) -> List[Witness]:
    return sorted(
        witnesses,
        key=lambda witness: _adjusted_strength(witness, regime),
        reverse=True,
    )


def _recommendation_from_evidence(witnesses: List[Witness], regime: str) -> tuple[str, float]:
    bullish = sum(
        _adjusted_strength(w, regime)
        for w in witnesses
        if w.direction == "bullish"
    )
    bearish = sum(
        _adjusted_strength(w, regime)
        for w in witnesses
        if w.direction == "bearish"
    )
    total = bullish + bearish
    balance = 0.0 if total <= 0 else (bullish - bearish) / total
    confidence = round(min(92.0, 50.0 + abs(balance) * 42.0), 1)

    if balance >= 0.42:
        return "Constructive / Long Bias", confidence
    if balance >= 0.15:
        return "Constructive Watchlist", confidence
    if balance <= -0.42:
        return "Avoid / Short Bias", confidence
    if balance <= -0.15:
        return "Defensive Watchlist", confidence
    return "Mixed / No Decisive Edge", confidence


def _consensus(witnesses: List[Witness]) -> Dict[str, Any]:
    counts = {
        "bullish": sum(w.direction == "bullish" for w in witnesses),
        "bearish": sum(w.direction == "bearish" for w in witnesses),
        "neutral": sum(w.direction == "neutral" for w in witnesses),
    }
    non_neutral = counts["bullish"] + counts["bearish"]
    if non_neutral == 0:
        direction = "neutral"
        ratio = 0.0
    elif counts["bullish"] >= counts["bearish"]:
        direction = "bullish"
        ratio = counts["bullish"] / non_neutral
    else:
        direction = "bearish"
        ratio = counts["bearish"] / non_neutral
    return {
        "direction": direction,
        "agreement_pct": round(ratio * 100.0, 1),
        "counts": counts,
    }


def _committee_summary(
    legacy_decision: str,
    committee_view: str,
    decisive: Optional[Witness],
    conflict: bool,
    shadow_mode: bool,
) -> str:
    decisive_text = decisive.claim if decisive else "No single witness is sufficiently strong."
    mode_text = (
        f"The legacy verdict remains '{legacy_decision}' because Phase 1 runs in shadow mode."
        if shadow_mode
        else f"The committee view is '{committee_view}'."
    )
    conflict_text = (
        " Material conflict exists between constructive and adverse witnesses."
        if conflict
        else " The evidence is comparatively aligned."
    )
    return f"{mode_text} Decisive consideration: {decisive_text}{conflict_text}"


def build_reasoning(
    result: Dict[str, Any],
    config: Optional[DecisionLayerConfig] = None,
) -> Dict[str, Any]:
    """
    Build a Phase-1 investment-committee interpretation.

    This function is fail-safe by design. It returns a diagnostic payload on
    failure and never changes result['decision'].
    """
    config = config or DecisionLayerConfig.from_env()
    legacy_decision = str(result.get("decision") or "Watchlist Only")

    if not config.enabled:
        return {
            "enabled": False,
            "shadow_mode": True,
            "legacy_decision": legacy_decision,
            "status": "disabled",
        }

    try:
        witnesses = adapt_engine_outputs(result)
        regime = str(result.get("regime") or "UNKNOWN")
        ranked = _rank(witnesses, regime)
        decisive = ranked[0] if ranked else None

        supporting = [w for w in ranked if w.direction == "bullish"]
        contradictory = [w for w in ranked if w.direction == "bearish"]
        neutral = [w for w in ranked if w.direction == "neutral"]
        conflict = bool(supporting and contradictory)

        committee_view, confidence = _recommendation_from_evidence(witnesses, regime)
        consensus = _consensus(witnesses)

        invalidators: List[str] = []
        for witness in ranked:
            invalidators.extend(witness.invalidators)
        invalidators = list(dict.fromkeys(invalidators))[: config.max_invalidators]

        payload = {
            "version": "phase1.0",
            "enabled": True,
            "shadow_mode": config.shadow_mode,
            "status": "ok",
            "legacy_decision": legacy_decision,
            "committee_view": committee_view,
            "effective_decision": legacy_decision if config.shadow_mode else committee_view,
            "confidence": confidence,
            "regime": regime,
            "decisive_factor": (
                {
                    "engine": decisive.engine,
                    "claim": decisive.claim,
                    "direction": decisive.direction,
                    "score": decisive.score,
                    "strength": round(_adjusted_strength(decisive, regime), 4),
                }
                if decisive
                else None
            ),
            "consensus": consensus,
            "conflict_detected": conflict,
            "supporting_evidence": [
                {
                    "engine": witness.engine,
                    "claim": witness.claim,
                    "score": witness.score,
                    "strength": round(_adjusted_strength(witness, regime), 4),
                }
                for witness in supporting[: config.max_supporting]
            ],
            "contradictory_evidence": [
                {
                    "engine": witness.engine,
                    "claim": witness.claim,
                    "score": witness.score,
                    "strength": round(_adjusted_strength(witness, regime), 4),
                }
                for witness in contradictory[: config.max_contradictory]
            ],
            "context_evidence": [
                {
                    "engine": witness.engine,
                    "claim": witness.claim,
                    "score": witness.score,
                }
                for witness in neutral[:3]
            ],
            "invalidators": invalidators,
            "committee_summary": _committee_summary(
                legacy_decision,
                committee_view,
                decisive,
                conflict,
                config.shadow_mode,
            ),
            "witnesses": [witness.to_dict() for witness in witnesses],
        }
        return payload
    except Exception as exc:
        logger.exception("Decision layer failed")
        return {
            "version": "phase1.0",
            "enabled": True,
            "shadow_mode": True,
            "status": "degraded",
            "legacy_decision": legacy_decision,
            "effective_decision": legacy_decision,
            "error": f"{type(exc).__name__}: {exc}",
        }
