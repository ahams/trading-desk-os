"""
Trading Desk OS - Beta Frontend
--------------------------------
Streamlit UI that connects to the FastAPI monetized backend.

Run:
    streamlit run frontend_streamlit.py

Backend endpoints used:
    GET  /api/v1/account
    POST /api/v1/analyze/compact
    POST /api/v1/scanner/compact
    POST /api/v1/report/daily

Environment variables supported:
    TDOS_API_URL
    TDOS_API_KEY
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import plotly.express as px
import pandas as pd
import requests
import streamlit as st

# =============================================================================
# helper notes for toltip
#==============================================================================
HELP = {
    "decision": "Final TDOS classification after combining investment quality, trading setup, positioning, liquidity, and risk.",
    "final_score": "Composite score from 0–100. Higher means stronger overall opportunity after combining all engines.",
    "trade_expectancy": "Expected value of the current trade plan using entry, stop, target, and win probability. This is not long-term expected return.",
    "win_probability": "Estimated probability that the trade reaches its favorable outcome before invalidation.",
    "reward_pct": "Potential upside from entry to Target 2.",
    "risk_pct": "Potential downside from entry to stop loss.",
    "scenario_ev": "Legacy scenario-based expected value using bull/base/bear outcomes. Useful as a secondary check.",
    "investment_view": "Longer-term business/investment view based on fundamentals, expectations, capital structure, and greenfield growth.",
    "trading_view": "Near-term tactical view based on technicals, liquidity, options positioning, and game-theory/participant behavior.",
}


# =============================================================================
# Page Config
# =============================================================================

st.set_page_config(
    page_title="Trading Desk OS Beta",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)



def apply_theme():
    st.markdown("""
    <style>
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
        max-width: 1400px;
    }

    div[data-testid="stMetric"] {
        border: 1px solid rgba(128,128,128,0.25);
        padding: 14px 16px;
        border-radius: 14px;
    }

    .tdos-card {
        border: 1px solid rgba(128,128,128,0.25);
        border-radius: 18px;
        padding: 20px;
        margin-bottom: 18px;
    }

    .tdos-muted {
        opacity: 0.72;
        margin-bottom: 10px;
    }

    .tdos-pill {
        display: inline-block;
        background: #2563EB;
        # color: white;
        padding: 8px 14px;
        border-radius: 999px;
        font-weight: 700;
    }

    h1, h2, h3 {
        letter-spacing: -0.02em;
    }
    </style>
    """, unsafe_allow_html=True)
# =============================================================================
# Helpers
# =============================================================================

DEFAULT_API_URL = os.getenv("TDOS_API_URL", "http://127.0.0.1:8000")
DEFAULT_API_KEY = os.getenv("TDOS_API_KEY") or os.getenv("STOCK_API_KEY", "")


def normalize_base_url(url: str) -> str:
    return (url or "").strip().rstrip("/")


def get_auth_headers() -> Dict[str, str]:
    key = st.session_state.get("api_key", "").strip()
    return {
        "X-API-Key": key,
        "Content-Type": "application/json",
    }


def api_request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
    timeout: int = 60,
) -> Tuple[bool, Any]:
    base_url = normalize_base_url(st.session_state.get("api_url", DEFAULT_API_URL))
    if not base_url:
        return False, "Missing API URL"

    url = f"{base_url}{path}"

    try:
        resp = requests.request(
            method=method.upper(),
            url=url,
            headers=get_auth_headers(),
            params=params,
            json=payload,
            timeout=timeout,
        )

        content_type = resp.headers.get("content-type", "")
        body = resp.json() if "application/json" in content_type else resp.text

        if resp.status_code >= 400:
            return False, {"status_code": resp.status_code, "error": body, "url": url}

        return True, body

    except requests.exceptions.ConnectionError:
        return False, f"Could not connect to API at {url}. Is backend running?"
    except requests.exceptions.Timeout:
        return False, f"Request timed out after {timeout}s: {url}"
    except Exception as exc:
        return False, f"Unexpected API error: {exc}"


def extract_data(resp: Any) -> Any:
    """API may return {user, credits_used, data}; compact endpoints may return direct data."""
    if isinstance(resp, dict) and isinstance(resp.get("data"), (dict, list)):
        return resp["data"]
    return resp


def parse_tickers(text: str) -> List[str]:
    return [x.strip().upper() for x in (text or "").replace("\n", ",").split(",") if x.strip()]


def as_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def fmt_pct(x: Any, decimals: int = 1) -> str:
    if x is None:
        return "n/a"
    try:
        val = float(x)
        # Backend compact expected_return.ev_pct is already a percent such as -1.1.
        # Raw expected_return may be decimal such as -0.011.
        if abs(val) <= 1.5:
            val *= 100
        return f"{val:.{decimals}f}%"
    except Exception:
        return "n/a"


def fmt_num(x: Any, decimals: int = 2) -> str:
    if x is None:
        return "n/a"
    try:
        return f"{float(x):,.{decimals}f}"
    except Exception:
        return str(x)


def decision_color(decision: str) -> str:
    d = (decision or "").lower()
    if "strong long" in d:
        return "#0f766e"
    if "tactical long" in d or "long" in d:
        return "#16a34a"
    if "short" in d:
        return "#dc2626"
    if "avoid" in d:
        return "#b91c1c"
    return "#ca8a04"


def show_error(err: Any) -> None:
    st.error("Request failed")
    if isinstance(err, dict):
        st.code(json.dumps(err, indent=2, default=str), language="json")
    else:
        st.write(err)


def render_score_bar(label: str, score: Any) -> None:
    score_f = max(0, min(100, as_float(score)))
    st.caption(label)
    st.progress(score_f / 100.0, text=f"{score_f:.1f}/100")


def safe_metric_value(x: Any, decimals: int = 1) -> str:
    if x is None:
        return "n/a"
    try:
        return f"{float(x):,.{decimals}f}"
    except Exception:
        return str(x)
#====================================
#Additional hepers
#====================================

import pandas as pd
from datetime import datetime


def _safe_get(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default

SCANNER_REQUIRED_COLUMNS = [
    "Ticker", "Decision", "Setup", "Final Score",
    "Investment View", "Investment Score",
    "Trading View", "Trading Score",
    "Trade Expectancy %", "Expectancy R",
    "Win Probability %", "Reward %", "Risk %",
    "Scenario EV %", "Entry", "Stop", "Target 1",
    "Target 2", "R/R", "Fundamental", "Technical",
    "Liquidity", "Options", "Game Theory",
    "Expectation", "Merton", "Greenfield ARR",
    "Credit Risk", "Theme", "Thesis",
]


def ensure_scanner_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None:
        df = pd.DataFrame()

    for col in SCANNER_REQUIRED_COLUMNS:
        if col not in df.columns:
            df[col] = None

    numeric_cols = [
        "Final Score", "Investment Score", "Trading Score",
        "Trade Expectancy %", "Expectancy R", "Win Probability %",
        "Reward %", "Risk %", "Scenario EV %",
        "Entry", "Stop", "Target 1", "Target 2", "R/R",
        "Fundamental", "Technical", "Liquidity", "Options",
        "Game Theory", "Expectation", "Merton", "Greenfield ARR",
        "Distance To Default",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df
def to_scanner_df(resp):
    """
    Convert scanner/report API response into a clean dataframe.
    Handles:
      resp["data"]["results"]
      resp["data"]["data"]["results"]
      resp["results"]
      {"results": [...]}
    """
    data = extract_data(resp)

    rows = []

    if isinstance(data, dict):
        rows = (
            data.get("results")
            or data.get("scanner_results")
            or (data.get("data") or {}).get("results")
            or []
        )
    elif isinstance(data, list):
        rows = data

    clean_rows = []

    for r in rows:
        if not isinstance(r, dict):
            continue

        trade = r.get("trade_expectancy") or r.get("expected_return") or {}
        decision_layer = r.get("decision_layer") or {}
        scores = r.get("scores") or {}
        plan = r.get("trade_plan") or {}
        cap = r.get("capital_structure_snapshot") or {}

        clean_rows.append({
            "Ticker": r.get("ticker"),
            "Decision": r.get("decision"),
            "Setup": r.get("setup_type"),
            "Final Score": r.get("final_score"),
            "Investment View": decision_layer.get("investment_view"),
            "Investment Score": decision_layer.get("investment_score"),
            "Trading View": decision_layer.get("trading_view"),
            "Trading Score": decision_layer.get("trading_score"),
            "Trade Expectancy %": trade.get("trade_expectancy_pct"),
            "Expectancy R": trade.get("trade_expectancy_r"),
            "Win Probability %": trade.get("probability_win"),
            "Reward %": trade.get("reward_pct"),
            "Risk %": trade.get("risk_pct"),
            "Scenario EV %": trade.get("legacy_scenario_ev_pct"),
            "Entry": plan.get("entry"),
            "Stop": plan.get("stop"),
            "Target 1": plan.get("target1"),
            "Target 2": plan.get("target2"),
            "R/R": plan.get("risk_reward"),
            "Position Size": plan.get("position_size"),
            "Fundamental": scores.get("fundamental"),
            "Technical": scores.get("technical"),
            "Liquidity": scores.get("liquidity"),
            "Options": scores.get("options"),
            "Game Theory": scores.get("game_theory"),
            "Expectation": scores.get("expectation"),
            "Merton": scores.get("merton_credit"),
            "Greenfield ARR": scores.get("greenfield_arr_valuation"),
            "Credit Risk": cap.get("risk"),
            "Distance To Default": cap.get("distance_to_default"),
            "Regime": r.get("regime"),
            "Theme": r.get("theme"),
            "Thesis": r.get("final_thesis"),
        })

    return ensure_scanner_columns(pd.DataFrame(clean_rows))


def render_scanner_tables(df: pd.DataFrame):
    if df is None or df.empty:
        st.warning("No scanner rows returned.")
        return

    required = ["Ticker", "Decision", "Final Score"]
    missing = [c for c in required if c not in df.columns]

    if missing:
        st.error(f"Scanner dataframe missing columns: {missing}")
        st.write("Available columns:", list(df.columns))
        st.dataframe(df, use_container_width=True)
        return

    st.success(f"Loaded {len(df)} rows")

    blotter_cols = [
        "Ticker", "Decision", "Setup", "Final Score",
        "Investment View", "Trading View",
        "Trade Expectancy %", "Expectancy R",
        "Win Probability %", "Entry", "Stop", "Target 2", "R/R", "Theme"
    ]

    st.subheader("Desk Blotter")
    st.dataframe(
        df[[c for c in blotter_cols if c in df.columns]],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Best Current Trades")
    best = df[
        df["Decision"].astype(str).str.contains("Strong Long|Tactical Long", na=False)
    ].sort_values("Trade Expectancy %", ascending=False)

    st.dataframe(
        best[[c for c in blotter_cols if c in best.columns]],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Investment / Trading Conflicts")
    conflict = df[
        df["Investment View"].astype(str).isin(["Bullish", "Constructive"])
        & df["Trading View"].astype(str).str.contains("Neutral|Wait", na=False)
    ]

    st.dataframe(
        conflict[[c for c in blotter_cols if c in conflict.columns]],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Risk Warnings")
    risk = df[
        (df["Merton"].fillna(100) < 50)
        | (df["Technical"].fillna(50) < 40)
        | (df["Liquidity"].fillna(50) < 45)
        | (df["Options"].fillna(50) < 35)
    ]

    risk_cols = [
        "Ticker", "Decision", "Setup", "Final Score",
        "Technical", "Liquidity", "Options", "Merton",
        "Credit Risk", "Thesis"
    ]

    st.dataframe(
        risk[[c for c in risk_cols if c in risk.columns]],
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("Engine Scores"):
        score_cols = [
            "Ticker", "Fundamental", "Technical", "Liquidity",
            "Options", "Game Theory", "Expectation", "Merton", "Greenfield ARR"
        ]
        st.dataframe(
            df[[c for c in score_cols if c in df.columns]],
            use_container_width=True,
            hide_index=True,
        )

    with st.expander("Full Scanner Export"):
        st.dataframe(df, use_container_width=True, hide_index=True)

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download Scanner CSV",
        data=csv,
        file_name=f"tdos_scanner_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )


def render_daily_report(results):
    df = to_scanner_df({"results": results})
    if df.empty:
        st.warning("No rows available.")
        return

    if df.empty:
        st.warning("No daily report rows returned.")
        return

    st.subheader("Executive Summary")

    strong = df[df["Decision"].astype(str).str.contains("Strong Long", na=False)]
    tactical = df[df["Decision"].astype(str).str.contains("Tactical Long", na=False)]
    watch = df[df["Decision"].astype(str).str.contains("Watchlist", na=False)]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Strong Longs", len(strong))
    c2.metric("Tactical Longs", len(tactical))
    c3.metric("Watchlist", len(watch))
    c4.metric("Avg Score", round(df["Final Score"].dropna().mean(), 1) if "Final Score" in df else "n/a")

    st.subheader("Top Ranked Names")
    st.dataframe(
        df.sort_values("Final Score", ascending=False).head(15),
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Best Trade Expectancy")
    st.dataframe(
        df.sort_values("Trade Expectancy %", ascending=False).head(10),
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Bullish Investment / Neutral Trading")
    conflict = df[
        df["Investment View"].astype(str).isin(["Bullish", "Constructive"])
        & df["Trading View"].astype(str).str.contains("Neutral|Wait", na=False)
    ]
    st.dataframe(conflict, use_container_width=True, hide_index=True)

    st.subheader("Risk Warnings")
    risk = df[
        (df["Merton"].fillna(100) < 50)
        | (df["Technical"].fillna(50) < 40)
        | (df["Liquidity"].fillna(50) < 45)
        | (df["Options"].fillna(50) < 35)
    ]
    st.dataframe(risk, use_container_width=True, hide_index=True)

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download Daily Report CSV",
        data=csv,
        file_name=f"tdos_daily_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )
def render_metric_strip(df):
    df = ensure_scanner_columns(df)
    if df.empty:
        st.warning("No rows available.")
        return
    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Strong Longs", df["Decision"].astype(str).str.contains("Strong Long", na=False).sum())
    c2.metric("Tactical Longs", df["Decision"].astype(str).str.contains("Tactical Long", na=False).sum())
    c3.metric("Watchlist", df["Decision"].astype(str).str.contains("Watchlist", na=False).sum())
    avg_score = pd.to_numeric(df["Final Score"], errors="coerce").dropna().mean()
    c4.metric("Avg Final Score", "n/a" if pd.isna(avg_score) else round(avg_score, 1))


def render_opportunity_matrix(df):
    df = ensure_scanner_columns(df)
    if df.empty:
        st.warning("No rows available.")
        return
    st.subheader("Investment vs Trading Matrix")

    plot_df = df.dropna(subset=["Investment Score", "Trading Score"]).copy()

    if "Trade Expectancy %" in plot_df.columns:
        plot_df["Bubble Size"] = plot_df["Trade Expectancy %"].abs().fillna(1).clip(lower=1)
    else:
        plot_df["Bubble Size"] = 1

    if plot_df.empty:
        st.info("Not enough data for opportunity matrix.")
        return

    fig = px.scatter(
        plot_df,
        x="Trading Score",
        y="Investment Score",
        size="Bubble Size",
        color="Decision",
        hover_name="Ticker",
        hover_data=[
            "Setup",
            "Final Score",
            "Trade Expectancy %",
            "Expectancy R",
            "Theme",
        ],
        height=520,
    )

    fig.add_vline(x=60, line_dash="dash")
    fig.add_hline(y=70, line_dash="dash")

    fig.update_layout(
        xaxis_title="Trading Quality",
        yaxis_title="Investment Quality",
    )

    st.plotly_chart(fig, use_container_width=True)

    st.caption(
        "Upper-right = strongest candidates. Upper-left = good businesses but wait for better entry. "
        "Lower-right = tactical trades only. Lower-left = avoid/watchlist."
    )


def render_theme_heatmap(df):
    df = ensure_scanner_columns(df)
    if df.empty:
        st.warning("No rows available.")
        return
    st.subheader("Theme Heatmap")

    if "Theme" not in df.columns or df["Theme"].dropna().empty:
        st.info("No theme data available.")
        return

    theme_df = (
        df.groupby("Theme", dropna=False)
        .agg(
            Names=("Ticker", "count"),
            AvgScore=("Final Score", "mean"),
            AvgTradeExpectancy=("Trade Expectancy %", "mean"),
            AvgInvestment=("Investment Score", "mean"),
            AvgTrading=("Trading Score", "mean"),
        )
        .reset_index()
        .sort_values("AvgScore", ascending=False)
    )

    fig = px.bar(
        theme_df,
        x="Theme",
        y="AvgScore",
        color="AvgTradeExpectancy",
        hover_data=["Names", "AvgInvestment", "AvgTrading"],
        height=420,
    )

    fig.update_layout(
        xaxis_title="Theme",
        yaxis_title="Average Final Score",
    )

    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(theme_df, use_container_width=True, hide_index=True)


def render_risk_radar(df):
    df = ensure_scanner_columns(df)
    if df.empty:
        st.warning("No rows available.")
        return
    st.subheader("Risk Radar")

    risk = df[
        (df["Merton"].fillna(100) < 50)
        | (df["Technical"].fillna(50) < 40)
        | (df["Liquidity"].fillna(50) < 45)
        | (df["Options"].fillna(50) < 35)
    ].copy()

    if risk.empty:
        st.success("No major risk warnings detected.")
        return

    risk_cols = [
        "Ticker", "Decision", "Setup", "Final Score",
        "Technical", "Liquidity", "Options", "Merton",
        "Credit Risk", "Thesis",
    ]

    st.dataframe(
        risk[[c for c in risk_cols if c in risk.columns]],
        use_container_width=True,
        hide_index=True,
    )


def _metric_or_dash(value, suffix="", decimals=1):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        return f"{float(value):.{decimals}f}{suffix}"
    except Exception:
        return f"{value}{suffix}"


def render_action_cards(df):
    """
    Scanner cards optimized for scanning.

    The old implementation hard-truncated the thesis to 350 characters.
    This version shows the key action first and puts the complete thesis,
    setup, trade levels, and scores inside an expander.
    """
    df = ensure_scanner_columns(df)
    if df.empty:
        st.warning("No rows available.")
        return

    st.subheader("Action Cards")
    top = df.sort_values("Final Score", ascending=False).head(8)

    for card_idx, (_, row) in enumerate(top.iterrows()):
        ticker = row.get("Ticker", "n/a")
        decision = row.get("Decision", "n/a")
        setup = row.get("Setup", "n/a")
        thesis = str(row.get("Thesis") or "No thesis available.")

        with st.container(border=True):
            h1, h2, h3 = st.columns([1, 1.3, 2.7])
            h1.metric("Ticker", ticker)
            h2.metric("Decision", decision)
            h3.markdown(f"**Setup**  \\n{setup}")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Final Score", _metric_or_dash(row.get("Final Score")))
            m2.metric("Trade Exp.", _metric_or_dash(row.get("Trade Expectancy %"), "%"))
            m3.metric("Inv. Score", _metric_or_dash(row.get("Investment Score")))
            m4.metric("Trading Score", _metric_or_dash(row.get("Trading Score")))

            if "wait" in str(setup).lower() or "watchlist" in str(setup).lower():
                st.info("Action: Wait for the stated pullback, breakout, or confirmation trigger.")
            elif "short" in str(decision).lower() or "avoid" in str(decision).lower():
                st.warning("Action: Avoid new long exposure; review the bear case and invalidation levels.")
            else:
                st.success("Action: Review the trade plan and execute only within the stated risk limits.")

            with st.expander(f"Why {ticker}? Full desk view", expanded=False):
                st.markdown("#### Full thesis")
                st.write(thesis)

                p1, p2, p3, p4, p5 = st.columns(5)
                p1.metric("Entry", _metric_or_dash(row.get("Entry"), decimals=2))
                p2.metric("Stop", _metric_or_dash(row.get("Stop"), decimals=2))
                p3.metric("Target 1", _metric_or_dash(row.get("Target 1"), decimals=2))
                p4.metric("Target 2", _metric_or_dash(row.get("Target 2"), decimals=2))
                p5.metric("R/R", _metric_or_dash(row.get("R/R"), decimals=2))

                st.caption(
                    "The scanner card is a summary. Open the single-stock analysis "
                    "for witness evidence, participant behavior, assumptions, and invalidators."
                )

            if st.button(
                f"Open {ticker} in Analyze →",
                key=f"scanner_open_analysis_{card_idx}_{ticker}",
                use_container_width=True,
            ):
                st.session_state.analyze_ticker = str(ticker).upper().strip()
                st.session_state.run_analysis_from_scanner = True
                # nav_page is the key of the st.radio widget and cannot be
                # changed after that widget has been instantiated in this run.
                # Queue the navigation change and apply it at the top of the
                # next rerun, before st.radio is created.
                st.session_state.pending_nav_page = "Analyze Stock"
                st.rerun()


# =============================================================================
# Renderers
# =============================================================================

# def render_analysis_card(data: Dict[str, Any]) -> None:
#     if not isinstance(data, dict):
#         st.warning("No analysis data returned")
#         return

#     ticker = data.get("ticker", "N/A")
#     decision = data.get("decision", "n/a")
#     setup = data.get("setup_type", "n/a")
#     regime = data.get("regime", "n/a")
#     theme = data.get("theme", "n/a")

#     trade_plan = data.get("trade_plan") or {}
#     expected = data.get("trade_expectancy") or data.get("expected_return") or {}
#     scores = data.get("scores") or {}
#     reads = data.get("reads") or {}

#     st.markdown(
#         f"""
#         <div style="border:1px solid #e5e7eb;border-radius:14px;padding:18px;margin-bottom:14px;">
#           <div style="display:flex;justify-content:space-between;align-items:center;">
#             <div>
#               <h2 style="margin:0;">{ticker}</h2>
#               <div style="color:#6b7280;">{setup} · Regime: {regime} · Theme: {theme}</div>
#             </div>
#             <div style="background:{decision_color(decision)};color:white;padding:8px 14px;border-radius:999px;font-weight:700;">
#               {decision}
#             </div>
#           </div>
#         </div>
#         """,
#         unsafe_allow_html=True,
#     )

