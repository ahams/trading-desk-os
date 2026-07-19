from __future__ import annotations

from typing import Any, Dict, List, Optional


def _round(x: Any, ndigits: int = 2) -> Optional[float]:
    try:
        if x is None:
            return None
        return round(float(x), ndigits)
    except Exception:
        return None


def _pct(x: Any, ndigits: int = 1) -> Optional[float]:
    """Convert decimal return to percent. If value already looks like percent, keep it."""
    try:
        if x is None:
            return None
        v = float(x)
        if abs(v) <= 2.0:
            v *= 100.0
        return round(v, ndigits)
    except Exception:
        return None


def _first(items: Any, n: int = 3) -> List[str]:
    if not items:
        return []
    if isinstance(items, str):
        return [items]
    try:
        return [str(x) for x in list(items)[:n] if x]
    except Exception:
        return []


def _score_bucket(score: Any) -> str:
    s = _round(score, 1) or 0
    if s >= 80:
        return "institutional-quality setup"
    if s >= 70:
        return "actionable setup"
    if s >= 60:
        return "tactical/watchlist setup"
    if s >= 45:
        return "mixed setup"
    return "avoid / weak setup"


def _why_not_long(result: Dict[str, Any]) -> List[str]:
    """Explain what is blocking a long decision in plain English."""
    reasons: List[str] = []
    scores = result.get("scores") or {}
    metas = result.get("metas") or {}

    technical = _round(scores.get("technical"), 1)
    liquidity = _round(scores.get("liquidity"), 1)
    game = _round(scores.get("game"), 1)
    expected = result.get("expected_return")

    if technical is not None and technical < 50:
        setup = (metas.get("technical") or {}).get("setup_type") or "no clean technical setup"
        reasons.append(f"Technical timing is weak ({technical}/100): {setup}.")

    if liquidity is not None and liquidity < 50:
        lsum = (result.get("summary") or {}).get("liquidity") or "liquidity/volume confirmation is weak"
        reasons.append(f"Liquidity confirmation is weak ({liquidity}/100): {lsum}")

    if game is not None and game < 55:
        g = metas.get("game") or {}
        env = g.get("environment") or "no clear forced-flow edge"
        reasons.append(f"Forced-flow/game-theory read is not compelling ({game}/100): {env}.")

    exp_pct = _pct(expected)
    if exp_pct is not None and exp_pct < 0:
        reasons.append(f"Expected-return model is negative ({exp_pct}%), so the reward does not justify immediate long exposure.")

    theme = metas.get("theme") or {}
    theme_score = _round(theme.get("total"), 1)
    if theme_score is not None and theme_score < 40:
        reasons.append(f"Theme participation is weak ({theme_score}/100): ticker is lagging its theme or benchmark.")

    if not reasons:
        reasons.append("No major blocker detected; decision is mainly constrained by final score/threshold discipline.")
    return reasons


