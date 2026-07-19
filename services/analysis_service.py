from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from catalyst_engine import catalyst_score
from daily_report_generator import generate_daily_report
from data_loader import get_info, get_news, get_ohlcv, get_options_chain
from expected_return_engine import estimate_expected_return
from fundamentals import fundamental_score
from game_theory import game_theory_score
from liquidity import analyze_liquidity
from market_regime import analyze_market_regime
from merton_credit_engine import analyze_merton_credit
from neocloud_profile_loader import is_neocloud_ticker, load_neocloud_profile
from neocloud_valuation import analyze_neocloud
from options_engine import options_score
from scoring import build_thesis, classify, combine_scores, result_row
from technicals import technical_score, trade_levels
from theme_engine import analyze_theme, rank_themes
from utils import clamp
from config.settings import settings
from database.store import connect, init_db, utc_now
from engines.trend_quality_engine import analyze_trend_quality
from engines.entry_quality_engine import analyze_entry_quality
from engines.leadership_engine import analyze_leadership
from decision_layer import build_reasoning

try:
    from engines.optionality_engine import optionality_score
except Exception as e:
    print(f"[IMPORT ERROR] optionality_engine failed: {type(e).__name__}: {e}")
    optionality_score = None   
logger = logging.getLogger("trading_desk.api.analysis")

DEFAULT_WEIGHTS = {
    "fundamental": 0.13,
    "technical": 0.18,
    "liquidity": 0.11,
    "options": 0.11,
    "game": 0.12,
    "catalyst": 0.06,
    "expectation": 0.10,
    "merton": 0.07,
    "neocloud": 0.05,
    "optionality": 0.07,
}

MARKET_SYMBOLS = ["SPY", "QQQ", "IWM", "DIA", "TLT", "HYG", "LQD", "UUP", "^VIX", "^TNX"]


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if pd.isna(obj) if not isinstance(obj, (str, bytes, list, dict, tuple)) else False:
        return None
    return obj


def _extract_options_expiry_and_chains(ticker: str):
    exp, calls, puts = get_options_chain(ticker)
    return exp, calls, puts


def load_market_data(period: str = "1y", interval: str = "1d") -> Dict[str, pd.DataFrame]:
    out = {}
    for sym in MARKET_SYMBOLS:
        try:
            df = get_ohlcv(sym, period=period, interval=interval)
            if df is not None and not df.empty:
                key = sym.replace("^", "")
                out[key] = df
                out[sym] = df
        except Exception as exc:
            logger.warning("market data failed %s: %s", sym, exc)
    return out


def get_regime(period: str = "1y", interval: str = "1d") -> Dict[str, Any]:
    market_data = load_market_data(period, interval)
    try:
        return _json_safe(analyze_market_regime(market_data))
    except Exception as exc:
        logger.exception("regime analysis failed: %s", exc)
        return {"regime": "UNKNOWN", "total": 50, "flags": [f"Regime failed: {exc}"], "metrics": {}}


