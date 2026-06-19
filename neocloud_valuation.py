"""
neocloud_valuation.py

Trading Desk OS engine for valuing AI infrastructure / NeoCloud names such as
NBIS, CRWV, IREN, CORZ-style compute/power operators, and AI data-center plays.

This engine is intentionally different from a normal fundamental model.
It values:
- contracted AI compute revenue / ARR runway
- MW/GW secured power pipeline
- GPU capacity and utilization
- customer concentration and backlog quality
- financing/dilution risk
- unit economics and EV / forward ARR
- capex execution risk

Contract:
    analyze_neocloud(ticker: str, data: dict) -> dict

Expected data keys, all optional:
    data = {
        "fundamentals": {...},
        "neocloud": {
            "current_arr": 1_200_000_000,
            "target_arr_2026": 8_000_000_000,
            "backlog": 15_000_000_000,
            "revenue_growth": 1.2,
            "gross_margin": 0.62,
            "ebitda_margin": 0.18,
            "market_cap": 25_000_000_000,
            "enterprise_value": 32_000_000_000,
            "cash": 2_000_000_000,
            "total_debt": 9_000_000_000,
            "capex_ttm": 5_000_000_000,
            "shares_outstanding": 600_000_000,
            "share_dilution_yoy": 0.12,
            "secured_power_mw": 900,
            "power_pipeline_mw": 2500,
            "active_power_mw": 450,
            "gpu_count": 120_000,
            "gpu_utilization": 0.82,
            "avg_contract_years": 4.5,
            "top_customer_revenue_pct": 0.55,
            "hyperscaler_contract": True,
            "power_cost_per_mwh": 45,
            "funding_gap": 4_000_000_000,
            "customer_quality_score": 85,
            "execution_score": 70,
        }
    }

Returns:
    dict with score, signal, flags, metrics, valuation bands, and thesis.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    try:
        return max(lo, min(hi, float(x)))
    except Exception:
        return 50.0


def _safe_float(x: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if x is None:
            return default
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except Exception:
        return default


def _pct(x: Optional[float]) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:.1f}%"


def _money(x: Optional[float]) -> str:
    if x is None:
        return "n/a"
    ax = abs(x)
    if ax >= 1e12:
        return f"${x/1e12:.2f}T"
    if ax >= 1e9:
        return f"${x/1e9:.2f}B"
    if ax >= 1e6:
        return f"${x/1e6:.1f}M"
    return f"${x:,.0f}"


def infer_neocloud_inputs(fundamentals: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort fallback from ordinary fundamental fields."""
    return {
        "market_cap": fundamentals.get("market_cap") or fundamentals.get("marketCap"),
        "enterprise_value": fundamentals.get("enterprise_value") or fundamentals.get("enterpriseValue"),
        "cash": fundamentals.get("cash") or fundamentals.get("total_cash") or fundamentals.get("totalCash"),
        "total_debt": fundamentals.get("total_debt") or fundamentals.get("totalDebt"),
        "revenue_growth": fundamentals.get("revenue_growth") or fundamentals.get("revenueGrowth"),
        "gross_margin": fundamentals.get("gross_margin") or fundamentals.get("grossMargins"),
        "ebitda_margin": fundamentals.get("ebitda_margin") or fundamentals.get("ebitdaMargins"),
        "shares_outstanding": fundamentals.get("shares_outstanding") or fundamentals.get("sharesOutstanding"),
    }


