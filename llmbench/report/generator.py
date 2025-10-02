"""Report generation (MVP).
Generates a markdown summary from global_summary.json data structure.
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List
import json
import csv


def _pad_markdown_table(headers: List[str], rows: List[List[str]]) -> List[str]:
    """Return a list of aligned markdown table lines.

    We compute the max width per column, pad each cell, and build a header separator
    with matching dash length for better alignment in raw text (still valid markdown).
    """
    if not headers:
        return []
    col_count = len(headers)
    widths = [len(h) for h in headers]
    for r in rows:
        for i in range(min(col_count, len(r))):
            widths[i] = max(widths[i], len(r[i]))
    # Build header
    header_line_cells = [headers[i].ljust(widths[i]) for i in range(col_count)]
    header_line = "| " + " | ".join(header_line_cells) + " |"
    # Build separator (at least 3 dashes)
    sep_cells = ["-" * max(3, widths[i]) for i in range(col_count)]
    sep_line = "| " + " | ".join(sep_cells) + " |"
    # Build rows
    body_lines = []
    for r in rows:
        cells = []
        for i in range(col_count):
            if i < len(r):
                cells.append(r[i].ljust(widths[i]))
            else:
                cells.append("".ljust(widths[i]))
        body_lines.append("| " + " | ".join(cells) + " |")
    return [header_line, sep_line, *body_lines]


def _extract_concurrency_rows(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    scenarios = summary.get("scenarios", {})
    for sname, servers in scenarios.items():
        for srv, stats in servers.items():
            if not stats:
                continue
            buckets = stats.get("concurrency_buckets", {})
            for conc, cstats in buckets.items():
                if not cstats:
                    continue
                rows.append(
                    {
                        "scenario": sname,
                        "server": srv,
                        "concurrency": conc,
                        "tokens_per_sec_output": cstats.get("tokens_per_sec_output", 0.0),
                        "tokens_per_sec_total": cstats.get("tokens_per_sec_total", 0.0),
                        "requests_per_sec": cstats.get("requests_per_sec", 0.0),
                        "p50_ms": cstats.get("p50_ms"),
                        "p95_ms": cstats.get("p95_ms"),
                        "error_rate": cstats.get("error_rate", 0.0),
                        "wait_p50_ms": cstats.get("wait_p50_ms"),
                    }
                )
    return rows


def _render_concurrency_throughput_table(summary: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    rows = _extract_concurrency_rows(summary)
    if not rows:
        return lines
    lines.append("## Concurrency Throughput Summary")
    lines.append("")
    header = [
        "Scenario",
        "Server",
        "Concurrency",
        "Tokens/s(out)",
        "Tokens/s(total)",
        "Req/s",
        "p50(ms)",
        "p95(ms)",
        "Err Rate",
        "Wait p50",
    ]
    body: List[List[str]] = []
    for r in rows:
        body.append([
            r['scenario'],
            r['server'],
            str(r['concurrency']),
            f"{r['tokens_per_sec_output']:.2f}",
            f"{r['tokens_per_sec_total']:.2f}",
            f"{r['requests_per_sec']:.2f}",
            f"{(r['p50_ms'] or 0):.1f}",
            f"{(r['p95_ms'] or 0):.1f}",
            f"{r['error_rate']:.3f}",
            f"{(r['wait_p50_ms'] or 0):.1f}",
        ])
    lines.extend(_pad_markdown_table(header, body))
    lines.append("")
    return lines


def _write_concurrency_csv(summary: Dict[str, Any], output_dir: Path) -> Path:
    rows = _extract_concurrency_rows(summary)
    target = output_dir / "concurrency_throughput.csv"
    if not rows:
        # still create empty header
        with target.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "scenario",
                "server",
                "concurrency",
                "tokens_per_sec_output",
                "tokens_per_sec_total",
                "requests_per_sec",
                "p50_ms",
                "p95_ms",
                "error_rate",
                "wait_p50_ms",
            ])
        return target
    with target.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "scenario",
                "server",
                "concurrency",
                "tokens_per_sec_output",
                "tokens_per_sec_total",
                "requests_per_sec",
                "p50_ms",
                "p95_ms",
                "error_rate",
                "wait_p50_ms",
            ],
        )
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    return target


def generate_markdown(summary: Dict[str, Any]) -> str:
    lines = ["# Benchmark Report", ""]
    runtime = summary.get("runtime_sec", 0)
    lines.append(f"Runtime: {runtime:.2f} sec")
    lines.append("")
    scenarios = summary.get("scenarios", {})
    for sname, servers in scenarios.items():
        lines.append(f"## Scenario: {sname}")
        lines.append("")
        # Scenario aggregated table (one row per server)
        header = [
            "Server","count","error","p50(ms)","p95","p99","avg","wait_p50","wait_p95","wait_avg","tokens/s(out)","err_rate","ttfb_p50","ttfb_p95","approx_ratio"
        ]
        body: List[List[str]] = []
        for srv, stats in servers.items():
            if not stats:
                body.append([srv,"0","0","-","-","-","-","-","-","-","-","-","-","-","-"])
                continue
            body.append([
                srv,
                str(stats.get('count',0)),
                str(stats.get('error_count',0)),
                f"{stats.get('p50_ms',0):.1f}",
                f"{stats.get('p95_ms',0):.1f}",
                f"{stats.get('p99_ms',0):.1f}",
                f"{stats.get('avg_ms',0):.1f}",
                (f"{stats['wait_p50_ms']:.1f}" if 'wait_p50_ms' in stats else '-'),
                (f"{stats['wait_p95_ms']:.1f}" if 'wait_p95_ms' in stats else '-'),
                (f"{stats['wait_avg_ms']:.1f}" if 'wait_avg_ms' in stats else '-'),
                f"{stats.get('tokens_per_sec_output', stats.get('tokens_per_sec',0.0)):.2f}",
                f"{stats.get('error_rate',0):.3f}",
                (f"{stats['ttfb_p50_ms']:.1f}" if 'ttfb_p50_ms' in stats else '-'),
                (f"{stats['ttfb_p95_ms']:.1f}" if 'ttfb_p95_ms' in stats else '-'),
                (f"{stats['output_tokens_approx_ratio']:.2f}" if 'output_tokens_approx_ratio' in stats else '-'),
            ])
        lines.extend(_pad_markdown_table(header, body))
        lines.append("")
        # Concurrency breakdown per server
        for srv, stats in servers.items():
            buckets = stats.get("concurrency_buckets") if stats else None
            if not buckets:
                continue
            lines.append(f"### Concurrency Breakdown ({srv})")
            header_cb = [
                "Concurrency","count","p50(ms)","wait_p50","tokens/s(out)","tokens/s(total)","req/s","err_rate","approx_ratio"
            ]
            body_cb: List[List[str]] = []
            for conc, cstats in buckets.items():
                if not cstats:
                    body_cb.append([str(conc),"0","-","-","-","-","-","-","-"])
                    continue
                body_cb.append([
                    str(conc),
                    str(cstats.get('count',0)),
                    f"{cstats.get('p50_ms',0):.1f}",
                    (f"{cstats['wait_p50_ms']:.1f}" if 'wait_p50_ms' in cstats else '-'),
                    f"{cstats.get('tokens_per_sec_output', cstats.get('tokens_per_sec',0.0)):.2f}",
                    f"{cstats.get('tokens_per_sec_total',0.0):.2f}",
                    f"{cstats.get('requests_per_sec',0.0):.2f}",
                    f"{cstats.get('error_rate',0.0):.3f}",
                    (f"{cstats['output_tokens_approx_ratio']:.2f}" if 'output_tokens_approx_ratio' in cstats else '-'),
                ])
            lines.extend(_pad_markdown_table(header_cb, body_cb))
            lines.append("")
    # Global summary table for all concurrency rows
    lines.extend(_render_concurrency_throughput_table(summary))
    return "\n".join(lines)


def write_report(summary: Dict[str, Any], output_dir: str | Path) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    md = generate_markdown(summary)
    target = out / "report.md"
    with target.open("w", encoding="utf-8") as f:
        f.write(md)
    with (out / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    # write csv
    _write_concurrency_csv(summary, out)
    return target