def analyze_stock(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
    account_size: float = 100_000,
    risk_pct: float = 0.005,
    regime_result: Optional[dict] = None,
    market_data: Optional[Dict[str, pd.DataFrame]] = None,
    include_options: bool = True,
    persist_signal: bool = True,
) -> Dict[str, Any]:
    ticker = ticker.strip().upper().replace(".", "-")
    df = get_ohlcv(ticker, period=period, interval=interval)
    if df is None or df.empty or len(df) < 40:
        return {"ticker": ticker, "error": "Insufficient OHLCV data", "decision": "Avoid", "final_score": 0}

    market_data = market_data or load_market_data(period, interval)
    regime_result = regime_result or get_regime(period, interval)
    spy_df = market_data.get("SPY")
    info = get_info(ticker) or {}
    news = get_news(ticker) or []

    # Safe defaults so downstream scoring never sees unbound optionality variables.
    optionality_total = 50.0
    optionality_meta = {
        "score": 50.0,
        "signal": "Not calculated",
        "summary": "Optionality analysis has not been calculated.",
        "metrics": {},
        "bull_points": [],
        "bear_points": [],
    }

    f_score, f_meta = fundamental_score(info)
    t_score, t_meta, xdf = technical_score(df, spy_df)
    l_res = analyze_liquidity(df, info)
    l_score = float(l_res.get("total", 50))
    l_meta = l_res.get("metrics", {}) | {k: v for k, v in l_res.items() if k != "metrics"}

    spot = float(df["Close"].iloc[-1])
    if include_options:
        exp, calls, puts = _extract_options_expiry_and_chains(ticker)
        o_score, o_meta = options_score(calls, puts, spot)
        o_meta["expiry"] = exp
    else:
        o_score, o_meta = 50.0, {"options_reasons": ["options disabled"]}

    c_score, c_meta = catalyst_score(news)
    try:
        e_score, e_meta = __import__("expectation_engine").expectation_score(info, df, f_meta, {"total": c_score, **c_meta})
    except Exception as exc:
        logger.warning("expectation score failed %s: %s", ticker, exc)
        e_score, e_meta = 50.0, {"expectation_read": "Expectation model unavailable", "expectation_reasons": [str(exc)]}

    try:
        g_score, g_meta = game_theory_score(t_meta, l_meta, o_meta, info)
    except Exception as exc:
        logger.warning("game score failed %s: %s", ticker, exc)
        g_score, g_meta = 50.0, {"participant_read": "Game theory model unavailable", "flags": [str(exc)]}

    try:
        merton_meta = analyze_merton_credit(ticker, {"ohlcv": df, "fundamentals": info, "risk_free_rate": 0.045})
        merton_score = float(merton_meta.get("score", 50))
    except Exception as exc:
        logger.warning("merton credit score failed %s: %s", ticker, exc)
        merton_score, merton_meta = 50.0, {"summary": "Merton credit model unavailable", "flags": [str(exc)], "metrics": {}}

    try:
        if is_neocloud_ticker(ticker, info):
            neocloud_profile = load_neocloud_profile(ticker)
            neocloud_meta = analyze_neocloud(ticker, {"fundamentals": info, "neocloud": neocloud_profile})
            neocloud_score = float(neocloud_meta.get("score", 50))
        else:
            neocloud_score = 50.0
            neocloud_meta = {
                "engine": "neocloud_valuation",
                "ticker": ticker,
                "score": 50.0,
                "signal": "Not a NeoCloud-specific name",
                "summary": "NeoCloud valuation not applicable to this ticker.",
                "flags": [],
                "metrics": {},
                "subscores": {},
            }
    except Exception as exc:
        logger.warning("neocloud score failed %s: %s", ticker, exc)
        neocloud_score, neocloud_meta = 50.0, {"summary": "NeoCloud valuation model unavailable", "flags": [str(exc)], "metrics": {}}

    try:
        theme_meta = analyze_theme(
            ticker=ticker,
            stock_df=df,
            market_data=market_data,
            news_items=news,
            sector=info.get("sector"),
            regime_result=regime_result,
        )
    except Exception as exc:
        logger.warning("theme score failed %s: %s", ticker, exc)
        theme_meta = {"total": 50, "summary": "Theme unavailable", "metrics": {}}

    # ============================================================
    # Optionality Engine: market-implied future option value
    # ============================================================
    try:
        if optionality_score is not None:
            optionality_total, optionality_meta = optionality_score(
                info=info,
                df=df,
                fund_meta=f_meta,
                expectation_meta=e_meta,
                greenfield_meta=neocloud_meta,
            )
            optionality_total = float(optionality_total)
        else:
            optionality_total = 50.0
            optionality_meta = {
                "score": 50.0,
                "signal": "Optionality engine unavailable",
                "summary": "Optionality analysis unavailable.",
                "metrics": {},
                "bull_points": [],
                "bear_points": [],
            }
    except Exception as exc:
        logger.warning("optionality score failed %s: %s", ticker, exc)
        optionality_total = 50.0
        optionality_meta = {
            "score": 50.0,
            "signal": "Optionality engine failed",
            "summary": f"Optionality analysis failed: {exc}",
            "metrics": {},
            "bull_points": [],
            "bear_points": [str(exc)],
        }

        
    # Technical v2: Trend + Entry + Leadership
    # ============================================================

    try:
        theme_peer_returns = {}

        if isinstance(theme_meta, dict):
            theme_peer_returns = (
                (theme_meta.get("metrics") or {}).get("theme_peer_returns")
                or theme_meta.get("theme_peer_returns")
                or {}
            )

        theme_name = (
            (theme_meta.get("metrics") or {}).get("theme")
            or theme_meta.get("theme")
        )

        engine_payload = {
            "ohlcv": df,
            "benchmark": spy_df,
            "sector": None,
            "theme": theme_name,
            "theme_peer_returns": theme_peer_returns,
        }

        trend_meta = analyze_trend_quality(ticker, engine_payload)
        entry_meta = analyze_entry_quality(ticker, engine_payload)
        leadership_meta = analyze_leadership(ticker, engine_payload)

        trend_score = float(trend_meta.get("score", 50))
        entry_score = float(entry_meta.get("score", 50))
        leadership_score = float(leadership_meta.get("score", 50))

        technical_legacy_score = float(t_score)

        technical_v2_score = round(
            0.40 * trend_score
            + 0.30 * entry_score
            + 0.30 * leadership_score,
            1,
        )

    except Exception as exc:
        logger.warning("technical v2 failed %s: %s", ticker, exc)

        technical_legacy_score = float(t_score)
        technical_v2_score = float(t_score)

        trend_score = 50.0
        entry_score = 50.0
        leadership_score = 50.0

        trend_meta = {"score": 50, "summary": "Trend quality unavailable", "signal": "Unavailable"}
        entry_meta = {"score": 50, "summary": "Entry quality unavailable", "signal": "Unavailable"}
        leadership_meta = {"score": 50, "summary": "Leadership unavailable", "signal": "Unavailable"}
    
    # scores = {
    #     "fundamental": float(f_score),
    #     "technical": float(t_score),
    #     "liquidity": float(l_score),
    #     "options": float(o_score),
    #     "game": float(g_score),
    #     "catalyst": float(c_score),
    #     "expectation": float(e_score),
    #     "merton": float(merton_score),
    #     "neocloud": float(neocloud_score),
    # }
    
    scores = {
        "fundamental": float(f_score),
        "technical": float(technical_v2_score),
        "technical_legacy": float(technical_legacy_score),
        "trend_quality": float(trend_score),
        "entry_quality": float(entry_score),
        "leadership": float(leadership_score),
        "technical_v2": float(technical_v2_score),
        "liquidity": float(l_score),
        "options": float(o_score),
        "game": float(g_score),
        "catalyst": float(c_score),
        "expectation": float(e_score),
        "merton": float(merton_score),
        "neocloud": float(neocloud_score),
        "optionality": float(optionality_total),
    }
    final_score = combine_scores(scores, DEFAULT_WEIGHTS)
    decision = classify(final_score, t_meta.get("setup_type", ""))
    setup_type = t_meta.get("setup_type", "")

    if trend_score >= 75 and leadership_score >= 65 and entry_score < 50:
        setup_type = "Strong trend / poor entry — wait for pullback or breakout"
    elif trend_score >= 75 and entry_score >= 60:
        setup_type = "Trend continuation entry"
    elif leadership_score >= 75 and entry_score < 50:
        setup_type = "Leadership name, no clean entry"
    levels = trade_levels(xdf, account_size=account_size, risk_pct=risk_pct)

    er = estimate_expected_return(
        ticker=ticker,
        df=df,
        scores={
            "final": final_score,
            # "technical": t_score,
            "technical": technical_v2_score,
            "technical_legacy": technical_legacy_score,
            "trend_quality": trend_score,
            "entry_quality": entry_score,
            "leadership": leadership_score,
            "liquidity": l_score,
            "options": o_score,
            "game": g_score,
            "catalyst": c_score,
            "theme": float(theme_meta.get("total", 50)),
            "expectation": e_score,
            "merton": merton_score,
            "neocloud": neocloud_score,
            "optionality": optionality_total,
        },
        metas={"technical": t_meta,
               "liquidity": l_meta,
               "options": o_meta, 
               "game": g_meta, 
               "theme": theme_meta,
               "expectation": e_meta,
               "merton": merton_meta, 
               "neocloud": neocloud_meta,
               "optionality": optionality_meta,
               },
        regime_result=regime_result,
        account_size=account_size,
        risk_per_trade=risk_pct,
    )

    # Prefer more refined expected-return levels if available.
    er_levels = er.get("levels") or {}
    for k_src, k_dst in [("entry", "entry"), ("stop", "stop"), ("target1", "target1"), ("target2", "target2")]:
        if er_levels.get(k_src) is not None:
            levels[k_dst] = er_levels[k_src]
    if er_levels.get("risk_reward") is not None:
        levels["rr"] = er_levels["risk_reward"]

    # thesis = build_thesis(ticker, decision, t_meta.get("setup_type", ""), f_meta, t_meta, l_meta, o_meta, g_meta, c_meta, e_meta)
    thesis = build_thesis(ticker, decision, setup_type, f_meta, t_meta, l_meta, o_meta, g_meta, c_meta, e_meta)
    thesis += f" Merton credit: {merton_meta.get('signal', 'n/a')} — {merton_meta.get('summary', 'n/a')}"
    if is_neocloud_ticker(ticker, info):
        thesis += f" NeoCloud valuation: {neocloud_meta.get('signal', 'n/a')} — {neocloud_meta.get('summary', 'n/a')}"
    thesis += f" Optionality: {optionality_meta.get('signal', 'n/a')} — {optionality_meta.get('summary', 'n/a')}"
    # row = result_row(ticker, final_score, decision, t_meta.get("setup_type", ""), levels, thesis)
    row = result_row(ticker, final_score, decision, setup_type, levels, thesis)

    result = {
        **row,
        "price": round(spot, 2),
        "scores": scores,
        "expected_return": er.get("expected_return"),  # legacy scenario EV
        "expected_r": er.get("expected_r"),
        "probability_win": er.get("probability_win"),

        "trade_expectancy_pct": er.get("trade_expectancy_pct"),
        "trade_expectancy_r": er.get("trade_expectancy_r"),
        "reward_pct": er.get("reward_pct"),
        "risk_pct": er.get("risk_pct"),
        "regime": regime_result.get("regime"),
        "theme": (theme_meta.get("metrics") or {}).get("theme") or theme_meta.get("theme"),
        "summary": {
            "fundamental": "; ".join(f_meta.get("fundamental_reasons", [])[:4]),
            # "technical": t_meta.get("setup_type"),    
            "technical": setup_type,
            "technical_legacy": t_meta.get("setup_type"),
            "trend_quality": trend_meta.get("summary"),
            "entry_quality": entry_meta.get("summary"),
            "leadership": leadership_meta.get("summary"),
            "liquidity": l_res.get("summary"),
            "options": o_meta.get("options_read"),
            "game_theory": g_meta.get("summary") or g_meta.get("participant_read"),
            "catalyst": c_meta.get("catalyst_read"),
            "expectation": e_meta.get("expectation_read"),
            "merton": merton_meta.get("summary"),
            "neocloud": neocloud_meta.get("summary"),
            "expected_return": er.get("summary"),
            "optionality": optionality_meta.get("summary"),
        },
        "metas": {
            "fundamental": f_meta,
            "technical": t_meta,
            "liquidity": l_meta,
            "options": o_meta,
            "game": g_meta,
            "catalyst": c_meta,
            "expectation": e_meta,
            "merton": merton_meta,
            "neocloud": neocloud_meta,
            "theme": theme_meta,
            "trend_quality": trend_meta,
            "entry_quality": entry_meta,
            "leadership": leadership_meta,
            "optionality": optionality_meta,
        },
    }

    # ============================================================
    # Phase-1 Decision Layer (shadow mode)
    # ============================================================
    # Interprets the completed engine outputs without changing the existing
    # score, classification, trade plan, persistence contract, or API fields.
    result["reasoning"] = build_reasoning(result)

    safe = _json_safe(result)
    if persist_signal and not safe.get("error"):
        save_signal(safe)
    return safe


