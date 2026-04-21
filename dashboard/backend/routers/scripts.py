from fastapi import APIRouter, HTTPException

from dashboard.backend.core.settings import CONFIG_PATH, SCRIPTS_DIR_CANDIDATES, WRITE_LOCK, now_iso
from dashboard.backend.schemas import (
    ScriptCreatePayload,
    ScriptEnabledPayload,
    ScriptHostTestBuildPayload,
    ScriptHostTestResultPayload,
    ScriptMovePayload,
    ScriptPayload,
    ScriptTestStartPayload,
)
from dashboard.backend.services.scripts_service import (
    build_host_test_script,
    create_script_path,
    delete_script_path,
    get_script_last_test_result,
    get_script_metadata,
    get_script_enabled,
    get_script_test_status,
    list_scripts,
    move_script_enabled_state,
    move_script_metadata,
    move_script_path,
    move_script_test_result,
    pick_scripts_dir,
    read_script,
    remove_script_enabled_state,
    remove_script_metadata,
    remove_script_test_result,
    resolve_script_path,
    set_script_enabled,
    set_script_last_test_result,
    set_script_metadata,
    sync_default_config_servers,
    sync_enabled_map,
    start_script_test,
    stop_script_test,
    write_script,
)


router = APIRouter(prefix="/api/scripts", tags=["scripts"])


@router.get("")
def get_scripts() -> dict:
    script_dir = pick_scripts_dir(SCRIPTS_DIR_CANDIDATES, create=True)
    rows = list_scripts(script_dir)
    path_list = [row["path"] for row in rows]
    enabled_map = sync_enabled_map(path_list, CONFIG_PATH, WRITE_LOCK)
    scripts = []
    group_map: dict[str, list] = {}
    for row in rows:
        path = row["path"]
        group = row["group"]
        item = {
            "name": row["name"],
            "path": path,
            "group": group,
            "enabled": bool(enabled_map.get(path, False)),
            "metadata": get_script_metadata(path, CONFIG_PATH),
            "last_test": get_script_last_test_result(path, CONFIG_PATH),
        }
        scripts.append(item)
        group_map.setdefault(group, []).append(item)

    groups = [{"name": name, "scripts": group_map[name]} for name in sorted(group_map.keys())]
    return {
        "dir": str(script_dir),
        "groups": groups,
        "scripts": scripts,
        "time": now_iso(),
    }


@router.get("/test/status")
def script_test_status() -> dict:
    status = get_script_test_status()
    if not status.get("has_test"):
        return {
            "has_test": False,
            "active": False,
            "time": now_iso(),
        }
    status["time"] = now_iso()
    return status


@router.post("/test/stop")
def script_test_stop() -> dict:
    status = stop_script_test()
    if not status.get("has_test"):
        return {
            "stopped": False,
            "active": False,
            "detail": "No active script test",
            "time": now_iso(),
        }
    status["stopped"] = True
    status["time"] = now_iso()
    return status


