"""
signal_outcome_db.py

Signal outcome tracking and learning database for Trading Desk OS.

Why it matters
--------------
The product becomes valuable only after it learns which combinations of factors
actually work. This module stores every generated signal and later updates the
outcome using future OHLCV data.

Main public API:
    init_signal_db(db_path=None)
    record_signal(signal_dict, db_path=None)
    update_signal_outcomes(price_data_by_ticker, db_path=None)
    get_outcome_stats(filters=None, db_path=None)
    export_signals(db_path=None) -> pd.DataFrame

The module uses SQLite and can coexist with your existing decision_app.db.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd

try:
    from utils import DB_PATH as DEFAULT_DB_PATH
except Exception:
    DEFAULT_DB_PATH = os.getenv("DECISION_APP_DB", "decision_app.db")

logger = logging.getLogger("trading_desk.signal_outcome_db")

SIGNALS_TABLE = "signal_outcomes"


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _connect(db_path: Optional[str] = None):
    return sqlite3.connect(db_path or DEFAULT_DB_PATH)


def init_signal_db(db_path: Optional[str] = None) -> None:
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS {SIGNALS_TABLE} (
        signal_id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        updated_at TEXT,
        ticker TEXT NOT NULL,
        direction TEXT,
        decision TEXT,
        setup_type TEXT,
        regime TEXT,
        theme TEXT,
        entry REAL,
        stop REAL,
        target1 REAL,
        target2 REAL,
        horizon_days INTEGER,
        final_score REAL,
        technical_score REAL,
        liquidity_score REAL,
        options_score REAL,
        game_score REAL,
        catalyst_score REAL,
        theme_score REAL,
        expected_return_score REAL,
        expected_return REAL,
        probability_win REAL,
        risk_reward REAL,
        thesis TEXT,
        status TEXT DEFAULT 'OPEN',
        outcome TEXT,
        realized_return REAL,
        realized_r REAL,
        max_favorable_excursion REAL,
        max_adverse_excursion REAL,
        exit_price REAL,
        exit_date TEXT,
        bars_held INTEGER,
        metadata_json TEXT
    )
    """)
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{SIGNALS_TABLE}_ticker ON {SIGNALS_TABLE}(ticker)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{SIGNALS_TABLE}_created ON {SIGNALS_TABLE}(created_at)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{SIGNALS_TABLE}_status ON {SIGNALS_TABLE}(status)")
    con.commit()
    con.close()


def _safe_float(x):
    try:
        if x is None or pd.isna(x):
            return None
        return float(x)
    except Exception:
        return None


def _safe_int(x):
    try:
        if x is None or pd.isna(x):
            return None
        return int(x)
    except Exception:
        return None