#     c1, c2, c3, c4 = st.columns(4)
    
#     c1.metric("Decision ⓘ", data.get("decision", "n/a"), help=HELP["decision"])
#     c2.metric("Final Score ⓘ", data.get("final_score", "n/a"), help=HELP["final_score"])
#     te = expected.get("trade_expectancy_pct")
#     te_r = expected.get("trade_expectancy_r")
#     c3.metric(
#         "Trade Expectancy ⓘ",
#         "n/a" if te is None else f"{float(te):.1f}%",
#         "n/a" if te_r is None else f"{float(te_r):.2f}R",
#         help=HELP["trade_expectancy"],
#     )
#     c4.metric("Win Probability", fmt_pct(expected.get("probability_win")),help=HELP["win_probability"])
    
    
    
#     c1, c2, c3 = st.columns(3)
#     c1.metric("Reward %", expected.get("reward_pct", "n/a"),help=HELP["reward_pct"])
#     c2.metric("Risk %", expected.get("risk_pct", "n/a"),help=HELP["risk_pct"])
#     c3.metric("Scenario EV", expected.get("legacy_scenario_ev_pct", "n/a"),help=HELP["scenario_ev"])

#     c1, c2, c3, c4, c5 = st.columns(5)
#     c1.metric("Entry", fmt_num(trade_plan.get("entry")))
#     c2.metric("Stop", fmt_num(trade_plan.get("stop")))
#     c3.metric("Target 1", fmt_num(trade_plan.get("target1")))
#     c4.metric("Target 2", fmt_num(trade_plan.get("target2")))
#     c5.metric("Risk/Reward", fmt_num(trade_plan.get("risk_reward")))

