"""Rebuild web challenges from saved qual result directories.

This is a non-destructive recovery tool for when `llmbench.db` was lost but
`results/qual/*/dataset.json` still exists.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

from llmbench.web.database import AsyncSessionLocal, init_db
from llmbench.web.models import Challenge


def _collect_unique_material_lines(items: list[dict]) -> tuple[str, int, Counter]:
    seen: set[str] = set()
    lines: list[str] = []
    categories: Counter = Counter()

    for item in items:
        material = item.get("source_material") or {}
        title = material.get("title", "")
        content = material.get("content", "")
        source_category = material.get("source_category", "")
        keyword = material.get("keyword", "")
        month_range = material.get("month_range") or {}
        month = month_range.get("start", "")

        key = json.dumps(
            {
                "title": title,
                "content": content,
                "source_category": source_category,
                "keyword": keyword,
                "month": month,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if key in seen:
            continue
        seen.add(key)
        categories[source_category] += 1
        lines.append(
            json.dumps(
                {
                    "text": content,
                    "title": title,
                    "source_category": source_category,
                    "keyword": keyword,
                    "month": month,
                },
                ensure_ascii=False,
            )
        )

    return "\n".join(lines), len(lines), categories


def _build_results_jsonl(items: list[dict]) -> str:
    rows: list[str] = []
    for item in items:
        material = item.get("source_material") or {}
        content = material.get("content", "") or ""
        thread_post = ""
        thread_replies = ""
        if "【主題】" in content and "【留言" in content:
            body = content.split("【主題】", 1)[1].strip()
            marker = body.find("【留言")
            if marker >= 0:
                end = body.find("】", marker)
                thread_post = body[:marker].strip()
                thread_replies = body[end + 1 :].strip() if end >= 0 else ""

        rows.append(
            json.dumps(
                {
                    "task_type": item.get("task_type", ""),
                    "topic": thread_post if item.get("task_type") == "stance_analysis" else "",
                    "stance": "",
                    "title": material.get("title", ""),
                    "content": thread_replies if thread_replies else content,
                    "full_content": content,
                    "thread_post": thread_post,
                    "thread_replies": thread_replies,
                    "reference_answer": item.get("reference_answer", "") or "",
                    "scoring_rubric": item.get("scoring_rubric", "") or "",
                    "score": None,
                    "reasoning": "",
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(rows)


def _make_name(run_dir: Path, categories: Counter, row_count: int) -> str:
    top_category = categories.most_common(1)[0][0] if categories else "unknown"
    suffix = top_category.replace("/", "_")
    return f"Recovered {run_dir.name} {suffix} ({row_count})"


async def recover(base_dir: Path, dry_run: bool = False) -> None:
    await init_db()

    dataset_paths = sorted(base_dir.glob("*/dataset.json"))
    print(f"Found {len(dataset_paths)} dataset files under {base_dir}")
    if not dataset_paths:
        return

    async with AsyncSessionLocal() as session:
        created = 0
        skipped = 0

        for dataset_path in dataset_paths:
            run_dir = dataset_path.parent
            raw = json.loads(dataset_path.read_text(encoding="utf-8"))
            items = raw.get("items") or []
            if not items:
                skipped += 1
                print(f"SKIP {run_dir.name}: no items")
                continue

            data_jsonl, row_count, categories = _collect_unique_material_lines(items)
            results_jsonl = _build_results_jsonl(items)
            task_types = raw.get("task_types") or []
            name = _make_name(run_dir, categories, row_count)
            description = (
                f"Recovered from results/qual/{run_dir.name}; "
                f"task_types={','.join(task_types)}; "
                f"source_categories={','.join(sorted(categories))}"
            )

            existing = await session.execute(
                __import__("sqlalchemy").select(Challenge).where(Challenge.name == name)
            )
            if existing.scalar_one_or_none():
                skipped += 1
                print(f"SKIP {run_dir.name}: already exists as {name}")
                continue

            print(
                f"CREATE {run_dir.name}: rows={row_count}, items={len(items)}, "
                f"categories={dict(categories)}"
            )
            if dry_run:
                continue

            challenge = Challenge(
                uuid=str(__import__("uuid").uuid4()),
                name=name,
                description=description,
                task_type="recovered_qual",
                data_jsonl=data_jsonl,
                results_jsonl=results_jsonl,
                row_count=row_count,
            )
            session.add(challenge)
            created += 1

        if not dry_run:
            await session.commit()
        print(f"Done. created={created}, skipped={skipped}, dry_run={dry_run}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Recover web challenges from qual result datasets.")
    parser.add_argument(
        "--base-dir",
        default="results/qual",
        help="Directory containing qual run subdirectories",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without writing to the database",
    )
    args = parser.parse_args()

    asyncio.run(recover(Path(args.base_dir), dry_run=args.dry_run))


if __name__ == "__main__":
    main()
