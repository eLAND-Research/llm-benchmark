"""QA Tester agent prompt templates.

Provides prompts for the QA Tester agent to perform quality assurance on
the benchmark pipeline outputs. Includes prompts for:
- Spot-checking Judge scoring reasonableness
- Validating reference answer quality in the dataset
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Judge scoring spot-check
# ---------------------------------------------------------------------------

QA_CHECK_PROMPT = """\
你是一位品質驗收專員，負責檢查 AI 評分員的評分是否合理。請審視以下評分結果，判斷評分是否恰當。

## 原始題目（送給待測 LLM 的 prompt）
{item_prompt}

## 待測 LLM 的回覆
{response}

## 評分員給的分數
{score} / 5

## 評分員的評分理由
{reasoning}

請檢查以下事項：
1. 分數是否與評分理由一致？（例如：理由指出多項嚴重缺陷，但分數卻偏高）
2. 評分理由是否具體且有引用回覆內容作為佐證？
3. 評分理由是否有邏輯謬誤或自相矛盾？
4. 分數是否在合理範圍內？（對照回覆品質，分數不應偏離太大）

請以 JSON 格式回傳（不要包含 markdown 標記或其他文字）：
{{
    "is_reasonable": true 或 false,
    "issue": "若不合理，說明具體問題；若合理則填入空字串"
}}"""

# ---------------------------------------------------------------------------
# Dataset / reference answer quality check
# ---------------------------------------------------------------------------

DATASET_QUALITY_PROMPT = """\
你是一位品質驗收專員，負責檢查 benchmark 資料集的品質。請審視以下 benchmark 題目及其參考答案，評估品質是否達標。

## 任務類型
{task_type}

## 原始素材標題
{title}

## 原始素材內容
{content}

## 產生的題目（prompt）
{item_prompt}

## 參考答案
{reference_answer}

## 評分標準
{scoring_rubric}

請檢查以下事項：
1. **題目品質**：題目是否清晰明確？是否能有效測試 LLM 在此任務上的能力？
2. **參考答案正確性**：參考答案是否準確？是否與原始素材內容一致？
3. **參考答案完整性**：參考答案是否涵蓋了應有的關鍵資訊？
4. **評分標準合理性**：評分標準是否具體可操作？能否有效區分不同品質的回覆？
5. **格式一致性**：題目要求的回覆格式是否清晰？參考答案是否符合該格式？

請以 JSON 格式回傳（不要包含 markdown 標記或其他文字）：
{{
    "quality_score": 1到5的整數（5 為最佳）,
    "issues": [
        "問題描述1（若有）",
        "問題描述2（若有）"
    ],
    "suggestions": [
        "改善建議1（若有）",
        "改善建議2（若有）"
    ],
    "pass": true 或 false（quality_score >= 3 視為通過）
}}"""