#     decision_layer = data.get("decision_layer") or {}

#     if decision_layer:
#         st.markdown("### Decision Layer")

#         c1, c2 = st.columns(2)
#         c1.metric(
#             "Investment View ⓘ",
#             decision_layer.get("investment_view", "n/a"),
#             f"{decision_layer.get('investment_score', 'n/a')}/100",
#             help=HELP["investment_view"],
#         )
#         c2.metric(
#             "Trading View ⓘ",
#             decision_layer.get("trading_view", "n/a"),
#             f"{decision_layer.get('trading_score', 'n/a')}/100",
#             help=HELP["trading_view"],
#         )

#         st.markdown("**Reason**")
#         st.write(decision_layer.get("reason", "n/a"))

#         st.markdown("**Action**")
#         st.success(decision_layer.get("action", "n/a"))
    
#     tech_snap = data.get("technical_snapshot") or {}
#     if tech_snap:
#         st.markdown("### Technical Decomposition")
#         c1, c2, c3 = st.columns(3)
#         c1.metric("Trend Quality", safe_metric_value(tech_snap.get("trend_quality_score"), 1))
#         c1.caption(tech_snap.get("trend_signal", ""))
#         c2.metric("Entry Quality", safe_metric_value(tech_snap.get("entry_quality_score"), 1))
#         c2.caption(tech_snap.get("entry_signal", ""))
#         c3.metric("Leadership", safe_metric_value(tech_snap.get("leadership_score"), 1))
#         c3.caption(tech_snap.get("leadership_signal", ""))

