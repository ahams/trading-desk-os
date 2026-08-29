from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

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


# Economic relevance to an equity investment decision.
# This prevents a very strong "confirming" witness (e.g. healthy credit)
# from automatically becoming the primary investment driver.
DECISION_RELEVANCE = {
    "fundamental": 1.00,
    "expectation": 1.00,
    "optionality": 0.85,
    "leadership": 0.85,
    "trend_quality": 0.82,
    "technical": 0.80,
    "entry_quality": 0.78,
    "liquidity": 0.72,
    "options": 0.70,
    "game": 0.70,
    "catalyst": 0.68,
    "neocloud": 0.65,
    "merton": 0.40,
}


def _regime_multiplier(engine: str, regime: str) -> float:
    return REGIME_MULTIPLIERS.get(regime.upper(), {}).get(engine, 1.0)


def _adjusted_strength(witness: Witness, regime: str) -> float:
    """Regime-aware witness strength used for aggregate recommendation."""
    return witness.strength * _regime_multiplier(witness.engine, regime)


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _merton_materiality(result: Dict[str, Any], witness: Witness) -> float:
    """
    Dynamic relevance for Merton / credit.

    Healthy credit is usually confirming evidence, not the reason to own an equity.
    Credit becomes decision-critical when the witness is bearish or the underlying
    capital-structure metrics indicate genuine distress.
    """
    # A bearish Merton witness should be allowed to become decisive immediately.
    if witness.direction == "bearish":
        return 1.00

    snap = result.get("capital_structure_snapshot") or {}
    risk = str(snap.get("risk") or "").strip().lower()
    score = _safe_float(snap.get("score"))
    dtd = _safe_float(snap.get("distance_to_default"))
    pd_pct = _safe_float(snap.get("pd_annual_proxy_pct"))

    severe_risk_labels = {
        "high",
        "high risk",
        "elevated",
        "elevated risk",
        "distressed",
        "distress",
    }
    moderate_risk_labels = {
        "moderate",
        "moderate risk",
        "medium",
        "medium risk",
    }

    severe = (
        risk in severe_risk_labels
        or (score is not None and score < 45)
        or (dtd is not None and dtd < 2.0)
        or (pd_pct is not None and pd_pct >= 10.0)
    )
    if severe:
        return 1.00

    moderate = (
        risk in moderate_risk_labels
        or (score is not None and score < 65)
        or (dtd is not None and dtd < 4.0)
        or (pd_pct is not None and pd_pct >= 3.0)
    )
    if moderate:
        return 0.75

    # Healthy Merton output = useful confirmation, not a primary equity driver.
    return 0.40


def _decision_relevance(witness: Witness, result: Dict[str, Any]) -> float:
    if witness.engine == "merton":
        return _merton_materiality(result, witness)
    return DECISION_RELEVANCE.get(witness.engine, 0.60)


def _decision_strength(
    witness: Witness,
    regime: str,
    result: Dict[str, Any],
) -> float:
    """
    Strength used specifically for choosing the primary decision driver.

    recommendation strength = witness strength × regime
    decision strength       = recommendation strength × economic relevance
    """
    return (
        _adjusted_strength(witness, regime)
        * _decision_relevance(witness, result)
    )


def _rank(witnesses: List[Witness], regime: str) -> List[Witness]:
    """Rank evidence for display/aggregation using regime-adjusted strength."""
    return sorted(
        witnesses,
        key=lambda witness: _adjusted_strength(witness, regime),
        reverse=True,
    )


def _rank_for_decision(
    witnesses: List[Witness],
    regime: str,
    result: Dict[str, Any],
) -> List[Witness]:
    """Rank witnesses by economic decision relevance × strength."""
    return sorted(
        witnesses,
        key=lambda witness: _decision_strength(witness, regime, result),
        reverse=True,
    )


def _recommendation_from_evidence(
    witnesses: List[Witness],
    regime: str,
) -> Tuple[str, float]:
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


def _engine_label(engine: str) -> str:
    labels = {
        "fundamental": "Business quality",
        "expectation": "Market expectations",
        "optionality": "Future value / optionality",
        "leadership": "Market leadership",
        "trend_quality": "Trend quality",
        "technical": "Technical structure",
        "entry_quality": "Entry quality",
        "liquidity": "Liquidity / positioning",
        "options": "Options positioning",
        "game": "Participant behavior",
        "catalyst": "Catalyst profile",
        "neocloud": "Greenfield / capacity economics",
        "merton": "Financial resilience",
    }
    return labels.get(engine, engine.replace("_", " ").title())


def _professional_committee_summary(
    committee_view: str,
    decisive: Optional[Witness],
    supporting: List[Witness],
    contradictory: List[Witness],
    conflict: bool,
) -> str:
    """
    Client-facing summary. Intentionally excludes implementation language
    such as legacy verdicts, Phase 1, and shadow mode.
    """
    if decisive:
        primary = (
            f"The primary decision driver is {_engine_label(decisive.engine).lower()}: "
            f"{decisive.claim}"
        )
    else:
        primary = "No single factor dominates the committee assessment."

    if contradictory:
        constraint = (
            f"The principal counterweight is {_engine_label(contradictory[0].engine).lower()}: "
            f"{contradictory[0].claim}"
        )
    elif conflict:
        constraint = "The committee sees meaningful cross-signal conflict."
    else:
        constraint = "There is no material adverse witness strong enough to overturn the current view."

    return (
        f"The committee view is '{committee_view}'. "
        f"{primary} {constraint}"
    )


