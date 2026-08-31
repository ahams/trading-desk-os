from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Optional

import pandas as pd
import yfinance as yf

from utils import logger


DEFAULT_UNIVERSES = {
    "Mega-cap Tech": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "AVGO", "TSLA", "AMD", "NFLX"],
    "Sector ETFs": ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLC", "XLP", "XLU", "XLB", "SMH"],
    "Liquid Momentum": ["PLTR", "COIN", "MSTR", "SOFI", "HOOD", "ARM", "TSM", "CRWD", "NET", "RBLX", "U", "SHOP"],
}

# Fields that matter most to TDOS fundamentals / expectation / Merton / optionality.
CRITICAL_INFO_FIELDS = (
    "symbol",
    "marketCap",
    "enterpriseValue",
    "totalRevenue",
    "revenueGrowth",
    "ebitda",
    "totalCash",
    "totalDebt",
    "freeCashflow",
    "operatingCashflow",
    "sharesOutstanding",
    "returnOnAssets",
    "returnOnEquity",
)


def load_universe(name: str) -> list[str]:
    if name in DEFAULT_UNIVERSES:
        return DEFAULT_UNIVERSES[name]

    if name == "S&P 500":
        try:
            return (
                pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")[0]["Symbol"]
                .str.replace(".", "-", regex=False)
                .tolist()
            )
        except Exception as exc:
            logger.warning("SP500 load failed: %s", exc)
            return DEFAULT_UNIVERSES["Mega-cap Tech"]

    if name == "Nasdaq 100":
        try:
            tables = pd.read_html("https://en.wikipedia.org/wiki/Nasdaq-100")
            for table in tables:
                if "Ticker" in table.columns:
                    return (
                        table["Ticker"]
                        .astype(str)
                        .str.replace(".", "-", regex=False)
                        .tolist()
                    )
        except Exception as exc:
            logger.warning("NDX load failed: %s", exc)

    return DEFAULT_UNIVERSES["Mega-cap Tech"]


def parse_tickers(manual: str = "", csv_file=None, universe: Optional[str] = None) -> list[str]:
    tickers: list[str] = []

    if universe and universe != "None":
        tickers += load_universe(universe)

    if manual:
        tickers += [
            value.strip().upper().replace(".", "-")
            for value in manual.replace("\n", ",").split(",")
            if value.strip()
        ]

    if csv_file is not None:
        df = pd.read_csv(csv_file)
        column = "ticker" if "ticker" in df.columns else df.columns[0]
        tickers += (
            df[column]
            .dropna()
            .astype(str)
            .str.upper()
            .str.replace(".", "-", regex=False)
            .tolist()
        )

    return sorted(set(tickers))


def _normalize_ticker(ticker: str) -> str:
    return str(ticker).strip().upper().replace(".", "-")


def get_ohlcv(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    ticker = _normalize_ticker(ticker)
    try:
        df = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False,
            threads=False,
        )
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns=str.title).dropna()
        df.index = pd.to_datetime(df.index)
        return df
    except Exception as exc:
        logger.warning("OHLCV failed %s: %s", ticker, exc)
        return pd.DataFrame()


def _safe_fast_info(tk: yf.Ticker) -> dict:
    """Best-effort lightweight Yahoo fallback.

    fast_info does not contain all fundamental fields required by TDOS, but it can
    preserve important market-value fields when Yahoo's full get_info endpoint is
    incomplete or temporarily unavailable.
    """
    try:
        fast = tk.fast_info
        if fast is None:
            return {}

        aliases = {
            "market_cap": "marketCap",
            "last_price": "currentPrice",
            "previous_close": "previousClose",
            "shares": "sharesOutstanding",
            "currency": "currency",
        }

        out: dict = {}
        for source, target in aliases.items():
            try:
                value = fast[source]
            except Exception:
                try:
                    value = getattr(fast, source)
                except Exception:
                    value = None
            if value is not None:
                out[target] = value
        return out
    except Exception as exc:
        logger.warning("fast_info failed: %s", exc)
        return {}