#     cap = data.get("capital_structure_snapshot") or {}
#     neo = data.get("neocloud_snapshot") or {}
#     if cap or neo:
#         st.markdown("### Specialized Engines")
#         cols = st.columns(2)
#         with cols[0]:
#             if cap:
#                 st.markdown("**Merton / Capital Structure**")
#                 st.metric("Credit Score", safe_metric_value(cap.get("score"), 1))
#                 st.caption(f"{cap.get('signal', 'n/a')} · Risk: {cap.get('risk', 'n/a')}")
#                 st.write("Distance to Default:", cap.get("distance_to_default", "n/a"))
#                 st.write("Annual PD Proxy:", cap.get("pd_annual_proxy_pct", "n/a"))
#         with cols[1]:
#             if neo and neo.get("signal") != "Not a Greenfield ARR/Capacity Valuation specific name":
#                 st.markdown("**Greenfield ARR/Capacity**")
#                 st.metric("Greenfield Score", safe_metric_value(neo.get("score"), 1))
#                 st.caption(neo.get("signal", "n/a"))
#                 st.write("EV / Current ARR:", neo.get("ev_current_arr", "n/a"))
#                 st.write("EV / Target ARR:", neo.get("ev_target_arr", "n/a"))
    
    
#     opt = data.get("optionality_snapshot") or {}

#     if opt:
#         st.markdown("### Embedded Optionality")

#         c1, c2, c3 = st.columns(3)
#         c1.metric("Optionality Score", opt.get("score", "n/a"))
#         c2.metric("Existing Business Value %", opt.get("existing_value_pct", "n/a"))
#         c3.metric("Embedded Future Option %", opt.get("embedded_optionality_pct", "n/a"))

#         st.caption(opt.get("signal", ""))

#         if opt.get("summary"):
#             st.info(opt.get("summary"))

#         bears = opt.get("bear_points") or []
#         bulls = opt.get("bull_points") or []

#         if bulls:
#             st.success(" | ".join(bulls))
#         if bears:
#             st.warning(" | ".join(bears))
#         st.markdown("### Desk Thesis")
#         st.write(data.get("final_thesis", "n/a"))

#     why_not = data.get("why_not_long_now") or []
#     if why_not:
#         st.markdown("### Why not long now / invalidation")
#         for item in why_not:
#             st.write(f"- {item}")

#     c1, c2 = st.columns(2)
#     with c1:
#         st.markdown("### Bull Case")
#         bull = data.get("main_bull_case") or []
#         if isinstance(bull, list):
#             for item in bull:
#                 st.success(str(item))
#         else:
#             st.success(str(bull))
#     with c2:
#         st.markdown("### Bear Case")
#         bear = data.get("main_bear_case") or []
#         if isinstance(bear, list):
#             for item in bear:
#                 st.error(str(item))
#         else:
#             st.error(str(bear))

# #new approach to use narratives instead of scores
#     narr = data.get("narrative") or {}

#     if narr:
#         st.markdown("### Investment Narrative")

#         c1, c2, c3 = st.columns(3)
#         c1.metric("Investment Quality", narr.get("business_quality", {}).get("rating", "n/a"))
#         c2.metric("Market Expectations", narr.get("market_expectations", {}).get("rating", "n/a"))
#         c3.metric("Trading Conditions", narr.get("trading_conditions", {}).get("rating", "n/a"))

#         with st.container(border=True):
#             st.markdown("#### Business Quality")
#             for p in narr.get("business_quality", {}).get("points", []):
#                 st.write(f"• {p}")

#         with st.container(border=True):
#             st.markdown("#### Market Expectations")
#             for p in narr.get("market_expectations", {}).get("points", []):
#                 st.write(f"• {p}")

#         with st.container(border=True):
#             st.markdown("#### Trading Conditions")
#             for p in narr.get("trading_conditions", {}).get("points", []):
#                 st.write(f"• {p}")

#         c1, c2 = st.columns(2)

#         with c1:
#             st.markdown("#### Primary Risks")
#             for p in narr.get("primary_risks", []):
#                 st.warning(p)

#         with c2:
#             st.markdown("#### Opportunity")
#             for p in narr.get("opportunity", []):
#                 st.success(p)

#         rec = narr.get("recommendation") or {}
#         st.markdown("#### Recommendation")
#         st.info(rec.get("summary", "n/a"))
#         st.success(rec.get("action", "n/a"))
#     else:
#         st.markdown("### Desk Thesis")
#         st.write(data.get("final_thesis", "n/a"))
    
    
    
    
    
#     if reads:
#         with st.expander("Key Reads", expanded=False):
#             for k, v in reads.items():
#                 if v:
#                     st.markdown(f"**{k.replace('_', ' ').title()}:** {v}")

#     if scores:
#         st.markdown("### Scores")
#         cols = st.columns(4)
#         for i, (k, v) in enumerate(scores.items()):
#             with cols[i % 4]:
#                 render_score_bar(k.replace("_", " ").title(), v)

#     with st.expander("Raw response"):
#         st.json(data)

def render_clean_daily_report(data: dict):
    st.subheader("Executive Summary")
    st.info(data.get("executive_summary", "No summary returned."))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Report ID", data.get("report_id", "n/a"))
    c2.metric("Date", data.get("report_date", "n/a"))
    c3.metric("Scanner Count", data.get("scanner_count", "n/a"))
    c4.metric("Signals Saved", len(data.get("signal_ids") or []))

    telegram_text = data.get("telegram_text")
    markdown_text = data.get("markdown_text")
    paths = data.get("paths") or {}

    if telegram_text:
        st.subheader("Telegram Brief")
        st.code(telegram_text, language="text")

    if markdown_text:
        with st.expander("Full Markdown Report"):
            st.markdown(markdown_text)

        st.download_button(
            "Download Markdown Report",
            data=markdown_text.encode("utf-8"),
            file_name=f"{data.get('report_id', 'tdos_daily_report')}.md",
            mime="text/markdown",
        )

    if paths:
        with st.expander("Generated Report Files"):
            st.json(paths)

    signal_ids = data.get("signal_ids") or []
    if signal_ids:
        with st.expander("Saved Signal IDs"):
            st.write(signal_ids)
            
            
            
def render_header_card(data):
    ticker = data.get("ticker", "N/A")
    decision = data.get("decision", "n/a")
    setup = data.get("setup_type", "n/a")
    regime = data.get("regime", "n/a")
    theme = data.get("theme", "n/a")

    st.markdown(f"""
    <div class="tdos-card">
        <h2 style="margin-bottom:4px;">{ticker}</h2>
        <div class="tdos-muted">{setup} · {regime} · {theme}</div>
        <div class="tdos-pill">{decision}</div>
    </div>
    """, unsafe_allow_html=True)


def render_trade_plan(data):
    plan = data.get("trade_plan") or {}
    exp = data.get("trade_expectancy") or data.get("expected_return") or {}

    st.markdown("### Trade Plan")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Trade Expectancy", f"{exp.get('trade_expectancy_pct', 'n/a')}%")
    c2.metric("Win Probability", f"{exp.get('probability_win', 'n/a')}%")
    c3.metric("Reward %", exp.get("reward_pct", "n/a"))
    c4.metric("Risk %", exp.get("risk_pct", "n/a"))

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Entry", plan.get("entry", "n/a"))
    c2.metric("Stop", plan.get("stop", "n/a"))
    c3.metric("Target 1", plan.get("target1", "n/a"))
    c4.metric("Target 2", plan.get("target2", "n/a"))
    c5.metric("R/R", plan.get("risk_reward", "n/a"))


def render_decision_layer(data):
    layer = data.get("decision_layer") or {}
    if not layer:
        return

    st.markdown("### Decision Layer")
    c1, c2 = st.columns(2)
    c1.metric("Investment View", layer.get("investment_view", "n/a"), f"{layer.get('investment_score', 'n/a')}/100")
    c2.metric("Trading View", layer.get("trading_view", "n/a"), f"{layer.get('trading_score', 'n/a')}/100")

    st.info(layer.get("reason", "n/a"))
    st.success(layer.get("action", "n/a"))


