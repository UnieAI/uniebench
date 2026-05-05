from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dashboard.backend.routers.config import router as config_router
from dashboard.backend.routers.benchmark import router as benchmark_router
from dashboard.backend.routers.gpu import router as gpu_router
from dashboard.backend.routers.global_config import router as global_config_router
from dashboard.backend.routers.health import router as health_router
from dashboard.backend.routers.scripts import router as scripts_router


app = FastAPI(title="Benchmark Dashboard API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(gpu_router)
app.include_router(config_router)
app.include_router(scripts_router)
app.include_router(global_config_router)
app.include_router(benchmark_router)
