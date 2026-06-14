"""
Game Theory / Participant Behavior Engine
-----------------------------------------
Drop-in replacement for the app's existing game_theory.py.

Core idea:
    Classical game theory is less useful for trading than a practical
    participant-pressure model. This module uses a Brandenburger/Nalebuff
    co-opetition lens + information asymmetry + forced-flow logic.

Public API expected by app.py:
    game_theory_score(tech, liq, opt, info=None) -> (score, metadata)

Inputs are dictionaries produced by:
    technicals.technical_score(...)
    liquidity.liquidity_score(...)
    options_engine.options_score(...)
    yfinance/FMP/etc. info dict

The module is defensive: missing fields are treated neutrally.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from utils import clamp

logger = logging.getLogger("trading_desk.game_theory")


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _safe_float(x: Any, default: float = np.nan) -> float:
    try:
        if x is None or pd.isna(x):
            return default
        return float(x)
    except Exception:
        return default


def _safe_bool(x: Any, default: bool = False) -> bool:
    try:
        if x is None:
            return default
        return bool(x)
    except Exception:
        return default


def _pct_to_0_100(x: Any, default: float = 0.0) -> float:
    """
    Converts vendor values that may arrive as 0.18 or 18 into percentage points.
    Example: shortPercentOfFloat from yfinance is usually 0.18 for 18%.
    """
    val = _safe_float(x, default=default)
    if np.isnan(val):
        return default
    if abs(val) <= 1.5:
        return val * 100.0
    return val


def _get_first(d: Optional[Dict[str, Any]], keys: List[str], default: Any = None) -> Any:
    if not d:
        return default
    for k in keys:
        if k in d and d.get(k) is not None:
            return d.get(k)
    return default


def _distance_pct(price: float, level: float) -> float:
    if price and level and not np.isnan(price) and not np.isnan(level):
        return abs(price - level) / price
    return np.nan


# -----------------------------------------------------------------------------
# Layer 1: Brandenburger / Nalebuff Co-opetition
# -----------------------------------------------------------------------------

def compute_coopetition_score(
    setup_type: str,
    cmf: float,
    obv_rising: bool,
    adl_rising: bool,
    rel_vol: float,
    institutional_ownership_pct: float,
    insider_ownership_pct: float,
    short_float_pct: float,
) -> Tuple[float, List[str], Dict[str, Any]]:
    """
    Measures whether participant incentives are aligned or in conflict.

    High score means the current setup is supported by cooperative flows:
    accumulation, sponsorship, dip-buying, momentum confirmation, or shorts
    creating potential future demand.
    """
    score = 50.0
    flags: List[str] = []

    setup = (setup_type or "").lower()

    # Institutional sponsorship is useful, but very high ownership can also mean
    # crowded ownership. Score moderately, not blindly.
    if institutional_ownership_pct >= 70:
        score += 10
        flags.append("High institutional sponsorship")
    elif institutional_ownership_pct >= 40:
        score += 5
        flags.append("Moderate institutional sponsorship")
    elif institutional_ownership_pct and institutional_ownership_pct < 15:
        score -= 5
        flags.append("Low institutional sponsorship")

    # Insider ownership can align incentives, but excessive insider ownership can
    # reduce float and liquidity.
    if 3 <= insider_ownership_pct <= 25:
        score += 6
        flags.append("Insider ownership aligns incentives")
    elif insider_ownership_pct > 40:
        score -= 3
        flags.append("Very high insider ownership may reduce free float")

    # Accumulation confirmation.
    if cmf > 0.15 and obv_rising and adl_rising:
        score += 18
        flags.append("Institutions/dip buyers appear cooperative: CMF, OBV, ADL all positive")
    elif cmf > 0.05 and (obv_rising or adl_rising):
        score += 10
        flags.append("Accumulation evidence improving")
    elif cmf < -0.15 and not obv_rising and not adl_rising:
        score -= 18
        flags.append("Distribution pressure: money flow and volume trend negative")
    elif cmf < -0.05:
        score -= 8
        flags.append("Money flow weak")

    # Setup-specific cooperative/predatory logic.
    if any(x in setup for x in ["breakout", "gap", "failed breakdown", "squeeze"]):
        if rel_vol >= 1.5 and cmf > 0:
            score += 12
            flags.append("Breakout/momentum buyers are being confirmed by volume")
        elif rel_vol < 0.8:
            score -= 8
            flags.append("Breakout lacks participation")

    if any(x in setup for x in ["pullback", "support", "reversal"]):
        if cmf > 0 and (obv_rising or adl_rising):
            score += 10
            flags.append("Dip buyers appear to be absorbing supply")
        elif cmf < 0:
            score -= 6
            flags.append("Pullback may be distribution, not absorption")

    if any(x in setup for x in ["rejection", "distribution", "downtrend", "resistance"]):
        score -= 15
        flags.append("Supply likely controls the tape; trapped longs may sell rallies")

    # Short interest creates conflict. It is not bullish by itself; it becomes
    # bullish only when price/volume forces shorts to cover.
    if short_float_pct >= 25 and rel_vol >= 1.5:
        score += 10
        flags.append("High short interest creates conflict; volume may pressure shorts")
    elif short_float_pct >= 25 and rel_vol < 1.0:
        score -= 5
        flags.append("High short interest but no current pressure on shorts")

    metrics = {
        "institutional_ownership_pct": institutional_ownership_pct,
        "insider_ownership_pct": insider_ownership_pct,
        "short_float_pct": short_float_pct,
        "coopetition_interpretation": _interpret_score(score, "alignment"),
    }
    return clamp(score), flags, metrics


# -----------------------------------------------------------------------------
# Layer 2: Information Asymmetry / Signaling
# -----------------------------------------------------------------------------

def compute_information_asymmetry_score(
    iv_rank: float,
    atm_iv: float,
    call_put_volume: float,
    put_call_volume: float,
    put_call_oi: float,
    earnings_days: float,
    analyst_revisions: float,
    news_catalyst_score: float,
) -> Tuple[float, List[str], Dict[str, Any]]:
    """
    Looks for signs that informed or catalyst-sensitive participants are active:
    unusual options, IV expansion, earnings proximity, analyst/filing/catalyst clues.
    """
    score = 50.0
    flags: List[str] = []

    # Convert PCR into call pressure if needed.
    # put_call_volume < 0.5 means call volume is roughly > 2x put volume.
    if not np.isnan(put_call_volume):
        if put_call_volume < 0.45:
            score += 15
            flags.append("Options tape suggests aggressive call demand")
        elif put_call_volume > 1.8:
            score -= 10
            flags.append("Options tape suggests put protection / bearish demand")

    if not np.isnan(call_put_volume):
        if call_put_volume > 2.2:
            score += 15
            flags.append("Call/put volume ratio elevated")
        elif call_put_volume < 0.55:
            score -= 10
            flags.append("Call demand weak versus puts")

    if not np.isnan(put_call_oi):
        if put_call_oi < 0.70:
            score += 6
            flags.append("Open interest skew leans bullish")
        elif put_call_oi > 1.50:
            score -= 6
            flags.append("Open interest skew leans defensive/bearish")

    # IV rank may not exist from free yfinance chain. Treat missing as neutral.
    if not np.isnan(iv_rank):
        if iv_rank > 80:
            score += 8
            flags.append("High IV rank: market pricing event/information risk")
        elif iv_rank < 20:
            score -= 3
            flags.append("Low IV rank: little event premium priced")

    # ATM IV heuristic if IV rank unavailable.
    if np.isnan(iv_rank) and not np.isnan(atm_iv):
        if atm_iv > 0.90:
            score += 7
            flags.append("Very high ATM IV: market expects large movement")
        elif atm_iv < 0.25:
            score -= 3
            flags.append("Low ATM IV: limited volatility signal")

    if not np.isnan(earnings_days):
        if 0 <= earnings_days <= 7:
            score += 10
            flags.append("Earnings imminent: information asymmetry elevated")
        elif 7 < earnings_days <= 21:
            score += 4
            flags.append("Earnings approaching")

    if analyst_revisions > 0:
        score += min(10, analyst_revisions * 3)
        flags.append("Positive analyst/revision signal")
    elif analyst_revisions < 0:
        score -= min(10, abs(analyst_revisions) * 3)
        flags.append("Negative analyst/revision signal")

    if news_catalyst_score >= 75:
        score += 10
        flags.append("Strong catalyst/news signal")
    elif news_catalyst_score <= 35:
        score -= 8
        flags.append("Weak or negative catalyst/news signal")

    metrics = {
        "iv_rank": iv_rank,
        "atm_iv": atm_iv,
        "put_call_volume": put_call_volume,
        "call_put_volume": call_put_volume,
        "information_interpretation": _interpret_score(score, "information"),
    }
    return clamp(score), flags, metrics


# -----------------------------------------------------------------------------
# Layer 3: Forced Flow
# -----------------------------------------------------------------------------

def compute_forced_flow_score(
    setup_type: str,
    rel_vol: float,
    float_rotation: float,
    short_float_pct: float,
    days_to_cover: float,
    put_call_volume: float,
    put_call_oi: float,
    spot: float,
    max_pain: float,
    gamma_zone: float,
    gex: float,
    gamma_flip_distance: float,
    thin_liquidity: bool,
) -> Tuple[float, List[str], Dict[str, Any]]:
    """
    Estimates whether a group of participants may become forced buyers/sellers.

    This is the most important trading-desk lens:
        - shorts forced to cover
        - dealers forced to hedge
        - breakout traders forced to chase
        - trapped longs forced to sell
        - market makers pinning price near large OI/max pain
    """
    score = 50.0
    flags: List[str] = []
    setup = (setup_type or "").lower()

    short_squeeze_score = 50.0
    gamma_squeeze_score = 50.0
    pinning_risk_score = 50.0
    trapped_longs_score = 50.0
    breakout_chase_score = 50.0

    # Short squeeze pressure.
    if short_float_pct >= 30:
        short_squeeze_score += 25
        flags.append("Very high short interest")
    elif short_float_pct >= 20:
        short_squeeze_score += 18
        flags.append("High short interest")
    elif short_float_pct >= 12:
        short_squeeze_score += 8
        flags.append("Moderate short interest")

    if days_to_cover >= 7:
        short_squeeze_score += 15
        flags.append("High days-to-cover: exits may be crowded")
    elif days_to_cover >= 4:
        short_squeeze_score += 8

    if rel_vol >= 2.0 and short_float_pct >= 12:
        short_squeeze_score += 15
        flags.append("Relative volume is pressuring shorts")

    if not np.isnan(float_rotation):
        if float_rotation >= 1.0:
            short_squeeze_score += 18
            flags.append("Full float rotation: extreme reflexivity risk")
        elif float_rotation >= 0.30:
            short_squeeze_score += 12
            flags.append("Large float rotation: active participant turnover")
        elif float_rotation < 0.02:
            short_squeeze_score -= 5

    # Options/dealer pressure.
    if not np.isnan(put_call_volume):
        if put_call_volume < 0.45:
            gamma_squeeze_score += 12
            flags.append("Call demand can force dealer hedging if dealers are short calls")
        elif put_call_volume > 2.0:
            gamma_squeeze_score -= 8
            flags.append("Put demand may create downside hedging pressure")

    # Optional external GEX support. Convention: negative GEX = unstable/chasey.
    if not np.isnan(gex):
        if gex < 0:
            gamma_squeeze_score += 12
            flags.append("Negative GEX proxy: dealer hedging may amplify moves")
        elif gex > 0:
            gamma_squeeze_score -= 6
            flags.append("Positive GEX proxy: dealer hedging may dampen moves")

    if not np.isnan(gamma_flip_distance):
        if gamma_flip_distance <= 0.02:
            gamma_squeeze_score += 8
            flags.append("Near gamma flip level")
        elif gamma_flip_distance <= 0.05:
            gamma_squeeze_score += 4

    # Pinning risk: price near max pain/gamma zone into expiry can dampen trend.
    max_pain_dist = _distance_pct(spot, max_pain)
    gamma_zone_dist = _distance_pct(spot, gamma_zone)

    if not np.isnan(max_pain_dist):
        if max_pain_dist <= 0.015:
            pinning_risk_score += 18
            flags.append("Pin risk: spot is very near max pain")
        elif max_pain_dist <= 0.035:
            pinning_risk_score += 8
            flags.append("Spot is near max pain")

    if not np.isnan(gamma_zone_dist):
        if gamma_zone_dist <= 0.015:
            pinning_risk_score += 12
            flags.append("Spot is very near major OI/gamma zone")
        elif gamma_zone_dist <= 0.035:
            pinning_risk_score += 6
            flags.append("Spot is near major OI/gamma zone")

    # Breakout chasers / trapped longs.
    if any(x in setup for x in ["breakout", "gap", "squeeze", "failed breakdown"]):
        if rel_vol >= 1.5:
            breakout_chase_score += 18
            flags.append("Momentum/breakout traders may be forced to chase")
        else:
            breakout_chase_score -= 6

    if any(x in setup for x in ["rejection", "distribution", "downtrend", "resistance"]):
        trapped_longs_score += 20
        flags.append("Trapped longs may sell into rallies")

    if thin_liquidity and rel_vol >= 2.0:
        # Thin names can move violently, but execution risk is high. We boost
        # reflexivity but the final narrative will flag the risk.
        breakout_chase_score += 7
        flags.append("Thin liquidity can amplify forced flow, but slippage risk is high")

    # Convert sub-scores to directional forced-flow score.
    # Pinning is not bullish or bearish; it reduces directional edge if dominant.
    directional_pressure = (
        0.35 * clamp(short_squeeze_score) +
        0.30 * clamp(gamma_squeeze_score) +
        0.20 * clamp(breakout_chase_score) +
        0.15 * (100 - clamp(trapped_longs_score))
    )

    pin_penalty = max(0.0, clamp(pinning_risk_score) - 60.0) * 0.35
    score = directional_pressure - pin_penalty

    metrics = {
        "short_squeeze_score": round(clamp(short_squeeze_score), 1),
        "gamma_squeeze_score": round(clamp(gamma_squeeze_score), 1),
        "pinning_risk_score": round(clamp(pinning_risk_score), 1),
        "trapped_longs_score": round(clamp(trapped_longs_score), 1),
        "breakout_chase_score": round(clamp(breakout_chase_score), 1),
        "max_pain_distance_pct": max_pain_dist,
        "gamma_zone_distance_pct": gamma_zone_dist,
        "forced_flow_interpretation": _interpret_score(score, "forced_flow"),
    }
    return clamp(score), flags, metrics


# -----------------------------------------------------------------------------
# Participant map + narrative
# -----------------------------------------------------------------------------

def build_participant_map(
    coop_score: float,
    info_score: float,
    forced_score: float,
    setup_type: str,
    cmf: float,
    rel_vol: float,
    short_float_pct: float,
    put_call_volume: float,
    pinning_risk_score: float,
) -> Dict[str, Dict[str, Any]]:
    setup = (setup_type or "").lower()

    institutions_bias = "Bullish" if cmf > 0.05 else ("Bearish" if cmf < -0.05 else "Neutral")
    institutions_pressure = clamp(50 + cmf * 120 + (10 if rel_vol > 1.3 else 0))

    shorts_bias = "Forced buyer risk" if short_float_pct >= 12 and rel_vol > 1.3 else "Bearish/defensive"
    shorts_pressure = clamp(40 + short_float_pct * 1.4 + (15 if rel_vol > 1.5 else 0))

    dealers_bias = "Pinning" if pinning_risk_score > 65 else "Hedging amplifier" if forced_score > 65 else "Neutral"
    dealers_pressure = clamp(pinning_risk_score if pinning_risk_score > 65 else forced_score)

    retail_bias = "FOMO" if rel_vol > 2.0 and any(x in setup for x in ["breakout", "gap", "squeeze"]) else "Watching"
    retail_pressure = clamp(45 + max(0, rel_vol - 1) * 18)

    momentum_bias = "Chasing" if any(x in setup for x in ["breakout", "gap", "squeeze"]) and rel_vol > 1.3 else "Inactive/neutral"
    momentum_pressure = clamp(50 + (20 if "breakout" in setup else 0) + max(0, rel_vol - 1) * 10)

    options_bias = "Call pressure" if (not np.isnan(put_call_volume) and put_call_volume < 0.7) else ("Put protection" if (not np.isnan(put_call_volume) and put_call_volume > 1.4) else "Balanced")
    options_pressure = clamp(info_score)

    return {
        "institutions": {"bias": institutions_bias, "pressure": round(institutions_pressure, 1)},
        "short_sellers": {"bias": shorts_bias, "pressure": round(shorts_pressure, 1)},
        "dealers": {"bias": dealers_bias, "pressure": round(dealers_pressure, 1)},
        "retail_momentum": {"bias": retail_bias, "pressure": round(retail_pressure, 1)},
        "momentum_funds": {"bias": momentum_bias, "pressure": round(momentum_pressure, 1)},
        "options_traders": {"bias": options_bias, "pressure": round(options_pressure, 1)},
    }


def _interpret_score(score: float, kind: str) -> str:
    score = clamp(score)
    if kind == "alignment":
        if score >= 75:
            return "cooperative accumulation / aligned participants"
        if score >= 60:
            return "moderately supportive participant alignment"
        if score <= 35:
            return "predatory/distribution environment"
        if score <= 45:
            return "weak alignment"
        return "balanced participant alignment"

    if kind == "information":
        if score >= 75:
            return "strong information/catalyst signal"
        if score >= 60:
            return "moderate information signal"
        if score <= 35:
            return "negative/defensive information signal"
        return "limited information edge"

    if kind == "forced_flow":
        if score >= 75:
            return "high forced-flow / squeeze potential"
        if score >= 60:
            return "moderate forced-flow support"
        if score <= 35:
            return "forced-selling / fade risk"
        return "balanced forced-flow profile"

    return "neutral"


def infer_environment(final_score: float, forced_score: float, coop_score: float, pinning_risk_score: float, setup_type: str) -> str:
    setup = (setup_type or "").lower()
    if pinning_risk_score >= 72 and forced_score < 70:
        return "pinning / range-control"
    if forced_score >= 75:
        return "squeeze / forced-flow"
    if coop_score >= 70 and final_score >= 65:
        return "accumulation"
    if final_score <= 35:
        return "distribution / fade"
    if "rejection" in setup or "downtrend" in setup:
        return "supply-controlled"
    return "balanced / wait for confirmation"


def build_game_theory_summary(
    final_score: float,
    environment: str,
    participant_map: Dict[str, Dict[str, Any]],
    key_flags: List[str],
) -> str:
    top_players = sorted(
        participant_map.items(),
        key=lambda kv: kv[1].get("pressure", 0),
        reverse=True,
    )[:3]
    player_txt = ", ".join([f"{name.replace('_', ' ')}: {data['bias']}" for name, data in top_players])

    if key_flags:
        flag_txt = "; ".join(key_flags[:4])
    else:
        flag_txt = "no obvious forced-flow edge"

    return (
        f"Game theory: {environment}. Score {final_score:.0f}. "
        f"Dominant participants — {player_txt}. Key read: {flag_txt}."
    )


# -----------------------------------------------------------------------------
# Main public API
# -----------------------------------------------------------------------------

def game_theory_score(
    tech: Optional[Dict[str, Any]],
    liq: Optional[Dict[str, Any]],
    opt: Optional[Dict[str, Any]],
    info: Optional[Dict[str, Any]] = None,
) -> Tuple[float, Dict[str, Any]]:
    """
    Drop-in replacement called by app.py.

    Args:
        tech: metadata from technical_score
        liq: metadata from liquidity_score
        opt: metadata from options_score
        info: yfinance/FMP/AlphaVantage style fundamentals dict

    Returns:
        score, metadata
    """
    tech = tech or {}
    liq = liq or {}
    opt = opt or {}
    info = info or {}

    # Technical / liquidity inputs.
    setup_type = str(_get_first(tech, ["setup_type", "setup", "pattern"], ""))
    spot = _safe_float(_get_first(tech, ["close", "price", "last_price"], np.nan))

    # If tech does not contain price, try option gamma distance fields later; neutral if missing.
    rel_vol = _safe_float(_get_first(liq, ["rel_vol", "relative_volume"], 1.0), 1.0)
    cmf = _safe_float(_get_first(liq, ["cmf", "cmf20"], 0.0), 0.0)
    obv_rising = _safe_bool(_get_first(liq, ["obv_rising"], False))
    adl_rising = _safe_bool(_get_first(liq, ["adl_rising"], False))
    float_rotation = _safe_float(_get_first(liq, ["float_rotation"], np.nan))
    thin_liquidity = _safe_bool(_get_first(liq, ["thin_liquidity", "very_thin_liquidity"], False))

    # Fundamental / ownership inputs. yfinance usually returns 0.12 for 12%.
    institutional_ownership_pct = _pct_to_0_100(_get_first(info, ["heldPercentInstitutions", "institutional_ownership", "institutionalOwnership"], 0.0))
    insider_ownership_pct = _pct_to_0_100(_get_first(info, ["heldPercentInsiders", "insider_ownership", "insiderOwnership"], 0.0))
    short_float_pct = _pct_to_0_100(_get_first(info, ["shortPercentOfFloat", "short_float", "shortFloat", "short_interest_pct"], 0.0))
    days_to_cover = _safe_float(_get_first(info, ["shortRatio", "daysToCover", "days_to_cover"], 0.0), 0.0)

    # Options inputs.
    put_call_oi = _safe_float(_get_first(opt, ["put_call_oi", "pcr_oi"], np.nan))
    put_call_volume = _safe_float(_get_first(opt, ["put_call_volume", "pcr_volume"], np.nan))
    call_put_volume = _safe_float(_get_first(opt, ["call_put_volume"], np.nan))
    if np.isnan(call_put_volume) and not np.isnan(put_call_volume) and put_call_volume != 0:
        call_put_volume = 1.0 / put_call_volume

    atm_iv = _safe_float(_get_first(opt, ["atm_iv", "iv", "implied_volatility"], np.nan))
    iv_rank = _safe_float(_get_first(opt, ["iv_rank", "iv_percentile"], np.nan))
    max_pain = _safe_float(_get_first(opt, ["max_pain"], np.nan))
    gamma_zone = _safe_float(_get_first(opt, ["gamma_zone", "dealer_resistance", "major_oi_strike"], np.nan))
    gex = _safe_float(_get_first(opt, ["gex", "gamma_exposure", "net_gex"], np.nan))
    gamma_flip_distance = _safe_float(_get_first(opt, ["gamma_flip_distance", "gamma_flip_distance_pct"], np.nan))

    # Optional catalyst/analyst fields if you later pass richer dicts into info/opt.
    earnings_days = _safe_float(_get_first(info, ["earnings_days", "days_to_earnings"], np.nan))
    analyst_revisions = _safe_float(_get_first(info, ["analyst_revisions", "recommendationChange", "revision_score"], 0.0), 0.0)
    news_catalyst_score = _safe_float(_get_first(info, ["catalyst_score", "news_score"], 50.0), 50.0)

    coop_score, coop_flags, coop_metrics = compute_coopetition_score(
        setup_type=setup_type,
        cmf=cmf,
        obv_rising=obv_rising,
        adl_rising=adl_rising,
        rel_vol=rel_vol,
        institutional_ownership_pct=institutional_ownership_pct,
        insider_ownership_pct=insider_ownership_pct,
        short_float_pct=short_float_pct,
    )

    info_score, info_flags, info_metrics = compute_information_asymmetry_score(
        iv_rank=iv_rank,
        atm_iv=atm_iv,
        call_put_volume=call_put_volume,
        put_call_volume=put_call_volume,
        put_call_oi=put_call_oi,
        earnings_days=earnings_days,
        analyst_revisions=analyst_revisions,
        news_catalyst_score=news_catalyst_score,
    )

    forced_score, forced_flags, forced_metrics = compute_forced_flow_score(
        setup_type=setup_type,
        rel_vol=rel_vol,
        float_rotation=float_rotation,
        short_float_pct=short_float_pct,
        days_to_cover=days_to_cover,
        put_call_volume=put_call_volume,
        put_call_oi=put_call_oi,
        spot=spot,
        max_pain=max_pain,
        gamma_zone=gamma_zone,
        gex=gex,
        gamma_flip_distance=gamma_flip_distance,
        thin_liquidity=thin_liquidity,
    )

    # Practical trading-desk weighting.
    final_score = 0.30 * coop_score + 0.30 * info_score + 0.40 * forced_score

    pinning_risk_score = forced_metrics.get("pinning_risk_score", 50.0)
    participant_map = build_participant_map(
        coop_score=coop_score,
        info_score=info_score,
        forced_score=forced_score,
        setup_type=setup_type,
        cmf=cmf,
        rel_vol=rel_vol,
        short_float_pct=short_float_pct,
        put_call_volume=put_call_volume,
        pinning_risk_score=pinning_risk_score,
    )

    environment = infer_environment(
        final_score=final_score,
        forced_score=forced_score,
        coop_score=coop_score,
        pinning_risk_score=pinning_risk_score,
        setup_type=setup_type,
    )

    all_flags = coop_flags + info_flags + forced_flags
    # De-duplicate while preserving order.
    seen = set()
    flags = []
    for f in all_flags:
        if f not in seen:
            seen.add(f)
            flags.append(f)

    summary = build_game_theory_summary(
        final_score=final_score,
        environment=environment,
        participant_map=participant_map,
        key_flags=flags,
    )

    # Backward-compatible keys for existing thesis builder.
    reads = flags if flags else ["No obvious forced-flow edge; wait for confirmation"]
    participant_read = "; ".join(reads[:5])

    metadata: Dict[str, Any] = {
        "participant_read": participant_read,
        "environment": environment,
        "game_reasons": reads,
        "flags": flags,
        "summary": summary,
        "coopetition_score": round(coop_score, 1),
        "information_asymmetry_score": round(info_score, 1),
        "forced_flow_score": round(forced_score, 1),
        "participant_map": participant_map,
        "metrics": {
            **coop_metrics,
            **info_metrics,
            **forced_metrics,
            "final_game_theory_score": round(clamp(final_score), 1),
        },
        # Convenience flattened fields for Streamlit display/export.
        "short_squeeze_score": forced_metrics.get("short_squeeze_score"),
        "gamma_squeeze_score": forced_metrics.get("gamma_squeeze_score"),
        "pinning_risk_score": forced_metrics.get("pinning_risk_score"),
        "trapped_longs_score": forced_metrics.get("trapped_longs_score"),
        "breakout_chase_score": forced_metrics.get("breakout_chase_score"),
    }

    return clamp(final_score), metadata


# Optional alias if future app versions call analyze_game_theory directly.
def analyze_game_theory(
    tech: Optional[Dict[str, Any]],
    liq: Optional[Dict[str, Any]],
    opt: Optional[Dict[str, Any]],
    info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    score, meta = game_theory_score(tech, liq, opt, info)
    return {"total": score, **meta}
