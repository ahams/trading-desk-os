"""
Enhanced Expectation Investing Engine
-------------------------------------
Production-safe version of the original expectation investing framework.

Public API kept compatible:
    expectation_score(info, df=None, fund_meta=None, catalyst_meta=None) -> (score, metadata)

What this adds versus the lightweight proxy:
    1. Reverse DCF-lite: market-implied revenue CAGR.
    2. Competitive Advantage Period (CAP): years of value creation priced in.
    3. MEROI proxy: market-expected return on incremental investment.
    4. Economic quality gate: ROIC/WACC spread, margins, FCF yield, growth.
    5. Partial-expectation bridge: historical Sharpe + volatility -> real-world alpha.
    6. Expectations gap synthesis: are implied hurdles beatable?

Design principle:
    This does NOT pretend to be precise intrinsic valuation. It estimates the
    hurdle embedded in market price and asks whether business evidence can beat it.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

try:
    from utils import clamp
except Exception:  # local testing fallback
    def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
        try:
            return max(lo, min(hi, float(x)))
        except Exception:
            return 50.0


# -----------------------------------------------------------------------------
# Basic helpers
# -----------------------------------------------------------------------------

def _f(x: Any, default: float = np.nan) -> float:
    try:
        if x is None or pd.isna(x):
            return default
        return float(x)
    except Exception:
        return default


def _pct(x: Any, default: float = 0.0) -> float:
    """Vendor values may be 0.18 or 18. Return decimal form."""
    v = _f(x, default)
    if np.isnan(v):
        return default
    return v / 100.0 if abs(v) > 1.5 else v


def _safe_div(a: float, b: float, default: float = np.nan) -> float:
    try:
        if b is None or b == 0 or np.isnan(b):
            return default
        return a / b
    except Exception:
        return default


def _latest_price(df: Optional[pd.DataFrame], info: Dict[str, Any]) -> float:
    if df is not None and not df.empty and "Close" in df.columns:
        return _f(df["Close"].iloc[-1])
    return _f(info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose"))


def _market_cap(info: Dict[str, Any], price: float) -> float:
    mc = _f(info.get("marketCap"))
    if not np.isnan(mc) and mc > 0:
        return mc
    shares = _f(info.get("sharesOutstanding"))
    if not np.isnan(shares) and shares > 0 and price > 0:
        return price * shares
    return np.nan


def _ev(info: Dict[str, Any], market_cap: float) -> float:
    ev = _f(info.get("enterpriseValue"))
    if not np.isnan(ev) and ev > 0:
        return ev
    debt = _f(info.get("totalDebt"), 0.0)
    cash = _f(info.get("totalCash"), 0.0)
    return market_cap + debt - cash if not np.isnan(market_cap) else np.nan


def _annualized_return_vol(df: Optional[pd.DataFrame]) -> Tuple[float, float, float]:
    """Return (ann_return, ann_vol, sharpe_excess)."""
    if df is None or df.empty or "Close" not in df.columns or len(df) < 60:
        return np.nan, np.nan, np.nan

    close = pd.to_numeric(df["Close"], errors="coerce").dropna()
    rets = close.pct_change().dropna()
    if len(rets) < 50:
        return np.nan, np.nan, np.nan

    ann_ret = float(rets.mean() * 252)
    ann_vol = float(rets.std() * np.sqrt(252))
    sharpe = (ann_ret - 0.04) / ann_vol if ann_vol > 0 else np.nan
    return ann_ret, ann_vol, sharpe


# -----------------------------------------------------------------------------
# Fundamental normalization
# -----------------------------------------------------------------------------

def _normalized_inputs(info: Dict[str, Any], df: Optional[pd.DataFrame]) -> Dict[str, float | str]:
    price = _latest_price(df, info)
    mc = _market_cap(info, price)
    ev = _ev(info, mc)

    revenue = _f(info.get("totalRevenue"))
    gross_margin = _pct(info.get("grossMargins"), np.nan)
    op_margin = _pct(info.get("operatingMargins"), np.nan)
    net_margin = _pct(info.get("profitMargins"), np.nan)
    revenue_growth = _pct(info.get("revenueGrowth"), 0.0)
    eps_growth = _pct(info.get("earningsGrowth"), 0.0)
    fcf = _f(info.get("freeCashflow"))
    debt = _f(info.get("totalDebt"), 0.0)
    cash = _f(info.get("totalCash"), 0.0)
    beta = _f(info.get("beta"), 1.0)
    beta = max(beta, 0.4) if not np.isnan(beta) else 1.0

    # Invested capital proxy: book equity + debt - cash. Fallback: EV-based capital proxy.
    book_value = _f(info.get("bookValue"))
    shares = _f(info.get("sharesOutstanding"))
    book_equity = book_value * shares if not np.isnan(book_value) and not np.isnan(shares) else np.nan
    invested_capital = book_equity + debt - cash if not np.isnan(book_equity) else np.nan
    if np.isnan(invested_capital) or invested_capital <= 0:
        invested_capital = ev * 0.45 if not np.isnan(ev) and ev > 0 else np.nan

    # NOPAT proxy
    margin_for_nopat = op_margin if not np.isnan(op_margin) else (net_margin if not np.isnan(net_margin) else 0.12)
    nopat = revenue * margin_for_nopat * (1 - 0.21) if not np.isnan(revenue) and revenue > 0 else np.nan
    roic = _safe_div(nopat, invested_capital)

    return {
        "price": price,
        "market_cap": mc,
        "enterprise_value": ev,
        "revenue": revenue,
        "gross_margin": gross_margin,
        "operating_margin": op_margin,
        "net_margin": net_margin,
        "revenue_growth": revenue_growth,
        "eps_growth": eps_growth,
        "free_cash_flow": fcf,
        "fcf_yield": _safe_div(fcf, mc),
        "debt": debt,
        "cash": cash,
        "net_debt": debt - cash,
        "beta": beta,
        "book_equity": book_equity,
        "invested_capital": invested_capital,
        "nopat": nopat,
        "roic": roic,
        "pe": _f(info.get("forwardPE") or info.get("trailingPE")),
        "ps": _f(info.get("priceToSalesTrailing12Months")),
        "ev_ebitda": _f(info.get("enterpriseToEbitda")),
        "roe": _pct(info.get("returnOnEquity"), np.nan),
        "sector": info.get("sector") or "Unknown",
    }


# -----------------------------------------------------------------------------
# Reverse DCF and CAP/MEROI
# -----------------------------------------------------------------------------

def _wacc(beta: float, rfr: float = 0.04, erp: float = 0.055) -> float:
    beta = max(_f(beta, 1.0), 0.4)
    return float(np.clip(rfr + beta * erp, 0.055, 0.16))


def _dcf_value(
    revenue: float,
    op_margin: float,
    net_debt: float,
    cagr: float,
    wacc: float,
    years: int = 5,
    terminal_growth: float = 0.03,
    reinvestment_rate: float = 0.30,
) -> float:
    if revenue <= 0 or wacc <= terminal_growth:
        return np.nan

    margin = op_margin if not np.isnan(op_margin) else 0.15
    rev = revenue
    pv = 0.0

    for yr in range(1, years + 1):
        prev_rev = rev
        rev = rev * (1 + cagr)
        nopat = rev * margin * (1 - 0.21)
        investment = max((rev - prev_rev) * reinvestment_rate, 0.0)
        fcf = nopat - investment
        pv += fcf / ((1 + wacc) ** yr)

    terminal_nopat = rev * (1 + terminal_growth) * margin * (1 - 0.21)
    terminal_value = terminal_nopat / max(wacc - terminal_growth, 0.01)
    firm_value = pv + terminal_value / ((1 + wacc) ** years)
    equity_value = firm_value - net_debt
    return equity_value


def _solve_implied_cagr(inputs: Dict[str, Any], years: int = 5) -> Dict[str, Any]:
    price = _f(inputs.get("price"))
    mc = _f(inputs.get("market_cap"))
    revenue = _f(inputs.get("revenue"))
    op_margin = _f(inputs.get("operating_margin"), 0.15)
    net_debt = _f(inputs.get("net_debt"), 0.0)
    w = _wacc(_f(inputs.get("beta"), 1.0))

    if np.isnan(mc) or mc <= 0 or np.isnan(revenue) or revenue <= 0:
        return {"implied_cagr": np.nan, "wacc": w, "dcf_gap_pct": np.nan, "status": "insufficient_data"}

    lo, hi = -0.30, 0.80
    for _ in range(80):
        mid = (lo + hi) / 2
        val = _dcf_value(revenue, op_margin, net_debt, mid, w, years=years)
        if np.isnan(val):
            break
        if val < mc:
            lo = mid
        else:
            hi = mid

    implied = (lo + hi) / 2
    model_value = _dcf_value(revenue, op_margin, net_debt, implied, w, years=years)
    gap_pct = (model_value / mc - 1) if mc > 0 and not np.isnan(model_value) else np.nan

    return {
        "implied_cagr": implied,
        "wacc": w,
        "dcf_gap_pct": gap_pct,
        "forecast_years": years,
        "status": "ok",
    }


def _cap_value(
    revenue: float,
    op_margin: float,
    net_debt: float,
    cagr: float,
    wacc: float,
    cap_years: int,
    terminal_growth: float = 0.03,
    reinvestment_rate: float = 0.30,
) -> float:
    """DCF where explicit excess-return period lasts cap_years."""
    if revenue <= 0:
        return np.nan
    margin = op_margin if not np.isnan(op_margin) else 0.15
    rev = revenue
    pv = 0.0

    for yr in range(1, cap_years + 1):
        prev_rev = rev
        rev *= (1 + cagr)
        nopat = rev * margin * (1 - 0.21)
        investment = max((rev - prev_rev) * reinvestment_rate, 0.0)
        fcf = nopat - investment
        pv += fcf / ((1 + wacc) ** yr)

    terminal_nopat = rev * (1 + terminal_growth) * margin * (1 - 0.21)
    # No-value-creation terminal proxy: NOPAT capitalized at WACC.
    terminal_value = terminal_nopat / max(wacc, 0.055)
    firm_value = pv + terminal_value / ((1 + wacc) ** cap_years)
    return firm_value - net_debt


def _market_implied_cap(inputs: Dict[str, Any], consensus_cagr: float, wacc: float) -> Dict[str, Any]:
    mc = _f(inputs.get("market_cap"))
    revenue = _f(inputs.get("revenue"))
    op_margin = _f(inputs.get("operating_margin"), 0.15)
    net_debt = _f(inputs.get("net_debt"), 0.0)
    sector = str(inputs.get("sector") or "Unknown")

    if np.isnan(mc) or mc <= 0 or np.isnan(revenue) or revenue <= 0 or np.isnan(consensus_cagr):
        return {"market_implied_cap": np.nan, "cap_gap": np.nan, "cap_read": "CAP unavailable"}

    best_cap, best_gap = 5, float("inf")
    for cap in range(1, 31):
        val = _cap_value(revenue, op_margin, net_debt, consensus_cagr, wacc, cap)
        if np.isnan(val):
            continue
        gap = abs(val - mc) / max(mc, 1.0)
        if gap < best_gap:
            best_cap, best_gap = cap, gap

    benchmarks = {
        "Technology": (12, 20),
        "Communication Services": (10, 18),
        "Consumer Cyclical": (7, 12),
        "Healthcare": (10, 15),
        "Industrials": (7, 12),
        "Energy": (5, 10),
        "Utilities": (8, 12),
        "Financial Services": (8, 12),
    }
    bench = benchmarks.get(sector)

    if best_cap <= 3:
        cap_read = f"Market prices a short value-creation period ({best_cap} years)."
    elif best_cap <= 7:
        cap_read = f"Market prices a moderate value-creation period ({best_cap} years)."
    elif best_cap <= 15:
        cap_read = f"Market prices a long value-creation period ({best_cap} years)."
    else:
        cap_read = f"Market prices a very long value-creation period ({best_cap} years)."

    if bench:
        lo, hi = bench
        if best_cap < lo:
            cap_read += f" Below {sector} benchmark ({lo}-{hi} years): cautious expectations."
        elif best_cap > hi:
            cap_read += f" Above {sector} benchmark ({lo}-{hi} years): demanding expectations."
        else:
            cap_read += f" Within {sector} benchmark ({lo}-{hi} years): reasonable expectations."

    return {
        "market_implied_cap": best_cap,
        "cap_gap": best_gap,
        "sector_benchmark": bench,
        "cap_read": cap_read,
    }


def _meroi_proxy(inputs: Dict[str, Any], implied_cagr: float, cap_years: float, wacc: float) -> Dict[str, Any]:
    revenue = _f(inputs.get("revenue"))
    op_margin = _f(inputs.get("operating_margin"), 0.15)
    roic = _f(inputs.get("roic"))
    if np.isnan(revenue) or revenue <= 0 or np.isnan(implied_cagr) or np.isnan(cap_years):
        return {"meroi": np.nan, "meroi_read": "MEROI unavailable"}

    # Practical proxy: the return hurdle on incremental investment rises with
    # implied growth and CAP length. This is not full IRR path solving, but it is
    # stable enough for a production scanner.
    growth_hurdle = max(implied_cagr, 0.0)
    cap_premium = min(max((cap_years - 5) * 0.006, 0.0), 0.08)
    meroi = wacc + 0.45 * growth_hurdle + cap_premium

    if not np.isnan(roic):
        spread = roic - meroi
        if spread > 0.10:
            read = f"Current ROIC appears well above market-required MEROI ({roic:.1%} vs {meroi:.1%})."
        elif spread > 0.03:
            read = f"Current ROIC is above market-required MEROI ({roic:.1%} vs {meroi:.1%})."
        elif spread > -0.03:
            read = f"Current ROIC is close to market-required MEROI ({roic:.1%} vs {meroi:.1%})."
        else:
            read = f"Current ROIC is below market-required MEROI ({roic:.1%} vs {meroi:.1%})."
    else:
        read = f"Market-required MEROI proxy is {meroi:.1%}; current ROIC unavailable."

    return {"meroi": meroi, "meroi_read": read}


# -----------------------------------------------------------------------------
# Quality, partial expectation, and synthesis
# -----------------------------------------------------------------------------

def _quality_screen(inputs: Dict[str, Any], fund_meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    roic = _f(inputs.get("roic"))
    w = _wacc(_f(inputs.get("beta"), 1.0))
    gross_margin = _f(inputs.get("gross_margin"))
    op_margin = _f(inputs.get("operating_margin"))
    revenue_growth = _f(inputs.get("revenue_growth"), 0.0)
    fcf_yield = _f(inputs.get("fcf_yield"))
    roe = _f(inputs.get("roe"))

    score = 50.0
    reasons = []

    if not np.isnan(roic):
        spread = roic - w
        if spread > 0.10:
            score += 22; reasons.append(f"ROIC materially exceeds WACC ({roic:.1%} vs {w:.1%})")
        elif spread > 0.03:
            score += 12; reasons.append(f"ROIC exceeds WACC ({roic:.1%} vs {w:.1%})")
        elif spread < -0.03:
            score -= 15; reasons.append(f"ROIC below WACC ({roic:.1%} vs {w:.1%})")

    if not np.isnan(op_margin):
        if op_margin > 0.25:
            score += 12; reasons.append(f"High operating margin ({op_margin:.1%})")
        elif op_margin > 0.12:
            score += 6; reasons.append(f"Healthy operating margin ({op_margin:.1%})")
        elif op_margin < 0:
            score -= 12; reasons.append("Negative operating margin")

    if not np.isnan(gross_margin) and gross_margin > 0.55:
        score += 6; reasons.append(f"Strong gross margin ({gross_margin:.1%})")

    if revenue_growth > 0.20:
        score += 10; reasons.append(f"High revenue growth ({revenue_growth:.1%})")
    elif revenue_growth > 0.08:
        score += 5; reasons.append(f"Positive revenue growth ({revenue_growth:.1%})")
    elif revenue_growth < 0:
        score -= 8; reasons.append(f"Revenue contraction ({revenue_growth:.1%})")

    if not np.isnan(fcf_yield):
        if fcf_yield > 0.05:
            score += 10; reasons.append(f"Attractive FCF yield ({fcf_yield:.1%})")
        elif fcf_yield > 0.02:
            score += 5; reasons.append(f"Positive FCF yield ({fcf_yield:.1%})")
        elif fcf_yield < -0.03:
            score -= 12; reasons.append(f"Cash burn vs market cap ({fcf_yield:.1%})")

    external_quality = _f((fund_meta or {}).get("quality"), np.nan)
    if not np.isnan(external_quality):
        score = 0.70 * score + 0.30 * external_quality
        reasons.append(f"Blended with fundamental quality engine ({external_quality:.1f}/100)")

    return {"quality_score": clamp(score), "quality_reasons": reasons}


def _partial_expectation_bridge(df: Optional[pd.DataFrame]) -> Dict[str, Any]:
    ann_ret, ann_vol, sharpe = _annualized_return_vol(df)
    rfr = 0.04
    if np.isnan(ann_vol):
        return {
            "historical_return": np.nan,
            "historical_volatility": np.nan,
            "historical_sharpe": np.nan,
            "real_world_alpha": np.nan,
            "partial_expectation_read": "Partial expectation bridge unavailable: insufficient price history.",
        }

    # Clip Sharpe to avoid one-year noise dominating; if negative but recent trend recovers, use conservative floor.
    sharpe_used = sharpe
    if np.isnan(sharpe_used):
        sharpe_used = 0.35
    sharpe_used = float(np.clip(sharpe_used, 0.05, 2.5))
    alpha = rfr + sharpe_used * ann_vol

    return {
        "historical_return": ann_ret,
        "historical_volatility": ann_vol,
        "historical_sharpe": sharpe,
        "sharpe_used": sharpe_used,
        "real_world_alpha": alpha,
        "partial_expectation_read": (
            f"Partial expectation bridge: vol {ann_vol:.1%}, Sharpe used {sharpe_used:.2f}, "
            f"real-world alpha hurdle {alpha:.1%}."
        ),
    }


def _legacy_multiple_proxy(inputs: Dict[str, Any]) -> Dict[str, float]:
    pe = _f(inputs.get("pe"))
    ps = _f(inputs.get("ps"))
    ev_ebitda = _f(inputs.get("ev_ebitda"))
    rev_g = _f(inputs.get("revenue_growth"), 0.0)
    eps_g = _f(inputs.get("eps_growth"), 0.0)
    gm = _f(inputs.get("gross_margin"), 0.0)
    om = _f(inputs.get("operating_margin"), 0.0)
    roe = _f(inputs.get("roe"), 0.0)

    expectation_hurdle = 50.0
    if not np.isnan(pe):
        expectation_hurdle += 10 if pe > 40 else (-8 if pe < 18 else 0)
    if not np.isnan(ps):
        expectation_hurdle += 10 if ps > 12 else (-6 if ps < 4 else 0)
    if not np.isnan(ev_ebitda):
        expectation_hurdle += 8 if ev_ebitda > 25 else (-5 if ev_ebitda < 12 else 0)

    fundamental_momentum = 50.0 + 80 * rev_g + 50 * eps_g + 18 * max(gm, 0) + 40 * om + 20 * roe

    return {
        "expectation_hurdle": clamp(expectation_hurdle),
        "fundamental_momentum": clamp(fundamental_momentum),
        "legacy_expectations_gap": clamp(fundamental_momentum) - clamp(expectation_hurdle),
    }


def _synthesize(
    inputs: Dict[str, Any],
    reverse: Dict[str, Any],
    cap: Dict[str, Any],
    meroi: Dict[str, Any],
    quality: Dict[str, Any],
    bridge: Dict[str, Any],
    catalyst_meta: Optional[Dict[str, Any]],
) -> Tuple[float, Dict[str, Any]]:
    implied_cagr = _f(reverse.get("implied_cagr"))
    rev_growth = _f(inputs.get("revenue_growth"), 0.0)
    roic = _f(inputs.get("roic"))
    meroi_val = _f(meroi.get("meroi"))
    alpha = _f(bridge.get("real_world_alpha"))
    hist_ret = _f(bridge.get("historical_return"))

    legacy = _legacy_multiple_proxy(inputs)
    catalyst_score = _f((catalyst_meta or {}).get("total"), 50.0)
    if np.isnan(catalyst_score):
        catalyst_score = 50.0

    # Gap 1: actual/consensus growth versus price-implied growth.
    growth_gap = rev_growth - implied_cagr if not np.isnan(implied_cagr) else np.nan
    growth_gap_score = 50.0 if np.isnan(growth_gap) else clamp(50 + 220 * growth_gap)

    # Gap 2: current ROIC versus MEROI.
    roic_gap = roic - meroi_val if not np.isnan(roic) and not np.isnan(meroi_val) else np.nan
    roic_gap_score = 50.0 if np.isnan(roic_gap) else clamp(50 + 180 * roic_gap)

    # Gap 3: realized market alpha versus implied real-world alpha.
    alpha_gap = hist_ret - alpha if not np.isnan(hist_ret) and not np.isnan(alpha) else np.nan
    alpha_gap_score = 50.0 if np.isnan(alpha_gap) else clamp(50 + 120 * alpha_gap)

    quality_score = _f(quality.get("quality_score"), 50.0)
    legacy_gap_score = clamp(50 + legacy["legacy_expectations_gap"])

    score = (
        0.25 * growth_gap_score
        + 0.25 * roic_gap_score
        + 0.20 * quality_score
        + 0.15 * legacy_gap_score
        + 0.10 * alpha_gap_score
        + 0.05 * catalyst_score
    )
    score = clamp(score)

    reasons = []
    # if not np.isnan(growth_gap):
    #     if growth_gap > 0.05:
    #         reasons.append(f"Growth expectations look beatable: revenue growth exceeds implied CAGR by {growth_gap}.") #{growth_gap:.1%}
    #     elif growth_gap < -0.05:
    #         reasons.append(f"Growth hurdle is demanding: implied CAGR exceeds current growth by {-growth_gap}.")
    #     else:
    #         reasons.append("Growth expectations look broadly fair versus current growth.")
            
    def pct(x):
        if x is None or np.isnan(x):
            return "n/a"
        return f"{x*100:.1f}%"

    if not np.isnan(growth_gap):

        if growth_gap > 0.05:
            reasons.append(
                f"Growth expectations look beatable: "
                f"revenue growth {pct(rev_growth)} exceeds the market-implied CAGR "
                f"of {pct(implied_cagr)}."
            )

        elif growth_gap < -0.05:
            reasons.append(
                f"Growth hurdle is demanding: "
                f"the market is pricing {pct(implied_cagr)} CAGR versus "
                f"current revenue growth of {pct(rev_growth)}."
            )

        else:
            reasons.append(
                f"Growth expectations appear balanced: "
                f"implied CAGR {pct(implied_cagr)} versus "
                f"revenue growth {pct(rev_growth)}."
            )

    if not np.isnan(roic_gap):
        if roic_gap > 0.05:
            reasons.append("ROIC comfortably exceeds market-required incremental return.")
        elif roic_gap < -0.05:
            reasons.append("ROIC is below the market-required incremental return.")
        else:
            reasons.append("ROIC is close to the market-required incremental return.")

    reasons.extend(quality.get("quality_reasons", [])[:4])
    reasons.append(cap.get("cap_read", "CAP unavailable"))
    reasons.append(meroi.get("meroi_read", "MEROI unavailable"))

    if score >= 75:
        signal = "Expectations look beatable"
    elif score >= 60:
        signal = "Expectations constructive"
    elif score >= 45:
        signal = "Expectations fairly priced"
    else:
        signal = "Expectations demanding"

    read = (
        f"Expectation investing: {signal}. "
        f"Implied CAGR {implied_cagr:.1%} vs revenue growth {rev_growth:.1%}; "
        f"CAP {cap.get('market_implied_cap', 'n/a')} yrs; "
        f"ROIC {_fmt_pct(roic)} vs MEROI {_fmt_pct(meroi_val)}."
    )

    meta = {
        "expectation_reasons": reasons,
        "expectation_read": read,
        "expectation_signal": signal,
        "expectations_gap": round(legacy["legacy_expectations_gap"], 1),
        "expectation_hurdle": legacy["expectation_hurdle"],
        "fundamental_momentum": legacy["fundamental_momentum"],
        "growth_gap": None if np.isnan(growth_gap) else round(growth_gap, 4),
        "roic_gap": None if np.isnan(roic_gap) else round(roic_gap, 4),
        "alpha_gap": None if np.isnan(alpha_gap) else round(alpha_gap, 4),
        "growth_gap_score": round(growth_gap_score, 1),
        "roic_gap_score": round(roic_gap_score, 1),
        "alpha_gap_score": round(alpha_gap_score, 1),
        "quality_score": round(quality_score, 1),
        **inputs,
        **reverse,
        **cap,
        **meroi,
        **bridge,
        **legacy,
    }
    return score, meta


def _fmt_pct(x: Any) -> str:
    v = _f(x)
    if np.isnan(v):
        return "n/a"
    return f"{v:.1%}"


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

def expectation_score(
    info: Optional[Dict[str, Any]],
    df: Optional[pd.DataFrame] = None,
    fund_meta: Optional[Dict[str, Any]] = None,
    catalyst_meta: Optional[Dict[str, Any]] = None,
) -> Tuple[float, Dict[str, Any]]:
    """
    Drop-in replacement for the old expectation_score().
    Returns:
        score: 0-100
        metadata: dict consumed by analysis_service / response_formatter
    """
    if not info:
        return 50.0, {
            "expectation_reasons": ["No expectation data available"],
            "expectation_read": "No expectation edge detected.",
            "expectation_signal": "Unavailable",
        }

    inputs = _normalized_inputs(info, df)
    reverse = _solve_implied_cagr(inputs, years=5)

    implied_cagr = _f(reverse.get("implied_cagr"))
    # Use current revenue growth as a consensus proxy unless unavailable.
    consensus_cagr = _f(inputs.get("revenue_growth"), np.nan)
    if np.isnan(consensus_cagr) or abs(consensus_cagr) < 1e-6:
        consensus_cagr = implied_cagr if not np.isnan(implied_cagr) else 0.05

    cap = _market_implied_cap(inputs, consensus_cagr=consensus_cagr, wacc=_f(reverse.get("wacc"), _wacc(inputs.get("beta", 1.0))))
    meroi = _meroi_proxy(
        inputs,
        implied_cagr=implied_cagr,
        cap_years=_f(cap.get("market_implied_cap")),
        wacc=_f(reverse.get("wacc"), _wacc(inputs.get("beta", 1.0))),
    )
    quality = _quality_screen(inputs, fund_meta)
    bridge = _partial_expectation_bridge(df)

    score, meta = _synthesize(inputs, reverse, cap, meroi, quality, bridge, catalyst_meta)
    return round(score, 1), meta