def render_investment_narrative(data):
    narr = data.get("narrative") or {}
    if not narr:
        st.markdown("### Desk Thesis")
        st.write(data.get("final_thesis", "n/a"))
        return

    st.markdown("### Investment Narrative")

    c1, c2, c3 = st.columns(3)
    c1.metric("Investment Quality", narr.get("business_quality", {}).get("rating", "n/a"))
    c2.metric("Market Expectations", narr.get("market_expectations", {}).get("rating", "n/a"))
    c3.metric("Trading Conditions", narr.get("trading_conditions", {}).get("rating", "n/a"))

    c1, c2, c3 = st.columns(3)

    with c1:
        with st.container(border=True):
            st.markdown("#### Business")
            for p in narr.get("business_quality", {}).get("points", []):
                st.write(f"• {p}")

    with c2:
        with st.container(border=True):
            st.markdown("#### Expectations")
            for p in narr.get("market_expectations", {}).get("points", []):
                st.write(f"• {p}")

    with c3:
        with st.container(border=True):
            st.markdown("#### Trading")
            for p in narr.get("trading_conditions", {}).get("points", []):
                st.write(f"• {p}")

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("#### Primary Risks")
        for p in narr.get("primary_risks", []):
            st.warning(p)

    with c2:
        st.markdown("#### Opportunity")
        for p in narr.get("opportunity", []):
            st.success(p)

    rec = narr.get("recommendation") or {}
    st.markdown("#### Recommendation")
    st.info(rec.get("summary", "n/a"))
    st.success(rec.get("action", "n/a"))


def render_specialized_engines(data):
    cap = data.get("capital_structure_snapshot") or {}
    opt = data.get("optionality_snapshot") or {}
    gf = data.get("greenfield_arr_snapshot") or {}

    st.markdown("### Specialized Engines")

    c1, c2, c3 = st.columns(3)

    with c1:
        with st.container(border=True):
            st.markdown("#### Merton / Credit")
            st.metric("Credit Score", cap.get("score", "n/a"))
            st.caption(f"{cap.get('signal', 'n/a')} · {cap.get('risk', 'n/a')}")
            st.write("Distance to Default:", cap.get("distance_to_default", "n/a"))
            st.write("Annual PD:", cap.get("pd_annual_proxy_pct", "n/a"))

    with c2:
        with st.container(border=True):
            st.markdown("#### Future Value Premium")
            st.metric("Optionality Score", opt.get("score", "n/a"))
            st.caption(opt.get("signal", "n/a"))
            st.write("Existing Value %:", opt.get("existing_value_pct", "n/a"))
            st.write("Future Option %:", opt.get("embedded_optionality_pct", "n/a"))

    with c3:
        with st.container(border=True):
            st.markdown("#### Greenfield ARR")
            st.metric("Score", gf.get("score", "n/a"))
            st.caption(gf.get("signal", "n/a"))
            st.write("EV / Current ARR:", gf.get("ev_current_arr", "n/a"))
            st.write("EV / Target ARR:", gf.get("ev_target_arr", "n/a"))


def render_bull_bear(data):
    st.markdown("### Bull / Bear Case")
    c1, c2 = st.columns(2)

    with c1:
        st.markdown("#### Bull Case")
        for p in data.get("main_bull_case") or []:
            st.success(p)

    with c2:
        st.markdown("#### Bear Case")
        for p in data.get("main_bear_case") or []:
            st.error(p)


def render_engine_scores(data):
    scores = data.get("scores") or {}
    if not scores:
        return

    st.markdown("### Engine Scores")
    cols = st.columns(5)

    for i, (k, v) in enumerate(scores.items()):
        with cols[i % 5]:
            st.metric(k.replace("_", " ").title(), f"{v}/100")
            

def _find_witness(data, *engine_names):
    reasoning = data.get("reasoning") or {}
    witnesses = reasoning.get("witnesses") or []
    wanted = {str(x).lower() for x in engine_names}
    for witness in witnesses:
        if str(witness.get("engine", "")).lower() in wanted:
            return witness
    return {}


def _render_evidence_list(title, values, kind="info"):
    values = [str(v) for v in (values or []) if v]
    if not values:
        st.caption(f"No {title.lower()} available.")
        return
    st.markdown(f"#### {title}")
    for value in values:
        if kind == "success":
            st.success(value)
        elif kind == "warning":
            st.warning(value)
        elif kind == "error":
            st.error(value)
        else:
            st.info(value)


def _classify_expectation_evidence(witness):
    """
    Split expectation-engine evidence into supporting evidence, current drawbacks,
    and true forward-looking invalidators.

    The backend currently returns a single ``evidence`` list, so the frontend
    performs a conservative presentation-only classification. This avoids
    displaying current valuation/ROIC weaknesses as positive evidence or as
    future invalidation conditions.
    """
    evidence = [str(x) for x in (witness.get("evidence") or []) if x]
    invalidators = [str(x) for x in (witness.get("invalidators") or []) if x]

    negative_markers = (
        "growth hurdle is demanding",
        "roic is below",
        "roic below",
        "below wacc",
        "below market-required",
        "below market required",
        "current roic is below",
        "current roic below",
    )

    supporting, drawbacks = [], []
    for item in evidence:
        low = item.lower()

        # ROIC vs MEROI is direction-sensitive:
        # above/exceeds = positive evidence; below = drawback.
        is_roic_meroi = "roic" in low and "meroi" in low
        if is_roic_meroi:
            if any(word in low for word in ("above", "exceeds", "well above", "comfortably exceeds", "materially exceeds")):
                supporting.append(item)
                continue
            if "below" in low:
                drawbacks.append(item)
                continue

        if any(marker in low for marker in negative_markers):
            drawbacks.append(item)
        else:
            supporting.append(item)

    # A current condition is not an invalidator.  If the backend repeats a
    # current ROIC/MEROI weakness under invalidators, move it to drawbacks.
    true_invalidators = []
    for item in invalidators:
        low = item.lower()
        is_current_drawback = (
            ("roic" in low and "meroi" in low and "below" in low)
            or ("roic" in low and "wacc" in low and "below" in low)
        )
        if is_current_drawback:
            if item not in drawbacks:
                drawbacks.append(item)
        else:
            true_invalidators.append(item)

    # De-duplicate while preserving backend order.
    supporting = list(dict.fromkeys(supporting))
    drawbacks = list(dict.fromkeys(drawbacks))
    true_invalidators = list(dict.fromkeys(true_invalidators))
    return supporting, drawbacks, true_invalidators


def _render_witness_header(witness, fallback_score=None, show_claim=True):
    score = witness.get("score", fallback_score)
    direction = witness.get("direction", "neutral")
    confidence = witness.get("confidence")
    strength = witness.get("strength")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Score", _metric_or_dash(score))
    c2.metric("Direction", str(direction).title())
    c3.metric(
        "Confidence",
        _metric_or_dash(float(confidence) * 100 if confidence is not None else None, "%"),
    )
    c4.metric("Committee Strength", _metric_or_dash(strength, decimals=3))

    claim = witness.get("claim")
    if show_claim and claim:
        st.info(claim)


def _escape_markdown_dollars(value):
    """Prevent monetary $ signs from being interpreted as LaTeX delimiters."""
    if value is None:
        return value
    return str(value).replace("$", r"\$")


def compact_number(value):
    try:
        value = float(value)
    except Exception:
        return "—"
    magnitude = abs(value)
    if magnitude >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f}T"
    if magnitude >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if magnitude >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    return f"${value:,.0f}"


def render_game_theory_explainer(data):
    snap = data.get("game_theory_snapshot") or {}
    witness = _find_witness(data, "game")
    scores = data.get("scores") or {}
    _render_witness_header(witness, scores.get("game_theory"))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Forced Flow", _metric_or_dash(snap.get("forced_flow_score")))
    c2.metric("Short Squeeze", _metric_or_dash(snap.get("short_squeeze_score")))
    c3.metric("Gamma Squeeze", _metric_or_dash(snap.get("gamma_squeeze_score")))
    c4.metric("Pinning Risk", _metric_or_dash(snap.get("pinning_risk_score")))

    st.markdown("#### Market environment")
    st.write(snap.get("environment", "Not available"))

    participants = snap.get("dominant_participants") or {}
    if participants:
        rows = []
        for participant, details in participants.items():
            details = details or {}
            rows.append({
                "Participant": participant.replace("_", " ").title(),
                "Bias": details.get("bias"),
                "Pressure": details.get("pressure"),
            })
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Pressure": st.column_config.ProgressColumn(
                    "Pressure", min_value=0, max_value=100, format="%.1f"
                )
            },
        )

    c1, c2 = st.columns(2)
    with c1:
        _render_evidence_list("Why the model reached this view", witness.get("evidence"), "success")
    with c2:
        _render_evidence_list("What would invalidate it", witness.get("invalidators"), "warning")