def save_signal(signal: Dict[str, Any]) -> str:
    init_db()
    signal_id = signal.get("signal_id") or f"sig_{signal.get('ticker','NA')}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    payload = json.dumps(_json_safe(signal), default=str)
    with connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO signals(signal_id, created_at, ticker, decision, setup_type, final_score,
                expected_return, entry, stop, target1, target2, risk_reward, position_size, regime, theme, thesis, payload_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                signal_id,
                utc_now(),
                signal.get("ticker"),
                signal.get("decision"),
                signal.get("setup_type"),
                signal.get("final_score"),
                signal.get("expected_return"),
                signal.get("entry"),
                signal.get("stop"),
                signal.get("target1"),
                signal.get("target2"),
                signal.get("rr") or signal.get("risk_reward"),
                signal.get("position_size"),
                signal.get("regime"),
                signal.get("theme"),
                signal.get("thesis"),
                payload,
            ),
        )
    return signal_id


def scan_tickers(
    tickers: Iterable[str],
    period: str = "1y",
    interval: str = "1d",
    max_names: int = 50,
    min_price: float = 1.0,
    min_avg_dollar_volume: float = 1_000_000,
    include_options: bool = True,
) -> Dict[str, Any]:
    market_data = load_market_data(period, interval)
    regime = _json_safe(analyze_market_regime(market_data)) if market_data else {"regime": "UNKNOWN"}
    rows: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    for ticker in list(tickers)[:max_names]:
        try:
            res = analyze_stock(ticker, period, interval, regime_result=regime, market_data=market_data, include_options=include_options)
            if res.get("error"):
                errors.append({"ticker": ticker, "error": res["error"]})
                continue
            if res.get("price", 0) < min_price:
                continue
            avg_dollar = (((res.get("metas", {}).get("liquidity", {}) or {}).get("avg_dollar_vol")) or 0)
            if avg_dollar and avg_dollar < min_avg_dollar_volume:
                continue
            rows.append(res)
        except Exception as exc:
            logger.exception("scan failed for %s", ticker)
            errors.append({"ticker": ticker, "error": str(exc)})
    rows = sorted(rows, key=lambda r: r.get("final_score", 0), reverse=True)
    return {"as_of": utc_now(), "regime": regime, "count": len(rows), "results": _json_safe(rows), "errors": errors}


