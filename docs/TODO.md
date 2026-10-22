# 目前狀態與開發代辦

更新日期：2026-10-22。版本 0.1.0，未發佈的 M1 alpha 基礎版本。共用 collector、snapshot／history、rate／epoch、vLLM／llama.cpp／Strata、host／NVIDIA、TUI／Web／API／CLI 已建立。證據見 [VALIDATION](VALIDATION.md)。

## 日常使用與更新

| 項目 | 狀態 | 驗收條件 |
| --- | --- | --- |
| U01 使用者安裝／PATH | 已實作並通過 Linux 驗收 | Wheel 隔離安裝、啟用前檢查；家目錄、其他目錄與新登入 shell 使用同版本，拒絕覆寫無關檔案 |
| U02 裸指令 | 已實作並通過 Linux 驗收 | llmtop 開 TUI；非 TTY 提示 once／Web；合成資料須 --demo |
| U03 設定／初始化 | 已實作並通過 Linux 驗收 | --config → LLMTOP_CONFIG → 使用者設定 → 舊 cwd；init 不覆寫，不同目錄讀同一固定設定 |
| U04 Web 啟動 | 已實作並通過 Linux 驗收 | web／serve、--open／--no-open；成功啟動後開瀏覽器，SSH／headless 列 URL／forwarding |
| U05 官方來源／版本檢查 | 已實作，待驗收 | `[update].source_url` 指定 HTTPS release 下載基底，抓 `SHA256SUMS` 解析 wheel／constraints；版本比較預設跳過 prerelease |
| U06 更新／復原 | 已實作，待驗收 | `llmtop update` 原子切換環境、保留前版並提示重啟；`llmtop rollback` 還原；下載、校驗或檢查失敗維持現行版本 |

U05／U06 命令已存在，但無內建預設來源；未設定 `[update].source_url` 時不進行任何遠端檢查，也不把任意索引的同名套件視為官方來源。驗收需實際 release 資產與隔離環境重驗。

## 本次 Strata 適配器收尾（2026-10-22）

| 項目 | 狀態 | 結果 |
| --- | --- | --- |
| S01 CI run #6 失敗根因 | 已修復 | `tui.py` 引擎篩選列未過 `ruff format --check`；已格式化，本地 CI 四步驟全過 |
| S02 Strata 單元測試 | 已完成 | 去敏 fixture `tests/fixtures/strata.prom`（取自 0.1.44.1 實機）＋4 項測試；pytest 89 passed |
| S03 README 快速開始範例 | 已修正 | 兩個 README 的 `[[hosts]]`／`[[services]]` 範例補上必填 `label`（原範例會被設定驗證擋下） |
| S04 Strata 實機驗證 | 已完成 | 端點行為逐項相符；端到端五指標 OK、語意與 model 識別正確；短暫非零吞吐樣本與請求 usage 一致。範圍與限制見 VALIDATION 同日紀錄 |
| S05 CI 轉綠 | 待推送後確認 | 修復推送後以實際 run 結果為準，未通過前不得宣稱 V04 |

持續非零負載（V03 範圍）、llama.cpp 實機（V01）、macOS（V02）、Firefox／Safari（V05）與首次發布（G05）不受本次影響，維持原狀。

## 本次 Git／發布收尾（2026-10-04）

本次範圍為 0.1.0 alpha 的本機 Git 與發布條件核對，不擴大為 M2–M4 實作，也不自行選定公開帳號或官方套件來源。

| 項目 | 狀態 | 結果／阻擋條件 |
| --- | --- | --- |
| G01 本機 Git 基礎 | 已完成 | 公開來源納入 main 初始提交；私人原型、設定與內部紀錄保持 ignore；以 .gitattributes 固定 LF |
| G02 既有驗證對應 | 已核對 | Runtime／tests／frontend／scripts 與先前 VM 的 SHA-256 清單一致；既有 wheel／sdist 校驗值吻合，不代表本次重新測試 |
| G03 本次遠端重驗 | 受阻 | 指定節點在線，SSH 非互動認證失敗；需恢復合法認證後在指定測試根目錄重新驗證，不以 Windows runtime 代替 |
| G04 正式 repository／官方來源 | 待維護者確認 | 尚無 remote；需確認 repository URL、公開範圍、MIT 貢獻權利與私密回報管道 |
| G05 CI／首次發布 | 受阻 | G03／G04 完成後 push、取得實際 CI 結果、依同一 commit 重建並審查安裝包，再建立 tag／release／校驗值 |

本次未 push、未建立版本 tag、未公開 release，也未上傳 PyPI。既有安裝包早於本次文件／Git 設定修訂，僅作歷史驗證產物，不作新 commit 的發布資產。未驗收與延後項目維持未完成；不得為清空 TODO 而勾選。

## 開源基礎準備

- [x] MIT、package metadata、contributors、CONTRIBUTING、SECURITY、CHANGELOG。
- [x] Git／package 排除私人原型、工作站指令、內部環境／驗收／盤點、設定、憑證、raw telemetry、cache／build。
- [x] 公開文件與驗證摘要不依賴私人操作文件。
- [x] 來源／wheel／sdist 審查工具及 release 流程。
- [x] 本次 71 項 Python、6 項 Chromium、安裝／PATH／設定／TUI／Web 與包檢查通過；見公開驗證摘要。
- [ ] 正式 repository URL、私密回報、實際 CI 與首次 release。

## M1 剩餘驗收

- [ ] V01 真實 llama.cpp 固定版本、flags、OS、metrics／slots 與去敏 fixtures。
- [ ] V02 macOS host／TUI／Web、Mac 讀 Linux engine；Apple GPU 深度資料另列 M2。
- [ ] V03 真實非零 throughput／reset／gap／持續負載；目前真實採樣為 idle，非零時序由合成資料驗證。
- [ ] V04 正式 repository 的 Linux／macOS、Python 3.11／3.14 portable CI。
- [ ] V05 Firefox／Safari 及對應 OS。

M2–M4 引擎／請求／來源／Apple GPU／remote agent／container mappings／跨機 Web／其他平台仍未完成。詳見 [ROADMAP](ROADMAP.md) 與 [METRIC-SPEC](METRIC-SPEC.md)。
