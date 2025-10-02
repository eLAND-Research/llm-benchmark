# LLM Inference Server Benchmark 系統藍圖 (Blueprint)

版本: 0.1.0  
最後更新: 2025-10-02  
作者: （待補）

---
## 1. 背景與目標
目前市面上各種 LLM 推論（Inference）服務與框架（如 OpenAI API、vLLM、TensorRT-LLM、HuggingFace TGI、FastChat、SGLang 等）在效能、穩定性、延遲、吞吐與資源利用上差異顯著。缺乏一個統一、可擴充且可重現的基準測試（Benchmark）工具，讓使用者可系統化比較:

1. 模型效率與能力（Model Capability & Efficiency）
2. GPU/硬體資源效率（Hardware Efficiency）

【更新重點】本系統以「純 Client 端觀測 (Black-box Benchmark)」為核心：執行測試的機器不假設擁有目標推論伺服器的本機 GPU / 系統存取權。所有核心指標以請求往返、回傳 token 節奏、錯誤行為為主；硬體資源效率僅在使用者額外提供遠端 metrics 介面（如 Prometheus、雲端監控 API 或自訂 webhook）時才啟用。若無硬體來源，報告中相關欄位標記為 `unavailable`。

---
## 2. 目標與非目標 (In / Out of Scope)
### In Scope (初版 MVP)
- 針對使用者提供的推論 API Endpoint 進行黑盒（black-box）壓力與品質測試（僅使用 HTTP/S streaming/非 streaming）
- 支援 OpenAI API 介面相容協定 (chat/completions, embeddings)
- 支援 vLLM / HuggingFace TGI 透過簡單 adaptor（同樣透過其公開 HTTP API）
- 測量（Client 可觀測核心）：
  - Latency：DNS + TCP + TLS（可選）/ TTFB / Total / Per Token / Percentiles
  - Throughput：Requests/sec、Tokens/sec (input/output/total)
  - Concurrency Scaling：不同同時連線數下的延遲與吞吐曲線
  - Error Metrics：HTTP status code 分布、timeout rate、retry 行為、abort/stream 中斷
  - Streaming Token Cadence：每 token 間隔、jitter、burst pattern
  - 基礎模型品質：Perplexity（若 API 提供 logprob 或 approximate）、簡單 QA 正確率
- 統一測試配置檔（YAML）
- 結構化輸出 (JSON + Markdown 報告)
- CLI 介面
- Adapter / Scenario / Metrics Collector（client-side）可擴充
- 結果版本化與可重現性 (commit hash / config fingerprint)
- 遠端硬體或系統資源指標：以「可選插件」方式（Prometheus / Custom HTTP），若未設定則不影響主流程

### Out of Scope (MVP 之後階段)
- 直接呼叫 `nvidia-smi` 或 NVML（因 client 無伺服器 shell 權限）
- 主動部署探針到目標伺服器（由使用者自行提供遠端 metrics 端點）
- Web UI / Dashboard（列入 Roadmap）
- Long-running 監測 / A/B 慢性對比
- 複雜任務評估（Code pass@k、工具使用推理）
- 真實電力耗用量測（需要外部裝置）
- 多節點 GPU profiling（black-box 階段僅聚焦 network / API 可觀測）

---
## 4. 高階架構 (High-Level Architecture)
```
+-------------------+
|      User / CLI   |
+-------------------+
          |
          v
+-------------------+          +-------------------+
|   Config Loader   | -------> | Dataset Provider  |
+-------------------+          +-------------------+
          |                            |
          v                            v
+---------------------------------------------------+
|             Benchmark Orchestrator                |
|  - Scenario Scheduler                             |
|  - Concurrency Controller                        |
|  - Warmup Manager                                 |
|  - Retry & Backoff                                |
|  - (Optional) Rate Limiter                        |
+---------------------------------------------------+
          |                   |                   |
          v                   v                   v
  +--------------+     +--------------+    +------------------+
  | API Adapter  |     | Client Metric|    | Quality Evaluator|
  | (HTTP/HTTPS) |     | Collector    |    | (PPL / QA)       |
  +--------------+     +--------------+    +------------------+
          |                       \
          |                        \
          |                +------------------+
          |                | Remote Metrics   |  (Optional plugin: Prometheus,
          |                | Collector        |   custom endpoint, cloud API)
          |                +------------------+
          |                         |
          +------------+------------+
                       v
             +------------------+
             |   Result Store   |
             +------------------+
                       |
                       v
             +------------------+
             | Report Generator |
             +------------------+
```
【差異說明】移除對本地 GPU 指令依賴，硬體資料僅透過遠端 plugin。

