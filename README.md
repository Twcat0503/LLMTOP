# LLMTOP

LLMTOP 是自管 LLM 服務的 TUI／Web 監控工具。兩端共用 collector、snapshot 與 history，顯示 input／output tokens、t/s、running／waiting、KV cache、CPU／RAM／swap 與可用的 NVIDIA 裝置資料。缺少資料時保留 N/A、狀態與原因；預設只讀取觀測端點，不發推論請求。

目前為 **0.1.0 未發佈的 alpha 基礎版本**。Linux、vLLM 與 NVIDIA 已有實測；llama.cpp 實機與 macOS gate 尚缺。其他引擎、逐筆請求／來源與遠端硬體 agent 依 [路線](docs/ROADMAP.md) 擴充。證據見 [公開驗證摘要](docs/VALIDATION.md)。

## 建立與安裝

Python 3.11+、Node 24 與 uv 用於開發與建置。wheel 包含 Web，安裝後不需要 Node。官方 repository／套件來源尚未設定，目前從可信的原始碼副本或建置包安裝。

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

`--install-dir`／`--bin-dir` 可改位置；`--gpu` 加入 NVIDIA 可選依賴，`--constraints` 使用匯出的固定依賴，`--wheelhouse` 支援離線安裝。新環境通過依賴、版本與 schema 檢查後才啟用，安裝失敗保留原有版本。官方版本檢查與自動更新仍為後續項目。

## 開始使用

```sh
llmtop --version
llmtop init
llmtop doctor
llmtop
```

`init` 顯示設定路徑，建立只監看本機硬體的設定，保護檔案權限並拒絕覆寫。加入引擎可參考 [最小範例](examples/llmtop.minimal.toml) 與 [完整範例](examples/llmtop.example.toml)。VM／容器請調整 `hardware_scope`。

設定順序：`--config PATH` → `LLMTOP_CONFIG` → 使用者設定 → 舊的工作目錄 `llmtop.toml`。明確指定的檔案不存在時報錯，不退回另一份設定。

| 平台 | 使用者設定 |
| --- | --- |
| Linux | `${XDG_CONFIG_HOME:-$HOME/.config}/llmtop/llmtop.toml`；XDG 路徑須為絕對路徑 |
| macOS | `~/Library/Application Support/llmtop/llmtop.toml` |

裸指令開啟 TUI；非互動終端提示 once／Web。合成範例須明確 `--demo`，畫面標示 Demo data。

```sh
llmtop --demo
llmtop once --demo --json
llmtop once --config /absolute/path/to/llmtop.toml --json
llmtop schema
```

`once` 預設取兩筆，依實際間隔計算 throughput；`--samples 1` 的 rate 為 warming_up。

## Web 與共用 collector

```sh
llmtop web
llmtop tui --connect http://127.0.0.1:8787
```

`web` 是 `serve` 的別名，本機桌面在成功啟動後嘗試開啟瀏覽器。`serve` 預設只啟動服務，`--open`／`--no-open` 控制瀏覽器。SSH／無桌面環境列網址與轉送指引。backend 保持 loopback，預設 [http://127.0.0.1:8787](http://127.0.0.1:8787)。

在開發機建立轉送，將 YOUR_SSH_ALIAS 換成自己的 SSH 別名：

```sh
ssh -N -L 127.0.0.1:8787:127.0.0.1:8787 YOUR_SSH_ALIAS
```

TUI：q 離開、/ 搜尋、Esc 返回、s 排序、t 切換趨勢、space 暫停、? 說明；`--ascii` 使用 ASCII sparklines。Web 提供篩選、排序、詳情與趨勢；REST 初始化、SSE 更新，斷線時 snapshot fallback。圖表只用 backend history，缺項保留 gap。

## 能力與限制

- vLLM／llama.cpp adapters 明確選擇 labels，拒絕未選定的多 series，避免加總 rank／replica。
- Counter epoch 處理重啟、series 變更與長 gap；GPU 失敗不拖停引擎輪詢。
- psutil 提供本機資料；可選 NVML，失敗以 nvidia-smi 或 N/A 降級。
- API：/health、/api/v1/snapshot、/api/v1/capabilities、/api/v1/history、/api/v1/events。

llama.cpp 的 context 容量不作 KV 使用率。遠端 engine HTTP 不代表遠端硬體；未設 collector 時明確 N/A。目前只提供服務層級 running／waiting，沒有完整逐筆 request lifecycle 或來源排行。憑證只由 server 環境變數讀取，不傳給瀏覽器。

## 開發與發佈準備

固定依賴位於 uv.lock 與 frontend/package-lock.json。檢查見 [CONTRIBUTING](CONTRIBUTING.md)，公開檔案與安裝包審查見 [RELEASING](docs/RELEASING.md)，狀態見 [TODO](docs/TODO.md)。私人設定、工作站指令、原始遙測與內部驗收紀錄排除於 Git 與發佈包。

[架構](docs/ARCHITECTURE.md)、[指標契約](docs/METRIC-SPEC.md)、[支援矩陣](docs/SUPPORT-MATRIX.md)、[介面](docs/INTERFACES.md)、[專案規劃](docs/PROJECT-PLAN.md)。

採 [MIT](LICENSE) 授權，第三方依賴保留各自授權。安全回報見 [SECURITY](SECURITY.md)。本機 Git 基礎已建立，但尚無 remote、版本 tag 或公開 release；正式 repository、私密回報管道與實機 gate 尚待完成。既有安裝包僅作歷史驗證產物，正式發布須由確認的 commit 重新建置，不能將本機提交視為發布完成。
