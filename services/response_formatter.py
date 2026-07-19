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

    merton = metas.get("merton") or {}
    merton_score = _round(merton.get("score"), 1)
    if merton_score is not None and merton_score < 50:
        reasons.append(f"Capital-structure/Merton credit risk is elevated ({merton_score}/100): {merton.get('signal', 'credit risk warning')}.")

    neocloud = metas.get("neocloud") or {}
    neocloud_score = _round(neocloud.get("score"), 1)
    if neocloud_score is not None and neocloud_score < 50 and neocloud.get("signal") != "Not a NeoCloud-specific name":
        reasons.append(f"NeoCloud valuation/funding quality is weak ({neocloud_score}/100): {neocloud.get('signal', 'valuation risk')}.")

    if not reasons:
        reasons.append("No major blocker detected; decision is mainly constrained by final score/threshold discipline.")
    return reasons

def harmonized_verdict(data: dict) -> dict:
    scores = data.get("scores", {}) or {}
    reads = data.get("reads", {}) or {}
    expected = data.get("expected_return", {}) or {}
    trade_plan = data.get("trade_plan", {}) or {}

    final_score = float(data.get("final_score") or 50)
    technical = float(scores.get("technical") or 50)
    liquidity = float(scores.get("liquidity") or 50)
    options = float(scores.get("options") or 50)
    game = float(scores.get("game_theory") or scores.get("game") or 50)
    fundamental = float(scores.get("fundamental") or 50)
    expectation = float(scores.get("expectation") or 50)
    merton = float(scores.get("merton_credit") or scores.get("merton") or 50)

    ev = expected.get("ev_pct")
    try:
        ev = float(ev)
        if abs(ev) <= 1.5:
            ev_pct = ev * 100
        else:
            ev_pct = ev
    except Exception:
        ev_pct = None

    bull_count = 0
    bear_count = 0

    if fundamental >= 75:
        bull_count += 1
    if technical >= 60:
        bull_count += 1
    if liquidity >= 60:
        bull_count += 1
    if expectation >= 65:
        bull_count += 1
    if merton >= 70:
        bull_count += 1
    if ev_pct is not None and ev_pct > 0:
        bull_count += 1

    if options < 35:
        bear_count += 1
    if game < 50:
        bear_count += 1
    if technical < 45:
        bear_count += 1
    if liquidity < 45:
        bear_count += 1
    if ev_pct is not None and ev_pct < 0:
        bear_count += 1

    # Harmonized decision
    if final_score >= 70 and bull_count >= 4 and (ev_pct is None or ev_pct > 1):
        decision = "Strong Long"
    elif final_score >= 60 and bull_count >= 4 and bear_count <= 2:
        if ev_pct is not None and ev_pct <= 0:
            decision = "Constructive Watchlist"
        else:
            decision = "Tactical Long"
    elif final_score >= 55 and bull_count >= 3:
        decision = "Constructive Watchlist"
    elif final_score <= 35:
        decision = "Avoid / Tactical Short"
    else:
        decision = data.get("decision", "Watchlist Only")

    # Better setup wording
    if technical >= 60 and liquidity >= 60 and options < 35:
        setup_type = "Strong trend, weak options confirmation"
    elif technical >= 60 and liquidity >= 60:
        setup_type = "Constructive trend continuation"
    elif technical >= 60 and liquidity < 50:
        setup_type = "Trend intact, liquidity not confirming"
    elif technical < 50 and final_score >= 60:
        setup_type = "Good stock, poor current entry"
    else:
        setup_type = data.get("setup_type", "Watchlist / no clean pattern")

    thesis_parts = []

    thesis_parts.append(
        f"{data.get('ticker')}: {decision}. "
        f"Final score {final_score:.1f}/100. Setup: {setup_type}."
    )

    if bull_count >= 4:
        thesis_parts.append(
            "Bull case is supported by strong fundamentals, positive expectation setup, "
            "healthy capital structure, and constructive liquidity/technical backdrop."
        )

    if options < 35:
        thesis_parts.append(
            "Main caution is options positioning: put demand / defensive skew is elevated, "
            "so equity strength is not fully confirmed by the options tape."
        )

    if game < 50:
        thesis_parts.append(
            "Forced-flow/game-theory confirmation is still weak, so this is not yet a clean squeeze setup."
        )

    if ev_pct is not None:
        if ev_pct > 1:
            thesis_parts.append(
                f"Trade expectancy is favorable at {ev_pct:.1f}%."
            )
        elif ev_pct >= 0:
            thesis_parts.append(
                f"Trade expectancy is marginal at {ev_pct:.1f}%."
            )
        else:
            thesis_parts.append(
                f"Trade expectancy is slightly negative at {ev_pct:.1f}%, suggesting a better entry may exist."
            )

    if trade_plan:
        thesis_parts.append(
            f"Trade plan: entry {trade_plan.get('entry')}, stop {trade_plan.get('stop')}, "
            f"target1 {trade_plan.get('target1')}, target2 {trade_plan.get('target2')}."
        )

    return {
        "decision": decision,
        "setup_type": setup_type,
        "final_thesis": " ".join(thesis_parts),
    }

