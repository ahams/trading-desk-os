"""
Options Skew Trading Engine
---------------------------
Adds an options-expression layer. It does not replace directional scoring.
It answers:
    "If I want to express this view with options, is skew helping or hurting?"

Public API:
    skew_score(calls, puts, spot, directional_bias='long') -> (score, metadata)

Score interpretation depends on directional_bias:
    long  : high score means upside options expression is attractive/supportive.
    short : high score means downside options expression is attractive/supportive.
"""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pandas as pd

from utils import clamp


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    for c in ["strike", "impliedVolatility", "volume", "openInterest", "lastPrice", "bid", "ask"]:
        if c in out:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out.dropna(subset=["strike"])


def _nearest_iv(df: pd.DataFrame, strike: float) -> float:
    if df.empty or "impliedVolatility" not in df:
        return np.nan
    x = df.dropna(subset=["impliedVolatility"])
    if x.empty:
        return np.nan
    row = x.iloc[(x["strike"] - strike).abs().argsort()[:1]]
    return float(row["impliedVolatility"].iloc[0]) if len(row) else np.nan


def _sum_zone(df: pd.DataFrame, lo: float, hi: float, col: str) -> float:
    if df.empty or col not in df:
        return 0.0
    z = df[(df["strike"] >= lo) & (df["strike"] <= hi)]
    return float(z[col].fillna(0).sum())


def skew_score(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    spot: float,
    directional_bias: str = "long",
) -> Tuple[float, Dict]:
    calls = _prep(calls)
    puts = _prep(puts)
    if spot is None or spot <= 0 or calls.empty or puts.empty:
        return 50.0, {
            "skew_reasons": ["No reliable option chain for skew analysis"],
            "skew_read": "Skew unavailable.",
            "suggested_options_expression": "Use stock or avoid options until chain is available.",
        }

    bias = (directional_bias or "long").lower()
    atm = spot
    put_25 = spot * 0.95
    call_25 = spot * 1.05
    put_10 = spot * 0.90
    call_10 = spot * 1.10

    atm_call_iv = _nearest_iv(calls, atm)
    atm_put_iv = _nearest_iv(puts, atm)
    atm_iv = np.nanmean([atm_call_iv, atm_put_iv])
    put_25_iv = _nearest_iv(puts, put_25)
    call_25_iv = _nearest_iv(calls, call_25)
    put_10_iv = _nearest_iv(puts, put_10)
    call_10_iv = _nearest_iv(calls, call_10)

    put_skew_5 = put_25_iv - atm_iv if not np.isnan(put_25_iv) and not np.isnan(atm_iv) else np.nan
    call_skew_5 = call_25_iv - atm_iv if not np.isnan(call_25_iv) and not np.isnan(atm_iv) else np.nan
    risk_reversal_5 = call_25_iv - put_25_iv if not np.isnan(call_25_iv) and not np.isnan(put_25_iv) else np.nan
    wing_convexity = (np.nanmean([put_10_iv, call_10_iv]) - atm_iv) if not np.isnan(atm_iv) else np.nan

    call_vol_5_10 = _sum_zone(calls, spot * 1.03, spot * 1.10, "volume")
    put_vol_5_10 = _sum_zone(puts, spot * 0.90, spot * 0.97, "volume")
    call_oi_5_10 = _sum_zone(calls, spot * 1.03, spot * 1.10, "openInterest")
    put_oi_5_10 = _sum_zone(puts, spot * 0.90, spot * 0.97, "openInterest")

    call_pressure = call_vol_5_10 / (call_vol_5_10 + put_vol_5_10) if (call_vol_5_10 + put_vol_5_10) > 0 else 0.5
    oi_pressure = call_oi_5_10 / (call_oi_5_10 + put_oi_5_10) if (call_oi_5_10 + put_oi_5_10) > 0 else 0.5

    score = 50.0
    flags = []

    if "short" in bias or "bear" in bias:
        # For bearish trades, expensive puts penalize long-put ideas, but can favor put spreads.
        if not np.isnan(put_skew_5):
            if put_skew_5 > 0.10:
                score -= 10
                flags.append("Downside puts are expensive; prefer put spread or call credit spread")
            elif put_skew_5 < 0.02:
                score += 12
                flags.append("Downside puts are relatively cheap")
        if put_vol_5_10 > call_vol_5_10 * 1.5:
            score += 8
            flags.append("Bearish put demand confirms downside interest")
        suggested = "Put debit spread / call credit spread" if score >= 55 else "Avoid naked puts; consider defined-risk spread only"
    else:
        # For bullish trades, cheap calls + call demand are best. Expensive call skew means use spreads.
        if not np.isnan(call_skew_5):
            if call_skew_5 < 0.02:
                score += 12
                flags.append("Upside calls are not overpriced versus ATM IV")
            elif call_skew_5 > 0.10:
                score -= 8
                flags.append("Upside calls are expensive; prefer call spread")
        if not np.isnan(risk_reversal_5):
            if risk_reversal_5 > 0.03:
                score += 8
                flags.append("Call skew positive: market paying for upside convexity")
            elif risk_reversal_5 < -0.08:
                score -= 5
                flags.append("Put skew dominates; upside demand less obvious")
        if call_pressure > 0.65:
            score += 10
            flags.append("Call volume concentrated above spot")
        elif call_pressure < 0.35:
            score -= 8
            flags.append("Put volume dominates nearby wings")
        suggested = "Call debit spread / stock + call spread" if score >= 55 else "Stock preferred; avoid overpaying for calls"

    if not np.isnan(wing_convexity):
        if wing_convexity > 0.12:
            score -= 5
            flags.append("Wings are expensive; avoid lottery-ticket options")
        elif wing_convexity < 0.03:
            score += 5
            flags.append("Wings are relatively cheap")

    if not flags:
        flags.append("Skew is broadly neutral")

    read = (
        f"Skew: ATM IV {atm_iv:.1%}, 5% put skew {put_skew_5:.1%}, "
        f"5% call skew {call_skew_5:.1%}, risk reversal {risk_reversal_5:.1%}."
    )

    return clamp(score), {
        "skew_reasons": flags,
        "skew_read": read,
        "suggested_options_expression": suggested,
        "atm_iv": atm_iv,
        "put_skew_5pct": put_skew_5,
        "call_skew_5pct": call_skew_5,
        "risk_reversal_5pct": risk_reversal_5,
        "wing_convexity": wing_convexity,
        "call_pressure_5_10pct": call_pressure,
        "oi_pressure_5_10pct": oi_pressure,
    }
