from datetime import datetime
from utils import clamp

def classify(score, tech_setup=''):
    if score>=80: return 'Strong Long'
    if score>=65: return 'Tactical Long'
    if score>=45: return 'Watchlist Only'
    if score>=30: return 'Tactical Short'
    return 'Strong Short'

def combine_scores(scores, weights):
    total=sum(float(weights[k]) for k in weights) or 1
    fs=sum(scores.get(k,50)*float(weights[k])/total for k in weights)
    return clamp(fs)

def build_thesis(ticker, decision, setup, f, t, l, o, g, c, e=None, sk=None, cml=None):
    bull=f"Bull case: {setup}; {', '.join(t.get('technical_reasons',[])[:2])}; {', '.join(l.get('liquidity_reasons',[])[:2])}."
    bear=f"Bear case: {', '.join(o.get('options_reasons',[])[:2])}; risks: {', '.join(c.get('negative_flags',[]) or ['failed follow-through, market regime, catalyst fade'])}."
    gt=f"Game theory: {g.get('participant_read','n/a')}"
    exp = f" Expectations: {(e or {}).get('expectation_read','n/a')}"
    skew = f" Skew: {(sk or {}).get('suggested_options_expression','n/a')}"
    macro = f" Macro pricing: {(cml or {}).get('pricing_read','n/a')}"
    return f"{ticker}: {decision}. {bull} {gt}.{exp}{skew}{macro} {bear}"

def result_row(ticker, final_score, decision, setup, levels, thesis):
    return {'ts':datetime.utcnow().isoformat(), 'ticker':ticker, 'final_score':round(final_score,1),'decision':decision,'setup_type':setup, **levels, 'thesis':thesis}