@router.post("/{script_path:path}/test/host-build")
def script_test_host_build(script_path: str, payload: ScriptHostTestBuildPayload) -> dict:
    script_dir = pick_scripts_dir(SCRIPTS_DIR_CANDIDATES, create=True)
    try:
        built = build_host_test_script(
            script_dir=script_dir,
            script_rel_path=script_path,
            endpoint_url=payload.endpoint_url,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to build host test script: {exc}") from exc

    built["built"] = True
    built["time"] = now_iso()
    return built


@router.post("/{script_path:path}/test/host-result")
def script_test_host_result(script_path: str, payload: ScriptHostTestResultPayload) -> dict:
    script_dir = pick_scripts_dir(SCRIPTS_DIR_CANDIDATES, create=False)
    try:
        _, normalized_path = resolve_script_path(script_dir, script_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    detail_parts = []
    reason = str(payload.reason or "").strip()
    log_file = str(payload.log_file or "").strip()
    if reason:
        detail_parts.append(reason)
    if log_file:
        detail_parts.append(log_file)
    detail = " | ".join(detail_parts)

    entry = set_script_last_test_result(
        script_rel_path=normalized_path,
        status=payload.status,
        detail=detail,
        config_path=CONFIG_PATH,
        lock=WRITE_LOCK,
    )
    return {
        "saved": True,
        "script_path": normalized_path,
        "last_test": entry,
        "time": now_iso(),
    }


@router.post("/move")
def script_move(payload: ScriptMovePayload) -> dict:
    script_dir = pick_scripts_dir(SCRIPTS_DIR_CANDIDATES, create=True)
    try:
        target_path, source_rel, target_rel = move_script_path(
            script_dir=script_dir,
            source_rel_path=payload.source_path,
            target_group=payload.target_group,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    move_script_enabled_state(source_rel, target_rel, CONFIG_PATH, WRITE_LOCK)
    move_script_metadata(source_rel, target_rel, CONFIG_PATH, WRITE_LOCK)
    move_script_test_result(source_rel, target_rel, CONFIG_PATH, WRITE_LOCK)
    return {
        "moved": True,
        "from": source_rel,
        "to": target_rel,
        "path": str(target_path),
        "time": now_iso(),
    }


@router.delete("/{script_path:path}")
def script_delete(script_path: str) -> dict:
    script_dir = pick_scripts_dir(SCRIPTS_DIR_CANDIDATES, create=True)
    try:
        deleted_path, normalized_path = delete_script_path(script_dir, script_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    remove_script_enabled_state(normalized_path, CONFIG_PATH, WRITE_LOCK)
    remove_script_metadata(normalized_path, CONFIG_PATH, WRITE_LOCK)
    remove_script_test_result(normalized_path, CONFIG_PATH, WRITE_LOCK)
    sync_info = sync_default_config_servers(
        script_dir=script_dir,
        config_path=CONFIG_PATH,
        lock=WRITE_LOCK,
    )
    return {
        "deleted": True,
        "script_path": normalized_path,
        "path": str(deleted_path),
        "default_config_server_sync": sync_info,
        "time": now_iso(),
    }


@router.post("/{script_path:path}/enabled")
def script_set_enabled(script_path: str, payload: ScriptEnabledPayload) -> dict:
    script_dir = pick_scripts_dir(SCRIPTS_DIR_CANDIDATES, create=True)
    try:
        resolved_path, normalized_path = resolve_script_path(script_dir, script_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not resolved_path.exists() or not resolved_path.is_file():
        raise HTTPException(status_code=404, detail=f"Script not found: {normalized_path}")

    changed = set_script_enabled(normalized_path, payload.enabled, CONFIG_PATH, WRITE_LOCK)
    sync_info = sync_default_config_servers(
        script_dir=script_dir,
        config_path=CONFIG_PATH,
        lock=WRITE_LOCK,
    )
    changed["default_config_server_sync"] = sync_info
    changed["time"] = now_iso()
    return changed


@router.post("/{script_path:path}/test/start")
def script_test_start(script_path: str, payload: ScriptTestStartPayload) -> dict:
    script_dir = pick_scripts_dir(SCRIPTS_DIR_CANDIDATES, create=False)
    try:
        resolved_script_path, normalized_path = resolve_script_path(script_dir, script_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not resolved_script_path.exists() or not resolved_script_path.is_file():
        raise HTTPException(status_code=404, detail=f"Script not found: {normalized_path}")

    try:
        status = start_script_test(
            script_path=resolved_script_path,
            script_rel_path=normalized_path,
            endpoint_url=payload.endpoint_url,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start script test: {exc}") from exc

    status["started"] = True
    status["time"] = now_iso()
    return status


@router.get("/{script_path:path}")
def get_script(script_path: str) -> dict:
    script_dir = pick_scripts_dir(SCRIPTS_DIR_CANDIDATES, create=False)
    try:
        resolved_script_path, normalized_path = resolve_script_path(script_dir, script_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not resolved_script_path.exists() or not resolved_script_path.is_file():
        raise HTTPException(status_code=404, detail=f"Script not found: {normalized_path}")

    return {
        "name": resolved_script_path.name,
        "group": normalized_path.split("/", 1)[0],
        "script_path": normalized_path,
        "path": str(resolved_script_path),
        "enabled": get_script_enabled(normalized_path, CONFIG_PATH),
        "metadata": get_script_metadata(normalized_path, CONFIG_PATH),
        "content": read_script(resolved_script_path),
        "time": now_iso(),
    }


@router.post("")
def create_script(payload: ScriptCreatePayload) -> dict:
    script_dir = pick_scripts_dir(SCRIPTS_DIR_CANDIDATES, create=True)
    try:
        script_path, normalized_path = create_script_path(script_dir, payload.group, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if script_path.exists():
        raise HTTPException(status_code=409, detail=f"Script already exists: {normalized_path}")

    write_script(script_path, payload.content, WRITE_LOCK)
    enabled = get_script_enabled(normalized_path, CONFIG_PATH)
    set_script_enabled(normalized_path, enabled, CONFIG_PATH, WRITE_LOCK)

    return {
        "created": True,
        "name": script_path.name,
        "group": normalized_path.split("/", 1)[0],
        "script_path": normalized_path,
        "path": str(script_path),
        "time": now_iso(),
    }


@router.put("/{script_path:path}")
def update_script(script_path: str, payload: ScriptPayload) -> dict:
    script_dir = pick_scripts_dir(SCRIPTS_DIR_CANDIDATES, create=True)
    try:
        resolved_script_path, normalized_path = resolve_script_path(script_dir, script_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_script(resolved_script_path, payload.content, WRITE_LOCK)
    metadata = get_script_metadata(normalized_path, CONFIG_PATH)
    if payload.metadata is not None:
        metadata_changed = set_script_metadata(
            normalized_path,
            payload.metadata.model_dump(),
            CONFIG_PATH,
            WRITE_LOCK,
        )
        metadata = metadata_changed["metadata"]

    sync_info = sync_default_config_servers(
        script_dir=script_dir,
        config_path=CONFIG_PATH,
        lock=WRITE_LOCK,
    )

    return {
        "saved": True,
        "name": resolved_script_path.name,
        "group": normalized_path.split("/", 1)[0],
        "script_path": normalized_path,
        "path": str(resolved_script_path),
        "metadata": metadata,
        "default_config_server_sync": sync_info,
        "time": now_iso(),
    }
