"""
cml_sml_engine.py

Macro-pricing / mispricing engine for the Pro Stock Decision App.

Purpose
-------
CML/SML should not be a blind buy/sell model. It is a risk-pricing diagnostic:

1) SML / CAPM: Is the stock offering enough expected return for its beta?
2) CML: Is the stock efficient after total volatility/idiosyncratic risk?
3) CML-SML gap: Is this a diversified-manager alpha opportunity or a
   concentrated-portfolio volatility trap?

This module returns the same app-friendly structure used elsewhere:
(score, metadata dict)
"""

from __future__ import annotations

import logging
from typing import Dict, Tuple

import numpy as np
import pandas as pd

from utils import clamp

logger = logging.getLogger("trading_desk.cml_sml")

TRADING_DAYS = 252


def _safe_float(x, default=np.nan) -> float:
    try:
        if x is None:
            return default
        val = float(x)
        if not np.isfinite(val):
            return default
        return val
    except Exception:
        return default


def _returns(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty or "Close" not in df:
        return pd.Series(dtype=float)
    r = df["Close"].astype(float).pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    return r


def estimate_beta(asset_df: pd.DataFrame, market_df: pd.DataFrame) -> float:
    """Estimate beta using aligned daily/intraday percentage returns."""
    ar = _returns(asset_df)
    mr = _returns(market_df)
    if len(ar) < 40 or len(mr) < 40:
        return 1.0

    joined = pd.concat([ar.rename("asset"), mr.rename("market")], axis=1).dropna()
    if len(joined) < 40 or joined["market"].var() <= 0:
        return 1.0
    beta = joined["asset"].cov(joined["market"]) / joined["market"].var()
    return float(np.clip(beta, -3.0, 5.0))


def estimate_annual_vol(df: pd.DataFrame) -> float:
    r = _returns(df)
    if len(r) < 20:
        return np.nan
    return float(r.std() * np.sqrt(TRADING_DAYS))


def estimate_expected_return(info: Dict, df: pd.DataFrame) -> float:
    """
    Practical expected return proxy.

    Priority:
    - targetMeanPrice / currentPrice if available from yfinance
    - trailing realized drift/momentum blend

    This is intentionally conservative and clipped because realized means are noisy.
    """
    price = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice"), np.nan) if info else np.nan
    target = _safe_float(info.get("targetMeanPrice"), np.nan) if info else np.nan
    if np.isfinite(price) and price > 0 and np.isfinite(target) and target > 0:
        implied = target / price - 1.0
        return float(np.clip(implied, -0.60, 1.50))

    if df is None or df.empty or len(df) < 60:
        return 0.08

    close = df["Close"].astype(float).dropna()
    if len(close) < 60:
        return 0.08

    # Blend 12m CAGR where possible with 3m momentum. This is a proxy, not a forecast.
    lookback = min(len(close) - 1, TRADING_DAYS)
    cagr = (close.iloc[-1] / close.iloc[-lookback - 1]) ** (TRADING_DAYS / lookback) - 1 if lookback > 20 else 0.08
    m63 = close.iloc[-1] / close.iloc[-min(63, len(close)-1)] - 1 if len(close) > 64 else 0.0
    expected = 0.65 * cagr + 0.35 * (m63 * 4.0)
    return float(np.clip(expected, -0.50, 1.00))


def cml_sml_score(
    info: Dict,
    asset_df: pd.DataFrame,
    market_df: pd.DataFrame,
    risk_free_rate: float = 0.045,
    expected_market_return: Optional[float] = None,
    market_volatility: Optional[float] = None,
) -> Tuple[float, Dict]:
    """
    Score a stock using SML alpha plus CML efficiency/trap diagnostics.

    Returns
    -------
    score : float 0-100
    meta  : dict with metrics/reasons/read
    """
    if asset_df is None or market_df is None or len(asset_df) < 40 or len(market_df) < 40:
        return 50.0, {
            "pricing_read": "Insufficient data for CML/SML analysis.",
            "macro_pricing_reasons": [],
            "metrics": {},
        }

    beta = estimate_beta(asset_df, market_df)
    asset_vol = estimate_annual_vol(asset_df)
    market_vol = market_volatility if market_volatility is not None else estimate_annual_vol(market_df)
    exp_asset_ret = estimate_expected_return(info or {}, asset_df)

    if expected_market_return is None:
        mr = _returns(market_df)
        raw_market = float(mr.mean() * TRADING_DAYS) if len(mr) > 40 else 0.10
        expected_market_return = float(np.clip(raw_market, risk_free_rate + 0.02, 0.18))

    market_risk_premium = expected_market_return - risk_free_rate
    sml_required = risk_free_rate + beta * market_risk_premium
    sml_alpha = exp_asset_ret - sml_required

    market_sharpe = market_risk_premium / market_vol if market_vol and market_vol > 0 else np.nan
    cml_required = risk_free_rate + market_sharpe * asset_vol if np.isfinite(market_sharpe) and np.isfinite(asset_vol) else np.nan
    cml_gap = exp_asset_ret - cml_required if np.isfinite(cml_required) else np.nan

    # Idiosyncratic risk proxy: total variance minus beta-implied market variance.
    systematic_vol = abs(beta) * market_vol if np.isfinite(market_vol) else np.nan
    idio_vol = np.sqrt(max(asset_vol**2 - systematic_vol**2, 0.0)) if np.isfinite(asset_vol) and np.isfinite(systematic_vol) else np.nan
    idio_share = idio_vol / asset_vol if np.isfinite(idio_vol) and asset_vol and asset_vol > 0 else np.nan

    score = 50.0
    reasons = []
    warnings = []

    # SML alpha component: useful for individual-asset pricing.
    if sml_alpha > 0.05:
        score += 20
        reasons.append(f"Positive SML alpha: {sml_alpha:.1%}")
    elif sml_alpha > 0.015:
        score += 10
        reasons.append(f"Modest positive SML alpha: {sml_alpha:.1%}")
    elif sml_alpha < -0.05:
        score -= 20
        warnings.append(f"Negative SML alpha: {sml_alpha:.1%}")
    elif sml_alpha < -0.015:
        score -= 10
        warnings.append(f"Modest negative SML alpha: {sml_alpha:.1%}")

    # CML gap: penalize concentrated total-risk inefficiency.
    if np.isfinite(cml_gap):
        if cml_gap > 0.03:
            score += 10
            reasons.append(f"Efficient vs CML hurdle: {cml_gap:.1%}")
        elif cml_gap < -0.08:
            score -= 18
            warnings.append(f"Below CML total-risk hurdle: {cml_gap:.1%}")
        elif cml_gap < -0.03:
            score -= 8
            warnings.append(f"Sits below CML total-risk hurdle: {cml_gap:.1%}")

    # Volatility trap diagnostic: positive SML alpha but poor CML placement.
    volatility_trap = bool(sml_alpha > 0 and np.isfinite(cml_gap) and cml_gap < -0.05)
    if volatility_trap:
        score -= 10
        warnings.append("SML-CML divergence: attractive to diversified managers but risky for concentrated portfolios")

    if np.isfinite(idio_share) and idio_share > 0.70:
        score -= 8
        warnings.append(f"High idiosyncratic risk share: {idio_share:.0%}")

    if beta > 2.0 and np.isfinite(asset_vol) and asset_vol > 0.55:
        score -= 6
        warnings.append("High-beta/high-volatility profile can gap violently in risk-off regimes")

    if score >= 70:
        read = "Macro pricing supports the setup; expected return clears the beta hurdle and risk efficiency is acceptable."
    elif score >= 50:
        read = "Macro pricing is mixed; use technical/liquidity confirmation before committing capital."
    else:
        read = "Macro pricing is unfavorable or volatility-trap risk is elevated; position sizing should be defensive."

    metrics = {
        "expected_asset_return": exp_asset_ret,
        "expected_market_return": expected_market_return,
        "risk_free_rate": risk_free_rate,
        "beta": beta,
        "asset_volatility": asset_vol,
        "market_volatility": market_vol,
        "sml_required_return": sml_required,
        "sml_alpha": sml_alpha,
        "cml_required_return": cml_required,
        "cml_gap": cml_gap,
        "market_sharpe": market_sharpe,
        "idiosyncratic_volatility": idio_vol,
        "idiosyncratic_risk_share": idio_share,
        "volatility_trap": volatility_trap,
    }

    return clamp(score), {
        "pricing_read": read,
        "macro_pricing_reasons": reasons,
        "macro_pricing_warnings": warnings,
        "metrics": metrics,
        "summary": read,
    }


# Backward-compatible alias if you prefer this naming in app.py
macro_pricing_score = cml_sml_score