def compute_capacity_score(n: Dict[str, Any]) -> Dict[str, Any]:
    secured_mw = _safe_float(n.get("secured_power_mw"), 0.0) or 0.0
    pipeline_mw = _safe_float(n.get("power_pipeline_mw"), 0.0) or 0.0
    active_mw = _safe_float(n.get("active_power_mw"), 0.0) or 0.0
    gpu_count = _safe_float(n.get("gpu_count"), 0.0) or 0.0
    utilization = _safe_float(n.get("gpu_utilization"), None)

    score = 40
    flags = []

    if secured_mw >= 1000:
        score += 25
        flags.append("GW-scale secured power footprint")
    elif secured_mw >= 500:
        score += 18
        flags.append("Large secured power footprint")
    elif secured_mw >= 150:
        score += 10
        flags.append("Meaningful secured power footprint")
    else:
        score -= 5
        flags.append("Limited disclosed secured power")

    if pipeline_mw >= 2000:
        score += 15
        flags.append("Large future power pipeline")
    elif pipeline_mw >= 750:
        score += 8

    if active_mw > 0 and secured_mw > 0:
        conversion = active_mw / secured_mw
        if conversion > 0.55:
            score += 10
            flags.append("Strong power-to-revenue conversion")
        elif conversion < 0.20:
            score -= 8
            flags.append("Large pipeline but limited active conversion")
    else:
        conversion = None

    if gpu_count >= 100_000:
        score += 12
        flags.append("Large GPU fleet")
    elif gpu_count >= 25_000:
        score += 6

    if utilization is not None:
        if utilization >= 0.80:
            score += 10
            flags.append("High GPU utilization")
        elif utilization < 0.50:
            score -= 12
            flags.append("Low GPU utilization risk")

    return {
        "score": _clamp(score),
        "flags": flags,
        "metrics": {
            "secured_power_mw": secured_mw or None,
            "power_pipeline_mw": pipeline_mw or None,
            "active_power_mw": active_mw or None,
            "power_conversion_ratio": conversion,
            "gpu_count": gpu_count or None,
            "gpu_utilization": utilization,
        },
    }


def compute_contract_score(n: Dict[str, Any]) -> Dict[str, Any]:
    backlog = _safe_float(n.get("backlog"), None)
    current_arr = _safe_float(n.get("current_arr"), None)
    target_arr = _safe_float(n.get("target_arr_2026") or n.get("target_arr_2027"), None)
    avg_years = _safe_float(n.get("avg_contract_years"), None)
    top_customer_pct = _safe_float(n.get("top_customer_revenue_pct"), None)
    hyperscaler = bool(n.get("hyperscaler_contract", False))
    customer_quality = _safe_float(n.get("customer_quality_score"), 50.0) or 50.0

    score = 45
    flags = []

    if backlog and current_arr and current_arr > 0:
        backlog_cover = backlog / current_arr
        if backlog_cover >= 5:
            score += 20
            flags.append("Backlog covers multiple years of current ARR")
        elif backlog_cover >= 2:
            score += 10
            flags.append("Healthy backlog coverage")
    else:
        backlog_cover = None

    if target_arr and current_arr and current_arr > 0:
        arr_growth_runway = target_arr / current_arr - 1
        if arr_growth_runway >= 3:
            score += 15
            flags.append("Large ARR growth runway")
        elif arr_growth_runway >= 1:
            score += 8
    else:
        arr_growth_runway = None

    if avg_years is not None:
        if avg_years >= 4:
            score += 10
            flags.append("Long-duration contracts")
        elif avg_years < 2:
            score -= 8
            flags.append("Short contract duration risk")

    if hyperscaler:
        score += 12
        flags.append("Hyperscaler / high-quality customer contract")

    if top_customer_pct is not None:
        if top_customer_pct >= 0.60:
            score -= 15
            flags.append("High customer concentration risk")
        elif top_customer_pct >= 0.35:
            score -= 7
            flags.append("Moderate customer concentration")

    score += (customer_quality - 50) * 0.25

    return {
        "score": _clamp(score),
        "flags": flags,
        "metrics": {
            "backlog": backlog,
            "current_arr": current_arr,
            "target_arr": target_arr,
            "backlog_cover_years": backlog_cover,
            "arr_growth_runway": arr_growth_runway,
            "avg_contract_years": avg_years,
            "top_customer_revenue_pct": top_customer_pct,
            "hyperscaler_contract": hyperscaler,
            "customer_quality_score": customer_quality,
        },
    }


