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


# =============================================================================
# Renderers
# =============================================================================

def render_analysis_card(data: Dict[str, Any]) -> None:
    if not isinstance(data, dict):
        st.warning("No analysis data returned")
        return

    ticker = data.get("ticker", "N/A")
    decision = data.get("decision", "n/a")
    setup = data.get("setup_type", "n/a")
    regime = data.get("regime", "n/a")
    theme = data.get("theme", "n/a")

    trade_plan = data.get("trade_plan") or {}
    expected = data.get("expected_return") or {}
    scores = data.get("scores") or {}
    reads = data.get("reads") or {}

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

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Decision", decision)
    c2.metric("Final Score", safe_metric_value(data.get("final_score"), 1))
    c3.metric("Trade Expectancy", f"{expected.get('ev_pct', 'n/a')}%")
    c4.metric("Win Probability", fmt_pct(expected.get("probability_win")))

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Entry", fmt_num(trade_plan.get("entry")))
    c2.metric("Stop", fmt_num(trade_plan.get("stop")))
    c3.metric("Target 1", fmt_num(trade_plan.get("target1")))
    c4.metric("Target 2", fmt_num(trade_plan.get("target2")))
    c5.metric("Risk/Reward", fmt_num(trade_plan.get("risk_reward")))

    decision_layer = data.get("decision_layer") or {}

    if decision_layer:
        st.markdown("### Decision Layer")

        c1, c2 = st.columns(2)
        c1.metric(
            "Investment View",
            decision_layer.get("investment_view", "n/a"),
            f"{decision_layer.get('investment_score', 'n/a')}/100",
        )
        c2.metric(
            "Trading View",
            decision_layer.get("trading_view", "n/a"),
            f"{decision_layer.get('trading_score', 'n/a')}/100",
        )

        st.markdown("**Reason**")
        st.write(decision_layer.get("reason", "n/a"))

        st.markdown("**Action**")
        st.success(decision_layer.get("action", "n/a"))
    
    tech_snap = data.get("technical_snapshot") or {}
    if tech_snap:
        st.markdown("### Technical Decomposition")
        c1, c2, c3 = st.columns(3)
        c1.metric("Trend Quality", safe_metric_value(tech_snap.get("trend_quality_score"), 1))
        c1.caption(tech_snap.get("trend_signal", ""))
        c2.metric("Entry Quality", safe_metric_value(tech_snap.get("entry_quality_score"), 1))
        c2.caption(tech_snap.get("entry_signal", ""))
        c3.metric("Leadership", safe_metric_value(tech_snap.get("leadership_score"), 1))
        c3.caption(tech_snap.get("leadership_signal", ""))

    cap = data.get("capital_structure_snapshot") or {}
    neo = data.get("neocloud_snapshot") or {}
    if cap or neo:
        st.markdown("### Specialized Engines")
        cols = st.columns(2)
        with cols[0]:
            if cap:
                st.markdown("**Merton / Capital Structure**")
                st.metric("Credit Score", safe_metric_value(cap.get("score"), 1))
                st.caption(f"{cap.get('signal', 'n/a')} · Risk: {cap.get('risk', 'n/a')}")
                st.write("Distance to Default:", cap.get("distance_to_default", "n/a"))
                st.write("Annual PD Proxy:", cap.get("pd_annual_proxy_pct", "n/a"))
        with cols[1]:
            if neo and neo.get("signal") != "Not a Greenfield ARR/Capacity Valuation specific name":
                st.markdown("**Greenfield ARR/Capacity**")
                st.metric("Greenfield Score", safe_metric_value(neo.get("score"), 1))
                st.caption(neo.get("signal", "n/a"))
                st.write("EV / Current ARR:", neo.get("ev_current_arr", "n/a"))
                st.write("EV / Target ARR:", neo.get("ev_target_arr", "n/a"))

    st.markdown("### Desk Thesis")
    st.write(data.get("final_thesis", "n/a"))

    why_not = data.get("why_not_long_now") or []
    if why_not:
        st.markdown("### Why not long now / invalidation")
        for item in why_not:
            st.write(f"- {item}")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### Bull Case")
        bull = data.get("main_bull_case") or []
        if isinstance(bull, list):
            for item in bull:
                st.success(str(item))
        else:
            st.success(str(bull))
    with c2:
        st.markdown("### Bear Case")
        bear = data.get("main_bear_case") or []
        if isinstance(bear, list):
            for item in bear:
                st.error(str(item))
        else:
            st.error(str(bear))

    if reads:
        with st.expander("Key Reads", expanded=False):
            for k, v in reads.items():
                if v:
                    st.markdown(f"**{k.replace('_', ' ').title()}:** {v}")

    if scores:
        st.markdown("### Scores")
        cols = st.columns(4)
        for i, (k, v) in enumerate(scores.items()):
            with cols[i % 4]:
                render_score_bar(k.replace("_", " ").title(), v)

    with st.expander("Raw response"):
        st.json(data)


