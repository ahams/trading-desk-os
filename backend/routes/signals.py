from fastapi import APIRouter, Depends, Query
from database.store import connect, init_db
from backend.auth import require_api_key

router = APIRouter(prefix="/api/v1/signals", tags=["signals"])


@router.get("/history")
def signal_history(
    ticker: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    user=Depends(require_api_key),
):
    init_db()

    with connect() as conn:
        if ticker:
            rows = conn.execute(
                """
                SELECT *
                FROM signals
                WHERE UPPER(ticker)=UPPER(?)
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (ticker, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM signals
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    return {
        "count": len(rows),
        "results": [dict(r) for r in rows],
    }