def _classify_driver_role(
    witness: Witness,
    decisive: Optional[Witness],
    result: Dict[str, Any],
) -> str:
    """
    Human-readable role for the frontend/audit layer.

    A healthy Merton signal is normally confirming evidence.
    A distressed/bearish Merton signal can become a primary constraint.
    """
    if decisive is witness:
        return "primary_driver"

    if witness.engine == "merton":
        relevance = _decision_relevance(witness, result)
        if relevance >= 0.95 and witness.direction == "bearish":
            return "primary_constraint"
        return "confirming_factor"

    if witness.direction == "bearish":
        return "constraint"
    if witness.direction == "bullish":
        return "supporting_factor"
    return "context"


def build_reasoning(
    result: Dict[str, Any],
    config: Optional[DecisionLayerConfig] = None,
) -> Dict[str, Any]:
    """
    Build a Phase-1 investment-committee interpretation.

    This function is fail-safe by design. In shadow mode it does not change
    result['decision']; the committee output remains an interpretive layer.
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

        # Evidence ranking: regime-aware strength.
        ranked = _rank(witnesses, regime)

        # Decision-driver ranking: regime-aware strength × economic relevance.
        decision_ranked = _rank_for_decision(witnesses, regime, result)
        decisive = decision_ranked[0] if decision_ranked else None

        supporting = [w for w in ranked if w.direction == "bullish"]
        contradictory = [w for w in ranked if w.direction == "bearish"]
        neutral = [w for w in ranked if w.direction == "neutral"]
        conflict = bool(supporting and contradictory)

        committee_view, confidence = _recommendation_from_evidence(
            witnesses,
            regime,
        )
        consensus = _consensus(witnesses)

        invalidators: List[str] = []
        for witness in ranked:
            invalidators.extend(witness.invalidators)
        invalidators = list(dict.fromkeys(invalidators))[: config.max_invalidators]

        decision_drivers = []
        for witness in decision_ranked:
            decision_drivers.append(
                {
                    "engine": witness.engine,
                    "label": _engine_label(witness.engine),
                    "claim": witness.claim,
                    "direction": witness.direction,
                    "role": _classify_driver_role(witness, decisive, result),
                    "score": witness.score,
                    "strength": round(_adjusted_strength(witness, regime), 4),
                    "decision_relevance": round(
                        _decision_relevance(witness, result), 3
                    ),
                    "decision_strength": round(
                        _decision_strength(witness, regime, result), 4
                    ),
                }
            )

        payload = {
            "version": "phase1.1",
            "enabled": True,
            "shadow_mode": config.shadow_mode,
            "status": "ok",
            "legacy_decision": legacy_decision,
            "committee_view": committee_view,
            "effective_decision": (
                legacy_decision if config.shadow_mode else committee_view
            ),
            "confidence": confidence,
            "regime": regime,

            # Primary factor is now relevance-aware rather than strength-only.
            "decisive_factor": (
                {
                    "engine": decisive.engine,
                    "label": _engine_label(decisive.engine),
                    "claim": decisive.claim,
                    "direction": decisive.direction,
                    "score": decisive.score,
                    "strength": round(_adjusted_strength(decisive, regime), 4),
                    "decision_relevance": round(
                        _decision_relevance(decisive, result), 3
                    ),
                    "decision_strength": round(
                        _decision_strength(decisive, regime, result), 4
                    ),
                }
                if decisive
                else None
            ),

            # New structured field for a professional frontend.
            "decision_drivers": decision_drivers,

            "consensus": consensus,
            "conflict_detected": conflict,

            "supporting_evidence": [
                {
                    "engine": witness.engine,
                    "label": _engine_label(witness.engine),
                    "claim": witness.claim,
                    "score": witness.score,
                    "strength": round(_adjusted_strength(witness, regime), 4),
                    "decision_relevance": round(
                        _decision_relevance(witness, result), 3
                    ),
                }
                for witness in supporting[: config.max_supporting]
            ],

            "contradictory_evidence": [
                {
                    "engine": witness.engine,
                    "label": _engine_label(witness.engine),
                    "claim": witness.claim,
                    "score": witness.score,
                    "strength": round(_adjusted_strength(witness, regime), 4),
                    "decision_relevance": round(
                        _decision_relevance(witness, result), 3
                    ),
                }
                for witness in contradictory[: config.max_contradictory]
            ],

            "context_evidence": [
                {
                    "engine": witness.engine,
                    "label": _engine_label(witness.engine),
                    "claim": witness.claim,
                    "score": witness.score,
                }
                for witness in neutral[:3]
            ],

            "invalidators": invalidators,

            # Professional/client-facing summary.
            "committee_summary": _professional_committee_summary(
                committee_view,
                decisive,
                supporting,
                contradictory,
                conflict,
            ),

            # Keep implementation details available for audit/debug only.
            "model_audit": {
                "legacy_decision": legacy_decision,
                "committee_view": committee_view,
                "effective_decision": (
                    legacy_decision if config.shadow_mode else committee_view
                ),
                "shadow_mode": config.shadow_mode,
                "ranking_method": (
                    "decisive factor = regime-adjusted witness strength "
                    "x economic decision relevance"
                ),
            },

            "witnesses": [witness.to_dict() for witness in witnesses],
        }

        return payload

    except Exception as exc:
        logger.exception("Decision layer failed")
        return {
            "version": "phase1.1",
            "enabled": True,
            "shadow_mode": True,
            "status": "degraded",
            "legacy_decision": legacy_decision,
            "effective_decision": legacy_decision,
            "error": f"{type(exc).__name__}: {exc}",
        }
