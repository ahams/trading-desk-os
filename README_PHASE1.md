# TDOS Phase-1 Decision Layer Patch

## Files changed

- `analysis_service.py`
- `response_formatter.py`

## Files added

- `decision_layer/__init__.py`
- `decision_layer/config.py`
- `decision_layer/models.py`
- `decision_layer/adapters.py`
- `decision_layer/committee.py`
- `tests/test_decision_layer.py`

## Safety design

The layer runs in shadow mode by default. It adds `reasoning` to the raw
analysis result and compact response, but does not overwrite:

- `decision`
- `final_score`
- `setup_type`
- trade levels
- expected-return output
- persistence logic
- existing API fields

## Environment switches

```bash
TDOS_DECISION_LAYER_ENABLED=true
TDOS_DECISION_LAYER_SHADOW_MODE=true
```

Keep shadow mode enabled for Phase 1.

## Install

Copy the two patched Python files and the `decision_layer/` directory into
the same backend source root where the original modules live.

## Test

```bash
pytest -q tests/test_decision_layer.py
```

## API payload

Both full and compact analysis now contain:

```json
{
  "reasoning": {
    "legacy_decision": "Watchlist Only",
    "committee_view": "Constructive Watchlist",
    "effective_decision": "Watchlist Only",
    "decisive_factor": {},
    "supporting_evidence": [],
    "contradictory_evidence": [],
    "invalidators": [],
    "committee_summary": ""
  }
}
```
