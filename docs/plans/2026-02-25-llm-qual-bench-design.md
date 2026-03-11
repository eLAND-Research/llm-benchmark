# LLM Quality Bench (llm-qual) — MVP Design

**Date**: 2026-02-25
**Status**: Approved

---

## Problem

評估新模型技術採用及 finetune 模型成效時，缺乏基於真實台灣輿情資料的標準化品質基準。需要一套自動化工具，用真實資料產生 benchmark 資料集，以 LLM as Judge 客觀比較不同模型的中文 NLP 品質。

## Solution

在 LLMBench 中新增 `llmbench/qual/` 子模組，實作 5 個 Agent 角色組成的品質驗證 pipeline：

```
TDS MCP (OpView 輿情)
    ↓
[Researcher] 抓取 + 篩選原始素材
    ↓
[Designer]   根據素材產生 4 類 benchmark 題目
    ↓  (benchmark dataset)
[Executor]   把題目丟給 N 個待測 LLM，收集回應
    ↓  (responses)
[Judge]      單一強模型評分 (1-5 分 + 理由)
    ↓  (scores)
[QA Tester]  驗收：資料集品質、評分一致性、流程正確性
    ↓
SQLite 儲存 + JSON snapshot 匯出 + 品質報告
```

## Decisions

| 項目 | 決定 | 理由 |
|------|------|------|
| MVP 任務類型 | 摘要、情感分析、主題分類、QA | 最符合 TDS 輿情資料特性 |
| Judge 策略 | 單一強模型 | MVP 簡單直接，後續可擴展多 Judge |
| 實作方式 | 混合式（pipeline 骨架 + 關鍵角色 LLM agent） | 流程可控好 debug，Designer/Judge 保留靈活性 |
| 儲存 | SQLite 主儲存 + JSON snapshot 匯出 | 方便查詢歷史 + 方便分享 |
| 待測 LLM 接入 | 複用現有 openai_compatible adapter | 不重複造輪 |

## Data Models

### RawMaterial — Researcher 輸出

```python
class RawMaterial(BaseModel):
    source_category: str        # "news" / "facebook" / "dcard"
    title: str
    content: str
    keyword: str                # 用了什麼關鍵字抓的
    month_range: dict           # {"start": "YYYYMM", "end": "YYYYMM"}
```

### BenchmarkItem / BenchmarkDataset — Designer 輸出

```python
class BenchmarkItem(BaseModel):
    id: str                     # uuid
    task_type: str              # "summarization" / "sentiment" / "classification" / "qa"
    source_material: RawMaterial
    prompt: str                 # 給待測 LLM 的完整 prompt
    reference_answer: str | None  # Designer 產生的參考答案
    scoring_rubric: str         # 評分標準描述

class BenchmarkDataset(BaseModel):
    id: str
    created_at: datetime
    task_types: list[str]
    items: list[BenchmarkItem]
```

### LLMResponse — Executor 輸出

```python
class LLMResponse(BaseModel):
    benchmark_item_id: str
    model_name: str
    response_text: str
    latency_ms: float
    token_count: int
```

### JudgeScore — Judge 輸出

```python
class JudgeScore(BaseModel):
    benchmark_item_id: str
    model_name: str
    score: int                  # 1-5
    reasoning: str              # 評分理由
    judge_model: str            # 用哪個模型當 Judge
```

### QAReport — QA Tester 輸出

```python
class QAReport(BaseModel):
    dataset_quality: dict       # 資料集品質指標
    scoring_consistency: dict   # 評分一致性指標
    issues: list[str]           # 發現的問題
    pass_: bool                 # 整體是否通過
```

## Agent Roles

### Researcher（純 Python + MCP 呼叫）

- 按照 config 指定的 categories / keywords / month_range 從 TDS 抓取
- 透過 `langchain-mcp-adapters` 呼叫 `easy_search`
- 對每個 task_type × keyword 組合抓取素材
- 去重後輸出 `list[RawMaterial]`

### Designer（LLM Agent）

最關鍵的角色，需要 LLM 理解素材並產出題目：
- 摘要：「請為以下文章產生一份 100 字摘要」+ 產生 reference answer
- 情感分析：「判斷以下文章的情感傾向」+ 標注正確答案
- 主題分類：「將以下文章分類到指定類別」+ 標注正確類別
- QA：「根據以下文章產生 3 個問答對」+ 產生參考答案
- 同時產生每題的 scoring_rubric

### Executor（純 Python，複用現有 adapter）

- 讀取 BenchmarkDataset，對每個 item 組裝 prompt
- 透過 openai_compatible adapter 送給每個待測 LLM
- 記錄回應內容 + latency + token count

### Judge（LLM Agent）

- 拿到 BenchmarkItem + LLMResponse + scoring_rubric
- 用 prompt 請強模型依照 rubric 給 1-5 分並說明理由

