from __future__ import annotations

from typing import Any, Dict, List


def _num(x: Any, default: float = 50.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def _bucket(score: float) -> str:
    if score >= 80:
        return "Exceptional"
    if score >= 70:
        return "Strong"
    if score >= 60:
        return "Constructive"
    if score >= 45:
        return "Mixed"
    return "Weak"


def _append_if(items: List[str], condition: bool, text: str) -> None:
    if condition:
        items.append(text)


def build_investment_narrative(compact: Dict[str, Any]) -> Dict[str, Any]:
    scores = compact.get("scores") or {}
    reads = compact.get("reads") or {}

    decision = compact.get("decision", "Watchlist")
    setup = compact.get("setup_type", "n/a")
    ticker = compact.get("ticker", "Ticker")

    fundamental = _num(scores.get("fundamental"))
    technical = _num(scores.get("technical"))
    liquidity = _num(scores.get("liquidity"))
    options = _num(scores.get("options"))
    game = _num(scores.get("game_theory"))
    expectation = _num(scores.get("expectation"))
    merton = _num(scores.get("merton_credit"))
    greenfield = _num(scores.get("greenfield_arr_valuation"))
    optionality = _num(scores.get("optionality"))

    trade = compact.get("trade_expectancy") or {}
    trade_exp = _num(trade.get("trade_expectancy_pct"), 0)
    win_prob = _num(trade.get("probability_win"), 50)

    expectation_snapshot = compact.get("expectation_snapshot") or {}
    optionality_snapshot = compact.get("optionality_snapshot") or {}
    cap_snapshot = compact.get("capital_structure_snapshot") or {}
    options_snapshot = compact.get("options_snapshot") or {}

    investment_score = round(
        0.30 * fundamental
        + 0.25 * expectation
        + 0.20 * merton
        + 0.15 * greenfield
        + 0.10 * optionality,
        1,
    )

    trading_score = round(
        0.35 * technical
        + 0.25 * liquidity
        + 0.20 * options
        + 0.20 * game,
        1,
    )

    business_points: List[str] = []
    _append_if(business_points, fundamental >= 75, "Business quality is strong.")
    _append_if(business_points, fundamental < 55, "Fundamental quality is not yet compelling.")
    _append_if(business_points, merton >= 70, "Balance sheet / credit risk is manageable.")
    _append_if(business_points, merton < 50, "Capital structure risk is elevated.")
    _append_if(business_points, greenfield >= 65, "Greenfield ARR / capacity exposure is supportive.")
    _append_if(business_points, greenfield < 50, "Greenfield ARR / capacity evidence is weak or not directly applicable.")

    if not business_points:
        business_points.append("Business quality is mixed, with no dominant positive or negative signal.")

    expectation_points: List[str] = []
    exp_read = expectation_snapshot.get("read") or reads.get("expectation")

    if exp_read:
        expectation_points.append(exp_read.replace("Expectation investing: ", ""))

    implied_cagr = expectation_snapshot.get("implied_cagr")
    revenue_growth = expectation_snapshot.get("revenue_growth")
    roic = expectation_snapshot.get("roic")
    meroi = expectation_snapshot.get("meroi")
    cap_years = expectation_snapshot.get("market_implied_cap")

    if implied_cagr is not None and revenue_growth is not None:
        try:
            if float(revenue_growth) > float(implied_cagr):
                expectation_points.append("Current growth appears ahead of the market-implied hurdle.")
            elif float(implied_cagr) > float(revenue_growth) * 1.5:
                expectation_points.append("Market-implied growth hurdle looks demanding.")
        except Exception:
            pass

    if roic is not None and meroi is not None:
        try:
            if float(roic) > float(meroi):
                expectation_points.append("ROIC exceeds the market-implied reinvestment hurdle.")
            elif float(roic) < float(meroi) * 0.75:
                expectation_points.append("ROIC is below the market-implied reinvestment hurdle.")
        except Exception:
            pass

    if cap_years is not None:
        try:
            if float(cap_years) >= 15:
                expectation_points.append("Market is pricing a long competitive advantage period.")
            elif float(cap_years) <= 7:
                expectation_points.append("Market is not pricing an excessive competitive advantage period.")
        except Exception:
            pass

    opt_signal = optionality_snapshot.get("signal")
    if opt_signal and "unavailable" not in str(opt_signal).lower():
        expectation_points.append(f"Future value premium: {opt_signal}.")

    if not expectation_points:
        expectation_points.append("Market expectations appear broadly balanced.")

    trading_points: List[str] = []
    _append_if(trading_points, technical >= 70, "Trend quality is strong.")
    _append_if(trading_points, technical < 50, "Technical timing is weak.")
    _append_if(trading_points, liquidity >= 65, "Liquidity / accumulation evidence is constructive.")
    _append_if(trading_points, liquidity < 50, "Liquidity confirmation is weak.")
    _append_if(trading_points, options >= 60, "Options positioning is supportive.")
    _append_if(trading_points, options < 40, "Options market is defensive or not confirming the equity setup.")
    _append_if(trading_points, game >= 60, "Participant / forced-flow setup is supportive.")
    _append_if(trading_points, game < 50, "Forced-flow confirmation is incomplete.")

    if not trading_points:
        trading_points.append("Trading conditions are mixed.")

    risks: List[str] = []
    _append_if(risks, options < 40, "Options tape remains defensive.")
    _append_if(risks, game < 50, "Game-theory / forced-flow confirmation is weak.")
    _append_if(risks, liquidity < 50, "Liquidity confirmation is weak.")
    _append_if(risks, technical < 50, "Entry timing is not clean.")
    _append_if(risks, merton < 50, "Capital structure risk is elevated.")
    _append_if(risks, expectation < 50, "Market expectations look demanding.")
    _append_if(risks, trade_exp < 0, "Trade expectancy is negative.")

    if not risks:
        risks.append("No major risk flag, but position sizing and stop discipline remain important.")

    opportunity: List[str] = []
    _append_if(opportunity, investment_score >= 70, "Investment quality is strong.")
    _append_if(opportunity, trading_score >= 65, "Trading setup is actionable.")
    _append_if(opportunity, trade_exp > 3, f"Trade expectancy is positive at approximately {trade_exp:.1f}%.")
    _append_if(opportunity, win_prob >= 55, f"Win probability is above neutral at approximately {win_prob:.1f}%.")
    _append_if(opportunity, expectation >= 65, "Expectation investing layer is supportive.")

    if not opportunity:
        opportunity.append("Opportunity is not yet compelling enough for aggressive action.")

    if investment_score >= 70 and trading_score >= 65:
        recommendation = "Business quality and trading setup are aligned. Tactical long is justified with defined risk."
        action = "Buy or accumulate with stop discipline."
    elif investment_score >= 70 and trading_score < 65:
        recommendation = "Business quality is attractive, but trading confirmation is incomplete."
        action = "Accumulate on pullbacks or wait for a cleaner breakout/reclaim."
    elif investment_score >= 55 and trading_score >= 65:
        recommendation = "The trading setup is constructive, but investment quality is not yet high conviction."
        action = "Treat as tactical trade only."
    elif investment_score >= 55:
        recommendation = "The setup is constructive but not yet high conviction."
        action = "Keep on watchlist; prefer pullbacks or confirmation."
    else:
        recommendation = "Signals are mixed or weak."
        action = "Avoid aggressive long exposure."

    executive_summary = (
        f"{ticker}: {decision}. Setup: {setup}. "
        f"Investment quality is {_bucket(investment_score).lower()} "
        f"and trading quality is {_bucket(trading_score).lower()}. "
        f"{recommendation}"
    )

    return {
        "investment_score": investment_score,
        "trading_score": trading_score,
        "business_quality": {
            "rating": _bucket(investment_score),
            "points": business_points[:5],
        },
        "market_expectations": {
            "rating": _bucket(expectation),
            "points": expectation_points[:5],
        },
        "trading_conditions": {
            "rating": _bucket(trading_score),
            "points": trading_points[:5],
        },
        "primary_risks": risks[:5],
        "opportunity": opportunity[:5],
        "recommendation": {
            "summary": recommendation,
            "action": action,
        },
        "executive_summary": executive_summary,
    }