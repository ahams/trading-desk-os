from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# Small formatting helpers
# =============================================================================

def _round(x: Any, ndigits: int = 2) -> Optional[float]:
    try:
        if x is None:
            return None
        return round(float(x), ndigits)
    except Exception:
        return None


def _pct(x: Any, ndigits: int = 1) -> Optional[float]:
    """
    Normalize a decimal ratio into percentage points.

    Examples:
        0.12  -> 12.0
        12.0  -> 12.0
        -0.003 -> -0.3
    """
    try:
        if x is None:
            return None
        v = float(x)
        if abs(v) <= 2.0:
            v *= 100.0
        return round(v, ndigits)
    except Exception:
        return None


def _safe_float(x: Any, default: float = 50.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


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


def _dedupe(items: List[str], limit: int = 6) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        if not item:
            continue
        s = str(item).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _metric(meta: Dict[str, Any], *keys: str) -> Any:
    """
    Search a metadata dict and nested metrics dict for the first available key.
    """
    metrics = meta.get("metrics") if isinstance(meta.get("metrics"), dict) else {}
    for key in keys:
        if key in meta and meta.get(key) is not None:
            return meta.get(key)
        if key in metrics and metrics.get(key) is not None:
            return metrics.get(key)
    return None


# =============================================================================
# Specialized reads
# =============================================================================

def _greenfield_arr_read(ticker: str, meta: Dict[str, Any]) -> str:
    meta = meta or {}
    metrics = meta.get("metrics") or {}

    has_capacity_metrics = any(
        metrics.get(k) is not None
        for k in ["secured_power_mw", "gpu_count", "ev_current_arr", "ev_target_arr"]
    )

    if not has_capacity_metrics:
        return (
            f"Greenfield ARR/capacity read: {ticker} is not being valued as a pure "
            "capacity-owning NeoCloud operator. ARR/MW/GPU-fleet metrics are not directly "
            "applicable. Treat this as AI infrastructure supplier/platform exposure."
        )

    return (
        meta.get("summary")
        or meta.get("read")
        or f"{ticker}: Greenfield ARR/capacity metrics are available but require interpretation."
    )


def expectation_bull_bear_flags(data: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """
    Convert the richer expectation investing output into explicit bull/bear points.

    This is where insights like:
      "Implied CAGR 80% vs revenue growth 37.8%; CAP 19 yrs; ROIC 7.6% vs MEROI 60%"
    become visible in dashboard bull/bear cases rather than hidden inside reads.
    """
    scores = data.get("scores") or {}
    reads = data.get("reads") or {}
    metas = data.get("metas") or {}

    exp_meta = (
        metas.get("expectation")
        or data.get("expectation_meta")
        or data.get("expectation_snapshot")
        or {}
    )

    exp_score = scores.get("expectation")
    exp_read = (
        reads.get("expectation")
        or exp_meta.get("expectation_read")
        or exp_meta.get("read")
        or ""
    )

    bulls: List[str] = []
    bears: List[str] = []

    implied_cagr = _pct(_metric(exp_meta, "implied_cagr"), 1)
    revenue_growth = _pct(_metric(exp_meta, "revenue_growth", "rev_growth"), 1)
    cap_years = _metric(exp_meta, "market_implied_cap", "cap_years")
    roic = _pct(_metric(exp_meta, "roic"), 1)
    meroi = _pct(_metric(exp_meta, "meroi"), 1)

    exp_read_clean = str(exp_read).replace("Expectation investing: ", "").strip()

    if "demanding" in exp_read_clean.lower():
        bears.append(f"Expectation hurdle is demanding: {exp_read_clean}")
    elif "beatable" in exp_read_clean.lower():
        bulls.append(f"Expectations look beatable: {exp_read_clean}")

    if implied_cagr is not None and revenue_growth is not None:
        if implied_cagr > revenue_growth * 1.5:
            bears.append(
                f"Market-implied growth looks demanding: implied CAGR {implied_cagr:.1f}% "
                f"vs current revenue growth {revenue_growth:.1f}%."
            )
        elif revenue_growth > implied_cagr:
            bulls.append(
                f"Current growth exceeds market hurdle: revenue growth {revenue_growth:.1f}% "
                f"vs implied CAGR {implied_cagr:.1f}%."
            )

    if roic is not None and meroi is not None:
        if roic < meroi * 0.75:
            bears.append(f"Value-creation hurdle is high: ROIC {roic:.1f}% vs MEROI {meroi:.1f}%.")
        elif roic > meroi:
            bulls.append(f"ROIC exceeds market-implied reinvestment hurdle: ROIC {roic:.1f}% vs MEROI {meroi:.1f}%.")

    try:
        if cap_years is not None:
            cap_num = int(float(cap_years))
            if cap_num >= 15:
                bears.append(f"Market prices in a long competitive advantage period: CAP {cap_num} years.")
            elif cap_num <= 7:
                bulls.append(f"Market embeds a modest competitive advantage period: CAP {cap_num} years.")
    except Exception:
        pass

    # Score fallback when detailed fields are not available.
    try:
        s = float(exp_score)
        if s >= 70 and not bulls:
            bulls.append(f"Expectation score is supportive ({s:.1f}/100).")
        elif s <= 45 and not bears:
            bears.append(f"Expectation score signals demanding assumptions ({s:.1f}/100).")
    except Exception:
        pass

    return _dedupe(bulls, 4), _dedupe(bears, 4)


# =============================================================================
# Decision / thesis layer
# =============================================================================

def split_investment_vs_trading_view(data: Dict[str, Any]) -> Dict[str, Any]:
    scores = data.get("scores", {}) or {}
    trade = data.get("trade_expectancy") or data.get("expected_return") or {}

    fundamental = _safe_float(scores.get("fundamental"), 50)
    expectation = _safe_float(scores.get("expectation"), 50)
    merton = _safe_float(scores.get("merton_credit") or scores.get("merton"), 50)
    greenfield = _safe_float(scores.get("greenfield_arr_valuation") or scores.get("neocloud"), 50)

    technical = _safe_float(scores.get("technical"), 50)
    liquidity = _safe_float(scores.get("liquidity"), 50)
    options = _safe_float(scores.get("options"), 50)
    game = _safe_float(scores.get("game_theory") or scores.get("game"), 50)

    ev = trade.get("trade_expectancy_pct")
    if ev is None:
        ev = trade.get("ev_pct")
    try:
        ev = float(ev)
    except Exception:
        ev = None

    investment_score = round(
        0.35 * fundamental
        + 0.25 * expectation
        + 0.25 * merton
        + 0.15 * greenfield,
        1,
    )

    trading_score = round(
        0.35 * technical
        + 0.25 * liquidity
        + 0.20 * options
        + 0.20 * game,
        1,
    )

    if investment_score >= 70:
        investment_view = "Bullish"
    elif investment_score >= 55:
        investment_view = "Constructive"
    elif investment_score <= 40:
        investment_view = "Bearish"
    else:
        investment_view = "Neutral"

    if trading_score >= 70 and (ev is None or ev > 0):
        trading_view = "Bullish"
    elif trading_score >= 55:
        trading_view = "Neutral / Wait for confirmation"
    elif trading_score <= 40:
        trading_view = "Bearish"
    else:
        trading_view = "Neutral"

    if investment_view in ["Bullish", "Constructive"] and "Neutral" in trading_view:
        reason = "Business quality and capital structure are supportive, but near-term trading confirmation is incomplete."
        action = "Accumulate on pullbacks or wait for a cleaner breakout/reclaim."
    elif investment_view == "Bullish" and trading_view == "Bullish":
        reason = "Business quality and near-term trading setup are aligned."
        action = "Tactical long is justified with defined stop and target."
    elif investment_view in ["Neutral", "Bearish"] and trading_view == "Bullish":
        reason = "Near-term momentum is strong, but investment quality is not fully supportive."
        action = "Treat as a tactical trade only, not a core position."
    elif investment_view == "Bearish" and trading_view in ["Bearish", "Neutral"]:
        reason = "Both investment quality and trading setup are weak."
        action = "Avoid or consider short setups only after confirmation."
    else:
        reason = "Signals are mixed across business quality and trading setup."
        action = "Keep on watchlist until alignment improves."

    return {
        "investment_score": investment_score,
        "trading_score": trading_score,
        "investment_view": investment_view,
        "trading_view": trading_view,
        "reason": reason,
        "action": action,
    }


def _why_not_long(compact_or_result: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    scores = compact_or_result.get("scores") or {}
    metas = compact_or_result.get("metas") or {}
    reads = compact_or_result.get("reads") or {}
    trade = compact_or_result.get("trade_expectancy") or compact_or_result.get("expected_return") or {}

    technical = _round(scores.get("technical"), 1)
    liquidity = _round(scores.get("liquidity"), 1)
    game = _round(scores.get("game_theory") or scores.get("game"), 1)

    if technical is not None and technical < 50:
        setup = (
            (metas.get("technical") or {}).get("setup_type")
            or compact_or_result.get("setup_type")
            or "no clean technical setup"
        )
        reasons.append(f"Technical timing is weak ({technical}/100): {setup}.")

    if liquidity is not None and liquidity < 50:
        lsum = reads.get("liquidity") or (compact_or_result.get("summary") or {}).get("liquidity") or "liquidity/volume confirmation is weak"
        reasons.append(f"Liquidity confirmation is weak ({liquidity}/100): {lsum}")

    if game is not None and game < 50:
        g = metas.get("game") or {}
        env = g.get("environment") or "no clear forced-flow edge"
        reasons.append(f"Forced-flow/game-theory read is not compelling ({game}/100): {env}.")

    exp_pct = trade.get("trade_expectancy_pct")
    if exp_pct is None:
        exp_pct = _pct(compact_or_result.get("expected_return"))
    try:
        if exp_pct is not None and float(exp_pct) < 0:
            reasons.append(f"Trade expectancy is negative ({float(exp_pct):.1f}%), so the current entry is not ideal.")
    except Exception:
        pass

    theme = metas.get("theme") or {}
    theme_score = _round(theme.get("total"), 1)
    if theme_score is not None and theme_score < 40:
        reasons.append(f"Theme participation is weak ({theme_score}/100): ticker is lagging its theme or benchmark.")

    return _dedupe(reasons, 5)


def harmonized_verdict(data: Dict[str, Any]) -> Dict[str, Any]:
    scores = data.get("scores", {}) or {}
    expected = data.get("trade_expectancy") or data.get("expected_return") or {}
    trade_plan = data.get("trade_plan", {}) or {}
    decision_layer = data.get("decision_layer") or {}

    final_score = _safe_float(data.get("final_score"), 50)
    technical = _safe_float(scores.get("technical"), 50)
    liquidity = _safe_float(scores.get("liquidity"), 50)
    options = _safe_float(scores.get("options"), 50)
    game = _safe_float(scores.get("game_theory") or scores.get("game"), 50)
    fundamental = _safe_float(scores.get("fundamental"), 50)
    expectation = _safe_float(scores.get("expectation"), 50)
    merton = _safe_float(scores.get("merton_credit") or scores.get("merton"), 50)

    ev_pct = expected.get("trade_expectancy_pct")
    if ev_pct is None:
        ev_pct = expected.get("ev_pct")
    try:
        ev_pct = float(ev_pct)
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
        decision = data.get("decision") or "Watchlist Only"

    if technical >= 60 and liquidity >= 60 and options < 35:
        setup_type = "Strong trend, weak options confirmation"
    elif technical >= 60 and liquidity >= 60:
        setup_type = "Constructive trend continuation"
    elif technical >= 60 and liquidity < 50:
        setup_type = "Trend intact, liquidity not confirming"
    elif technical < 50 and final_score >= 60:
        setup_type = "Good stock, poor current entry"
    else:
        setup_type = data.get("setup_type") or "Watchlist / no clean pattern"

    thesis_parts = [
        f"{data.get('ticker')}: {decision}. Final score {final_score:.1f}/100. Setup: {setup_type}."
    ]

    if decision_layer:
        thesis_parts.append(
            f"Investment view: {decision_layer.get('investment_view')}. "
            f"Trading view: {decision_layer.get('trading_view')}. "
            f"Reason: {decision_layer.get('reason')} "
            f"Action: {decision_layer.get('action')}"
        )

    if bull_count >= 4:
        thesis_parts.append(
            "Bull case is supported by fundamentals, expectation quality, capital structure, "
            "and/or constructive liquidity/technical backdrop."
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
            thesis_parts.append(f"Trade expectancy is supportive at {ev_pct:.1f}%.")
        elif ev_pct >= 0:
            thesis_parts.append(f"Trade expectancy is marginal at {ev_pct:.1f}%, so position size should be controlled.")
        else:
            thesis_parts.append(f"Trade expectancy is negative at {ev_pct:.1f}%, so a better entry may exist.")

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


# =============================================================================
# Main compact response
# =============================================================================

def compact_analysis(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert verbose engine output into a monetizable, end-user friendly response.

    Stable API fields preserved:
      - trade_expectancy
      - expected_return alias
      - scores
      - reads
      - snapshots
      - decision_layer
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
    game_meta = metas.get("game") or metas.get("game_theory") or {}
    liquidity_meta = metas.get("liquidity") or {}
    theme_meta = metas.get("theme") or {}
    expected_meta = metas.get("expectation") or {}
    merton_meta = metas.get("merton") or {}
    neocloud_meta = metas.get("neocloud") or metas.get("greenfield_arr") or {}

    participant_map = game_meta.get("participant_map") or {}
    dominant_participants = {
        k: {"bias": v.get("bias"), "pressure": _round(v.get("pressure"), 1)}
        for k, v in participant_map.items()
        if isinstance(v, dict)
    }

    # This is short-term trade expectancy, not long-term investment expected return.
    trade_expectancy = {
        "trade_expectancy_pct": _pct(result.get("trade_expectancy_pct")),
        "trade_expectancy_r": _round(result.get("trade_expectancy_r"), 2),
        "reward_pct": _pct(result.get("reward_pct")),
        "risk_pct": _pct(result.get("risk_pct")),
        "probability_win": _pct(result.get("probability_win")),
        "legacy_scenario_ev_pct": _pct(result.get("expected_return")),
        "read": summary.get("expected_return"),
    }

    compact_scores = {
        "fundamental": _round(scores.get("fundamental"), 1),
        "technical": _round(scores.get("technical"), 1),
        "liquidity": _round(scores.get("liquidity"), 1),
        "options": _round(scores.get("options"), 1),
        "game_theory": _round(scores.get("game") or scores.get("game_theory"), 1),
        "catalyst": _round(scores.get("catalyst"), 1),
        "expectation": _round(scores.get("expectation"), 1),
        "merton_credit": _round(scores.get("merton") or scores.get("merton_credit"), 1),
        "greenfield_arr_valuation": _round(scores.get("neocloud") or scores.get("greenfield_arr_valuation"), 1),
    }

    reads = {
        "technical": summary.get("technical"),
        "liquidity": summary.get("liquidity"),
        "options": summary.get("options") or options_meta.get("options_read"),
        "game_theory": game_meta.get("participant_read") or summary.get("game_theory"),
        "catalyst": summary.get("catalyst"),
        "expectation": expected_meta.get("expectation_read") or summary.get("expectation"),
        "merton_credit": merton_meta.get("summary") or summary.get("merton"),
        "greenfield_arr_valuation": _greenfield_arr_read(result.get("ticker"), neocloud_meta),
        "theme": theme_meta.get("summary"),
    }

    expectation_snapshot = {
        "score": compact_scores.get("expectation"),
        "read": reads.get("expectation"),
        "expectations_gap": _round(_metric(expected_meta, "expectations_gap"), 1),
        "implied_cagr": _pct(_metric(expected_meta, "implied_cagr"), 1),
        "revenue_growth": _pct(_metric(expected_meta, "revenue_growth", "rev_growth"), 1),
        "market_implied_cap": _metric(expected_meta, "market_implied_cap", "cap_years"),
        "roic": _pct(_metric(expected_meta, "roic"), 1),
        "meroi": _pct(_metric(expected_meta, "meroi"), 1),
        "signal": expected_meta.get("signal"),
    }

    compact = {
        "ticker": result.get("ticker"),
        "price": _round(result.get("price"), 2),
        "decision": result.get("decision"),
        "final_score": _round(result.get("final_score"), 1),
        "score_read": _score_bucket(result.get("final_score")),
        "setup_type": result.get("setup_type"),
        "regime": result.get("regime"),
        "theme": result.get("theme"),
        "trade_plan": {
            "entry": _round(result.get("entry"), 2),
            "stop": _round(result.get("stop"), 2),
            "target1": _round(result.get("target1"), 2),
            "target2": _round(result.get("target2"), 2),
            "risk_reward": _round(result.get("rr") or result.get("risk_reward"), 2),
            "position_size": result.get("position_size"),
            "invalidates_if": ["Breaks stop or thesis drivers deteriorate."],
        },
        "trade_expectancy": trade_expectancy,
        "expected_return": trade_expectancy,  # legacy compatibility
        "scores": compact_scores,
        "reads": reads,
        "expectation_snapshot": expectation_snapshot,
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
            "distance_to_default": _round(_metric(merton_meta, "distance_to_default"), 2),
            "pd_annual_proxy_pct": _pct(_metric(merton_meta, "pd_annual_proxy")),
            "net_debt_to_market_cap_pct": _pct(_metric(merton_meta, "net_debt_to_market_cap")),
        },
        "greenfield_arr_snapshot": {
            "score": _round(neocloud_meta.get("score"), 1),
            "signal": neocloud_meta.get("signal"),
            "subscores": neocloud_meta.get("subscores") or {},
            "ev_current_arr": _round(_metric(neocloud_meta, "ev_current_arr"), 2),
            "ev_target_arr": _round(_metric(neocloud_meta, "ev_target_arr"), 2),
            "secured_power_mw": _round(_metric(neocloud_meta, "secured_power_mw"), 0),
            "gpu_count": _round(_metric(neocloud_meta, "gpu_count"), 0),
        },
    }

    # First pass blockers before final verdict.
    blockers = _why_not_long({**compact, "metas": metas, "summary": summary})
    compact["trade_plan"]["invalidates_if"] = blockers[:3] if blockers else ["Breaks stop or thesis drivers deteriorate."]

    # Initial bull/bear points.
    bull_points: List[str] = []
    bear_points: List[str] = []

    if _safe_float(compact_scores.get("fundamental"), 0) >= 70:
        bull_points.append(f"Strong fundamentals ({compact_scores.get('fundamental')}/100).")
    if _safe_float(compact_scores.get("options"), 0) >= 65:
        bull_points.append(f"Options positioning supportive ({compact_scores.get('options')}/100).")
    if _safe_float(compact_scores.get("expectation"), 0) >= 65:
        bull_points.append(f"Expectation score supportive ({compact_scores.get('expectation')}/100).")
    if _safe_float(compact_scores.get("merton_credit"), 0) >= 70:
        bull_points.append(f"Capital structure supportive / low credit risk ({compact_scores.get('merton_credit')}/100).")
    if _safe_float(compact_scores.get("greenfield_arr_valuation"), 0) >= 70:
        bull_points.append(f"Greenfield ARR/capacity valuation supportive ({compact_scores.get('greenfield_arr_valuation')}/100).")
    if result.get("regime"):
        bull_points.append(f"Market regime: {result.get('regime')}.")

    if _safe_float(compact_scores.get("technical"), 100) < 50:
        bear_points.append(f"Technical score weak ({compact_scores.get('technical')}/100).")
    if _safe_float(compact_scores.get("liquidity"), 100) < 50:
        bear_points.append(f"Liquidity/volume score weak ({compact_scores.get('liquidity')}/100).")
    if liquidity_meta.get("cmf") is not None and _safe_float(liquidity_meta.get("cmf"), 0) < -0.05:
        bear_points.append(f"Negative CMF ({_round(liquidity_meta.get('cmf'), 2)}), suggesting distribution.")
    if theme_meta.get("total") is not None and _safe_float(theme_meta.get("total"), 50) < 40:
        bear_points.append("Ticker is lagging its theme/basket.")
    if _safe_float(compact_scores.get("merton_credit"), 100) < 50:
        bear_points.append(f"Capital-structure risk elevated ({compact_scores.get('merton_credit')}/100).")
    if _safe_float(compact_scores.get("greenfield_arr_valuation"), 100) < 50:
        bear_points.append(f"Greenfield ARR/capacity valuation risk elevated ({compact_scores.get('greenfield_arr_valuation')}/100).")

    # Add explicit expectation-investing bull/bear factors.
    exp_bulls, exp_bears = expectation_bull_bear_flags(
        {**compact, "metas": {"expectation": expected_meta}}
    )
    bull_points.extend(exp_bulls)
    bear_points.extend(exp_bears)

    compact["main_bull_case"] = _dedupe(bull_points, 7) or [summary.get("fundamental") or "No clear bull case detected."]
    compact["main_bear_case"] = _dedupe(bear_points, 7) or ["No major bearish factor detected."]
    compact["why_not_long_now"] = blockers

    # Decision layer and harmonized verdict last.
    decision_layer = split_investment_vs_trading_view(compact)
    compact["decision_layer"] = decision_layer

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
