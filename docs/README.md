# Professional Stock Decision-Support Engine

A modular Streamlit app for ranking stocks using fundamentals, technicals, liquidity, options positioning, catalyst/news keywords, and game-theory/participant-flow inference.

## Install
```bash
cd pro_stock_decision_app
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Files
- `app.py` Streamlit UI
- `data_loader.py` yfinance/universe/news/options loaders
- `fundamentals.py` fundamental score
- `technicals.py` indicators, setups, trade levels
- `liquidity.py` volume/liquidity score
- `options_engine.py` put/call, max pain, IV, gamma-zone approximation
- `game_theory.py` participant behavior inference
- `catalyst_engine.py` news/theme keyword engine
- `scoring.py` final weighted decision engine
- `backtester.py` signal backtester with next-bar entry to reduce lookahead
- `utils.py` logging, scoring helpers, SQLite persistence

## Notes
Free data sources can be incomplete. The architecture is designed so you can replace `data_loader.py` with Alpaca, Polygon, IBKR, FMP, Tradier, or Benzinga loaders without changing the decision engine.