def _info_quality(info: dict) -> tuple[int, list[str]]:
    if not isinstance(info, dict):
        return 0, list(CRITICAL_INFO_FIELDS)
    missing = [key for key in CRITICAL_INFO_FIELDS if info.get(key) is None]
    return len(CRITICAL_INFO_FIELDS) - len(missing), missing


def _log_info_quality(ticker: str, info: dict, source: str) -> None:
    score, missing = _info_quality(info)
    logger.warning(
        "GET_INFO %s source=%s keys=%d critical=%d/%d symbol=%s marketCap=%s "
        "enterpriseValue=%s totalRevenue=%s revenueGrowth=%s totalCash=%s totalDebt=%s "
        "missing=%s",
        ticker,
        source,
        len(info),
        score,
        len(CRITICAL_INFO_FIELDS),
        info.get("symbol"),
        info.get("marketCap"),
        info.get("enterpriseValue"),
        info.get("totalRevenue"),
        info.get("revenueGrowth"),
        info.get("totalCash"),
        info.get("totalDebt"),
        ",".join(missing),
    )


def get_info(ticker: str) -> dict:
    """Return the best Yahoo fundamentals dictionary available.

    Important production behavior:
    - no Streamlit dependency/cache;
    - retries Yahoo's full info endpoint;
    - supplements missing lightweight market fields from fast_info;
    - never raises into the analysis pipeline;
    - logs data quality so Render failures are visible.

    This preserves the existing TDOS `info` contract, so downstream engines do
    not need to change.
    """
    ticker = _normalize_ticker(ticker)
    last_error: Exception | None = None

    for attempt in range(1, 3):
        try:
            tk = yf.Ticker(ticker)
            info = tk.get_info() or {}
            if not isinstance(info, dict):
                info = dict(info)

            # Always preserve the requested ticker even if Yahoo omits symbol.
            info.setdefault("symbol", ticker)

            fast = _safe_fast_info(tk)
            for key, value in fast.items():
                if info.get(key) is None and value is not None:
                    info[key] = value

            _log_info_quality(ticker, info, source=f"yfinance.get_info attempt={attempt}")

            # A non-trivial dictionary is useful even if some optional fields are
            # absent. Downstream engines already handle individual missing fields.
            if len(info) >= 10:
                return info

            logger.warning(
                "GET_INFO %s returned only %d keys on attempt %d; retrying",
                ticker,
                len(info),
                attempt,
            )
        except Exception as exc:
            last_error = exc
            logger.exception("GET_INFO FAILED %s attempt=%d: %s", ticker, attempt, exc)

        if attempt < 2:
            time.sleep(0.75)

    # Final fallback: fast_info is better than silently returning a completely
    # anonymous empty dictionary, although TDOS specialist engines may still mark
    # fundamentals as insufficient when accounting fields are unavailable.
    try:
        tk = yf.Ticker(ticker)
        fallback = _safe_fast_info(tk)
        fallback.setdefault("symbol", ticker)
        _log_info_quality(ticker, fallback, source="yfinance.fast_info fallback")
        return fallback
    except Exception as exc:
        logger.exception(
            "GET_INFO FINAL FAILURE %s: %s (previous=%s)",
            ticker,
            exc,
            last_error,
        )
        return {"symbol": ticker}


def get_options_chain(ticker: str):
    ticker = _normalize_ticker(ticker)
    try:
        tk = yf.Ticker(ticker)
        expiries = list(tk.options)
        if not expiries:
            return None, pd.DataFrame(), pd.DataFrame()
        expiry = expiries[0]
        chain = tk.option_chain(expiry)
        return expiry, chain.calls.copy(), chain.puts.copy()
    except Exception as exc:
        logger.warning("options failed %s: %s", ticker, exc)
        return None, pd.DataFrame(), pd.DataFrame()


def get_news(ticker: str, limit: int = 8) -> list[dict]:
    ticker = _normalize_ticker(ticker)
    try:
        return (yf.Ticker(ticker).news or [])[:limit]
    except Exception as exc:
        logger.warning("news failed %s: %s", ticker, exc)
        return []
