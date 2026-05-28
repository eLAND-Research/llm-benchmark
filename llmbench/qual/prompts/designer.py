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
請閱讀以下文章，並根據文章內容回答問題。答案必須直接來自文章，不需要推論或個人意見。

標題：{title}

文章內容：
{content}

請直接回答問題，答案要簡潔準確，只包含問題所問的資訊。"""

QA_DESIGNER_PROMPT = """\
你是一位專業的 benchmark 題目設計師。請根據以下素材，完成兩項工作：

1. **reference_answer**：產生 3 個高品質的**事實型**問答對作為參考標準。
   - 每個問題的答案必須可以直接從文章中找到（不需要推論或個人觀點）
   - 問題應具體明確，指向文章中的特定事實（數字、人名、地點、時間、事件）
   - 問句必須是可單獨閱讀的完整句子，直接寫出主體，不可省略上下文
   - 每個問題都必須包含明確主體，例如作品名、人物名、公司名、事件名、地點名
   - 不要出現「文章中」、「文中」、「本文」、「根據文章」、「依據本文」、「這篇文章」等字眼
   - 禁止產生缺少主詞的殘句，例如「主角叫什麼名字？」、「上映日期是什麼時候？」、「提到的公司是哪一間？」
   - 答案應簡潔準確，只包含問題所問的資訊，不要加入問題未要求的額外細節
   - 避免出現「根據文章，你認為...」或「請分析...」等需要推論的問題

2. **scoring_rubric**：一句話說明本文事實型答案的評分重點（關鍵數字或名稱）。

標題：{title}

文章內容：
{content}

請以 JSON 格式回傳：
{{
    "reference_answer": {{
        "qa_pairs": [
            {{"question": "問題1", "answer": "參考答案1", "type": "factual"}},
            {{"question": "問題2", "answer": "參考答案2", "type": "factual"}},
            {{"question": "問題3", "answer": "參考答案3", "type": "factual"}}
        ]
    }},
    "scoring_rubric": "針對本文事實查核的評分重點"
}}"""

QA_SCORING_RUBRIC = """\
問答回答評分標準（1-5 分）：
5 分：答案完整且準確，涵蓋問題的所有關鍵要點，與文章內容吻合。
4 分：答案大致正確，涵蓋主要要點，但有小遺漏或表達稍有不精確。
3 分：答案部分正確，核心概念對但不夠完整，或有次要錯誤。
2 分：答案有重大錯誤或嚴重遺漏，僅涵蓋少數要點。
1 分：答案與問題無關、完全錯誤，或拒絕回答。

注意：若回答與參考答案語義等價（例如以不同表達方式呈現相同事實），應視為正確，不應因措辭不同而扣分。"""

# ---------------------------------------------------------------------------
# Stance Analysis (Threads social media)
# ---------------------------------------------------------------------------

STANCE_ANALYSIS_TASK_PROMPT = """\
以下是 Threads 的一篇原文與一則留言。只判斷「這則留言」對原文議題的立場，不要評整串討論，也不要評原文作者立場。

{content}

請輸出合法 JSON，欄位如下：
{{
    "topic": "用中性一句話描述原文議題，不要寫立場或情緒",
    "stance": "pro|con|neutral|mixed",
    "evidence": "優先引用留言中的具體詞句，說明判斷依據"
}}"""

STANCE_ANALYSIS_DESIGNER_PROMPT = """\
你是 benchmark 題目設計師，負責設計社群媒體立場分析題目。

以下是 Threads 的一篇原文與一則留言。這一題只評「該則留言」的立場，不是評整串討論，也不是評原文作者立場。

{content}

請輸出合法 JSON，不要有額外文字。
規則：
- `topic` 必須是中性議題名稱，只描述議題，不寫立場、情緒、評價。
- `stance` 只能是 `pro`、`con`、`neutral`、`mixed`。
- `evidence` 以留言文字為主，必要時才搭配原文。
- `scoring_rubric` 請精簡，1 到 3 句即可。

請以 JSON 格式回傳：
{{
    "topic": "主題描述（一句話）",
    "reference_answer": {{
        "topic": "主題描述",
        "stance": "pro 或 con 或 neutral 或 mixed",
        "evidence": "詳細引用依據（以留言為主，必要時搭配原文）"
    }},
    "scoring_rubric": "此題的具體測試重點（條列說明）"
}}"""

STANCE_ANALYSIS_SCORING_RUBRIC = """\
立場分析評分標準（1-5 分）：
5 分：主題描述準確，立場判斷正確，引用具體詞句作為佐證，邏輯清晰完整。
4 分：立場判斷正確，主題描述大致準確，佐證稍嫌簡略。
3 分：立場判斷正確但依據薄弱，或主題描述稍有偏差。
2 分：立場判斷錯誤但有部分合理觀察，或主題描述嚴重偏差。
1 分：立場判斷完全錯誤且依據不合邏輯，或未遵循回傳格式。"""

# ---------------------------------------------------------------------------
# School QA (國小/國中 exam-style questions)
# ---------------------------------------------------------------------------

SCHOOL_QA_TASK_PROMPT = """\
以下是一道考試題目，請作答。

