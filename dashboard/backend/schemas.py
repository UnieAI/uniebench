from pydantic import BaseModel


class ConfigPayload(BaseModel):
    content: str


class ScriptMetadataPayload(BaseModel):
    tp_size: str = ""
    model_name: str = ""
    model_id: str = ""
    base_url: str = ""
    port: str = ""


class ScriptPayload(BaseModel):
    content: str
    metadata: ScriptMetadataPayload | None = None


class ScriptCreatePayload(BaseModel):
    name: str
    group: str = "default"
    content: str = "#!/bin/bash\nset -euo pipefail\n\n"


class ScriptTestStartPayload(BaseModel):
    endpoint_url: str


class ScriptEnabledPayload(BaseModel):
    enabled: bool


class ScriptMovePayload(BaseModel):
    source_path: str
    target_group: str


class GlobalConfigPayload(BaseModel):
    model_path: str = ""
    model_names: list[str] = []
    default_base_url: str = ""
