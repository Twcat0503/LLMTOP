# TUI 與 Web 同步規劃

規劃日期：2026-10-02。2026-10-03 已實作 M1 TUI／Web、REST／SSE 與 bounded history；requests／sources 頁面仍屬 M2。操作方式見 [README](../README.md)，測試結果見 [M1 紀錄](VALIDATION.md)。

## 1. 同步交付原則

使用者已指定 TUI 與 Web 同步規劃。首個可用版本需同時完成兩端的服務表、硬體表、趨勢、篩選、錯誤／N/A 與 freshness；下一個里程碑同時增加請求與來源資料。

兩種介面讀取同一資料契約。相同 runtime／snapshot sequence 的值、單位、來源與品質狀態必須相同。t/s、percent、request lifecycle、來源排行與 cache semantics 都在 backend 定義。

| 資訊／互動 | TUI | Web |
| --- | --- | --- |
| 總覽 | 頂部 host／service 狀態列 | overview cards＋連線狀態 |
| 服務指標 | 可排序表格＋詳情分頁 | 可排序表格＋service 詳細頁 |
| 主機／GPU | host/device 表格 | host/device 卡片與表格 |
| t/s、KV、waiting 趨勢 | sparklines＋數值 | 時間曲線與 tooltip |
| 請求／來源（M2） | request／source 分頁 | request table／source ranking |
| 篩選 | host／engine／model、文字搜尋 | 共用相同 filter dimensions |
| N/A／stale | 文字 badge＋原因面板 | badge＋原因說明 |
| 暫停顯示 | 畫面標示 paused，collector 繼續 | 畫面標示 paused，collector 繼續 |
| 最新連線 | local／connected runtime 狀態 | API／SSE 連線、重連與最後 snapshot |

## 2. TUI 版面與操作

預設顯示總覽、服務、硬體與趨勢。80×24 終端採分頁；120×40 可呈現更多區塊。中文寬度、ASCII 與 light／dark 模式列入驗收。

規劃快捷鍵：q 離開介面、space 暫停／恢復顯示、tab 切換區域、方向鍵選取、enter 查看詳細、/ 搜尋、s 切換排序、? 說明。連接共用 backend 時，退出 TUI 不停止 Web collector。

程序與 GPU 關聯不足時，顯示 host/device 資料及原因；來源未設定時，請求區呈現取得方式與 coverage 狀態，不能用空表暗示沒有流量。

## 3. Web 資訊架構

| 視圖 | 第一版內容 |
| --- | --- |
| Overview | 服務健康、有效 throughput、running／waiting、硬體摘要與近期趨勢 |
| Services | backend／model／host 篩選、完整服務指標、能力缺項 |
| Service detail | metric 來源、scope、window、epoch、版本 profile 與趨勢 |
| Hosts | CPU／RAM／swap、device 表、container／VM／host scope |
| Requests（M2） | 可觀察 request／attempt、時間、來源、生命週期；可用時顯示 tokens |
| Sources（M2） | 匿名 source、觀察 usage、完成／失敗數、視窗與 coverage |

每個狀態都以文字呈現，不能只靠紅綠顏色。圖表缺資料時保留 gap，滑鼠／鍵盤可查詢單位、原始來源與時間。窄視窗將表格改為重點欄位＋詳細頁，不把必需資訊截斷。

