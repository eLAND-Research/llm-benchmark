# llm-benchmark

LLM 推論伺服器的客戶端黑箱效能測試工具。透過 HTTP/HTTPS 測量延遲、吞吐量、串流節奏與錯誤模式，無需存取伺服器端。

支援任何實作 OpenAI chat completions 協定的端點（vLLM、SGLang、HuggingFace TGI 等）。

## 功能

- **多伺服器比較** — 以相同 prompts 對多個端點進行基準測試
- **並行度掃描** — 跨可設定的並行等級測試，找出吞吐量飽和點
- **串流指標** — TTFB、token 間隔、首 token 延遲、抖動 (p95)
- **可重現性** — 透過 SHA256 設定指紋確保測試條件一致
- **錯誤分析** — 自動分類（逾時、速率限制、5xx、連線、解析）
- **Web UI** — 儀表板介面，可執行測試、檢視結果、匯出資料

## 安裝

需要 Python 3.11+。

```bash
pip install -e .

# 含開發依賴
pip install -e ".[dev]"
```

## 使用方式

### CLI

```bash
# 驗證設定檔
llmbench validate-config config/config_mock.yaml

# 執行基準測試
llmbench run config/config_mock.yaml -o results/my_run
```

### Web UI

```bash
llmbench serve
```

- 儀表板：http://localhost:8000/
- API 文件：http://localhost:8000/docs

### REST API

| 方法 | 端點 | 說明 |
|------|------|------|
| GET | `/api/benchmarks` | 列出基準測試 |
| POST | `/api/benchmarks` | 從 YAML 建立 |
| GET | `/api/benchmarks/{uuid}` | 測試詳情 |
| GET | `/api/benchmarks/{uuid}/status` | 輪詢狀態 |
| POST | `/api/benchmarks/{uuid}/run` | 觸發執行 |
| POST | `/api/benchmarks/{uuid}/cancel` | 取消執行 |
| GET | `/api/benchmarks/{uuid}/export` | 匯出 (json/csv/md) |
| GET | `/api/stats` | 儀表板統計 |
| POST | `/api/validate-config` | 驗證 YAML |

## 設定範例

```yaml
version: 1
servers:
  - name: vllm-local
    type: openai_compatible
    base_url: http://localhost:8000/v1
    model: meta-llama/Llama-3-8B

scenarios:
  - name: short_chat
    type: chat_short
    prompts_file: data/prompts/short.jsonl
    runs: 50
    concurrency: [1, 4, 8, 16]
    request:
      max_output_tokens: 100
      temperature: 0.7
      stream: true

warmup:
  requests: 3

retry_policy:
  strategy: exponential
  base_delay_ms: 500
  max_attempts: 3
```

API key 可透過 `env:VAR_NAME` 語法注入。

## 指標

| 類別 | 指標 |
|------|------|
| 延遲 | p50, p90, p95, p99 (ms) |
| 吞吐量 | requests/sec, tokens/sec (輸入, 輸出, 總計) |
| 串流 | TTFB, 首 token 延遲, 平均/p95 token 間隔 |
| 可靠性 | 錯誤率, 重試率, 錯誤類別分布 |
| 並行度 | 各並行等級的獨立統計 |

## 輸出

```
results/<run_name>/
├── scenario-<name>/<server>/
│   ├── requests.jsonl    # 原始逐筆請求資料
│   └── summary.json      # 彙總指標
├── global_summary.json   # 跨場景摘要
├── report.md             # 可讀報告
└── concurrency_throughput.csv
```

## 開發

```bash
pytest -v              # 執行測試
ruff check llmbench/   # Lint
mypy llmbench/         # 型別檢查
```

## 授權

Apache License 2.0
