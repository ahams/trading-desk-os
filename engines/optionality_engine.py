from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
import math
import numpy as np
import pandas as pd

try:
    from utils import clamp
except Exception:
    def clamp(x, lo=0, hi=100):
        try:
            return max(lo, min(hi, float(x)))
        except Exception:
            return 50.0


def _f(x: Any, default: float = np.nan) -> float:
    try:
        if x is None or pd.isna(x):
            return default
        return float(x)
    except Exception:
        return default


def _pct(x: Any, default: float = 0.0) -> float:
    v = _f(x, default)
    if np.isnan(v):
        return default
    return v / 100.0 if abs(v) > 1.5 else v

def fmt_pct(x: Any, default: float = 0.0) -> str:
    """
    Accepts either 0.18 or 18 and always returns '18.0%'.
    """
    return f"{_pct(x, default):.1%}"

def _safe_div(a: float, b: float, default: float = np.nan) -> float:
    try:
        if b is None or b == 0 or np.isnan(b):
            return default
        return a / b
    except Exception:
        return default


def _infer_sector_multiple(sector: str, industry: str = "") -> Dict[str, float]:
    """
    Conservative existing-business valuation multiples.
    These are not target multiples; they are rough anchors for visible business value.
    """

    s = (sector or "").lower()
    i = (industry or "").lower()

    if "semiconductor" in i or "semiconductor" in s:
        return {"ev_sales": 8.0, "ev_ebitda": 22.0, "fcf": 30.0}

    if "software" in i:
        return {"ev_sales": 7.0, "ev_ebitda": 20.0, "fcf": 28.0}

    if "technology" in s:
        return {"ev_sales": 5.0, "ev_ebitda": 16.0, "fcf": 24.0}

    if "communication" in s:
        return {"ev_sales": 4.0, "ev_ebitda": 14.0, "fcf": 22.0}

    if "healthcare" in s:
        return {"ev_sales": 4.0, "ev_ebitda": 15.0, "fcf": 22.0}

    if "consumer" in s:
        return {"ev_sales": 2.5, "ev_ebitda": 12.0, "fcf": 18.0}

    if "industrial" in s:
        return {"ev_sales": 2.0, "ev_ebitda": 11.0, "fcf": 16.0}

    if "energy" in s:
        return {"ev_sales": 1.8, "ev_ebitda": 7.0, "fcf": 10.0}

    if "utilities" in s:
        return {"ev_sales": 2.5, "ev_ebitda": 10.0, "fcf": 14.0}

    if "financial" in s:
        return {"ev_sales": 3.0, "ev_ebitda": 10.0, "fcf": 12.0}

    return {"ev_sales": 3.0, "ev_ebitda": 12.0, "fcf": 18.0}


def _blend_existing_value(values: Dict[str, float]) -> Tuple[float, Dict[str, float]]:
    """
    Blend available valuation anchors.
    More weight to EBITDA/FCF if available, less to sales.
    """

    valid = {k: v for k, v in values.items() if v is not None and not np.isnan(v) and v > 0}

    if not valid:
        return np.nan, {}

    weights = {
        "sales_value": 0.25,
        "ebitda_value": 0.40,
        "fcf_value": 0.35,
        "book_asset_value": 0.15,
    }

    numerator = 0.0
    denominator = 0.0

    used_weights = {}

    for k, v in valid.items():
        w = weights.get(k, 0.25)
        numerator += v * w
        denominator += w
        used_weights[k] = w

    return numerator / denominator if denominator > 0 else np.nan, used_weights


