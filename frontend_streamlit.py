"""
Trading Desk OS - Beta Frontend
--------------------------------
Streamlit UI that connects to the FastAPI monetized backend.

Run:
    streamlit run frontend_streamlit.py

Expected backend endpoints:
    GET  /api/v1/account
    POST /api/v1/analyze/compact
    GET  /api/v1/scanner/compact?tickers=AAPL,NVDA
    GET  /api/v1/report/daily?tickers=AAPL,NVDA

Environment variables supported:
    TDOS_API_URL
    TDOS_API_KEY
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st


# =============================================================================
# Page Config
# =============================================================================

st.set_page_config(
    page_title="Trading Desk OS Beta",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =============================================================================
# Helpers
# =============================================================================

DEFAULT_API_URL = os.getenv("TDOS_API_URL", "http://127.0.0.1:8000")
DEFAULT_API_KEY = os.getenv("TDOS_API_KEY", "")


def normalize_base_url(url: str) -> str:
    url = (url or "").strip()
    return url.rstrip("/")


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
        if "application/json" in content_type:
            body = resp.json()
        else:
            body = resp.text

        if resp.status_code >= 400:
            return False, {
                "status_code": resp.status_code,
                "error": body,
                "url": url,
            }

        return True, body

    except requests.exceptions.ConnectionError:
        return False, f"Could not connect to API at {url}. Is uvicorn running?"
    except requests.exceptions.Timeout:
        return False, f"Request timed out after {timeout}s: {url}"
    except Exception as exc:
        return False, f"Unexpected API error: {exc}"


def extract_data(resp: Any) -> Dict[str, Any]:
    """API may return {user, credits_used, data}; compact endpoints may return direct data."""
    if isinstance(resp, dict) and "data" in resp and isinstance(resp["data"], dict):
        return resp["data"]
    return resp if isinstance(resp, dict) else {"raw": resp}


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


def render_metric_card(title: str, value: str, help_text: Optional[str] = None) -> None:
    st.metric(title, value, help=help_text)


def render_trade_plan(data: Dict[str, Any]) -> None:
    decision = data.get("decision") or data.get("final_decision") or "n/a"
    score = data.get("final_score") or data.get("score") or data.get("confidence")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Decision", decision)
    c2.metric("Final Score", fmt_num(score, 1))
    c3.metric("Expected Return", fmt_pct(data.get("expected_return") or data.get("expected_return_pct")))
    c4.metric("Win Probability", fmt_pct(data.get("probability_win")))

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Entry", fmt_num(data.get("entry") or data.get("best_entry")))
    c2.metric("Stop", fmt_num(data.get("stop") or data.get("stop_loss")))
    c3.metric("Target 1", fmt_num(data.get("target1") or data.get("target_1")))
    c4.metric("Target 2", fmt_num(data.get("target2") or data.get("target_2")))
    c5.metric("Risk/Reward", fmt_num(data.get("rr") or data.get("risk_reward")))


def render_analysis_card(data: Dict[str, Any]) -> None:
    ticker = data.get("ticker", "Ticker")
    decision = data.get("decision", "n/a")
    setup = data.get("setup_type") or data.get("setup") or "n/a"
    regime = data.get("regime", "n/a")
    theme = data.get("theme", "n/a")

    st.markdown(
        f"""
        <div style="border:1px solid #e5e7eb;border-radius:14px;padding:18px;margin-bottom:14px;">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <div>
              <h2 style="margin:0;">{ticker}</h2>
              <div style="color:#6b7280;">{setup} · Regime: {regime} · Theme: {theme}</div>
            </div>
            <div style="background:{decision_color(decision)};color:white;padding:8px 14px;border-radius:999px;font-weight:700;">
              {decision}
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    render_trade_plan(data)

    st.divider()

    thesis = data.get("final_thesis") or data.get("thesis") or data.get("summary")
    if isinstance(thesis, dict):
        thesis = thesis.get("final_thesis") or json.dumps(thesis, indent=2)
    if thesis:
        st.subheader("Desk Thesis")
        st.write(thesis)

    why_not = data.get("why_not_long_now") or data.get("why_not_trade_now") or data.get("invalidating_conditions")
    if why_not:
        st.subheader("Why not long now / invalidation")
        if isinstance(why_not, list):
            for item in why_not:
                st.warning(str(item))
        else:
            st.warning(str(why_not))

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Bull Case")
        bull = data.get("main_bull_case") or data.get("bull_case") or data.get("bull")
        st.success(bull if bull else "n/a")
    with c2:
        st.subheader("Bear Case")
        bear = data.get("main_bear_case") or data.get("bear_case") or data.get("bear")
        st.error(bear if bear else "n/a")

    st.divider()
    scores = data.get("scores", {})
    if isinstance(scores, dict) and scores:
        st.subheader("Scores")
        cols = st.columns(3)
        for i, (k, v) in enumerate(scores.items()):
            with cols[i % 3]:
                render_score_bar(k.replace("_", " ").title(), v)

    snapshots = {
        "Options Read": data.get("options_read"),
        "Game Theory Read": data.get("game_theory_read"),
        "Catalyst Read": data.get("catalyst_read"),
        "Liquidity Read": data.get("liquidity_read"),
        "Technical Read": data.get("technical_read"),
        "Expectation Read": data.get("expectation_read"),
    }
    clean = {k: v for k, v in snapshots.items() if v}
    if clean:
        st.subheader("Key Reads")
        for k, v in clean.items():
            st.markdown(f"**{k}:** {v}")

    with st.expander("Raw response"):
        st.json(data)


