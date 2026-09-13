import os,secrets
from fastapi import Header,HTTPException,status
_INTERNAL_KEY=os.getenv("FASTAPI_INTERNAL_KEY","")
def require_internal_service_key(x_internal_service_key:str|None=Header(default=None))->None:
    if not _INTERNAL_KEY:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,detail="FASTAPI_INTERNAL_KEY is not configured")
    if not x_internal_service_key or not secrets.compare_digest(x_internal_service_key,_INTERNAL_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="Invalid internal service credential")
