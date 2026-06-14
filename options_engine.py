import numpy as np, pandas as pd
from utils import clamp

def _prep(calls, puts):
    for df in [calls, puts]:
        if not df.empty:
            for c in ['openInterest','volume','impliedVolatility','strike','lastPrice']:
                if c in df: df[c]=pd.to_numeric(df[c], errors='coerce').fillna(0)
    return calls, puts

def max_pain(calls, puts):
    if calls.empty or puts.empty: return np.nan
    strikes=np.sort(np.unique(np.r_[calls.strike.values, puts.strike.values]))
    losses=[]
    for s in strikes:
        call_loss=((np.maximum(0, s-calls.strike))*calls.openInterest).sum()
        put_loss=((np.maximum(0, puts.strike-s))*puts.openInterest).sum()
        losses.append(call_loss+put_loss)
    return float(strikes[int(np.argmin(losses))]) if len(strikes) else np.nan

def options_score(calls, puts, spot):
    calls,puts=_prep(calls.copy(), puts.copy())
    if calls.empty or puts.empty: return 50, {'options_reasons':['no options chain available']}
    co,po=calls.openInterest.sum(), puts.openInterest.sum(); cv,pv=calls.volume.sum(), puts.volume.sum()
    pcr_oi=float(po/co) if co else np.nan; pcr_vol=float(pv/cv) if cv else np.nan
    atm_calls=calls.iloc[(calls.strike-spot).abs().argsort()[:5]]; atm_puts=puts.iloc[(puts.strike-spot).abs().argsort()[:5]]
    atm_iv=float(pd.concat([atm_calls.impliedVolatility, atm_puts.impliedVolatility]).replace(0,np.nan).mean())
    pain=max_pain(calls, puts)
    call_pressure=cv/(cv+pv) if (cv+pv)>0 else .5
    near=calls[(calls.strike>=spot*.95)&(calls.strike<=spot*1.15)]
    gamma_zone=float(near.assign(g=near.openInterest/(near.strike-spot).abs().replace(0,1)).sort_values('g', ascending=False).strike.head(1).iloc[0]) if not near.empty else np.nan
    score=50
    score += 15 if call_pressure>.62 else (-12 if call_pressure<.38 else 0)
    score += 10 if pcr_oi<0.8 else (-10 if pcr_oi>1.4 else 0)
    score += -10 if atm_iv and atm_iv>1.0 else (8 if atm_iv and atm_iv<0.45 else 0)
    if not np.isnan(pain): score += 5 if abs(spot-pain)/spot<.03 else 0
    reasons=[f'put/call OI {pcr_oi:.2f}' if not np.isnan(pcr_oi) else 'PCR n/a', f'put/call volume {pcr_vol:.2f}' if not np.isnan(pcr_vol) else 'PCR vol n/a', f'ATM IV {atm_iv:.1%}' if atm_iv else 'IV n/a', f'max pain {pain:.2f}' if not np.isnan(pain) else 'max pain n/a']
    read='Call buying pressure' if call_pressure>.62 else ('Put protection / bearish pressure' if call_pressure<.38 else 'Balanced positioning')
    return clamp(score), {'put_call_oi':pcr_oi,'put_call_volume':pcr_vol,'atm_iv':atm_iv,'max_pain':pain,'gamma_zone':gamma_zone,'options_read':read,'options_reasons':reasons}