def to_scanner_df(resp: Any) -> pd.DataFrame:
    data = extract_data(resp)
    rows = []

    if isinstance(data, dict):
        if isinstance(data.get("results"), list):
            rows = data["results"]
        elif isinstance(data.get("longs"), list) or isinstance(data.get("shorts"), list):
            rows = (data.get("longs") or []) + (data.get("shorts") or [])
        elif isinstance(data.get("items"), list):
            rows = data["items"]
        elif isinstance(data.get("scanner"), list):
            rows = data["scanner"]
        else:
            # If dict of ticker -> analysis
            if all(isinstance(v, dict) for v in data.values()):
                rows = list(data.values())
    elif isinstance(data, list):
        rows = data

    if not rows:
        return pd.DataFrame()

    flat_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        r = dict(row)
        if "data" in r and isinstance(r["data"], dict):
            r = r["data"]
        scores = r.pop("scores", {}) if isinstance(r.get("scores"), dict) else {}
        for k, v in scores.items():
            r[f"score_{k}"] = v
        flat_rows.append(r)

    df = pd.DataFrame(flat_rows)
    preferred = [
        "ticker", "decision", "final_score", "score", "setup_type", "expected_return",
        "entry", "stop", "target1", "target2", "rr", "regime", "theme",
        "score_fundamental", "score_technical", "score_liquidity", "score_options",
        "score_game", "score_catalyst", "score_expectation",
    ]
    cols = [c for c in preferred if c in df.columns] + [c for c in df.columns if c not in preferred]
    return df[cols]


# =============================================================================
# Sidebar
# =============================================================================

if "api_url" not in st.session_state:
    st.session_state.api_url = DEFAULT_API_URL
if "api_key" not in st.session_state:
    st.session_state.api_key = DEFAULT_API_KEY

st.sidebar.title("Trading Desk OS")
st.sidebar.caption("Beta frontend")

st.sidebar.text_input("API URL", key="api_url", placeholder="http://127.0.0.1:8000")
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
st.sidebar.caption("Tip: set TDOS_API_URL and TDOS_API_KEY in .env or shell env for defaults.")


# =============================================================================
# Main UI
# =============================================================================

st.title("📈 Trading Desk OS Beta")
st.caption("Multi-factor trade decision engine: regime, theme, fundamentals, technicals, liquidity, options, game theory, and expected return.")

account_tab, analyze_tab, scanner_tab, report_tab, history_tab = st.tabs(
    ["Account", "Analyze Stock", "Scanner", "Daily Report", "Signal History"]
)


# =============================================================================
# Account
# =============================================================================

with account_tab:
    st.header("Account & Usage")
    if st.button("Refresh Account", use_container_width=False):
        ok, resp = api_request("GET", "/api/v1/account")
        if ok:
            st.success("Account loaded")
            data = extract_data(resp)
            if isinstance(resp, dict):
                user = resp.get("user", {})
                c1, c2, c3 = st.columns(3)
                c1.metric("Email", user.get("email", "n/a"))
                c2.metric("Plan", user.get("plan", "n/a"))
                c3.metric("Credits Used", resp.get("credits_used", "n/a"))
            st.json(resp)
        else:
            show_error(resp)


# =============================================================================
# Analyze Stock
# =============================================================================