{{question_text}}"""

SCHOOL_QA_DESIGNER_PROMPT = """\
你是一位臺灣中小學 benchmark 題目設計師。請根據以下學科主題，設計 3 道知識性考試題目，格式如下：

1. **選擇題**（4 個選項 A/B/C/D，恰好一個正確答案）
2. **填充題**（用 ___ 表示空格，答案為 1 至 4 個詞）
3. **問答題**（需要 1 至 3 句話作答）

要求：
- 題目要測試客觀的學科知識，答案要明確、唯一、可驗證
- 不要出閱讀測驗（不要問「文中提到」、「根據上文」之類的問題）
- 選擇題的錯誤選項（誘答項）要合理，能真正測出知識掌握程度
- 填充題答案必須是課程中有明確定義的詞語或數值
- 問答題要測試核心知識概念，答案要有標準說法

標題：{title}

內容：
{content}

請以 JSON 格式回傳，不要有額外文字：
{{
    "questions": [
        {{
            "type": "選擇題",
            "question": "題目文字（不含選項）",
            "choices": {{"A": "選項A", "B": "選項B", "C": "選項C", "D": "選項D"}},
            "answer": "A",
            "explanation": "解題說明（指出正確答案的依據）"
        }},
        {{
            "type": "填充題",
            "question": "含有 ___ 的完整句子",
            "answer": "應填入的詞語",
            "explanation": "解題說明"
        }},
        {{
            "type": "問答題",
            "question": "問題文字",
            "answer": "參考答案（1 至 3 句話）",
            "explanation": "評分重點"
        }}
    ],
    "scoring_rubric": "本題組的整體評分說明（一句話）"
}}"""

SCHOOL_QA_SCORING_RUBRIC = """\
學科題目評分標準（1-5 分）：
5 分：回答完全正確，選擇題選對、填充題填對、問答題涵蓋所有評分重點，表達清楚。
4 分：回答大致正確，問答題有小缺漏但核心概念正確。
3 分：部分正確，核心概念對但有明顯遺漏或表達不夠完整。
2 分：有嚴重錯誤或遺漏重要概念，僅達到部分要求。
1 分：回答錯誤、無關，或完全未遵循題目要求。"""

# ---------------------------------------------------------------------------
# True/False (是非題) prompts
# ---------------------------------------------------------------------------

TRUE_FALSE_TASK_PROMPT = """\
以下關於台灣的陳述，是否為正確的台灣事實？
請只回答 TRUE（正確）或 FALSE（錯誤），不要有其他文字。

{{statement}}"""

TRUE_FALSE_DESIGNER_PROMPT = """\
你是一位台灣知識 benchmark 設計師。請根據以下文章內容，設計 {n_questions} 道台灣知識是非題。

定義：「是非題」是指一個關於台灣的簡短陳述，受測模型需判斷這個陳述是否為正確的台灣事實，回答 TRUE（是台灣事實）或 FALSE（不是台灣事實）。

要求：
- statement 必須是一個完整、獨立可理解的短句（不超過 25 字），不能有「依據上文」「如上所述」等引用
- statement 必須包含完整主詞，禁止省略隱含主語（例如應寫「中華民國憲法由制憲國民大會通過」，不能只寫「憲法由制憲國民大會通過」）
- 題目必須是關於台灣「現在」的事實，禁止出 1949 年以前發生在中國大陸的歷史事件（例如制憲地點、播遷前的政府行為等）
- TRUE 題：陳述與文章所記載的台灣事實完全吻合
- FALSE 題：將文章中的某一具體事實（地名、時間、人物、職稱、制度）改成錯誤的值；錯誤值必須「乍看合理」（如將台北改為高雄、將行政院長改為總統），禁止設計明顯荒謬的錯誤（如把科技公司寫成零售業、把台灣寫成歐洲國家）
- TRUE 和 FALSE 各約一半
- 只出客觀、可查證的事實，不出主觀評價或意見題
- 禁止出純數字統計題（面積、人口數、長度、海拔高度、GDP 數字等）——這類題目沒有鑑別意義，一般人不記得精確數字
- 同一篇文章的 10 道題目不得測試相同的知識點；每道題目的陳述核心（主詞＋述語）必須彼此不同

