# main_cli.py 規格草案（v0.1）

## 1. 目的
建立新的 CLI 入口 `main_cli.py`，提供互動式文字介面，讓使用者可以在不手改檔案的情況下完成：
1. 修改 `config/config.yaml`
2. 匯入 `config/service_account.json`
3. 撰寫服務啟動腳本（`.sh`）
4. 測試腳本可啟動/關閉
5. 預覽 Benchmark 執行計畫
6. 執行完整 Benchmark

## 2. 範圍
### 2.1 MVP（第一版必做）
- 單一入口：`python3 main_cli.py`
- 菜單式互動流程
- 以目前既有模組整合為主，不重寫 benchmark 核心邏輯
  - 啟動：`run_container.py` / `run_container.run_container`
  - 健康檢查：`wait_for_healthcheck.py`
  - 執行：`main.py`
  - 停止：`stop_container.py`
  - 匯出：沿用 `main.py` 既有流程

### 2.2 非目標（MVP 不做）
- Web UI
- 多使用者協作鎖定
- 遠端主機管理

## 3. 目錄與檔案
- 新增：`main_cli.py`
- 新增：`docs/main_cli_spec.md`（本文件）
- 可能新增：`cli/` 子模組（第二階段）

## 4. 使用者操作流程
1. 進入主選單
2. 選擇功能：
   - `1) 編輯設定檔`
   - `2) 匯入 service_account.json`
   - `3) 編輯服務腳本`
   - `4) 測試服務腳本`
   - `5) 預覽 Benchmark 計畫`
   - `6) 執行完整 Benchmark`
   - `7) 離開`

## 5. 功能規格
### 5.1 編輯設定檔
- 進入 `編輯設定檔` 後固定分成四個子選單：
  - `1) autotest`
  - `2) healthcheck`
  - `3) server`
  - `4) benchmark`

#### 5.1.1 autotest
- 可編輯：
  - `autotest.name`
  - `autotest.sheet_name`
- `sheet_name` 操作：
  - 顯示 `sheet_id_list.json` 既有清單，支援上下移動選擇（或數字選擇）
  - 可輸入新 `sheet_name` + Google Sheet URL 新增到 `sheet_id_list.json`
  - 新增成功後自動將 `autotest.sheet_name` 切換為新值
- 驗證：
  - 新增網址必須符合 Google Sheet URL 格式（含 `/spreadsheets/d/`）
  - 若 `sheet_name` 重複，需再次確認是覆蓋還是取消

#### 5.1.2 healthcheck
- 可編輯：
  - `healthcheck.timeout`
  - `healthcheck.max_tries`
  - `healthcheck.interval`
- 驗證：
  - `timeout > 0`
  - `max_tries >= 1`
  - `interval > 0`

#### 5.1.3 server
- 先顯示目前 `server.id`
- 提供三個 `id` 層級操作：
  - `切換 id`（從 `default_config.server[*].id` 清單選擇）
  - `建立並切換新 id`
  - `編輯目前 id 設定`
- `建立新 id`：
  - 要求輸入新 id（不可重複）
  - 以目前 id 設定複製一份作為初始值（MVP 預設）
  - 建立後把 `server.id` 指向新 id
- `編輯目前 id 設定` 可編輯：
  - `base_url`（UI 文案顯示為 host）
  - `port`
  - `model_id`
  - `model_name`
  - `model_path`
- `container` 在 CLI 選單統一改名為「服務」
- 服務管理選單：
  - `新增服務`
  - `編輯服務`
  - `移除服務`
- `新增服務`（依序詢問）：
  - `name`
  - `path`
  - `service_name`（可填 `none`）
  - `tp_size`
  - 其他可選欄位：`port`, `base_url`, `model_name`, `model_path`, `model_id`, `endpoint_type`
  - 可選欄位仍要逐一詢問，使用者可直接按 Enter 表示採用預設值（預設取目前 server id 對應設定）
- `編輯服務`：
  - 先以 `name` 列出所有服務供選擇
  - 選定後依序詢問每個欄位是否修改
- `移除服務`：
  - 先以 `name` 選擇目標服務
  - 需二次確認（例如輸入 `DELETE`）後才刪除

#### 5.1.4 benchmark
- 先顯示目前 `benchmark.id`
- 提供三個 `id` 層級操作：
  - `切換 id`
  - `建立並切換新 id`
  - `編輯目前 id 設定`
