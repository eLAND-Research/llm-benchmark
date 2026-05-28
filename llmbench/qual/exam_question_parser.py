"""Parser for Taiwanese school exam PDFs.

Extracts individual questions from exam paper text and matches them with
answers from answer sheet text.

Supports the most common formats used in Taiwanese school exams:
- 單選題 (MCQ) with (Ａ)(Ｂ)(Ｃ)(Ｄ) full-width options
- 答案卷 answer sheets in "11. B 12. A" or "題號/答案" table formats

Returns a list of structured question dicts, ready for direct use as
BenchmarkItems without going through the Designer LLM.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Character normalisation helpers
# ---------------------------------------------------------------------------

_FW_TO_ASCII: Dict[str, str] = {
    # Full-width option letters A-D
    "Ａ": "A", "Ｂ": "B", "Ｃ": "C", "Ｄ": "D",
    "ａ": "A", "ｂ": "B", "ｃ": "C", "ｄ": "D",
    "A": "A", "B": "B", "C": "C", "D": "D",
    "a": "A", "b": "B", "c": "C", "d": "D",
    # Circled digits 1-4 used in math exams
    "①": "1", "②": "2", "③": "3", "④": "4",
    # Full-width digits
    "１": "1", "２": "2", "３": "3", "４": "4",
    "1": "1", "2": "2", "3": "3", "4": "4",
}


def _norm_option(ch: str) -> str:
    return _FW_TO_ASCII.get(ch, ch.upper())


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Section header: 一、 二、 三、 ...
_SECTION_RE = re.compile(
    r"^[一二三四五六七八九十百]+[、,，。]\s*(.{0,30})",
    re.MULTILINE,
)

# MCQ sections keywords
_MCQ_KEYWORDS = re.compile(r"選擇|單選|複選|題組")

# Question number line (with optional answer blank 「（ ）」 or nothing)
_Q_RE = re.compile(
    r"^(\d{1,3})[.．。]\s*(?:[（(]\s*[）)]\s*)?(.{2,})",
    re.MULTILINE,
)

# MCQ choice on its own line or inline:
# matches （Ａ）text, (A)text, (１)text, （1）text
_CHOICE_RE = re.compile(
    r"[（(]([ＡＢＣＤabcdABCD１２３４1234])[）)]\s*([^\n（(]{1,120})"
)

# Answer-key patterns in answer sheets:

# Format 1a: "11. B  12. A  13. D ..." (period separator)
_ANS_INLINE_RE = re.compile(
    r"(\d{1,3})[.．。]\s*([ABCDabcd１２３４1234ＡＢＣＤabcd])\b"
)

# Format 1b: "11 B  12 A  13 D ..." (space separator, no period) — common in 學測/指考
_ANS_INLINE_NOPUNCT_RE = re.compile(
    r"(?<!\d)(\d{1,3})\s+([ABCDabcd１２３４1234ＡＢＣＤ])\b"
)

# Format 2: 題號 row + 答案 row (table style)
_ANS_TABLE_QNO_RE = re.compile(r"題號\s+([\d\s]+)")
_ANS_TABLE_ANS_RE = re.compile(r"答案\s+([A-Da-d１-４1-4ＡＢＣＤabcd\s]+)")

# Format 3: plain row-of-10 (e.g. English answer sheets)
_ANS_ROW10_RE = re.compile(
    r"^(?:[ABCDabcd１-４1-4ＡＢＣＤabcd]\s+){4,}[ABCDabcd１-４1-4ＡＢＣＤabcd]",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_mcq_questions(text: str) -> List[Dict]:
    """Extract MCQ questions from exam paper text.

    Returns a list of dicts::

        {
            "number": 11,
            "question": "question stem text",
            "choices": {"A": "...", "B": "...", "C": "...", "D": "..."},
            "answer": "",   # filled later by match_answers()
        }
    """
    if not text:
        return []

    # Find MCQ sections
    sections = _split_into_sections(text)
    mcq_blocks = [s for s in sections if _MCQ_KEYWORDS.search(s["header"])]

    # Fallback: if no explicitly labelled MCQ section, try the whole text
    if not mcq_blocks:
        mcq_blocks = [{"header": "", "body": text}]

    questions: List[Dict] = []
    for block in mcq_blocks:
        questions.extend(_extract_questions_from_block(block["body"]))

    # De-duplicate by question number
    seen: set[int] = set()
    unique: List[Dict] = []
    for q in questions:
        if q["number"] not in seen:
            seen.add(q["number"])
            unique.append(q)

    return sorted(unique, key=lambda q: q["number"])


def parse_answer_key(text: str) -> Dict[int, str]:
    """Extract answer key from answer sheet text.

    Returns ``{question_number: "A" | "B" | "C" | "D"}``.
    """
    answers: Dict[int, str] = {}

    # --- Format 2: 題號 / 答案 table ---
    qno_m = _ANS_TABLE_QNO_RE.search(text)
    ans_m = _ANS_TABLE_ANS_RE.search(text)
    if qno_m and ans_m:
        numbers = [int(n) for n in qno_m.group(1).split() if n.isdigit()]
        raw_ans = ans_m.group(1).split()
        for n, a in zip(numbers, raw_ans):
            answers[n] = _norm_option(a)
        if answers:
            return answers

    # --- Format 1a: "11. B  12. A ..." (with period) ---
    for m in _ANS_INLINE_RE.finditer(text):
        n, a = int(m.group(1)), _norm_option(m.group(2))
        if a in ("A", "B", "C", "D", "1", "2", "3", "4"):
            answers[n] = a
    if answers:
        return answers

    # --- Format 1b: "11 B  12 A ..." (space, no period) ---
    for m in _ANS_INLINE_NOPUNCT_RE.finditer(text):
        n, a = int(m.group(1)), _norm_option(m.group(2))
        if a in ("A", "B", "C", "D", "1", "2", "3", "4"):
            answers[n] = a
    if answers:
        return answers

    # --- Format 3: plain rows of single-letter answers ---
    rows = _ANS_ROW10_RE.findall(text)
    if rows:
        all_letters = []
        for row in rows:
            all_letters.extend([_norm_option(c) for c in row.split()])
        for i, a in enumerate(all_letters, start=1):
            answers[i] = a
        if answers:
            return answers

    # --- Format 4: number and letter on alternating lines (column-table PDF extraction)
    # e.g. "1\nC\n21\nD\n41\nA\n..."
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    alt_answers: Dict[int, str] = {}
    idx = 0
    while idx < len(lines) - 1:
        num_line = lines[idx]
        let_line = lines[idx + 1]
        if re.fullmatch(r"\d{1,3}", num_line):
            norm = _norm_option(let_line)
            if norm in ("A", "B", "C", "D", "1", "2", "3", "4"):
                alt_answers[int(num_line)] = norm
                idx += 2
                continue
        idx += 1
    if len(alt_answers) >= 5:
        return alt_answers

    return answers


def match_answers(questions: List[Dict], answer_key: Dict[int, str]) -> List[Dict]:
    """Fill in the ``answer`` field of each question from the answer key."""
    for q in questions:
        n = q["number"]
        if n in answer_key:
            q["answer"] = answer_key[n]
    return questions


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _split_into_sections(text: str) -> List[Dict]:
    """Split text into sections by header lines like 一、 二、 ..."""
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        return [{"header": "", "body": text}]

    sections = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append({
            "header": m.group(1).strip(),
            "body": text[start:end],
        })
    return sections


_NOISE_LINE = re.compile(
    r"^\s*("
    r"[（(][ＡＢＣＤabcdABCD１２３４1234][）)]"  # MCQ choice line
    r"|[-－—]+\s*\d+\s*[-－—]+"                  # page number:  - 10 -
    r"|第\s*\d+\s*頁"                             # page header:  第 11 頁
    r"|共\s*\d+\s*頁"                             # page header:  共 17 頁
    r"|\d+\s*年\s*學測"                           # exam label:   111年學測
    r"|\d+-\d+\s*為題組"                          # group label:  42-43 為題組
    r")"
)


def _clean_passage(text: str) -> str:
    """Remove noise lines (MCQ choices, page numbers, headers) from between-question text.

    Keeps lines starting with ◎ or plain prose. Used to extract 題組 passages.
    """
    # If there's a ◎ marker, start from there — it's the reliable passage start
    marker = text.find("◎")
    if marker != -1:
        text = text[marker:]
    lines = []
    for line in text.splitlines():
        if _NOISE_LINE.match(line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _extract_questions_from_block(block: str) -> List[Dict]:
    """Extract individual questions (with choices) from a text block."""
    # Find all question-number positions
    q_matches = list(_Q_RE.finditer(block))
    questions = []

    for idx, m in enumerate(q_matches):
        q_num = int(m.group(1))
        # The text for this question spans until the next question starts
        start = m.start()
        end = q_matches[idx + 1].start() if idx + 1 < len(q_matches) else len(block)
        q_block = block[start:end].strip()

        stem, choices = _parse_question_block(q_block, q_num)
        if not stem:
            continue

        # Collect passage text that precedes this question (題組 context).
        # Use the start of the previous question's block (not just its regex
        # end) so we skip its choices.  Then strip noise lines.
        prev_q_start = q_matches[idx - 1].start() if idx > 0 else 0
        raw_between = block[prev_q_start:start] if idx > 0 else block[:start]
        passage = _clean_passage(raw_between)
        _REF_PATTERN = re.compile(r"題文|上文|下文|上述|以下圖|以下表|以下資料|依據.*?判斷|根據.*?回答")
        if passage and len(passage) > 20 and _REF_PATTERN.search(stem):
            stem = passage + "\n\n" + stem

        questions.append({
            "number": q_num,
            "question": stem,
            "choices": choices,
            "answer": "",
        })

    return questions


def _parse_question_block(block: str, q_num: int) -> tuple[str, Dict[str, str]]:
    """Parse a single question block into (stem, choices_dict).

    Returns empty stem if no valid MCQ choices are found.
    """
    choice_spans = list(_CHOICE_RE.finditer(block))

    # Require at least 3 choices to count as MCQ
    if len(choice_spans) < 3:
        return "", {}

    # The stem is everything before the first choice
    stem_end = choice_spans[0].start()
    # Strip the question number prefix from the stem
    stem_raw = block[:stem_end].strip()
    stem = re.sub(rf"^{q_num}[.．。]\s*[（(]?\s*[）)]?\s*", "", stem_raw).strip()
    stem = stem.rstrip("（").strip()

    choices: Dict[str, str] = {}
    for m in choice_spans:
        key = _norm_option(m.group(1))
        val = m.group(2).strip()
        if key and val:
            choices[key] = val

    # Valid MCQ needs A, B, C, D (or 1,2,3,4 for math)
    if len(choices) < 3:
        return "", {}

    return stem, choices
