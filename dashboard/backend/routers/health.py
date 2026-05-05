from fastapi import APIRouter

from dashboard.backend.core.settings import now_iso


router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "time": now_iso()}