- `編輯目前 id 設定`：
  - 每個欄位都可選擇並編輯（MVP 至少包含）
  - `name`（benchmark 名稱列表）
  - `endpoint_type`
  - `dataset_path`
  - `token_lengths`
  - `concurrency`
  - `seeds`（若存在）

#### 5.1.5 儲存與回寫
- 所有編輯先在記憶體中變更，離開 `編輯設定檔` 前顯示 diff 摘要
- 使用者確認後才寫回：
  - `config/config.yaml`
  - `sheet_id_list.json`（若有新增/覆蓋 sheet）

### 5.2 匯入 service_account.json
- 目標位置：`config/service_account.json`
- 行為：
  - 以類似 vim 的互動式編輯介面讓使用者直接填寫/修改 JSON 內容
  - 檢查 JSON 可解析
  - 檢查必要鍵（最少：`type`, `project_id`, `client_email`, `private_key`）
  - 通過後寫入檔案
  - 寫入權限建議 `0600`

### 5.3 撰寫服務腳本
- 目標位置：`services/<name>.sh`
- 僅提供「編輯器模式」：開啟類似 vim 的互動式編輯介面讓使用者直接編輯檔案
- 寫入後自動：
  - `chmod +x`
  - 基本靜態檢查：首行 shebang、`set -euo pipefail`

### 5.4 測試服務腳本
- 選擇欲測試腳本（例如 `services/run_rs.sh`）
- 使用既有流程執行：
  1. 啟動服務
  2. `healthcheck` 端點檢查（使用 `config.healthcheck.url`）
  3. `/v1/models` 端點檢查（確認 OpenAI 相容 API 可用）
  4. 顯示結果（成功/失敗，需分別顯示兩個檢查項目）
  5. 無論成功失敗皆嘗試停止服務
- 測試模式不執行 benchmark

### 5.5 預覽 Benchmark
- 不執行實際 benchmark
- 列出展開後的執行矩陣：
  - container x benchmark_name x token_lengths x concurrency
- 顯示總輪數、每輪關鍵資訊：
  - `container`, `benchmark`, `input_len`, `output_len`, `concurrency`
- 顯示預估輸出目錄：`results/{autotest.name}`

### 5.6 執行完整 Benchmark
- 呼叫既有 `main.py` 主流程（建議以子程序執行，保持行為一致）
- 支援 verbosity 轉發：
  - `main_cli.py` 無參數 -> `main.py`
  - `main_cli.py -v/-vv/-vvv` -> 同步傳給 `main.py`
- 執行前二次確認：
  - 顯示即將執行的設定摘要
  - `yes/no`

## 6. 命令列介面
## 6.1 啟動
- `python3 main_cli.py`
- `python3 main_cli.py -v`
- `python3 main_cli.py -vv`
- `python3 main_cli.py -vvv`

### 6.2 可選非互動命令（第二階段）
- `python3 main_cli.py preview`
- `python3 main_cli.py run`
- `python3 main_cli.py config set autotest.name xxx`

## 7. 錯誤處理與回傳碼
- `0`: 成功
- `1`: 使用者輸入錯誤或驗證失敗
- `2`: 外部依賴失敗（如 hf、docker、python 子程序）
- `3`: benchmark 執行失敗

## 8. 安全與資料保護
- `service_account.json` 不印出敏感欄位
- log 只顯示 key 名稱，不顯示 `private_key` 內容
- 任何複製/覆蓋操作先提示目標檔案

## 9. 與現有系統整合重點
- 沿用現有 logging 層級（無參數、`-v`、`-vv`、`-vvv`）
- 沿用現有模型自動下載邏輯（啟動前檢查 model）
- 沿用現有結果格式與後處理欄位

## 10. 驗收條件（MVP）
1. 使用者可在 CLI 內修改並保存 `config/config.yaml`
2. 可匯入並驗證 `config/service_account.json`
3. 可建立/修改 `services/*.sh` 並通過基本檢查
4. 可完成「啟動->健康檢查->停止」的腳本測試
5. 可預覽 benchmark 全部輪次
6. 可從 CLI 觸發完整 benchmark，且保有現有日志行為

## 11. 建議實作順序
1. 主選單框架 + verbosity
2. config 編輯
3. service_account 匯入
4. 腳本編輯與測試
5. benchmark 預覽
6. 完整 benchmark 執行