---
## 7. 配置檔 (Configuration Spec) - YAML 草案
```yaml
version: 1
metadata:
  experiment_name: "baseline_vllm_vs_tgi"
  description: "Compare vLLM and TGI under mixed workload"
  seed: 42
  tags: [baseline, compare]

servers:
  - name: vllm_local
    type: openai_compatible    # adapter key
    base_url: http://127.0.0.1:8000/v1
    api_key: "env:VLLM_API_KEY" # env 變數
    model: "Qwen2-7B-Instruct"
    max_retries: 3
    timeout_seconds: 30
    extra:
      compression: false
  - name: tgi_gpu1
    type: huggingface_tgi
    base_url: http://10.0.0.12:8080
    model: "meta-llama/Meta-Llama-3-8B-Instruct"

scenarios:
  - name: short_chat
    type: chat_short
    prompts_file: data/prompts/short.jsonl
    runs: 200
    concurrency: [1, 4, 8, 16]
    request:
      max_output_tokens: 128
      temperature: 0.7
      stream: false
  - name: long_chat
    type: chat_long
    prompts_file: data/prompts/long.jsonl
    runs: 100
    concurrency: [1, 2, 4]
    request:
      max_output_tokens: 1024
      temperature: 0.2
      stream: true

quality:
  perplexity:
    enabled: true
    dataset: data/eval/wikitext_sample.txt
  qa_accuracy:
    enabled: true
    dataset: data/eval/qa_small.jsonl

metrics:
  gpu:
    enabled: true
    interval_sec: 1.0
  system:
    enabled: true
    interval_sec: 1.0

report:
  formats: [markdown, json]
  output_dir: results/2025-10-02-exp1

storage:
  backend: json
  path: results/2025-10-02-exp1/raw

warmup:
  requests: 10
  discard_metrics: true

rate_limit:
  enabled: false

retry_policy:
  strategy: exponential_backoff
  base_delay_ms: 200
  max_attempts: 3

cost_model:
  enabled: true
  entries:
    - model_pattern: "Qwen2-7B-Instruct"
      input_token_usd: 0.0000004
      output_token_usd: 0.0000006
    - model_pattern: "Meta-Llama-3-*"
      input_token_usd: 0.000001
      output_token_usd: 0.000002

remote_metrics:                # 新增：遠端硬體/系統指標 (可選)
  - name: prod_prometheus
    type: prometheus
    base_url: https://metrics.example.com
    query:
      gpu_util: avg(DCGM_FI_DEV_GPU_UTIL{instance="inference-a"})
      gpu_mem_used_mb: avg(DCGM_FI_DEV_FB_USED{instance="inference-a"})
      power_w: avg(DCGM_FI_DEV_POWER_USAGE{instance="inference-a"})
      # 可自訂多個查詢鍵；聚合時 key 直接映射
    interval_sec: 5
    timeout_sec: 3
  - name: custom_http_node1
    type: json_http
    url: https://node1.example.com/llm/metrics
    method: GET
    headers:
      Authorization: "Bearer env:PROM_TOKEN"
    interval_sec: 10
    parse:
      gpu_util: $.gpus[0].utilization
      gpu_mem_used_mb: $.gpus[0].memory.used_mb
      model_qps: $.model.qps
```

---
## 8. Adapters 設計
```python
class InferenceAdapter(ABC):
    # 保持不依賴伺服器內部資源；所有延遲細節於上層收集（DNS/TCP/TLS）
    # 可以傳入 session_factory 以便自訂連線池與 timeout
    ...
```
新增：
- `supports_network_timings` 改由上層 HTTP wrapper 直接量測，不強制各 adapter 實作。
- Adapter 僅負責構造 payload / 解析 response / streaming 迭代。網路階段 latency 分解在共用 http client middleware。

