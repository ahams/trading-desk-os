# from __future__ import annotations

# import os
# from dataclasses import dataclass
# from pathlib import Path


# @dataclass(frozen=True)
# class Settings:
#     app_name: str = os.getenv("TDO_APP_NAME", "Trading Desk OS API")
#     environment: str = os.getenv("TDO_ENV", "dev")
#     database_path: str = os.getenv("TDO_DB_PATH", "trading_desk_os.db")
#     reports_dir: str = os.getenv("TDO_REPORTS_DIR", "reports")
#     default_free_monthly_credits: int = int(os.getenv("TDO_FREE_MONTHLY_CREDITS", "100"))
#     default_paid_monthly_credits: int = int(os.getenv("TDO_PAID_MONTHLY_CREDITS", "10000"))
#     admin_bootstrap_key: str = os.getenv("TDO_ADMIN_BOOTSTRAP_KEY", "dev-admin-key-change-me")
#     cors_allow_origins: str = os.getenv("TDO_CORS_ALLOW_ORIGINS", "*")

#     @property
#     def db_path(self) -> Path:
#         return Path(self.database_path).expanduser().resolve()

#     @property
#     def report_path(self) -> Path:
#         p = Path(self.reports_dir).expanduser().resolve()
#         p.mkdir(parents=True, exist_ok=True)
#         return p


# settings = Settings()

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv
ENV_FILE = Path("/Users/abdulhameed/ibalgo/ibkralgo/pro_trading_desk/.env")
load_dotenv(ENV_FILE)
# Load .env from project root
# load_dotenv()
print("Loading .env from:", ENV_FILE)
print("Exists:", ENV_FILE.exists())
print("Admin key:", os.getenv("TDO_ADMIN_BOOTSTRAP_KEY"))

@dataclass(frozen=True)
class Settings:

    # =========================
    # APP
    # =========================

    app_name: str = os.getenv(
        "TDO_APP_NAME",
        "Trading Desk OS API"
    )

    environment: str = os.getenv(
        "TDO_ENV",
        "dev"
    )

    # =========================
    # DATABASE
    # =========================

    database_path: str = os.getenv(
    "TDO_DB_PATH",
    "trading_desk_os.db"
)

    database_url: str = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{database_path}"
)

    # =========================
    # REPORTS
    # =========================

    reports_dir: str = os.getenv(
        "TDO_REPORTS_DIR",
        "reports"
    )

    # =========================
    # API BILLING
    # =========================

    default_free_monthly_credits: int = int(
        os.getenv("TDO_FREE_MONTHLY_CREDITS", "100")
    )

    default_paid_monthly_credits: int = int(
        os.getenv("TDO_PAID_MONTHLY_CREDITS", "10000")
    )

    admin_bootstrap_key: str = os.getenv(
        "TDO_ADMIN_BOOTSTRAP_KEY",
        "tdos_admin_0yx2AD_5qYD8kLUcuxL0gHqixz4__wETUnrx9VW2N1e43XW-WEka3vlQLkPnJq8X"
    )

    # =========================
    # API
    # =========================

    tdos_api_key: str = os.getenv(
        "STOCK_API_KEY",
        "tdo_FHMTu_NvdvhLu6r0qx6tW-SohQhpBTUDb5Bc66A1Z2Q"
    )

    tdos_api_url: str = os.getenv(
        "STOCK_API_URL",
        "http://127.0.0.1:8000"
    )

    # =========================
    # ALPACA
    # =========================

    alpaca_api_key: str = os.getenv(
        "ALPACA_API_KEY",
        ""
    )

    alpaca_secret_key: str = os.getenv(
        "ALPACA_SECRET_KEY",
        ""
    )

    # =========================
    # OPENAI
    # =========================

    openai_api_key: str = os.getenv(
        "OPENAI_API_KEY",
        ""
    )

    # =========================
    # STRIPE
    # =========================

    stripe_secret_key: str = os.getenv(
        "STRIPE_SECRET_KEY",
        ""
    )

    stripe_webhook_secret: str = os.getenv(
        "STRIPE_WEBHOOK_SECRET",
        ""
    )

    # =========================
    # EMAIL
    # =========================

    smtp_user: str = os.getenv(
        "SMTP_USER",
        ""
    )

    smtp_password: str = os.getenv(
        "SMTP_PASSWORD",
        ""
    )

    cors_allow_origins: str = os.getenv(
        "TDO_CORS_ALLOW_ORIGINS",
        "*"
    )

    @property
    def db_path(self) -> Path:
        return Path(self.database_path).expanduser().resolve()

    @property
    def report_path(self) -> Path:
        p = Path(self.reports_dir).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