def compute_unit_economics_score(n: Dict[str, Any]) -> Dict[str, Any]:
    gross_margin = _safe_float(n.get("gross_margin"), None)
    ebitda_margin = _safe_float(n.get("ebitda_margin"), None)
    power_cost = _safe_float(n.get("power_cost_per_mwh"), None)
    execution_score = _safe_float(n.get("execution_score"), 50.0) or 50.0

    score = 50
    flags = []

    if gross_margin is not None:
        if gross_margin >= 0.60:
            score += 18
            flags.append("Strong gross margin for AI infrastructure")
        elif gross_margin >= 0.40:
            score += 8
        elif gross_margin < 0.25:
            score -= 15
            flags.append("Weak gross margin / commodity hosting risk")

    if ebitda_margin is not None:
        if ebitda_margin >= 0.25:
            score += 14
            flags.append("Positive EBITDA margin scaling")
        elif ebitda_margin >= 0.10:
            score += 6
        elif ebitda_margin < 0:
            score -= 15
            flags.append("Negative EBITDA margin")

    if power_cost is not None:
        if power_cost <= 40:
            score += 10
            flags.append("Low-cost power advantage")
        elif power_cost >= 80:
            score -= 12
            flags.append("High power cost risk")

    score += (execution_score - 50) * 0.30

    return {
        "score": _clamp(score),
        "flags": flags,
        "metrics": {
            "gross_margin": gross_margin,
            "ebitda_margin": ebitda_margin,
            "power_cost_per_mwh": power_cost,
            "execution_score": execution_score,
        },
    }


def compute_balance_sheet_score(n: Dict[str, Any]) -> Dict[str, Any]:
    market_cap = _safe_float(n.get("market_cap"), None)
    ev = _safe_float(n.get("enterprise_value"), None)
    cash = _safe_float(n.get("cash"), 0.0) or 0.0
    debt = _safe_float(n.get("total_debt"), 0.0) or 0.0
    capex = _safe_float(n.get("capex_ttm"), None)
    funding_gap = _safe_float(n.get("funding_gap"), None)
    dilution = _safe_float(n.get("share_dilution_yoy"), None)

    score = 55
    flags = []

    net_debt = debt - cash
    net_debt_to_mcap = net_debt / market_cap if market_cap and market_cap > 0 else None

    if net_debt_to_mcap is not None:
        if net_debt_to_mcap < 0:
            score += 15
            flags.append("Net cash balance sheet")
        elif net_debt_to_mcap < 0.25:
            score += 5
        elif net_debt_to_mcap > 0.75:
            score -= 25
            flags.append("High leverage versus market cap")
        elif net_debt_to_mcap > 0.40:
            score -= 12
            flags.append("Moderate leverage risk")

    if funding_gap is not None and market_cap and market_cap > 0:
        funding_gap_pct = funding_gap / market_cap
        if funding_gap_pct > 0.25:
            score -= 20
            flags.append("Large funding gap / dilution risk")
        elif funding_gap_pct > 0.10:
            score -= 10
            flags.append("Moderate funding gap")
    else:
        funding_gap_pct = None

    if dilution is not None:
        if dilution > 0.20:
            score -= 20
            flags.append("Heavy share dilution")
        elif dilution > 0.08:
            score -= 10
            flags.append("Meaningful share dilution")
        elif dilution < 0.02:
            score += 5

    if capex and market_cap and market_cap > 0:
        capex_intensity = capex / market_cap
        if capex_intensity > 0.35:
            score -= 10
            flags.append("Very high capex intensity")
        elif capex_intensity > 0.15:
            score -= 5
    else:
        capex_intensity = None

    return {
        "score": _clamp(score),
        "flags": flags,
        "metrics": {
            "market_cap": market_cap,
            "enterprise_value": ev,
            "cash": cash,
            "total_debt": debt,
            "net_debt": net_debt,
            "net_debt_to_market_cap": net_debt_to_mcap,
            "capex_ttm": capex,
            "capex_intensity": capex_intensity,
            "funding_gap": funding_gap,
            "funding_gap_pct_market_cap": funding_gap_pct,
            "share_dilution_yoy": dilution,
        },
    }