Web 已採 React＋TypeScript＋Vite，backend 提供同 origin 的打包靜態檔與 API。開發 Vite server 的 origin 如需讀取 API，須在設定中明確加入 allowed_origins；預設驗收使用 `npm run build` 與 backend。資料來源：[React](https://react.dev/learn)、[Vite](https://vite.dev/guide/)。

## 4. HTTP API 草案

以下 M1 路徑已提供實際 server；M2 路徑仍為規劃。API 只讀取 collector store，不因瀏覽器數增加 engine scrape。

| Method／path | 回傳／用途 | 階段 |
| --- | --- | --- |
| `GET /health` | LLMTOP runtime 本身是否可用；不等同所有 LLM 健康 | M1 |
| `GET /api/v1/snapshot` | schema version、runtime id、snapshot seq、host／service metrics 與來源狀態 | M1 |
| `GET /api/v1/capabilities` | 指定 service／host 的欄位能力、版本與限制 | M1 |
| `GET /api/v1/history` | 指定已登錄 id、metric、視窗的有上限樣本 | M1 |
| `GET /api/v1/events` | SSE snapshot 更新、heartbeat、reset | M1 |
| `GET /api/v1/requests` | cursor 分頁的可觀察 requests／attempts 與 coverage | M2 |
| `GET /api/v1/sources` | 指定視窗的來源摘要與有效統計範圍 | M2 |

查詢僅接受已登錄的 id、允許的 metric、範圍受限的 window／limit。filter 組合與 schema version 由 TUI 和 Web 共用。公開 response 不包含環境變數值、完整內部 config、原始 headers、prompt／response 或 API keys。

一般 engine 故障寫入其 observation status，snapshot API 仍可成功回傳其他健康服務。API 自身無有效 snapshot 時需明確呈現初始化／runtime failure，避免誤解為 LLM 全部 offline。

## 5. 更新、重連與一致性

Web 首次以 REST 取得 snapshot，再以 SSE 取得更新。connected TUI 可使用相同流程；SSE 不可用時依 2 秒可調頻率讀取既有 snapshot，不能將 fallback polling 轉成額外 engine scrape。

SSE event id 使用 runtime id＋snapshot seq。sequence 只在同一 runtime 有意義；backend 重啟或 client cursor 超過可重播視窗時，發出 reset，client 重新取 snapshot。client 丟棄過時 sequence，保留明確 reconnecting／stale 狀態。

第一版推送 compact snapshot 摘要，不每 2 秒重送完整請求歷史。請求與長視窗趨勢由分頁／限量 API 取得。每個 client queue 有上限，慢 client 可略過中間 snapshot 或重連，不阻塞 collector。

SSE 是單向更新，符合讀取型儀表板的需要；未規劃停止請求或修改 LLM 狀態。框架與通訊依據：[FastAPI](https://fastapi.tiangolo.com/)、[MDN SSE](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)。

## 6. 本機與遠端使用邊界

M1 Web 預設 `127.0.0.1:8787`，本機單一使用者；TUI 仍可獨立運行。只查看遠端 engine，不會自動將 Web server 暴露到外網。

跨主機查看 Web 屬 M3 部署模式：需明確啟用 remote、驗證身份並使用 TLS reverse proxy。engine credentials 始終在 server；若使用 bearer，禁止放在 URL 或 browser local storage。瀏覽器 stream 可採同 origin HttpOnly session；本機 token 交換方式於遠端階段具體化。

M1 以同 origin 與明確 Host／Origin 驗證為設計方向，不開 wildcard CORS。API 不接受由瀏覽器提供任意 metrics URL；所有來源在設定檔登錄。

## 7. 共同驗收場景

1. 相同 snapshot fixture 在 TUI／Web 顯示一致的 input／output t/s、tokens、KV 與 counts。
2. 一個服務 timeout，兩端均顯示原因；其他服務繼續刷新。
3. counter reset 時兩端都先 warming_up，沒有巨大吞吐尖峰。
4. 缺少 KV／來源／逐筆 request 時，兩端以相同理由呈現 N/A，不能用 0 替代。
5. Web SSE 斷線後重連、backend 重啟、慢 client 都不導致重複 counter／event 計算。
6. 同時開 TUI、Web 與第二個 browser client，scrape 次數維持由 collector 週期決定。
7. 原始 credential 不出現在 API response、Web assets、client console 或 TUI diagnostic output。
8. TUI 80×24／120×40；Web 1024×768 桌面與 375px 窄視窗檢查布局、鍵盤操作與圖表 gap。

M1 已以 Textual pilot、真實 SSH PTY、IAB 與指定 VM 的 Chromium 驗證。已覆蓋 80×24／120×40 TUI 與 1505×1045／1024×768／375×812 Web；完整結果與限制見 [M1 紀錄](VALIDATION.md)。
