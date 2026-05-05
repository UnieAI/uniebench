from fastapi import APIRouter

from dashboard.backend.core.settings import now_iso
from dashboard.backend.services.gpu_service import get_gpu_status


router = APIRouter(prefix="/api", tags=["gpu"])


@router.get("/gpu")
def gpu_status() -> dict:
    return get_gpu_status(now_iso=now_iso())
