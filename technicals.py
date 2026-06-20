import numpy as np, pandas as pd
from utils import clamp

def ema(s,n): return s.ewm(span=n, adjust=False).mean()
def rsi(close,n=14):
    d=close.diff(); up=d.clip(lower=0).rolling(n).mean(); dn=(-d.clip(upper=0)).rolling(n).mean()
    return 100 - 100/(1+up/dn.replace(0,np.nan))
def atr(df,n=14):
    tr=pd.concat([(df.High-df.Low),(df.High-df.Close.shift()).abs(),(df.Low-df.Close.shift()).abs()],axis=1).max(axis=1)
    return tr.rolling(n).mean()
def macd(close):
    m=ema(close,12)-ema(close,26); sig=ema(m,9); return m,sig,m-sig

def add_indicators(df):
    if df.empty: return df
    x=df.copy(); c=x.Close
    for n in [8,21,50,200]: x[f'EMA{n}']=ema(c,n)
    x['RSI']=rsi(c); x['ATR']=atr(x); x['MACD'],x['MACDsig'],x['MACDh']=macd(c)
    lo=x.Low.rolling(14).min(); hi=x.High.rolling(14).max(); x['StochK']=100*(c-lo)/(hi-lo).replace(0,np.nan); x['StochD']=x.StochK.rolling(3).mean()
    mid=c.rolling(20).mean(); sd=c.rolling(20).std(); x['BBu']=mid+2*sd; x['BBl']=mid-2*sd
    x['KCu']=mid+1.5*x.ATR; x['KCl']=mid-1.5*x.ATR; x['Squeeze']=(x.BBu<x.KCu)&(x.BBl>x.KCl)
    x['DonchianHigh']=x.High.rolling(20).max().shift(1); x['DonchianLow']=x.Low.rolling(20).min().shift(1)
    tp=(x.High+x.Low+x.Close)/3; x['VWAP20']=(tp*x.Volume).rolling(20).sum()/x.Volume.rolling(20).sum()
    return x

def infer_setup(x):
    if len(x)<60: return 'Insufficient data'
    r=x.iloc[-1]; p=x.iloc[-2]
    if r.Close>r.DonchianHigh and r.Volume>x.Volume.rolling(20).mean().iloc[-1]*1.5: return 'Breakout'
    if r.Squeeze and r.Close>r.EMA21 and r.MACDh>0: return 'Squeeze building'
    if r.Close>r.EMA50 and abs(r.Close-r.EMA21)/r.Close<0.025 and r.RSI>45: return 'Pullback to trend'
    if p.Close<p.DonchianLow and r.Close>p.DonchianLow: return 'Failed breakdown'
    if r.Close<r.EMA21 and r.RSI>70: return 'Resistance rejection risk'
    if r.Close<r.EMA50 and r.EMA21<r.EMA50: return 'Downtrend / short bias'
    return 'Watchlist / no clean pattern'

def technical_score(df, spy_df=None):
    x = add_indicators(df)
    if x.empty or len(x) < 60:
        return 50, {}, x

    r = x.iloc[-1]
    score = 0
    reasons = []

    # -------------------------
    # 1. Trend Quality: 45 pts
    # -------------------------
    trend_score = 0

    if r.Close > r.EMA21:
        trend_score += 12
    if r.EMA21 > r.EMA50:
        trend_score += 12
    if not pd.isna(r.EMA200) and r.EMA50 > r.EMA200:
        trend_score += 10

    # EMA slope confirms trend persistence
    ema21_slope = (x.EMA21.iloc[-1] / x.EMA21.iloc[-10] - 1) if x.EMA21.iloc[-10] else 0
    ema50_slope = (x.EMA50.iloc[-1] / x.EMA50.iloc[-20] - 1) if x.EMA50.iloc[-20] else 0

    if ema21_slope > 0:
        trend_score += 6
    if ema50_slope > 0:
        trend_score += 5

    score += trend_score
    reasons.append(f"trend_quality {trend_score}/45")

    # -------------------------
    # 2. Momentum: 20 pts
    # -------------------------
    momentum_score = 0

    if r.MACD > r.MACDsig:
        momentum_score += 7
    if r.RSI > 50:
        momentum_score += 7
    if r.StochK > r.StochD:
        momentum_score += 6

    score += momentum_score
    reasons.append(f"momentum {momentum_score}/20")

    # -------------------------
    # 3. Entry Quality: 20 pts
    # -------------------------
    entry_score = 0

    near_ema21 = abs(r.Close - r.EMA21) / r.Close < 0.035
    near_ema50 = abs(r.Close - r.EMA50) / r.Close < 0.05

    if r.Close > r.DonchianHigh:
        entry_score += 12
        reasons.append("20d breakout")
    elif near_ema21 and r.Close > r.EMA50:
        entry_score += 10
        reasons.append("pullback near EMA21")
    elif near_ema50 and r.Close > r.EMA200:
        entry_score += 7
        reasons.append("deeper pullback near EMA50")

    if bool(r.Squeeze):
        entry_score += 5
        reasons.append("squeeze")

    if r.RSI > 75:
        entry_score -= 5
        reasons.append("overbought entry risk")

    score += max(0, entry_score)
    reasons.append(f"entry_quality {entry_score}/20")

    # -------------------------
    # 4. Relative Strength: 15 pts
    # -------------------------
    rs_score = 7.5

    if spy_df is not None and not spy_df.empty and len(spy_df) > 30:
        rs = (
            df.Close.iloc[-1] / df.Close.iloc[-21] - 1
        ) - (
            spy_df.Close.iloc[-1] / spy_df.Close.iloc[-21] - 1
        )

        # Convert RS into 0-15 score
        rs_score = clamp(7.5 + 250 * rs, 0, 15)
        reasons.append(f"20d RS vs benchmark {rs:.1%}, rs_score {rs_score:.1f}/15")

    score += rs_score

    setup = infer_setup(x)

    # Override wording for strong stocks without perfect entry
    if score >= 65 and setup == "Watchlist / no clean pattern":
        setup = "Strong trend / no ideal entry"
    elif score >= 65 and "Pullback" in setup:
        setup = "Constructive pullback in uptrend"
    elif score >= 75:
        setup = "Strong technical uptrend"

    meta = {
        "setup_type": setup,
        "technical_reasons": reasons,
        "last": r.to_dict(),
        "trend_score": round(trend_score, 1),
        "momentum_score": round(momentum_score, 1),
        "entry_score": round(entry_score, 1),
        "relative_strength_score": round(rs_score, 1),
    }

    return clamp(score), meta, x

def trade_levels(x, account_size=100000, risk_pct=0.005):
    r=x.iloc[-1]; atrv=float(r.ATR) if not pd.isna(r.ATR) else float(r.Close)*0.03
    long_bias = r.Close>=r.EMA21
    entry=float(r.Close)
    stop = entry-1.5*atrv if long_bias else entry+1.5*atrv
    target1 = entry+2*atrv if long_bias else entry-2*atrv
    target2 = entry+3.5*atrv if long_bias else entry-3.5*atrv
    risk_per_share=abs(entry-stop); size=(account_size*risk_pct)/risk_per_share if risk_per_share else 0
    rr=abs(target1-entry)/risk_per_share if risk_per_share else np.nan
    return dict(entry=round(entry,2), stop=round(stop,2), target1=round(target1,2), target2=round(target2,2), rr=round(rr,2), position_size=int(size))