---
## 9. Metrics 與指標定義 （擴充：Client Network & Streaming Cadence）
| 類別 | 指標 | 定義 | 備註 |
|------|------|------|------|
| Network | dns_ms | DNS 解析耗時 | 若快取則可能為 0 / 近似 |
| Network | connect_ms | TCP 連線時間 | 多路複用下僅首連線 | 
| Network | tls_ms | TLS 握手時間 | HTTP/2 / HTTPS only |
| Network | handshake_ms | connect_ms + tls_ms | 綜合指標 |
| Network | wait_ms | 送出請求到首 byte 前（含伺服端排隊） | Chromium timing analogous |
| Network | ttfb_ms | 首個 token/字元抵達 | Streaming/非 streaming皆可（非 streaming=整包） |
| Streaming | first_token_gap_ms | ttfb 後第一個完整 token 間隔 | stream 啟動後節奏 |
| Streaming | mean_token_interval_ms | 後續 token 平均輸出間隔 | |
| Streaming | token_interval_p95_ms | Token 間隔 P95 | jitter 分析 |
| Streaming | throughput_tokens_sec | Output tokens/sec (stream cadence) | 實際觀測 |
| Reliability | partial_stream_rate | 中途中斷（未完成）比例 | |
| Cost | estimated_cost_usd | 以 usage 或 approximate token × cost model | 若缺 usage 則 approximate=true |
| Hardware(Remote) | gpu_util | 遠端 plugin 回傳 | 無資料 -> unavailable |
| Hardware(Remote) | gpu_mem_used_mb | 遠端 plugin 回傳 | |
| Custom(Remote) | 任意 key | 遠端 plugin 自訂欄位 | 直接 pass-through |

說明：若 remote metrics 缺席，報告中硬體列改顯示符號 `—` 並於附錄載明限制。

---
## 10. 資料收集與時間序列結構
新增 network timing 於 request-level：
```json
{
  "request_id": "req_abc123",
  "scenario": "short_chat",
  "server": "vllm_local",
  "concurrency_level": 8,
  "dns_ms": 2.1,
  "connect_ms": 14.3,
  "tls_ms": 12.0,
  "ttfb_ms": 120.5,
  "first_token_gap_ms": 18.2,
  "mean_token_interval_ms": 9.4,
  "token_interval_p95_ms": 21.7,
  "total_ms": 460.2,
  "input_tokens": 58,
  "output_tokens": 120,
  "cost_usd": 0.0000912,
  "cost_estimated": false,
  "error": null,
  "retries": 0,
  "stream": false
}
```
遠端硬體 time-series：
```json
{
  "timestamp": 1730000005.001,
  "source": "prod_prometheus",
  "metrics": {
    "gpu_util": 72.4,
    "gpu_mem_used_mb": 10120,
    "power_w": 215.3
  }
}
```

---
## 11. 儲存層 (Result Storage)
【補充】增加 `remote_metrics.jsonl`：若啟用遠端硬體/自訂指標插件，每 interval 寫一行。

---
## 14. 執行流程 (Benchmark Lifecycle)
增補步驟：
- (可選) 啟動 Remote Metrics Poller 任務（與主負載 decouple，使用 asyncio.create_task）
- 收到 cancel signal 或全部 scenario 完成後優雅終止 poller
- 若 remote metrics 失敗次數 > 閾值，記錄 warning 但不終止主流程

---
## 18. GPU / 系統監控 （改為：Remote Metrics 插件架構）
原設計依賴本地 `nvidia-smi` 已調整：
1. Core 版本：不收集伺服器硬體指標
2. 使用者可於 config `remote_metrics` 陣列註冊多個來源：
   - `prometheus`: 以 HTTP GET 發送多條 query（range=instant）解析數值
   - `json_http`: 呼叫自訂 REST 回傳 JSON，透過 JSONPath/鍵映射提取
   - （未來）`cloudwatch`, `datadog`, `custom_python`
