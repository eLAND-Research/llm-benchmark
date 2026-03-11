"""Designer agent prompt templates.

Provides task-specific prompts for the Designer agent to generate benchmark
items from raw materials. Each task type (summarization, sentiment,
classification, QA) includes:
- task_prompt: the prompt sent to the LLM under test
- designer_prompt: the prompt for the Designer LLM to produce reference answers
- scoring_rubric: default scoring criteria (1-5 scale)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Summarization
# ---------------------------------------------------------------------------

SUMMARIZATION_TASK_PROMPT = """\
請閱讀以下文章，並撰寫一份約 100 字的繁體中文摘要。摘要須涵蓋文章的核心論點、關鍵事實與結論，語句通順且不遺漏重要資訊。

標題：{title}

文章內容：
{content}

請直接輸出摘要，不要加任何前綴或標題。"""

SUMMARIZATION_DESIGNER_PROMPT = """\
你是一位專業的 benchmark 題目設計師。請根據以下素材，完成兩項工作：

1. **reference_answer**：撰寫一份約 100 字的繁體中文參考摘要，涵蓋文章核心論點、關鍵事實與結論。
2. **scoring_rubric**：根據文章內容，列出此摘要任務的具體評分要點（哪些關鍵資訊必須被提及）。

標題：{title}

文章內容：
{content}

請以 JSON 格式回傳：
{{
    "reference_answer": "你的參考摘要",
    "scoring_rubric": "針對本文的具體評分要點"
}}"""

SUMMARIZATION_SCORING_RUBRIC = """\
摘要評分標準（1-5 分）：
5 分：完整涵蓋所有核心論點與關鍵事實，語句通順精練，無冗餘或遺漏。
4 分：涵蓋大部分核心資訊，有少量細節遺漏，整體表達清晰。
3 分：涵蓋主要論點但遺漏部分關鍵事實，或表達略有不順。
2 分：僅提及部分資訊，遺漏多項重點，或有明顯事實錯誤。
1 分：摘要與原文嚴重不符、資訊錯誤、或幾乎未觸及核心內容。"""

# ---------------------------------------------------------------------------
# Sentiment Analysis
# ---------------------------------------------------------------------------

SENTIMENT_TASK_PROMPT = """\
請閱讀以下文章，判斷其整體情感傾向，並說明判斷理由。

情感類別：positive（正面）、negative（負面）、neutral（中性）

標題：{title}

文章內容：
{content}

請以 JSON 格式回傳：
{{
    "sentiment": "positive 或 negative 或 neutral",
    "reasoning": "你的判斷理由"
}}"""

SENTIMENT_DESIGNER_PROMPT = """\
你是一位專業的 benchmark 題目設計師。請根據以下素材，完成兩項工作：

1. **reference_answer**：判斷文章的整體情感傾向（positive / negative / neutral），並提供詳細的判斷依據，包含支持該情感判斷的關鍵詞句。
2. **scoring_rubric**：列出此情感分析任務的具體評分要點（哪些線索應被辨識、哪些語句暗示情感方向）。

標題：{title}

文章內容：
{content}

請以 JSON 格式回傳：
{{
    "reference_answer": {{
        "sentiment": "positive 或 negative 或 neutral",
        "reasoning": "詳細判斷依據"
    }},
    "scoring_rubric": "針對本文的具體評分要點"
}}"""

SENTIMENT_SCORING_RUBRIC = """\
情感分析評分標準（1-5 分）：
5 分：情感判斷正確，理由充分且引用文中具體語句作為佐證，邏輯清晰。
4 分：情感判斷正確，理由合理但佐證稍嫌不足。
3 分：情感判斷正確但理由薄弱，或判斷略有偏差但理由部分合理。
2 分：情感判斷錯誤但理由中有部分合理觀察，或判斷正確但理由完全不相關。
1 分：情感判斷錯誤且理由不合邏輯，或未遵循回傳格式。"""

# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

CLASSIFICATION_TASK_PROMPT = """\
請閱讀以下文章，將其分類到最適合的類別中，並說明分類理由。

可選類別：politics（政治）、technology（科技）、finance（財經）、entertainment（娛樂）、sports（體育）、society（社會）、international（國際）、other（其他）

標題：{title}

文章內容：
{content}

請以 JSON 格式回傳：
{{
    "category": "類別名稱（英文）",
    "reasoning": "你的分類理由"
}}"""

CLASSIFICATION_DESIGNER_PROMPT = """\
你是一位專業的 benchmark 題目設計師。請根據以下素材，完成兩項工作：

1. **reference_answer**：將文章分類到最適合的類別（politics / technology / finance / entertainment / sports / society / international / other），並說明為何選擇此類別，包含文中支持分類的關鍵線索。
2. **scoring_rubric**：列出此分類任務的具體評分要點（文章中哪些元素指向正確類別、可能造成混淆的因素）。

標題：{title}

文章內容：
{content}