def render_expectation_explainer(data):
    snap = data.get("expectation_snapshot") or {}
    witness = _find_witness(data, "expectation")
    scores = data.get("scores") or {}
    _render_witness_header(witness, scores.get("expectation"), show_claim=False)

    c1, c2, c3 = st.columns(3)
    c1.metric("Market-implied CAGR", _metric_or_dash(snap.get("implied_cagr_pct"), "%"))
    c2.metric("Revenue Growth", _metric_or_dash(snap.get("revenue_growth_pct"), "%"))
    c3.metric("CAP Years", _metric_or_dash(snap.get("market_implied_cap_years")))

    c1, c2, c3 = st.columns(3)
    c1.metric("ROIC", _metric_or_dash(snap.get("roic_pct"), "%"))
    c2.metric("Market-required MEROI", _metric_or_dash(snap.get("meroi_pct"), "%"))
    c3.metric("Growth Gap", _metric_or_dash(snap.get("growth_gap_pct"), "%"))

    if snap.get("read"):
        st.info(snap.get("read"))

    supporting, drawbacks, invalidators = _classify_expectation_evidence(witness)

    st.markdown("#### Why the model reached this view")
    c1, c2 = st.columns(2)
    with c1:
        _render_evidence_list("Supporting evidence", supporting, "success")
    with c2:
        _render_evidence_list("Current drawbacks / valuation hurdles", drawbacks, "warning")

    _render_evidence_list("What would invalidate the thesis", invalidators, "error")


def render_optionality_explainer(data):
    snap = data.get("optionality_snapshot") or {}
    witness = _find_witness(data, "optionality")
    scores = data.get("scores") or {}
    _render_witness_header(witness, scores.get("optionality"), show_claim=False)

    c1, c2, c3 = st.columns(3)
    c1.metric("Enterprise Value", compact_number(snap.get("enterprise_value")))
    c2.metric("Visible Business Value", compact_number(snap.get("existing_business_value")))
    c3.metric("Future Option Value", compact_number(snap.get("embedded_option_value")))

    c1, c2 = st.columns(2)
    c1.metric("Existing Value", _metric_or_dash(snap.get("existing_value_pct"), "%"))
    c2.metric("Future Optionality", _metric_or_dash(snap.get("embedded_optionality_pct"), "%"))

    if snap.get("summary"):
        st.info(_escape_markdown_dollars(snap.get("summary")))

    c1, c2 = st.columns(2)
    with c1:
        _render_evidence_list("Why the model reached this view", witness.get("evidence"), "success")
    with c2:
        _render_evidence_list("What would invalidate it", witness.get("invalidators"), "warning")


def render_credit_explainer(data):
    snap = data.get("capital_structure_snapshot") or {}
    witness = _find_witness(data, "merton")
    scores = data.get("scores") or {}
    _render_witness_header(witness, scores.get("merton_credit"))

    c1, c2, c3 = st.columns(3)
    c1.metric("Distance to Default", _metric_or_dash(snap.get("distance_to_default"), decimals=2))
    c2.metric("Annual PD", _metric_or_dash(snap.get("pd_annual_proxy_pct"), "%"))
    c3.metric("Net Debt / Market Cap", _metric_or_dash(snap.get("net_debt_to_market_cap_pct"), "%"))

    st.info(f"{snap.get('signal', 'Not available')} · Risk: {snap.get('risk', 'n/a')}")

    c1, c2 = st.columns(2)
    with c1:
        _render_evidence_list("Why the model reached this view", witness.get("evidence"), "success")
    with c2:
        _render_evidence_list("What would invalidate it", witness.get("invalidators"), "warning")


def _committee_engine_label(engine):
    labels = {
        "fundamental": "Fundamentals",
        "expectation": "Market Expectations",
        "optionality": "Future Value / Optionality",
        "technical": "Technical Setup",
        "trend_quality": "Trend Quality",
        "entry_quality": "Entry Quality",
        "leadership": "Market Leadership",
        "liquidity": "Liquidity",
        "options": "Options Positioning",
        "game": "Game Theory / Participant Behaviour",
        "game_theory": "Game Theory / Participant Behaviour",
        "merton": "Balance Sheet / Credit",
        "merton_credit": "Balance Sheet / Credit",
        "neocloud": "Greenfield / Capacity",
        "catalyst": "Catalysts",
    }
    key = str(engine or "").lower()
    return labels.get(key, key.replace("_", " ").title() or "Other")


def _committee_relevance(engine, data):
    """Decision relevance, distinct from raw model confidence/strength.

    Healthy credit is usually confirming evidence for an equity decision rather
    than the primary reason to own the stock. Credit relevance rises sharply
    when balance-sheet risk is actually material.
    """
    key = str(engine or "").lower()
    base = {
        "fundamental": 1.00,
        "expectation": 1.00,
        "optionality": 0.85,
        "technical": 0.80,
        "trend_quality": 0.80,
        "entry_quality": 0.75,
        "leadership": 0.75,
        "liquidity": 0.70,
        "options": 0.70,
        "game": 0.70,
        "game_theory": 0.70,
        "catalyst": 0.65,
        "neocloud": 0.55,
        "merton": 0.40,
        "merton_credit": 0.40,
    }.get(key, 0.60)

    if key in {"merton", "merton_credit"}:
        cap = data.get("capital_structure_snapshot") or {}
        score = as_float(cap.get("score"), 100.0)
        risk = str(cap.get("risk") or "").lower()
        signal = str(cap.get("signal") or "").lower()
        material_risk = (
            score < 60
            or any(token in risk for token in ("high", "elevated", "distress"))
            or any(token in signal for token in ("high risk", "distress", "deteriorat"))
        )
        if material_risk:
            return 1.00
    return base


def _committee_rank_items(items, data):
    ranked = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        engine = item.get("engine")
        raw_strength = item.get("strength")
        if raw_strength is None:
            score = as_float(item.get("score"), 50.0)
            raw_strength = abs(score - 50.0) / 50.0
        relevance = _committee_relevance(engine, data)
        decision_weight = as_float(raw_strength, 0.0) * relevance
        enriched = dict(item)
        enriched["decision_relevance"] = relevance
        enriched["decision_weight"] = decision_weight
        ranked.append(enriched)
    return sorted(ranked, key=lambda x: x.get("decision_weight", 0.0), reverse=True)


def _committee_expectation_constraint(data):
    snap = data.get("expectation_snapshot") or {}
    implied = snap.get("implied_cagr_pct")
    growth = snap.get("revenue_growth_pct")
    roic = snap.get("roic_pct")
    meroi = snap.get("meroi_pct")

    concerns = []
    try:
        if implied is not None and growth is not None and float(implied) > float(growth):
            concerns.append(
                f"market-implied growth of {float(implied):.1f}% exceeds current revenue growth of {float(growth):.1f}%"
            )
    except Exception:
        pass
    try:
        if roic is not None and meroi is not None and float(roic) < float(meroi):
            concerns.append(
                f"ROIC of {float(roic):.1f}% remains below the market-required MEROI of {float(meroi):.1f}%"
            )
    except Exception:
        pass

    if not concerns:
        return None
    return "Valuation remains the principal hurdle: " + "; and ".join(concerns) + "."


def _committee_assessment_text(data, reasoning, primary, support_ranked, contradictions):
    ticker = str(data.get("ticker") or "the company")
    view = str(reasoning.get("committee_view") or "the current view")
    primary_label = _committee_engine_label(primary.get("engine")) if primary else "cross-engine evidence"

    confirming = []
    for item in support_ranked:
        label = _committee_engine_label(item.get("engine"))
        if label != primary_label and label not in confirming:
            confirming.append(label)
        if len(confirming) == 2:
            break

    sentence = f"The committee maintains a {view.lower()} on {ticker}. The assessment is driven primarily by {primary_label}."
    if confirming:
        sentence += " The view is reinforced by " + " and ".join(confirming) + "."

    cap = data.get("capital_structure_snapshot") or {}
    merton_score = as_float(cap.get("score"), 0.0)
    merton_risk = str(cap.get("risk") or "").lower()
    if merton_score >= 70 and not any(x in merton_risk for x in ("high", "elevated", "distress")):
        sentence += " Balance-sheet risk is not currently a material constraint on the equity thesis."

    if contradictions:
        sentence += " The committee nevertheless identifies material counter-evidence that should be monitored."
    return sentence