def optionality_score(
    info: Optional[Dict[str, Any]],
    df: Optional[pd.DataFrame] = None,
    fund_meta: Optional[Dict[str, Any]] = None,
    expectation_meta: Optional[Dict[str, Any]] = None,
    greenfield_meta: Optional[Dict[str, Any]] = None,
) -> Tuple[float, Dict[str, Any]]:
    """
    Market-implied optionality decomposition.

    Core question:
        How much of today's market value is supported by visible/current business,
        and how much is implied future option value?

    Output:
        score: 0-100
            Higher score = more unpriced / attractive optionality.
            Lower score = market already prices a lot of future optionality.

    This is different from Merton:
        Merton = survival / default risk.
        Optionality = future upside already embedded in market price.
    """

    if not info:
        return 50.0, {
            "signal": "No optionality data",
            "summary": "Optionality analysis unavailable because market/fundamental data is missing.",
        }

    ticker = info.get("symbol") or info.get("ticker") or "UNKNOWN"

    market_cap = _f(info.get("marketCap"))
    enterprise_value = _f(info.get("enterpriseValue"))

    total_debt = _f(info.get("totalDebt"), 0.0)
    total_cash = _f(info.get("totalCash"), 0.0)

    if np.isnan(enterprise_value) or enterprise_value <= 0:
        if not np.isnan(market_cap) and market_cap > 0:
            enterprise_value = market_cap + total_debt - total_cash

    revenue = _f(info.get("totalRevenue"))
    ebitda = _f(info.get("ebitda"))
    fcf = _f(info.get("freeCashflow"))

    sector = info.get("sector") or ""
    industry = info.get("industry") or ""

    multiples = _infer_sector_multiple(sector, industry)

    sales_value = revenue * multiples["ev_sales"] if revenue and revenue > 0 else np.nan
    ebitda_value = ebitda * multiples["ev_ebitda"] if ebitda and ebitda > 0 else np.nan
    fcf_value = fcf * multiples["fcf"] if fcf and fcf > 0 else np.nan

    book_value_per_share = _f(info.get("bookValue"))
    shares = _f(info.get("sharesOutstanding"))

    book_asset_value = (
        book_value_per_share * shares
        if book_value_per_share and shares and book_value_per_share > 0 and shares > 0
        else np.nan
    )

    visible_values = {
        "sales_value": sales_value,
        "ebitda_value": ebitda_value,
        "fcf_value": fcf_value,
        "book_asset_value": book_asset_value,
    }

    existing_business_value, blend_weights = _blend_existing_value(visible_values)

    if np.isnan(existing_business_value) or existing_business_value <= 0 or np.isnan(enterprise_value) or enterprise_value <= 0:
        return 50.0, {
            "signal": "Insufficient optionality data",
            "summary": f"Optionality read for {ticker}: insufficient data to decompose existing business value vs embedded future option value.",
            "metrics": {
                "market_cap": market_cap,
                "enterprise_value": enterprise_value,
                "revenue": revenue,
                "ebitda": ebitda,
                "free_cash_flow": fcf,
            },
        }

    embedded_option_value = max(enterprise_value - existing_business_value, 0.0)
    embedded_optionality_pct = embedded_option_value / enterprise_value

    existing_value_pct = existing_business_value / enterprise_value

    # If existing value exceeds EV, the market is not paying much for future options.
    if existing_business_value >= enterprise_value:
        embedded_optionality_pct = 0.0
        embedded_option_value = 0.0
        existing_value_pct = 1.0

    # Greenfield / ARR optionality may justify more option value.
    gf_score = _f((greenfield_meta or {}).get("score"), np.nan)
    exp_score = _f((expectation_meta or {}).get("score"), np.nan)

    # Expectation demanding indicators
    implied_cagr = _f((expectation_meta or {}).get("implied_cagr"), np.nan)
    revenue_growth = _f((expectation_meta or {}).get("revenue_growth"), np.nan)
    roic = _f((expectation_meta or {}).get("roic"), np.nan)
    meroi = _f((expectation_meta or {}).get("meroi"), np.nan)
    cap_years = _f((expectation_meta or {}).get("market_implied_cap"), np.nan)

    expectation_penalty = 0.0
    expectation_bonus = 0.0

    if not np.isnan(implied_cagr) and not np.isnan(revenue_growth):
        if implied_cagr > revenue_growth * 1.5:
            expectation_penalty += 12
        elif revenue_growth > implied_cagr:
            expectation_bonus += 10

    if not np.isnan(roic) and not np.isnan(meroi):
        if roic > meroi:
            expectation_bonus += 12
        elif roic < meroi * 0.75:
            expectation_penalty += 12

    if not np.isnan(cap_years):
        if cap_years >= 15:
            expectation_penalty += 8
        elif cap_years <= 7:
            expectation_bonus += 8

    # Interpret optionality burden.
    # Low embedded optionality = market mostly pays for existing assets => more upside optionality left.
    # Very high embedded optionality = market already prices future upside => execution burden high.
    if embedded_optionality_pct <= 0.10:
        base_score = 82
        signal = "Low embedded optionality / upside not fully priced"
    elif embedded_optionality_pct <= 0.25:
        base_score = 70
        signal = "Moderate embedded optionality"
    elif embedded_optionality_pct <= 0.50:
        base_score = 55
        signal = "Meaningful embedded optionality"
    elif embedded_optionality_pct <= 0.75:
        base_score = 38
        signal = "High embedded optionality / execution burden elevated"
    else:
        base_score = 25
        signal = "Very high embedded optionality / market already prices future success"

    if not np.isnan(gf_score):
        if gf_score >= 70 and embedded_optionality_pct < 0.35:
            base_score += 8
        elif gf_score < 45 and embedded_optionality_pct > 0.35:
            base_score -= 8

    if not np.isnan(exp_score):
        if exp_score >= 70:
            base_score += 5
        elif exp_score < 45:
            base_score -= 5

    score = clamp(base_score + expectation_bonus - expectation_penalty)

    if embedded_optionality_pct <= 0.15:
        interpretation = (
            "Market value appears mostly supported by visible/current business. "
            "Future opportunities may not be heavily priced in."
        )
    elif embedded_optionality_pct <= 0.40:
        interpretation = (
            "Market is assigning some value to future opportunities, but existing business still supports a meaningful part of valuation."
        )
    elif embedded_optionality_pct <= 0.65:
        interpretation = (
            "A large portion of valuation depends on future opportunities. Execution quality matters."
        )
    else:
        interpretation = (
            "Valuation is heavily dependent on future optionality. Execution disappointment could create downside."
        )

    existing_value_b = existing_business_value / 1e9
    ev_b = enterprise_value / 1e9
    option_b = embedded_option_value / 1e9

    summary = (
        f"Optionality read for {ticker}: {signal}. "
        f"Enterprise value ≈ ${ev_b:.1f}B, estimated visible business value ≈ ${existing_value_b:.1f}B, "
        f"embedded future option value ≈ ${option_b:.1f}B "
        f"({embedded_optionality_pct:.0%} of EV). {interpretation}"
    )

    bull_points = []
    bear_points = []

    if embedded_optionality_pct <= 0.15:
        bull_points.append("Market appears to be pricing limited value for future options.")
    elif embedded_optionality_pct >= 0.50:
        bear_points.append("Market is already pricing substantial future optionality.")

    if embedded_option_value > 0:
        bear_points.append(
            f"Embedded option value is approximately ${option_b:.1f}B, requiring future execution to justify valuation."
        )

    if not np.isnan(implied_cagr) and not np.isnan(revenue_growth) and implied_cagr > revenue_growth * 1.5:
        bear_points.append(
            f"Growth hurdle is demanding: implied CAGR {fmt_pct(implied_cagr)} vs revenue growth {fmt_pct(revenue_growth)}."
        )

    if not np.isnan(roic) and not np.isnan(meroi):
        if roic > meroi:
            bull_points.append(f"ROIC exceeds market-implied reinvestment hurdle: ROIC {fmt_pct(roic)} vs MEROI {fmt_pct(meroi)}.")
        elif roic < meroi * 0.75:
            bear_points.append(f"ROIC is below market-implied reinvestment hurdle: ROIC {fmt_pct(roic)}  vs MEROI {fmt_pct(meroi)}.")

    return score, {
        "score": round(score, 1),
        "signal": signal,
        "summary": summary,
        "bull_points": bull_points[:3],
        "bear_points": bear_points[:3],
        "metrics": {
            "market_cap": market_cap,
            "enterprise_value": enterprise_value,
            "existing_business_value": existing_business_value,
            "embedded_option_value": embedded_option_value,
            "embedded_optionality_pct": embedded_optionality_pct,
            "existing_value_pct": existing_value_pct,
            "sales_value": sales_value,
            "ebitda_value": ebitda_value,
            "fcf_value": fcf_value,
            "book_asset_value": book_asset_value,
            "revenue": revenue,
            "ebitda": ebitda,
            "free_cash_flow": fcf,
            "sector_ev_sales_multiple": multiples["ev_sales"],
            "sector_ev_ebitda_multiple": multiples["ev_ebitda"],
            "sector_fcf_multiple": multiples["fcf"],
            "blend_weights": blend_weights,
        },
        "expectation_context": {
            "implied_cagr": implied_cagr,
            "revenue_growth": revenue_growth,
            "market_implied_cap": cap_years,
            "roic": roic,
            "meroi": meroi,
        },
    }