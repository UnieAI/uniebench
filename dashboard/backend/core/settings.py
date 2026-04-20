import os
import threading
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", "/workspace/jeff/Benchmark-Autotest"))
CONFIG_PATH = Path(os.getenv("CONFIG_PATH", str(PROJECT_ROOT / "config" / "config.yaml")))

_SCRIPT_DIR_ENV = os.getenv("SCRIPT_DIR", "").strip()
if _SCRIPT_DIR_ENV:
    SCRIPTS_DIR_CANDIDATES = [Path(_SCRIPT_DIR_ENV)]
else:
    SCRIPTS_DIR_CANDIDATES = [PROJECT_ROOT / "service", PROJECT_ROOT / "services"]

WRITE_LOCK = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
