"""
daily_report_generator.py

Business/reporting layer for Trading Desk OS.

Purpose
-------
Convert scanner/model outputs into monetizable daily research artifacts:
    - HTML report
    - Markdown/email text
    - Telegram-safe concise text
    - CSV scanner table
    - SQLite report archive
    - Optional signal outcome recording

This module intentionally avoids fetching data. It consumes already-computed
outputs from your scanner/app modules so it can be used in Streamlit, cron jobs,
notebooks, or a backend API.

Main public API
---------------
    generate_daily_report(...)
    save_report_to_sqlite(...)
    load_recent_reports(...)
    build_report_from_scanner_df(...)

Typical use
-----------
    from daily_report_generator import generate_daily_report

    result = generate_daily_report(
        scanner_results=df,
        regime=regime_meta,
        theme_results=theme_df,
        output_dir="reports",
        db_path="decision_app.db",
        record_signals=True,
    )

    print(result["telegram_text"])
    print(result["html_path"])
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

try:
    from utils import DB_PATH as DEFAULT_DB_PATH
except Exception:
    DEFAULT_DB_PATH = os.getenv("DECISION_APP_DB", "decision_app.db")

try:
    from signal_outcome_db import record_signal
except Exception:  # module may not be present in early app versions
    record_signal = None

logger = logging.getLogger("trading_desk.daily_report_generator")

REPORTS_TABLE = "daily_reports"
REPORT_ITEMS_TABLE = "daily_report_items"


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class ReportConfig:
    report_title: str = "Trading Desk OS Daily Report"
    base_currency: str = "USD"
    top_n_longs: int = 10
    top_n_shorts: int = 10
    top_n_squeeze: int = 5
    top_n_avoid: int = 5
    min_long_score: float = 65.0
    max_short_score: float = 35.0
    min_squeeze_score: float = 70.0
    risk_per_trade_pct: float = 0.50
    account_equity: Optional[float] = None
    report_timezone: str = "UTC"
    include_disclaimer: bool = True
    brand_name: str = "Trading Desk OS"
    analyst_name: Optional[str] = None


# =============================================================================
# Generic helpers
# =============================================================================

def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _slugify(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", str(text).strip())
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "report"


def _safe_float(x: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if x is None or pd.isna(x):
            return default
        return float(x)
    except Exception:
        return default


def _safe_str(x: Any, default: str = "") -> str:
    if x is None:
        return default
    try:
        if pd.isna(x):
            return default
    except Exception:
        pass
    return str(x)


def _fmt_num(x: Any, digits: int = 2, na: str = "—") -> str:
    val = _safe_float(x)
    if val is None:
        return na
    return f"{val:,.{digits}f}"


def _fmt_pct(x: Any, digits: int = 1, na: str = "—") -> str:
    val = _safe_float(x)
    if val is None:
        return na
    # Accept either decimal or percent-like values.
    if abs(val) <= 1.5:
        val *= 100
    return f"{val:,.{digits}f}%"


def _fmt_price(x: Any, na: str = "—") -> str:
    val = _safe_float(x)
    if val is None:
        return na
    if abs(val) >= 1000:
        return f"{val:,.2f}"
    if abs(val) >= 10:
        return f"{val:.2f}"
    return f"{val:.4f}"


def _json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, default=str, ensure_ascii=False)
    except Exception:
        return json.dumps(str(obj))


def _coalesce(row: Union[pd.Series, Dict[str, Any]], keys: Iterable[str], default: Any = None) -> Any:
    for key in keys:
        try:
            if key in row and row[key] is not None and not pd.isna(row[key]):
                return row[key]
        except Exception:
            if isinstance(row, dict) and key in row and row[key] is not None:
                return row[key]
    return default


# =============================================================================
# Normalization layer
# =============================================================================

def normalize_scanner_results(scanner_results: Union[pd.DataFrame, List[Dict[str, Any]]]) -> pd.DataFrame:
    """Normalize arbitrary scanner rows into the reporting schema.

    The current app has evolved across many modules, so this function accepts
    several likely column names and maps them to standard fields.
    """
    if scanner_results is None:
        return pd.DataFrame()
    df = pd.DataFrame(scanner_results).copy()
    if df.empty:
        return df

    # Flatten nested dict values when common module outputs were stored as dicts.
    for col in list(df.columns):
        if df[col].map(lambda x: isinstance(x, dict)).any():
            # Keep original but extract common nested keys.
            for key in ["total", "score", "summary", "flags"]:
                new_col = f"{col}_{key}"
                if new_col not in df.columns:
                    df[new_col] = df[col].map(lambda d: d.get(key) if isinstance(d, dict) else None)

    mapping = {
        "ticker": ["ticker", "Ticker", "symbol", "Symbol"],
        "final_score": ["final_score", "Final Score", "total", "score", "combined_score"],
        "decision": ["decision", "Final Decision", "signal", "rating"],
        "setup_type": ["setup_type", "Setup Type", "setup", "pattern"],
        "entry": ["entry", "Best Entry", "entry_price", "entry_zone", "best_entry"],
        "stop": ["stop", "Stop Loss", "stop_loss", "invalid_level"],
        "target1": ["target1", "Target 1", "target_1", "t1"],
        "target2": ["target2", "Target 2", "target_2", "t2"],
        "risk_reward": ["risk_reward", "rr", "Risk/Reward", "R/R"],
        "position_size": ["position_size", "Position Size", "shares", "size"],
        "expected_return": ["expected_return", "Expected Return", "ev_return", "base_return"],
        "probability_win": ["probability_win", "Probability", "win_probability", "prob_win"],
        "thesis": ["thesis", "Final Thesis", "trade_thesis", "summary"],
        "bull_case": ["bull_case", "Main Bull Case", "bull"],
        "bear_case": ["bear_case", "Main Bear Case", "bear"],
        "options_read": ["options_read", "Options Read", "options_summary", "options_total_summary"],
        "game_theory_read": ["game_theory_read", "Game Theory Read", "game_summary", "game_total_summary"],
        "catalyst_read": ["catalyst_read", "Catalyst Read", "catalyst_summary", "catalyst_total_summary"],
        "theme": ["theme", "Theme", "best_theme"],
        "theme_score": ["theme_score", "Theme Score"],
        "regime": ["regime", "Regime", "market_regime"],
        "technical_score": ["technical_score", "Technical Score", "technical_total"],
        "liquidity_score": ["liquidity_score", "Liquidity Score", "liquidity_total"],
        "options_score": ["options_score", "Options Score", "options_total"],
        "game_score": ["game_score", "Game Score", "game_theory_score", "game_total"],
        "catalyst_score": ["catalyst_score", "Catalyst Score", "catalyst_total"],
        "fundamental_score": ["fundamental_score", "Fundamental Score", "fundamentals_score"],
        "squeeze_score": ["squeeze_score", "gamma_squeeze_score", "short_squeeze_score"],
    }

    out = pd.DataFrame(index=df.index)
    for target, candidates in mapping.items():
        chosen = None
        for c in candidates:
            if c in df.columns:
                chosen = c
                break
        out[target] = df[chosen] if chosen else None

    # Preserve any unrecognized original columns for downstream users.
    for col in df.columns:
        if col not in out.columns:
            out[col] = df[col]

    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out = out[out["ticker"].ne("") & out["ticker"].ne("NAN")]

    numeric_cols = [
        "final_score", "entry", "stop", "target1", "target2", "risk_reward",
        "position_size", "expected_return", "probability_win", "theme_score",
        "technical_score", "liquidity_score", "options_score", "game_score",
        "catalyst_score", "fundamental_score", "squeeze_score",
    ]
    for col in numeric_cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    out["final_score"] = out["final_score"].fillna(50.0)
    out["decision"] = out.apply(_infer_decision, axis=1)
    out["direction"] = out.apply(_infer_direction, axis=1)
    out["risk_reward"] = out.apply(_infer_risk_reward, axis=1)
    out["thesis"] = out.apply(_infer_thesis, axis=1)

    return out.sort_values("final_score", ascending=False).reset_index(drop=True)


def _infer_decision(row: pd.Series) -> str:
    decision = _safe_str(row.get("decision"), "").strip()
    if decision:
        return decision
    score = _safe_float(row.get("final_score"), 50) or 50
    if score >= 80:
        return "Strong Long"
    if score >= 65:
        return "Tactical Long"
    if score <= 20:
        return "Strong Short"
    if score <= 35:
        return "Tactical Short"
    return "Watchlist Only"


def _infer_direction(row: pd.Series) -> str:
    decision = _safe_str(row.get("decision"), "").upper()
    if "SHORT" in decision or "SELL" in decision:
        return "SHORT"
    if "LONG" in decision or "BUY" in decision:
        return "LONG"
    score = _safe_float(row.get("final_score"), 50) or 50
    if score >= 60:
        return "LONG"
    if score <= 40:
        return "SHORT"
    return "NEUTRAL"


def _infer_risk_reward(row: pd.Series) -> Optional[float]:
    rr = _safe_float(row.get("risk_reward"))
    if rr is not None:
        return rr
    entry, stop, t1 = _safe_float(row.get("entry")), _safe_float(row.get("stop")), _safe_float(row.get("target1"))
    direction = _infer_direction(row)
    if entry is None or stop is None or t1 is None:
        return None
    risk = abs(entry - stop)
    reward = abs(t1 - entry)
    if risk <= 0:
        return None
    return reward / risk


def _infer_thesis(row: pd.Series) -> str:
    thesis = _safe_str(row.get("thesis"), "").strip()
    if thesis:
        return thesis
    parts = []
    ticker = _safe_str(row.get("ticker"), "This stock")
    decision = _safe_str(row.get("decision"), "Watchlist Only")
    score = _safe_float(row.get("final_score"), 50) or 50
    setup = _safe_str(row.get("setup_type"), "multi-factor setup")
    parts.append(f"{ticker} is classified as {decision} with a {score:.1f} final score based on a {setup}.")
    for label, col in [
        ("technical", "technical_score"),
        ("liquidity", "liquidity_score"),
        ("options", "options_score"),
        ("game theory", "game_score"),
        ("catalyst", "catalyst_score"),
    ]:
        val = _safe_float(row.get(col))
        if val is not None:
            parts.append(f"{label} score {val:.0f}")
    return " ".join(parts)


# =============================================================================
# Report sections
# =============================================================================

def split_idea_buckets(df: pd.DataFrame, cfg: ReportConfig) -> Dict[str, pd.DataFrame]:
    if df.empty:
        return {"longs": df, "shorts": df, "squeeze": df, "avoid": df}

    decision_upper = df["decision"].astype(str).str.upper()
    direction_upper = df["direction"].astype(str).str.upper()

    longs = df[(direction_upper.eq("LONG") | decision_upper.str.contains("LONG|BUY", regex=True)) & (df["final_score"] >= cfg.min_long_score)]
    longs = longs.sort_values("final_score", ascending=False).head(cfg.top_n_longs)

    shorts = df[(direction_upper.eq("SHORT") | decision_upper.str.contains("SHORT|SELL", regex=True)) | (df["final_score"] <= cfg.max_short_score)]
    shorts = shorts.sort_values("final_score", ascending=True).head(cfg.top_n_shorts)

    if "squeeze_score" in df.columns and df["squeeze_score"].notna().any():
        squeeze = df[df["squeeze_score"] >= cfg.min_squeeze_score].sort_values("squeeze_score", ascending=False).head(cfg.top_n_squeeze)
    else:
        # Fallback: high game/options/liquidity combo.
        tmp = df.copy()
        for c in ["game_score", "options_score", "liquidity_score"]:
            if c not in tmp.columns:
                tmp[c] = np.nan
        tmp["synthetic_squeeze_score"] = tmp[["game_score", "options_score", "liquidity_score"]].mean(axis=1)
        squeeze = tmp[tmp["synthetic_squeeze_score"] >= cfg.min_squeeze_score].sort_values("synthetic_squeeze_score", ascending=False).head(cfg.top_n_squeeze)

    avoid = df[(df["final_score"] < 45) | decision_upper.str.contains("AVOID|WATCH", regex=True)]
    avoid = avoid.sort_values("final_score", ascending=True).head(cfg.top_n_avoid)

    return {"longs": longs, "shorts": shorts, "squeeze": squeeze, "avoid": avoid}


def summarize_regime(regime: Optional[Union[Dict[str, Any], pd.Series]]) -> Dict[str, Any]:
    if regime is None:
        return {"regime": "UNKNOWN", "summary": "Market regime data unavailable.", "risk_on_probability": None, "risk_off_probability": None, "chop_probability": None}
    if isinstance(regime, pd.Series):
        regime = regime.to_dict()
    out = dict(regime)
    reg = _safe_str(_coalesce(out, ["regime", "label", "state", "market_regime"], "UNKNOWN"), "UNKNOWN")
    summary = _safe_str(_coalesce(out, ["summary", "read", "description"], ""), "")
    if not summary:
        ro = _coalesce(out, ["risk_on_probability", "risk_on", "risk_on_prob"])
        rf = _coalesce(out, ["risk_off_probability", "risk_off", "risk_off_prob"])
        chop = _coalesce(out, ["chop_probability", "chop", "chop_prob"])
        summary = f"Market regime: {reg}. Risk-on {_fmt_pct(ro)}, risk-off {_fmt_pct(rf)}, chop {_fmt_pct(chop)}."
    out["regime"] = reg
    out["summary"] = summary
    return out


def summarize_themes(theme_results: Optional[Union[pd.DataFrame, List[Dict[str, Any]], Dict[str, Any]]], top_n: int = 5) -> pd.DataFrame:
    if theme_results is None:
        return pd.DataFrame(columns=["theme", "score", "summary"])
    if isinstance(theme_results, dict):
        if "themes" in theme_results and isinstance(theme_results["themes"], (list, pd.DataFrame)):
            df = pd.DataFrame(theme_results["themes"])
        else:
            df = pd.DataFrame([theme_results])
    else:
        df = pd.DataFrame(theme_results)
    if df.empty:
        return pd.DataFrame(columns=["theme", "score", "summary"])

    cols = {c.lower(): c for c in df.columns}
    theme_col = cols.get("theme") or cols.get("name") or cols.get("sector") or df.columns[0]
    score_col = cols.get("score") or cols.get("theme_score") or cols.get("total")
    summary_col = cols.get("summary") or cols.get("read") or cols.get("description")

    out = pd.DataFrame()
    out["theme"] = df[theme_col].astype(str)
    out["score"] = pd.to_numeric(df[score_col], errors="coerce") if score_col else np.nan
    out["summary"] = df[summary_col].astype(str) if summary_col else ""
    return out.sort_values("score", ascending=False, na_position="last").head(top_n).reset_index(drop=True)


def build_executive_summary(df: pd.DataFrame, buckets: Dict[str, pd.DataFrame], regime_meta: Dict[str, Any], themes: pd.DataFrame) -> str:
    if df.empty:
        return "No scanner rows were available for today."
    top_long = buckets["longs"].iloc[0] if not buckets["longs"].empty else None
    top_short = buckets["shorts"].iloc[0] if not buckets["shorts"].empty else None
    top_theme = themes.iloc[0] if themes is not None and not themes.empty else None

    parts = [f"Today’s market regime is {regime_meta.get('regime', 'UNKNOWN')}."]
    if top_theme is not None:
        parts.append(f"The strongest theme is {top_theme['theme']} with a score of {_fmt_num(top_theme.get('score'), 1)}.")
    if top_long is not None:
        parts.append(f"Top long candidate: {top_long['ticker']} ({top_long['decision']}, score {_fmt_num(top_long['final_score'], 1)}).")
    if top_short is not None:
        parts.append(f"Top short/fade candidate: {top_short['ticker']} ({top_short['decision']}, score {_fmt_num(top_short['final_score'], 1)}).")
    parts.append(f"The report contains {len(buckets['longs'])} long ideas, {len(buckets['shorts'])} short/fade ideas, {len(buckets['squeeze'])} squeeze candidates, and {len(buckets['avoid'])} avoid/watchlist names.")
    return " ".join(parts)


# =============================================================================
# Text renderers
# =============================================================================

def _idea_line(row: pd.Series, rank: int, compact: bool = False) -> str:
    ticker = _safe_str(row.get("ticker"))
    decision = _safe_str(row.get("decision"))
    score = _fmt_num(row.get("final_score"), 1)
    setup = _safe_str(row.get("setup_type"), "Setup")
    entry = _fmt_price(row.get("entry"))
    stop = _fmt_price(row.get("stop"))
    t1 = _fmt_price(row.get("target1"))
    rr = _fmt_num(row.get("risk_reward"), 2)
    ev = _fmt_pct(row.get("expected_return"), 1)
    if compact:
        return f"{rank}. {ticker} | {decision} | Score {score} | Entry {entry} | Stop {stop} | T1 {t1} | RR {rr}"
    thesis = _safe_str(row.get("thesis"), "")
    return (
        f"{rank}. {ticker} — {decision} | Score {score}\n"
        f"   Setup: {setup}\n"
        f"   Entry: {entry} | Stop: {stop} | Target 1: {t1} | R/R: {rr} | EV: {ev}\n"
        f"   Thesis: {thesis}"
    )


def render_markdown_report(
    report_id: str,
    report_date: str,
    cfg: ReportConfig,
    executive_summary: str,
    regime_meta: Dict[str, Any],
    themes: pd.DataFrame,
    buckets: Dict[str, pd.DataFrame],
) -> str:
    lines = []
    lines.append(f"# {cfg.report_title}")
    lines.append(f"**Report ID:** `{report_id}`  ")
    lines.append(f"**Generated:** {report_date}  ")
    if cfg.analyst_name:
        lines.append(f"**Analyst:** {cfg.analyst_name}  ")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append(executive_summary)
    lines.append("")
    lines.append("## Market Regime")
    lines.append(_safe_str(regime_meta.get("summary"), "Market regime unavailable."))
    lines.append("")

    lines.append("## Strongest Themes")
    if themes.empty:
        lines.append("Theme data unavailable.")
    else:
        for i, row in themes.iterrows():
            summary = _safe_str(row.get("summary"), "")
            line = f"{i+1}. **{row['theme']}** — Score {_fmt_num(row.get('score'), 1)}"
            if summary:
                line += f" — {summary}"
            lines.append(line)
    lines.append("")

    section_specs = [
        ("Top Long Ideas", "longs"),
        ("Top Short / Fade Ideas", "shorts"),
        ("Squeeze Candidates", "squeeze"),
        ("Avoid / Trap Setups", "avoid"),
    ]
    for title, key in section_specs:
        lines.append(f"## {title}")
        sub = buckets.get(key, pd.DataFrame())
        if sub.empty:
            lines.append("No qualifying names.")
        else:
            for i, (_, row) in enumerate(sub.iterrows(), start=1):
                lines.append(_idea_line(row, i, compact=False))
                lines.append("")
        lines.append("")

    if cfg.include_disclaimer:
        lines.append("---")
        lines.append("**Disclaimer:** This report is for research and educational purposes only. It is not financial advice, a recommendation, or an offer to buy or sell securities. Trading involves substantial risk, including loss of principal. Validate all data and use your own risk controls.")

    return "\n".join(lines).strip() + "\n"


def render_telegram_text(
    report_date: str,
    cfg: ReportConfig,
    executive_summary: str,
    regime_meta: Dict[str, Any],
    themes: pd.DataFrame,
    buckets: Dict[str, pd.DataFrame],
    max_chars: int = 3900,
) -> str:
    lines = [
        f"📊 {cfg.brand_name} Daily Report",
        f"Generated: {report_date}",
        "",
        f"Regime: {regime_meta.get('regime', 'UNKNOWN')}",
        executive_summary,
        "",
    ]
    if not themes.empty:
        theme_bits = [f"{r.theme}({_fmt_num(r.score,0)})" for r in themes.itertuples(index=False)]
        lines.append("🔥 Themes: " + ", ".join(theme_bits[:5]))
        lines.append("")

    for title, key, emoji in [
        ("Top Longs", "longs", "🟢"),
        ("Top Shorts/Fades", "shorts", "🔴"),
        ("Squeeze Watch", "squeeze", "⚡"),
    ]:
        sub = buckets.get(key, pd.DataFrame())
        lines.append(f"{emoji} {title}")
        if sub.empty:
            lines.append("None")
        else:
            for i, (_, row) in enumerate(sub.head(5).iterrows(), start=1):
                lines.append(_idea_line(row, i, compact=True))
        lines.append("")

    if cfg.include_disclaimer:
        lines.append("Research only. Not financial advice.")

    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 60].rstrip() + "\n… truncated. See full HTML/Markdown report."
    return text


def render_html_report(markdown_text: str, cfg: ReportConfig, scanner_df: pd.DataFrame) -> str:
    """Render simple self-contained HTML without requiring markdown dependency."""
    # Lightweight markdown-ish conversion for headings and bold.
    body_lines = []
    in_ul = False
    for raw in markdown_text.splitlines():
        line = html.escape(raw)
        if line.startswith("# "):
            body_lines.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            body_lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("---"):
            body_lines.append("<hr>")
        elif re.match(r"^\d+\. ", raw):
            body_lines.append(f"<p class='idea'>{line}</p>")
        elif line.strip() == "":
            body_lines.append("")
        else:
            line = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", line)
            body_lines.append(f"<p>{line}</p>")

    table_html = ""
    if scanner_df is not None and not scanner_df.empty:
        cols = [c for c in ["ticker", "decision", "final_score", "setup_type", "entry", "stop", "target1", "target2", "risk_reward", "expected_return", "theme"] if c in scanner_df.columns]
        table_df = scanner_df[cols].copy().head(50)
        table_html = table_df.to_html(index=False, escape=True, classes="scanner-table", border=0)

    css = """
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; margin: 36px; color: #172033; background: #fafafa; }
    .container { max-width: 1120px; margin: auto; background: white; padding: 32px; border-radius: 16px; box-shadow: 0 4px 24px rgba(0,0,0,.06); }
    h1 { margin-top: 0; font-size: 32px; }
    h2 { margin-top: 34px; border-bottom: 1px solid #e5e7eb; padding-bottom: 8px; }
    p { line-height: 1.52; }
    .idea { white-space: pre-wrap; background: #f8fafc; border-left: 4px solid #64748b; padding: 12px 14px; border-radius: 8px; }
    .scanner-table { width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 14px; }
    .scanner-table th { background: #0f172a; color: white; padding: 9px; text-align: left; }
    .scanner-table td { border-bottom: 1px solid #e5e7eb; padding: 8px; }
    .footer { margin-top: 32px; font-size: 12px; color: #64748b; }
    """
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(cfg.report_title)}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
{''.join(body_lines)}
<h2>Scanner Table</h2>
{table_html}
<div class="footer">Generated by {html.escape(cfg.brand_name)}.</div>
</div>
</body>
</html>"""


# =============================================================================
# Persistence
# =============================================================================

def _connect(db_path: Optional[str] = None):
    return sqlite3.connect(db_path or DEFAULT_DB_PATH)


def init_report_db(db_path: Optional[str] = None) -> None:
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS {REPORTS_TABLE} (
        report_id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        report_date TEXT,
        title TEXT,
        regime TEXT,
        executive_summary TEXT,
        markdown_text TEXT,
        html_path TEXT,
        markdown_path TEXT,
        csv_path TEXT,
        telegram_text TEXT,
        metadata_json TEXT
    )
    """)
    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS {REPORT_ITEMS_TABLE} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id TEXT NOT NULL,
        bucket TEXT,
        rank INTEGER,
        ticker TEXT,
        decision TEXT,
        final_score REAL,
        setup_type TEXT,
        entry REAL,
        stop REAL,
        target1 REAL,
        target2 REAL,
        risk_reward REAL,
        expected_return REAL,
        thesis TEXT,
        metadata_json TEXT
    )
    """)
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{REPORT_ITEMS_TABLE}_report ON {REPORT_ITEMS_TABLE}(report_id)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{REPORTS_TABLE}_created ON {REPORTS_TABLE}(created_at)")
    con.commit()
    con.close()


def save_report_to_sqlite(
    report_id: str,
    report_date: str,
    cfg: ReportConfig,
    regime_meta: Dict[str, Any],
    executive_summary: str,
    markdown_text: str,
    telegram_text: str,
    buckets: Dict[str, pd.DataFrame],
    paths: Dict[str, Optional[str]],
    metadata: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> None:
    init_report_db(db_path)
    con = _connect(db_path)
    try:
        con.execute(
            f"""
            INSERT OR REPLACE INTO {REPORTS_TABLE}
            (report_id, created_at, report_date, title, regime, executive_summary, markdown_text,
             html_path, markdown_path, csv_path, telegram_text, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                report_id,
                _utcnow(),
                report_date,
                cfg.report_title,
                _safe_str(regime_meta.get("regime")),
                executive_summary,
                markdown_text,
                paths.get("html_path"),
                paths.get("markdown_path"),
                paths.get("csv_path"),
                telegram_text,
                _json_dumps(metadata or {}),
            ],
        )
        con.execute(f"DELETE FROM {REPORT_ITEMS_TABLE} WHERE report_id = ?", [report_id])
        for bucket, sub in buckets.items():
            if sub is None or sub.empty:
                continue
            for rank, (_, row) in enumerate(sub.iterrows(), start=1):
                con.execute(
                    f"""
                    INSERT INTO {REPORT_ITEMS_TABLE}
                    (report_id, bucket, rank, ticker, decision, final_score, setup_type, entry, stop,
                     target1, target2, risk_reward, expected_return, thesis, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        report_id,
                        bucket,
                        rank,
                        _safe_str(row.get("ticker")),
                        _safe_str(row.get("decision")),
                        _safe_float(row.get("final_score")),
                        _safe_str(row.get("setup_type")),
                        _safe_float(row.get("entry")),
                        _safe_float(row.get("stop")),
                        _safe_float(row.get("target1")),
                        _safe_float(row.get("target2")),
                        _safe_float(row.get("risk_reward")),
                        _safe_float(row.get("expected_return")),
                        _safe_str(row.get("thesis")),
                        _json_dumps(row.to_dict()),
                    ],
                )
        con.commit()
    finally:
        con.close()


def load_recent_reports(db_path: Optional[str] = None, limit: int = 20) -> pd.DataFrame:
    init_report_db(db_path)
    con = _connect(db_path)
    try:
        return pd.read_sql(
            f"SELECT report_id, created_at, report_date, title, regime, executive_summary, html_path, markdown_path, csv_path FROM {REPORTS_TABLE} ORDER BY created_at DESC LIMIT ?",
            con,
            params=[limit],
        )
    finally:
        con.close()


# =============================================================================
# Signal recording / position sizing
# =============================================================================

def add_position_sizing(df: pd.DataFrame, cfg: ReportConfig) -> pd.DataFrame:
    out = df.copy()
    if cfg.account_equity is None or cfg.account_equity <= 0:
        return out
    risk_dollars = cfg.account_equity * (cfg.risk_per_trade_pct / 100.0)
    sizes = []
    for _, row in out.iterrows():
        entry, stop = _safe_float(row.get("entry")), _safe_float(row.get("stop"))
        if entry is None or stop is None:
            sizes.append(np.nan)
            continue
        per_share_risk = abs(entry - stop)
        if per_share_risk <= 0:
            sizes.append(np.nan)
        else:
            sizes.append(np.floor(risk_dollars / per_share_risk))
    out["position_size"] = out.get("position_size", pd.Series(index=out.index, dtype=float)).fillna(pd.Series(sizes, index=out.index))
    return out


def record_report_signals(buckets: Dict[str, pd.DataFrame], db_path: Optional[str] = None) -> List[str]:
    signal_ids = []
    if record_signal is None:
        logger.warning("signal_outcome_db.record_signal is unavailable; skipping signal recording")
        return signal_ids
    for bucket, sub in buckets.items():
        if sub is None or sub.empty:
            continue
        for _, row in sub.iterrows():
            direction = _infer_direction(row)
            if direction == "NEUTRAL" or bucket == "avoid":
                continue
            signal = {
                "ticker": row.get("ticker"),
                "direction": direction,
                "decision": row.get("decision"),
                "setup_type": row.get("setup_type"),
                "regime": row.get("regime"),
                "theme": row.get("theme"),
                "entry": row.get("entry"),
                "stop": row.get("stop"),
                "target1": row.get("target1"),
                "target2": row.get("target2"),
                "final_score": row.get("final_score"),
                "technical_score": row.get("technical_score"),
                "liquidity_score": row.get("liquidity_score"),
                "options_score": row.get("options_score"),
                "game_score": row.get("game_score"),
                "catalyst_score": row.get("catalyst_score"),
                "theme_score": row.get("theme_score"),
                "expected_return": row.get("expected_return"),
                "probability_win": row.get("probability_win"),
                "risk_reward": row.get("risk_reward"),
                "thesis": row.get("thesis"),
                "metadata": {"report_bucket": bucket, "source": "daily_report_generator"},
            }
            try:
                signal_ids.append(record_signal(signal, db_path=db_path))
            except Exception as exc:
                logger.exception("Failed to record signal for %s: %s", row.get("ticker"), exc)
    return signal_ids


# =============================================================================
# Main generator
# =============================================================================

def generate_daily_report(
    scanner_results: Union[pd.DataFrame, List[Dict[str, Any]]],
    regime: Optional[Union[Dict[str, Any], pd.Series]] = None,
    theme_results: Optional[Union[pd.DataFrame, List[Dict[str, Any]], Dict[str, Any]]] = None,
    config: Optional[Union[ReportConfig, Dict[str, Any]]] = None,
    output_dir: Union[str, Path] = "reports",
    db_path: Optional[str] = None,
    report_date: Optional[str] = None,
    report_id: Optional[str] = None,
    save_sqlite: bool = True,
    record_signals: bool = False,
    save_files: bool = True,
) -> Dict[str, Any]:
    """Generate a complete daily report package.

    Parameters
    ----------
    scanner_results:
        DataFrame/list of dict rows from app scanner.
    regime:
        Dict from market_regime.py, optional.
    theme_results:
        DataFrame/list/dict from theme_engine.py, optional.
    config:
        ReportConfig or dict overrides.
    output_dir:
        Folder where HTML/Markdown/CSV files are saved.
    db_path:
        SQLite path.
    report_date:
        Human/report date string. Defaults to UTC date.
    report_id:
        Optional deterministic report id.
    save_sqlite:
        Archive report and report items into SQLite.
    record_signals:
        Also insert actionable long/short ideas into signal_outcome_db.
    save_files:
        Save artifacts to output_dir.

    Returns
    -------
    dict with dataframe, buckets, markdown_text, html_text, telegram_text, paths, report_id.
    """
    if config is None:
        cfg = ReportConfig()
    elif isinstance(config, dict):
        cfg = ReportConfig(**{**asdict(ReportConfig()), **config})
    else:
        cfg = config

    report_date = report_date or datetime.utcnow().strftime("%Y-%m-%d")
    report_id = report_id or f"daily_{_slugify(report_date)}_{datetime.utcnow().strftime('%H%M%S')}"

    df = normalize_scanner_results(scanner_results)
    df = add_position_sizing(df, cfg)
    regime_meta = summarize_regime(regime)
    themes = summarize_themes(theme_results)

    # Fill missing regime from regime_meta for all rows.
    if not df.empty and "regime" in df.columns:
        df["regime"] = df["regime"].fillna(regime_meta.get("regime"))

    buckets = split_idea_buckets(df, cfg)
    executive_summary = build_executive_summary(df, buckets, regime_meta, themes)
    markdown_text = render_markdown_report(report_id, report_date, cfg, executive_summary, regime_meta, themes, buckets)
    telegram_text = render_telegram_text(report_date, cfg, executive_summary, regime_meta, themes, buckets)
    html_text = render_html_report(markdown_text, cfg, df)

    paths = {"html_path": None, "markdown_path": None, "csv_path": None}
    if save_files:
        outdir = Path(output_dir)
        outdir.mkdir(parents=True, exist_ok=True)
        base = _slugify(report_id)
        html_path = outdir / f"{base}.html"
        md_path = outdir / f"{base}.md"
        csv_path = outdir / f"{base}_scanner.csv"
        html_path.write_text(html_text, encoding="utf-8")
        md_path.write_text(markdown_text, encoding="utf-8")
        df.to_csv(csv_path, index=False)
        paths = {"html_path": str(html_path), "markdown_path": str(md_path), "csv_path": str(csv_path)}

    metadata = {
        "config": asdict(cfg),
        "row_count": int(len(df)),
        "bucket_counts": {k: int(len(v)) for k, v in buckets.items()},
        "themes": themes.to_dict(orient="records"),
    }

    if save_sqlite:
        save_report_to_sqlite(
            report_id=report_id,
            report_date=report_date,
            cfg=cfg,
            regime_meta=regime_meta,
            executive_summary=executive_summary,
            markdown_text=markdown_text,
            telegram_text=telegram_text,
            buckets=buckets,
            paths=paths,
            metadata=metadata,
            db_path=db_path,
        )

    signal_ids = []
    if record_signals:
        signal_ids = record_report_signals(buckets, db_path=db_path)

    return {
        "report_id": report_id,
        "report_date": report_date,
        "scanner_df": df,
        "buckets": buckets,
        "regime": regime_meta,
        "themes": themes,
        "executive_summary": executive_summary,
        "markdown_text": markdown_text,
        "html_text": html_text,
        "telegram_text": telegram_text,
        "paths": paths,
        "html_path": paths.get("html_path"),
        "markdown_path": paths.get("markdown_path"),
        "csv_path": paths.get("csv_path"),
        "signal_ids": signal_ids,
        "metadata": metadata,
    }


def build_report_from_scanner_df(
    scanner_df: pd.DataFrame,
    regime: Optional[Dict[str, Any]] = None,
    themes: Optional[pd.DataFrame] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Thin convenience wrapper for Streamlit/app.py usage."""
    return generate_daily_report(scanner_df, regime=regime, theme_results=themes, **kwargs)


# =============================================================================
# CLI smoke test / demo
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    demo_rows = [
        {
            "ticker": "NVDA", "final_score": 91, "decision": "Strong Long", "setup_type": "Breakout + forced flow",
            "entry": 180, "stop": 171, "target1": 198, "target2": 215, "risk_reward": 2.0,
            "expected_return": 0.094, "technical_score": 88, "liquidity_score": 84, "options_score": 90,
            "game_score": 92, "catalyst_score": 83, "theme": "AI Infrastructure",
            "thesis": "Dealer/forced-flow support aligns with trend and AI infrastructure theme."
        },
        {
            "ticker": "XYZ", "final_score": 24, "decision": "Tactical Short", "setup_type": "Distribution / failed breakout",
            "entry": 42, "stop": 45, "target1": 36, "risk_reward": 2.0,
            "expected_return": -0.08, "technical_score": 25, "liquidity_score": 35, "options_score": 30,
            "game_score": 28, "catalyst_score": 40, "theme": "Weak Balance Sheet",
            "thesis": "Breakout buyers appear trapped; liquidity is deteriorating."
        },
    ]
    demo_regime = {"regime": "RISK_ON", "risk_on_probability": 0.72, "risk_off_probability": 0.11, "chop_probability": 0.17}
    demo_themes = [{"theme": "AI Infrastructure", "score": 88, "summary": "Semis and data center names leading."}]
    result = generate_daily_report(demo_rows, demo_regime, demo_themes, output_dir="reports", record_signals=False)
    print(result["telegram_text"])
    print("HTML:", result["html_path"])