3. Poller 行為：
   - 依各來源 `interval_sec` 排程
   - 超時標記 `error` 欄位並跳過寫入或寫入 error 記錄
   - 不阻塞主 benchmark
4. 聚合策略：
   - 對於同名指標（如 gpu_util）可計算 mean / max / p95（可在 report 階段）
5. 報告標註：沒有任何 remote metrics → 報告章節顯示提示訊息："No server-side hardware metrics (client-only run)"。

---
## 19. 成本模型
補充：若 API 不返回 token usage：
- 啟用 approximate tokenizer (根據 adapter 指定 model family)
- 在 request log 標記 `cost_estimated=true`
- 報告中統計「估算比例」(% of requests estimated)

---
## 20. 錯誤與例外處理策略
新增：
| 類型 | 策略 |
|------|------|
| RemoteMetricsTimeout | 記錄 warning，不影響主流程 |
| RemoteMetricsParseError | 記錄 error 次數，連續 N 次停用該來源 |
| HTTP2 Stream Reset | 重試一次（若可重建流），否則標記 partial |

---
## 21. 結果聚合 (Aggregation)
新增聚合：
- network_handshake_ms_avg = (connect_ms + tls_ms) 平均
- streaming_jitter_p95 = token_interval_p95_ms - mean_token_interval_ms
- partial_stream_rate = partial_stream / stream_requests
- remote_metrics_presence = {gpu_util: true/false, ...}

---
## 22. 擴充性 (Extensibility)
補充 remote metrics plugin interface 草案：
```python
class RemoteMetricsSource(ABC):
    name: str
    interval_sec: float
    async def fetch(self) -> dict[str, float]: ...  # raise RemoteMetricsError on failure
```

---
## 23. 安全與隱私 (Security & Privacy)
補充：遠端 metrics 認證：
- 支援 `env:` 取值置換
- 若含機密 header，結果文件不回寫 header 值

---
## 25. 效能與資源考量
補充：
- Network timing 收集使用 `async instrumentation`（例如 httpx event hooks）避免阻塞
- 避免為每 request 建立新 TCP 連線：重用 keep-alive 連線，僅首連線有 connect/tls timing；對後續請求 connect_ms/tls_ms 設置為 0 或 None（報告需解釋）

---
## 26. 風險與緩解 (Risks & Mitigations)
新增：
| 風險 | 說明 | 緩解 |
|------|------|------|
| 網路抖動影響指標 | 公網/跨區 latency 浮動 | 多次重複實驗 + 置信區間報告 |
| 遠端 metrics 與 request 時間軸不同步 | Poll interval 粗粒度 | 以最近窗口對齊 / 標註時間偏差 |
| 重用連線影響 connect_ms 分析 | 只首請求有 connect/tls | 報告分離 "first-connection" 指標 |

---
## 34. 下一步 (Immediate Next Steps)
更新：
1. 建立 http instrumentation middleware（量測 dns/connect/tls/ttfb/token cadence）
2. Adapter OpenAI baseline + streaming 支援
3. Config schema 加入 `remote_metrics` 驗證
4. Remote metrics plugin: prometheus / json_http prototype
5. Request log 資料結構擴充 network fields
6. Report generator: client-only 模式 fallback 說明
7. 聚合：network + streaming cadence + 成本估算旗標
8. 單元測試：network timing mock、remote metrics failure recover

---
## 35. 附錄：Client-Only vs Instrumented 模式
| 模式 | 描述 | 需要伺服器權限 | 硬體指標來源 |
|------|------|----------------|--------------|
| client_only | 純 HTTP 黑盒觀測 | 否 | 無（報告標示 unavailable） |
| client_with_remote_metrics | 使用者提供 metrics endpoint | 僅讀取 HTTP/S | 遠端 plugin + 聚合 |
| instrumented (未來) | 代理側車或內嵌探針 | 是 | 直接 NVML / profiler |

---
## 36. 目前實作進度 (Progress Update - 2025-10-02)
本節描述已在程式庫中完成的最小可執行骨架（MVP pre-alpha）與尚未完成項目，對照原藍圖需求與 Roadmap。

