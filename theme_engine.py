"""
theme_engine.py

Cross-asset / theme-flow engine for Trading Desk OS.

It scores whether a stock has support from its broader theme basket, sector ETF,
market regime, relative strength, and catalyst tags.

Main public API:
    analyze_theme(ticker, stock_df, theme_map=None, market_data=None, news_items=None, sector=None) -> dict
    scan_themes(market_data, theme_map=None) -> pd.DataFrame

Return contract is scanner-compatible:
    {"total": 0-100, "theme": str, "flags": [...], "metrics": {...}, "summary": str}
"""
from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    from utils import clamp
except Exception:
    def clamp(x, lo=0, hi=100):
        try:
            if pd.isna(x):
                return 50
            return max(lo, min(hi, float(x)))
        except Exception:
            return 50

logger = logging.getLogger("trading_desk.theme_engine")

DEFAULT_THEME_MAP: Dict[str, Dict[str, object]] = {
    "AI Infrastructure": {
        "tickers": ["NVDA", "AVGO", "AMD", "TSM", "ARM", "SMCI", "DELL", "ANET", "VRT", "PLTR", "ORCL", "MU"],
        "etfs": ["SMH", "QQQ", "XLK"],
        "keywords": ["ai", "artificial intelligence", "gpu", "datacenter", "data center", "accelerator", "inference"],
    },
    "Semiconductors": {
        "tickers": ["NVDA", "AVGO", "AMD", "TSM", "ASML", "AMAT", "LRCX", "KLAC", "MU", "ARM", "QCOM", "INTC"],
        "etfs": ["SMH", "SOXX"],
        "keywords": ["semiconductor", "chip", "foundry", "wafer", "memory", "hbm"],
    },
    "Nuclear / Power": {
        "tickers": ["CCJ", "CEG", "VST", "TLN", "OKLO", "SMR", "BWXT", "GEV"],
        "etfs": ["XLU", "URA"],
        "keywords": ["nuclear", "uranium", "power", "reactor", "energy demand", "grid"],
    },
    "Defense": {
        "tickers": ["LMT", "RTX", "NOC", "GD", "KTOS", "AVAV", "HII", "TXT"],
        "etfs": ["ITA", "XLI"],
        "keywords": ["defense", "drone", "missile", "contract", "pentagon", "geopolitical"],
    },
    "Crypto / Digital Assets": {
        "tickers": ["COIN", "MSTR", "MARA", "RIOT", "CLSK", "HOOD", "IBIT", "BITO"],
        "etfs": ["IBIT", "BITO", "QQQ"],
        "keywords": ["bitcoin", "crypto", "ethereum", "blockchain", "digital asset"],
    },
    "Solar / Clean Energy": {
        "tickers": ["FSLR", "ENPH", "SEDG", "ARRY", "NXT", "RUN", "BE", "PLUG"],
        "etfs": ["TAN", "ICLN"],
        "keywords": ["solar", "photovoltaic", "renewable", "clean energy", "inverter", "battery"],
    },
    "Biotech Momentum": {
        "tickers": ["XBI", "IBB", "MRNA", "BNTX", "CRSP", "EDIT", "NTLA", "RXRX", "VKTX"],
        "etfs": ["XBI", "IBB"],
        "keywords": ["fda", "phase", "trial", "oncology", "rare disease", "gene therapy", "biotech"],
    },
}

SECTOR_ETF_MAP = {
    "Technology": "XLK",
    "Communication Services": "XLC",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Industrials": "XLI",
    "Energy": "XLE",
    "Utilities": "XLU",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
}