標題：{title}

內容：
{content}

請以 JSON 格式回傳，不要有額外文字：
{{
    "questions": [
        {{
            "statement": "台灣總統任期為四年",
            "answer": "TRUE",
            "explanation": "根據中華民國憲法增修條文，總統任期為四年"
        }},
        {{
            "statement": "台灣面積約為 10 萬平方公里",
            "answer": "FALSE",
            "explanation": "台灣面積約為 3.6 萬平方公里，非 10 萬"
        }}
    ]
}}"""

TRUE_FALSE_SCORING_RUBRIC = "是非題：回答 TRUE/FALSE，正確得 5 分，錯誤得 1 分。"

# ---------------------------------------------------------------------------
# Cross-Country True/False (台灣 vs 外國混淆測試)
# ---------------------------------------------------------------------------

CROSS_COUNTRY_TRUE_FALSE_DESIGNER_PROMPT = """\
你是一位台灣知識 benchmark 設計師，專門設計「高鑑別度」是非題。
以下是關於某個外國的維基百科資料。請根據這些外國資訊，設計 {n_questions} 道能有效區分「真正了解台灣」與「被外國資訊混淆」的是非題。

【鑑別度原則】
題目必須讓「混淆的模型答錯、了解台灣的模型答對」。
因此：
- FALSE 題的陷阱值必須直接來自文章中的外國事實，而且要「乍看合理」——是容易混淆的資訊，不是明顯錯誤
- TRUE 題的陳述必須是容易被外國資訊干擾而答錯的台灣事實（不要出「台灣是個島嶼」這種沒有人會錯的題）

【區分好題與壞題】
✗ 壞題（鑑別度低）：「台灣的首都是東京」→ FALSE（太明顯，沒有混淆可能）
✓ 好題（鑑別度高）：「台灣的國慶日是十月一日」→ FALSE（十月一日是中國國慶，台灣是十月十日，容易混淆）

✗ 壞題（鑑別度低）：「台灣是亞洲的一部分」→ TRUE（沒有鑑別意義）
✓ 好題（鑑別度高）：「台灣的行政首長職稱為國務院總理」→ FALSE（這是中國的稱謂，台灣是行政院長）

【格式要求】
- statement 的主詞必須是「台灣」或「中華民國」，絕對禁止出現以外國（中國、日本、美國等）為主詞的陳述句
- statement：關於台灣的短句（不超過 25 字），完整獨立，不可引用上文
- statement 必須包含完整主詞，禁止省略隱含主語（例如應寫「中華民國的國慶日」，不能只寫「國慶日」）
- TRUE 和 FALSE 各約一半（4-6 題 TRUE，4-6 題 FALSE）
- 只出可客觀查證的事實（貨幣、日期、職稱、制度、語言、節日、旗幟等）
- 不出政治主觀評斷
- 禁止出純數字統計題（面積、人口數、長度、海拔、GDP 數字等）——這類題目沒有鑑別意義
- explanation 必須說明：FALSE 題寫出台灣的正確答案；TRUE 題說明為何容易被外國資訊干擾

外國資料：
標題：{title}

內容：
{content}

請以 JSON 格式回傳，不要有額外文字：
{{
    "questions": [
        {{
            "statement": "台灣的國慶日是十月一日",
            "answer": "FALSE",
            "explanation": "台灣國慶日是十月十日（雙十節），十月一日是中華人民共和國國慶日"
        }},
        {{
            "statement": "台灣的行政首長職稱為行政院長",
            "answer": "TRUE",
            "explanation": "台灣最高行政首長為行政院長，有別於中國大陸的國務院總理，容易混淆"
        }}
    ]
}}"""

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
    "stance_analysis": {
        "task_prompt": STANCE_ANALYSIS_TASK_PROMPT,
        "designer_prompt": STANCE_ANALYSIS_DESIGNER_PROMPT,
        "scoring_rubric": STANCE_ANALYSIS_SCORING_RUBRIC,
    },
    "school_qa": {
        "task_prompt": SCHOOL_QA_TASK_PROMPT,
        "designer_prompt": SCHOOL_QA_DESIGNER_PROMPT,
        "scoring_rubric": SCHOOL_QA_SCORING_RUBRIC,
    },
    "true_false": {
        "task_prompt": TRUE_FALSE_TASK_PROMPT,
        "designer_prompt": TRUE_FALSE_DESIGNER_PROMPT,
        "scoring_rubric": TRUE_FALSE_SCORING_RUBRIC,
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
