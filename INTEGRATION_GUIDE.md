# Trading Desk OS: Trend / Entry / Leadership Patch

This patch fixes the problem where a stock can be a clear market leader but the old technical engine marks it weak because there is no fresh breakout/pullback pattern.

## New files

Copy these into your repo:

```text
engines/trend_quality_engine.py
engines/entry_quality_engine.py
engines/leadership_engine.py
```

If your repo does not use an `engines/` folder and your modules are in the root, either:

1. create `engines/__init__.py`, or
2. copy the files to root and update imports accordingly.

---

## Conceptual change

Old:

```text
Technical Score = one combined score
```

New:

```text
Trend Quality = Is the stock in a strong trend?
Entry Quality = Is today a good entry?
Leadership = Is the stock a leader vs benchmark/theme?
```

Recommended combined technical score:

```python
technical_v2 = (
    0.40 * trend_quality_score
    + 0.30 * entry_quality_score
    + 0.30 * leadership_score
)
```

This lets the system say:

```text
Strong trend, poor entry: wait for pullback or breakout.
```

instead of incorrectly saying:

```text
Technical weak.
```

---

## Patch `services/analysis_service.py`

Add imports near the top:

```python
try:
    from engines.trend_quality_engine import analyze_trend_quality
    from engines.entry_quality_engine import analyze_entry_quality
    from engines.leadership_engine import analyze_leadership
except Exception:
    from trend_quality_engine import analyze_trend_quality
    from entry_quality_engine import analyze_entry_quality
    from leadership_engine import analyze_leadership
```

After you already have OHLCV `df`, benchmark data, sector data, and theme, build this payload:

```python
engine_payload = {
    "ohlcv": df,
    "benchmark": benchmark_df,      # optional, can be None
    "sector": sector_df,            # optional, can be None
    "theme": theme_name,            # optional string, e.g. "AI Infrastructure"
    "theme_peer_returns": theme_peer_returns,  # optional dict
}

trend_meta = analyze_trend_quality(ticker, engine_payload)
entry_meta = analyze_entry_quality(ticker, engine_payload)
leadership_meta = analyze_leadership(ticker, engine_payload)

trend_score = trend_meta.get("score", 50)
entry_score = entry_meta.get("score", 50)
leadership_score = leadership_meta.get("score", 50)

technical_v2_score = round(
    0.40 * trend_score
    + 0.30 * entry_score
    + 0.30 * leadership_score,
    1,
)
```

Then add these to your response objects:

```python
scores["trend_quality"] = trend_score
scores["entry_quality"] = entry_score
scores["leadership"] = leadership_score
scores["technical_v2"] = technical_v2_score

summary["trend_quality"] = trend_meta.get("summary")
summary["entry_quality"] = entry_meta.get("summary")
summary["leadership"] = leadership_meta.get("summary")

metas["trend_quality"] = trend_meta
metas["entry_quality"] = entry_meta
metas["leadership"] = leadership_meta
```

Then either replace old technical score:

```python
scores["technical"] = technical_v2_score
```

or keep both:

```python
scores["technical_legacy"] = scores.get("technical")
scores["technical"] = technical_v2_score
```

Recommended during beta: keep both so you can compare.

---

## Improve decision wording

Add this logic near thesis generation:

```python
if trend_score >= 75 and leadership_score >= 65 and entry_score < 50:
    setup_type = "Strong trend / poor entry — wait for pullback or breakout"
elif trend_score >= 75 and entry_score >= 60:
    setup_type = "Trend continuation entry"
elif leadership_score >= 75 and entry_score < 50:
    setup_type = "Leadership name, no clean entry"
```

This fixes MRVL-type outputs.

---

## Patch `services/response_formatter.py`

Inside compact formatter, add these fields:

```python
trend = metas.get("trend_quality") or {}
entry = metas.get("entry_quality") or {}
leadership = metas.get("leadership") or {}
```

In compact `scores`, include:

```python
"trend_quality": _round(scores.get("trend_quality"), 1),
"entry_quality": _round(scores.get("entry_quality"), 1),
"leadership": _round(scores.get("leadership"), 1),
"technical_v2": _round(scores.get("technical_v2"), 1),
```

In compact `reads`, include:

```python
"trend_quality": trend.get("summary"),
"entry_quality": entry.get("summary"),
"leadership": leadership.get("summary"),
```

Add a new snapshot:

```python
"technical_snapshot": {
    "trend_quality_score": _round((metas.get("trend_quality") or {}).get("score"), 1),
    "trend_signal": (metas.get("trend_quality") or {}).get("signal"),
    "entry_quality_score": _round((metas.get("entry_quality") or {}).get("score"), 1),
    "entry_signal": (metas.get("entry_quality") or {}).get("signal"),
    "leadership_score": _round((metas.get("leadership") or {}).get("score"), 1),
    "leadership_signal": (metas.get("leadership") or {}).get("signal"),
}
```

---

## Patch `frontend_streamlit.py`

Inside `render_analysis_card(data)`, add:

```python
tech_snap = data.get("technical_snapshot") or {}
if tech_snap:
    st.markdown("### Technical Decomposition")
    c1, c2, c3 = st.columns(3)
    c1.metric("Trend Quality", tech_snap.get("trend_quality_score", "n/a"))
    c1.caption(tech_snap.get("trend_signal", ""))
    c2.metric("Entry Quality", tech_snap.get("entry_quality_score", "n/a"))
    c2.caption(tech_snap.get("entry_signal", ""))
    c3.metric("Leadership", tech_snap.get("leadership_score", "n/a"))
    c3.caption(tech_snap.get("leadership_signal", ""))
```

Also make sure score display does not break if values are `None`.

---

## Expected MRVL-style behavior

Old output:

```text
Technical weak / Watchlist Only
```

New output should be closer to:

```text
Trend Quality: Strong / Constructive
Leadership: Leadership Candidate
Entry Quality: Watch/Poor Entry
Setup: Strong trend, poor entry — wait for pullback or breakout
```

This is much more professionally correct.
