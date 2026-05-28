"""Rename recovered challenges to more readable labels.

This rewrites generic names like:
    Recovered 2026-03-25_150615 threads (169)

Into labels such as:
    Threads｜AI｜摘要/情緒/分類/問答｜169題｜2026-03-25 15:06
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path


TASK_LABELS = {
    "qa": "問答",
    "summarization": "摘要",
    "sentiment": "情緒",
    "classification": "分類",
    "stance_analysis": "立場分析",
}


def _friendly_source(source_categories: list[str]) -> str:
    if not source_categories:
        return "已恢復題庫"
    top = source_categories[0]
    if top.startswith("taiwan_md/"):
        return "台灣知識庫"
    if top == "ptt/movie":
        return "PTT 電影版"
    if top.startswith("threads"):
        return "Threads"
    return top.replace("/", " ")


def _task_text(description: str) -> str:
    marker = "task_types="
    if marker not in description:
        return "題目"
    raw = description.split(marker, 1)[1].split(";", 1)[0]
    labels = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        labels.append(TASK_LABELS.get(token, token))
    return "/".join(labels) if labels else "題目"


def _source_categories(description: str) -> list[str]:
    marker = "source_categories="
    if marker not in description:
        return []
    raw = description.split(marker, 1)[1].strip()
    return [part.strip() for part in raw.split(",") if part.strip()]


def _extract_keyword(data_jsonl: str, source_categories: list[str]) -> str:
    if not data_jsonl.strip():
        return ""

    counts: Counter[str] = Counter()
    for raw_line in data_jsonl.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        keyword = str(row.get("keyword") or "").strip()
        if keyword:
            counts[keyword] += 1

    if not counts:
        if source_categories and source_categories[0].startswith("taiwan_md/"):
            return source_categories[0].split("/", 1)[1]
        return ""

    keyword, _ = counts.most_common(1)[0]
    return keyword


def _format_timestamp(run_name: str) -> str:
    if len(run_name) >= 15 and "_" in run_name:
        day, clock = run_name.split("_", 1)
        return f"{day} {clock[:2]}:{clock[2:4]}"
    return run_name


def _build_name(old_name: str, description: str, data_jsonl: str, row_count: int) -> str:
    run_name = old_name.removeprefix("Recovered ").split(" ", 1)[0]
    categories = _source_categories(description)
    source_text = _friendly_source(categories)
    keyword = _extract_keyword(data_jsonl, categories)
    task_text = _task_text(description)
    timestamp = _format_timestamp(run_name)

    parts = [source_text]
    if keyword:
        parts.append(keyword)
    parts.append(task_text)
    parts.append(f"{row_count}題")
    parts.append(timestamp)
    return "｜".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cleanup recovered challenge names")
    parser.add_argument(
        "--db",
        default="llmbench.db",
        help="Path to llmbench SQLite database",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the new names back to the database",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, description, data_jsonl, row_count FROM challenges WHERE name LIKE 'Recovered %' ORDER BY id"
    )
    rows = cur.fetchall()

    print(f"found={len(rows)} recovered challenges")
    for challenge_id, name, description, data_jsonl, row_count in rows:
        new_name = _build_name(name, description or "", data_jsonl or "", int(row_count or 0))
        print(f"{challenge_id}: {name} -> {new_name}")
        if args.apply:
            cur.execute("UPDATE challenges SET name = ? WHERE id = ?", (new_name, challenge_id))

    if args.apply:
        conn.commit()
        print("updated names written to database")

    conn.close()


if __name__ == "__main__":
    main()
