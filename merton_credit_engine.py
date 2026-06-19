"""
merton_credit_engine.py

Trading Desk OS structural-credit / Merton-style engine.

Purpose
-------
This engine is deliberately different from ordinary fundamental valuation.
It asks:

    Can the company survive long enough for the growth story to play out?

It estimates a practical, app-friendly approximation of:
- equity volatility
- default barrier
- distance to default
- annualized default probability proxy
- capital-structure / refinancing risk score

It is inspired by the full multi-period Merton model, but designed to be
fast, dependency-light, and safe inside the FastAPI scanner. It does not
require scipy and does not solve a nonlinear option-pricing system on every
API request.

Contract
--------
    analyze_merton_credit(ticker: str, data: dict) -> dict

Expected data keys, all optional:
    data = {
        "ohlcv": pandas DataFrame with Close,
        "fundamentals": yfinance info dict or normalized fundamentals,
        "risk_free_rate": 0.045,
    }

Returns registry-compatible dict:
    {
      "engine": "merton_credit",
      "score": 0-100,              # higher = safer capital structure
      "signal": "Low Credit Risk" | ...,
      "summary": "...",
      "flags": [...],
      "metrics": {...},
      "trade_impact": {...}
    }

Notes
-----
- This is a structural credit-risk approximation, not a default forecast.
- Financials/banks/insurers should be treated cautiously.
- For speculative growth equities, use this together with neocloud_valuation
  or expectation_engine rather than as a standalone buy/sell signal.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    try:
        if x is None or math.isnan(float(x)) or math.isinf(float(x)):
            return 50.0
        return max(lo, min(hi, float(x)))
    except Exception:
        return 50.0


def _safe_float(x: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if x is None:
            return default
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except Exception:
        return default


def _norm_info(info: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize common yfinance/FMP naming variants."""
    info = info or {}
    return {
        "market_cap": _safe_float(info.get("market_cap") or info.get("marketCap")),
        "enterprise_value": _safe_float(info.get("enterprise_value") or info.get("enterpriseValue")),
        "total_debt": _safe_float(info.get("total_debt") or info.get("totalDebt"), 0.0) or 0.0,
        "cash": _safe_float(info.get("cash") or info.get("total_cash") or info.get("totalCash"), 0.0) or 0.0,
        "ebitda": _safe_float(info.get("ebitda") or info.get("EBITDA")),
        "free_cashflow": _safe_float(info.get("free_cashflow") or info.get("freeCashflow") or info.get("freeCashFlow")),
        "operating_cashflow": _safe_float(info.get("operating_cashflow") or info.get("operatingCashflow")),
        "revenue_growth": _safe_float(info.get("revenue_growth") or info.get("revenueGrowth")),
        "current_ratio": _safe_float(info.get("current_ratio") or info.get("currentRatio")),
        "shares_outstanding": _safe_float(info.get("shares_outstanding") or info.get("sharesOutstanding")),
        "sector": info.get("sector", ""),
        "industry": info.get("industry", ""),
    }


