import numpy as np, pandas as pd
from technicals import add_indicators

def make_signal(x, strategy):
    if strategy=='Breakout': return x.Close>x.DonchianHigh
    if strategy=='Pullback': return (x.Close>x.EMA50)&((x.Close-x.EMA21).abs()/x.Close<0.025)&(x.RSI>45)
    if strategy=='Squeeze': return x.Squeeze.shift(1).fillna(False)&(x.Close>x.BBu)&(x.MACDh>0)
    if strategy=='Failed breakdown': return (x.Close.shift(1)<x.DonchianLow.shift(1))&(x.Close>x.DonchianLow)
    if strategy=='High RVOL momentum': return (x.Volume>x.Volume.rolling(20).mean()*2)&(x.Close>x.Close.shift(1))
    return pd.Series(False, index=x.index)

def backtest(df, strategy='Breakout', hold_days=10):
    x=add_indicators(df).dropna().copy()
    if x.empty: return pd.DataFrame(), {}
    sig=make_signal(x, strategy).shift(1).fillna(False)  # avoid lookahead: enter next bar
    trades=[]
    for dt in x.index[sig]:
        i=x.index.get_loc(dt)
        if i+hold_days>=len(x): continue
        entry=x.Close.iloc[i]; exitp=x.Close.iloc[i+hold_days]
        ret=exitp/entry-1
        trades.append({'entry_date':dt,'exit_date':x.index[i+hold_days],'entry':entry,'exit':exitp,'return':ret})
    tr=pd.DataFrame(trades)
    if tr.empty: return tr, {'trades':0}
    eq=(1+tr['return']).cumprod(); dd=eq/eq.cummax()-1
    wins=tr[tr['return']>0]['return']; losses=tr[tr['return']<=0]['return']
    metrics={'trades':len(tr),'win_rate':float((tr['return']>0).mean()),'avg_return':float(tr['return'].mean()),'median_return':float(tr['return'].median()),'max_drawdown':float(dd.min()),'profit_factor':float(wins.sum()/abs(losses.sum())) if abs(losses.sum())>0 else np.inf,'sharpe_proxy':float(tr['return'].mean()/tr['return'].std()*np.sqrt(252/hold_days)) if tr['return'].std()>0 else np.nan,'avg_holding_period':hold_days}
    return tr, metrics
