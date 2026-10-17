"""术语标注：解析模型的结构化输出、过滤、生成可点击 HTML 与搜索 URL。

不依赖 Qt，方便单独测试。
"""

from __future__ import annotations

import html
import json
from urllib.parse import quote

MAX_TERMS = 6
MIN_TERM_LENGTH = 2

_ENGINES = {
    "bing": "https://www.bing.com/search?q=",
    "baidu": "https://www.baidu.com/s?wd=",
    "google": "https://www.google.com/search?q=",
}


def search_url(query: str, engine: str = "bing") -> str:
    base = _ENGINES.get((engine or "bing").lower(), _ENGINES["bing"])
    return base + quote((query or "").strip(), safe="")


def parse_rich_response(raw: str) -> tuple[str, list]:
    """从模型输出里取 (译文, 原始术语列表)。

    模型不听话（返回纯文本、JSON 坏了）时：整段当译文，术语为空，
    绝不因为标注失败而丢译文。
    """
    text = (raw or "").strip()
    if not text:
        return "", []

    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
        except Exception:  # noqa: BLE001
            data = None
        if isinstance(data, dict) and isinstance(data.get("translation"), str):
            terms = data.get("terms")
            return data["translation"].strip(), terms if isinstance(terms, list) else []
    return text, []


def normalize_terms(translation: str, raw_terms) -> list[dict]:
    """只保留确实出现在译文里的词，去重、限流，query 为空时用词本身。"""
    if not translation or not isinstance(raw_terms, list):
        return []

    seen: set[str] = set()
    result: list[dict] = []
    for item in raw_terms:
        if isinstance(item, str):
            term, query, kind = item.strip(), "", ""
        elif isinstance(item, dict):
            term = str(item.get("text", "")).strip()
            query = str(item.get("query", "")).strip()
            kind = str(item.get("kind", "")).strip()
        else:
            continue
        if len(term) < MIN_TERM_LENGTH or term not in translation:
            continue
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append({"text": term, "query": query or term, "kind": kind})
        if len(result) >= MAX_TERMS:
            break
    return result


def build_rich_html(text: str, terms: list[dict], link_color: str) -> str:
    """把译文里的术语替换成蓝色链接；长词优先，避免把长词拆成短词。"""
    if not text:
        return ""
    ordered = sorted(
        (t for t in (terms or []) if str(t.get("text", "")).strip()),
        key=lambda t: len(str(t["text"])),
        reverse=True,
    )
    mapping = [
        (str(t["text"]), search_url(str(t.get("query") or t["text"])))
        for t in ordered
    ]

    out: list[str] = []
    index = 0
    while index < len(text):
        matched = None
        for term, url in mapping:
            if text.startswith(term, index):
                matched = (term, url)
                break
        if matched:
            term, url = matched
            out.append(
                f'<a href="{html.escape(url, quote=True)}" '
                f'style="color:{link_color}; text-decoration:underline;">'
                f"{html.escape(term)}</a>"
            )
            index += len(term)
        else:
            out.append(html.escape(text[index]))
            index += 1
    return "".join(out)
