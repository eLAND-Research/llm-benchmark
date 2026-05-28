# llm-benchmark

LLM 推論伺服器的基準測試與「客觀知識」題庫產生平台。

包含兩大功能：

1. **Inference Benchmark** — 對任何 OpenAI 相容端點（vLLM、SGLang、LiteLLM、HuggingFace TGI）做延遲／吞吐量／串流指標測試。
2. **Quality / Knowledge Pipeline** — 自動從中文維基百科抓題材，請 LLM 生成「客觀台灣知識是非題」、跑模型測試、Judge 評分、出排行榜、P 值分析、選題下載 Google 表單。

---

## 系統需求

- **Python 3.11+**
- **uv** 或 **pip**（建議用 uv）
- **LiteLLM Gateway / OpenAI 相容 API** 的 base_url 與 api_key

---

## 從 GitHub 下載並啟動

### 1. Clone repo

```bash
git clone https://github.com/eLAND-Research/llm-benchmark.git
cd llm-benchmark
```

### 2. 安裝依賴

**用 uv（推薦）：**

```bash
uv venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
uv pip install -e .
```

**或用 pip：**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. 設定環境變數

```bash
cp .env.example .env
```

打開 `.env` 填入：

| 變數 | 必填 | 預設 | 說明 |
|------|------|------|------|
| `LITELLM_URL` | ✅ | `https://llmgw.elandai.cloud` | LiteLLM Proxy 或 OpenAI 相容 endpoint（不含 `/v1`，程式自動加） |
| `LITELLM_API_KEY` | ✅ | — | 對應的 API key（`sk-...`） |
| `JUDGE_LITELLM_API_KEY` | ❌ | 同上 | Judge 評分專用 key（不填用 `LITELLM_API_KEY`） |
| `JUDGE_MODEL_NAME` | ❌ | `gpt-4o-mini` | 預設 Judge 模型（UI 可覆寫） |
| `LITELLM_MCP_API_KEY` | ❌ | — | MCP 工具用，只在需要時設 |

注意：API key 不會 commit 到 GitHub（`.env` 在 `.gitignore`），只有 `.env.example` 範例會被 commit。

### 4. 初始化資料庫

```bash
python -m llmbench.web.init_db
```

如果之後新增了欄位，跑對應的 migration：

```bash
python -m llmbench.web.migrate_add_history
python -m llmbench.web.migrate_add_logs
python -m llmbench.web.migrate_add_participant_scores
```

### 5. 啟動 Web UI

```bash
llmbench serve
```

瀏覽器打開 <http://localhost:8000/>。

API 文件在 <http://localhost:8000/docs>。

---

## 使用：Quality Pipeline（題庫產生）

### 流程

```
匯入素材（5 種來源任選）
   ↓
生成題目（Designer LLM 出題）
   ↓
測試模型（Executor 跑題）
   ↓
評分（Judge LLM 評分）
   ↓
排行榜 / P 值分析 / 選題下載
```

### 五種素材匯入方式

進入 Web UI → **Challenges** → 點對應按鈕：

| 匯入方式 | 來源 | 資料放哪 | 產出題型 |
|---------|------|---------|---------|
| **客觀台灣知識** | 中文維基百科（程式即時抓） | 無需放檔案，UI 勾選條目分類即可 | true_false 是非題 |
| **Import Threads** | Threads 貼文 scraper 輸出的 JSON | 自選目錄，UI 填路徑 | stance_analysis 立場分析 |
| **Import Taiwan.md** | GitHub `frank890417/taiwan-md` repo（程式抓） | 自動快取在 `data/taiwan_md_cache/` | qa 問答題 |
| **Import School Exam** | 內建範例 / 學測會考題庫 ZIP | `data/exam_bank/raw_archives/*.zip` | school_qa 選擇題 |
| **Import PTT Movie** | PTT 看板（程式即時抓） | 無需放檔案，UI 填看板名稱 | qa 問答題 |

### 資料格式詳解

#### 1. 客觀台灣知識（無需檔案）
程式呼叫 zh.wikipedia.org API 即時抓。UI 勾條目分類即可（政治／地理／文化／歷史／教育／科技／節日）。