def render_committee_explainer(data):
    reasoning = data.get("reasoning") or {}
    if not reasoning:
        st.caption("Committee reasoning is not available.")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Committee View", reasoning.get("committee_view", "n/a"))
    c2.metric("Confidence", _metric_or_dash(reasoning.get("confidence"), "%"))
    c3.metric(
        "Committee Agreement",
        _metric_or_dash((reasoning.get("consensus") or {}).get("agreement_pct"), "%"),
    )

    support_ranked = _committee_rank_items(reasoning.get("supporting_evidence"), data)
    contradiction_ranked = _committee_rank_items(reasoning.get("contradictory_evidence"), data)
    primary = support_ranked[0] if support_ranked else {}

    st.markdown("#### Committee Assessment")
    st.info(
        _committee_assessment_text(
            data, reasoning, primary, support_ranked, contradiction_ranked
        )
    )

    st.markdown("#### Decision Drivers")
    if primary:
        st.success(
            f"**Primary driver — {_committee_engine_label(primary.get('engine'))}:** "
            f"{primary.get('claim', 'No supporting claim available.')}"
        )

    confirmations = []
    for item in support_ranked[1:]:
        engine = str(item.get("engine") or "").lower()
        label = _committee_engine_label(engine)
        # Healthy Merton belongs here as confirmation, not as an automatic primary driver.
        role = "Financial resilience" if engine in {"merton", "merton_credit"} else label
        confirmations.append(f"**{role}:** {item.get('claim', '')}")
        if len(confirmations) == 3:
            break
    if confirmations:
        for line in confirmations:
            st.write(f"• {line}")

    st.markdown("#### Principal Concern")
    expectation_constraint = _committee_expectation_constraint(data)
    if expectation_constraint:
        st.warning(expectation_constraint)
    elif contradiction_ranked:
        concern = contradiction_ranked[0]
        st.warning(
            f"{_committee_engine_label(concern.get('engine'))}: "
            f"{concern.get('claim', 'Material counter-evidence is present.')}"
        )
    else:
        context = reasoning.get("context_evidence") or []
        if context:
            top_context = context[0]
            st.warning(
                f"Monitor {_committee_engine_label(top_context.get('engine'))}: "
                f"{top_context.get('claim', 'the setup remains incomplete.')}"
            )
        else:
            st.caption("No dominant portfolio constraint is currently identified.")

    st.markdown("#### Portfolio Conclusion")
    view = str(reasoning.get("committee_view") or "Current view")
    if expectation_constraint:
        st.write(
            f"**{view}, but valuation-sensitive.** Maintain the current bias only while operating evidence "
            "continues to support the expectations embedded in the valuation and the tactical risk framework remains intact."
        )
    else:
        st.write(
            f"**{view}.** The balance of specialist evidence supports the current stance, while position sizing, "
            "entry quality, and thesis invalidation levels should govern execution."
        )

    if contradiction_ranked:
        st.markdown("#### Counter-evidence")
        for item in contradiction_ranked[:4]:
            st.warning(
                f"{_committee_engine_label(item.get('engine'))}: "
                f"{item.get('claim', '')}"
            )

    invalidators = reasoning.get("invalidators") or []
    _render_evidence_list("What would change the committee view", invalidators, "warning")

    # Keep implementation details available for audit without exposing them in the investment narrative.
    if reasoning.get("shadow_mode") or reasoning.get("legacy_decision"):
        with st.expander("Advanced: Committee model audit", expanded=False):
            st.write("Production verdict:", reasoning.get("legacy_decision", "n/a"))
            st.write("Committee shadow view:", reasoning.get("committee_view", "n/a"))
            st.write("Effective decision:", reasoning.get("effective_decision", "n/a"))
            st.write("Shadow mode:", bool(reasoning.get("shadow_mode")))
            backend_decisive = reasoning.get("decisive_factor") or {}
            if backend_decisive:
                st.write(
                    "Backend-selected decisive witness:",
                    f"{_committee_engine_label(backend_decisive.get('engine'))} — {backend_decisive.get('claim', '')}",
                )
            if reasoning.get("committee_summary"):
                st.caption(reasoning.get("committee_summary"))

def render_explainability_workbench(data):
    st.markdown("### Understand the Decision")
    st.caption(
        "Open an expert panel to see the conclusion, inputs, supporting evidence, "
        "participant behavior, and invalidation conditions."
    )

    tabs = st.tabs([
        "Investment Committee",
        "Game Theory",
        "Expectation Investing",
        "Future Value Premium",
        "Merton / Credit",
    ])
    with tabs[0]:
        render_committee_explainer(data)
    with tabs[1]:
        render_game_theory_explainer(data)
    with tabs[2]:
        render_expectation_explainer(data)
    with tabs[3]:
        render_optionality_explainer(data)
    with tabs[4]:
        render_credit_explainer(data)


def render_analysis_card(data):
    if not isinstance(data, dict):
        st.warning("No analysis data returned.")
        return

    render_header_card(data)
    render_decision_layer(data)
    render_trade_plan(data)
    render_investment_narrative(data)
    render_specialized_engines(data)
    render_bull_bear(data)
    render_engine_scores(data)
    render_explainability_workbench(data)

    with st.expander("Key Reads"):
        reads = data.get("reads") or {}
        for k, v in reads.items():
            if v:
                st.markdown(f"**{k.replace('_', ' ').title()}:** {v}")

    with st.expander("Advanced: Raw model payload", expanded=False):
        st.caption("For audit, debugging, and model-development use.")
        st.json(data)
        
