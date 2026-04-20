from pydantic import BaseModel


class ConfigPayload(BaseModel):
    content: str


class ScriptPayload(BaseModel):
    content: str


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
