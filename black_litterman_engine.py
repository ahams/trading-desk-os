"""
black_litterman_engine.py

Portfolio-level Bayesian allocation engine for the Pro Stock Decision App.

Use case
--------
The scanner ranks individual opportunities. Black-Litterman converts those
opportunities into a diversified portfolio/risk-budget recommendation.

Prior: market-cap weights or equal weights.
Views: scanner/game-theory/expectation/CML-SML scores transformed into annual
       active-return views with confidence levels.
Posterior: stable expected returns and suggested long-only weights.

This is not a guarantee of returns. It is a disciplined way to size conviction
without letting a noisy optimizer allocate 100% to one name.
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("trading_desk.black_litterman")

TRADING_DAYS = 252


def _safe_float(x, default=np.nan):
    try:
        if x is None:
            return default
        val = float(x)
        return val if np.isfinite(val) else default
    except Exception:
        return default


def _annualized_cov(price_map: Dict[str, pd.DataFrame]) -> Tuple[List[str], pd.DataFrame]:
    returns = []
    tickers = []
    for ticker, df in price_map.items():
        if df is None or df.empty or "Close" not in df or len(df) < 60:
            continue
        r = df["Close"].astype(float).pct_change().replace([np.inf, -np.inf], np.nan).dropna()
        if len(r) >= 40:
            returns.append(r.rename(ticker))
            tickers.append(ticker)
    if not returns:
        return [], pd.DataFrame()
    ret_df = pd.concat(returns, axis=1).dropna(how="any")
    if len(ret_df) < 40:
        return [], pd.DataFrame()
    cov = ret_df.cov() * TRADING_DAYS
    return list(cov.columns), cov


def _market_cap_weight(results: Dict[str, Dict], tickers: List[str]) -> np.ndarray:
    caps = []
    for t in tickers:
        info = results.get(t, {}).get("info", {}) or {}
        caps.append(_safe_float(info.get("marketCap"), np.nan))
    caps = np.array(caps, dtype=float)
    if np.isfinite(caps).sum() < len(caps) or np.nansum(caps) <= 0:
        return np.ones(len(tickers)) / len(tickers)
    caps = np.nan_to_num(caps, nan=np.nanmedian(caps[np.isfinite(caps)]))
    caps = np.maximum(caps, 1.0)
    return caps / caps.sum()


def _score_to_view(row: Dict, meta: Dict, max_active_view: float = 0.18) -> Tuple[float, float, str]:
    """
    Convert scanner output to a Black-Litterman absolute return view.

    View return is annualized active view centered around 0.
    Confidence is 0.05 to 0.85; higher when score is far from 50 and supported by
    expectation/game/macro-pricing modules.
    """
    final_score = _safe_float(row.get("final_score"), 50.0)
    tech_score = _safe_float(row.get("technical_score"), 50.0)
    exp_score = _safe_float(row.get("expectation_score"), 50.0)
    game_score = _safe_float(row.get("game_score"), 50.0)
    macro_score = _safe_float(row.get("cml_sml_score"), 50.0)

    composite = 0.45 * final_score + 0.20 * exp_score + 0.20 * game_score + 0.15 * macro_score
    active_view = ((composite - 50.0) / 50.0) * max_active_view

    # Penalize cases where technical score conflicts with the total desk score.
    conflict = abs(final_score - tech_score) > 25
    if conflict:
        active_view *= 0.65

    distance = abs(composite - 50.0) / 50.0
    support = np.mean([abs(exp_score - 50)/50, abs(game_score - 50)/50, abs(macro_score - 50)/50])
    confidence = float(np.clip(0.10 + 0.55 * distance + 0.20 * support, 0.05, 0.85))
    if conflict:
        confidence *= 0.75

    direction = "bullish" if active_view > 0 else "bearish" if active_view < 0 else "neutral"
    return float(active_view), float(confidence), direction


def black_litterman_allocation(
    results: Dict[str, Dict],
    risk_free_rate: float = 0.045,
    risk_aversion: float = 2.5,
    tau: float = 0.05,
    long_only: bool = True,
    max_weight: float = 0.35,
) -> Tuple[pd.DataFrame, Dict]:
    """
    Build posterior returns and suggested weights from scanner results.

    Parameters
    ----------
    results : dict[ticker -> full analyze_ticker output]
        Must include df, row, info.
    risk_free_rate : float
    risk_aversion : float
    tau : float
    long_only : bool
    max_weight : float

    Returns
    -------
    allocation_df, metadata
    """
    if not results:
        return pd.DataFrame(), {"summary": "No scanner results available for Black-Litterman."}

    price_map = {t: r.get("df") for t, r in results.items() if r is not None}
    tickers, cov_df = _annualized_cov(price_map)
    if len(tickers) < 2 or cov_df.empty:
        return pd.DataFrame(), {"summary": "Need at least two tickers with sufficient history for portfolio allocation."}

    n = len(tickers)
    cov = cov_df.loc[tickers, tickers].values
    # Numerical stability
    cov = cov + np.eye(n) * 1e-6

    prior_w = _market_cap_weight(results, tickers)
    pi = risk_aversion * cov.dot(prior_w)  # implied equilibrium excess returns

    # Identity views: each asset gets its own absolute active view.
    P = np.eye(n)
    q = []
    confidences = []
    directions = []
    for t in tickers:
        row = results[t].get("row", {}) or {}
        active_view, confidence, direction = _score_to_view(row, results[t])
        q.append(pi[tickers.index(t)] + active_view)
        confidences.append(confidence)
        directions.append(direction)
    q = np.array(q, dtype=float)
    confidences = np.array(confidences, dtype=float)

    # View uncertainty: high confidence -> low omega. Use asset variance scale.
    diag_var = np.diag(cov)
    omega_diag = np.maximum((1.0 - confidences + 0.05) * diag_var, 1e-5)
    omega = np.diag(omega_diag)

    try:
        tau_cov_inv = np.linalg.inv(tau * cov)
        omega_inv = np.linalg.inv(omega)
        posterior_cov = np.linalg.inv(tau_cov_inv + P.T.dot(omega_inv).dot(P))
        posterior = posterior_cov.dot(tau_cov_inv.dot(pi) + P.T.dot(omega_inv).dot(q))
    except np.linalg.LinAlgError:
        logger.exception("Black-Litterman inversion failed; using prior returns.")
        posterior = pi.copy()

    try:
        raw_w = np.linalg.inv(risk_aversion * cov).dot(posterior)
    except np.linalg.LinAlgError:
        raw_w = prior_w.copy()

    if long_only:
        raw_w = np.maximum(raw_w, 0.0)
    if raw_w.sum() <= 0:
        raw_w = prior_w.copy()
    weights = raw_w / raw_w.sum()

    if max_weight and max_weight > 0:
        # Simple cap-and-redistribute loop.
        weights = np.minimum(weights, max_weight)
        if weights.sum() > 0:
            weights = weights / weights.sum()

    rows = []
    for i, t in enumerate(tickers):
        row = results[t].get("row", {}) or {}
        rows.append({
            "ticker": t,
            "prior_weight": prior_w[i],
            "posterior_weight": weights[i],
            "weight_change": weights[i] - prior_w[i],
            "implied_prior_return": pi[i] + risk_free_rate,
            "posterior_expected_return": posterior[i] + risk_free_rate,
            "view_return": q[i] + risk_free_rate,
            "view_confidence": confidences[i],
            "view_direction": directions[i],
            "scanner_score": row.get("final_score"),
            "decision": row.get("decision"),
        })
    out = pd.DataFrame(rows).sort_values("posterior_weight", ascending=False)

    meta = {
        "summary": "Black-Litterman allocation blends market equilibrium weights with scanner/game/expectation/macro-pricing views.",
        "risk_free_rate": risk_free_rate,
        "risk_aversion": risk_aversion,
        "tau": tau,
        "long_only": long_only,
        "max_weight": max_weight,
        "tickers_used": tickers,
    }
    return out, meta