def _normalize(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.get_level_values(0)
    out.columns = [str(c).title() for c in out.columns]
    if "Adj Close" in out.columns and "Close" not in out.columns:
        out["Close"] = out["Adj Close"]
    if "Close" not in out:
        return None
    return out.dropna(subset=["Close"])


def _get(market_data: Dict[str, pd.DataFrame], symbol: str) -> Optional[pd.DataFrame]:
    if not market_data:
        return None
    for k, v in market_data.items():
        if str(k).upper() == str(symbol).upper():
            return _normalize(v)
    return None


def _ret(df: Optional[pd.DataFrame], n: int = 20) -> Optional[float]:
    try:
        c = df["Close"].dropna()
        if len(c) <= n:
            return None
        return float(c.iloc[-1] / c.iloc[-n - 1] - 1)
    except Exception:
        return None


def _volume_surge(df: Optional[pd.DataFrame]) -> Optional[float]:
    try:
        if "Volume" not in df:
            return None
        v = df["Volume"].dropna()
        if len(v) < 21:
            return None
        avg = float(v.rolling(20).mean().iloc[-1])
        return float(v.iloc[-1] / avg) if avg > 0 else None
    except Exception:
        return None


def _keyword_hits(news_items: Optional[List[dict]], keywords: Iterable[str]) -> List[str]:
    if not news_items:
        return []
    text_parts = []
    for item in news_items:
        if isinstance(item, dict):
            text_parts.append(str(item.get("title", "")))
            text_parts.append(str(item.get("summary", "")))
            text_parts.append(str(item.get("publisher", "")))
        else:
            text_parts.append(str(item))
    text = " ".join(text_parts).lower()
    return sorted({kw for kw in keywords if kw and str(kw).lower() in text})


def infer_theme(ticker: str, news_items: Optional[List[dict]] = None, theme_map: Optional[dict] = None) -> Tuple[str, List[str]]:
    """Infer likely theme from ticker membership and news keyword hits."""
    theme_map = theme_map or DEFAULT_THEME_MAP
    t = str(ticker).upper()
    best_theme = "General Market"
    best_hits = []
    best_score = -1
    for theme, meta in theme_map.items():
        tickers = [x.upper() for x in meta.get("tickers", [])]
        keywords = meta.get("keywords", [])
        hits = _keyword_hits(news_items, keywords)
        score = (3 if t in tickers else 0) + len(hits)
        if score > best_score:
            best_theme, best_hits, best_score = theme, hits, score
    return best_theme, best_hits


def _basket_returns(theme: str, market_data: Dict[str, pd.DataFrame], theme_map: dict, n: int = 20) -> Tuple[Optional[float], Dict[str, float]]:
    meta = theme_map.get(theme, {})
    members = list(meta.get("tickers", [])) + list(meta.get("etfs", []))
    vals = {}
    for sym in members:
        df = _get(market_data, sym)
        r = _ret(df, n)
        if r is not None:
            vals[sym] = r
    if not vals:
        return None, {}
    return float(np.nanmean(list(vals.values()))), vals


def scan_themes(market_data: Dict[str, pd.DataFrame], theme_map: Optional[dict] = None, lookback: int = 20) -> pd.DataFrame:
    """Rank configured themes by basket momentum and breadth."""
    theme_map = theme_map or DEFAULT_THEME_MAP
    rows = []
    for theme, meta in theme_map.items():
        basket_ret, components = _basket_returns(theme, market_data or {}, theme_map, lookback)
        if not components:
            rows.append({"theme": theme, "score": 50, "basket_return": np.nan, "breadth": np.nan, "leaders": ""})
            continue
        rets = pd.Series(components).sort_values(ascending=False)
        breadth = float((rets > 0).mean())
        score = 50 + 500 * (basket_ret or 0) + 25 * (breadth - 0.5)
        leaders = ", ".join(rets.head(3).index.tolist())
        rows.append({
            "theme": theme,
            "score": round(clamp(score), 1),
            "basket_return": basket_ret,
            "breadth": breadth,
            "leaders": leaders,
            "component_count": len(rets),
        })
    return pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)