with analyze_tab:
    st.header("Analyze Stock")
    c1, c2, c3 = st.columns([2, 1, 1])
    ticker = c1.text_input("Ticker", value="NVDA").upper().strip()
    persist_signal = c2.checkbox("Persist signal", value=True)
    raw_mode = c3.checkbox("Show raw only", value=False)

    if st.button("Analyze", type="primary", use_container_width=True):
        if not ticker:
            st.warning("Enter a ticker")
        else:
            with st.spinner(f"Analyzing {ticker}..."):
                ok, resp = api_request(
                    "POST",
                    "/api/v1/analyze/compact",
                    payload={"ticker": ticker, "persist_signal": persist_signal},
                    timeout=120,
                )
            if ok:
                data = extract_data(resp)
                if raw_mode:
                    st.json(resp)
                else:
                    render_analysis_card(data)
            else:
                show_error(resp)


# =============================================================================
# Scanner
# =============================================================================

with scanner_tab:
    st.header("Scanner")
    default_watchlist = "NVDA,AAPL,MSFT,AMZN,META,GOOGL,TSLA,AMD,AVGO,PLTR"
    watchlist_text = st.text_area("Tickers", value=default_watchlist, height=90)
    uploaded = st.file_uploader("Optional CSV watchlist", type=["csv"])

    tickers: List[str] = []
    if uploaded is not None:
        try:
            df_upload = pd.read_csv(uploaded)
            first_col = df_upload.columns[0]
            tickers = df_upload[first_col].dropna().astype(str).str.upper().str.strip().tolist()
        except Exception as exc:
            st.error(f"Could not read CSV: {exc}")
    else:
        tickers = [x.strip().upper() for x in watchlist_text.replace("\n", ",").split(",") if x.strip()]

    max_tickers = st.slider("Max tickers this run", 1, 100, min(20, max(1, len(tickers))))
    tickers = tickers[:max_tickers]

    if st.button("Run Scanner", type="primary", use_container_width=True):
        if not tickers:
            st.warning("Add at least one ticker")
        else:
            with st.spinner(f"Scanning {len(tickers)} tickers..."):
                ok, resp = api_request(
                    "GET",
                    "/api/v1/scanner/compact",
                    params={"tickers": ",".join(tickers)},
                    timeout=300,
                )
            if ok:
                df = to_scanner_df(resp)
                if df.empty:
                    st.warning("Scanner returned no rows. Raw response below.")
                    st.json(resp)
                else:
                    st.success(f"Loaded {len(df)} scanner rows")
                    st.dataframe(df, use_container_width=True, hide_index=True)
                    csv = df.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        "Download Scanner CSV",
                        data=csv,
                        file_name=f"tdos_scanner_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                    )
                    with st.expander("Raw response"):
                        st.json(resp)
            else:
                show_error(resp)


# =============================================================================
# Daily Report
# =============================================================================

with report_tab:
    st.header("Daily Report")
    report_tickers = st.text_input(
        "Report tickers",
        value="NVDA,AAPL,MSFT,AMZN,META,GOOGL,TSLA,AMD,AVGO,PLTR",
    )
    if st.button("Generate Daily Report", type="primary", use_container_width=True):
        with st.spinner("Generating report..."):
            ok, resp = api_request(
                "GET",
                "/api/v1/report/daily",
                params={"tickers": report_tickers},
                timeout=300,
            )
        if ok:
            data = extract_data(resp)
            st.success("Report generated")
            if isinstance(data, dict):
                html = data.get("html") or data.get("html_report")
                markdown = data.get("markdown") or data.get("email") or data.get("text")
                telegram = data.get("telegram") or data.get("telegram_text")

                if markdown:
                    st.subheader("Markdown / Email")
                    st.markdown(markdown)
                    st.download_button(
                        "Download Markdown",
                        markdown,
                        file_name="tdos_daily_report.md",
                        mime="text/markdown",
                    )

                if html:
                    st.subheader("HTML Preview")
                    st.components.v1.html(html, height=700, scrolling=True)
                    st.download_button(
                        "Download HTML",
                        html,
                        file_name="tdos_daily_report.html",
                        mime="text/html",
                    )

                if telegram:
                    st.subheader("Telegram Text")
                    st.code(telegram, language="text")
            else:
                st.write(data)

            with st.expander("Raw response"):
                st.json(resp)
        else:
            show_error(resp)


# =============================================================================
# Signal History Placeholder
# =============================================================================

with history_tab:
    st.header("Signal History")
    st.info("This tab is ready for the next backend endpoint: GET /api/v1/signals/history")
    st.markdown(
        """
        Suggested next beta endpoint:

        ```http
        GET /api/v1/signals/history?ticker=NVDA&limit=100
        ```

        It should return saved forward-test signals with status, 5d/10d/20d returns,
        target hit, stop hit, and max favorable/adverse excursion.
        """
    )
