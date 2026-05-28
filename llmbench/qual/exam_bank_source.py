"""Exam bank data source for the qual pipeline.

Downloads and parses Taiwanese elementary / middle school exam PDFs.

Two modes:
- ``parse_questions=False`` (default): full PDF text → RawMaterial.content
  (Designer LLM generates questions from the article text)
- ``parse_questions=True``: directly parse MCQ questions from the PDF,
  match with answer sheets, embed as JSON in RawMaterial.content
  (Designer is bypassed; each question becomes a BenchmarkItem directly)

Two backends are supported (both can be active simultaneously):
1. **Zip archives** -- PDFs extracted in-memory from local ``.zip`` files.
2. **Manifest CSV / JSON** -- PDFs downloaded from remote URLs and cached locally.

Requires: ``pdfplumber >= 0.11``

Content marker for pre-parsed questions:
    ``__PARSED_QUESTIONS__\\n<JSON list>``
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests

from llmbench.qual.schemas import RawMaterial

logger = logging.getLogger(__name__)


def _resolve_path(path: str) -> str:
    """Normalise a file path from user input.

    - Strips surrounding quotes (single or double).
    - On Linux/WSL: converts Windows-style paths (C:\\...) to /mnt/c/...
    - On Windows: keeps the path as-is (backslashes are valid).
    """
    import re as _re
    import sys

    # Strip surrounding quotes (handles "path" or 'path')
    p = path.strip()
    while len(p) >= 2 and p[0] in ('"', "'") and p[-1] == p[0]:
        p = p[1:-1].strip()

    # On Linux/WSL only: convert Windows drive paths to mount paths
    if sys.platform != "win32":
        win_match = _re.match(r'^([A-Za-z]):[/\\](.*)', p)
        if win_match:
            drive = win_match.group(1).lower()
            rest = win_match.group(2).replace('\\', '/')
            p = f"/mnt/{drive}/{rest}"

    return p


# Minimum number of Chinese characters to consider a page as "text-based"
_MIN_CHINESE_CHARS = 30
# Minimum total text length for a useful RawMaterial
_MIN_CONTENT_LENGTH = 100

# Mapping keywords in school names → level
_SCHOOL_LEVEL_RULES: list[tuple[str, str]] = [
    ("高一", "high_school"),
    ("高二", "high_school"),
    ("高三", "high_school"),
    ("高職", "high_school"),
    ("學測", "high_school"),
    ("指考", "high_school"),
    ("高中", "high_school"),
    ("國小", "elementary"),
    ("小學", "elementary"),
    ("國中", "middle_school"),
    ("中學", "middle_school"),
]

# Subject normalisation (label substring → canonical subject name)
_SUBJECT_ALIASES: Dict[str, str] = {
    "國文": "國文",
    "國語": "國文",
    "語文": "國文",
    "英文": "英語",
    "英語": "英語",
    "數學": "數學",
    "自然": "自然",
    "社會": "社會",
    "理化": "理化",
    "生物": "生物",
    "地理": "地理",
    "歷史": "歷史",
    "公民": "公民",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


PARSED_QUESTIONS_MARKER = "__PARSED_QUESTIONS__"


def load_exam_bank_materials(
    manifest: Optional[str] = None,
    zip_archives: Optional[List[str]] = None,
    level: str = "both",
    subjects: Optional[List[str]] = None,
    grades: Optional[List[str]] = None,
    cache_dir: str = "data/exam_bank/pdf_cache",
    limit: Optional[int] = None,
    download_timeout: int = 30,
    max_download_workers: int = 4,
    parse_questions: bool = False,
) -> List[RawMaterial]:
    """Load exam PDFs and convert to :class:`RawMaterial` objects.

    Parameters
    ----------
    manifest:
        Path to a CSV or JSON manifest listing ``file_url``, ``subject``,
        ``grade``, ``school``, etc.  Use ``None`` to skip.
    zip_archives:
        List of paths to local ``.zip`` archives containing exam PDFs.
        Use ``None`` or ``[]`` to skip.
    level:
        ``"elementary"``, ``"middle_school"``, or ``"both"``.
    subjects:
        Subject filter, e.g. ``["國文", "數學"]``.  ``None`` = all.
    grades:
        Grade filter, e.g. ``["5", "6"]``.  ``None`` = all.
    cache_dir:
        Directory for caching downloaded PDFs.
    limit:
        Maximum number of materials to return.
    download_timeout:
        HTTP request timeout in seconds.
    max_download_workers:
        Max parallel download threads.

    Returns
    -------
    list[RawMaterial]
    """
    cache_path = Path(cache_dir)
    subject_set = {_normalise_subject(s) for s in subjects} if subjects else None
    grade_set = set(grades) if grades else None

    materials: List[RawMaterial] = []

    # --- Zip archives -------------------------------------------------------
    for archive in (zip_archives or []):
        if not archive or not archive.strip():
            continue
        archive_path = Path(_resolve_path(archive.strip()))
        if not archive_path.is_file():
            logger.warning("exam_bank: zip not found: %s", archive_path)
            continue
        logger.info("exam_bank: loading zip %s", archive_path.name)
        zip_materials = _load_from_zip(
            archive_path,
            level=level,
            subject_set=subject_set,
            grade_set=grade_set,
            parse_questions=parse_questions,
        )
        materials.extend(zip_materials)
        logger.info("exam_bank: %d materials from zip %s", len(zip_materials), archive_path.name)

    # --- Manifest -----------------------------------------------------------
    if manifest:
        manifest_path = Path(_resolve_path(manifest.strip()))
        if not manifest_path.exists():
            logger.warning("exam_bank: manifest not found: %s", manifest_path)
        else:
            logger.info("exam_bank: loading manifest %s", manifest_path.name)
            entries = _read_manifest(manifest_path)
            entries = _filter_entries(entries, level=level, subject_set=subject_set, grade_set=grade_set)
            logger.info("exam_bank: %d entries after filter", len(entries))

            manifest_materials = _download_and_parse(
                entries=entries,
                cache_dir=cache_path,
                timeout=download_timeout,
                max_workers=max_download_workers,
                limit=limit - len(materials) if limit else None,
            )
            materials.extend(manifest_materials)
            logger.info("exam_bank: %d materials from manifest", len(manifest_materials))

    if limit:
        materials = materials[:limit]

    logger.info("exam_bank: %d total materials loaded", len(materials))
    return materials


# ---------------------------------------------------------------------------
# Zip backend
# ---------------------------------------------------------------------------


def _load_from_zip(
    zip_path: Path,
    level: str,
    subject_set: Optional[set],
    grade_set: Optional[set],
    parse_questions: bool = False,
) -> List[RawMaterial]:
    materials: List[RawMaterial] = []

    try:
        with zipfile.ZipFile(str(zip_path)) as zf:
            # Build name → info map (decoded filenames)
            all_pdfs: Dict[str, object] = {}
            for info in zf.infolist():
                decoded = _decode_zip_filename(info.filename)
                if decoded.lower().endswith(".pdf"):
                    all_pdfs[decoded] = info

            if parse_questions:
                # Pair question papers with answer sheets
                pairs = _pair_question_answer_pdfs(list(all_pdfs.keys()))
                for q_name, a_name in pairs:
                    logger.info("exam_bank: pair — 題卷=%s  解答=%s", q_name, a_name or "（未配對）")
                    meta = _meta_from_filename(q_name, zip_path.stem)
                    if not _matches_filters(meta, level=level, subject_set=subject_set, grade_set=grade_set):
                        continue
                    try:
                        q_bytes = zf.read(all_pdfs[q_name].filename)
                        q_text = _extract_pdf_text_from_bytes(q_bytes)
                        a_text = ""
                        if a_name and a_name in all_pdfs:
                            a_bytes = zf.read(all_pdfs[a_name].filename)
                            a_text = _extract_pdf_text_from_bytes(a_bytes)
                        elif a_name:
                            logger.warning("exam_bank: 解答檔 %s 不在 zip 內", a_name)
                    except Exception as exc:
                        logger.warning("exam_bank: failed to read %s: %s", q_name, exc)
                        continue

                    mat = _make_parsed_questions_material(
                        q_text=q_text, a_text=a_text, meta=meta, source=zip_path.name
                    )
                    if mat:
                        materials.append(mat)
            else:
                for decoded_name, info in all_pdfs.items():
                    # Skip answer sheets in article mode
                    if _is_answer_sheet(decoded_name):
                        logger.debug("exam_bank: skipping answer sheet %s", decoded_name)
                        continue
                    meta = _meta_from_filename(decoded_name, zip_path.stem)
                    if not _matches_filters(meta, level=level, subject_set=subject_set, grade_set=grade_set):
                        logger.debug(
                            "exam_bank: filtered out %s (level=%s, subject=%s, grade=%s, filter level=%s)",
                            decoded_name, meta.get("level"), meta.get("subject"), meta.get("grade"), level,
                        )
                        continue
                    try:
                        pdf_bytes = zf.read(info.filename)
                        text = _extract_pdf_text_from_bytes(pdf_bytes)
                    except Exception as exc:
                        logger.warning("exam_bank: failed to read %s from zip: %s", decoded_name, exc)
                        continue
                    if len(text) < _MIN_CONTENT_LENGTH:
                        logger.debug("exam_bank: skipping short/scanned PDF %s", decoded_name)
                        continue
                    materials.append(_make_material(text=text, meta=meta, source=zip_path.name))

    except zipfile.BadZipFile as exc:
        logger.error("exam_bank: bad zip file %s: %s", zip_path, exc)

    return materials


def _decode_zip_filename(raw: str) -> str:
    """Attempt to decode a zip filename from cp437→big5 (Windows Chinese zips)."""
    try:
        return raw.encode("cp437").decode("big5")
    except Exception:
        return raw


def _is_answer_sheet(filename: str) -> bool:
    return "答案" in filename or "解答" in filename or "answer" in filename.lower()


def _pair_question_answer_pdfs(names: List[str]) -> List[tuple[str, Optional[str]]]:
    """Pair each question paper with its corresponding answer sheet.

    Matching heuristic: same year prefix (e.g. "105") and same subject keyword.
    Returns list of (question_pdf_name, answer_pdf_name_or_None).
    """
    q_papers = [n for n in names if not _is_answer_sheet(n)]
    a_sheets = [n for n in names if _is_answer_sheet(n)]

    pairs: List[tuple[str, Optional[str]]] = []
    for q in q_papers:
        year_m = re.search(r"(?<!\d)(1\d{2})(?!\d)", q)
        year = year_m.group(1) if year_m else ""
        subj = _infer_subject(q)
        # Find best matching answer sheet
        best_a: Optional[str] = None
        for a in a_sheets:
            a_year_m = re.search(r"(?<!\d)(1\d{2})(?!\d)", a)
            a_year = a_year_m.group(1) if a_year_m else ""
            if year and a_year and year != a_year:
                continue
            if subj and subj != "綜合" and _infer_subject(a) != subj:
                continue
            best_a = a
            break
        pairs.append((q, best_a))
    return pairs


def _make_parsed_questions_material(
    q_text: str, a_text: str, meta: Dict, source: str
) -> Optional[RawMaterial]:
    """Parse questions from exam text and return a RawMaterial with embedded JSON.

    Returns None if no valid MCQ questions are found.
    """
    from llmbench.qual.exam_question_parser import (
        parse_mcq_questions, parse_answer_key, match_answers,
    )

    questions = parse_mcq_questions(q_text)
    if not questions:
        logger.debug("exam_bank: no MCQ questions found in %s", meta.get("label", ""))
        return None

    if a_text:
        answer_key = parse_answer_key(a_text)
        if not answer_key:
            logger.warning(
                "exam_bank: parse_answer_key returned empty for %s — "
                "answer sheet format not recognized. First 300 chars: %r",
                meta.get("label", ""), a_text[:300],
            )
        questions = match_answers(questions, answer_key)
        answered = sum(1 for q in questions if q["answer"])
        if answered == 0 and questions:
            logger.warning(
                "exam_bank: 0/%d answers matched for %s — "
                "check question numbers vs answer key: %s",
                len(questions), meta.get("label", ""), dict(list(answer_key.items())[:5]),
            )
        else:
            logger.info("exam_bank: matched %d/%d answers for %s",
                        answered, len(questions), meta.get("label", ""))

    content = PARSED_QUESTIONS_MARKER + "\n" + json.dumps(questions, ensure_ascii=False)
    mat = _make_material(text=content, meta=meta, source=source)
    logger.info(
        "exam_bank: parsed %d MCQ questions from %s", len(questions), meta.get("label", source)
    )
    return mat


def _meta_from_filename(filename: str, archive_stem: str = "") -> Dict:
    """Extract subject, grade, and level from a PDF filename."""
    basename = Path(filename).stem  # strip path and .pdf

    subject = _infer_subject(basename)
    grade = _infer_grade(basename)

    # Try to infer level from the archive name or filename
    combined = archive_stem + " " + basename
    inferred_level = _infer_level_from_text(combined)

    return {
        "subject": subject,
        "grade": grade,
        "level": inferred_level,
        "label": basename,
        "school": "",
    }


def _infer_subject(text: str) -> str:
    for key, canonical in _SUBJECT_ALIASES.items():
        if key in text:
            return canonical
    return "綜合"


def _infer_grade(text: str) -> str:
    m = re.search(r"(\d)年", text)
    if m:
        return m.group(1)
    if "小六" in text or "六年" in text:
        return "6"
    if "小五" in text or "五年" in text:
        return "5"
    return ""


def _infer_level_from_text(text: str) -> str:
    for keyword, lv in _SCHOOL_LEVEL_RULES:
        if keyword in text:
            return lv
    # If it mentions 小六 or grades 1-6, assume elementary
    if re.search(r"[一二三四五六]年|小[一二三四五六]|小六", text):
        return "elementary"
    return "elementary"  # default


# ---------------------------------------------------------------------------
# Manifest backend
# ---------------------------------------------------------------------------


def _read_manifest(path: Path) -> List[Dict]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8-sig"))
    else:  # CSV (default)
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)


def _filter_entries(entries: List[Dict], level: str, subject_set, grade_set) -> List[Dict]:
    result = []
    for e in entries:
        if e.get("file_type", "pdf").lower() != "pdf":
            continue
        meta = {
            "subject": _normalise_subject(e.get("subject", "")),
            "grade": str(e.get("grade", "")),
            "level": _infer_level_from_text(e.get("school", "") + " " + e.get("label", "")),
            "label": e.get("label", ""),
            "school": e.get("school", ""),
        }
        if not _matches_filters(meta, level=level, subject_set=subject_set, grade_set=grade_set):
            continue
        e["_meta"] = meta
        result.append(e)
    return result


def _matches_filters(meta: Dict, level: str, subject_set, grade_set) -> bool:
    meta_level = meta.get("level", "")
    if level == "both":
        # "both" = 國小 + 國中，不包含高中
        if meta_level not in ("elementary", "middle_school"):
            return False
    elif meta_level != level:
        return False
    if subject_set and meta.get("subject") not in subject_set:
        return False
    if grade_set:
        grade = str(meta.get("grade", ""))
        if grade and grade not in grade_set:
            return False
    return True


def _download_and_parse(
    entries: List[Dict],
    cache_dir: Path,
    timeout: int,
    max_workers: int,
    limit: Optional[int],
) -> List[RawMaterial]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    if limit:
        entries = entries[:limit]

    materials: List[RawMaterial] = []

    def process_entry(entry: Dict) -> Optional[RawMaterial]:
        url = entry.get("file_url", "")
        meta = entry.get("_meta", {})
        if not url:
            return None

        pdf_bytes = _download_pdf(url=url, cache_dir=cache_dir, timeout=timeout)
        if pdf_bytes is None:
            return None

        text = _extract_pdf_text_from_bytes(pdf_bytes)
        if len(text) < _MIN_CONTENT_LENGTH:
            logger.debug("exam_bank: skipping short/scanned PDF %s", url)
            return None

        school = meta.get("school") or entry.get("school", "")
        return _make_material(text=text, meta=meta, source=school or _url_basename(url))

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(process_entry, e): e for e in entries}
        for future in as_completed(futures):
            try:
                mat = future.result()
                if mat:
                    materials.append(mat)
            except Exception as exc:
                entry = futures[future]
                logger.warning("exam_bank: failed processing %s: %s", entry.get("file_url", "?"), exc)

    return materials


def _download_pdf(url: str, cache_dir: Path, timeout: int) -> Optional[bytes]:
    """Download a PDF, using local cache if available."""
    filename = re.sub(r"[^\w\-.]", "_", _url_basename(url))[:100]
    cache_file = cache_dir / filename

    if cache_file.exists():
        logger.debug("exam_bank: cache hit %s", filename)
        return cache_file.read_bytes()

    logger.info("exam_bank: downloading %s", url)
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "llmbench/1.0"})
        resp.raise_for_status()
        pdf_bytes = resp.content
        cache_file.write_bytes(pdf_bytes)
        return pdf_bytes
    except Exception as exc:
        logger.warning("exam_bank: download failed for %s: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------


def _extract_pdf_text_from_bytes(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using pdfplumber."""
    import pdfplumber  # lazy import — optional dependency

    pages_text: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text(x_tolerance=3, y_tolerance=3)
                if text:
                    pages_text.append(text.strip())
    except Exception as exc:
        logger.warning("exam_bank: pdfplumber error: %s", exc)
        return ""

    full = "\n\n".join(pages_text)
    # Remove Unicode Private Use Area characters (U+E000–U+F8FF, U+F0000–U+FFFFF)
    # These come from custom symbol/dingbat fonts and are meaningless as text.
    full = re.sub(r"[\uE000-\uF8FF\U000F0000-\U000FFFFF]", "", full)
    # Collapse excessive blank lines
    full = re.sub(r"\n{3,}", "\n\n", full)
    return full.strip()


def _count_chinese(text: str) -> int:
    return sum(1 for c in text if "\u4e00" <= c <= "\u9fff")


# ---------------------------------------------------------------------------
# RawMaterial construction
# ---------------------------------------------------------------------------


def _make_material(text: str, meta: Dict, source: str) -> RawMaterial:
    subject = meta.get("subject", "綜合")
    grade = meta.get("grade", "")
    level = meta.get("level", "elementary")
    label = meta.get("label", "")
    school = meta.get("school", source)

    level_label = {"elementary": "國小", "middle_school": "國中", "high_school": "高中"}.get(level, "國中")
    grade_label = f"{grade}年級" if grade else ""
    title = f"【{level_label}·{subject}{grade_label}】{label or school}"

    return RawMaterial(
        source_category=f"exam_bank/{level}/{subject}",
        title=title,
        content=text,
        keyword=subject,
        month_range={"start": "", "end": ""},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_subject(raw: str) -> str:
    raw = (raw or "").strip()
    for key, canonical in _SUBJECT_ALIASES.items():
        if key in raw:
            return canonical
    return raw or "綜合"


def _url_basename(url: str) -> str:
    return Path(urlparse(url).path).name or "unknown.pdf"