def compact_analysis(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert verbose engine output into a monetizable, end-user friendly response.

    Keeps the important trading-desk fields and hides deep internal metas unless
    the user requests the full /api/v1/analyze payload.
    """
    if result.get("error"):
        return {
            "ticker": result.get("ticker"),
            "error": result.get("error"),
            "decision": result.get("decision", "Avoid"),
        }

    scores = result.get("scores") or {}
    metas = result.get("metas") or {}
    summary = result.get("summary") or {}
    options_meta = metas.get("options") or {}
    game_meta = metas.get("game") or {}
    liquidity_meta = metas.get("liquidity") or {}
    theme_meta = metas.get("theme") or {}
    expected_meta = metas.get("expectation") or {}
    merton_meta =metas.get("merton") or {}
    neocloud_meta = metas.get("neocloud") or {}
    decision = result.get("decision")
    final_score = _round(result.get("final_score"), 1)
    setup_type = result.get("setup_type")

    blockers = []
    if decision in {"Watchlist Only", "Avoid", "Tactical Short", "Strong Short"}:
        blockers = _why_not_long(result)

    bull_points = []
    if scores.get("fundamental") and float(scores.get("fundamental")) >= 70:
        bull_points.append(f"Strong fundamentals ({_round(scores.get('fundamental'), 1)}/100).")
    if scores.get("options") and float(scores.get("options")) >= 65:
        bull_points.append(f"Options positioning supportive ({_round(scores.get('options'), 1)}/100).")
    if scores.get("expectation") and float(scores.get("expectation")) >= 65:
        bull_points.append(f"Expectations look beatable ({_round(scores.get('expectation'), 1)}/100).")
    if result.get("regime"):
        bull_points.append(f"Market regime: {result.get('regime')}.")

    bear_points = []
    if scores.get("technical") and float(scores.get("technical")) < 50:
        bear_points.append(f"Technical score weak ({_round(scores.get('technical'), 1)}/100).")
    if scores.get("liquidity") and float(scores.get("liquidity")) < 50:
        bear_points.append(f"Liquidity/volume score weak ({_round(scores.get('liquidity'), 1)}/100).")
    if liquidity_meta.get("cmf") is not None and float(liquidity_meta.get("cmf")) < -0.05:
        bear_points.append(f"Negative CMF ({_round(liquidity_meta.get('cmf'), 2)}), suggesting distribution.")
    if theme_meta.get("total") is not None and float(theme_meta.get("total")) < 40:
        bear_points.append("Ticker is lagging its theme/basket.")

    trade_plan = {
        "entry": _round(result.get("entry"), 2),
        "stop": _round(result.get("stop"), 2),
        "target1": _round(result.get("target1"), 2),
        "target2": _round(result.get("target2"), 2),
        "risk_reward": _round(result.get("rr") or result.get("risk_reward"), 2),
        "position_size": result.get("position_size"),
        "invalidates_if": blockers[:3] if blockers else ["Breaks stop or thesis drivers deteriorate."],
    }

    expected_return = {
        "ev_pct": _pct(result.get("expected_return")),
        "expected_r": _round(result.get("expected_r"), 2),
        "probability_win": _pct(result.get("probability_win")),
        "read": summary.get("expected_return"),
    }

    participant_map = game_meta.get("participant_map") or {}
    dominant_participants = {}
    for k, v in participant_map.items():
        if isinstance(v, dict):
            dominant_participants[k] = {
                "bias": v.get("bias"),
                "pressure": _round(v.get("pressure"), 1),
            }

    compact = {
        "ticker": result.get("ticker"),
        "price": _round(result.get("price"), 2),
        "decision": decision,
        "final_score": final_score,
        "score_read": _score_bucket(final_score),
        "setup_type": setup_type,
        "regime": result.get("regime"),
        "theme": result.get("theme"),
        "trade_plan": trade_plan,
        "expected_return": expected_return,
        "scores": {
            "fundamental": _round(scores.get("fundamental"), 1),
            "technical": _round(scores.get("technical"), 1),
            "liquidity": _round(scores.get("liquidity"), 1),
            "options": _round(scores.get("options"), 1),
            "game_theory": _round(scores.get("game"), 1),
            "catalyst": _round(scores.get("catalyst"), 1),
            "expectation": _round(scores.get("expectation"), 1),
            "merton_credit": _round(scores.get("merton"), 1),
            "neocloud_valuation": _round(scores.get("neocloud"), 1),
        },
        "main_bull_case": bull_points[:5] or [summary.get("fundamental") or "No clear bull case detected."],
        "main_bear_case": bear_points[:5] or ["No major bearish factor detected."],
        "why_not_long_now": blockers,
        "reads": {
            "technical": summary.get("technical"),
            "liquidity": summary.get("liquidity"),
            "options": summary.get("options") or options_meta.get("options_read"),
            "game_theory": game_meta.get("participant_read") or summary.get("game_theory"),
            "catalyst": summary.get("catalyst"),
            "expectation": expected_meta.get("expectation_read") or summary.get("expectation"),
            "theme": theme_meta.get("summary"),
            "merton_credit": merton_meta.get("summary") or summary.get("merton"),
            "neocloud_valuation": neocloud_meta.get("summary") or summary.get("neocloud"),
        },
        "options_snapshot": {
            "expiry": options_meta.get("expiry"),
            "put_call_oi": _round(options_meta.get("put_call_oi"), 2),
            "put_call_volume": _round(options_meta.get("put_call_volume"), 2),
            "atm_iv_pct": _pct(options_meta.get("atm_iv")),
            "max_pain": _round(options_meta.get("max_pain"), 2),
            "gamma_zone": _round(options_meta.get("gamma_zone"), 2),
        },
        "game_theory_snapshot": {
            "environment": game_meta.get("environment"),
            "forced_flow_score": _round(game_meta.get("forced_flow_score"), 1),
            "short_squeeze_score": _round(game_meta.get("short_squeeze_score"), 1),
            "gamma_squeeze_score": _round(game_meta.get("gamma_squeeze_score"), 1),
            "pinning_risk_score": _round(game_meta.get("pinning_risk_score"), 1),
            "dominant_participants": dominant_participants,
        },
        "capital_structure_snapshot": {
                "score": _round(merton_meta.get("score"), 1),
                "signal": merton_meta.get("signal"),
                "risk": (merton_meta.get("trade_impact") or {}).get("risk"),
                "distance_to_default": _round((merton_meta.get("metrics") or {}).get("distance_to_default"), 2),
                "pd_annual_proxy_pct": _pct((merton_meta.get("metrics") or {}).get("pd_annual_proxy")),
                "net_debt_to_market_cap_pct": _pct((merton_meta.get("metrics") or {}).get("net_debt_to_market_cap")),
            },
            "neocloud_snapshot": {
                "score": _round(neocloud_meta.get("score"), 1),
                "signal": neocloud_meta.get("signal"),
                "subscores": neocloud_meta.get("subscores") or {},
                "ev_current_arr": _round((neocloud_meta.get("metrics") or {}).get("ev_current_arr"), 2),
                "ev_target_arr": _round((neocloud_meta.get("metrics") or {}).get("ev_target_arr"), 2),
                "secured_power_mw": _round((neocloud_meta.get("metrics") or {}).get("secured_power_mw"), 0),
                "gpu_count": _round((neocloud_meta.get("metrics") or {}).get("gpu_count"), 0),
            },
        "final_thesis": result.get("thesis"),
    }
    return compact


def compact_scanner(scan_result: Dict[str, Any], top_n: int = 20) -> Dict[str, Any]:
    rows = scan_result.get("results") or []
    compact_rows = [compact_analysis(r) for r in rows[:top_n]]
    return {
        "as_of": scan_result.get("as_of"),
        "regime": scan_result.get("regime"),
        "count": len(compact_rows),
        "results": compact_rows,
        "errors": scan_result.get("errors", []),
    }