def to_scanner_df(resp: Any) -> pd.DataFrame:
    data = extract_data(resp)
    rows: List[Dict[str, Any]] = []

    if isinstance(data, dict):
        if isinstance(data.get("results"), list):
            rows = data["results"]
        elif isinstance(data.get("data"), list):
            rows = data["data"]
        elif isinstance(data.get("longs"), list) or isinstance(data.get("shorts"), list):
            rows = (data.get("longs") or []) + (data.get("shorts") or [])
        elif isinstance(data.get("items"), list):
            rows = data["items"]
        elif isinstance(data.get("scanner"), list):
            rows = data["scanner"]
        elif all(isinstance(v, dict) for v in data.values()):
            rows = list(data.values())
    elif isinstance(data, list):
        rows = data

    flat_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        r = dict(row)
        if isinstance(r.get("data"), dict):
            r = r["data"]

        trade_plan = r.pop("trade_plan", {}) if isinstance(r.get("trade_plan"), dict) else {}
        expected = r.pop("expected_return", {}) if isinstance(r.get("expected_return"), dict) else r.get("expected_return")
        scores = r.pop("scores", {}) if isinstance(r.get("scores"), dict) else {}

        for k in ["entry", "stop", "target1", "target2", "risk_reward", "position_size"]:
            if k in trade_plan:
                r[k] = trade_plan[k]
        if isinstance(expected, dict):
            r["ev_pct"] = f"{expected.get('ev_pct', 'n/a')}%"
            r["expected_r"] = expected.get("expected_r")
            r["probability_win"] = expected.get("probability_win")
        elif expected is not None:
            r["expected_return"] = expected

        for k, v in scores.items():
            r[f"score_{k}"] = v
        flat_rows.append(r)

    if not flat_rows:
        return pd.DataFrame()

    df = pd.DataFrame(flat_rows)
    preferred = [
        "ticker", "decision", "final_score", "setup_type", "ev_pct", "expected_r", "probability_win",
        "entry", "stop", "target1", "target2", "risk_reward", "position_size", "regime", "theme",
        "score_fundamental", "score_technical", "score_trend_quality", "score_entry_quality", "score_leadership",
        "score_liquidity", "score_options", "score_game_theory", "score_game", "score_catalyst",
        "score_expectation", "score_merton", "score_neocloud",
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
                    timeout=180,
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
    default_watchlist = "NVDA,AAPL,MSFT,AMZN,META,GOOGL,TSLA,AMD,AVGO,PLTR,MRVL,ANET,CRWV,NBIS,IREN"
    watchlist_text = st.text_area("Tickers", value=default_watchlist, height=90)
    uploaded = st.file_uploader("Optional CSV watchlist", type=["csv"])
    include_options = st.checkbox("Include options", value=True, key="scanner_include_options")

    tickers: List[str] = []
    if uploaded is not None:
        try:
            df_upload = pd.read_csv(uploaded)
            first_col = df_upload.columns[0]
            tickers = df_upload[first_col].dropna().astype(str).str.upper().str.strip().tolist()
        except Exception as exc:
            st.error(f"Could not read CSV: {exc}")
    else:
        tickers = parse_tickers(watchlist_text)

    max_tickers = st.slider("Max tickers this run", 1, 100, min(20, max(1, len(tickers))))
    tickers = tickers[:max_tickers]

    if st.button("Run Scanner", type="primary", use_container_width=True):
        if not tickers:
            st.warning("Add at least one ticker")
        else:
            payload = {
                "tickers": tickers,
                "max_names": len(tickers),
                "include_options": include_options,
            }
            with st.spinner(f"Scanning {len(tickers)} tickers..."):
                ok, resp = api_request("POST", "/api/v1/scanner/compact", payload=payload, timeout=600)

                # Backward-compatible fallback for older backend builds.
                if not ok and isinstance(resp, dict) and resp.get("status_code") == 405:
                    ok, resp = api_request(
                        "GET",
                        "/api/v1/scanner/compact",
                        params={"tickers": ",".join(tickers)},
                        timeout=600,
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
    report_tickers_text = st.text_area(
        "Report tickers",
        value="NVDA,AAPL,MSFT,AMZN,META,GOOGL,TSLA,AMD,AVGO,PLTR,MRVL,ANET",
        height=90,
    )
    report_title = st.text_input("Report title", value="Trading Desk OS Daily Report")
    report_max_names = st.slider("Max report names", 1, 100, 20)
    include_signal_records = st.checkbox("Record report signals", value=True)

    if st.button("Generate Daily Report", type="primary", use_container_width=True):
        report_tickers = parse_tickers(report_tickers_text)[:report_max_names]
        if not report_tickers:
            st.warning("Add at least one report ticker")
        else:
            payload = {
                "tickers": report_tickers,
                "title": report_title,
                "max_names": report_max_names,
                "include_signal_records": include_signal_records,
            }
            with st.spinner("Generating report..."):
                ok, resp = api_request("POST", "/api/v1/report/daily", payload=payload, timeout=900)

                # Backward-compatible fallback for older backend builds.
                if not ok and isinstance(resp, dict) and resp.get("status_code") == 405:
                    ok, resp = api_request(
                        "GET",
                        "/api/v1/report/daily",
                        params={"tickers": ",".join(report_tickers)},
                        timeout=900,
                    )

            if ok:
                data = extract_data(resp)
                st.success("Report generated")
                if isinstance(data, dict):
                    html = data.get("html_text") or data.get("html") or data.get("html_report")
                    markdown = data.get("markdown_text") or data.get("markdown") or data.get("email") or data.get("text")
                    telegram = data.get("telegram_text") or data.get("telegram")
                    executive_summary = data.get("executive_summary")

                    if executive_summary:
                        st.subheader("Executive Summary")
                        st.write(executive_summary)

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
