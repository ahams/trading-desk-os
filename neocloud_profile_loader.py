"""
neocloud_profile_loader.py

Optional user-maintained NeoCloud profile loader.

Why this exists
---------------
Most NeoCloud-specific inputs (secured MW, GPU fleet, target ARR, backlog,
hyperscaler contract duration, funding gap) are not reliably available from
free market-data APIs. This loader lets the Trading Desk OS API consume a
simple JSON file that you can update from filings, investor presentations, or
paid datasets.

Default path:
    config/neocloud_profiles.json

Override with env var:
    NEOCLOUD_PROFILE_PATH=/path/to/neocloud_profiles.json
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

NEOCLOUD_TICKERS = {
    "NBIS", "CRWV", "IREN", "CORZ", "CIFR", "WULF", "HUT", "BTDR", "APLD"
}


def is_neocloud_ticker(ticker: str, info: Optional[Dict[str, Any]] = None) -> bool:
    t = (ticker or "").upper().replace(".", "-")
    if t in NEOCLOUD_TICKERS:
        return True
    text = " ".join(str((info or {}).get(k, "")) for k in ["sector", "industry", "longBusinessSummary", "shortName"]).lower()
    keywords = ["data center", "datacenter", "gpu", "ai cloud", "cloud infrastructure", "bitcoin mining", "high performance computing", "hpc"]
    return any(k in text for k in keywords)


def _profile_path() -> Path:
    return Path(os.getenv("NEOCLOUD_PROFILE_PATH", "config/neocloud_profiles.json")).expanduser().resolve()


def load_neocloud_profile(ticker: str) -> Dict[str, Any]:
    path = _profile_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data.get((ticker or "").upper().replace(".", "-"), {}) or {}
    except Exception:
        return {}
