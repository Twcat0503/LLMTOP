**[English](README.md)** | **繁體中文**

<div align="center">

# LLMTOP

**自管 LLM 服務的 TUI／Web 監控工具**

tokens、t/s、佇列深度、KV cache 與主機硬體 — vLLM、llama.cpp、Strata 與它們所在的機器，一個唯讀畫面全部看到。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![Version 0.1.0 alpha](https://img.shields.io/badge/version-0.1.0--alpha-orange)](CHANGELOG.md)
[![Platform Linux · macOS](https://img.shields.io/badge/platform-Linux%20%C2%B7%20macOS-lightgrey)](docs/SUPPORT-MATRIX.md)

</div>

> **狀態**：目前為 **0.1.0 未發佈的 alpha 基礎版本**。Linux 上的 vLLM 與 NVIDIA 已實測；llama.cpp 實機與 macOS gate 尚缺。證據見 [公開驗證摘要](docs/VALIDATION.md)，後續項目見 [路線](docs/ROADMAP.md)。

## LLMTOP 是什麼？

LLMTOP 是自管 LLM 推論服務的終端機（TUI）與 Web 儀表板。它把你跑的引擎 — vLLM、llama.cpp、Strata — 和背後的主機硬體放在同一個畫面：input／output tokens 與 tokens/sec、running／waiting 請求數、KV cache 使用率、CPU／RAM／swap，以及可取得的 NVIDIA 裝置資料。

TUI 與 Web 共用同一個 collector、snapshot 與 history，兩端永遠顯示相同的數值。LLMTOP 預設唯讀：只輪詢觀測端點（`/metrics` 等），不發推論請求。

## 為什麼選 LLMTOP？

- **缺資料就說缺**。數值無法取得時顯示 N/A，並保留狀態與原因；不猜值、不補零，也不會把多餘的 rank／replica series 加總。
- **預設唯讀**。監控探測不發推論請求；憑證只由 server 環境變數讀取，不傳給瀏覽器。
- **一個引擎，兩個介面**。TUI 與 Web 渲染同一份 snapshot，值、單位與缺項完全一致。
- **重啟安全的 counter**。counter epoch 處理引擎重啟、series 變更與長 gap；GPU 收集失敗不會拖停引擎輪詢。
- **對遠端部署友善**。Web backend 預設只綁 loopback，內建 SSH 轉送指引；TUI 可用 `--connect` 接上遠端 backend。

## 功能

### 引擎指標

- input／output token counter 與即時 throughput（tokens/sec）
- 引擎有暴露時的 running／waiting 請求數
- 以引擎原生比率顯示 KV cache 使用率（llama.cpp 的 context 容量不當作 KV 使用率）
- 明確的指標選擇：scrape 含多 series 時由你指定 labels，LLMTOP 拒絕自行加總 rank／replica

### 主機與 GPU

- psutil 提供 CPU、RAM、swap 與程序資料
- NVIDIA 資料優先走 NVML（可選依賴），失敗以 nvidia-smi 或明確 N/A 降級
- 按 host 劃分資料範圍：讀取遠端 engine URL 不代表能顯示遠端硬體

### 介面

- TUI：搜尋、排序、趨勢 sparkline、暫停、說明；`--ascii` 支援純文字終端
- Web（React）：篩選、排序、服務詳情與趨勢圖；圖表只用 backend history，缺項保留 gap
- 腳本整合：`llmtop once --json` 輸出單次 snapshot；`llmtop schema` 輸出 snapshot 的 JSON schema
- SSE 即時更新，斷線時以 snapshot fallback

### 部署

- 單一 wheel 內含建置完成的 Web UI，執行期不需要 Node
- 隔離環境的安裝工具（預設 `~/.local/share/llmtop`，指令在 `~/.local/bin`）；新環境通過依賴、版本與 schema 檢查後才啟用，安裝失敗保留原有版本
- Demo 模式（`--demo`）顯示明確標示的合成資料，完全不碰引擎

## 支援的引擎

| 引擎 | 狀態 | 可取得的資料 | 備註 |
| --- | --- | --- | --- |
| vLLM（OpenAI server） | 已實測（Linux） | token counters 與 t/s、running／waiting、原生 KV 比率（`/metrics`） | 已對 vLLM 0.29.0／Ubuntu 26.04 實測 |
| llama.cpp server | 已實作，僅合成 fixtures | token counters、processing／deferred gauges（`/metrics`） | 需啟用 `--metrics`；實機 gate 尚未完成；context 容量不作 KV 使用率 |
| Strata server | Linux 實機驗證 | token counters 與 t/s、running／waiting、model 名稱（`/metrics` 採 vLLM 命名） | `/metrics` 預設回傳 JSON，需以 `Accept: text/plain` 或 `?format=prometheus` 協商文字格式；KV 欄位為執行中請求的 context 佔用比而非 KV pool；已對 Strata 0.1.44.1 實機驗證（Ubuntu 24.04，2026-10-22），持續負載 gate 仍開放 |
| SGLang server | 路線圖中 | — | 計畫於 M2 介接 |
| Ollama | 路線圖中 | — | 計畫於 M2 介接 |

逐版本、逐平台的支援宣稱請看 [支援矩陣](docs/SUPPORT-MATRIX.md)：只有完成 fixture 與實機驗收的組合才會被標為已驗證。

## 安裝

執行需要 Python 3.11+；從原始碼建置才需要 Node 24 與 uv。官方 repository／套件來源尚未設定，目前從可信的原始碼副本或建置包安裝。

```sh
uv sync --locked --extra dev
cd frontend
npm ci --no-audit --no-fund
npm run build
cd ..
uv build --wheel
python3 scripts/install_user.py \
  --wheel dist/llmtop-0.1.0-py3-none-any.whl \
  --ensure-path
```

安裝工具為 Linux／macOS 使用者建立隔離環境，預設放在 `~/.local/share/llmtop`，指令放在 `~/.local/bin`。`--ensure-path` 為 Bash／Zsh／POSIX sh 加入可重複執行的 PATH 設定；重新開啟登入 shell 後，可從任意目錄使用同一版本。立即使用可執行 `export PATH="$HOME/.local/bin:$PATH"`。既有同名指令或非本工具管理的目錄會被拒絕覆寫。

`--install-dir`／`--bin-dir` 可改位置；`--gpu` 加入 NVIDIA 可選依賴，`--constraints` 使用匯出的固定依賴，`--wheelhouse` 支援離線安裝。安裝完成後，`llmtop update` 會檢查設定為 `[update].source_url` 的發佈來源（HTTPS，以 `SHA256SUMS` 驗證）並原子啟用新環境；`llmtop rollback` 還原前一版本。預設未設定更新來源。

## 開始使用

```sh
llmtop init      # 建立只監看本機硬體的私有設定
llmtop doctor    # 檢查設定、端點與權限
llmtop           # 開啟 TUI
```

編輯設定加入引擎，可參考 [最小範例](examples/llmtop.minimal.toml) 與 [完整範例](examples/llmtop.example.toml)。VM／容器請調整 `hardware_scope`。

```toml
schema_version = 1

[[hosts]]
id = "local"
label = "本機主機"
collector = "local"

[[services]]
id = "vllm"
label = "vLLM"
host_id = "local"
engine = "vllm"
api_url = "http://127.0.0.1:8000"
```

設定順序：`--config PATH` → `LLMTOP_CONFIG` → 使用者設定 → 舊的工作目錄 `llmtop.toml`。明確指定的檔案不存在時報錯，不退回另一份設定。

| 平台 | 使用者設定 |
| --- | --- |
| Linux | `${XDG_CONFIG_HOME:-$HOME/.config}/llmtop/llmtop.toml`；XDG 路徑須為絕對路徑 |
| macOS | `~/Library/Application Support/llmtop/llmtop.toml` |

想先看畫面？`llmtop --demo` 顯示明確標示 Demo data 的合成範例。非互動終端下，裸指令會提示改用 once 或 Web。

## Web 與遠端監控

```sh
llmtop web               # serve 的別名；本機桌面在成功啟動後嘗試開啟瀏覽器
llmtop serve --no-open   # headless：只列網址與 SSH 轉送指引
```

backend 保持 loopback，預設 [http://127.0.0.1:8787](http://127.0.0.1:8787)。在開發機建立轉送，將 `YOUR_SSH_ALIAS` 換成自己的 SSH 別名：

```sh
ssh -N -L 127.0.0.1:8787:127.0.0.1:8787 YOUR_SSH_ALIAS
```

也可以不開瀏覽器，讓 TUI 直接接上 backend；connected 模式只讀 backend URL，不讀引擎憑證：

```sh
llmtop tui --connect http://127.0.0.1:8787
```

## 指令參考

| 指令 | 說明 |
| --- | --- |
| `llmtop` | TUI（預設） |
| `llmtop once` | 取兩筆樣本計算 throughput；`--json` 輸出機器可讀格式；`--samples 1` 的 rate 為 warming_up |
| `llmtop doctor` | 診斷設定與端點 |
| `llmtop init` | 建立使用者設定；`--print` 只輸出範本 |
| `llmtop web` / `llmtop serve` | Web backend；`--port` 改埠號；`--open`／`--no-open` 控制瀏覽器 |
| `llmtop tui --connect URL` | TUI 接上既有 backend |
| `llmtop schema` | 輸出 snapshot 的 JSON schema |
| `llmtop update` | 檢查已設定的發佈來源並安裝新版本；`--check` 只回報，`--wheel` 離線安裝 |
| `llmtop rollback` | 還原上次更新保留的前一版本 |

全域選項：`--config`、`--demo`、`--ascii`、`--theme dark|light|auto`、`--version`。

TUI 按鍵：`q` 離開、`/` 搜尋、`Esc` 返回、`s` 排序、`t` 切換趨勢、`space` 暫停、`?` 說明。

## 運作方式

```text
engines (read-only /metrics) ─┐
hosts (psutil · NVML)         ├─▶ collectors ─▶ snapshot + history ─┬─▶ TUI
                                                                    ├─▶ Web UI (REST + SSE)
                                                                    └─▶ once --json
```

- Adapters 明確選擇 Prometheus labels，拒絕未選定的多 series，避免加總 rank／replica
- Counter epoch 處理重啟、series 變更與長 gap
- REST API：`/health`、`/api/v1/snapshot`、`/api/v1/capabilities`、`/api/v1/history`、`/api/v1/events`（SSE）

細節見 [架構](docs/ARCHITECTURE.md)、[介面](docs/INTERFACES.md) 與 [指標契約](docs/METRIC-SPEC.md)。

## 隱私與安全

- 預設唯讀監控，不發推論請求
- 憑證只由 server 環境變數讀取，不傳給瀏覽器
- 無 telemetry、不回傳任何資料
- Web backend 預設只綁 loopback

目前只提供服務層級 running／waiting，沒有完整逐筆 request lifecycle 或來源排行；遠端 engine HTTP 不代表遠端硬體，未設 collector 時明確顯示 N/A。疑似漏洞請依 [SECURITY](SECURITY.md) 回報。

## 專案狀態

已驗證：Linux（Ubuntu 26.04）上的 vLLM 0.29.0 與 NVIDIA NVML 實測、Strata 0.1.44.1 實機驗證（Ubuntu 24.04，2026-10-22）、Linux／macOS × Python 3.11／3.14 portable CI（於 `49439ba` 全綠）、89 項 pytest 與 6 項 Chromium 測試、安裝與發佈審查流程。尚待完成：llama.cpp 實機、macOS／Apple GPU、真實非零持續負載與正式 release。即時狀態見 [TODO](docs/TODO.md) 與 [驗證紀錄](docs/VALIDATION.md)。

既有安裝包僅作歷史驗證產物，正式發布須由確認的 commit 重新建置。

## 文件

| 文件 | 內容 |
| --- | --- |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | 整體架構與資料流 |
| [METRIC-SPEC](docs/METRIC-SPEC.md) | 指標語意與單位契約 |
| [INTERFACES](docs/INTERFACES.md) | REST／SSE 介面定義 |
| [SUPPORT-MATRIX](docs/SUPPORT-MATRIX.md) | 引擎／OS／硬體支援核對 |
| [VALIDATION](docs/VALIDATION.md) | 公開驗證摘要與證據 |
| [ROADMAP](docs/ROADMAP.md)・[PROJECT-PLAN](docs/PROJECT-PLAN.md)・[TODO](docs/TODO.md) | 路線與目前進度 |
| [RELEASING](docs/RELEASING.md) | 發佈程序與產物審查 |

## 參與貢獻

專案處於 alpha。開發環境、檢查指令與貢獻規則見 [CONTRIBUTING](CONTRIBUTING.md)；改動 collector 或 adapter 前請先讀 [路線](docs/ROADMAP.md) 與 [指標語意](docs/METRIC-SPEC.md)。

## 授權

採 [MIT](LICENSE) 授權，第三方依賴保留各自授權。