def _equity_volatility(df: Optional[pd.DataFrame]) -> Optional[float]:
    if df is None or len(df) < 60 or "Close" not in df.columns:
        return None
    close = pd.to_numeric(df["Close"], errors="coerce").dropna()
    if len(close) < 60:
        return None
    vol = close.pct_change().dropna().std() * np.sqrt(252)
    return _safe_float(vol)


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _credit_score_from_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    market_cap = metrics.get("market_cap")
    debt = metrics.get("total_debt") or 0.0
    cash = metrics.get("cash") or 0.0
    ebitda = metrics.get("ebitda")
    fcf = metrics.get("free_cashflow")
    equity_vol = metrics.get("equity_volatility")
    distance = metrics.get("distance_to_default")
    pd_annual = metrics.get("pd_annual_proxy")
    current_ratio = metrics.get("current_ratio")

    score = 55.0
    flags = []

    net_debt = debt - cash
    net_debt_to_mcap = net_debt / market_cap if market_cap and market_cap > 0 else None
    debt_to_mcap = debt / market_cap if market_cap and market_cap > 0 else None
    net_debt_to_ebitda = net_debt / ebitda if ebitda and ebitda > 0 else None
    fcf_to_debt = fcf / debt if fcf is not None and debt and debt > 0 else None

    if distance is not None:
        if distance >= 3.0:
            score += 22
            flags.append("Wide distance to default")
        elif distance >= 1.5:
            score += 10
            flags.append("Acceptable distance to default")
        elif distance < 0.5:
            score -= 25
            flags.append("Thin distance to default")
        elif distance < 1.0:
            score -= 12
            flags.append("Elevated structural credit risk")

    if pd_annual is not None:
        if pd_annual < 0.02:
            score += 8
        elif pd_annual > 0.15:
            score -= 18
            flags.append("High annualized default-probability proxy")
        elif pd_annual > 0.07:
            score -= 8
            flags.append("Moderate annualized default-probability proxy")

    if net_debt_to_mcap is not None:
        if net_debt_to_mcap < -0.05:
            score += 14
            flags.append("Net cash capital structure")
        elif net_debt_to_mcap > 0.75:
            score -= 22
            flags.append("Net debt is high versus market cap")
        elif net_debt_to_mcap > 0.35:
            score -= 10
            flags.append("Meaningful net debt burden")

    if net_debt_to_ebitda is not None:
        if net_debt_to_ebitda < 0:
            score += 8
        elif net_debt_to_ebitda <= 2.0:
            score += 6
        elif net_debt_to_ebitda > 5.0:
            score -= 18
            flags.append("High net debt / EBITDA")
        elif net_debt_to_ebitda > 3.5:
            score -= 9
            flags.append("Elevated net debt / EBITDA")
    elif debt and debt > 0 and (ebitda is None or ebitda <= 0):
        score -= 10
        flags.append("Debt present but EBITDA support is weak/missing")

    if fcf_to_debt is not None:
        if fcf_to_debt > 0.20:
            score += 8
            flags.append("FCF covers debt burden")
        elif fcf_to_debt < -0.10:
            score -= 12
            flags.append("Negative FCF versus debt burden")

    if current_ratio is not None:
        if current_ratio >= 2.0:
            score += 5
        elif current_ratio < 1.0:
            score -= 8
            flags.append("Current ratio below 1")

    if equity_vol is not None:
        if equity_vol > 0.90:
            score -= 15
            flags.append("Very high equity volatility")
        elif equity_vol > 0.60:
            score -= 7
            flags.append("High equity volatility")
        elif equity_vol < 0.30:
            score += 4

    if debt_to_mcap is not None and debt_to_mcap < 0.05:
        score += 4

    final = round(_clamp(score), 1)
    if final >= 75:
        signal = "Low Credit Risk"
        risk_level = "low"
        bias = "supportive"
    elif final >= 60:
        signal = "Manageable Credit Risk"
        risk_level = "moderate"
        bias = "neutral_to_supportive"
    elif final >= 45:
        signal = "Watch Credit Risk"
        risk_level = "elevated"
        bias = "cautious"
    else:
        signal = "High Credit / Funding Risk"
        risk_level = "high"
        bias = "bearish"

    metrics.update(
        {
            "net_debt": net_debt,
            "net_debt_to_market_cap": net_debt_to_mcap,
            "debt_to_market_cap": debt_to_mcap,
            "net_debt_to_ebitda": net_debt_to_ebitda,
            "fcf_to_debt": fcf_to_debt,
            "merton_credit_score": final,
            "risk_level": risk_level,
        }
    )
    return {"score": final, "signal": signal, "risk_level": risk_level, "bias": bias, "flags": flags, "metrics": metrics}


