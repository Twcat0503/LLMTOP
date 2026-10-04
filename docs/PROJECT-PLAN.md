# LLMTOP 專案規劃

日期：2026-10-02（Asia/Taipei）

狀態：M0 規劃已完成；2026-10-03 已建立 M1 首版，實作與 gate 狀態見 [驗證紀錄](VALIDATION.md)。M2–M4 仍為後續範圍。

2026-10-04 更新：日常使用功能與開源基礎準備已建立，操作與公開驗證摘要見 README。

## 1. 專案目的

讓操作本機或自管 LLM 的使用者，在同一個儀表板看見：服務是否可連線、token 吞吐量、KV／記憶體是否緊張、硬體負載、請求從哪裡進來，以及正在執行或等待的請求。

第一階段以個人開發者與小型自管部署為主要情境。支援數個服務、不同引擎、不同機器，避免把監控資料來源綁死在某台主機、Docker 容器名稱或資料庫 schema。

本文件保留整體產品計畫；目前實作聚焦 M1 的共用 collector、TUI／Web 與兩個優先 adapters。逐筆請求／來源、其他引擎、remote agent 與公開發佈依後續里程碑進行。

## 2. 使用情境

| 情境 | 使用者需要判斷的事情 | 最低資料條件 |
| --- | --- | --- |
| Linux GPU 主機部署多個模型 | 哪個服務排隊、哪張 GPU 負載高、KV 是否接近上限 | 引擎 metrics＋同主機硬體收集器 |
| Mac 本機執行 llama.cpp／Ollama | 模型是否可用、生成速度、CPU／記憶體壓力 | 本機 API＋macOS 主機收集器；部分用量需請求事件 |
| Mac 監看 Linux 遠端 vLLM | 推論服務狀態與吞吐；可選遠端硬體資料 | 遠端 metrics；硬體另需同機 agent／exporter |
| 推論服務位於 Docker／Compose | 對應 service、container、host、GPU，避免看錯資源範圍 | 明確端點＋主機／容器資源範圍標記 |
| 請求經 LiteLLM 或其他 gateway | 哪個 application／client 使用最多 tokens，請求是否仍在處理 | gateway 事件或允許的日誌，含 request correlation |

## 3. 功能需求與落地順序

| 編號 | 需求 | 規劃階段 | 驗收重點 |
| --- | --- | --- | --- |
| F01 | 設定多台主機、多個部署與模型識別 | M1 | 不需修改程式內固定清單 |
| F02 | 顯示 input／output t/s 與累積 tokens | M1；Ollama 在 M2 | 標明 engine processed／request usage 與時間範圍 |
| F03 | 顯示 running／waiting 數量 | M1 | 原生 scheduler counts；缺項不能補成 0 |
| F04 | 顯示 KV 使用率與容量 | M1 起依能力啟用 | 比率、token slots、bytes、context 分開呈現 |
| F05 | 顯示 CPU、RAM、swap、GPU 與記憶體 | M1／M2 | 主機與容器、獨立 VRAM 與統一記憶體分清楚 |
| F06 | 顯示請求來源與來源用量排行 | M2 | 明確事件來源、覆蓋率與匿名化方式 |
| F07 | 顯示可觀察的逐筆請求與生命週期 | M2 | gateway inflight 與 engine running 不混用 |
| F08 | 顯示最近趨勢、離線與資料陳舊狀態 | M1 | 單一端點故障不拖停整個儀表板 |
| F09 | 同步提供 TUI 與 Web，另提供一次性／JSON 輸出 | M1／M2 | 兩種 UI 的數值、單位、狀態與更新來源一致 |
| F10 | 遠端主機硬體與更多部署形式 | M3 | agent／exporter 必須位於正確主機 |

M1 是首個可用版本；M2 才完成第一波所有可觀察需求。各引擎資料能力不同，不能把四種部署都描述為同等完整。

## 4. 畫面規劃

使用者已指定 **TUI 與 Web 同步規劃**。兩種介面共用以下資訊架構，並在相同里程碑驗收。TUI 使用表格與分頁；Web 使用總覽、表格、趨勢與詳細頁，兩端不各自推算指標。

| 區域 | 顯示內容 | 預計互動 |
| --- | --- | --- |
| 總覽 | 主機／服務數、freshness、監控範圍、錯誤提示 | 依 host／engine／model 篩選 |
| 服務表 | engine、model、健康、input／output t/s、tokens、running、waiting、KV | 選取服務、排序、查看來源與計算方式 |
| 硬體表 | host CPU／RAM／swap；device GPU utilization／memory／溫度／功耗 | 切換主機；缺能力顯示原因 |
| 趨勢 | output t/s、waiting、KV 的近期樣本 | 暫停畫面；樣本缺口不補 0 |
| 請求表 | request id、source、model、觀察狀態、已經過時間、可取得的 tokens | 只有事件／slot 證據時顯示 |
| 來源排行 | source id、觀察請求數、input／output usage、錯誤 | 顯示 partial／complete coverage |

