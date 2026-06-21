"""
leadership_engine.py
Trading Desk OS - Market/Theme Leadership Engine

Purpose
-------
Answers: "Is this stock a leader in its theme/sector?"
This prevents AI-infrastructure leaders from being penalized just because they lack a fresh pattern today.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd

DEFAULT_THEME_BASKETS = {
    "AI Infrastructure": ["NVDA", "AVGO", "ANET", "MRVL", "AMD", "SMCI", "CRWV", "NBIS", "DELL", "VRT"],
    "Semiconductors": ["NVDA", "AVGO", "AMD", "MRVL", "TSM", "MU", "ARM", "ASML", "AMAT", "LRCX"],
    "NeoCloud": ["CRWV", "NBIS", "IREN", "CORZ", "WULF", "APLD", "IREN"],
    "Defense": ["LMT", "RTX", "NOC", "GD", "KTOS", "AVAV"],
    "Nuclear": ["CCJ", "CEG", "SMR", "OKLO", "BWXT", "LEU"],
}


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    try:
        if not np.isfinite(x): return 50.0
        return round(float(max(lo, min(hi, x))), 1)
    except Exception:
        return 50.0


def _ret(close: pd.Series, n: int) -> Optional[float]:
    try:
        c = pd.to_numeric(close, errors="coerce").dropna()
        if len(c) <= n: return None
        return float(c.iloc[-1] / c.iloc[-n - 1] - 1.0)
    except Exception:
        return None


def _safe_last(s: pd.Series, default=np.nan):
    try:
        v = pd.to_numeric(s, errors="coerce").dropna()
        return float(v.iloc[-1]) if len(v) else default
    except Exception:
        return default


def _rank_percentile(value: float, peers: List[float]) -> Optional[float]:
    vals = [x for x in peers if x is not None and np.isfinite(x)]
    if value is None or not np.isfinite(value) or len(vals) < 2:
        return None
    return float((sum(v <= value for v in vals)) / len(vals))


def infer_theme(ticker: str, data: Dict[str, Any]) -> str:
    theme = data.get("theme")
    if theme:
        return str(theme)
    t = ticker.upper()
    for name, basket in DEFAULT_THEME_BASKETS.items():
        if t in basket:
            return name
    return "General Market"


def analyze_leadership(ticker: str, data: Dict[str, Any]) -> Dict[str, Any]:
    df = data.get("ohlcv") or data.get("df")
    benchmark = data.get("benchmark")
    sector = data.get("sector")
    theme = infer_theme(ticker, data)

    if df is None or not isinstance(df, pd.DataFrame) or len(df) < 80:
        return {
            "engine": "leadership",
            "score": 50.0,
            "signal": "Insufficient Data",
            "confidence": 0.0,
            "summary": "Insufficient data for leadership analysis.",
            "flags": ["insufficient_data"],
            "metrics": {"theme": theme},
            "trade_impact": {"bias": "neutral", "position_adjustment": 0.5},
        }

    close = pd.to_numeric(df["Close"], errors="coerce")
    high = pd.to_numeric(df["High"], errors="coerce") if "High" in df else close
    volume = pd.to_numeric(df["Volume"], errors="coerce") if "Volume" in df else pd.Series(index=df.index, dtype=float)

    ret20 = _ret(close, 20); ret60 = _ret(close, 60); ret120 = _ret(close, 120)
    price = _safe_last(close)
    high_window = _safe_last(high.rolling(min(252, len(high))).max())
    distance_from_high = price / high_window - 1 if high_window and high_window > 0 else None

    rs20_spy = None; rs60_spy = None
    if isinstance(benchmark, pd.DataFrame) and "Close" in benchmark and len(benchmark) > 65:
        br20 = _ret(benchmark["Close"], 20); br60 = _ret(benchmark["Close"], 60)
        if ret20 is not None and br20 is not None: rs20_spy = ret20 - br20
        if ret60 is not None and br60 is not None: rs60_spy = ret60 - br60

    rs20_sector = None
    if isinstance(sector, pd.DataFrame) and "Close" in sector and len(sector) > 30:
        sr20 = _ret(sector["Close"], 20)
        if ret20 is not None and sr20 is not None: rs20_sector = ret20 - sr20

    # Optional peer returns from data provider. Format:
    # data["theme_peer_returns"] = {"NVDA": {"ret20": .1, "ret60": .2}, ...}
    peer_returns = data.get("theme_peer_returns") or {}
    peer20 = []
    peer60 = []
    if isinstance(peer_returns, dict):
        for _, vals in peer_returns.items():
            if isinstance(vals, dict):
                peer20.append(vals.get("ret20"))
                peer60.append(vals.get("ret60"))
    pctile20 = _rank_percentile(ret20, peer20) if peer20 else None
    pctile60 = _rank_percentile(ret60, peer60) if peer60 else None

    avg_vol20 = _safe_last(volume.rolling(20).mean())
    avg_vol60 = _safe_last(volume.rolling(60).mean())
    volume_trend = avg_vol20 / avg_vol60 if avg_vol20 and avg_vol60 and avg_vol60 > 0 else None

    score = 50.0
    flags = []

    if ret20 is not None:
        if ret20 > 0.18: score += 12; flags.append("Very strong 20-day return")
        elif ret20 > 0.08: score += 7; flags.append("Strong 20-day return")
        elif ret20 < -0.08: score -= 8; flags.append("Weak 20-day return")

    if ret60 is not None:
        if ret60 > 0.35: score += 16; flags.append("Very strong 60-day leadership")
        elif ret60 > 0.15: score += 9; flags.append("Strong 60-day leadership")
        elif ret60 < -0.12: score -= 10; flags.append("Weak 60-day trend")

    if ret120 is not None:
        if ret120 > 0.50: score += 12; flags.append("Major 6-month leadership")
        elif ret120 > 0.20: score += 6
        elif ret120 < -0.20: score -= 10; flags.append("Poor 6-month leadership")

    if rs20_spy is not None:
        if rs20_spy > 0.08: score += 10; flags.append("Outperforming SPY strongly")
        elif rs20_spy > 0.02: score += 5
        elif rs20_spy < -0.06: score -= 10; flags.append("Underperforming SPY")

    if rs60_spy is not None:
        if rs60_spy > 0.15: score += 10; flags.append("Strong 60-day RS vs SPY")
        elif rs60_spy < -0.10: score -= 10; flags.append("Weak 60-day RS vs SPY")

    if rs20_sector is not None:
        if rs20_sector > 0.05: score += 8; flags.append("Outperforming sector")
        elif rs20_sector < -0.05: score -= 8; flags.append("Lagging sector")

    if pctile20 is not None:
        if pctile20 >= 0.75: score += 10; flags.append("Top-quartile theme performer over 20 days")
        elif pctile20 <= 0.25: score -= 8; flags.append("Bottom-quartile theme performer over 20 days")

    if pctile60 is not None:
        if pctile60 >= 0.75: score += 8; flags.append("Top-quartile theme performer over 60 days")
        elif pctile60 <= 0.25: score -= 8; flags.append("Bottom-quartile theme performer over 60 days")

    if distance_from_high is not None:
        if distance_from_high > -0.06: score += 8; flags.append("Near high-window highs")
        elif distance_from_high < -0.25: score -= 10; flags.append("Far from highs")

    if volume_trend is not None:
        if volume_trend > 1.25: score += 5; flags.append("Volume participation rising")
        elif volume_trend < 0.75: score -= 3

    # Known theme membership gives some context, but not a free pass.
    if ticker.upper() in DEFAULT_THEME_BASKETS.get(theme, []):
        score += 5
        flags.append(f"Recognized member of {theme} theme")

    final = _clamp(score)
    if final >= 80:
        signal = "Market Leader"
    elif final >= 65:
        signal = "Leadership Candidate"
    elif final >= 45:
        signal = "Average / Watch"
    else:
        signal = "Laggard"

    summary = f"Leadership read: {signal} in {theme}. " + ("; ".join(flags[:5]) if flags else "No clear leadership edge.")

    return {
        "engine": "leadership",
        "score": final,
        "signal": signal,
        "confidence": 0.70,
        "summary": summary,
        "flags": flags,
        "metrics": {
            "theme": theme,
            "ret20": ret20,
            "ret60": ret60,
            "ret120": ret120,
            "rs20_vs_benchmark": rs20_spy,
            "rs60_vs_benchmark": rs60_spy,
            "rs20_vs_sector": rs20_sector,
            "theme_percentile_20d": pctile20,
            "theme_percentile_60d": pctile60,
            "distance_from_high": distance_from_high,
            "volume_trend_20v60": volume_trend,
        },
        "trade_impact": {
            "bias": "long" if final >= 65 else "neutral" if final >= 45 else "avoid",
            "position_adjustment": 1.2 if final >= 80 else 1.0 if final >= 65 else 0.75 if final >= 45 else 0.4,
        },
    }


def analyze(ticker: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return analyze_leadership(ticker, data)
