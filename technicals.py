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
    x=add_indicators(df)
    if x.empty or len(x)<60: return 50, {}, x
    r=x.iloc[-1]; score=0; reasons=[]
    trend = (r.Close>r.EMA21) + (r.EMA21>r.EMA50) + (r.EMA50>r.EMA200 if not pd.isna(r.EMA200) else 0)
    score += trend/3*35; reasons.append(f'trend {trend}/3')
    mom = int(r.MACD>r.MACDsig)+int(r.RSI>50)+int(r.StochK>r.StochD)
    score += mom/3*25; reasons.append(f'momentum {mom}/3')
    if r.Close>r.DonchianHigh: score+=15; reasons.append('20d breakout')
    elif abs(r.Close-r.EMA21)/r.Close<0.03 and r.Close>r.EMA50: score+=10; reasons.append('constructive pullback')
    if bool(r.Squeeze): score+=8; reasons.append('squeeze')
    if spy_df is not None and not spy_df.empty and len(spy_df)>30:
        rs=(df.Close.iloc[-1]/df.Close.iloc[-21]-1) - (spy_df.Close.iloc[-1]/spy_df.Close.iloc[-21]-1)
        score += clamp(50+300*rs,0,15); reasons.append(f'20d RS vs benchmark {rs:.1%}')
    setup=infer_setup(x)
    return clamp(score), {'setup_type':setup, 'technical_reasons':reasons, 'last':r.to_dict()}, x

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