def compute_valuation_bands(n: Dict[str, Any]) -> Dict[str, Any]:
    ev = _safe_float(n.get("enterprise_value"), None)
    current_arr = _safe_float(n.get("current_arr"), None)
    target_arr = _safe_float(n.get("target_arr_2026") or n.get("target_arr_2027"), None)
    gross_margin = _safe_float(n.get("gross_margin"), None)
    secured_mw = _safe_float(n.get("secured_power_mw"), None)
    pipeline_mw = _safe_float(n.get("power_pipeline_mw"), None)

    ev_current_arr = ev / current_arr if ev and current_arr and current_arr > 0 else None
    ev_target_arr = ev / target_arr if ev and target_arr and target_arr > 0 else None
    ev_per_secured_mw = ev / secured_mw if ev and secured_mw and secured_mw > 0 else None
    ev_per_pipeline_mw = ev / pipeline_mw if ev and pipeline_mw and pipeline_mw > 0 else None

    # Multiples are deliberately broad because NeoCloud valuation depends on
    # contract quality, funding access, and GPU cycle risk.
    if gross_margin is not None and gross_margin >= 0.55:
        bear_mult, base_mult, bull_mult = 4.0, 7.0, 11.0
    elif gross_margin is not None and gross_margin >= 0.35:
        bear_mult, base_mult, bull_mult = 3.0, 5.5, 8.0
    else:
        bear_mult, base_mult, bull_mult = 2.0, 4.0, 6.0

    target_arr_basis = target_arr or current_arr
    valuation_band = None
    if target_arr_basis:
        valuation_band = {
            "bear_ev": target_arr_basis * bear_mult,
            "base_ev": target_arr_basis * base_mult,
            "bull_ev": target_arr_basis * bull_mult,
            "bear_ev_arr_multiple": bear_mult,
            "base_ev_arr_multiple": base_mult,
            "bull_ev_arr_multiple": bull_mult,
            "arr_basis": target_arr_basis,
        }

    return {
        "ev_current_arr": ev_current_arr,
        "ev_target_arr": ev_target_arr,
        "ev_per_secured_mw": ev_per_secured_mw,
        "ev_per_pipeline_mw": ev_per_pipeline_mw,
        "valuation_band": valuation_band,
    }


def compute_neocloud_score(n: Dict[str, Any]) -> Dict[str, Any]:
    capacity = compute_capacity_score(n)
    contracts = compute_contract_score(n)
    unit = compute_unit_economics_score(n)
    balance = compute_balance_sheet_score(n)
    valuation = compute_valuation_bands(n)

    valuation_score = 50
    flags = []
    ev_target_arr = valuation.get("ev_target_arr")
    ev_current_arr = valuation.get("ev_current_arr")

    if ev_target_arr is not None:
        if ev_target_arr <= 4:
            valuation_score += 25
            flags.append("Cheap versus forward ARR target")
        elif ev_target_arr <= 7:
            valuation_score += 10
            flags.append("Reasonable versus forward ARR target")
        elif ev_target_arr >= 12:
            valuation_score -= 25
            flags.append("Expensive versus forward ARR target")
        elif ev_target_arr >= 9:
            valuation_score -= 10
            flags.append("Rich versus forward ARR target")
    elif ev_current_arr is not None:
        if ev_current_arr <= 8:
            valuation_score += 12
        elif ev_current_arr >= 20:
            valuation_score -= 18
            flags.append("Expensive on current ARR")

    # Weighted final score
    final = (
        0.25 * capacity["score"]
        + 0.25 * contracts["score"]
        + 0.20 * unit["score"]
        + 0.20 * balance["score"]
        + 0.10 * _clamp(valuation_score)
    )

    all_flags = (
        capacity["flags"]
        + contracts["flags"]
        + unit["flags"]
        + balance["flags"]
        + flags
    )

    if final >= 75:
        signal = "High-quality NeoCloud compounder"
        bias = "bullish"
    elif final >= 62:
        signal = "Promising but execution-sensitive"
        bias = "constructive"
    elif final >= 45:
        signal = "Watchlist / needs confirmation"
        bias = "neutral"
    else:
        signal = "High-risk NeoCloud / funding trap"
        bias = "bearish"

    return {
        "score": round(_clamp(final), 1),
        "signal": signal,
        "bias": bias,
        "flags": all_flags[:12],
        "subscores": {
            "capacity": round(capacity["score"], 1),
            "contracts": round(contracts["score"], 1),
            "unit_economics": round(unit["score"], 1),
            "balance_sheet": round(balance["score"], 1),
            "valuation": round(_clamp(valuation_score), 1),
        },
        "metrics": {
            **capacity["metrics"],
            **contracts["metrics"],
            **unit["metrics"],
            **balance["metrics"],
            **valuation,
        },
    }