def analyze_theme(
    ticker: str,
    stock_df: pd.DataFrame,
    theme_map: Optional[dict] = None,
    market_data: Optional[Dict[str, pd.DataFrame]] = None,
    news_items: Optional[List[dict]] = None,
    sector: Optional[str] = None,
    regime_result: Optional[dict] = None,
) -> dict:
    """Score a ticker's cross-asset/theme confirmation.

    This is deliberately not a pure news classifier. It asks whether the trade
    is being confirmed by the asset's theme, sector ETF, and market regime.
    """
    theme_map = theme_map or DEFAULT_THEME_MAP
    market_data = market_data or {}
    stock_df = _normalize(stock_df)

    flags, metrics = [], {}
    theme, keyword_hits = infer_theme(ticker, news_items, theme_map)
    sector_etf = SECTOR_ETF_MAP.get(sector or "")

    stock_5d = _ret(stock_df, 5)
    stock_20d = _ret(stock_df, 20)
    rel_vol = _volume_surge(stock_df)
    spy_20d = _ret(_get(market_data, "SPY"), 20)
    qqq_20d = _ret(_get(market_data, "QQQ"), 20)
    sector_20d = _ret(_get(market_data, sector_etf), 20) if sector_etf else None
    basket_20d, components = _basket_returns(theme, market_data, theme_map, 20)

    metrics.update({
        "theme": theme,
        "keyword_hits": keyword_hits,
        "sector": sector,
        "sector_etf": sector_etf,
        "stock_5d_return": stock_5d,
        "stock_20d_return": stock_20d,
        "spy_20d_return": spy_20d,
        "qqq_20d_return": qqq_20d,
        "sector_20d_return": sector_20d,
        "theme_basket_20d_return": basket_20d,
        "relative_volume": rel_vol,
        "theme_components_available": len(components),
    })

    score = 50.0

    if stock_20d is not None:
        score += clamp(stock_20d * 350, -15, 15)
        if stock_20d > 0.08:
            flags.append("Stock has strong 20-day momentum")
        elif stock_20d < -0.08:
            flags.append("Stock has weak 20-day momentum")

    if spy_20d is not None and stock_20d is not None:
        rs_spy = stock_20d - spy_20d
        metrics["relative_strength_vs_spy_20d"] = rs_spy
        if rs_spy > 0.05:
            score += 12
            flags.append("Strong relative strength vs SPY")
        elif rs_spy < -0.05:
            score -= 12
            flags.append("Weak relative strength vs SPY")

    if sector_20d is not None and stock_20d is not None:
        rs_sector = stock_20d - sector_20d
        metrics["relative_strength_vs_sector_20d"] = rs_sector
        if rs_sector > 0.04:
            score += 8
            flags.append("Stock leading sector ETF")
        elif rs_sector < -0.04:
            score -= 8
            flags.append("Stock lagging sector ETF")

    if basket_20d is not None:
        if basket_20d > 0.04:
            score += 12
            flags.append(f"Theme basket '{theme}' is in positive flow")
        elif basket_20d < -0.04:
            score -= 12
            flags.append(f"Theme basket '{theme}' is deteriorating")

        if stock_20d is not None:
            rs_theme = stock_20d - basket_20d
            metrics["relative_strength_vs_theme_20d"] = rs_theme
            if rs_theme > 0.05:
                score += 8
                flags.append("Ticker is a theme leader")
            elif rs_theme < -0.06:
                score -= 8
                flags.append("Ticker is lagging its own theme")

    if keyword_hits:
        score += min(10, 3 * len(keyword_hits))
        flags.append("News/catalyst keywords match active theme: " + ", ".join(keyword_hits[:4]))

    if rel_vol is not None:
        if rel_vol > 2.0:
            score += 8
            flags.append("Theme move confirmed by elevated volume")
        elif rel_vol < 0.5:
            score -= 5

    regime = (regime_result or {}).get("regime")
    if regime == "RISK_ON" and score > 55:
        score += 5
        flags.append("Risk-on regime supports thematic longs")
    elif regime == "RISK_OFF" and score > 60:
        score -= 6
        flags.append("Risk-off regime reduces confidence in thematic longs")

    score = clamp(score)
    if not flags:
        flags.append("No strong theme confirmation detected")

    leader_text = ""
    if components:
        leaders = pd.Series(components).sort_values(ascending=False).head(3)
        leader_text = "; leaders: " + ", ".join([f"{k} {v:.1%}" for k, v in leaders.items()])

    summary = (
        f"Theme read: {theme}. Score {score:.0f}/100. "
        f"{flags[0]}{leader_text}."
    )
    return {
        "total": round(score, 1),
        "theme": theme,
        "flags": flags,
        "metrics": metrics,
        "summary": summary,
    }

# -----------------------------------------------------------------------------
# Backward/forward compatibility alias
# -----------------------------------------------------------------------------
def rank_themes(market_data=None, theme_map=None, lookback=20, top_n=None):
    """Compatibility wrapper used by the FastAPI/report layer.

    Older service code imports `rank_themes`, while the theme module exposes
    `scan_themes`. This wrapper keeps both names valid.
    """
    df = scan_themes(market_data or {}, theme_map=theme_map, lookback=lookback)
    if top_n is not None:
        try:
            return df.head(int(top_n)).reset_index(drop=True)
        except Exception:
            return df
    return df
