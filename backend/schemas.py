from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    ticker: str = Field(..., examples=["NVDA"])
    period: str = "1y"
    interval: str = "1d"
    account_size: float = 100_000
    risk_pct: float = 0.005
    compact: bool = False
    persist_signal: bool = True
    


class ScannerRequest(BaseModel):
    tickers: List[str] = Field(default_factory=lambda: ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "AMD", "TSLA"])
    period: str = "1y"
    interval: str = "1d"
    max_names: int = Field(50, ge=1, le=500)
    min_price: float = 1.0
    min_avg_dollar_volume: float = 1_000_000
    include_options: bool = True


class DailyReportRequest(BaseModel):
    tickers: List[str] = Field(default_factory=lambda: ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "AMD", "TSLA", "PLTR", "COIN"])
    title: str = "Trading Desk OS Daily Report"
    include_signal_records: bool = True
    max_names: int = Field(50, ge=1, le=500)


class PortfolioRequest(BaseModel):
    tickers: List[str]
    max_names: int = 25
    risk_aversion: float = 2.5


class CreateUserRequest(BaseModel):
    email: str
    name: str = ""
    plan: str = "free"
    monthly_credit_limit: Optional[int] = None


class CreateApiKeyRequest(BaseModel):
    email: str
    label: str = "default"


class BillingEventRequest(BaseModel):
    email: Optional[str] = None
    event_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
