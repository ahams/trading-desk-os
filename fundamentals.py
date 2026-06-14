import pandas as pd
from utils import clamp, zscore_to_score

def fundamental_score(info: dict):
    if not info: return 50, {'fundamental_reasons':['no fundamentals available']}
    rev_growth=info.get('revenueGrowth'); eps_growth=info.get('earningsGrowth')
    gm=info.get('grossMargins'); om=info.get('operatingMargins'); roe=info.get('returnOnEquity')
    de=info.get('debtToEquity'); fcf=info.get('freeCashflow'); pe=info.get('trailingPE') or info.get('forwardPE')
    ps=info.get('priceToSalesTrailing12Months'); beta=info.get('beta')
    growth=clamp(50+(rev_growth or 0)*120+(eps_growth or 0)*80)
    prof=clamp(50+(gm or 0)*35+(om or 0)*60+(roe or 0)*40)
    bal=clamp(75-(de or 50)/4 + (20 if fcf and fcf>0 else -10))
    val=50
    if pe: val += 20 if pe<25 else (-15 if pe>80 else 0)
    if ps: val += 15 if ps<5 else (-15 if ps>20 else 0)
    qual=clamp((prof+bal)/2)
    catalyst=55
    score=clamp(.25*growth+.25*prof+.20*bal+.15*val+.15*qual)
    reasons=[f'growth {growth:.0f}',f'profitability {prof:.0f}',f'balance sheet {bal:.0f}',f'valuation {val:.0f}']
    return score, {'growth':growth,'profitability':prof,'balance_sheet':bal,'valuation':val,'quality':qual,'catalyst_strength':catalyst,'fundamental_reasons':reasons}

def fundamental_table(info):
    fields=['marketCap','sector','industry','revenueGrowth','earningsGrowth','grossMargins','operatingMargins','freeCashflow','debtToEquity','returnOnEquity','trailingPE','forwardPE','priceToSalesTrailing12Months','enterpriseToEbitda','heldPercentInstitutions','heldPercentInsiders','shortPercentOfFloat','beta']
    return pd.DataFrame([{'metric':k,'value':info.get(k)} for k in fields])
