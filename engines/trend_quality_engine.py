"""
trend_quality_engine.py
Trading Desk OS - Trend Quality Engine

Purpose
-------
Separates "is this a strong stock/trend?" from "is today the right entry?".
This fixes cases like MRVL/NVDA/AVGO where the stock can be a leadership name
but not currently showing a clean pullback/breakout entry.

Input contract
--------------
analyze_trend_quality(ticker, data)

data can contain:
    data["ohlcv"]        -> pd.DataFrame with Open/High/Low/Close/Volume
    data["benchmark"]    -> optional pd.DataFrame, e.g. SPY/QQQ OHLCV
    data["sector"]       -> optional pd.DataFrame sector ETF OHLCV

Output contract
---------------
{
  "engine": "trend_quality",
  "score": 0-100,
  "signal": "Strong Trend" | "Constructive" | "Neutral" | "Weak Trend",
  "summary": str,
  "flags": list[str],
  "metrics": dict,
  "trade_impact": dict
}
"""

from __future__ import annotations

from typing import Dict, Any, Optional
import numpy as np
import pandas as pd


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    try:
        if not np.isfinite(x):
            return 50.0
        return round(float(max(lo, min(hi, x))), 1)
    except Exception:
        return 50.0


def _ema(s: pd.Series, span: int) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").ewm(span=span, adjust=False).mean()


def _safe_last(s: pd.Series, default: float = np.nan) -> float:
    try:
        v = pd.to_numeric(s, errors="coerce").dropna()
        if v.empty:
            return default
        return float(v.iloc[-1])
    except Exception:
        return default


def _ret(close: pd.Series, n: int) -> Optional[float]:
    try:
        c = pd.to_numeric(close, errors="coerce").dropna()
        if len(c) <= n:
            return None
        return float(c.iloc[-1] / c.iloc[-n - 1] - 1.0)
    except Exception:
        return None


def _slope_pct(series: pd.Series, n: int = 20) -> Optional[float]:
    try:
        s = pd.to_numeric(series, errors="coerce").dropna()
        if len(s) <= n or s.iloc[-n - 1] == 0:
            return None
        return float(s.iloc[-1] / s.iloc[-n - 1] - 1.0)
    except Exception:
        return None