def _greenfield_arr_read(ticker, meta):
    metrics = meta.get("metrics") or {}
    signal = meta.get("signal")

    has_capacity_metrics = any([
        metrics.get("secured_power_mw"),
        metrics.get("gpu_count"),
        metrics.get("ev_current_arr"),
        metrics.get("ev_target_arr"),
    ])

    if not has_capacity_metrics:
        return (
            f"Greenfield ARR/capacity read: {ticker} is not being valued as a pure "
            "capacity-owning NeoCloud operator. ARR/MW/GPU-fleet metrics are not directly "
            "applicable. Treat this as AI infrastructure supplier/platform exposure."
        )

    return meta.get("summary")



def _safe_float(x: Any, default: float = 50.0) -> float:
    try:
        return default if x is None else float(x)
    except Exception:
        return default


def _expectation_snapshot(meta: Dict[str, Any]) -> Dict[str, Any]:
    meta = meta or {}
    return {
        "signal": meta.get("expectation_signal") or meta.get("signal"),
        "read": meta.get("expectation_read") or meta.get("summary"),
        "implied_cagr_pct": _pct(meta.get("implied_cagr")),
        "revenue_growth_pct": _pct(meta.get("revenue_growth")),
        "market_implied_cap_years": _round(meta.get("market_implied_cap") or meta.get("cap_years"), 1),
        "roic_pct": _pct(meta.get("roic")),
        "meroi_pct": _pct(meta.get("meroi")),
        "growth_gap_pct": _pct(meta.get("growth_gap")),
        "roic_gap_pct": _pct(meta.get("roic_gap")),
        "expectation_hurdle": meta.get("expectation_hurdle"),
        "expectations_gap": _round(meta.get("expectations_gap"), 1),
    }


def _optionality_snapshot(meta: Dict[str, Any]) -> Dict[str, Any]:
    meta = meta or {}
    metrics = meta.get("metrics") or {}
    context = meta.get("expectation_context") or {}
    return {
        "score": _round(meta.get("score"), 1),
        "signal": meta.get("signal"),
        "summary": meta.get("summary"),
        "existing_business_value": _round(metrics.get("existing_business_value"), 0),
        "embedded_option_value": _round(metrics.get("embedded_option_value"), 0),
        "existing_value_pct": _pct(metrics.get("existing_value_pct")),
        "embedded_optionality_pct": _pct(metrics.get("embedded_optionality_pct")),
        "enterprise_value": _round(metrics.get("enterprise_value"), 0),
        "market_cap": _round(metrics.get("market_cap"), 0),
        "implied_cagr_pct": _pct(context.get("implied_cagr")),
        "revenue_growth_pct": _pct(context.get("revenue_growth")),
        "market_implied_cap_years": _round(context.get("market_implied_cap"), 1),
        "roic_pct": _pct(context.get("roic")),
        "meroi_pct": _pct(context.get("meroi")),
    }


