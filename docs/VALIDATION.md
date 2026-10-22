# 公開驗證摘要

此文件只保留可公開的環境、方法、結果與限制。連線身份、私有端點、原始遙測及完整內部紀錄不隨專案發佈。

## 2026-10-03 M1 首版

Ubuntu 26.04 LTS／x86_64、Python 3.14.4、Node 24.18.0 的固定依賴及 Python／Web 建置通過。45 項 Python 與 6 項 Chromium 測試通過；TUI 為 80×24／120×40，Web 為 1505×1045／1024×768／375×812。

30 分鐘合成 collector 測試使用 10 個 MockTransport 來源、2 秒週期與 300 筆 history。900 次 snapshot、18,000 次 GET 一致，API clients 沒有增加 scrape。history 填滿後 RSS 約 158.8 MiB，未持續增長；這不能當成十個真實引擎的壓力測試。

真實 vLLM 0.29.0 的 counters／rates／running／waiting／native KV ratio 與 NVIDIA NVML device fields 已讀取成功。真實採樣為 idle，沒有發推論探測。fixture 覆蓋非零差分、reset／gap、labels、重複 series、timeout／auth、malformed、缺項及 GPU hang。

## 2026-10-04 日常使用與發佈準備

本次在指定 Linux VM 執行，Ubuntu 26.04 LTS／x86_64、Python 3.14.4、Node 22.22.1、npm 9.2.0。安裝、cache、測試與產物均在隔離目錄；工作站只負責編輯及靜態檢查。

| 驗證 | 結果／退出碼 | 範圍 |
| --- | --- | --- |
| 固定依賴、Ruff check／format | 0 | Runtime、CLI、installer、release audit 與 tests |
| pytest | 71 passed／0 | 原有 45 項及設定順序、初始化權限／拒絕覆寫、非 TTY、Web／browser failure、安裝失敗保留舊環境、私人資料／連結與版本審查 |
| npm ci／build、uv build | 0 | 同來源 Web，sdist → wheel，包含 Web／設定 template／MIT |
| source／wheel／sdist audit | 0 | 私人文件與機器資訊不入公開候選檔；package metadata／Python／Web 版本一致 |
| 使用者安裝、新登入 shell | 0 | 家目錄、其他目錄及專案目錄找到同一版本；固定設定一致，原有設定保留 |
| 裸指令 TUI／非 TTY | 0／2 | 真正 PTY 啟動與 q 結束；非 TTY 的 2 為預期提示退出碼 |
| 安裝包 Web／headless／SIGINT | 正常／130 | Loopback 頁面及 assets、啟動後 URL／forwarding；130 為 Ctrl+C 的預期退出碼 |
| Chromium、connected TUI | 6 passed／0 | 三種尺寸、同 runtime／snapshot 的 Web history 與 TUI 值一致 |

程式來源以 SHA-256 清單記錄，程式／測試／frontend 清單的彙總值為 `dff1bc3649bcfce35a840ea8219f4c36ce0f5bbf9bb8e8e9737a4f9310968df3`。來源尚無 Git commit；此值不包含公開文件與打包設定，打包另以 archive SHA-256 查核。

桌面自動開瀏覽器與失敗分支由單元模擬驗證；指定 VM 實測的是 SSH／headless 與 Chromium，不代表 macOS 桌面驗收。前次長測未因 CLI／打包變更重跑，不擴大其宣告範圍。

## 2026-10-04 Git／發布狀態核對

本次核對 runtime、tests、frontend 與 scripts 檔案的 SHA-256，與上述 Linux VM 的程式清單一致；既有 wheel／sdist 的 SHA-256 亦與先前驗證紀錄吻合。另執行 Windows 上的來源靜態檢查，確認公開文件連結與私人檔案排除；這些不是 Linux runtime 測試。

指定遠端節點在線，但非互動 SSH 認證失敗（退出碼 255），因此本次沒有重新執行 pytest、frontend build、安裝或實機測試。本機 Git 基礎已建立；尚無 remote、版本 tag、公開 CI 結果或 release。既有包不包含本次文件／Git 修訂，發布前必須由確認的 commit 重新建置。

## 2026-10-22 Strata 適配器實機驗證

本次在 research-u 本機執行，Ubuntu 24.04.4 LTS／x86_64、Python 3.12.3（uv 固定依賴）。被監控端為本機運行的 Strata server 0.1.44.1（單槽位、262 K context、RTX 5070），LLMTOP 為未發佈的 main 工作區。

端點行為與 2026-10-21 之文件核對逐項相符：`/metrics` 預設 JSON，`Accept: text/plain` 或 `?format=prometheus` 得 vLLM 命名且帶 `model_name` 的文字格式；`/metrics/prometheus` 為 `llamacpp:*` 命名無 label；`/health` 恆 200 附 `loaded`；`/slots` 為 llama.cpp 風格；`/metrics` 與 `/slots` 需 bearer，`/health` 不需要。

LLMTOP 端到端（`doctor`、`once --json`）：health REACHABLE、model 名稱自動識別、五個映射指標全 OK、`kv_cache_usage_ratio` 標記為 `native_context_share`、`slot_states` 為 conditional。發送一筆 150 token 完成請求後，15.03 秒視窗測得 input_tps 3.99／output_tps 9.98，與該請求 usage（60／150 tokens）一致；生成中另測得 running＝1 與非零 context 佔用比（0.0008／0.0025）。因 Strata counters 僅於完成時累計，rate 僅在完成事件落入視窗時非零——此為文件語意的實測確認。

去敏 fixture（model 名稱代換、gauge 由 idle 值上調）入 `tests/fixtures/strata.prom`；新增 4 項 Strata 單元測試（映射與語意、Accept 協商、vLLM 預設 Accept 不變、JSON 未協商時回報 ERROR），pytest 89 passed。CI 失敗之根因為 `tui.py` 一列未過 `ruff format --check`，已修正。

限制：僅 Strata 0.1.44.1、單機單槽位、短暫負載而非持續負載；未測 macOS、多 replicas 與 HTTP(S) 憑證路徑。

## 未覆蓋

真實 llama.cpp、macOS／Apple GPU、真實非零持續負載（Strata 已於 2026-10-22 取得短暫非零吞吐樣本，持續負載仍未做）與 Firefox／Safari 尚未通過；正式 GitHub CI 已於 2026-10-22 在 `49439ba` 全矩陣轉綠。M1 未全部驗收；檢查與發佈 gate 見 [RELEASING](RELEASING.md)。
