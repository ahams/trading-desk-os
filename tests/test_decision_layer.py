from decision_layer import DecisionLayerConfig, build_reasoning


def sample_result():
    return {
        "ticker": "TEST",
        "decision": "Watchlist Only",
        "regime": "RISK_ON",
        "scores": {
            "fundamental": 82,
            "technical": 74,
            "trend_quality": 80,
            "entry_quality": 42,
            "leadership": 78,
            "liquidity": 71,
            "options": 38,
            "game": 55,
            "catalyst": 60,
            "expectation": 28,
            "merton": 76,
            "neocloud": 50,
            "optionality": 68,
        },
        "summary": {
            "expectation": "The market prices an unusually demanding growth hurdle.",
            "entry_quality": "The stock is extended and lacks a clean entry.",
        },
        "metas": {
            "expectation": {
                "expectation_read": "The market prices an unusually demanding growth hurdle."
            },
            "entry_quality": {
                "summary": "The stock is extended and lacks a clean entry."
            },
        },
    }


def test_shadow_mode_preserves_legacy_decision():
    result = sample_result()
    reasoning = build_reasoning(
        result,
        DecisionLayerConfig(enabled=True, shadow_mode=True),
    )
    assert reasoning["status"] == "ok"
    assert reasoning["effective_decision"] == result["decision"]
    assert reasoning["legacy_decision"] == result["decision"]
    assert reasoning["decisive_factor"] is not None


def test_disabled_layer_is_safe():
    result = sample_result()
    reasoning = build_reasoning(
        result,
        DecisionLayerConfig(enabled=False, shadow_mode=True),
    )
    assert reasoning["enabled"] is False
    assert reasoning["legacy_decision"] == result["decision"]
