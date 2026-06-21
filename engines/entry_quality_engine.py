"""
entry_quality_engine.py
Trading Desk OS - Entry Quality Engine

Purpose
-------
Answers: "Is now the right place to enter?" independent of whether the stock is a leader.
A leader can have weak entry quality if extended, choppy, or lacking confirmation.
"""

from __future__ import annotations

from typing import Dict, Any
import numpy as np
import pandas as pd


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    try:
        if not np.isfinite(x): return 50.0
        return round(float(max(lo, min(hi, x))), 1)
    except Exception:
        return 50.0


def _ema(s: pd.Series, span: int) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").ewm(span=span, adjust=False).mean()


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    high = pd.to_numeric(df["High"], errors="coerce")
    low = pd.to_numeric(df["Low"], errors="coerce")
    close = pd.to_numeric(df["Close"], errors="coerce")
    prev = close.shift(1)
    tr = pd.concat([(high-low).abs(), (high-prev).abs(), (low-prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = pd.to_numeric(close, errors="coerce").diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = (-delta.clip(upper=0)).rolling(n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _safe(v, default=np.nan):
    try:
        if isinstance(v, pd.Series):
            s = pd.to_numeric(v, errors="coerce").dropna()
            return float(s.iloc[-1]) if len(s) else default
        val = float(v)
        return val if np.isfinite(val) else default
    except Exception:
        return default


def analyze_entry_quality(ticker: str, data: Dict[str, Any]) -> Dict[str, Any]:
    df = data.get("ohlcv") or data.get("df")
    if df is None or not isinstance(df, pd.DataFrame) or len(df) < 60:
        return {
            "engine": "entry_quality",
            "score": 50.0,
            "signal": "Insufficient Data",
            "confidence": 0.0,
            "summary": "Insufficient OHLCV history for entry quality analysis.",
            "flags": ["insufficient_data"],
            "metrics": {},
            "trade_impact": {"bias": "neutral", "position_adjustment": 0.5},
        }

    close = pd.to_numeric(df["Close"], errors="coerce")
    high = pd.to_numeric(df["High"], errors="coerce")
    low = pd.to_numeric(df["Low"], errors="coerce")
    volume = pd.to_numeric(df["Volume"], errors="coerce") if "Volume" in df else pd.Series(index=df.index, dtype=float)

    price = _safe(close)
    ema8 = _ema(close, 8); ema20 = _ema(close, 20); ema50 = _ema(close, 50)
    e8, e20, e50 = _safe(ema8), _safe(ema20), _safe(ema50)
    atr = _atr(df, 14); atrv = _safe(atr)
    rsi = _rsi(close, 14); rsiv = _safe(rsi)

    # Setup detection
    prior_20_high = _safe(high.shift(1).rolling(20).max())
    prior_55_high = _safe(high.shift(1).rolling(55).max())
    prior_20_low = _safe(low.shift(1).rolling(20).min())

    breakout_20 = np.isfinite(prior_20_high) and price > prior_20_high
    breakout_55 = np.isfinite(prior_55_high) and price > prior_55_high

    dist_ema20_atr = (price - e20) / atrv if np.isfinite(price) and np.isfinite(e20) and atrv and atrv > 0 else np.nan
    dist_ema50_atr = (price - e50) / atrv if np.isfinite(price) and np.isfinite(e50) and atrv and atrv > 0 else np.nan

    pullback_to_ema20 = np.isfinite(dist_ema20_atr) and -0.25 <= dist_ema20_atr <= 0.75 and price > e50
    pullback_to_ema50 = np.isfinite(dist_ema50_atr) and -0.25 <= dist_ema50_atr <= 0.75
    extended = np.isfinite(dist_ema20_atr) and dist_ema20_atr > 2.5
    deeply_below_ema20 = np.isfinite(dist_ema20_atr) and dist_ema20_atr < -1.5

    # Bollinger/Keltner squeeze proxy
    ma20 = close.rolling(20).mean()
    sd20 = close.rolling(20).std()
    bb_width = ((ma20 + 2*sd20) - (ma20 - 2*sd20)) / ma20.replace(0, np.nan)
    bb_width_pctile = np.nan
    try:
        hist = pd.to_numeric(bb_width, errors="coerce").dropna()
        if len(hist) > 30:
            bb_width_pctile = float((hist <= hist.iloc[-1]).mean())
    except Exception:
        pass
    squeeze_like = np.isfinite(bb_width_pctile) and bb_width_pctile < 0.25

    avg_vol20 = _safe(volume.rolling(20).mean())
    today_vol = _safe(volume)
    rel_vol = today_vol / avg_vol20 if avg_vol20 and avg_vol20 > 0 else np.nan
    volume_confirms = np.isfinite(rel_vol) and rel_vol > 1.25

    # Risk/reward proxy to latest range
    recent_low = _safe(low.rolling(10).min())
    stop_proxy = min(e20 if np.isfinite(e20) else price, recent_low if np.isfinite(recent_low) else price)
    risk = price - stop_proxy if np.isfinite(price) and np.isfinite(stop_proxy) else np.nan
    target_proxy = prior_55_high + 2 * atrv if np.isfinite(prior_55_high) and np.isfinite(atrv) else np.nan
    reward = target_proxy - price if np.isfinite(target_proxy) and np.isfinite(price) else np.nan
    rr_proxy = reward / risk if np.isfinite(reward) and np.isfinite(risk) and risk > 0 else np.nan

    score = 50.0
    flags = []

    if breakout_55:
        score += 20; flags.append("55-day breakout")
    elif breakout_20:
        score += 14; flags.append("20-day breakout")

    if pullback_to_ema20:
        score += 18; flags.append("Buyable pullback/reclaim near EMA20")
    elif pullback_to_ema50:
        score += 12; flags.append("Pullback near EMA50")

    if squeeze_like:
        score += 8; flags.append("Volatility compression / squeeze-like setup")

    if volume_confirms:
        score += 10; flags.append(f"Volume confirmation: {rel_vol:.1f}x")
    elif np.isfinite(rel_vol) and rel_vol < 0.7:
        score -= 6; flags.append("Weak volume confirmation")

    if np.isfinite(rsiv):
        if 45 <= rsiv <= 65:
            score += 6; flags.append("RSI in constructive zone")
        elif rsiv > 78:
            score -= 8; flags.append("RSI extended/overheated")
        elif rsiv < 35:
            score -= 6; flags.append("RSI weak")

    if extended:
        score -= 18; flags.append("Extended above EMA20; poor fresh entry")
    if deeply_below_ema20:
        score -= 10; flags.append("Below EMA20 by >1.5 ATR")

    if np.isfinite(rr_proxy):
        if rr_proxy >= 3:
            score += 8; flags.append("Risk/reward proxy attractive")
        elif rr_proxy < 1.2:
            score -= 10; flags.append("Risk/reward proxy unattractive")

    final = _clamp(score)
    if final >= 75:
        signal = "Clean Entry"
    elif final >= 60:
        signal = "Tradable Entry"
    elif final >= 45:
        signal = "Watch Entry"
    else:
        signal = "Poor Entry"

    summary = f"Entry quality: {signal}. " + ("; ".join(flags[:5]) if flags else "No clean entry trigger.")
    return {
        "engine": "entry_quality",
        "score": final,
        "signal": signal,
        "confidence": 0.72,
        "summary": summary,
        "flags": flags,
        "metrics": {
            "price": price,
            "ema8": e8,
            "ema20": e20,
            "ema50": e50,
            "atr14": atrv,
            "rsi14": rsiv,
            "breakout_20": breakout_20,
            "breakout_55": breakout_55,
            "pullback_to_ema20": pullback_to_ema20,
            "pullback_to_ema50": pullback_to_ema50,
            "dist_ema20_atr": dist_ema20_atr,
            "dist_ema50_atr": dist_ema50_atr,
            "extended": extended,
            "relative_volume": rel_vol,
            "squeeze_like": squeeze_like,
            "risk_reward_proxy": rr_proxy,
        },
        "trade_impact": {
            "bias": "long" if final >= 60 else "neutral" if final >= 45 else "wait",
            "position_adjustment": 1.0 if final >= 75 else 0.8 if final >= 60 else 0.5 if final >= 45 else 0.25,
        },
    }


def analyze(ticker: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return analyze_entry_quality(ticker, data)