def analyze_trend_quality(ticker: str, data: Dict[str, Any]) -> Dict[str, Any]:
    df = data.get("ohlcv") or data.get("df")
    benchmark = data.get("benchmark")
    sector = data.get("sector")

    if df is None or not isinstance(df, pd.DataFrame) or len(df) < 80:
        return {
            "engine": "trend_quality",
            "score": 50.0,
            "signal": "Insufficient Data",
            "confidence": 0.0,
            "summary": "Insufficient OHLCV history for trend quality analysis.",
            "flags": ["insufficient_data"],
            "metrics": {},
            "trade_impact": {"bias": "neutral", "position_adjustment": 0.5},
        }

    close = pd.to_numeric(df["Close"], errors="coerce")
    high = pd.to_numeric(df["High"], errors="coerce") if "High" in df else close
    price = _safe_last(close)

    ema20 = _ema(close, 20)
    ema50 = _ema(close, 50)
    ema200 = _ema(close, 200) if len(close) >= 200 else _ema(close, min(100, len(close)//2))

    e20, e50, e200 = _safe_last(ema20), _safe_last(ema50), _safe_last(ema200)
    ema_stack_bull = price > e20 > e50 > e200 if all(np.isfinite([price, e20, e50, e200])) else False
    above_20 = price > e20 if np.isfinite(e20) else False
    above_50 = price > e50 if np.isfinite(e50) else False
    above_200 = price > e200 if np.isfinite(e200) else False

    ema20_slope = _slope_pct(ema20, 20)
    ema50_slope = _slope_pct(ema50, 20)
    ema200_slope = _slope_pct(ema200, 50)

    ret20 = _ret(close, 20)
    ret60 = _ret(close, 60)
    ret120 = _ret(close, 120)

    high_52w = _safe_last(high.rolling(min(252, len(high))).max())
    distance_from_high = (price / high_52w - 1.0) if high_52w and high_52w > 0 else None
    near_high = distance_from_high is not None and distance_from_high > -0.08

    # Relative strength vs benchmark/sector where available
    rs20_bench = None
    rs60_bench = None
    if isinstance(benchmark, pd.DataFrame) and "Close" in benchmark and len(benchmark) > 65:
        br20 = _ret(benchmark["Close"], 20)
        br60 = _ret(benchmark["Close"], 60)
        if ret20 is not None and br20 is not None:
            rs20_bench = ret20 - br20
        if ret60 is not None and br60 is not None:
            rs60_bench = ret60 - br60

    rs20_sector = None
    if isinstance(sector, pd.DataFrame) and "Close" in sector and len(sector) > 30:
        sr20 = _ret(sector["Close"], 20)
        if ret20 is not None and sr20 is not None:
            rs20_sector = ret20 - sr20

    score = 50.0
    flags = []

    if ema_stack_bull:
        score += 25
        flags.append("Bullish EMA stack: price > EMA20 > EMA50 > long EMA")
    else:
        if above_20: score += 5
        if above_50: score += 7
        if above_200: score += 8
        if not above_50: flags.append("Price below EMA50")

    if ema20_slope is not None:
        if ema20_slope > 0.04: score += 8; flags.append("EMA20 rising strongly")
        elif ema20_slope > 0.0: score += 4
        else: score -= 6; flags.append("EMA20 slope negative")

    if ema50_slope is not None:
        if ema50_slope > 0.06: score += 10; flags.append("EMA50 rising strongly")
        elif ema50_slope > 0.0: score += 5
        else: score -= 8; flags.append("EMA50 slope negative")

    if ema200_slope is not None:
        if ema200_slope > 0.05: score += 6
        elif ema200_slope < 0: score -= 6; flags.append("Long-term trend slope negative")

    if ret20 is not None:
        if ret20 > 0.15: score += 8; flags.append("Strong 20-day momentum")
        elif ret20 > 0.05: score += 4
        elif ret20 < -0.08: score -= 8; flags.append("Weak 20-day momentum")

    if ret60 is not None:
        if ret60 > 0.25: score += 10; flags.append("Strong 60-day trend")
        elif ret60 > 0.10: score += 5
        elif ret60 < -0.12: score -= 10; flags.append("Weak 60-day trend")

    if rs20_bench is not None:
        if rs20_bench > 0.08: score += 8; flags.append("Outperforming benchmark over 20 days")
        elif rs20_bench > 0.02: score += 4
        elif rs20_bench < -0.05: score -= 8; flags.append("Underperforming benchmark over 20 days")

    if rs60_bench is not None:
        if rs60_bench > 0.12: score += 8; flags.append("Outperforming benchmark over 60 days")
        elif rs60_bench < -0.08: score -= 8; flags.append("Underperforming benchmark over 60 days")

    if rs20_sector is not None:
        if rs20_sector > 0.05: score += 5; flags.append("Outperforming sector ETF")
        elif rs20_sector < -0.05: score -= 5; flags.append("Lagging sector ETF")

    if near_high:
        score += 6
        flags.append("Trading near 52-week/high-window highs")
    elif distance_from_high is not None and distance_from_high < -0.25:
        score -= 10
        flags.append("Far below high-window highs")

    final = _clamp(score)
    if final >= 80:
        signal = "Strong Trend"
    elif final >= 65:
        signal = "Constructive Trend"
    elif final >= 45:
        signal = "Neutral Trend"
    else:
        signal = "Weak Trend"

    summary = f"Trend quality: {signal}. " + ("; ".join(flags[:5]) if flags else "No dominant trend edge.")

    return {
        "engine": "trend_quality",
        "score": final,
        "signal": signal,
        "confidence": 0.75,
        "summary": summary,
        "flags": flags,
        "metrics": {
            "price": price,
            "ema20": e20,
            "ema50": e50,
            "ema200_or_long": e200,
            "ema_stack_bull": ema_stack_bull,
            "above_20": above_20,
            "above_50": above_50,
            "above_200": above_200,
            "ema20_slope_20d": ema20_slope,
            "ema50_slope_20d": ema50_slope,
            "ema200_slope_50d": ema200_slope,
            "ret20": ret20,
            "ret60": ret60,
            "ret120": ret120,
            "distance_from_high": distance_from_high,
            "rs20_vs_benchmark": rs20_bench,
            "rs60_vs_benchmark": rs60_bench,
            "rs20_vs_sector": rs20_sector,
        },
        "trade_impact": {
            "bias": "long" if final >= 65 else "short" if final < 40 else "neutral",
            "position_adjustment": 1.15 if final >= 80 else 1.0 if final >= 65 else 0.65 if final < 45 else 0.85,
        },
    }


# Alias for registry/plugin compatibility
def analyze(ticker: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return analyze_trend_quality(ticker, data)
