# 指標與資料契約草案

規劃日期：2026-10-02。2026-10-03 已建立 M1 程式模型與 vLLM／llama.cpp parser；本文件的 request／source、其他引擎與深度硬體欄位仍屬後續範圍。實際 schema 由 `llmtop schema` 產生，驗證見 [M1 紀錄](VALIDATION.md)。

## 1. 共通觀測欄位

每筆 metric observation 都需保留以下資訊；TUI、Web、JSON 不自行補值或改變定義。

| 欄位 | 意義 |
| --- | --- |
| `host_id`／`service_id`／`model_id`／`device_id` | 可穩定關聯的資料維度；沒有證據的關聯留空 |
| `metric`／`value`／`unit` | 指標名稱、值與單位；無有效值時 `value=null` |
| `status` | `ok`、`warming_up`、`no_data`、`unsupported`、`unavailable`、`permission_denied`、`error`、`stale` |
| `source_kind`／`source_metric` | engine metrics、slot、host provider、gateway event 等原始來源 |
| `measurement_kind` | `observed`、`derived`、`estimated`；推估值不能冒充原生值 |
| `scope`／`aggregation` | host、device、engine、model、request；sum、max、none 等計算方式 |
| `observed_at`／`last_success_at` | UTC RFC3339 時間；畫面可依使用者時區顯示 |
| `window_seconds`／`source_period_seconds` | LLMTOP 計算視窗與上游自身更新週期 |
| `epoch`／`semantics` | counter 世代、重啟識別與 token／cache 統計定義 |
| `coverage`／`reason` | complete、partial、unknown；無資料或降級原因 |

snapshot 層另保留 schema_version、runtime_id、snapshot_seq 與 collected_at；runtime_id 改變後，sequence 不可跨程序世代比較。

首次 counter 樣本為 warming_up；缺欄位為 unsupported／no_data；成功測得的 0 才是 0。端點 timeout 是 unavailable。品質狀態與服務健康分開，一個服務可仍可用但 metrics 已 stale。

## 2. Tokens 與 t/s

| 指標 | 單位 | 定義與範圍 |
| --- | --- | --- |
| `engine_prompt_tokens_total` | tokens | 引擎原生 prompt／prefill counter；保留是否含 cached tokens 的定義 |
| `engine_generation_tokens_total` | tokens | 引擎原生 generation counter；draft／accepted tokens 若分開提供，保留不同欄位 |
| `input_tps`／`output_tps` | tokens/s | 同一 counter 序列在 LLMTOP 視窗內的差分除以實際經過時間 |
| `request_input_tokens`／`request_output_tokens` | tokens | 單筆回應 usage；通常在完成時取得，可能包含 cached prompt tokens |
| `observed_request_input_tokens_total`／`observed_request_output_tokens_total` | tokens | 已觀察請求 usage 的合計；標示自啟動／保留視窗與 partial coverage |
| `request_decode_tps` | tokens/s | 單筆 output tokens 除以原生 decode duration；只在確有 timing 時提供 |
| `completion_input_tps`／`completion_output_tps` | tokens/s | 視窗內收到的完成事件 usage 除以視窗時間；不代表當下 engine 吞吐 |

`input_tps = Δengine_prompt_tokens_total / Δmonotonic_seconds`。output 同理。預設顯示短視窗與最近 60 秒趨勢；同一 service 先對每個獨立 series 計算，再按 backend profile 合併。

不能把 engine processed counters 與 request usage counters 相加；二者可能統計同一批 tokens，也可能有不同 cache 語意。total tokens 只有在相同 scope／epoch／basis 的 input 與 output 均有效時才可相加。

