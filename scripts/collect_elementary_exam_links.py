"""Collect public elementary exam-bank file links into a manifest.

This script fetches a set of public school/resource pages, extracts PDF/ZIP
links, and writes a CSV/JSON manifest for later OCR / parsing work.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
from dataclasses import dataclass, asdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
import urllib3


SEED_PAGES = [
    "https://affairs.kh.edu.tw/1613/upload/file_list/57",
    "https://affairs.kh.edu.tw/1613/upload/file_list/63",
    "https://affairs.kh.edu.tw/1613/upload/file_list/69",
    "https://affairs.kh.edu.tw/1613/upload/file_list/70",
    "https://affairs.kh.edu.tw/1613/upload/file_list/71",
    "https://affairs.kh.edu.tw/1874/upload/file_list/6",
    "https://affairs.kh.edu.tw/1874/upload/file_list/3",
    "https://market.cloud.edu.tw/resources/web/1695731",
    "https://newboe.chc.edu.tw/upload/show_download/%264%26186%263641",
    "https://newboe.chc.edu.tw/upload/show_download/%264%26186%264182",
    "https://newboe.chc.edu.tw/upload/show_download/%264%26186%265452%265469",
    "https://newboe.chc.edu.tw/upload/show_download/%264%26186%267547",
    "https://www.kmsh.tn.edu.tw/km107/edu_g6exam.htm",
    "https://www.tcsh.tn.edu.tw/AcadCamping.aspx",
    "https://www.jwsh.tp.edu.tw/TC/page.aspx?mid=318",
    "https://ehjhs.ntct.edu.tw/p/406-1012-298582,r787.php",
]

SUBJECT_PATTERNS = {
    "國文": [r"國語", r"國文", r"語文"],
    "數學": [r"數學"],
    "自然": [r"自然", r"理化", r"生物"],
    "社會": [r"社會", r"歷史", r"地理", r"公民"],
    "英文": [r"英文", r"英語", r"英聽", r"聽力"],
}

GRADE_PATTERNS = {
    1: [r"一年級", r"一上", r"一下", r"1年級", r"小一"],
    2: [r"二年級", r"二上", r"二下", r"2年級", r"小二"],
    3: [r"三年級", r"三上", r"三下", r"3年級", r"小三"],
    4: [r"四年級", r"四上", r"四下", r"4年級", r"小四"],
    5: [r"五年級", r"五上", r"五下", r"5年級", r"小五"],
    6: [r"六年級", r"六上", r"六下", r"6年級", r"小六"],
}


@dataclass
class LinkRecord:
    source_page: str
    file_url: str
    label: str
    file_type: str
    school: str
    subject: str
    grade: str
    term: str


class LinkExtractor(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[dict[str, str]] = []
        self._current_href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr_map = dict(attrs)
        href = attr_map.get("href")
        if href:
            self._current_href = urljoin(self.base_url, href)
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._current_href is None:
            return
        text = re.sub(r"\s+", " ", "".join(self._text_parts)).strip()
        self.links.append({"href": self._current_href, "text": text})
        self._current_href = None
        self._text_parts = []


def _school_from_url(url: str) -> str:
    if "1613" in url:
        return "獅湖國小"
    if "1874" in url:
        return "林園國小"
    if "kmsh.tn.edu.tw" in url:
        return "崑山中學小六試題"
    if "tcsh.tn.edu.tw" in url:
        return "台南慈濟高中小六菁英盃"
    if "jwsh.tp.edu.tw" in url:
        return "景文中學小六評量"
    if "ehjhs.ntct.edu.tw" in url:
        return "延和國中小六潛能測驗"
    if "newboe.chc.edu.tw" in url:
        return "彰化縣學力鑑定"
    if "cloud.edu.tw" in url:
        return "教育雲"
    return "未知來源"


def _infer_subject(text: str) -> str:
    for subject, patterns in SUBJECT_PATTERNS.items():
        if any(re.search(pattern, text) for pattern in patterns):
            return subject
    return ""


def _infer_grade(text: str) -> str:
    matched: list[int] = []
    for grade, patterns in GRADE_PATTERNS.items():
        if any(re.search(pattern, text) for pattern in patterns):
            matched.append(grade)
    if not matched:
        range_match = re.search(r"([1-6])\s*[-~～到]\s*([1-6])", text)
        if range_match:
            start, end = range_match.groups()
            return f"{start}-{end}"
        return ""
    if len(matched) == 1:
        return str(matched[0])
    return ",".join(str(item) for item in sorted(set(matched)))


def _infer_term(text: str) -> str:
    patterns = [
        r"\d{3}學年度[上下]學期",
        r"\d{3}-[12](?:期中|期末|第一次|第二次|第三次)?",
        r"\d{2,3}年",
        r"[一二三]上",
        r"[一二三]下",
        r"[AB]卷",
        r"期中考",
        r"期末考",
        r"段考",
    ]
    hits = [match.group(0) for pattern in patterns for match in re.finditer(pattern, text)]
    return " / ".join(dict.fromkeys(hits))


def _fetch_links(page_url: str, timeout: int, verify_ssl: bool) -> list[dict[str, str]]:
    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    response = requests.get(page_url, timeout=timeout, verify=verify_ssl)
    response.raise_for_status()
    parser = LinkExtractor(page_url)
    parser.feed(response.text)
    return parser.links


def _fetch_text(page_url: str, timeout: int, verify_ssl: bool, encoding: str | None = None) -> str:
    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    response = requests.get(page_url, timeout=timeout, verify=verify_ssl)
    response.raise_for_status()
    if encoding:
        return response.content.decode(encoding, errors="ignore")
    return response.text


def _iter_newboe_records(page_url: str, timeout: int, verify_ssl: bool) -> Iterable[LinkRecord]:
    school = _school_from_url(page_url)
    text = _fetch_text(page_url, timeout, verify_ssl)
    figure_blocks = re.findall(r"<figure\b.*?</figure>", text, flags=re.IGNORECASE | re.DOTALL)
    for block in figure_blocks:
        href_match = re.search(r'href="([^"]*upload/download/[^"]+)"', block, flags=re.IGNORECASE)
        label_match = re.search(r"<small[^>]*>(.*?)</small>", block, flags=re.IGNORECASE | re.DOTALL)
        if not href_match or not label_match:
            continue
        href = html.unescape(href_match.group(1))
        label = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", label_match.group(1)))).strip()
        if re.search(r"(答案|解答)", label):
            continue
        if "國小級" not in label:
            continue
        yield LinkRecord(
            source_page=page_url,
            file_url=href,
            label=label,
            file_type="pdf",
            school=school,
            subject=_infer_subject(label),
            grade="1-6",
            term=_infer_term(label),
        )


def _kmsh_subject_from_href(href: str) -> str:
    name = Path(urlparse(href).path).name.lower()
    if any(token in name for token in ["math", "mat", "ma"]):
        return "數學"
    if any(token in name for token in ["chinese", "chi", "ch"]):
        return "國文"
    if any(token in name for token in ["eng", "en"]):
        return "英文"
    if "ns" in name:
        return "自然"
    return ""


def _kmsh_label_from_href(href: str) -> str:
    name = Path(urlparse(href).path).name
    year_match = re.search(r"(\d{2,3})", name)
    year = year_match.group(1) if year_match else ""
    subject = _kmsh_subject_from_href(href)
    paper = ""
    lower_name = name.lower()
    if "-a" in lower_name or "a." in lower_name:
        paper = "A卷"
    elif "-b" in lower_name or "b." in lower_name:
        paper = "B卷"
    if subject:
        base = f"{year}年小六{subject}"
    else:
        base = name
    if paper:
        return f"{base}{paper}試題.pdf"
    return f"{base}試題.pdf" if subject else name


def _iter_kmsh_records(page_url: str, timeout: int, verify_ssl: bool) -> Iterable[LinkRecord]:
    school = _school_from_url(page_url)
    text = _fetch_text(page_url, timeout, verify_ssl, encoding="big5")
    hrefs = re.findall(r'href="([^"]+\.pdf)"', text, flags=re.IGNORECASE)
    seen: set[str] = set()
    for href in hrefs:
        full_href = urljoin(page_url, html.unescape(href))
        lower_href = full_href.lower()
        if full_href in seen or "ans" in lower_href:
            continue
        seen.add(full_href)
        label = _kmsh_label_from_href(full_href)
        yield LinkRecord(
            source_page=page_url,
            file_url=full_href,
            label=label,
            file_type="pdf",
            school=school,
            subject=_kmsh_subject_from_href(full_href),
            grade="6",
            term=_infer_term(label),
        )


def _iter_tcsh_records(page_url: str, timeout: int, verify_ssl: bool) -> Iterable[LinkRecord]:
    school = _school_from_url(page_url)
    text = _fetch_text(page_url, timeout, verify_ssl)
    matches = re.findall(r'href="([^"]+/(109|110|111)-(chi|eng|math)\.pdf)"[^>]*>([^<]+)</a>', text, flags=re.IGNORECASE)
    seen: set[str] = set()
    subject_map = {"chi": "國文", "eng": "英文", "math": "數學"}
    for href, year, key, label_text in matches:
        full_href = urljoin(page_url, href)
        if full_href in seen:
            continue
        seen.add(full_href)
        subject = subject_map.get(key.lower(), "")
        label = f"{year}年小六{subject}試題.pdf" if subject else (label_text.strip() or Path(urlparse(full_href).path).name)
        yield LinkRecord(
            source_page=page_url,
            file_url=full_href,
            label=label,
            file_type="pdf",
            school=school,
            subject=subject,
            grade="6",
            term=_infer_term(label),
        )


def _iter_ehjhs_records(page_url: str, timeout: int, verify_ssl: bool) -> Iterable[LinkRecord]:
    school = _school_from_url(page_url)
    text = _fetch_text(page_url, timeout, verify_ssl)
    matches = re.findall(
        r'href="([^"]*Action=downloadfile[^"]*)"[^>]*>.*?<img[^>]*>\s*([^<]+)</a>',
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    seen: set[str] = set()
    for href, label_text in matches:
        label = html.unescape(re.sub(r"\s+", " ", label_text)).strip()
        full_href = urljoin(page_url, html.unescape(href))
        if full_href in seen:
            continue
        seen.add(full_href)
        if not label.lower().endswith(".pdf"):
            continue
        if re.search(r"(答案|答案|解答|海報|簡章)", label):
            continue
        if not re.search(r"(國語|語文|數學|英語|英文|數理)", label):
            continue
        yield LinkRecord(
            source_page=page_url,
            file_url=full_href,
            label=label,
            file_type="pdf",
            school=school,
            subject=_infer_subject(label),
            grade="6",
            term=_infer_term(label),
        )


def _iter_records(page_url: str, timeout: int, verify_ssl: bool) -> Iterable[LinkRecord]:
    if "newboe.chc.edu.tw" in page_url:
        yield from _iter_newboe_records(page_url, timeout, verify_ssl)
        return
    if "kmsh.tn.edu.tw" in page_url:
        yield from _iter_kmsh_records(page_url, timeout, verify_ssl)
        return
    if "tcsh.tn.edu.tw" in page_url:
        yield from _iter_tcsh_records(page_url, timeout, verify_ssl)
        return
    if "ehjhs.ntct.edu.tw" in page_url:
        yield from _iter_ehjhs_records(page_url, timeout, verify_ssl)
        return
    school = _school_from_url(page_url)
    for link in _fetch_links(page_url, timeout, verify_ssl):
        href = link["href"]
        if "docs.google.com/viewer" in href:
            continue
        text = link["text"] or Path(href).name
        if text in {"(線上開啟)", "線上開啟", "預覽", "download"}:
            text = Path(href).name
        if not re.search(r"\.(pdf|zip)(?:$|\?)", href, re.IGNORECASE):
            continue
        if re.search(r"(答案|解答)", text):
            continue
        if not re.search(r"(題|試卷|試題|考|評量|pdf|zip)", text, re.IGNORECASE):
            continue
        yield LinkRecord(
            source_page=page_url,
            file_url=href,
            label=text,
            file_type="zip" if ".zip" in href.lower() else "pdf",
            school=school,
            subject=_infer_subject(text),
            grade=_infer_grade(text),
            term=_infer_term(text),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect public elementary exam-bank file links")
    parser.add_argument("--output-dir", default="data/exam_bank/manifests")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--insecure", action="store_true", help="Disable SSL certificate verification")
    parser.add_argument("--page", action="append", dest="pages", help="Additional page URL")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pages = list(dict.fromkeys([*SEED_PAGES, *(args.pages or [])]))
    records: list[LinkRecord] = []
    seen_urls: set[str] = set()
    for page in pages:
        try:
            for record in _iter_records(page, args.timeout, verify_ssl=not args.insecure):
                if record.file_url in seen_urls:
                    continue
                seen_urls.add(record.file_url)
                records.append(record)
        except Exception as exc:
            print(f"SKIP {page}: {exc}")

    json_path = output_dir / "elementary_exam_links.json"
    csv_path = output_dir / "elementary_exam_links.csv"

    payload = [asdict(record) for record in records]
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(payload[0].keys()) if payload else list(LinkRecord.__annotations__.keys()))
        writer.writeheader()
        writer.writerows(payload)

    print(f"pages={len(pages)}")
    print(f"records={len(records)}")
    print(f"json={json_path}")
    print(f"csv={csv_path}")


if __name__ == "__main__":
    main()
