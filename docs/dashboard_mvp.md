# Dashboard MVP

最小架構：
- `dashboard-api` (`FastAPI`): `2148`
- `dashboard-ui` (`Nginx` static): `2147`

功能：
- Tab 1（系統資源監看）: 即時 GPU/CPU/RAM 使用狀態（每 2 秒刷新）
- Tab 2（設定檔編輯器）: `config/config.yaml` 編輯與儲存（YAML 驗證）
- Tab 3（服務腳本）: 列出腳本、點選編輯、新增、儲存；提供 Test Script（可輸入 endpoint、啟動/停止測試、即時顯示 health/models/completions），`enable/disable` 目前仍為 UI 介面
- 多語系：支援中文 / English，前端可即時切換

## 目錄結構（按功能拆分）

- `dashboard/backend/main.py`: FastAPI app 組裝入口
- `dashboard/backend/routers/`: API 路由（`gpu` / `config` / `scripts` / `health`）
- `dashboard/backend/services/`: 功能邏輯（GPU 狀態、設定檔處理、腳本處理）
- `dashboard/backend/core/`: 共用設定
- `dashboard/frontend/index.html`: 頁面骨架（不含 inline script/style）
- `dashboard/frontend/partials/`: 各 Tab 的 HTML partial（monitor / config / scripts）
- `dashboard/frontend/js/app.js`: 前端入口與跨功能初始化
- `dashboard/frontend/js/features/`: 各 Tab 功能（monitor / configEditor / scripts）
- `dashboard/frontend/js/core/`: 共用模組（api / i18n / ui / tabs）
- `dashboard/frontend/styles/`: 按頁面功能拆分樣式

## 啟動

```bash
docker compose -f docker-compose.dashboard.yml up --build -d
```

## 存取

- UI: `http://localhost:2147`
- API health: `http://localhost:2148/health`

## 停止

```bash
docker compose -f docker-compose.dashboard.yml down
```

## 備註

- API 會直接讀寫 `config/config.yaml`。
- `gpus: all` 需要主機具備 NVIDIA Container Toolkit。
- 若主機不支援 GPU runtime，先移除 `docker-compose.dashboard.yml` 的 `gpus: all`，UI 仍可使用 config 編輯器。
