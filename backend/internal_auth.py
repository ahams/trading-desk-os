from pathlib import Path
import os
import secrets

from dotenv import load_dotenv
from fastapi import Header, HTTPException, status


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


FASTAPI_INTERNAL_KEY = os.getenv(
    "FASTAPI_INTERNAL_KEY",
    ""
)


def require_internal_service_key(
    x_internal_service_key: str | None = Header(default=None),
):
    """
    Authenticate calls coming from the Django control plane.

    This is NOT a user API key.

    User authentication is handled by Django/JWT.
    Django authenticates itself to FastAPI with this internal key.
    """

    if not FASTAPI_INTERNAL_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FASTAPI_INTERNAL_KEY is not configured."
        )

    if not x_internal_service_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing internal service key."
        )

    if not secrets.compare_digest(
        x_internal_service_key,
        FASTAPI_INTERNAL_KEY
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal service key."
        )

    return True