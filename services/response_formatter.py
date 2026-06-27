from __future__ import annotations
from engines.narrative_engine import build_investment_narrative
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
        reasons.append(f"Trade expectancy model is negative ({exp_pct}%), so the reward does not justify immediate long exposure.")

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
        reasons.append(f"Greenfield ARR/capacity valuation quality is weak ({neocloud_score}/100): {neocloud.get('signal', 'valuation risk')}.")

    if not reasons:
        reasons.append("No major blocker detected; decision is mainly constrained by final score/threshold discipline.")
    return reasons

def harmonized_verdict(data: dict) -> dict:
    scores = data.get("scores", {}) or {}
    reads = data.get("reads", {}) or {}
    expected = data.get("trade_expectancy") or data.get("expected_return") or {}
    trade_plan = data.get("trade_plan", {}) or {}
    decision_layer = data.get("decision_layer") or {}
    
    final_score = float(data.get("final_score") or 50)
    technical = float(scores.get("technical") or 50)
    liquidity = float(scores.get("liquidity") or 50)
    options = float(scores.get("options") or 50)
    game = float(scores.get("game_theory") or scores.get("game") or 50)
    fundamental = float(scores.get("fundamental") or 50)
    expectation = float(scores.get("expectation") or 50)
    merton = float(scores.get("merton_credit") or scores.get("merton") or 50)
    optionality = float(scores.get("optionality") or 50)

    ev = (
        expected.get("trade_expectancy_pct")
        or expected.get("legacy_scenario_ev_pct")
        or expected.get("ev_pct")
    )
    try:
        ev = float(ev)
        # trade_expectancy_pct is already percent in compact output.
        ev_pct = ev * 100 if abs(ev) <= 1.5 else ev
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
    if optionality >= 70:
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
    if optionality < 45:
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
    if decision_layer:
        thesis_parts.append(
            f"Investment view: {decision_layer.get('investment_view')}. "
            f"Trading view: {decision_layer.get('trading_view')}. "
            f"Reason: {decision_layer.get('reason')} "
            f"Action: {decision_layer.get('action')}"
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
            thesis_parts.append(f"Expected-return model is supportive with EV around {ev_pct:.1f}%.")
        elif ev_pct >= 0:
            thesis_parts.append(f"Expected-return model is only mildly positive at {ev_pct:.1f}%, so position size should be controlled.")
        else:
            thesis_parts.append(f"Expected-return model is slightly negative at {ev_pct:.1f}%, so this is a watchlist/pullback setup rather than a full long signal.")
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
#. adding expectation investing angel
def expectation_bull_bear_flags(data: dict) -> tuple[list[str], list[str]]:
    scores = data.get("scores") or {}
    reads = data.get("reads") or {}
    metas = data.get("metas") or {}

    exp_score = scores.get("expectation")
    exp_read = reads.get("expectation") or ""

    exp_meta = (
        metas.get("expectation")
        or data.get("expectation_meta")
        or data.get("expectation_snapshot")
        or {}
    )

    bulls, bears = [], []

    implied_cagr = exp_meta.get("implied_cagr")
    revenue_growth = exp_meta.get("revenue_growth")
    cap_years = exp_meta.get("market_implied_cap")
    roic = exp_meta.get("roic")
    meroi = exp_meta.get("meroi")

    # Fallback from read string when metadata is not yet surfaced
    if "Expectations demanding" in exp_read:
        bears.append(f"Expectation hurdle is demanding: {exp_read.replace('Expectation investing: ', '')}")
    elif "Expectations beatable" in exp_read or "beatable" in exp_read.lower():
        bulls.append(f"Expectations look beatable: {exp_read.replace('Expectation investing: ', '')}")

    if implied_cagr is not None and revenue_growth is not None:
        try:
            if implied_cagr > revenue_growth * 1.5:
                bears.append(
                    f"Market-implied growth looks demanding: implied CAGR {implied_cagr:.1f}% vs current revenue growth {revenue_growth:.1f}%."
                )
            elif revenue_growth > implied_cagr:
                bulls.append(
                    f"Current growth exceeds market hurdle: revenue growth {revenue_growth:.1f}% vs implied CAGR {implied_cagr:.1f}%."
                )
        except Exception:
            pass

    if roic is not None and meroi is not None:
        try:
            if roic < meroi * 0.75:
                bears.append(
                    f"Value-creation hurdle is high: ROIC {roic:.1f}% vs MEROI {meroi:.1f}%."
                )
            elif roic > meroi:
                bulls.append(
                    f"ROIC exceeds market-implied reinvestment hurdle: ROIC {roic:.1f}% vs MEROI {meroi:.1f}%."
                )
        except Exception:
            pass

    if cap_years is not None:
        try:
            if cap_years >= 15:
                bears.append(
                    f"Market prices in a long competitive advantage period: CAP {cap_years} years."
                )
            elif cap_years <= 7:
                bulls.append(
                    f"Market embeds a modest competitive advantage period: CAP {cap_years} years."
                )
        except Exception:
            pass

    # Score fallback
    try:
        if exp_score is not None and float(exp_score) >= 70 and not bulls:
            bulls.append("Expectation score is supportive.")
        elif exp_score is not None and float(exp_score) <= 45 and not bears:
            bears.append("Expectation score signals demanding assumptions.")
    except Exception:
        pass

    return bulls[:3], bears[:3]

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
        bull_points.append(f"Greenfield ARR/capacity valuation supportive ({_round(scores.get('neocloud'), 1)}/100).")
    if scores.get("optionality") and float(scores.get("optionality")) >= 70:
        bull_points.append(f"Embedded optionality appears attractive ({_round(scores.get('optionality'), 1)}/100).")
    if result.get("regime"):
        bull_points.append(f"Market regime: {result.get('regime')}.")

    # ==========================================================
# Optionality Bull Factors (Merton)
# ==========================================================

    for p in optionality_meta.get("bull_points", []):
        if p not in bull_points:
            bull_points.append(p)
    
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
        bear_points.append(f"Greenfield ARR/capacity valuation risk elevated ({_round(scores.get('neocloud'), 1)}/100).")
    if scores.get("optionality") and float(scores.get("optionality")) < 50:
        bear_points.append(f"Market may already be pricing significant future optionality ({_round(scores.get('optionality'), 1)}/100).")

    # ==========================================================
# Optionality Bear Factors
# ==========================================================

    for p in optionality_meta.get("bear_points", []):
        if p not in bear_points:
            bear_points.append(p)
    
    trade_plan = {
        "entry": _round(result.get("entry"), 2),
        "stop": _round(result.get("stop"), 2),
        "target1": _round(result.get("target1"), 2),
        "target2": _round(result.get("target2"), 2),
        "risk_reward": _round(result.get("rr") or result.get("risk_reward"), 2),
        "position_size": result.get("position_size"),
        "invalidates_if": blockers[:3] if blockers else ["Breaks stop or thesis drivers deteriorate."],
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

    # Backward-compatible alias for older frontend/API clients.
    expected_return = trade_expectancy
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
        "trade_expectancy": trade_expectancy,
        "expected_return": trade_expectancy,#legacy compatablity        
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
            "greenfield_arr_valuation": _greenfield_arr_read(result.get("ticker"), neocloud_meta),
            "theme": theme_meta.get("summary"),
            "optionality": optionality_meta.get("summary"),
        },
        
        "expectation_snapshot": {
            "score": _round(scores.get("expectation"), 1),
            "read": expected_meta.get("expectation_read") or summary.get("expectation"),
            "expectations_gap": _round((metas.get("expectation") or {}).get("expectations_gap"), 1),
            "implied_cagr": _round((metas.get("expectation") or {}).get("implied_cagr"), 1),
            "revenue_growth": _round((metas.get("expectation") or {}).get("revenue_growth"), 1),
            "market_implied_cap": (metas.get("expectation") or {}).get("market_implied_cap"),
            "roic": _round((metas.get("expectation") or {}).get("roic"), 1),
            "meroi": _round((metas.get("expectation") or {}).get("meroi"), 1),
            "signal": (metas.get("expectation") or {}).get("signal"),
            
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
        "optionality_snapshot": {
            "score": _round(optionality_meta.get("score"), 1),
            "signal": optionality_meta.get("signal"),
            "summary": optionality_meta.get("summary"),
            "embedded_optionality_pct": _pct((optionality_meta.get("metrics") or {}).get("embedded_optionality_pct")),
            "existing_value_pct": _pct((optionality_meta.get("metrics") or {}).get("existing_value_pct")),
            "enterprise_value": _round((optionality_meta.get("metrics") or {}).get("enterprise_value"), 0),
            "existing_business_value": _round((optionality_meta.get("metrics") or {}).get("existing_business_value"), 0),
            "embedded_option_value": _round((optionality_meta.get("metrics") or {}).get("embedded_option_value"), 0),
            "bull_points": optionality_meta.get("bull_points") or [],
            "bear_points": optionality_meta.get("bear_points") or [],
        },
        "final_thesis": result.get("thesis"),
    }
    
    decision_layer = split_investment_vs_trading_view(compact)

    verdict = harmonized_verdict(compact)

    compact["decision"] = verdict["decision"]
    compact["setup_type"] = verdict["setup_type"]
    compact["final_thesis"] = verdict["final_thesis"]  
    compact["decision_layer"] = decision_layer 
    compact["narrative"] = build_investment_narrative(compact)
    compact["final_thesis"] = compact["narrative"]["executive_summary"]
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

def split_investment_vs_trading_view(data: dict) -> dict:
    scores = data.get("scores", {}) or {}
    trade = data.get("trade_expectancy") or data.get("expected_return") or {}

    fundamental = float(scores.get("fundamental") or 50)
    expectation = float(scores.get("expectation") or 50)
    merton = float(scores.get("merton_credit") or 50)
    greenfield = float(scores.get("greenfield_arr_valuation") or 50)
    optionality = float(scores.get("optionality") or 50)

    technical = float(scores.get("technical") or 50)
    liquidity = float(scores.get("liquidity") or 50)
    options = float(scores.get("options") or 50)
    game = float(scores.get("game_theory") or 50)

    ev = trade.get("ev_pct")
    try:
        ev = float(ev)
    except Exception:
        ev = None

    investment_score = round(
        0.30 * fundamental
        + 0.25 * expectation
        + 0.20 * merton
        + 0.10 * greenfield
        + 0.15 * optionality,
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