def render_clean_dashboard(df):
    st.markdown("### Top Opportunities")

    top = df[
        df["Decision"].astype(str).str.contains("Strong Long|Tactical Long", na=False)
    ].sort_values("Final Score", ascending=False)

    st.dataframe(
        top[[
            "Ticker", "Decision", "Setup", "Final Score",
            "Trade Expectancy %", "Investment View", "Trading View",
            "Theme"
        ]].head(10),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("### Watchlist / Pullback Candidates")

    watch = df[
        df["Decision"].astype(str).str.contains("Watchlist|Constructive", na=False)
    ].sort_values("Final Score", ascending=False)

    st.dataframe(
        watch[[
            "Ticker", "Decision", "Setup", "Final Score",
            "Trade Expectancy %", "Investment View", "Trading View", "Theme"
        ]].head(10),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("### Risk Radar")

    risk = df[
        (df["Options"].fillna(50) < 40)
        | (df["Game Theory"].fillna(50) < 50)
        | (df["Technical"].fillna(50) < 45)
        | (df["Merton"].fillna(100) < 50)
    ]

    st.dataframe(
        risk[[
            "Ticker", "Decision", "Final Score", "Options",
            "Game Theory", "Technical", "Merton", "Theme"
        ]].head(15),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("### Expectation Gap")

    exp_cols = [
        "Ticker", "Decision", "Final Score", "Expectation",
        "Trade Expectancy %", "Theme"
    ]

    st.dataframe(
        df[[c for c in exp_cols if c in df.columns]]
        .sort_values("Expectation", ascending=False)
        .head(15),
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("Full Export"):
        st.dataframe(df, use_container_width=True, hide_index=True)

# =============================================================================
# Sidebar
# =============================================================================
# theme_mode = st.sidebar.radio(
#     "Appearance",
#     ["Light", "Dark"],
#     horizontal=True,
# )

# apply_theme()



if "api_url" not in st.session_state:
    st.session_state.api_url = DEFAULT_API_URL
if "api_key" not in st.session_state:
    st.session_state.api_key = DEFAULT_API_KEY

st.sidebar.title("Trading Desk OS")
st.sidebar.caption("Beta frontend")
st.sidebar.text_input("API URL", key="api_url", placeholder="https://your-backend.up.railway.app")
st.sidebar.text_input("API Key", key="api_key", type="password", placeholder="tdos_xxxxx")

if st.sidebar.button("Test Connection", use_container_width=True):
    ok, resp = api_request("GET", "/api/v1/account")
    if ok:
        st.sidebar.success("Connected")
        st.sidebar.json(resp)
    else:
        st.sidebar.error("Connection failed")
        st.sidebar.write(resp)

st.sidebar.divider()
st.sidebar.caption("Tip: set TDOS_API_URL and TDOS_API_KEY in Railway variables or local environment.")


# =============================================================================
# Main UI
# =============================================================================

st.title("📈 Trading Desk OS Beta")
st.caption("Multi-factor trade decision engine: regime, theme, fundamentals, technicals, liquidity, options, game theory, Merton credit,  Greenfield ARR / Capacity Valuation, and expected return.")

# Stateful navigation is used instead of st.tabs so the Scanner can send a
# selected ticker directly to Analyze Stock and activate that view.
if "nav_page" not in st.session_state:
    st.session_state.nav_page = "Account"
if "analyze_ticker" not in st.session_state:
    st.session_state.analyze_ticker = "NVDA"

# Apply queued navigation BEFORE the nav widget is instantiated.
# This avoids StreamlitAPIException when Scanner sends a ticker to Analyze.
pending_nav_page = st.session_state.pop("pending_nav_page", None)
if pending_nav_page:
    st.session_state.nav_page = pending_nav_page

nav_page = st.radio(
    "Desk navigation",
    ["Account", "Analyze Stock", "Scanner", "Daily Report"],
    horizontal=True,
    key="nav_page",
    label_visibility="collapsed",
)


# =============================================================================
# Account
# =============================================================================

if nav_page == "Account":
    st.header("Account & Usage")
    if st.button("Refresh Account", use_container_width=False):
        ok, resp = api_request("GET", "/api/v1/account")
        if ok:
            st.success("Account loaded")
            account = extract_data(resp)
            if isinstance(account, dict):
                # API may return direct account object or wrapper with user object.
                user = account.get("user") if isinstance(account.get("user"), dict) else account
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Email", user.get("email", "n/a"))
                c2.metric("Plan", user.get("plan", "n/a"))
                c3.metric("Credits Used", user.get("monthly_credits_used", account.get("monthly_credits_used", "n/a")))
                c4.metric("Remaining", user.get("monthly_credits_remaining", account.get("monthly_credits_remaining", "n/a")))
            st.json(resp)
        else:
            show_error(resp)


# =============================================================================
# Analyze Stock
# =============================================================================

if nav_page == "Analyze Stock":
    st.header("Analyze Stock")
    c1, c2, c3 = st.columns([2, 1, 1])
    ticker = c1.text_input("Ticker", key="analyze_ticker").upper().strip()
    persist_signal = c2.checkbox("Persist signal", value=True)
    raw_mode = c3.checkbox("Show raw only", value=False)

    manual_analyze = st.button("Analyze", type="primary", use_container_width=True)
    scanner_analyze = bool(st.session_state.pop("run_analysis_from_scanner", False))

    if manual_analyze or scanner_analyze:
        if not ticker:
            st.warning("Enter a ticker")
        else:
            with st.spinner(f"Analyzing {ticker}..."):
                ok, resp = api_request(
                    "POST",
                    "/api/v1/analyze/compact",
                    payload={"ticker": ticker, "persist_signal": persist_signal},
                    timeout=180,
                )
            if ok:
                data = extract_data(resp)
                st.session_state.analysis_data = data
                st.session_state.analysis_raw_response = resp
                st.session_state.analysis_data_ticker = ticker
            else:
                show_error(resp)

    # Persist the last detailed analysis across normal Streamlit reruns.
    saved_data = st.session_state.get("analysis_data")
    saved_ticker = st.session_state.get("analysis_data_ticker")
    if isinstance(saved_data, dict) and saved_ticker == ticker:
        if raw_mode:
            st.json(st.session_state.get("analysis_raw_response", saved_data))
        else:
            render_analysis_card(saved_data)


# =============================================================================
# Scanner
# =============================================================================

if nav_page == "Scanner":
    st.header("Stock Scanner")

    c1, c2, c3 = st.columns([3, 1, 1])

    universe_text = c1.text_area(
        "Tickers",
        value="NVDA, AMD, AVGO, ANET, MRVL, MU, GOOGL, AMZN, AAPL, MSFT",
        height=100,
        help="Comma-separated tickers."
    )

    max_names = c2.number_input(
        "Max names",
        min_value=1,
        max_value=100,
        value=20,
        step=1,
    )

    include_options = c3.checkbox(
        "Include options",
        value=False,
        help="Options chains slow down bulk scans. Keep off for large scans."
    )

    tickers = [
        t.strip().upper()
        for t in universe_text.replace("\n", ",").split(",")
        if t.strip()
    ]

    if st.button("Run Scanner", type="primary", use_container_width=True):
        if not tickers:
            st.warning("Enter at least one ticker.")
        else:
            payload = {
                "tickers": tickers[: int(max_names)],
                "max_names": int(max_names),
                "include_options": bool(include_options),
                "compact": True,
            }

            with st.spinner(f"Scanning {len(payload['tickers'])} tickers..."):
                ok, resp = api_request(
                    "POST",
                    "/api/v1/scanner/compact",
                    payload=payload,
                    timeout=300,
                )

            if ok:
                df = to_scanner_df(resp)
                if df.empty:
                    st.warning("Scanner returned no rows.")
                    st.json(resp)
                else:
                    st.session_state.scanner_df = df
                    st.session_state.scanner_raw_response = resp
            else:
                show_error(resp)

    # Keep scanner results visible after reruns (including after returning from
    # a detailed single-stock analysis).
    df = st.session_state.get("scanner_df")
    if isinstance(df, pd.DataFrame) and not df.empty:
        render_metric_strip(df)
        render_opportunity_matrix(df)
        render_theme_heatmap(df)
        render_action_cards(df)
        render_risk_radar(df)

        with st.expander("Full Desk Blotter"):
            render_scanner_tables(df)


# =============================================================================
# Daily Report
# =============================================================================

if nav_page == "Daily Report":
    st.header("Daily Report")

    c1, c2 = st.columns([3, 1])

    report_tickers_text = c1.text_area(
        "Report tickers",
        value="NVDA, AMD, AVGO, ANET, MRVL, MU, GOOGL, AMZN, AAPL, MSFT",
        height=100,
    )

    report_max_names = c2.number_input(
        "Max report names",
        min_value=1,
        max_value=100,
        value=20,
        step=1,
    )

    report_tickers = parse_tickers(report_tickers_text)

    if st.button("Generate Daily Report", type="primary", use_container_width=True):
        payload = {
            "tickers": report_tickers[: int(report_max_names)],
            "max_names": int(report_max_names),
            "compact": True,
        }

        with st.spinner("Generating daily report..."):
            ok, resp = api_request(
                "POST",
                "/api/v1/report/daily",
                payload=payload,
                timeout=300,
            )

        if ok:
            data = extract_data(resp)
            if isinstance(data, dict):
                render_clean_daily_report(data)
            else:
                st.warning("Unexpected report response.")
                st.json(resp)
        else:
            show_error(resp)
# =============================================================================
# Signal History Placeholder
# =============================================================================

# with history_tab:
#     st.header("Signal History")

#     c1, c2 = st.columns([2, 1])
#     hist_ticker = c1.text_input("Ticker filter", value="")
#     hist_limit = c2.number_input("Limit", min_value=10, max_value=500, value=100, step=10)

#     if st.button("Load Signal History", type="primary", use_container_width=True):
#         params = {"limit": int(hist_limit)}
#         if hist_ticker.strip():
#             params["ticker"] = hist_ticker.strip().upper()

#         with st.spinner("Loading signal history..."):
#             ok, resp = api_request(
#                 "GET",
#                 "/api/v1/signals/history",
#                 params=params,
#                 timeout=120,
#             )

#         if ok:
#             data = extract_data(resp)
#             rows = data.get("results", []) if isinstance(data, dict) else []

#             if not rows:
#                 st.warning("No saved signals found.")
#                 st.json(resp)
#             else:
#                 df = pd.DataFrame(rows)

#                 st.success(f"Loaded {len(df)} signals")

#                 preferred_cols = [
#                     "created_at", "ticker", "decision", "setup_type",
#                     "final_score", "entry", "stop", "target1", "target2",
#                     "risk_reward", "expected_return", "regime", "theme",
#                 ]

#                 cols = [c for c in preferred_cols if c in df.columns]

#                 st.dataframe(
#                     df[cols] if cols else df,
#                     use_container_width=True,
#                     hide_index=True,
#                 )

#                 st.download_button(
#                     "Download Signal History CSV",
#                     data=df.to_csv(index=False).encode("utf-8"),
#                     file_name="tdos_signal_history.csv",
#                     mime="text/csv",
#                 )
#         else:
#             show_error(resp)
