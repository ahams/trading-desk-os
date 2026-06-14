import logging, os, sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any
import numpy as np
import pandas as pd

DB_PATH = os.getenv('DECISION_APP_DB', 'decision_app.db')
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger('decision_app')

def clamp(x, lo=0, hi=100):
    try:
        if pd.isna(x): return 50
        return max(lo, min(hi, float(x)))
    except Exception:
        return 50

def zscore_to_score(x, center=0, scale=1, invert=False):
    if x is None or pd.isna(x): return 50
    z = (x-center)/(scale if scale else 1)
    score = 50 + 15*z
    if invert: score = 100-score
    return clamp(score)

def pct(a,b):
    try:
        return (a/b - 1)*100 if b not in (0, None) and not pd.isna(b) else np.nan
    except Exception: return np.nan

def ensure_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS scanner_results(
        ts TEXT, ticker TEXT, final_score REAL, decision TEXT, setup_type TEXT,
        entry REAL, stop REAL, target1 REAL, target2 REAL, rr REAL, thesis TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS trade_journal(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, ticker TEXT, decision TEXT,
        entry REAL, stop REAL, target1 REAL, target2 REAL, size REAL, thesis TEXT,
        outcome TEXT, lessons TEXT)''')
    con.commit(); con.close()

def save_scanner_rows(rows):
    ensure_db(); con = sqlite3.connect(DB_PATH)
    df = pd.DataFrame(rows)
    if not df.empty:
        cols = ['ts','ticker','final_score','decision','setup_type','entry','stop','target1','target2','rr','thesis']
        for c in cols:
            if c not in df: df[c] = None
        df[cols].to_sql('scanner_results', con, if_exists='append', index=False)
    con.close()

def save_trade_journal(row: Dict[str, Any]):
    ensure_db(); con = sqlite3.connect(DB_PATH)
    row = dict(row); row.setdefault('ts', datetime.utcnow().isoformat())
    pd.DataFrame([row]).to_sql('trade_journal', con, if_exists='append', index=False)
    con.close()

def read_table(name):
    ensure_db(); con = sqlite3.connect(DB_PATH)
    try: return pd.read_sql(f'SELECT * FROM {name} ORDER BY ts DESC', con)
    finally: con.close()