請以 JSON 格式回傳：
{{
    "reference_answer": {{
        "category": "正確類別（英文）",
        "reasoning": "詳細分類依據"
    }},
    "scoring_rubric": "針對本文的具體評分要點"
}}"""

CLASSIFICATION_SCORING_RUBRIC = """\
文章分類評分標準（1-5 分）：
5 分：分類完全正確，理由清晰且指出文中關鍵分類線索。
4 分：分類正確，理由合理但未充分指出關鍵線索。
3 分：分類正確但理由薄弱，或分類到相近類別且理由部分合理。
2 分：分類錯誤但選擇了相關類別，或分類正確但理由完全不相關。
1 分：分類完全錯誤且理由不合邏輯，或未遵循回傳格式。"""

# ---------------------------------------------------------------------------
# Question Answering
# ---------------------------------------------------------------------------

QA_TASK_PROMPT = """\
請閱讀以下文章，並根據文章內容產生 3 個問答對。每個問答對應包含：
- 一個需要理解文章才能回答的問題
- 一個完整且準確的答案

問題應涵蓋文章的不同面向（例如：事實型、推論型、觀點型），避免過於簡單或可直接從標題得知答案的問題。

標題：{title}

文章內容：
{content}

請以 JSON 格式回傳：
{{
    "qa_pairs": [
        {{"question": "問題1", "answer": "答案1"}},
        {{"question": "問題2", "answer": "答案2"}},
        {{"question": "問題3", "answer": "答案3"}}
    ]
}}"""

QA_DESIGNER_PROMPT = """\
你是一位專業的 benchmark 題目設計師。請根據以下素材，完成兩項工作：

1. **reference_answer**：產生 3 個高品質的問答對作為參考標準。問題應涵蓋不同面向：
   - 至少一個事實型問題（答案可直接從文中找到）
   - 至少一個推論型問題（需要綜合文中資訊才能回答）
   - 至少一個觀點/分析型問題（需要理解文章立場或影響）
   每個答案應完整且準確，可作為評分依據。

2. **scoring_rubric**：列出此問答任務的具體評分要點（問題品質的判斷標準、答案正確性的驗證依據）。

標題：{title}

文章內容：
{content}

請以 JSON 格式回傳：
{{
    "reference_answer": {{
        "qa_pairs": [
            {{"question": "問題1", "answer": "參考答案1", "type": "factual/inferential/analytical"}},
            {{"question": "問題2", "answer": "參考答案2", "type": "factual/inferential/analytical"}},
            {{"question": "問題3", "answer": "參考答案3", "type": "factual/inferential/analytical"}}
        ]
    }},
    "scoring_rubric": "針對本文的具體評分要點"
}}"""

QA_SCORING_RUBRIC = """\
問答生成評分標準（1-5 分）：
5 分：產生 3 個高品質問答對，問題涵蓋不同面向且具深度，答案完整準確且有文中佐證。
4 分：產生 3 個問答對，問題品質良好但面向多樣性稍不足，答案大致正確。
3 分：產生 3 個問答對但品質參差不齊，部分問題過於簡單或答案不夠完整。
2 分：問答對數量不足，或多數問題品質低落（過於淺顯、與文章關聯薄弱），答案有錯誤。
1 分：未能產生有效問答對，或問答內容與文章嚴重不符，或未遵循回傳格式。"""

# ---------------------------------------------------------------------------
# Registry and accessor
# ---------------------------------------------------------------------------

_PROMPT_REGISTRY: dict[str, dict[str, str]] = {
    "summarization": {
        "task_prompt": SUMMARIZATION_TASK_PROMPT,
        "designer_prompt": SUMMARIZATION_DESIGNER_PROMPT,
        "scoring_rubric": SUMMARIZATION_SCORING_RUBRIC,
    },
    "sentiment": {
        "task_prompt": SENTIMENT_TASK_PROMPT,
        "designer_prompt": SENTIMENT_DESIGNER_PROMPT,
        "scoring_rubric": SENTIMENT_SCORING_RUBRIC,
    },
    "classification": {
        "task_prompt": CLASSIFICATION_TASK_PROMPT,
        "designer_prompt": CLASSIFICATION_DESIGNER_PROMPT,
        "scoring_rubric": CLASSIFICATION_SCORING_RUBRIC,
    },
    "qa": {
        "task_prompt": QA_TASK_PROMPT,
        "designer_prompt": QA_DESIGNER_PROMPT,
        "scoring_rubric": QA_SCORING_RUBRIC,
    },
}


def get_prompts(task_type: str) -> dict[str, str]:
    """Return the prompt templates for the given task type.

    Parameters
    ----------
    task_type:
        One of ``"summarization"``, ``"sentiment"``, ``"classification"``,
        ``"qa"``.

    Returns
    -------
    dict with keys ``task_prompt``, ``designer_prompt``, ``scoring_rubric``.

    Raises
    ------
    ValueError
        If *task_type* is not a recognised task.
    """
    key = task_type.lower().strip()
    if key not in _PROMPT_REGISTRY:
        valid = ", ".join(sorted(_PROMPT_REGISTRY))
        raise ValueError(
            f"Unknown task type {task_type!r}. Valid types: {valid}"
        )
    return _PROMPT_REGISTRY[key]
