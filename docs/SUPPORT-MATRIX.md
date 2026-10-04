# 支援矩陣與可行性核對

核對日期：2026-10-02（Asia/Taipei）。本文件核對官方文件及部分上游原始碼，沒有連線到使用者部署，也沒有執行 Mac／Linux 實機測試。

2026-10-03 在 Ubuntu 26.04／Python 3.14.4 完成 M1 首輪：真實 vLLM 0.29.0 counters／rates／counts／KV 與 NVIDIA NVML fields。llama.cpp 僅通過合成 fixtures；實機與 macOS 尚未驗證。證據見 [公開摘要](VALIDATION.md)。

## 1. 支援狀態的意義

| 狀態 | 意義 |
| --- | --- |
| 文件確認 | 官方觀測介面存在，足以規劃介接；尚未驗證實際版本 |
| 條件可用 | 需要啟動參數、額外權限、既有請求事件或特定版本 |
| 未確認 | 尚無已核對的穩定介面，不承諾提供數值 |
| 目標支援 | LLMTOP 計畫納入的範圍；尚未實作 |
| 實機驗證 | 只適用已完成驗收的指定版本／OS／硬體；目前 Ubuntu VM 的 vLLM 0.29.0 與兩張 Ada GPU 範圍見 M1 紀錄 |

「LLMTOP 能在哪個 OS 運行」、「被監控引擎在哪個 OS 運行」、「哪些指標可取得」是三個獨立維度。

## 2. 引擎能力矩陣

以下各列都是目標介接能力，並非已完成的 LLMTOP 功能。

| 引擎／形式 | input／output tokens 與 t/s | running／waiting 數量 | 逐筆請求 | KV／memory pool | 請求來源 | 階段 |
| --- | --- | --- | --- | --- | --- | --- |
| vLLM OpenAI server | 文件確認：counter 差分 | 文件確認：scheduler gauges | 原生 metrics 為彙總；需另外接事件 | 文件確認：KV 使用比率；容量依版本 | 額外 gateway／event source | M1 |
| llama.cpp server | 條件可用：啟用 metrics 後 counter 差分 | 條件可用：processing／deferred | slots 可觀察 running 槽位，不能保證完整 waiting 清單 | 未確認通用使用率；context 不作替代 | 額外 gateway／event source | M1 |
| SGLang server | 條件可用：啟用 metrics 後 counter 差分 | 文件確認：running／queue gauges | 原生彙總；詳細狀態需事件 | 條件可用：按版本及 pool 語意區分 | 額外 gateway／event source | M2 |
| Ollama 原生 API | 條件可用：觀察請求最終 usage／timings | 沒有已確認的通用 scheduler API | 額外 gateway／event source；只能展示被觀察請求 | 沒有已確認的通用 KV occupancy API | 額外 gateway／event source | M2 |
| 僅 OpenAI-compatible API | 回應有 usage 且可觀察時才可用 | 不由 API 相容性推定 | 以已授權請求事件為主 | 未確認 | 以事件資料為主 | M3 候選 |

### vLLM

