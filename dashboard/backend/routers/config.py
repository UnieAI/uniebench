from fastapi import APIRouter, HTTPException

from dashboard.backend.core.settings import CONFIG_PATH, WRITE_LOCK, now_iso
from dashboard.backend.schemas import ConfigPayload
from dashboard.backend.services.config_service import read_config, save_config, validate_config_yaml


router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
def get_config() -> dict:
    if not CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail=f"Config file not found: {CONFIG_PATH}")

    return {
        "path": str(CONFIG_PATH),
        "content": read_config(CONFIG_PATH),
        "time": now_iso(),
    }


@router.put("")
def update_config(payload: ConfigPayload) -> dict:
    if not CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail=f"Config file not found: {CONFIG_PATH}")

    try:
        parsed = validate_config_yaml(payload.content)
    except Exception as exc:  # yaml parser exception details passed through
        raise HTTPException(status_code=400, detail=f"YAML parse error: {exc}") from exc

    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="YAML root must be a mapping/object")

    save_config(CONFIG_PATH, payload.content, WRITE_LOCK)

    return {
        "saved": True,
        "path": str(CONFIG_PATH),
        "time": now_iso(),
    }
