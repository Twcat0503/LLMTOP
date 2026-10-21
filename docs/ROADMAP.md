# 開發路線與驗收計畫

更新日期：2026-10-19。M0 文件已完成，M1 為可使用的 alpha 首版；llama.cpp 實機與 macOS gate 尚缺，M1 未全部驗收。公開證據見 [VALIDATION](VALIDATION.md)，近期項目見 [TODO](TODO.md)。

## M1：共用 MVP 與 TUI／Web

已建立 packages／固定依賴、snapshot、collector／rates／epoch／history、vLLM／llama.cpp adapters、host／NVIDIA providers、TUI、REST／SSE、React Web、once／doctor／schema 與 wheel。Linux 首輪已通過合成負載及真實 vLLM／NVIDIA 讀取。

2026-10-04 增加使用者安裝／PATH、裸指令 TUI、固定設定／初始化與 Web 啟動。2026-10-19 增加版本檢查、更新與 rollback（`llmtop update`／`rollback`）；來源由 `[update].source_url` 指定，無內建預設，驗收待實際發佈資產。

必要 gate：

- [ ] 固定 release／commit 的真實 llama.cpp metrics／slots。
- [ ] macOS host、TUI／Web 與 Mac 讀取 Linux remote engine。
- [ ] 真實引擎非零 rates 與持續負載。
- [ ] 正式 repository 執行 Linux／macOS、Python 3.11／3.14 CI。
- [ ] Firefox／Safari 與對應 OS 驗收。

每次驗證記錄來源版本／雜湊、OS／工具／引擎、命令、退出碼與限制。安裝及負載前重查磁碟／RAM；無對應硬體時保留未驗證。

## M2：引擎與請求

SGLang unified engine counters／queue／pool；Ollama loaded models 與既有請求 usage／timings；版本化 request event／JSONL、去重、rotation、late arrival、attempt correlation；匿名來源、生命週期與 partial coverage。TUI／Web 同步增加 Requests／Sources。Apple GPU 另做來源／權限／統一記憶體 PoC。

完成事件不等同 engine 即時吞吐或完整請求清單；gateway inflight 不等同 engine running／waiting。沒有可靠資料時保留 N/A。

## M3：遠端硬體與部署

Read-only agent／exporter 的身份、認證、TLS、clock skew；container／host／GPU UUID 與程序對應；Docker／Compose／Kubernetes profiles；跨機 Web 認證／反向代理；其他 GPU／engine／平台。每項經 fixtures 與實機證據後才宣告支援，目前維持 loopback＋SSH forwarding。

## M4：開源發佈

- [x] MIT、CONTRIBUTING、SECURITY、CHANGELOG 與 contributors。
- [x] Git／packaging 排除私人資料，公開文件使用通用例子。
- [x] 來源／wheel／sdist 檢查工具及 release 流程。
- [x] 本機 Git 基礎與 LF 規則；發布阻擋條件與驗證順序已整理。
- [ ] 正式 repository、私密回報管道與公開 CI。
- [ ] 完整 release assets／校驗值與首次公開發佈。
- [ ] 版本檢查、更新與 rollback 已實作（`[update].source_url`＋`SHA256SUMS`），待實際 release 資產驗收。

基礎版本保持 alpha；發佈前 gate 見 [RELEASING](RELEASING.md)。