def analyze_merton_credit(ticker: str, data: Dict[str, Any]) -> Dict[str, Any]:
    info = _norm_info(data.get("fundamentals", {}) or {})
    df = data.get("ohlcv")
    r = _safe_float(data.get("risk_free_rate"), 0.045) or 0.045

    market_cap = info.get("market_cap")
    debt = info.get("total_debt") or 0.0
    cash = info.get("cash") or 0.0
    equity_vol = _equity_volatility(df)

    flags = []
    if not market_cap or market_cap <= 0:
        return {
            "engine": "merton_credit",
            "ticker": ticker.upper(),
            "score": 50.0,
            "signal": "Unavailable",
            "confidence": 0.1,
            "summary": "Merton credit model unavailable: missing market capitalization.",
            "flags": ["missing_market_cap"],
            "metrics": {},
            "trade_impact": {"bias": "neutral", "risk": "unknown", "position_adjustment": 1.0},
        }

    if equity_vol is None or equity_vol <= 0:
        return {
            "engine": "merton_credit",
            "ticker": ticker.upper(),
            "score": 50.0,
            "signal": "Unavailable",
            "confidence": 0.1,
            "summary": "Merton credit model unavailable: insufficient price history for equity volatility.",
            "flags": ["missing_equity_volatility"],
            "metrics": {"market_cap": market_cap, "total_debt": debt, "cash": cash},
            "trade_impact": {"bias": "neutral", "risk": "unknown", "position_adjustment": 1.0},
        }

    # Practical default barrier approximation. For an app scanner this is much
    # faster and more stable than solving the full nonlinear Merton system.
    # Cash reduces the effective barrier because it can fund obligations.
    default_barrier = max(debt - 0.5 * cash, 1.0) if debt > 0 else 1.0
    asset_proxy = max(market_cap + debt - cash, 1.0)
    asset_vol_proxy = max(0.01, equity_vol * market_cap / max(asset_proxy, 1.0))
    horizon = 1.0

    if debt <= 0:
        distance = 5.0
        pd_annual = 0.001
        flags.append("No material debt disclosed")
    else:
        distance = (math.log(max(asset_proxy, 1.0) / default_barrier) + (r - 0.5 * asset_vol_proxy**2) * horizon) / (asset_vol_proxy * math.sqrt(horizon))
        pd_annual = _normal_cdf(-distance)

    metrics = {
        **info,
        "equity_volatility": equity_vol,
        "asset_value_proxy": asset_proxy,
        "asset_volatility_proxy": asset_vol_proxy,
        "default_barrier_proxy": default_barrier,
        "distance_to_default": distance,
        "pd_annual_proxy": pd_annual,
        "risk_free_rate": r,
    }
    scored = _credit_score_from_metrics(metrics)
    all_flags = flags + scored["flags"]

    nd_mcap = metrics.get("net_debt_to_market_cap")
    nd_mcap_text = f"{nd_mcap * 100:.1f}%" if nd_mcap is not None else "n/a"
    summary = (
        f"Merton credit read for {ticker.upper()}: {scored['signal']} "
        f"with score {scored['score']}/100. "
        f"Distance-to-default proxy {distance:.2f}, annual PD proxy {pd_annual*100:.1f}%, "
        f"net debt/market cap {nd_mcap_text}"
    )
    if all_flags:
        summary += ". Key reads: " + "; ".join(all_flags[:5]) + "."

    position_adjustment = 1.0
    if scored["score"] < 45:
        position_adjustment = 0.55
    elif scored["score"] < 60:
        position_adjustment = 0.75
    elif scored["score"] > 75:
        position_adjustment = 1.05

    return {
        "engine": "merton_credit",
        "ticker": ticker.upper(),
        "score": scored["score"],
        "signal": scored["signal"],
        "confidence": 0.65 if debt > 0 else 0.45,
        "summary": summary,
        "flags": all_flags[:12],
        "metrics": scored["metrics"],
        "trade_impact": {
            "bias": scored["bias"],
            "risk": scored["risk_level"],
            "position_adjustment": position_adjustment,
        },
    }


# Registry-compatible alias
analyze = analyze_merton_credit
