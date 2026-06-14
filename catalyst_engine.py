from datetime import datetime, timezone
from utils import clamp

THEME_KEYWORDS=['ai','artificial intelligence','quantum','defense','nuclear','energy','semiconductor','ev','battery','fda','cancer','biotech','contract','partnership','earnings','upgrade','buyback','merger','acquisition','offering','dilution']
NEGATIVE=['offering','dilution','sec investigation','downgrade','miss','lawsuit','bankruptcy']

def catalyst_score(news):
    if not news: return 50, {'catalyst_read':'No fresh free-news feed available.', 'themes':[], 'news_summary':[]}
    texts=[]
    for n in news:
        title=n.get('title') or n.get('content',{}).get('title') or ''
        pub=n.get('providerPublishTime') or n.get('pubDate') or ''
        texts.append(title.lower())
    blob=' '.join(texts)
    themes=sorted({k for k in THEME_KEYWORDS if k in blob})
    neg=[k for k in NEGATIVE if k in blob]
    score=50+min(25,len(themes)*5)-min(30,len(neg)*10)
    read='Real catalyst/theme detected' if themes else 'No strong catalyst keyword detected'
    if neg: read += '; dilution/legal/negative-risk keywords present'
    summary=[(n.get('title') or n.get('content',{}).get('title') or '') for n in news[:5]]
    return clamp(score), {'catalyst_read':read,'themes':themes,'negative_flags':neg,'news_summary':summary}
