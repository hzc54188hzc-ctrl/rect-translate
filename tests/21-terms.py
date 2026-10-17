"""术语标注纯逻辑自检：JSON 解析、过滤、HTML 渲染、搜索 URL。

用法：.venv\\Scripts\\python.exe tests\\21-terms.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from recttrans.terms import (
    MAX_TERMS,
    build_rich_html,
    normalize_terms,
    parse_rich_response,
    search_url,
)


def main() -> int:
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")

    # 1) 标准 JSON
    text, terms = parse_rich_response(
        '{"translation": "使用注意力机制", "terms": '
        '[{"text": "注意力机制", "query": "注意力机制 论文", "kind": "论文"}]}'
    )
    check("解析标准 JSON", text == "使用注意力机制" and len(terms) == 1, repr(text))

    # 2) 带代码围栏
    text, terms = parse_rich_response(
        '```json\n{"translation": "破防了", "terms": []}\n```'
    )
    check("解析代码围栏", text == "破防了" and terms == [], repr(text))

    # 3) 模型不听话返回纯文本：整段当译文，不标术语
    text, terms = parse_rich_response("就是一段普通译文")
    check("纯文本兜底", text == "就是一段普通译文" and terms == [], repr(text))

    # 4) 过滤：不在译文中 / 太短 / 重复 / 超过上限
    translation = "Transformer 使用注意力机制，这就是破防。"
    raw = [
        {"text": "Transformer", "query": "Transformer 论文"},
        {"text": "注意力机制", "query": ""},
        {"text": "不存在的词", "query": "x"},
        {"text": "破", "query": "x"},
        {"text": "Transformer", "query": "重复"},
    ] + [{"text": f"词{i}", "query": "q"} for i in range(10)]
    terms = normalize_terms(translation, raw)
    check(
        "过滤无效与重复并限流",
        len(terms) <= MAX_TERMS
        and [t["text"] for t in terms][:2] == ["Transformer", "注意力机制"],
        str([t["text"] for t in terms]),
    )
    check("query 为空时用词本身", terms[1]["query"] == "注意力机制", terms[1]["query"])

    # 5) HTML：转义 + 链接 + 长词优先
    html = build_rich_html(
        "使用 Transformer 与注意力机制 <b>",
        [
            {"text": "注意力", "query": "短"},
            {"text": "注意力机制", "query": "注意力机制 解释"},
            {"text": "Transformer", "query": "Transformer 论文"},
        ],
        "#2563EB",
    )
    check("生成可点击链接", "href=" in html and "Transformer</a>" in html, html[:80])
    check("长词优先不拆词", ">注意力机制</a>" in html and ">注意力</a>" not in html)
    check("HTML 被转义", "&lt;b&gt;" in html)

    # 6) 搜索 URL
    url = search_url("Transformer 论文", "bing")
    check(
        "Bing 搜索 URL",
        url.startswith("https://www.bing.com/search?q=") and "%20" in url,
        url,
    )
    check("百度搜索 URL", search_url("破防", "baidu").startswith("https://www.baidu.com/s?wd="))

    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