def analyze_neocloud(ticker: str, data: Dict[str, Any]) -> Dict[str, Any]:
    fundamentals = data.get("fundamentals", {}) or {}
    n = {}
    n.update(infer_neocloud_inputs(fundamentals))
    n.update(data.get("neocloud", {}) or {})

    result = compute_neocloud_score(n)
    m = result["metrics"]
    valuation_band = m.get("valuation_band") or {}

    thesis_parts = [
        f"{ticker}: {result['signal']} with NeoCloud score {result['score']}/100.",
        f"Capacity score {result['subscores']['capacity']}, contract score {result['subscores']['contracts']}, balance-sheet score {result['subscores']['balance_sheet']}.",
    ]

    if m.get("ev_target_arr") is not None:
        thesis_parts.append(f"EV/target ARR is {m['ev_target_arr']:.1f}x.")
    elif m.get("ev_current_arr") is not None:
        thesis_parts.append(f"EV/current ARR is {m['ev_current_arr']:.1f}x.")

    if valuation_band:
        thesis_parts.append(
            "ARR-based EV band: "
            f"bear {_money(valuation_band.get('bear_ev'))}, "
            f"base {_money(valuation_band.get('base_ev'))}, "
            f"bull {_money(valuation_band.get('bull_ev'))}."
        )

    if result["flags"]:
        thesis_parts.append("Key reads: " + "; ".join(result["flags"][:5]) + ".")

    result.update(
        {
            "engine": "neocloud_valuation",
            "ticker": ticker.upper(),
            "summary": " ".join(thesis_parts),
            "trade_impact": {
                "bias": result["bias"],
                "position_adjustment": 1.15 if result["score"] >= 75 else 1.0 if result["score"] >= 55 else 0.65,
                "risk": "high" if result["subscores"]["balance_sheet"] < 45 else "medium",
            },
        }
    )
    return result


# Registry-compatible alias
analyze = analyze_neocloud


if __name__ == "__main__":
    # Example only. Replace with real company-specific inputs from filings / APIs.
    example = {
        "fundamentals": {
            "market_cap": 25_000_000_000,
            "enterprise_value": 32_000_000_000,
            "cash": 2_000_000_000,
            "total_debt": 8_000_000_000,
            "gross_margin": 0.60,
            "ebitda_margin": 0.18,
        },
        "neocloud": {
            "current_arr": 1_200_000_000,
            "target_arr_2026": 8_000_000_000,
            "backlog": 14_000_000_000,
            "secured_power_mw": 900,
            "power_pipeline_mw": 2500,
            "active_power_mw": 420,
            "gpu_count": 120_000,
            "gpu_utilization": 0.82,
            "avg_contract_years": 4.5,
            "top_customer_revenue_pct": 0.55,
            "hyperscaler_contract": True,
            "share_dilution_yoy": 0.10,
            "funding_gap": 3_000_000_000,
            "customer_quality_score": 85,
            "execution_score": 72,
        },
    }
    import json

    print(json.dumps(analyze_neocloud("CRWV", example), indent=2, default=str))
