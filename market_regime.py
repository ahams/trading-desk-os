"""
market_regime.py

Trading Desk OS market-regime engine.

Purpose
-------
Classify the tape into regimes that should change how much we trust
breakouts, pullbacks, short squeezes, mean reversion, and volatility trades.

Free-data default uses yfinance-compatible OHLCV DataFrames. You can pass a
preloaded dictionary of market data from your app:

    market_data = {
        "SPY": spy_df,
        "QQQ": qqq_df,
        "IWM": iwm_df,
        "VIX": vix_df,      # ^VIX from yfinance also accepted
        "TLT": tlt_df,
        "HYG": hyg_df,
        "LQD": lqd_df,
        "DXY": dxy_df,      # DX-Y.NYB or UUP fallback
        "TNX": tnx_df,      # ^TNX from yfinance
    }

Main public API:
    analyze_market_regime(market_data) -> dict

Return contract:
    {
      "regime": "RISK_ON" | "RISK_OFF" | "CHOP" | "VOL_EXPANSION" | "VOL_COMPRESSION",
      "total": 0-100 risk appetite score,
      "risk_on_probability": ..., "risk_off_probability": ..., "chop_probability": ...,
      "volatility_regime": ...,
      "flags": [...], "metrics": {...}, "summary": "..."
    }
"""
from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

try:
    from utils import clamp
except Exception:  # standalone fallback
    def clamp(x, lo=0, hi=100):
        try:
            if pd.isna(x):
                return 50
            return max(lo, min(hi, float(x)))
        except Exception:
            return 50

logger = logging.getLogger("trading_desk.market_regime")


def _get_df(market_data: Dict[str, pd.DataFrame], *keys: str) -> Optional[pd.DataFrame]:
    if not market_data:
        return None
    lowered = {str(k).upper(): v for k, v in market_data.items()}
    aliases = {
        "VIX": ["VIX", "^VIX"],
        "TNX": ["TNX", "^TNX", "10Y"],
        "DXY": ["DXY", "DX-Y.NYB", "UUP"],
        "MOVE": ["MOVE", "^MOVE"],
        "VVIX": ["VVIX", "^VVIX"],
    }
    candidates = []
    for k in keys:
        candidates.append(k)
        candidates.extend(aliases.get(str(k).upper(), []))
    for k in candidates:
        df = lowered.get(str(k).upper())
        if isinstance(df, pd.DataFrame) and not df.empty:
            return _normalize_ohlcv(df)
    return None


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.get_level_values(0)
    out.columns = [str(c).title() for c in out.columns]
    if "Adj Close" in out.columns and "Close" not in out.columns:
        out["Close"] = out["Adj Close"]
    return out.dropna(how="all")


def _last_close(df: Optional[pd.DataFrame]) -> Optional[float]:
    try:
        return float(df["Close"].dropna().iloc[-1])
    except Exception:
        return None


def _ret(df: Optional[pd.DataFrame], n: int) -> Optional[float]:
    try:
        c = df["Close"].dropna()
        if len(c) <= n:
            return None
        return float(c.iloc[-1] / c.iloc[-n - 1] - 1.0)
    except Exception:
        return None


def _sma_slope(df: Optional[pd.DataFrame], fast: int = 20, slow: int = 50) -> Tuple[Optional[bool], Optional[float]]:
    try:
        c = df["Close"].dropna()
        if len(c) < slow + 5:
            return None, None
        fast_ma = c.rolling(fast).mean()
        slow_ma = c.rolling(slow).mean()
        spread = float(fast_ma.iloc[-1] / slow_ma.iloc[-1] - 1.0)
        return bool(fast_ma.iloc[-1] > slow_ma.iloc[-1] and c.iloc[-1] > slow_ma.iloc[-1]), spread
    except Exception:
        return None, None


def _realized_vol(df: Optional[pd.DataFrame], n: int = 20) -> Optional[float]:
    try:
        c = df["Close"].dropna()
        if len(c) < n + 2:
            return None
        return float(c.pct_change().dropna().tail(n).std() * np.sqrt(252))
    except Exception:
        return None


def _score_component(condition: Optional[bool], pos: float, neg: float = None) -> float:
    if condition is None:
        return 0.0
    if neg is None:
        neg = -pos
    return pos if condition else neg


