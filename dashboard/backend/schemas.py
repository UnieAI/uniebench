from pydantic import BaseModel


class ConfigPayload(BaseModel):
    content: str


class ScriptMetadataPayload(BaseModel):
    tp_size: str = ""
    model_id: str = ""
    model_name: str = ""
    model_path: str = ""
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


class ScriptHostTestBuildPayload(BaseModel):
    endpoint_url: str


class ScriptHostTestResultPayload(BaseModel):
    status: str
    reason: str = ""
    log_file: str = ""
    endpoint: str = ""
    script: str = ""


class ScriptEnabledPayload(BaseModel):
    enabled: bool


class ScriptMovePayload(BaseModel):
    source_path: str
    target_group: str


class GlobalConfigPayload(BaseModel):
    model_path: str = ""
    model_names: list[str] = []
    default_base_url: str = ""


class BenchmarkProfilePayload(BaseModel):
    id: str = "default"
    name: list[str] = ["inferencemax-h100"]
    endpoint_type: str = "completions"
    dataset_path: str = "/workspace/jeff/Benchmark-Autotest/datasets/neural-bridge/rag-dataset-12000/data/train-00000-of-00001-9df3a936e1f63191.parquet"
    token_lengths: list[str] = ["none/1024"]
    concurrency: list[int] = [1, 16, 32, 64, 128, 256, 512]


class BenchmarkConfigPayload(BaseModel):
    profiles: list[BenchmarkProfilePayload] = []


class RuntimeTargetPayload(BaseModel):
    server_id: str | None = None
    benchmark_id: str | None = None


class TestMetaPayload(BaseModel):
    test_name: str | None = None
    sheet_name: str | None = None
    platform_name: str | None = None