### 36.1 已完成 (Implemented)
- 專案骨架 & 套件結構（`llmbench/`）
- `pyproject.toml` + 安裝腳手架 (editable 模式)
- Config Schema（Pydantic v2 + field_validator, 支援 servers/scenarios/cost_model/remote_metrics 等欄位；尚未全部使用）
- Config Loader（YAML -> Pydantic）
- Adapters：
  - `openai_compatible`（基本非 streaming + streaming SSE）
  - `mock`（支援 `fail_first_n` 模擬暫時性錯誤）
- Scenario：`chat_short`/`chat_long` 共用 `ChatScenario`
- Load Generation：`LoadExecutor`（async + concurrency semaphore）
- Orchestrator：多 scenario × 多 server 執行 + per concurrency bucket 聚合
- Warmup：支援 `warmup.requests`，結果丟棄不計入統計
- Retry：指數退避 + jitter（利用 `retry_policy`）；收集 `retries_total` 与 `retry_rate`
- Error 分類：`error_categories`（timeout / http_429 / http_5xx / connection / parse / transient / other）
- Streaming：初步 token cadence（chunk 間隔）＋ approximate token 計算（長度/4）
- Approx Tokens 標記：`output_tokens_approx_ratio`
- Network Instrumentation Scaffold：取得 `wait_ms`（headers_received - start）、推導 `ttfb_ms`；保留 `dns_ms` / `connect_ms` / `tls_ms` placeholder
- Metrics 聚合：latency percentiles、ttfb percentiles、wait_p50 / wait_p95 / wait_avg、tokens_per_sec、error_rate、retry_rate、error_categories
- Concurrency Buckets：每個 concurrency level 擁有獨立聚合
- Reporting：Markdown 報告展示主要 latency / wait / tokens/s / err_rate / ttfb / approx_ratio / concurrency breakdown（含 wait_p50）
- Tests：
  - config 載入
  - mock benchmark 執行
  - CLI validate / run
  - concurrency buckets 基本驗證
  - streaming approximate tokens 驗證
- Logging：rich handler（INFO 級別）
- Pydantic v1 validator Deprecated 警告已處理 (field_validator)

### 36.2 部分完成 / 初步雛形 (Partial / Stub)
| 項目 | 狀態 | 說明 |
|------|------|------|
| Streaming 指標 | 初步 | 尚未計算 mean_token_interval / p95 在 summary（僅 request-level / 暫時性）|
| Network 分解 | scaffold | 只有 wait_ms / ttfb_ms，無 DNS/Connect/TLS 真實拆解 |
| Cost Model | schema | 尚未實作計算与報告欄位 |
| Perplexity / QA | schema | 尚未執行邏輯 |
| Rate Limit | 未啟用 | 僅 concurrency 控制，無固定 RPS |
| Storage 抽象 | 基本 | 僅 JSONL / summary JSON |
| 報告 | 強化中 | 尚未顯示 retry_rate / error_categories 詳細表 |

### 36.3 尚未實作 (Not Implemented Yet)
| 類別 | 未完成項目 | 說明 / 待辦 |
|------|------------|-------------|
| DNS/TCP/TLS Timing | 真實分解 | 需自訂 httpx Transport 或 aiohttp TraceConfig |
| Streaming Cadence 聚合 | jitter / mean/p95 指標 | 需寫進聚合與報告 |
| Token Usage 落差補救 | tokenizer 真實估算 | 引入 tiktoken/transformers fallback |
| Perplexity | logprob 或外部近似 | 需 API 支援或離線重算 |
| QA Accuracy | dataset 比對 | 實作 exact / 包含 / semantic 可選 |
| Remote Metrics Plugins | prometheus/json_http poller | 背景輪詢 + timeseries 寫檔 |
| Cost Model 計算 | total_cost_usd / cost_per_1k_tokens | 匹配 model_pattern + approximate flag |
| Error Taxonomy 擴充 | 更細粒度 | 區分 partial_stream / client_cancel |
| Rate Limiter | 固定 RPS / token bucket | 載入配置後節流 |
| Compare 指令 | 多結果 diff | `llmbench compare pathA pathB --metric tokens_per_sec` |
| SQLite Backend | 快速查詢 | 需 schema 與寫入 transaction |
| Report 圖表 | ASCII / SVG | 產出簡易趨勢圖 (latency vs concurrency) |
| Repro Metadata | git commit/config hash 寫入結果 | 目前僅 CLI 指紋輸出 |
| CI / Lint | pipeline | 加入 ruff / mypy / pytest workflow |
| Docs | 擴充 README / 使用手冊 | 需撰寫典型情境範例 |