def analyze_market_regime(
    market_data: Dict[str, pd.DataFrame],
    risk_free_rate: float = 0.045,
    lookback_short: int = 5,
    lookback_mid: int = 20,
) -> dict:
    """Classify broad market tape and return probabilities/scores.

    Parameters
    ----------
    market_data:
        Dict of OHLCV DataFrames keyed by symbol. At minimum pass SPY and QQQ.
    risk_free_rate:
        Annualized risk-free rate used for summary context only.
    """
    flags = []
    metrics = {}

    spy = _get_df(market_data, "SPY")
    qqq = _get_df(market_data, "QQQ")
    iwm = _get_df(market_data, "IWM")
    vix = _get_df(market_data, "VIX", "^VIX")
    tlt = _get_df(market_data, "TLT")
    hyg = _get_df(market_data, "HYG")
    lqd = _get_df(market_data, "LQD")
    dxy = _get_df(market_data, "DXY", "UUP")
    tnx = _get_df(market_data, "TNX", "^TNX")
    move = _get_df(market_data, "MOVE", "^MOVE")
    vvix = _get_df(market_data, "VVIX", "^VVIX")

    # Equity trend and breadth proxies
    spy_up, spy_ma_spread = _sma_slope(spy)
    qqq_up, qqq_ma_spread = _sma_slope(qqq)
    iwm_up, iwm_ma_spread = _sma_slope(iwm)
    spy_5d, spy_20d = _ret(spy, lookback_short), _ret(spy, lookback_mid)
    qqq_20d = _ret(qqq, lookback_mid)
    iwm_20d = _ret(iwm, lookback_mid)

    # Credit/liquidity proxies: HYG vs LQD and TLT trend.
    hyg_lqd_ratio = None
    hyg_lqd_20d = None
    try:
        ratio = (hyg["Close"].dropna() / lqd["Close"].dropna()).dropna()
        if len(ratio) > 25:
            hyg_lqd_ratio = float(ratio.iloc[-1])
            hyg_lqd_20d = float(ratio.iloc[-1] / ratio.iloc[-21] - 1.0)
    except Exception:
        pass

    vix_level = _last_close(vix)
    vvix_level = _last_close(vvix)
    move_level = _last_close(move)
    tnx_level = _last_close(tnx)
    dxy_20d = _ret(dxy, lookback_mid)
    tlt_20d = _ret(tlt, lookback_mid)
    spy_rvol = _realized_vol(spy)

    metrics.update({
        "spy_5d_return": spy_5d,
        "spy_20d_return": spy_20d,
        "qqq_20d_return": qqq_20d,
        "iwm_20d_return": iwm_20d,
        "spy_trend_up": spy_up,
        "qqq_trend_up": qqq_up,
        "iwm_trend_up": iwm_up,
        "spy_ma_spread": spy_ma_spread,
        "qqq_ma_spread": qqq_ma_spread,
        "iwm_ma_spread": iwm_ma_spread,
        "vix": vix_level,
        "vvix": vvix_level,
        "move": move_level,
        "tnx": tnx_level,
        "dxy_20d_return": dxy_20d,
        "tlt_20d_return": tlt_20d,
        "hyg_lqd_ratio": hyg_lqd_ratio,
        "hyg_lqd_20d_return": hyg_lqd_20d,
        "spy_realized_vol_20d": spy_rvol,
        "risk_free_rate": risk_free_rate,
    })

    # Risk appetite composite: 0 bearish, 100 bullish.
    score = 50.0
    score += _score_component(spy_up, 12)
    score += _score_component(qqq_up, 10)
    score += _score_component(iwm_up, 6)

    if spy_20d is not None:
        score += clamp(spy_20d * 300, -10, 10)
        if spy_20d > 0.03:
            flags.append("SPY 20-day trend is risk-on")
        elif spy_20d < -0.03:
            flags.append("SPY 20-day trend is risk-off")

    if qqq_20d is not None and spy_20d is not None:
        tech_leadership = qqq_20d - spy_20d
        metrics["tech_leadership_20d"] = tech_leadership
        if tech_leadership > 0.015:
            score += 6
            flags.append("QQQ leading SPY — growth leadership")
        elif tech_leadership < -0.015:
            score -= 6
            flags.append("QQQ lagging SPY — growth under pressure")

    if iwm_20d is not None and spy_20d is not None:
        smallcap_breadth = iwm_20d - spy_20d
        metrics["smallcap_breadth_20d"] = smallcap_breadth
        if smallcap_breadth > 0.01:
            score += 5
            flags.append("IWM leading — breadth improving")
        elif smallcap_breadth < -0.02:
            score -= 7
            flags.append("IWM lagging — narrow/fragile tape")

    if vix_level is not None:
        if vix_level < 14:
            score += 8
            flags.append("Low VIX — vol compression/risk appetite")
        elif vix_level < 20:
            score += 2
        elif vix_level > 30:
            score -= 20
            flags.append("VIX stress regime")
        elif vix_level > 22:
            score -= 10
            flags.append("Elevated VIX")

    if vvix_level is not None:
        if vvix_level > 115:
            score -= 8
            flags.append("VVIX elevated — vol-of-vol stress")
        elif vvix_level < 85:
            score += 4

    if move_level is not None:
        if move_level > 130:
            score -= 8
            flags.append("MOVE elevated — rates volatility stress")
        elif move_level < 95:
            score += 3

    if hyg_lqd_20d is not None:
        if hyg_lqd_20d > 0.01:
            score += 8
            flags.append("Credit risk appetite improving")
        elif hyg_lqd_20d < -0.01:
            score -= 10
            flags.append("Credit spreads/liquidity proxy deteriorating")

    if dxy_20d is not None:
        if dxy_20d > 0.03:
            score -= 5
            flags.append("Strong USD pressure")
        elif dxy_20d < -0.02:
            score += 3

    if tnx_level is not None:
        # yfinance ^TNX is often 10x yield, e.g. 45 = 4.5%.
        yld = tnx_level / 10 if tnx_level > 1 else tnx_level
        metrics["ten_year_yield_pct"] = yld
        if yld > 4.75:
            score -= 6
            flags.append("10Y yield elevated — duration/growth headwind")
        elif yld < 4.0:
            score += 3

    score = clamp(score)

    # Convert to rough probabilities. This is intentionally heuristic and stable.
    risk_on_prob = clamp(score, 0, 100) / 100
    risk_off_prob = clamp(100 - score, 0, 100) / 100
    chop_prob = max(0.0, 1.0 - abs(score - 50) / 50)
    # Normalize just risk_on/off/chop for display.
    total_p = risk_on_prob + risk_off_prob + chop_prob
    if total_p > 0:
        risk_on_prob /= total_p
        risk_off_prob /= total_p
        chop_prob /= total_p

    # Vol regime classification separate from direction.
    if vix_level is None and spy_rvol is None:
        vol_regime = "UNKNOWN"
    elif (vix_level is not None and vix_level > 22) or (spy_rvol is not None and spy_rvol > 0.25):
        vol_regime = "VOL_EXPANSION"
    elif (vix_level is not None and vix_level < 15) and (spy_rvol is not None and spy_rvol < 0.16):
        vol_regime = "VOL_COMPRESSION"
    else:
        vol_regime = "NORMAL_VOL"

    if score >= 65:
        regime = "RISK_ON"
    elif score <= 35:
        regime = "RISK_OFF"
    elif vol_regime == "VOL_EXPANSION":
        regime = "VOL_EXPANSION"
    elif vol_regime == "VOL_COMPRESSION":
        regime = "VOL_COMPRESSION"
    else:
        regime = "CHOP"

    if not flags:
        flags.append("Mixed regime inputs — no dominant macro tape signal")

    summary = (
        f"Market regime: {regime}. Risk appetite score {score:.0f}/100. "
        f"Volatility regime: {vol_regime}. "
        f"Key read: {', '.join(flags[:3])}."
    )

    return {
        "regime": regime,
        "total": round(score, 1),
        "risk_on_probability": round(risk_on_prob, 3),
        "risk_off_probability": round(risk_off_prob, 3),
        "chop_probability": round(chop_prob, 3),
        "volatility_regime": vol_regime,
        "flags": flags,
        "metrics": metrics,
        "summary": summary,
    }


