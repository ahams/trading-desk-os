"""
Expectation Investing Engine
----------------------------
Adds a Mauboussin/Rappaport-style "expectations gap" layer.

This module does NOT claim intrinsic value precision. It asks the practical
trader's question:
    "What must the market already be assuming, and is that hurdle beatable?"

Public API:
    expectation_score(info, df=None, fund_meta=None, catalyst_meta=None) -> (score, metadata)

Score interpretation:
    70-100: expectations look beatable / positive revision potential
    45-70 : neutral or fairly priced expectations
    0-45  : expectations look demanding / disappointment risk
"""
from __future__ import annotations

import math
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd

from utils import clamp


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


def _latest_price(df: Optional[pd.DataFrame], info: Dict[str, Any]) -> float:
    if df is not None and not df.empty and "Close" in df:
        return _f(df["Close"].iloc[-1])
    return _f(info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose"))


def _ev(info: Dict[str, Any]) -> float:
    ev = _f(info.get("enterpriseValue"))
    if not np.isnan(ev) and ev > 0:
        return ev
    mc = _f(info.get("marketCap"))
    debt = _f(info.get("totalDebt"), 0.0)
    cash = _f(info.get("totalCash"), 0.0)
    return mc + debt - cash if not np.isnan(mc) else np.nan


def _expected_move_from_multiples(info: Dict[str, Any]) -> Dict[str, float]:
    """
    Very rough reverse-expectation proxies from valuation.
    Higher valuation means market is embedding more growth/quality expectation.
    """
    pe = _f(info.get("forwardPE") or info.get("trailingPE"))
    ps = _f(info.get("priceToSalesTrailing12Months"))
    ev_ebitda = _f(info.get("enterpriseToEbitda"))
    rev_g = _pct(info.get("revenueGrowth"))
    eps_g = _pct(info.get("earningsGrowth"))
    gm = _pct(info.get("grossMargins"))
    om = _pct(info.get("operatingMargins"))
    roe = _pct(info.get("returnOnEquity"))

    expectation_hurdle = 50.0
    if not np.isnan(pe):
        expectation_hurdle += 10 if pe > 40 else (-8 if pe < 18 else 0)
    if not np.isnan(ps):
        expectation_hurdle += 10 if ps > 12 else (-6 if ps < 4 else 0)
    if not np.isnan(ev_ebitda):
        expectation_hurdle += 8 if ev_ebitda > 25 else (-5 if ev_ebitda < 12 else 0)

    fundamental_momentum = 50.0
    fundamental_momentum += 80 * rev_g
    fundamental_momentum += 50 * eps_g
    fundamental_momentum += 18 * max(gm, 0)
    fundamental_momentum += 40 * om
    fundamental_momentum += 20 * roe

    return {
        "expectation_hurdle": clamp(expectation_hurdle),
        "fundamental_momentum": clamp(fundamental_momentum),
        "revenue_growth": rev_g,
        "eps_growth": eps_g,
        "gross_margin": gm,
        "operating_margin": om,
        "roe": roe,
        "pe": pe,
        "ps": ps,
        "ev_ebitda": ev_ebitda,
    }


def _reverse_fcf_yield(info: Dict[str, Any]) -> Dict[str, float]:
    """
    Reverse DCF-lite. Uses FCF yield and growth to infer whether market pricing
    is forgiving or demanding. This avoids fragile precise valuation.
    """
    mc = _f(info.get("marketCap"))
    fcf = _f(info.get("freeCashflow"))
    ev = _ev(info)
    fcf_yield = fcf / mc if mc and not np.isnan(fcf) and mc > 0 else np.nan
    ev_fcf_yield = fcf / ev if ev and not np.isnan(fcf) and ev > 0 else np.nan

    score = 50.0
    flags = []

    if np.isnan(fcf_yield):
        flags.append("FCF yield unavailable")
    elif fcf_yield > 0.06:
        score += 20
        flags.append(f"Attractive FCF yield: {fcf_yield:.1%}")
    elif fcf_yield > 0.03:
        score += 10
        flags.append(f"Positive FCF yield: {fcf_yield:.1%}")
    elif fcf_yield < -0.05:
        score -= 20
        flags.append(f"Heavy cash burn vs market cap: {fcf_yield:.1%}")
    elif fcf_yield < 0:
        score -= 10
        flags.append(f"Negative FCF yield: {fcf_yield:.1%}")

    return {"fcf_yield": fcf_yield, "ev_fcf_yield": ev_fcf_yield, "fcf_score": clamp(score), "fcf_flags": flags}


def expectation_score(
    info: Optional[Dict[str, Any]],
    df: Optional[pd.DataFrame] = None,
    fund_meta: Optional[Dict[str, Any]] = None,
    catalyst_meta: Optional[Dict[str, Any]] = None,
) -> Tuple[float, Dict[str, Any]]:
    if not info:
        return 50.0, {
            "expectation_reasons": ["No expectation data available"],
            "expectation_read": "No expectation edge detected.",
        }

    mult = _expected_move_from_multiples(info)
    fcf = _reverse_fcf_yield(info)

    catalyst_score = _f((catalyst_meta or {}).get("total"), 50.0)
    if np.isnan(catalyst_score):
        catalyst_score = 50.0

    # If market expectations are high, the stock needs stronger fundamental/catalyst
    # evidence. If expectations are low, merely improving fundamentals can be enough.
    expectations_gap = mult["fundamental_momentum"] - mult["expectation_hurdle"]
    gap_score = clamp(50 + expectations_gap)

    score = (
        0.45 * gap_score
        + 0.30 * fcf["fcf_score"]
        + 0.15 * catalyst_score
        + 0.10 * _f((fund_meta or {}).get("quality"), 50.0)
    )

    flags = []
    if expectations_gap > 15:
        flags.append("Market expectations look beatable")
    elif expectations_gap < -15:
        flags.append("Valuation expectations look demanding")
    else:
        flags.append("Expectations look broadly fair")
    flags.extend(fcf["fcf_flags"])

    pe = mult["pe"]
    ps = mult["ps"]
    rg = mult["revenue_growth"]
    eg = mult["eps_growth"]
    read_parts = []
    if not np.isnan(pe):
        read_parts.append(f"P/E {pe:.1f}")
    if not np.isnan(ps):
        read_parts.append(f"P/S {ps:.1f}")
    read_parts.append(f"revenue growth {rg:.1%}")
    read_parts.append(f"EPS growth {eg:.1%}")

    return clamp(score), {
        "expectation_reasons": flags,
        "expectation_read": "Expectation investing: " + "; ".join(read_parts) + ".",
        "expectations_gap": round(expectations_gap, 1),
        "expectation_hurdle": mult["expectation_hurdle"],
        "fundamental_momentum": mult["fundamental_momentum"],
        **fcf,
        **mult,
    }
