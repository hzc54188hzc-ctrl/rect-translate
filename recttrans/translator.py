"""翻译通道：DeepSeek 对话接口。只做一件事——把文字翻成目标语言并只返回译文。"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from recttrans.terms import normalize_terms, parse_rich_response

SYSTEM_PROMPT = (
    "你是翻译引擎。把用户给出的文本翻译成{target}。"
    "只输出译文本身，不要解释、不要加引号、不要保留原文、不要输出拼音或音标。"
    "如果原文已经是{target}，就翻译成英文。"
    "保持原有的段落结构，不要合并或拆分段落。"
)

CAPTION_SYSTEM_PROMPT = (
    "你在为美剧或直播做同声传译字幕。用户可能给出【上文】和【本句】。"
    "上文只用于理解代词、语气、称呼和对话关系，不要翻译它；"
    "只输出【本句】的自然、口语化简体中文译文。"
    "如果本句里的 she/he/it/they 等代词能从上一句确定具体指谁，"
    "译文里直接写出所指（例如“我妈”“那小子”），不要只写“她/他”。"
    "要求：像真人在说话，不要书面腔；不要逐词直译；短句优先；"
    "避免翻译腔，不要写“我将”“我会”“这是……的”这类句式；"
    "可以用成语、俗语和口头禅，但只在贴合原意时用，不要为了用而用；"
    "语气词按人物情绪来，不要每句都加“好吧”“行吧”“天哪”；"
    "保留人名、地名、专有名词的常用译名；只输出译文，不要解释、不要加引号。"
    "示例：【上文】Mom is going to kill me when she finds out."
    "【本句】I can't face her. → 我没脸见我妈。"
)

_LANGUAGE_NAMES = {
    "zh-CN": "简体中文",
    "zh-Hans-CN": "简体中文",
    "en": "英文",
    "en-GB": "英文",
    "en-US": "英文",
    "ja": "日文",
}

# 免 key 免费通道（2026-10-16 实测可用；clients5 变体，另一条 gtx 变体会 429）
FREE_ENDPOINT = "https://clients5.google.com/translate_a/t"
FREE_CLIENT = "dict-chrome-ex"
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class TranslateError(RuntimeError):
    """翻译调用失败。"""


def target_name(code: str) -> str:
    return _LANGUAGE_NAMES.get(code, code)


def translate(text: str, config: dict, timeout: float = 60.0) -> str:
    provider = str(config.get("translate", {}).get("provider", "deepseek"))
    if provider == "free":
        return _translate_free(text, config, timeout)
    return _translate_llm(text, config, timeout)


def translate_caption(
    text: str,
    config: dict,
    timeout: float = 8.0,
    context: str = "",
) -> str:
    """影视/直播字幕：在普通翻译基础上要求口语化。"""
    provider = str(config.get("translate", {}).get("provider", "deepseek"))
    if provider == "free":
        return _free_resilient(text, config, timeout)
    payload = text
    if context.strip():
        payload = f"【上文】{context.strip()[:500]}\n【本句】{text.strip()}"
    return _llm_resilient(
        payload,
        config,
        timeout,
        system=CAPTION_SYSTEM_PROMPT,
        temperature=0.5,
    )


def translate_rich(text: str, config: dict, timeout: float = 60.0) -> dict:
    """翻译并顺带标注高辨识度术语，返回 {"text": 译文, "terms": [...]}。

    免费通道没有结构化输出，只返回译文；大模型通道一次请求同时拿到两者，
    解析失败时把整段当译文，术语为空——标注失败绝不能拖累翻译本身。
    """
    provider = str(config.get("translate", {}).get("provider", "deepseek"))
    if provider == "free":
        return {"text": _free_resilient(text, config, timeout), "terms": []}

    try:
        raw = _llm_resilient(
            text, config, timeout, system=_rich_system_prompt(config)
        )
    except TranslateError as exc:
        # 大模型不可用时退回免费通道，至少让用户拿到译文。
        try:
            fallback_text = _free_resilient(text, config, timeout)
        except TranslateError:
            raise exc
        return {
            "text": fallback_text,
            "terms": [],
            "fallback": "free",
            "reason": str(exc),
        }
    translation, raw_terms = parse_rich_response(raw)
    if not translation.strip():
        raise TranslateError("接口没有返回译文")
    terms = normalize_terms(translation, raw_terms)
    return {"text": translation, "terms": terms}


def _is_permanent(error: TranslateError) -> bool:
    message = str(error)
    return " 401" in message or " 403" in message


def _llm_resilient(
    text: str,
    config: dict,
    timeout: float,
    system: str,
    temperature: float = 0.2,
) -> str:
    """瞬时错误重试一次；401/403 不重试（重试也不会成功）。"""
    try:
        return _translate_llm(
            text, config, timeout, system=system, temperature=temperature
        )
    except TranslateError as exc:
        if _is_permanent(exc):
            raise
        time.sleep(0.6)
        return _translate_llm(
            text, config, timeout, system=system, temperature=temperature
        )


def _free_resilient(text: str, config: dict, timeout: float) -> str:
    try:
        return _translate_free(text, config, timeout)
    except TranslateError:
        time.sleep(0.6)
        return _translate_free(text, config, timeout)


def _rich_system_prompt(config: dict) -> str:
    target = target_name(str(config.get("target_language", "zh-CN")))
    source_code = str(config.get("source_language", "auto"))
    if source_code in ("", "auto"):
        head = f"你是翻译引擎。把用户给出的文本翻译成{target}。"
    else:
        head = f"你是翻译引擎。把用户给出的{target_name(source_code)}文本翻译成{target}。"
    return (
        head
        + "\n\n只输出一个 JSON 对象，不要代码围栏，不要任何解释，格式："
        '{"translation": "译文", "terms": [{"text": "词", "query": "搜索关键词", "kind": "术语"}]}'
        "\n\n术语标注规则（宁缺毋滥）：\n"
        "1. 只标 0-6 个高辨识度的词：专业术语、广为流传的网络热梗、"
        "经典典故/名句、明确指向某篇论文或理论的概念。\n"
        "2. 冷门、小众、需要猜测或只在特定圈子里使用的词，一律不标。\n"
        "3. text 必须原样出现在 translation 里；不要标单字，不要重复。\n"
        "4. query 用简短、适合搜索引擎的关键词，可加领域或「含义 / 出处 / 论文」。\n"
        "5. 没有合适的词就返回空数组。\n"
        "6. translation 里不要加引号、不要保留原文、不要解释。"
    )


def _system_prompt(config: dict) -> str:
    target = target_name(str(config.get("target_language", "zh-CN")))
    source_code = str(config.get("source_language", "auto"))
    if source_code in ("", "auto"):
        head = f"你是翻译引擎。把用户给出的文本翻译成{target}。"
    else:
        head = f"你是翻译引擎。把用户给出的{target_name(source_code)}文本翻译成{target}。"
    return (
        head
        + "只输出译文本身，不要解释、不要加引号、不要保留原文、不要输出拼音或音标。"
        + f"如果原文已经是{target}，就翻译成英文。"
        + "保持原有的段落结构，不要合并或拆分段落。"
    )


def _translate_free(text: str, config: dict, timeout: float) -> str:
    target = str(config.get("target_language", "zh-CN"))
    query = urllib.parse.urlencode(
        {"client": FREE_CLIENT, "sl": "auto", "tl": target, "q": text}
    )
    request = urllib.request.Request(
        f"{FREE_ENDPOINT}?{query}", headers={"User-Agent": _BROWSER_UA}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:160]
        raise TranslateError(f"免费通道返回 {exc.code}：{detail}") from exc
    except Exception as exc:  # noqa: BLE001
        raise TranslateError(f"免费通道不可用：{type(exc).__name__}: {exc}") from exc

    try:
        payload = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise TranslateError(f"免费通道返回格式异常：{raw[:160]}") from exc

    pieces: list[str] = []
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, list) and item and isinstance(item[0], str):
                pieces.append(item[0])
            elif isinstance(item, str):
                pieces.append(item)
    result = "".join(pieces).strip()
    if not result:
        raise TranslateError(f"免费通道没有返回译文：{raw[:160]}")
    return result


def _translate_llm(
    text: str,
    config: dict,
    timeout: float,
    system: str | None = None,
    temperature: float = 0.2,
) -> str:
    settings = config["translate"]
    base_url = str(settings["base_url"]).rstrip("/")

    payload = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": system or _system_prompt(config)},
            {"role": "user", "content": text},
        ],
        "temperature": temperature,
        "stream": False,
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings['api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise TranslateError(f"接口返回 {exc.code}：{detail}") from exc
    except Exception as exc:  # noqa: BLE001
        raise TranslateError(f"{type(exc).__name__}: {exc}") from exc

    try:
        return str(body["choices"][0]["message"]["content"]).strip()
    except Exception as exc:  # noqa: BLE001
        raise TranslateError(f"接口返回格式异常：{str(body)[:200]}") from exc