def regime_adjustment_multiplier(regime_result: dict, setup_type: str = "breakout") -> float:
    """Return a multiplier to apply to strategy scores by regime.

    Example usage:
        adjusted_technical = technical_score * regime_adjustment_multiplier(regime, setup_type)
    """
    regime = (regime_result or {}).get("regime", "CHOP")
    vol = (regime_result or {}).get("volatility_regime", "NORMAL_VOL")
    setup = str(setup_type or "").lower()

    mult = 1.0
    if regime == "RISK_ON":
        if any(x in setup for x in ["breakout", "momentum", "gap", "squeeze"]):
            mult += 0.10
        if "short" in setup or "mean reversion short" in setup:
            mult -= 0.07
    elif regime == "RISK_OFF":
        if "short" in setup or "breakdown" in setup:
            mult += 0.10
        if any(x in setup for x in ["breakout", "gap-and-go", "momentum long"]):
            mult -= 0.12
    elif regime == "CHOP":
        if any(x in setup for x in ["mean", "pullback", "failed breakdown", "support"]):
            mult += 0.05
        if any(x in setup for x in ["breakout", "gap"]):
            mult -= 0.08

    if vol == "VOL_EXPANSION":
        if any(x in setup for x in ["squeeze", "options", "gamma"]):
            mult += 0.05
        mult -= 0.03  # wider stops / execution risk
    elif vol == "VOL_COMPRESSION":
        if any(x in setup for x in ["squeeze", "breakout"]):
            mult += 0.04

    return float(np.clip(mult, 0.75, 1.25))