窄終端採分頁；規劃驗證至少 80×24 與 120×40。顏色只作輔助，保留文字狀態、ASCII fallback 與中英文寬度處理。

服務健康至少區分 reachable、loading、degraded、unreachable、auth_error、unknown。`/v1/models` 回應成功只證明 API 可達，不能直接宣告引擎已就緒。

## 5. 暫定技術決策

| 決策 | 暫定方案 | 理由／待驗證事項 |
| --- | --- | --- |
| 語言 | Python 3.11+ | 延續既有原型；以 TOML 標準函式庫與非同步收集為基礎 |
| TUI | Textual／Rich | 表格、趨勢、鍵盤操作與終端尺寸調整 |
| Web | React＋TypeScript＋Vite | 共用 snapshot 型別；元件化呈現總覽、表格與趨勢 |
| Web API | FastAPI；REST snapshot＋SSE | API 提供已收集的狀態，SSE 推送更新；斷線可重新讀 snapshot |
| HTTP | HTTPX async | 共用連線、明確 timeout、受限併發；不用阻塞 UI |
| 主機指標 | psutil＋平台 provider | 跨 Mac／Linux 的基本 CPU／RAM／程序觀測；GPU 獨立處理 |
| Metrics | Prometheus exposition parser | 依 metric family、labels 與型別解析；避免以零值掩蓋缺項 |
| 設定 | TOML＋環境變數憑證引用 | 把 deployment inventory 與機密分離 |
| 儲存 | 有上限的記憶體 ring buffer | 第一版不要求外部資料庫；明確保留期間 |
| 遠端 host agent | 後續傳輸介面 | Web API 與 host agent 用途分開；遠端硬體在 M3 擴充 |

框架依據：[Textual](https://textual.textualize.io/)、[HTTPX](https://www.python-httpx.org/)、[psutil](https://psutil.readthedocs.io/stable/index.html)、[FastAPI](https://fastapi.tiangolo.com/)、[React](https://react.dev/learn)、[Vite](https://vite.dev/guide/)。M1 已依此建立程式，依賴固定於 `uv.lock` 與 `frontend/package-lock.json`，指定 VM 的實測結果見 [驗證紀錄](VALIDATION.md)。

## 6. 非功能需求

- 預設每 2 秒取得服務與主機資料，刷新頻率可調；慢端點受 timeout 與 concurrency 上限控制。
- 預設不做推論探測，不為了取得 t/s 發出生成請求；收集既有 metrics、slots、模型清單或已授權事件。
- TUI、Web 與非互動輸出使用相同資料；JSON 包含單位、來源與品質狀態。
- Web 預設只綁定 loopback，讀取伺服器側設定的來源；引擎憑證不送入瀏覽器。
- 預設不需要 root、Docker socket、資料庫管理員或 SSH shell。
- 普通主機指標可用時，GPU 或某個引擎失敗不影響其他區塊。
- 目標支援 Linux x86_64／arm64、macOS Apple Silicon；Intel Mac 另列實際可測範圍。
- MVP 預估以 1–10 個 service／30 分鐘持續運行作負載驗收；先取得基準再訂監控開銷門檻。

## 7. 第一階段以外的範圍

Windows 原生 collector、完整 Kubernetes 自動探索、模型下載／部署、訓練監控、排程控制、停止請求、多租戶帳務、完整 prompt／response 保存、長期時序資料庫與公開 Web 服務，均不列入首個可用版本。

MLX-LM、LM Studio、Triton／TensorRT-LLM、其他 OpenAI-compatible server 為候選擴充。每項需先確認可讀取的觀測介面，再決定支援等級；只有 chat API 相容不代表能取得 KV 或 scheduler 資料。

## 8. 待確認決策

1. Ubuntu 26.04／Python 3.14.4 的固定依賴、真實 vLLM／NVIDIA 已實測；llama.cpp 與 macOS gate 尚缺。
2. 請求來源希望以 application／匿名 client id 為主，還是需要授權顯示 IP。
3. Web 首輪以本機單一使用者為主；跨機器存取的認證／TLS 部署方式在遠端階段確認。
4. 已選 MIT 與 LLMTOP contributors；正式 repository、聯絡方式與貢獻來源需在公開前確認。

這些項目已留下調整位置，不影響本次完成規劃。實作順序與具體 gate 見 [開發路線](ROADMAP.md)。

## 9. 開發環境與下一步

Linux／macOS 使用固定依賴建置與測試；其他 OS 可進行編輯與靜態檢查。每次驗證記錄來源版本／雜湊與環境範圍，不以其他機器的結果替代實機 gate。

操作見 [README](../README.md)，開發見 [CONTRIBUTING](../CONTRIBUTING.md)，公開檔案與包檢查見 [RELEASING](RELEASING.md)。
