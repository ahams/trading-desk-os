from __future__ import annotations
import io, os, requests
from typing import List, Optional
import pandas as pd
import yfinance as yf
import streamlit as st
from utils import logger

DEFAULT_UNIVERSES = {
    'Mega-cap Tech': ['AAPL','MSFT','NVDA','AMZN','META','GOOGL','AVGO','TSLA','AMD','NFLX'],
    'Sector ETFs': ['SPY','QQQ','IWM','DIA','XLK','XLF','XLE','XLV','XLY','XLI','XLC','XLP','XLU','XLB','SMH'],
    'Liquid Momentum': ['PLTR','COIN','MSTR','SOFI','HOOD','ARM','TSM','CRWD','NET','RBLX','U','SHOP'],
}

@st.cache_data(ttl=3600, show_spinner=False)
def load_universe(name: str) -> list[str]:
    if name in DEFAULT_UNIVERSES: return DEFAULT_UNIVERSES[name]
    if name == 'S&P 500':
        try:
            return pd.read_html('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies')[0]['Symbol'].str.replace('.','-', regex=False).tolist()
        except Exception as e:
            logger.warning('SP500 load failed: %s', e); return DEFAULT_UNIVERSES['Mega-cap Tech']
    if name == 'Nasdaq 100':
        try:
            tables = pd.read_html('https://en.wikipedia.org/wiki/Nasdaq-100')
            for t in tables:
                if 'Ticker' in t.columns: return t['Ticker'].astype(str).str.replace('.','-', regex=False).tolist()
        except Exception as e: logger.warning('NDX load failed: %s', e)
    return DEFAULT_UNIVERSES['Mega-cap Tech']

def parse_tickers(manual: str='', csv_file=None, universe: Optional[str]=None) -> list[str]:
    tickers=[]
    if universe and universe != 'None': tickers += load_universe(universe)
    if manual:
        tickers += [x.strip().upper().replace('.','-') for x in manual.replace('\n',',').split(',') if x.strip()]
    if csv_file is not None:
        df = pd.read_csv(csv_file)
        col = 'ticker' if 'ticker' in df.columns else df.columns[0]
        tickers += df[col].dropna().astype(str).str.upper().str.replace('.','-', regex=False).tolist()
    return sorted(set(tickers))

@st.cache_data(ttl=900, show_spinner=False)
def get_ohlcv(ticker: str, period='1y', interval='1d') -> pd.DataFrame:
    try:
        df = yf.download(ticker, period=period, interval=interval, auto_adjust=True, progress=False, threads=False)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df.rename(columns=str.title).dropna()
        df.index = pd.to_datetime(df.index)
        return df
    except Exception as e:
        logger.warning('OHLCV failed %s: %s', ticker, e); return pd.DataFrame()

@st.cache_data(ttl=3600, show_spinner=False)
def get_info(ticker: str) -> dict:
    try: return yf.Ticker(ticker).get_info() or {}
    except Exception as e:
        logger.warning('info failed %s: %s', ticker, e); return {}

@st.cache_data(ttl=1800, show_spinner=False)
def get_options_chain(ticker: str):
    try:
        tk = yf.Ticker(ticker); expiries = list(tk.options)
        if not expiries: return None, pd.DataFrame(), pd.DataFrame()
        exp = expiries[0]; ch = tk.option_chain(exp)
        return exp, ch.calls.copy(), ch.puts.copy()
    except Exception as e:
        logger.warning('options failed %s: %s', ticker, e); return None, pd.DataFrame(), pd.DataFrame()

@st.cache_data(ttl=1800, show_spinner=False)
def get_news(ticker: str, limit=8) -> list[dict]:
    # yfinance news is unstable but useful as a free fallback.
    try:
        return (yf.Ticker(ticker).news or [])[:limit]
    except Exception as e:
        logger.warning('news failed %s: %s', ticker, e); return []