def split_investment_vs_trading_view(data: Dict[str, Any]) -> Dict[str, Any]:
    scores = data.get("scores") or {}
    trade = data.get("trade_expectancy") or data.get("expected_return") or {}

    fundamental = _safe_float(scores.get("fundamental"))
    expectation = _safe_float(scores.get("expectation"))
    merton = _safe_float(scores.get("merton_credit") or scores.get("merton"))
    optionality = _safe_float(scores.get("optionality"),
                              _safe_float(scores.get("greenfield_arr_valuation")))

    technical = _safe_float(scores.get("technical"))
    liquidity = _safe_float(scores.get("liquidity"))
    options = _safe_float(scores.get("options"))
    game = _safe_float(scores.get("game_theory") or scores.get("game"))

    investment_score = round(
        0.32 * fundamental + 0.28 * expectation + 0.23 * merton + 0.17 * optionality, 1
    )
    trading_score = round(
        0.35 * technical + 0.25 * liquidity + 0.20 * options + 0.20 * game, 1
    )

    expectancy = trade.get("trade_expectancy_pct")
    if expectancy is None:
        expectancy = trade.get("ev_pct")
    try:
        expectancy = float(expectancy)
    except Exception:
        expectancy = None

    investment_view = (
        "Bullish" if investment_score >= 75 else
        "Constructive" if investment_score >= 60 else
        "Bearish" if investment_score < 40 else
        "Neutral"
    )
    trading_view = (
        "Bullish" if trading_score >= 70 and (expectancy is None or expectancy > 0) else
        "Constructive / Wait for confirmation" if trading_score >= 58 else
        "Bearish" if trading_score < 40 else
        "Neutral"
    )

    if investment_view in {"Bullish", "Constructive"} and trading_view.startswith("Constructive"):
        reason = "Investment evidence is supportive, but the near-term setup still requires cleaner confirmation."
        action = "Accumulate selectively on pullbacks or wait for a confirmed breakout."
    elif investment_view == "Bullish" and trading_view == "Bullish":
        reason = "Long-term investment quality and near-term trading conditions are aligned."
        action = "A tactical long is justified with the stated stop and position sizing."
    elif investment_view in {"Neutral", "Bearish"} and trading_view == "Bullish":
        reason = "Near-term momentum is stronger than the underlying investment case."
        action = "Treat this as a tactical trade rather than a core investment."
    elif investment_view in {"Bullish", "Constructive"} and trading_view == "Bearish":
        reason = "The longer-term thesis is intact, but current tape conditions are adverse."
        action = "Do not chase; wait for stabilization and renewed liquidity confirmation."
    else:
        reason = "Investment and trading evidence do not yet provide a sufficiently clear edge."
        action = "Review evidence before acting."

    return {
        "investment_view": investment_view,
        "investment_score": investment_score,
        "trading_view": trading_view,
        "trading_score": trading_score,
        "reason": reason,
        "action": action,
    }

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
    merton_meta = metas.get("merton") or {}
    neocloud_meta = metas.get("neocloud") or {}
    optionality_meta = metas.get("optionality") or {}

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
    if scores.get("merton") and float(scores.get("merton")) >= 70:
        bull_points.append(f"Capital structure supportive / low credit risk ({_round(scores.get('merton'), 1)}/100).")
    if scores.get("neocloud") and float(scores.get("neocloud")) >= 70:
        bull_points.append(f"NeoCloud capacity/ARR valuation supportive ({_round(scores.get('neocloud'), 1)}/100).")
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
    if scores.get("merton") and float(scores.get("merton")) < 50:
        bear_points.append(f"Capital-structure risk elevated ({_round(scores.get('merton'), 1)}/100).")
    if scores.get("neocloud") and float(scores.get("neocloud")) < 50 and neocloud_meta.get("signal") != "Not a NeoCloud-specific name":
        bear_points.append(f"NeoCloud valuation/funding risk elevated ({_round(scores.get('neocloud'), 1)}/100).")

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

    trade_expectancy = {
        "trade_expectancy_pct": _pct(result.get("trade_expectancy_pct")),
        "trade_expectancy_r": _round(result.get("trade_expectancy_r"), 2),
        "probability_win": _pct(result.get("probability_win")),
        "reward_pct": _pct(result.get("reward_pct")),
        "risk_pct": _pct(result.get("risk_pct")),
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
        "trade_expectancy": trade_expectancy,
        "scores": {
            "fundamental": _round(scores.get("fundamental"), 1),
            "technical": _round(scores.get("technical"), 1),
            "liquidity": _round(scores.get("liquidity"), 1),
            "options": _round(scores.get("options"), 1),
            "game_theory": _round(scores.get("game"), 1),
            "catalyst": _round(scores.get("catalyst"), 1),
            "expectation": _round(scores.get("expectation"), 1),
            "merton_credit": _round(scores.get("merton"), 1),
            "greenfield_arr_valuation": _round(scores.get("neocloud"), 1),
            "optionality": _round(scores.get("optionality"), 1),
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
            "merton_credit": merton_meta.get("summary") or summary.get("merton"),
            "greenfield_arr_valuation": (
            neocloud_meta.get("summary")
            or summary.get("neocloud")
            or "Greenfield ARR/capacity valuation not available."
        ),
            "theme": theme_meta.get("summary"),
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
        "greenfield_arr_snapshot": {
            "score": _round(neocloud_meta.get("score"), 1),
            "signal": neocloud_meta.get("signal"),
            "subscores": neocloud_meta.get("subscores") or {},
            "ev_current_arr": _round((neocloud_meta.get("metrics") or {}).get("ev_current_arr"), 2),
            "ev_target_arr": _round((neocloud_meta.get("metrics") or {}).get("ev_target_arr"), 2),
            "secured_power_mw": _round((neocloud_meta.get("metrics") or {}).get("secured_power_mw"), 0),
            "gpu_count": _round((neocloud_meta.get("metrics") or {}).get("gpu_count"), 0),
        },
        "expectation_snapshot": _expectation_snapshot(expected_meta),
        "optionality_snapshot": _optionality_snapshot(optionality_meta),
        "final_thesis": result.get("thesis"),

        # Phase-1 investment-committee interpretation. The legacy decision
        # remains authoritative while reasoning runs in shadow mode.
        "reasoning": result.get("reasoning") or {
            "enabled": False,
            "shadow_mode": True,
            "status": "not_available",
            "legacy_decision": decision,
        },
    }

    compact["decision_layer"] = split_investment_vs_trading_view(compact)

    verdict = harmonized_verdict(compact)

    compact["decision"] = verdict["decision"]
    compact["setup_type"] = verdict["setup_type"]
    compact["final_thesis"] = verdict["final_thesis"]   
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
