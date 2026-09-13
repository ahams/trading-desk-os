from fastapi import APIRouter,Depends
from backend.internal_auth import require_internal_service_key
router=APIRouter()
# Example only; adapt to your existing AnalyzeRequest and handler.
# @router.post("/api/v1/analyze/compact")
# def analyze_compact(payload: AnalyzeRequest, _:None=Depends(require_internal_service_key)):
#     return existing_handler(payload)