def record_signal(signal: Dict, db_path: Optional[str] = None) -> str:
    """Insert one signal and return signal_id.

    Expected signal keys are flexible. Common keys:
    ticker, direction, decision, setup_type, regime, theme, entry, stop, target1,
    target2, horizon_days, final_score, technical_score, liquidity_score,
    options_score, game_score, catalyst_score, theme_score, expected_return,
    probability_win, risk_reward, thesis, metadata.
    """
    init_signal_db(db_path)
    now = _utcnow()
    signal_id = str(signal.get("signal_id") or uuid.uuid4())
    metadata = signal.get("metadata") or signal.get("metadata_json") or {}
    if not isinstance(metadata, str):
        metadata = json.dumps(metadata, default=str)

    row = {
        "signal_id": signal_id,
        "created_at": signal.get("created_at") or now,
        "updated_at": now,
        "ticker": str(signal.get("ticker", "")).upper(),
        "direction": signal.get("direction"),
        "decision": signal.get("decision"),
        "setup_type": signal.get("setup_type"),
        "regime": signal.get("regime"),
        "theme": signal.get("theme"),
        "entry": _safe_float(signal.get("entry")),
        "stop": _safe_float(signal.get("stop")),
        "target1": _safe_float(signal.get("target1")),
        "target2": _safe_float(signal.get("target2")),
        "horizon_days": _safe_int(signal.get("horizon_days", 20)),
        "final_score": _safe_float(signal.get("final_score")),
        "technical_score": _safe_float(signal.get("technical_score")),
        "liquidity_score": _safe_float(signal.get("liquidity_score")),
        "options_score": _safe_float(signal.get("options_score")),
        "game_score": _safe_float(signal.get("game_score")),
        "catalyst_score": _safe_float(signal.get("catalyst_score")),
        "theme_score": _safe_float(signal.get("theme_score")),
        "expected_return_score": _safe_float(signal.get("expected_return_score")),
        "expected_return": _safe_float(signal.get("expected_return")),
        "probability_win": _safe_float(signal.get("probability_win")),
        "risk_reward": _safe_float(signal.get("risk_reward")),
        "thesis": signal.get("thesis"),
        "status": signal.get("status", "OPEN"),
        "metadata_json": metadata,
    }

    cols = list(row.keys())
    placeholders = ",".join(["?"] * len(cols))
    sql = f"INSERT OR REPLACE INTO {SIGNALS_TABLE} ({','.join(cols)}) VALUES ({placeholders})"
    con = _connect(db_path)
    con.execute(sql, [row[c] for c in cols])
    con.commit()
    con.close()
    return signal_id


def export_signals(db_path: Optional[str] = None, status: Optional[str] = None) -> pd.DataFrame:
    init_signal_db(db_path)
    con = _connect(db_path)
    try:
        where = ""
        params = []
        if status:
            where = "WHERE status = ?"
            params.append(status)
        return pd.read_sql(f"SELECT * FROM {SIGNALS_TABLE} {where} ORDER BY created_at DESC", con, params=params)
    finally:
        con.close()


def _normalize_price_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.get_level_values(0)
    out.columns = [str(c).title() for c in out.columns]
    out.index = pd.to_datetime(out.index)
    return out.dropna(how="all")


def _evaluate_one_signal(row: pd.Series, df: pd.DataFrame, mark_open_after_signal: bool = True) -> Dict:
    """Evaluate one open signal against future OHLCV bars."""
    df = _normalize_price_df(df)
    created = pd.to_datetime(row["created_at"], errors="coerce")
    if pd.isna(created):
        created = df.index.min()

    # Use bars after signal timestamp. Daily data timestamp may be date-only, so allow same-day when necessary.
    future = df[df.index >= created.tz_localize(None) if getattr(created, 'tzinfo', None) else df.index >= created]
    if future.empty:
        return {}

    horizon = int(row.get("horizon_days") or 20)
    future = future.head(horizon)
    entry = _safe_float(row.get("entry"))
    stop = _safe_float(row.get("stop"))
    target1 = _safe_float(row.get("target1"))
    target2 = _safe_float(row.get("target2"))
    direction = str(row.get("direction") or row.get("decision") or "LONG").upper()
    is_short = "SHORT" in direction

    if entry is None:
        entry = float(future["Close"].iloc[0])
    if stop is None:
        stop = entry * (1.05 if is_short else 0.95)

    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0:
        risk_per_share = max(entry * 0.02, 0.01)

    hit_target = False
    hit_stop = False
    exit_price = float(future["Close"].iloc[-1])
    exit_date = future.index[-1].isoformat()
    bars_held = len(future)
    outcome = "EXPIRED"

    mfe = -np.inf
    mae = np.inf

    for i, (idx, bar) in enumerate(future.iterrows(), start=1):
        high = float(bar.get("High", bar.get("Close")))
        low = float(bar.get("Low", bar.get("Close")))
        close = float(bar.get("Close"))

        if is_short:
            favorable = (entry - low) / entry
            adverse = (entry - high) / entry
            stop_hit = high >= stop
            target_hit = (target2 is not None and low <= target2) or (target1 is not None and low <= target1)
            chosen_target = target2 if target2 is not None else target1
        else:
            favorable = (high - entry) / entry
            adverse = (low - entry) / entry
            stop_hit = low <= stop
            target_hit = (target2 is not None and high >= target2) or (target1 is not None and high >= target1)
            chosen_target = target2 if target2 is not None else target1

        mfe = max(mfe, favorable)
        mae = min(mae, adverse)

        # Conservative: if both hit same bar, assume stop first.
        if stop_hit:
            hit_stop = True
            exit_price = stop
            exit_date = idx.isoformat()
            bars_held = i
            outcome = "STOP_HIT"
            break
        if target_hit:
            hit_target = True
            exit_price = chosen_target if chosen_target is not None else close
            exit_date = idx.isoformat()
            bars_held = i
            outcome = "TARGET_HIT"
            break

    if not hit_stop and not hit_target:
        final_close = float(future["Close"].iloc[-1])
        exit_price = final_close
        if is_short:
            outcome = "PROFIT" if final_close < entry else "LOSS"
        else:
            outcome = "PROFIT" if final_close > entry else "LOSS"

    realized_return = (entry - exit_price) / entry if is_short else (exit_price - entry) / entry
    realized_r = ((entry - exit_price) if is_short else (exit_price - entry)) / risk_per_share

    return {
        "status": "CLOSED",
        "outcome": outcome,
        "realized_return": float(realized_return),
        "realized_r": float(realized_r),
        "max_favorable_excursion": float(mfe if np.isfinite(mfe) else 0),
        "max_adverse_excursion": float(mae if np.isfinite(mae) else 0),
        "exit_price": float(exit_price),
        "exit_date": exit_date,
        "bars_held": int(bars_held),
        "updated_at": _utcnow(),
    }


