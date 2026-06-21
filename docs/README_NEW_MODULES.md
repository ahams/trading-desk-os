# Trading Desk OS: Sprint Modules

Added modules:

1. `market_regime.py` — classifies broad tape into RISK_ON/RISK_OFF/CHOP/VOL_EXPANSION/VOL_COMPRESSION.
2. `theme_engine.py` — scores cross-asset theme support and leadership.
3. `expected_return_engine.py` — converts model scores into bull/base/bear EV, levels, and position sizing.
4. `signal_outcome_db.py` — records every signal, updates outcomes, and produces factor performance reports.

Minimal integration sketch:

```python
from market_regime import analyze_market_regime
from theme_engine import analyze_theme
from expected_return_engine import estimate_expected_return
from signal_outcome_db import record_from_app_outputs, update_signal_outcomes, get_outcome_stats

market_data = {"SPY": spy_df, "QQQ": qqq_df, "IWM": iwm_df, "VIX": vix_df, "HYG": hyg_df, "LQD": lqd_df}
regime = analyze_market_regime(market_data)

theme = analyze_theme(ticker, df, market_data=market_data, news_items=news, sector=info.get("sector"), regime_result=regime)

scores = {
    "final": final_score,
    "technical": technical_score,
    "liquidity": liquidity_score,
    "options": options_score,
    "game": game_score,
    "catalyst": catalyst_score,
    "theme": theme["total"],
}

er = estimate_expected_return(ticker, df, scores=scores, metas={}, regime_result=regime)

record_from_app_outputs(ticker, final_row={}, scores=scores, metas={}, expected_return_result=er, regime_result=regime, theme_result=theme)
```