### 36.4 風險 / 技術債現況 (Current Risks / Debts)
| 類別 | 風險 / 技術債 | 緩解計畫 |
|------|---------------|-----------|
| Network Timing 精度 | 無真實 DNS/Connect/TLS | 實作自訂 Transport 逐步補齊 |
| Streaming 僅近似 tokens | 無 usage 時粗估 | 優先加 tokenizer fallback 並標註來源 |
| Retry 行為未測細節 | 尚未有 fail_then_success / fail_always 測試 | 新增專門測試 config（fail_first_n vs max_attempts）|
| 指標爆炸 | summary 欄位逐增 | 引入分組/命名空間或可選輸出等級 |
| Error Categories | 目前以字串匹配 | 後續統一錯誤代碼表 + 前綴 |

### 36.5 下一階段優先開發建議 (Priority Backlog)
順序更新：
1. 新增 retry / error_categories 測試（fail_first_n 不同值）
2. 將 streaming token cadence（mean / p95）納入聚合與報告
3. Network 分解：最小 Transport -> connect_ms / tls_ms 基礎近似
4. Cost model 計算與報告 cost 欄位
5. Tokenizer approximate fallback（tiktoken）
6. Report 顯示 retry_rate / error_categories 摘要表
7. Remote metrics poller（prometheus + json_http）
8. Compare 指令 (差異輸出 markdown)
9. Perplexity / QA (最小實作) 並標記對結果的隔離執行階段

### 36.6 與 Roadmap 對照
| Roadmap 版本 | 預期 | 現狀 | 備註 |
|--------------|------|------|------|
| v0.1 | CLI + OpenAI 相容 + 基本 latency/throughput | 已擴充 (含 retry/warmup) | throughput 尚為簡化 (僅 output tokens/sec) |
| v0.2 | Streaming + Remote metrics + perplexity | 部分 (streaming 初版) | remote/perplexity 未完成 |
| v0.3 | QA + cost + 強化報告 | 未開始 | |
| v0.4 | SQLite + compare + batch generation | 未開始 | |
| v0.5 | 更多 adapters + dashboard | 未開始 | |
| v1.0 | 插件系統/CI/完整文件 | 未開始 | |

### 36.7 驗證結果摘要 (Current Test Snapshot)
| 測試類型 | 結果 | 備註 |
|-----------|------|------|
| Config 載入 | 通過 | 解析 YAML -> Pydantic |
| Orchestrator (mock) | 通過 | latency / 基本聚合 |
| CLI | 通過 | validate / run |
| Concurrency buckets | 通過 | 驗證 bucket 總和一致 |
| Streaming approx | 通過 | ratio > 0 |
| Retry / Warmup | 未測 | 剛實作；待新增 | 
| Error categories | 未測 | 需 fail_always 測試 | 
| Wait 指標 | 未測 | 僅生成與報告顯示 |

### 36.8 近期變更摘要 (Changelog Since Initial Progress)
| 日期 | 變更 | 摘要 |
|------|------|------|
| 2025-10-02 | Network scaffold | 加入 wait_ms / ttfb_ms，佔位 dns/connect/tls |
| 2025-10-02 | Concurrency buckets | 每並發層級獨立聚合輸出 |
| 2025-10-02 | Streaming approx tokens | 以字元長度/4 估算 tokens + ratio 指標 |
| 2025-10-02 | Warmup 支援 | warmup.requests 丟棄結果不影響主統計 |
| 2025-10-02 | Retry 機制 | 指數退避 + jitter + retries_total / retry_rate |
| 2025-10-02 | Error 分類 | 基於字串模式分類成 7 種類別 |
| 2025-10-02 | Wait 指標聚合 | wait_p50 / wait_p95 / wait_avg 納入報告 |

---
(文件結束)