def update_signal_outcomes(price_data_by_ticker: Dict[str, pd.DataFrame], db_path: Optional[str] = None) -> int:
    """Update all OPEN signals using supplied price data.

    price_data_by_ticker: {"NVDA": df, "PLTR": df, ...}
    Returns number of signals updated.
    """
    init_signal_db(db_path)
    open_df = export_signals(db_path, status="OPEN")
    if open_df.empty:
        return 0
    updates = []
    for _, row in open_df.iterrows():
        ticker = str(row["ticker"]).upper()
        df = None
        for k, v in (price_data_by_ticker or {}).items():
            if str(k).upper() == ticker:
                df = v
                break
        if df is None or df.empty:
            continue
        result = _evaluate_one_signal(row, df)
        if result:
            result["signal_id"] = row["signal_id"]
            updates.append(result)

    if not updates:
        return 0

    con = _connect(db_path)
    cur = con.cursor()
    for upd in updates:
        cols = [c for c in upd.keys() if c != "signal_id"]
        set_clause = ", ".join([f"{c} = ?" for c in cols])
        vals = [upd[c] for c in cols] + [upd["signal_id"]]
        cur.execute(f"UPDATE {SIGNALS_TABLE} SET {set_clause} WHERE signal_id = ?", vals)
    con.commit()
    con.close()
    return len(updates)


def get_outcome_stats(filters: Optional[Dict] = None, db_path: Optional[str] = None) -> Dict:
    """Aggregate performance stats for closed signals."""
    df = export_signals(db_path)
    if df.empty:
        return {"sample_size": 0}
    df = df[df["status"] == "CLOSED"].copy()
    filters = filters or {}
    for col, val in filters.items():
        if col in df.columns and val is not None:
            if isinstance(val, (list, tuple, set)):
                df = df[df[col].isin(val)]
            else:
                df = df[df[col] == val]
    if df.empty:
        return {"sample_size": 0}

    r = pd.to_numeric(df["realized_r"], errors="coerce").dropna()
    ret = pd.to_numeric(df["realized_return"], errors="coerce").dropna()
    wins = r > 0
    losses = r < 0
    gross_win = r[wins].sum() if wins.any() else 0.0
    gross_loss = abs(r[losses].sum()) if losses.any() else 0.0
    profit_factor = gross_win / gross_loss if gross_loss > 0 else np.inf if gross_win > 0 else 0.0

    return {
        "sample_size": int(len(df)),
        "win_rate": float(wins.mean()) if len(r) else None,
        "avg_r": float(r.mean()) if len(r) else None,
        "median_r": float(r.median()) if len(r) else None,
        "avg_return": float(ret.mean()) if len(ret) else None,
        "median_return": float(ret.median()) if len(ret) else None,
        "profit_factor": float(profit_factor) if np.isfinite(profit_factor) else 999.0,
        "avg_bars_held": float(pd.to_numeric(df["bars_held"], errors="coerce").mean()),
        "target_hit_rate": float(df["outcome"].astype(str).eq("TARGET_HIT").mean()),
        "stop_hit_rate": float(df["outcome"].astype(str).eq("STOP_HIT").mean()),
    }


