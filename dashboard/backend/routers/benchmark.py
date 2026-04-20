from fastapi import APIRouter

from dashboard.backend.core.settings import CONFIG_PATH, WRITE_LOCK, now_iso
from dashboard.backend.schemas import BenchmarkConfigPayload
from dashboard.backend.services.benchmark_service import get_benchmark_config, save_benchmark_config


router = APIRouter(prefix="/api/benchmark-config", tags=["benchmark-config"])


@router.get("")
def read_benchmark_config() -> dict:
    data = get_benchmark_config(CONFIG_PATH)
    data["time"] = now_iso()
    return data


@router.put("")
def update_benchmark_config(payload: BenchmarkConfigPayload) -> dict:
    data = save_benchmark_config(CONFIG_PATH, WRITE_LOCK, [item.model_dump() for item in payload.profiles])
    data["saved"] = True
    data["time"] = now_iso()
    return data