def build_daily_report(tickers: Iterable[str], title: str, max_names: int = 50, include_signal_records: bool = True) -> Dict[str, Any]:
    scan = scan_tickers(tickers, max_names=max_names)
    rows = scan["results"]
    market_data = load_market_data()
    themes_df = None
    try:
        # rank pre-defined themes using available market data
        themes_df = rank_themes(market_data)
    except Exception as exc:
        logger.warning("theme ranking failed: %s", exc)
    report = generate_daily_report(
        rows,
        regime=scan.get("regime"),
        theme_results=themes_df,
        config={"brand_name": "Trading Desk OS", "report_title": title},
        output_dir=settings.report_path,
        db_path=str(settings.db_path),
        record_signals=include_signal_records,
        save_files=True,
        save_sqlite=True,
    )
    out = {
        "report_id": report["report_id"],
        "report_date": report["report_date"],
        "executive_summary": report["executive_summary"],
        "telegram_text": report["telegram_text"],
        "markdown_text": report["markdown_text"],
        "html_text": report["html_text"],
        "paths": report["paths"],
        "signal_ids": report["signal_ids"],
        "scanner_count": len(rows),
    }
    return _json_safe(out)


def recent_signals(limit: int = 100) -> List[Dict[str, Any]]:
    init_db()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM signals ORDER BY created_at DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(r) for r in rows]