官方 API server 暴露 `/metrics`。規劃映射 prompt／generation counters、running／waiting 與 KV ratio；counter 名稱須辨別文件中的 family 名稱與實際 exposition 的 `_total` suffix，並以版本 fixture 決定 alias。資料來源：[Production Metrics](https://docs.vllm.ai/en/stable/usage/metrics/)、[Metrics design](https://docs.vllm.ai/en/stable/design/metrics/)。

macOS Apple Silicon 的 CPU 部署由官方列為實驗性，需從原始碼編譯；官方亦連結社群維護的 vllm-metal。首輪驗收以 Linux 部署為主，Mac dashboard 可透過 HTTP 監看 Linux；Mac 原生 vLLM／Metal plugin 需獨立測試，不一概寫成不支援。資料來源：[CPU installation](https://docs.vllm.ai/en/stable/getting_started/installation/cpu/)。

### llama.cpp

server 的 `/metrics` 需啟用 `--metrics`；`/slots` 是否可用取決於設定與版本。規劃使用原生 token counters 與 processing／deferred gauges；router mode 的 metrics 可能需要 model query。slots 能補充槽位狀態，但不足以重建兩次輪詢之間所有完成請求。資料來源：[server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)。

llama.cpp 官方列出 Apple Silicon／Metal 與多種 Linux 可用的計算 backend，作為 Mac／Linux 原生部署的主要驗收候選。資料來源：[llama.cpp README](https://github.com/ggml-org/llama.cpp)。

### SGLang

啟用 `--enable-metrics` 後，官方資料包含 prompt／generation counters 與 running／queue gauges。先驗收一般 unified engine，prefill／decode 分離部署另作 profile。資料來源：[Production Metrics](https://github.com/sgl-project/sglang/blob/main/docs/docs/references/production_metrics.mdx)。

目前上游程式將 `token_usage` 定義為 full／SWA／Mamba pools 的瓶頸比率。不能直接把它統一標成「KV cache 使用率」。有 full-attention pool metrics 時才能映射對應 KV pool；舊版本需保留 native 語意。資料來源：[metrics_collector.py](https://github.com/sgl-project/sglang/blob/main/python/sglang/srt/observability/metrics_collector.py)。

### Ollama

`/api/ps` 提供已載入模型與其記憶體資料，不是請求清單。tokens 與 timing 出現在生成回應，串流則位於最終 `done=true` chunk；時間單位為 ns。被動 dashboard 無法讀取其他 client 已收到的回應，需要 client／gateway 的既有觀測資料。資料來源：[List running models](https://docs.ollama.com/api/ps)、[Usage](https://docs.ollama.com/api/usage)。

官方確認 Apple GPU 可使用 Metal。這只證明 Ollama 的計算 backend 能用 Metal，並不保證 LLMTOP 能從外部取得完整 Apple GPU utilization。資料來源：[Hardware support](https://docs.ollama.com/gpu)。

## 3. LLMTOP 本身的 OS／硬體目標

| 執行環境 | TUI／Web backend／HTTP 介接 | CPU／RAM／swap／process | GPU 負載／記憶體 | 目標狀態 |
| --- | --- | --- | --- | --- |
| Linux x86_64＋NVIDIA | 目標支援 | 目標支援：psutil | NVML 優先，nvidia-smi fallback；按 device 能力降級 | 首輪驗收 |
| Linux x86_64／arm64 CPU only | 目標支援 | 目標支援：psutil | N/A，不要求 GPU | 首輪含 x86_64；arm64 需 runner |
| macOS Apple Silicon | 目標支援 | 目標支援：psutil；OS 特有指標另驗證 | 統一記憶體須分清來源；GPU utilization／功耗為獨立研究項 | 首輪基本監控；GPU 深度資料在 M2 gate |
| macOS Intel | 目標支援 | 目標支援：psutil | CPU 路徑先驗收；AMD／Intel GPU provider 尚未確認 | 有實機再擴充驗收 |
| Linux AMD／Intel GPU | TUI 與 engine HTTP 目標支援 | 基本主機收集目標支援 | 獨立 provider 待研究，不承諾第一版完整 GPU 資料 | M3 候選 |
| Windows | 本次設計不作第一階段驗收承諾 | 不列入第一階段 | 不列入第一階段 | 後續另議 |

psutil 提供跨平台主機／程序介面，但欄位可用性與記憶體定義依 OS 而異，需採用 portable fields 並處理權限錯誤。資料來源：[psutil documentation](https://psutil.readthedocs.io/stable/index.html)。

Web 瀏覽器只是讀取 backend snapshot；瀏覽器所在 OS 不決定能收集哪台主機。M1 規劃驗收當期桌面 Chrome／Firefox／Safari，版本在實作時記錄。Mac 上的瀏覽器可查看 Linux backend，硬體數值仍屬於 Linux host。

NVIDIA 收集器依官方 NVML／nvidia-smi 定義取樣；溫度、功耗、MIG、程序 GPU 利用率等欄位不保證每個 device 都具備。資料來源：[NVML API](https://docs.nvidia.com/deploy/nvml-api/latest/index.html)、[nvidia-smi](https://docs.nvidia.com/deploy/nvidia-smi/index.html)。

Apple 官方的 Metal device memory／counter 及 Instruments 文件，主要描述應用程式或工具觀測能力。本規劃由此推論：外部通用 collector 的取得方式、權限與支援 OS 仍需 PoC。禁止將 Metal 某個 process 的記憶體數字當成整機 GPU 用量。資料來源：[Device inspection](https://developer.apple.com/documentation/metal/device-inspection)、[Metal developer tools](https://developer.apple.com/metal/tools/)。

## 4. 部署形式與資料範圍

| 部署形式 | 引擎資料怎麼取得 | 主機／GPU 資料怎麼取得 | 首輪邊界 |
| --- | --- | --- | --- |
| 本機 native process | 設定 localhost API／metrics | 同一 OS 上的 local collector | M1／M2 |
| Linux Docker／Compose | 暴露或明確配置可讀的 metrics URL | 優先 host collector；container 範圍須標記 | 不預設 docker exec／socket |
| Mac native＋Docker Desktop 混合 | 按實際服務端點讀取 | native Mac collector；VM／container 另列 | 不把 Linux VM 指標當 Mac host 指標 |
| 遠端 HTTP(S) | 設定遠端 API 與 metrics，獨立驗證憑證 | 同機 agent／既有 exporter，或顯示 N/A | M1 可讀引擎；M3 加遠端硬體 |
| Kubernetes | 指定 service／Pod metrics 或既有 Prometheus | node exporter／DCGM 等來源另做 profile | M3；不預設 cluster discovery |
| SSH | 可在遠端啟動 TUI 使用者自己的 shell session | 遠端程序直接使用 local collector | 不建立隱式 SSH shell collector |

Docker Desktop 的容器執行於 Linux VM，因此容器內的主機數字必須標明 VM scope。資料來源：[Docker Desktop networking](https://docs.docker.com/desktop/features/networking/)。

任何 engine、process、device 的關聯都需同一 host identity；沒有 GPU UUID／container／process 對應證據時，硬體僅展示 host/device 層，不自動歸屬到模型。

## 5. 請求來源與詳細請求的共通限制

Prometheus 彙總數值不包含完整 request id、client source 與每筆 scheduler 狀態。請求來源與請求清單需配置獨立事件來源，可採 client instrumentation、gateway callback、讀取已允許的日誌或 trace。

LiteLLM 官方提供 custom callback 路徑，可作候選事件產生來源；不以其內部 PostgreSQL 表或 Docker 容器名稱作 LLMTOP 的必備依賴。callback 的時間點、欄位與事件完整度仍需在固定版本確認。資料來源：[LiteLLM logging](https://docs.litellm.ai/docs/proxy/logging)。

逐筆 waiting 只有收到引擎 scheduler event 才可標成 engine waiting；gateway 收到、尚未回應的請求，只能標為 gateway inflight／unknown。來源 coverage 無法證明完整時預設 partial。

## 6. 正式支援版本的驗證規則

每個 backend profile 需記錄：引擎 release／commit、啟動 flags、OS／architecture、模型型態、原始 fixture、metric labels、取得方式、測試日期與限制。上游 `main`／`master`／`stable` 是本次研究來源，尚未成為鎖定的正式支援版本。

後續發布只能宣告完成 fixture 與真實部署驗收的組合。其他版本可做 capability detection 並降級顯示，但要保留「未驗證版本」標記。2026-10-03 已完成指定 VM 的 inventory 與上述 M1 實測；未測版本、平台及引擎不能沿用此結果宣稱相容。