def factor_performance_report(db_path: Optional[str] = None, min_n: int = 10) -> pd.DataFrame:
    """Return performance grouped by important factors.

    Useful to discover combinations like: RISK_ON + AI Infrastructure + high
    game_score actually works.
    """
    df = export_signals(db_path)
    if df.empty:
        return pd.DataFrame()
    df = df[df["status"] == "CLOSED"].copy()
    if df.empty:
        return pd.DataFrame()
    df["realized_r"] = pd.to_numeric(df["realized_r"], errors="coerce")
    rows = []
    for group_col in ["regime", "theme", "setup_type", "decision"]:
        if group_col not in df:
            continue
        for key, g in df.groupby(group_col):
            if len(g) < min_n:
                continue
            r = g["realized_r"].dropna()
            rows.append({
                "factor": group_col,
                "value": key,
                "n": len(g),
                "win_rate": float((r > 0).mean()) if len(r) else np.nan,
                "avg_r": float(r.mean()) if len(r) else np.nan,
                "median_r": float(r.median()) if len(r) else np.nan,
            })
    return pd.DataFrame(rows).sort_values(["avg_r", "win_rate"], ascending=False).reset_index(drop=True)


def record_from_app_outputs(
    ticker: str,
    final_row: Dict,
    scores: Dict,
    metas: Dict,
    expected_return_result: Optional[dict] = None,
    regime_result: Optional[dict] = None,
    theme_result: Optional[dict] = None,
    db_path: Optional[str] = None,
) -> str:
    """Convenience adapter for your Streamlit scanner output."""
    er = expected_return_result or {}
    levels = er.get("levels", {}) or {}
    signal = {
        "ticker": ticker,
        "direction": er.get("metrics", {}).get("direction") or final_row.get("direction"),
        "decision": er.get("decision") or final_row.get("decision"),
        "setup_type": final_row.get("setup_type"),
        "regime": (regime_result or {}).get("regime"),
        "theme": (theme_result or {}).get("theme"),
        "entry": levels.get("entry") or final_row.get("entry"),
        "stop": levels.get("stop") or final_row.get("stop"),
        "target1": levels.get("target1") or final_row.get("target1"),
        "target2": levels.get("target2") or final_row.get("target2"),
        "final_score": scores.get("final") or scores.get("final_score"),
        "technical_score": scores.get("technical"),
        "liquidity_score": scores.get("liquidity"),
        "options_score": scores.get("options"),
        "game_score": scores.get("game") or scores.get("game_theory"),
        "catalyst_score": scores.get("catalyst"),
        "theme_score": (theme_result or {}).get("total"),
        "expected_return_score": er.get("total"),
        "expected_return": er.get("expected_return"),
        "probability_win": er.get("probability_win"),
        "risk_reward": levels.get("risk_reward") or final_row.get("rr"),
        "thesis": er.get("summary") or final_row.get("thesis"),
        "metadata": {"scores": scores, "metas": metas, "expected_return": er, "regime": regime_result, "theme": theme_result},
    }
    return record_signal(signal, db_path=db_path)
