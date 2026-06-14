from __future__ import annotations

import os
import requests

BASE = os.getenv("TDO_API_BASE", "http://127.0.0.1:8000")
KEY = os.getenv("TDO_API_KEY")

if not KEY:
    raise SystemExit("Set TDO_API_KEY first")

headers = {"X-API-Key": KEY}
print(requests.get(f"{BASE}/health").json())
print(requests.get(f"{BASE}/api/v1/account", headers=headers).json())
print(requests.post(f"{BASE}/api/v1/analyze", headers=headers, json={"ticker": "NVDA"}).json())