### QA Tester（LLM Agent + 規則檢查）

- 規則檢查：空值/重複、評分分佈異常、回應是否為空
- LLM 輔助：抽樣檢查 Judge 評分理由是否合理、reference answer 品質
- 不通過就標記 issues

## Directory Structure

```
llmbench/qual/
├── __init__.py
├── pipeline.py          # 主 pipeline 編排（async）
├── config.py            # QualConfig Pydantic 設定
├── schemas.py           # 所有資料結構
├── agents/
│   ├── __init__.py
│   ├── researcher.py    # TDS 資料抓取
│   ├── designer.py      # LLM agent - 產生 benchmark 題目
│   ├── executor.py      # 呼叫待測 LLM
│   ├── judge.py         # LLM as Judge 評分
│   └── qa_tester.py     # 驗收檢查
├── prompts/
│   ├── designer.py      # Designer 的 prompt templates
│   ├── judge.py         # Judge 的 prompt templates
│   └── qa_tester.py     # QA Tester 的 prompt templates
├── storage/
│   ├── db.py            # SQLite 存取層
│   └── exporter.py      # JSON snapshot 匯出
└── report.py            # 品質報告產生器
```

## Config Example

```yaml
qual:
  data_source:
    mcp_url: "http://172.18.10.41:8888/sse"
    searches:
      - categories: ["news", "facebook"]
        keyword: "川普 & 關稅"
        top_k: 20
        month_range: { start: "202501", end: "202602" }

  task_types: ["summarization", "sentiment", "classification", "qa"]
  items_per_task: 10

  models_under_test:
    - name: "gpt-4o"
      base_url: "https://api.openai.com/v1"
      api_key: "env:OPENAI_API_KEY"
      model: "gpt-4o"
    - name: "local-llama"
      base_url: "http://localhost:8000/v1"
      model: "llama-3-70b"

  judge:
    model_name: "gpt-4o"
    base_url: "https://api.openai.com/v1"
    api_key: "env:OPENAI_API_KEY"

  output_dir: "results/qual"
  db_path: "llmbench_qual.db"
```

## Pipeline Flow

```python
async def run_qual_pipeline(config: QualConfig):
    # Phase 1: Study — 抓取素材
    researcher = Researcher(config.data_source)
    materials = await researcher.fetch()

    # Phase 2: Design — 產生資料集
    designer = Designer(config)
    dataset = await designer.generate(materials)
    storage.save_dataset(dataset)

    # Phase 3: Implement — 執行待測 + 評分
    executor = Executor(config.models_under_test)
    responses = await executor.run(dataset)
    storage.save_responses(responses)

    judge = Judge(config.judge)
    scores = await judge.evaluate(dataset, responses)
    storage.save_scores(scores)

    # Phase 4: UAT — 驗收
    qa = QATester()
    report = await qa.verify(dataset, responses, scores)
    storage.save_report(report)

    # 匯出
    exporter.export_json_snapshot(config.output_dir)
    report_gen.generate_markdown(config.output_dir)
```

## CLI

```bash
# 完整跑一輪
llmbench qual run config/qual_example.yaml

# 只跑單一階段（debug 用）
llmbench qual fetch config/qual_example.yaml
llmbench qual design config/qual_example.yaml
llmbench qual execute config/qual_example.yaml
llmbench qual judge config/qual_example.yaml
llmbench qual verify config/qual_example.yaml

# 查看結果
llmbench qual report results/qual/2026-02-25/
```

## Implementation Plan

### Step 1: 基礎建設
- 建立 `llmbench/qual/` 目錄結構
- 實作 `schemas.py`（所有 Pydantic models）
- 實作 `config.py`（QualConfig + YAML 載入）
- 實作 `storage/db.py`（SQLite schema + CRUD）

### Step 2: Researcher + Designer
- 實作 `researcher.py`（TDS MCP 抓取）
- 實作 `prompts/designer.py`（4 種 task 的 prompt templates）
- 實作 `designer.py`（LLM agent 產生題目）
- 測試：能從 TDS 抓資料並產出 BenchmarkDataset

### Step 3: Executor + Judge
- 實作 `executor.py`（複用 openai adapter）
- 實作 `prompts/judge.py`（評分 prompt templates）
- 實作 `judge.py`（LLM as Judge）
- 測試：能跑待測 LLM 並評分

### Step 4: QA Tester + Report
- 實作 `qa_tester.py`（規則 + LLM 檢查）
- 實作 `report.py`（Markdown 報告）
- 實作 `storage/exporter.py`（JSON snapshot）

### Step 5: Pipeline + CLI 整合
- 實作 `pipeline.py`（串接所有階段）
- 擴展 `cli.py`（qual 子命令群）
- 端到端測試
