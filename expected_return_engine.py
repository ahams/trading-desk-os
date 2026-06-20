"""
expected_return_engine.py

Expected-return scenario engine for Trading Desk OS.

This converts the scanner's multi-engine reads into a probabilistic trade plan:
- bull/base/bear outcomes
- expected return and expected R multiple
- estimated hit probability
- entry/stop/targets and suggested risk budget

It is intentionally heuristic at first. Once signal_outcome_db.py has enough
history, use `calibrate_from_outcomes()` to adjust probabilities by real data.

Main public API:
    estimate_expected_return(ticker, df, scores, metas, regime_result=None, account_size=100000, risk_per_trade=0.005)
"""
from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

try:
    from utils import clamp
except Exception:
    def clamp(x, lo=0, hi=100):
        try:
            if pd.isna(x):
                return 50
            return max(lo, min(hi, float(x)))
        except Exception:
            return 50

logger = logging.getLogger("trading_desk.expected_return")


def _normalize(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.get_level_values(0)
    out.columns = [str(c).title() for c in out.columns]
    if "Adj Close" in out.columns and "Close" not in out.columns:
        out["Close"] = out["Adj Close"]
    return out.dropna()


def _atr(df: pd.DataFrame, n: int = 14) -> float:
    try:
        high, low, close = df["High"], df["Low"], df["Close"]
        prev_close = close.shift(1)
        tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        val = float(tr.rolling(n).mean().iloc[-1])
        if np.isnan(val) or val <= 0:
            return float((high.tail(n).max() - low.tail(n).min()) / max(1, n))
        return val
    except Exception:
        try:
            return float(df["Close"].pct_change().dropna().tail(20).std() * df["Close"].iloc[-1])
        except Exception:
            return 0.0


def _realized_vol(df: pd.DataFrame, n: int = 20) -> float:
    try:
        return float(df["Close"].pct_change().dropna().tail(n).std() * np.sqrt(252))
    except Exception:
        return 0.35


def _extract_score(scores: Dict[str, float], *names: str, default: float = 50.0) -> float:
    if not scores:
        return default
    lowered = {str(k).lower(): v for k, v in scores.items()}
    for name in names:
        if name in scores:
            return float(scores[name])
        if str(name).lower() in lowered:
            return float(lowered[str(name).lower()])
    return default


def _setup_bias(scores: Dict[str, float], metas: Dict[str, dict]) -> Tuple[str, float]:
    """Return directional setup and directional score."""
    final = _extract_score(scores, "final", "final_score", default=50)
    tech = _extract_score(scores, "technical", "technical_score", default=50)
    liq = _extract_score(scores, "liquidity", "liquidity_score", default=50)
    opt = _extract_score(scores, "options", "options_score", "options_volatility", default=50)
    game = _extract_score(scores, "game", "game_theory", "game_theory_score", default=50)
    catalyst = _extract_score(scores, "catalyst", "catalyst_score", default=50)
    theme = _extract_score(scores, "theme", "theme_score", default=50)
    expectation = _extract_score(scores, "expectation", "expectation_score", default=50)
    macro = _extract_score(scores, "macro", "cml_sml", "cml_sml_score", default=50)

    directional = np.average(
        [final, tech, liq, opt, game, catalyst, theme, expectation, macro],
        weights=[2.0, 1.5, 1.0, 1.0, 1.3, 0.8, 0.9, 1.2, 1.0],
    )

    if directional >= 65:
        setup = "LONG"
    elif directional <= 35:
        setup = "SHORT"
    else:
        setup = "WATCH"
    return setup, float(directional)


def estimate_trade_levels(df: pd.DataFrame, direction: str = "LONG") -> dict:
    """Estimate entry, stop and targets from current price and ATR."""
    df = _normalize(df)
    if df is None or len(df) < 20:
        return {"entry": None, "stop": None, "target1": None, "target2": None, "risk_reward": None}

    close = float(df["Close"].iloc[-1])
    atr = _atr(df)
    recent_high = float(df["High"].tail(20).max()) if "High" in df else close + atr
    recent_low = float(df["Low"].tail(20).min()) if "Low" in df else close - atr

    if direction == "SHORT":
        entry = close
        stop = min(close + 1.5 * atr, recent_high + 0.25 * atr)
        target1 = close - 2.0 * atr
        target2 = max(close - 3.5 * atr, recent_low - 0.5 * atr)
        risk = abs(stop - entry)
        reward = abs(entry - target2)
    else:
        entry = close
        stop = max(close - 1.5 * atr, recent_low - 0.25 * atr)
        target1 = close + 2.0 * atr
        target2 = min(close + 3.5 * atr, recent_high + 1.25 * atr)
        # If target2 got clipped too close in a strong breakout, force minimum R.
        if target2 <= target1:
            target2 = close + 3.5 * atr
        risk = abs(entry - stop)
        reward = abs(target2 - entry)

    rr = reward / risk if risk > 0 else None
    return {
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target1": round(target1, 2),
        "target2": round(target2, 2),
        "atr": round(atr, 3),
        "risk_reward": round(rr, 2) if rr is not None else None,
    }


def estimate_expected_return(
    ticker: str,
    df: pd.DataFrame,
    scores: Dict[str, float],
    metas: Optional[Dict[str, dict]] = None,
    regime_result: Optional[dict] = None,
    account_size: float = 100_000,
    risk_per_trade: float = 0.005,
    max_position_pct: float = 0.15,
    calibration: Optional[dict] = None,
) -> dict:
    """Create a probabilistic trade plan from model scores.

    scores can include any of: final, technical, liquidity, options, game,
    catalyst, theme, expectation, macro/cml_sml.
    metas can include detailed outputs from each engine.
    """
    metas = metas or {}
    df = _normalize(df)
    flags = []
    if df is None or len(df) < 60:
        return {
            "total": 50,
            "decision": "WATCH",
            "expected_return": 0.0,
            "expected_r": 0.0,
            "probability_win": 0.5,
            "flags": ["Insufficient data for expected-return model"],
            "metrics": {},
            "summary": "Expected return: insufficient data.",
        }

    direction, directional_score = _setup_bias(scores, metas)
    if direction == "WATCH":
        flags.append("No strong directional edge — classify as watchlist until price confirms")

    price = float(df["Close"].iloc[-1])
    atr_val = _atr(df)
    rv = _realized_vol(df)
    levels = estimate_trade_levels(df, "LONG" if direction != "SHORT" else "SHORT")

    # Raw win probability from score, then regime adjustments.
    p_win = 0.50 + (directional_score - 50) / 160.0
    if direction == "SHORT":
        p_win = 0.50 + (50 - directional_score) / 160.0

    regime = (regime_result or {}).get("regime", "CHOP")
    if direction == "LONG" and regime == "RISK_ON":
        p_win += 0.04; flags.append("Risk-on regime improves long expected value")
    elif direction == "LONG" and regime == "RISK_OFF":
        p_win -= 0.07; flags.append("Risk-off regime reduces long expected value")
    elif direction == "SHORT" and regime == "RISK_OFF":
        p_win += 0.04; flags.append("Risk-off regime improves short expected value")
    elif direction == "SHORT" and regime == "RISK_ON":
        p_win -= 0.05; flags.append("Risk-on regime reduces short expected value")
    elif regime == "CHOP":
        p_win -= 0.02

    # Calibration from historical outcomes if passed.
    if calibration:
        hist_p = calibration.get("win_rate")
        sample_n = calibration.get("sample_size", 0)
        if hist_p is not None and sample_n >= 20:
            weight = min(0.60, sample_n / 300.0)
            p_win = (1 - weight) * p_win + weight * float(hist_p)
            flags.append(f"Probability blended with historical outcome calibration n={sample_n}")

    p_win = float(np.clip(p_win, 0.35, 0.72))

    # Scenario returns: ATR-based and score-sensitive.
    atr_pct = atr_val / price if price > 0 else 0.03
    vol_floor = max(atr_pct, rv / np.sqrt(252) if rv else atr_pct, 0.015)
    edge_strength = abs(directional_score - 50) / 50

    bull_ret = min(0.35, 2.5 * vol_floor + 0.10 * edge_strength)
    base_ret = min(0.20, 1.2 * vol_floor + 0.04 * edge_strength)
    bear_ret = -min(0.20, 1.4 * vol_floor + 0.03 * (1 - edge_strength))

    if direction == "SHORT":
        # Expected return from short perspective: positive if price falls.
        bull_ret, bear_ret = abs(bear_ret), -abs(bull_ret)
        base_ret = abs(base_ret) * 0.75
    elif direction == "WATCH":
        bull_ret *= 0.45
        base_ret *= 0.20
        bear_ret *= 0.75

    # Three-scenario probability distribution.
    p_bull = p_win * 0.65
    p_base = 0.25 + max(0, p_win - 0.55) * 0.2
    p_bear = 1.0 - p_bull - p_base
    if p_bear < 0.10:
        p_bear = 0.10
        total = p_bull + p_base + p_bear
        p_bull, p_base, p_bear = p_bull/total, p_base/total, p_bear/total

    expected_return = p_bull * bull_ret + p_base * base_ret + p_bear * bear_ret

    # ------------------------------------------------------------
# Trade expectancy from actual trade plan
# ------------------------------------------------------------
    entry = levels.get("entry")
    stop = levels.get("stop")
    target2 = levels.get("target2")

    trade_expectancy_pct = None
    trade_expectancy_r = None
    reward_pct = None
    risk_pct = None

    try:
        if entry and stop and target2:
            if direction == "SHORT":
                risk_pct = abs(stop - entry) / entry
                reward_pct = abs(entry - target2) / entry
            else:
                risk_pct = abs(entry - stop) / entry
                reward_pct = abs(target2 - entry) / entry

            trade_expectancy_pct = (
                p_win * reward_pct
                - (1.0 - p_win) * risk_pct
            )

            trade_expectancy_r = (
                trade_expectancy_pct / risk_pct
                if risk_pct and risk_pct > 0
                else None
            )
    except Exception:
        pass
    
    risk_per_share = None
    shares = 0
    position_value = 0.0
    if levels.get("entry") and levels.get("stop"):
        risk_per_share = abs(levels["entry"] - levels["stop"])
        dollar_risk = account_size * risk_per_trade
        if risk_per_share > 0:
            shares_by_risk = int(dollar_risk / risk_per_share)
            shares_by_cap = int((account_size * max_position_pct) / price) if price > 0 else 0
            shares = max(0, min(shares_by_risk, shares_by_cap))
            position_value = shares * price

    expected_dollar = position_value * expected_return
    expected_r = None
    if risk_per_share and shares > 0:
        expected_r = expected_dollar / (risk_per_share * shares)

    ev_score = 50 + expected_return * 500 + (p_win - 0.5) * 50
    if expected_r is not None:
        ev_score += 8 * expected_r
    if levels.get("risk_reward") and levels["risk_reward"] >= 2.5:
        ev_score += 5
    elif levels.get("risk_reward") and levels["risk_reward"] < 1.5:
        ev_score -= 10

    total = clamp(ev_score)
    if expected_return > 0.04:
        flags.append("Positive expected value with meaningful upside")
    elif expected_return < 0:
        flags.append("Negative expected value — avoid or wait")

    decision = "WATCH"
    if direction == "LONG" and total >= 70 and expected_return > 0:
        decision = "STRONG_LONG"
    elif direction == "LONG" and total >= 58 and expected_return > 0:
        decision = "TACTICAL_LONG"
    elif direction == "SHORT" and total >= 70 and expected_return > 0:
        decision = "STRONG_SHORT"
    elif direction == "SHORT" and total >= 58 and expected_return > 0:
        decision = "TACTICAL_SHORT"
    elif total < 45:
        decision = "AVOID"

    metrics = {
        "directional_score": directional_score,
        "direction": direction,
        "price": price,
        "atr": atr_val,
        "atr_pct": atr_val / price if price else None,
        "realized_vol_20d": rv,
        "probability_win": p_win,
        "p_bull": p_bull,
        "p_base": p_base,
        "p_bear": p_bear,
        "bull_return": bull_ret,
        "base_return": base_ret,
        "bear_return": bear_ret,
        "expected_return": expected_return,
        "expected_r": expected_r,
        "expected_dollar": expected_dollar,
        "shares": shares,
        "position_value": position_value,
        "risk_per_share": risk_per_share,
        **levels,
        "reward_pct": reward_pct,
        "risk_pct": risk_pct,
        "trade_expectancy_pct": trade_expectancy_pct,
        "trade_expectancy_r": trade_expectancy_r,
    }

    summary = (
        f"Expected return read for {ticker}: {decision}. "
        f"EV {expected_return:.1%}, win probability {p_win:.0%}, "
        f"bull/base/bear {bull_ret:.1%}/{base_ret:.1%}/{bear_ret:.1%}. "
        f"Entry {levels.get('entry')}, stop {levels.get('stop')}, target2 {levels.get('target2')}."
    )

    return {
        "total": round(total, 1),
        "decision": decision,

        # old scenario expectancy
        "expected_return": round(expected_return, 4),
        "expected_r": round(expected_r, 2) if expected_r is not None else None,

        # new actual trade-plan expectancy
        "trade_expectancy_pct": round(trade_expectancy_pct, 4) if trade_expectancy_pct is not None else None,
        "trade_expectancy_r": round(trade_expectancy_r, 2) if trade_expectancy_r is not None else None,
        "reward_pct": round(reward_pct, 4) if reward_pct is not None else None,
        "risk_pct": round(risk_pct, 4) if risk_pct is not None else None,

        "probability_win": round(p_win, 3),
        "levels": levels,
        "position_size": {"shares": shares, "position_value": round(position_value, 2)},
        "flags": flags,
        "metrics": metrics,
        "summary": summary,
    }


def calibrate_from_outcomes(outcome_df: pd.DataFrame, filters: Optional[dict] = None) -> dict:
    """Produce simple calibration stats from signal_outcome_db exports.

    filters example: {"setup_type": "breakout", "regime": "RISK_ON"}
    """
    if outcome_df is None or outcome_df.empty:
        return {"sample_size": 0}
    df = outcome_df.copy()
    filters = filters or {}
    for col, val in filters.items():
        if col in df.columns and val is not None:
            df = df[df[col] == val]
    if df.empty:
        return {"sample_size": 0}
    if "realized_r" in df.columns:
        win = df["realized_r"].astype(float) > 0
        return {
            "sample_size": int(len(df)),
            "win_rate": float(win.mean()),
            "avg_r": float(df["realized_r"].mean()),
            "median_r": float(df["realized_r"].median()),
        }
    if "outcome" in df.columns:
        win = df["outcome"].astype(str).str.upper().str.contains("WIN|TARGET|PROFIT")
        return {"sample_size": int(len(df)), "win_rate": float(win.mean())}
    return {"sample_size": int(len(df))}