Ollama 單筆 decode t/s 可用 `eval_count / (eval_duration / 1e9)`；串流 final chunk 才有完整 usage。prefill timing 可能只對應未快取 tokens，需核對 `prompt_eval_cached_count` 與版本定義後才計算。資料來源：[Ollama usage](https://docs.ollama.com/api/usage)。

SSE／HTTP chunk 數不是 token 數；多個 token 可在同個 chunk，沒有 usage 時不能用 chunk count 代替。單筆 decode t/s、服務 output t/s、完成事件 t/s 在畫面上分開命名。

### 差分與重啟規則

1. 相鄰樣本必須是同一 source、完整 label set、metric semantics 與 epoch。
2. elapsed time 使用 monotonic clock；不以固定刷新間隔假設實際時間。
3. counter 下降、程序 start time 改變、replica／series 改變時重新建立基準。只有 counter 單調不足以排除重啟，優先使用 start time／instance identity。
4. 首次、重啟與斷線恢復後首個樣本不以「當前 counter 除以 2 秒」建立尖峰，也不把負 delta 截成 0 當作正常資料。
5. 輪詢失敗不覆蓋最後成功樣本的時間；gap 超過 freshness 限制時，當前 rate 標示 N/A 並重新取基準。
6. 不跨不同 model_name、engine id、DP replica、TP rank 或 scrape endpoint 直接相加；duplicate replicas 只選擇權威 series。
7. histogram `_count` 是該 histogram 的事件數，不自動等同 received requests。completed／successful／failed／received counts 分別定義。

## 3. 原生欄位映射候選

實作時需用固定 release 的 raw fixture 驗證名稱、labels、型別與統計範圍。同時出現 alias 時只能選一個，不能累加。

| 引擎 | 正規化目標 | 已核對的原生欄位／候選 |
| --- | --- | --- |
| vLLM | prompt／generation totals | `vllm:prompt_tokens_total`、`vllm:generation_tokens_total`；官方表也使用沒有 suffix 的 family 名稱 |
| vLLM | running／waiting | `vllm:num_requests_running`、`vllm:num_requests_waiting` |
| vLLM | KV ratio | `vllm:kv_cache_usage_perc`（0–1） |
| llama.cpp | prompt／generation totals | `llamacpp:prompt_tokens_total`、`llamacpp:tokens_predicted_total` |
| llama.cpp | running／waiting | `llamacpp:requests_processing`、`llamacpp:requests_deferred` |
| Strata | prompt／generation totals | `vllm:prompt_tokens_total`、`vllm:generation_tokens_total`（皆帶 `model_name` label；僅計已完成請求） |
| Strata | running／waiting | `vllm:num_requests_running`、`vllm:num_requests_waiting` |
| Strata | context 佔用比 | `vllm:kv_cache_usage_perc`＝執行中請求的 context 佔用（0–1），名稱沿用 KV 但語意不同，展示需標為 `native_context_share` |
| SGLang | prompt／generation totals | `sglang:prompt_tokens_total`、`sglang:generation_tokens_total` |
| SGLang | running／waiting | `sglang:num_running_reqs`、`sglang:num_queue_reqs`；grammar／PD queues 另列 |
| SGLang | pools | `sglang:full_token_usage`、`sglang:token_usage`、`sglang:kv_used_tokens` 等，依版本能力啟用 |
| Ollama | request usage／timings | `prompt_eval_count`、`eval_count`、`eval_duration`；沒有引擎 counter 的通用替代 |

資料來源：[vLLM metrics design](https://docs.vllm.ai/en/stable/design/metrics/)、[vLLM production metrics](https://docs.vllm.ai/en/stable/usage/metrics/)、[llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)、[SGLang metrics](https://github.com/sgl-project/sglang/blob/main/docs/docs/references/production_metrics.mdx)、[SGLang collector](https://github.com/sgl-project/sglang/blob/main/python/sglang/srt/observability/metrics_collector.py)、[Strata serve/prometheus.py](https://github.com/Niko1221/Strata/blob/main/serve/prometheus.py)。

llama.cpp 的 throughput gauges 與 LLMTOP counter rate 不一定具有相同時間視窗；如果保留，名稱需標為 native throughput。slots 採樣只能補充 live state，不能作為完整累積 token counter 的主要來源。

## 4. KV、context 與記憶體

| 指標 | 定義 | 不可混用的資料 |
| --- | --- | --- |
| `kv_cache_usage_ratio` | 指定 KV pool 的使用比率（0–1），UI 乘 100 顯示百分比 | GPU memory utilization、context 占比 |
| `kv_used_tokens`／`kv_capacity_tokens` | 同一 pool 的 token slots 用量／容量 | 單筆 context limit、服務 max_model_len |
| `kv_cache_bytes` | backend 直接提供，或有完整模型布局與配置時的明確估計 | 以 KV ratio 乘整張 GPU VRAM |
| `memory_pool_usage_ratio` | backend 定義的 pool 使用或瓶頸比率 | 自動把 SSM／Mamba 狀態稱為 KV |
| `context_tokens_used`／`context_limit_tokens` | 單筆請求／slot 的可確認 context 資訊 | 全服務實際 KV residency |
| `gpu_memory_used_bytes` | device／process provider 定義的記憶體使用 | model weights＋KV 的任意推測拆分 |

SGLang 當期原始碼的 `token_usage` 包含多種 pool；新 profile 可提供 full-attention／SWA／SSM 欄位，且保留 pool identity。舊 profile 不具備相同語意時，僅展示 native memory pool usage。資料來源：[SchedulerStats](https://github.com/sgl-project/sglang/blob/main/python/sglang/srt/observability/metrics_collector.py)。

多 engine 的比率不能直接相加。有可比較的 capacity 才做加權聚合；不具 capacity 時展示各 engine 或明確標示 max。KV token slots 對應的 bytes 依模型、dtype、cache layout 變化，本版不以簡單公式推算通用 bytes。

## 5. Running／waiting 與逐筆請求

| 類型 | 指標／狀態 | 定義 |
| --- | --- | --- |
| 引擎彙總 | `engine_running_requests` | 上游 scheduler 明確提供的當下執行數 |
| 引擎彙總 | `engine_waiting_requests` | 上游 queue 的當下等待數；保留 queue 類型 |
| Gateway | `gateway_inflight_requests` | gateway 已收到但尚未結束的請求，包括可能的 engine queue |
| 逐筆 | `received`／`submitted` | 由明確 client／gateway 事件觀察到的生命週期 |
| 逐筆 | `engine_waiting`／`engine_running` | 必須有 scheduler／slot／對應 trace 證據 |
| 逐筆 | `completed`／`failed`／`cancelled` | 必須有來源結束事件；缺失時留為 unknown |
| 逐筆 | `unknown` | 無足夠證據、event gap 或 source 失聯 |

first_output 事件可表示正在串流，但不拿它回推精確排隊時間。slot id 會重複使用，需搭配 task id 與 engine epoch；沒有 request correlation 時顯示 slot/task，不虛構 gateway request id。

gateway 與 engine 狀態可能不同步，不能將 `gateway_inflight - engine_running` 解釋成 waiting。只有總數時，UI 顯示「可取得彙總，逐筆列表無資料」。

## 6. 請求來源與事件契約

來源優先採用可信 gateway 配置的 `application_id`／匿名 `client_id`；若只有網路位址，顯示匿名化 source。HTTP body 的 user／任意 header 若未由可信層驗證，需標示 client_claimed。

| 事件欄位 | 要求 |
| --- | --- |
| `schema_version`、`event_id`、`event_type` | 契約版本、去重識別、生命週期類型 |
| `request_id`、`attempt_id`、`service_id`、`model_id` | logical request 與 gateway retries 分開；維度可空但不猜測 |
| `timestamp`、`source_clock`、`event_origin` | UTC 時間、時鐘來源、client／gateway／engine |
| `source_id`、`source_trust` | 匿名來源與 verified／client_claimed／unknown |
| `input_tokens`、`output_tokens`、`decode_duration_seconds` | 可選 usage／timing；只在來源有資料時填入 |
| `coverage`、`reason` | 事件缺漏、sampling、繞過 gateway 等限制 |

重試同一 request 的 attempts 必須分開；最終 logical usage 與所有 attempts 的 engine 消耗不能重複算入同一排行。completed event 去重以 event id 與 request attempt 為準，支援日誌 rotation／replay／late arrival。

IP 預設不保存原值；可採帶本機 secret 的 HMAC 建立穩定匿名 id。salt／secret 不進 Git，輪替後跨 epoch 排行不可自動合併。只有可信 proxy hop 可以提供 forwarding IP，否則保留 socket peer 為 gateway，不推測原始 client。

預設不接收 prompt、response、Authorization headers 或完整 API keys。事件讀取只取 allowlist metadata。request_id／IP 不作 engine 時序 metrics 的高基數 labels。

## 7. 硬體、延遲與保留期間

- CPU 使用率正規化為 0–1；host total 與 process CPU 分開，process CPU 可跨多核心，不強制裁切為 100%。
- RAM 主欄位採 total／available 與定義一致的 ratio；swap、process RSS、container memory 各自標 scope。GPU 統一記憶體不重複加入 host RAM total。
- 溫度使用 °C、功耗 W、記憶體 bytes；未提供的 GPU 欄位保留 N/A。不可把全 host/device utilization 分攤成個別 model utilization。
- TTFT／queue time／end-to-end latency 須保留 engine timing 與 client timing 的不同起訖。p95 使用可聚合的 histogram buckets 或事件分布；不能平均各 replica 的 p95。
- 預設趨勢保留 600 秒；請求 metadata 保留 3600 秒並限制最大 10000 個事件，二者皆可調。source 排行需標明視窗與 coverage。
- 端點每 2 秒取樣，預設超過 10 秒未成功即 stale；各來源可獨立調整。歷史圖有 gap，當前值不沿用舊值冒充 fresh。

## 8. Snapshot 範例（合成資料）

```json
{
  "schema_version": 1,
  "runtime_id": "demo-runtime-1",
  "snapshot_seq": 42,
  "collected_at": "2026-10-02T03:00:00Z",
  "metrics": [
    {
      "service_id": "demo-vllm",
      "metric": "output_tps",
      "value": 45.2,
      "unit": "tokens/s",
      "status": "ok",
      "measurement_kind": "derived",
      "source_kind": "engine_metrics",
      "source_metric": "vllm:generation_tokens_total",
      "scope": "engine",
      "aggregation": "none",
      "window_seconds": 2.04,
      "observed_at": "2026-10-02T03:00:00Z",
      "last_success_at": "2026-10-02T03:00:00Z",
      "epoch": "demo-epoch-1",
      "coverage": "complete"
    },
    {
      "service_id": "demo-ollama",
      "metric": "engine_waiting_requests",
      "value": null,
      "unit": "requests",
      "status": "unsupported",
      "reason": "No verified native scheduler endpoint"
    }
  ]
}
```

正式 schema 尚待實作時建立；此例只展示有值／無值與品質 metadata，不代表完整 wire format。