#### 2. Import Threads
UI 填入「Threads scraper 輸出目錄路徑」，例如 `/home/user/threads_data/`。

目錄裡的 JSON 檔格式：

```json
[
  {
    "id": "...",
    "text": "貼文內容",
    "timestamp": 1770965969,
    "username": "alice",
    "like_count": 42,
    "replies_count": 3,
    "repost_count": 5,
    "permalink": "https://www.threads.com/...",
    "replies": [
      { "text": "留言內容", "username": "bob", "like_count": 1 }
    ]
  }
]
```

#### 3. Import Taiwan.md（自動抓）
從 [taiwan-md repo](https://github.com/frank890417/taiwan-md) 抓 Markdown 文件，自動快取在 `data/taiwan_md_cache/`。第一次匯入會比較慢，之後從快取讀。

#### 4. Import School Exam
兩種模式：
- **builtin** — 用內建的少量範例文章（不需放檔案）
- **exambank** — 用真實學測題庫 ZIP

題庫模式需要把 ZIP 檔案放到：

```
data/exam_bank/raw_archives/jingwen_105_108.zip
data/exam_bank/raw_archives/your_archive.zip
```

ZIP 結構通常是 `年級/科目/卷子.pdf`，程式會抽出題幹。

#### 5. Import PTT Movie（即時抓）
UI 填看板名稱（預設 `movie`）、抓幾頁、關鍵字篩選。程式直接打 PTT 網頁 API。

### 各題型範例

#### true_false（是非題）

```json
{
  "statement": "台灣總統任期為四年",
  "answer": "TRUE",
  "explanation": "根據中華民國憲法增修條文，總統任期為四年"
}
```

#### stance_analysis（立場分析）

針對一則貼文/主題，判斷留言區整體立場（支持／反對／中立／混合）並說明依據。

```json
{
  "topic": "核電應該續用",
  "stance": "pro",
  "reasoning": "留言多數提及能源穩定與低碳排放的好處..."
}
```

#### qa（問答題）

開放式問答，模型回完整答案，Judge 依評分標準（rubric）打 1-5 分。

```json
{
  "question": "九份老街的歷史背景為何？",
  "reference_answer": "九份在日治時期因採金礦興盛...",
  "scoring_rubric": "完整答對給 5 分，部分答對給 3 分..."
}
```

#### school_qa（學測選擇題）

```json
{
  "question": "下列何者為 2024 年諾貝爾文學獎得主？",
  "options": ["A. 韓江", "B. 村上春樹", "C. 川普", "D. 馬奎斯"],
  "answer": "A",
  "explanation": "韓江於 2024 年獲頒諾貝爾文學獎"
}
```

### 通用步驟（以「客觀台灣知識」為例）

1. 點 **客觀台灣知識**，勾選想要的條目分類（政治／地理／文化／歷史／教育／科技／節日）→ **匯入**
2. 進入該 Challenge 詳細頁，按 **生成題目**：
   - 待測模型：填一個或多個（逗號分隔）
   - 抽取篇數：要從幾篇文章生題（上限是匯入的文章數）
   - 每篇文章題數：每篇要生幾道題（預設 10，只對 true_false 有效）
3. 生成完後到 **生成題目** tab 看結果：
   - **選題下載** — 手動勾選或快速配比（依 P 值難度抽樣，自動 dedup）
   - **P 值分析** — 看哪些題太簡單／太難／理想
   - **Google 表單腳本** — 下載 .gs，貼到 Google Apps Script 直接建出表單測驗
   - **排序下拉** — 最新優先 / 標題 / 得分 / 模型 / 面向
4. 想加新模型測同一份題目：按 **新增模型**，勾「用所有現有題目測試此模型」（不重新生題，直接拿現有題庫去測）

---

## 使用：Inference Benchmark（原始效能測試）

### CLI

```bash
# 驗證設定檔
llmbench validate-config config/config_mock.yaml

# 執行基準測試
llmbench run config/config_mock.yaml -o results/my_run
```

### YAML 設定範例

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

---

## 進階：Quality Pipeline 細節

### Pipeline 四階段（`llmbench/qual/pipeline.py`）

```
Phase 1  Research    研究員 agent 把 challenge 的素材轉成 RawMaterial 物件
Phase 2  Design      Designer LLM 對每篇素材出題，產出 BenchmarkItem
Phase 3  Implement   Executor 對每題打待測模型；Judge LLM 評分 1–5
Phase 4  UAT         QA Tester 檢查產出品質，產 report（PASS/FAIL）
```

每階段都會把中間結果存 SQLite，跑到一半失敗或關閉可從 results_jsonl 恢復顯示。

### Designer Prompt 核心規則（true_false）

- statement 必須包含完整主詞，禁止省略隱含主語
- 題目必須是關於台灣「現在」的事實，禁止 1949 前發生在中國大陸的歷史事件
- FALSE 題的錯誤值必須「乍看合理」（如將台北改高雄），禁止明顯荒謬
- 同篇文章 10 題不得測試相同知識點
- 禁止純數字統計題（面積、人口、GDP 等難記精確值）
- 跨國混淆題：statement 主詞必須是「台灣」或「中華民國」

完整 prompt 在 `llmbench/qual/prompts/designer.py`。

### P 值（鑑別度）

P 值 = 該題的「答對率」（0–1）。

| P 值範圍 | 分類 | 意義 |
|----------|------|------|
| > 0.7 | 太簡單 | 多數模型都答對，鑑別度低 |
| 0.4 – 0.7 | 理想 | 一半模型答對一半答錯，鑑別度最高 |
| < 0.4 | 太難 | 多數模型答錯，可能題目有問題或太冷僻 |

**計算方式**：每個 unique statement，跨所有測試過的模型計算「答對數 / 總測試模型數」。Judge 評分 ≥ 4 算答對。

P 值分析模態框可以多選類別篩選，下載 / Google 表單匯出。

### 選題下載：快速配比

選題 modal 內可指定要幾題理想 / 簡單 / 難題，按「快速配比」會：

1. 從各 P 值類別隨機抽指定題數
2. 平均分配六面向（可勾選關閉）
3. 每篇文章最多貢獻 `floor(n/10)` 題
4. 最後 shuffle，避免同文章/同主題題目相鄰

確保下載的題目多樣性高、無重複。

### 新增模型測試（不重新生題）

按 **新增模型** → 勾「用所有現有題目測試此模型」：

- 抓題庫所有 unique 題目（自動去重）
- 跳過已成功跑過該模型的題目
- 失敗的舊 row 會被移除重跑（不會累積錯誤）
- timeout 600 秒，支援 reasoning model
- 401 錯誤自動 retry 最多 6 次（LiteLLM 負載均衡換 deployment）

---

## REST API 速查

部分常用端點（完整列表見 `/docs`）：

### Challenges

| 方法 | 端點 | 說明 |
|------|------|------|
| `GET` | `/api/challenges` | 列出所有 challenge |
| `GET` | `/api/challenges/{uuid}` | challenge 詳情 |
| `POST` | `/api/challenges/import/taiwan-knowledge` | 匯入台灣知識 |
| `POST` | `/api/challenges/import/threads` | 匯入 Threads JSON |
| `POST` | `/api/challenges/import/taiwan-md` | 匯入 Taiwan.md |
| `POST` | `/api/challenges/import/school-exam` | 匯入學測題庫 |
| `POST` | `/api/challenges/import/ptt-movie` | 匯入 PTT 文章 |
| `DELETE` | `/api/challenges/{uuid}` | 刪除 challenge |

### Generate / Test

| 方法 | 端點 | 說明 |
|------|------|------|
| `POST` | `/api/challenges/{uuid}/generate` | 啟動生題＋測試任務 |
| `GET` | `/api/challenges/{uuid}/generate-status` | 查詢任務狀態 |
| `DELETE` | `/api/challenges/{uuid}/generate` | 取消任務 |
| `POST` | `/api/challenges/{uuid}/test-new-model` | 新模型測現有題庫 |

### 結果 / 分析

| 方法 | 端點 | 說明 |
|------|------|------|
| `GET` | `/api/challenges/{uuid}/results` | 取得排行榜 + 全部 row |
| `GET` | `/api/challenges/{uuid}/question-list` | 去重題目清單 + P 值 |
| `GET` | `/api/challenges/{uuid}/p-values` | P 值分析 |
| `GET` | `/api/challenges/{uuid}/export-questions` | 下載受試者題目 XLSX |
| `GET` | `/api/challenges/{uuid}/export/google-form-script` | Google 表單 .gs |
| `POST` | `/api/challenges/{uuid}/score-answers` | 上傳受試者答案評分 |
| `GET` | `/api/challenges/{uuid}/aspect-stats` | 各面向資料筆數統計 |

### 結果 row 主要欄位

每個 `results_jsonl` row 的關鍵欄位：

| 欄位 | 型別 | 說明 |
|------|------|------|
| `task_type` | str | true_false / qa / stance_analysis / school_qa |
| `model_name` | str | 待測模型名稱 |
| `title` | str | 來源文章標題 |
| `aspect` | str | 面向（人文/歷史/政治/社會/國際/科技） |
| `prompt` | str | 丟給待測模型的完整 prompt |
| `reference_answer` | str | JSON 字串，含 `{statement, answer, explanation}` |
| `response_text` | str | 模型回覆 |
| `response_error` | str | 失敗訊息（成功為空） |
| `score` | int | Judge 評分 1–5 |
| `reasoning` | str | Judge 評分理由 |
| `latency_ms` | float | 此題該模型延遲 |
| `judge_model` | str | 評分用的 model |
| `_run_dedup_count` | int | 該次生成內被去重的題數 |

---

## 專案結構

```
llmbench/
├── cli.py                  # CLI 入口
├── web/                    # FastAPI Web UI
│   ├── app.py              # FastAPI app
│   ├── routes/             # API + UI routes
│   ├── templates/          # Jinja2 templates
│   ├── models.py           # SQLAlchemy models
│   ├── init_db.py          # 初始化 DB
│   └── migrate_*.py        # 各次 schema migration
└── qual/                   # 題目生成 pipeline
    ├── pipeline.py         # 4 階段 pipeline 主流程
    ├── agents/
    │   ├── designer.py     # 生題 agent
    │   ├── executor.py     # 跑模型 agent
    │   ├── judge.py        # 評分 agent
    │   └── qa_tester.py    # 品質檢測
    ├── prompts/            # Designer / Judge prompts
    ├── taiwan_knowledge_source.py   # 維基百科抓題材
    └── world_knowledge_source.py    # 外國知識（混淆測試）

config/                     # YAML 設定檔範例
data/                       # 本地題材快取
results/                    # benchmark 輸出
tests/                      # pytest 測試
```

---

## 指標說明

### Inference Benchmark

| 類別 | 指標 |
|------|------|
| 延遲 | p50, p90, p95, p99 (ms) |
| 吞吐量 | requests/sec, tokens/sec |
| 串流 | TTFB, 首 token 延遲, token 間隔 |
| 可靠性 | 錯誤率, 重試率, 錯誤類別 |

### Quality Pipeline

| 指標 | 說明 |
|------|------|
| Avg Score | Judge 評分平均（1–5） |
| Count | 該模型答的題數 |
| Errors | 模型呼叫失敗數 |
| P 值（鑑別度） | 答對率；0.4–0.7 為理想題，>0.7 太簡單，<0.4 太難 |

---

## 常見問題

### LiteLLM 回 401 Unauthorized

LiteLLM 後面掛的 OpenAI key 沒設好。需要 LiteLLM 管理員：
1. 確認 server 上有 `export OPENAI_API_KEY=...`
2. 確認 LiteLLM 的 `config.yaml` 裡 `api_key: os.environ/OPENAI_API_KEY` 寫法正確
3. 重啟 LiteLLM service

### 生成題目卡住 / 跑超久

Reasoning model（如 gpt-5.x、o1）每題可能 5–10 分鐘。可以：
- 減少抽取篇數
- 換成非 reasoning 模型
- 等任務跑完（會用背景 task 不阻塞 UI）

### `gpt-5.x` 報 `temperature` 不支援

程式碼已自動 fallback（不傳 temperature 就用預設 1），不需手動處理。

---

## 開發

```bash
pytest -v              # 執行測試
ruff check llmbench/   # Lint
mypy llmbench/         # 型別檢查
```

---

## 授權

Apache License 2.0
