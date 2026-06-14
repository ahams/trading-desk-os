"""
Liquidity / Volume Engine
-------------------------
Professional liquidity analysis for the stock decision-support app.

The app still exposes `liquidity_score(df, info)` because app.py expects:
    score, metadata = liquidity_score(df, info)

It also exposes `analyze_liquidity(df, fund)` for richer downstream use.
"""

import logging
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from utils import clamp

logger = logging.getLogger("trading_desk.liquidity")


def _safe_float(x: Any, default: float = np.nan) -> float:
    try:
        if x is None or pd.isna(x):
            return default
        return float(x)
    except Exception:
        return default


def _get_float_shares(fund: Optional[dict]) -> Optional[float]:
    """Accept multiple vendor field names: yfinance, FMP, custom normalized keys."""
    if not fund:
        return None
    for key in ("float_shares", "floatShares", "sharesFloat", "float", "freeFloat"):
        val = fund.get(key)
        if val is not None:
            val = _safe_float(val, default=np.nan)
            if not np.isnan(val) and val > 0:
                return val
    return None


def analyze_liquidity(df: pd.DataFrame, fund: Optional[dict] = None) -> Dict[str, Any]:
    """
    Analyze volume behavior, accumulation/distribution, and execution risk.

    Returns:
        {
            "total": 0-100 score,
            "flags": list[str],
            "metrics": dict,
            "summary": str,
        }
    """
    if df is None or df.empty or len(df) < 20:
        return {
            "total": 50,
            "flags": ["Insufficient liquidity history"],
            "summary": "Liquidity: insufficient data.",
            "metrics": {},
        }

    required = {"Close", "High", "Low", "Volume"}
    missing = required.difference(df.columns)
    if missing:
        return {
            "total": 50,
            "flags": [f"Missing columns: {', '.join(sorted(missing))}"],
            "summary": "Liquidity: unavailable due to missing OHLCV fields.",
            "metrics": {},
        }

    data = df.copy()
    for col in ["Close", "High", "Low", "Volume"]:
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data = data.dropna(subset=["Close", "High", "Low", "Volume"])

    if len(data) < 20:
        return {
            "total": 50,
            "flags": ["Insufficient clean liquidity history"],
            "summary": "Liquidity: insufficient clean data.",
            "metrics": {},
        }

    close = data["Close"]
    high = data["High"]
    low = data["Low"]
    volume = data["Volume"].clip(lower=0)

    price = _safe_float(close.iloc[-1], default=0.0)
    avg_vol = _safe_float(volume.rolling(20).mean().iloc[-1], default=0.0)
    today_vol = _safe_float(volume.iloc[-1], default=0.0)
    rel_vol = today_vol / avg_vol if avg_vol > 0 else 1.0

    dollar_vol = price * today_vol
    avg_dollar_vol = price * avg_vol

    recent_vol = _safe_float(volume.iloc[-5:].mean(), default=0.0)
    prior_vol = _safe_float(volume.iloc[-10:-5].mean(), default=0.0)
    vol_expansion = recent_vol / prior_vol if prior_vol > 0 else 1.0

    pre_vol = _safe_float(volume.iloc[-4:-1].mean(), default=0.0)
    vol_dryup = (avg_vol > 0) and (pre_vol / avg_vol < 0.70) and (rel_vol > 1.20)

    # OBV trend: accumulation if price-up days are carrying more volume.
    direction = np.sign(close.diff()).fillna(0)
    obv = (direction * volume).cumsum()
    obv_rising = bool(_safe_float(obv.iloc[-1]) > _safe_float(obv.iloc[-10])) if len(obv) >= 10 else False
    obv_20_delta = _safe_float(obv.iloc[-1] - obv.iloc[-20]) if len(obv) >= 20 else np.nan

    # Money flow / ADL / CMF.
    denom = (high - low).replace(0, np.nan)
    money_flow_multiplier = (((close - low) - (high - close)) / denom).replace([np.inf, -np.inf], np.nan).fillna(0)
    mfv = money_flow_multiplier * volume
    adl = mfv.cumsum()
    adl_rising = bool(_safe_float(adl.iloc[-1]) > _safe_float(adl.iloc[-10])) if len(adl) >= 10 else False

    cmf_series = mfv.rolling(20).sum() / volume.rolling(20).sum().replace(0, np.nan)
    cmf_val = _safe_float(cmf_series.iloc[-1], default=0.0)

    float_shares = _get_float_shares(fund)
    float_rotation = today_vol / float_shares if float_shares and float_shares > 0 else np.nan

    thin_liquidity = avg_dollar_vol < 5_000_000
    very_thin_liquidity = avg_dollar_vol < 1_000_000

    # We do not have bid/ask spread from OHLCV, so intraday range acts as an execution-risk proxy.
    spread_proxy = (high.iloc[-1] - low.iloc[-1]) / price if price > 0 else np.nan
    avg_spread_proxy_5d = _safe_float(((high - low) / close.replace(0, np.nan)).rolling(5).mean().iloc[-1], default=np.nan)

    metrics = {
        "rel_vol": rel_vol,
        "relative_volume": rel_vol,              # backward-compatible alias
        "today_volume": today_vol,
        "avg_volume_20d": avg_vol,
        "dollar_vol": dollar_vol,
        "dollar_volume": dollar_vol,             # backward-compatible alias
        "avg_dollar_vol": avg_dollar_vol,
        "vol_expansion": vol_expansion,
        "vol_dryup": bool(vol_dryup),
        "obv_rising": obv_rising,
        "obv_20_delta": obv_20_delta,
        "adl_rising": adl_rising,
        "cmf": cmf_val,
        "cmf20": cmf_val,                        # backward-compatible alias
        "float_rotation": float_rotation,
        "thin_liquidity": bool(thin_liquidity),
        "very_thin_liquidity": bool(very_thin_liquidity),
        "spread_proxy": spread_proxy,
        "avg_spread_proxy_5d": avg_spread_proxy_5d,
    }

    score = 50.0
    flags = []

    # Relative volume: confirms attention, but extreme volume can also mean crowded chase.
    if rel_vol > 3.0:
        score += 18
        flags.append(f"Very high relative volume: {rel_vol:.1f}x")
    elif rel_vol > 2.0:
        score += 15
        flags.append(f"High relative volume: {rel_vol:.1f}x")
    elif rel_vol > 1.3:
        score += 8
        flags.append(f"Above-normal relative volume: {rel_vol:.1f}x")
    elif rel_vol < 0.5:
        score -= 10
        flags.append("Very low volume day")

    # Volume trend.
    if vol_expansion > 1.5:
        score += 10
        flags.append("Volume expanding")
    elif vol_expansion < 0.7:
        score -= 5
        flags.append("Volume contracting")

    # Volume dry-up before expansion is often a constructive coil/base signal.
    if vol_dryup:
        score += 8
        flags.append("Volume dry-up before expansion — potential coil")

    # Accumulation / distribution.
    if obv_rising and adl_rising:
        score += 15
        flags.append("OBV + ADL rising — accumulation")
    elif obv_rising or adl_rising:
        score += 7
        flags.append("One accumulation measure improving")
    else:
        score -= 7
        flags.append("Distribution pattern in volume")

    # CMF confirmation.
    if cmf_val > 0.15:
        score += 8
        flags.append(f"Strong positive CMF: {cmf_val:.2f}")
    elif cmf_val > 0.05:
        score += 4
    elif cmf_val < -0.15:
        score -= 10
        flags.append(f"Strong negative CMF: {cmf_val:.2f}")
    elif cmf_val < -0.05:
        score -= 4

    # Float rotation: useful mainly for low-float momentum/squeeze names.
    if not np.isnan(float_rotation):
        if float_rotation > 1.0:
            score += 12
            flags.append(f"Full float rotation: {float_rotation:.0%} today")
        elif float_rotation > 0.30:
            score += 10
            flags.append(f"Large float rotation: {float_rotation:.0%} today")
        elif float_rotation < 0.02:
            score -= 5
            flags.append("Very low float turnover")

    # Execution quality / liquidity risk.
    if very_thin_liquidity:
        score -= 20
        flags.append("⚠️ Very low dollar volume (<$1M avg daily)")
    elif thin_liquidity:
        score -= 15
        flags.append("⚠️ Thin liquidity (<$5M avg daily)")
    elif avg_dollar_vol > 100_000_000:
        score += 5
        flags.append("Institutional-grade dollar liquidity")

    # Range-as-spread proxy: flags names where stops/slippage may be poor.
    if not np.isnan(avg_spread_proxy_5d):
        if avg_spread_proxy_5d > 0.10:
            score -= 12
            flags.append("⚠️ Very wide range/spread proxy — high slippage risk")
        elif avg_spread_proxy_5d > 0.06:
            score -= 6
            flags.append("Elevated range/spread proxy")
        elif avg_spread_proxy_5d < 0.03:
            score += 3

    parts = []
    if rel_vol > 1.5:
        parts.append("elevated relative volume")
    if vol_expansion > 1.5:
        parts.append("volume expansion")
    if obv_rising or adl_rising:
        parts.append("accumulation improving")
    if cmf_val < -0.05:
        parts.append("negative money flow")
    if thin_liquidity:
        parts.append("thin liquidity / execution risk")
    if not np.isnan(float_rotation) and float_rotation > 0.30:
        parts.append("meaningful float rotation")

    return {
        "total": clamp(score),
        "flags": flags,
        "metrics": metrics,
        "summary": "Liquidity: " + (", ".join(parts) if parts else "normal conditions") + ".",
    }


def liquidity_score(df: pd.DataFrame, info: Optional[dict] = None) -> Tuple[float, Dict[str, Any]]:
    """
    Backward-compatible wrapper used by app.py.

    Returns:
        score, metadata
    """
    result = analyze_liquidity(df, info)
    metrics = result.get("metrics", {}) or {}
    meta = dict(metrics)
    meta["liquidity_reasons"] = result.get("flags", [])
    meta["liquidity_summary"] = result.get("summary", "")
    meta["flags"] = result.get("flags", [])
    return result.get("total", 50), meta
