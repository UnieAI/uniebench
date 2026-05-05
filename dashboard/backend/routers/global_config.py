from fastapi import APIRouter, File, HTTPException, UploadFile

from dashboard.backend.core.settings import CONFIG_PATH, WRITE_LOCK, now_iso
from dashboard.backend.schemas import GlobalConfigPayload
from dashboard.backend.services.scripts_service import (
    discover_model_names,
    get_global_config,
    save_global_config,
    save_service_account_json,
)


router = APIRouter(prefix="/api/global-config", tags=["global-config"])


@router.get("")
def read_global_config() -> dict:
    data = get_global_config(CONFIG_PATH)
    data["time"] = now_iso()
    return data


@router.put("")
def update_global_config(payload: GlobalConfigPayload) -> dict:
    data = save_global_config(CONFIG_PATH, WRITE_LOCK, payload.model_dump())
    data["saved"] = True
    data["time"] = now_iso()
    return data


@router.get("/discover-model-names")
def read_discovered_model_names(model_path: str = "") -> dict:
    data = discover_model_names(model_path)
    data["time"] = now_iso()
    return data


@router.post("/service-account")
async def upload_service_account_json(file: UploadFile = File(...)) -> dict:
    try:
        content = await file.read()
        data = save_service_account_json(
            config_path=CONFIG_PATH,
            lock=WRITE_LOCK,
            file_name=file.filename or "",
            content=content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save service_account.json: {exc}") from exc

    data["uploaded"] = True
    data["time"] = now_iso()
    return data
