"""调用 OpenAI 兼容接口生成摘要与话题标签。

不使用 response_format 参数以最大化免费端点兼容性（Groq/Gemini/OpenRouter 均可），
靠提示词约束 + 解析容错保证拿到 JSON。
"""
import json
import logging
import re

import requests

from . import config

log = logging.getLogger(__name__)

PROMPT = """你是一名科技资讯编辑。请先判断下面新闻内容的语言，再生成摘要：
- summary_zh: 80-150 字的中文摘要，突出关键事实，不夸张不脑补（原文为英文时即翻译提炼为中文）
- summary_en: 严格执行——若内容为中文，此字段输出空字符串 ""；若内容为英文或其他语言，此字段必须输出 80-150 words 的英文摘要作为对照，绝不能留空
- tags: 2-4 个话题标签，从内容提炼核心主题词，中文为主（专有名词、产品名可保留英文），每个不超过 12 个字

只输出一个 JSON 对象，格式如下，不要输出任何其他文字：
{{"summary_zh": "...", "summary_en": "...", "tags": ["标签1", "标签2"]}}

标题：{title}
来源：{source}
内容：{content}"""


def _parse_json(text: str) -> dict | None:
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                data = json.loads(match.group())
                return data if isinstance(data, dict) else None
            except json.JSONDecodeError:
                return None
    return None


def _clean_tags(raw) -> list[str]:
    """清洗 LLM 输出的标签：去 #/空白/标点，限长去重，最多 4 个。"""
    if not isinstance(raw, list):
        return []
    cleaned: list[str] = []
    for tag in raw:
        tag = re.sub(r"[#\s，,。、]+", "", str(tag))[:24]
        if tag and tag not in cleaned:
            cleaned.append(tag)
    return cleaned[:4]


def _request(payload: dict) -> str:
    resp = requests.post(
        f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def summarize(title: str, source: str, content: str) -> dict | None:
    """返回 {"summary_zh", "summary_en", "tags"}，失败返回 None。"""
    payload = {
        "model": config.LLM_MODEL,
        "messages": [
            {
                "role": "user",
                "content": PROMPT.format(
                    title=title, source=source, content=content or title
                ),
            }
        ],
        "temperature": 0.3,
        # 预算放宽：gpt-oss 等推理模型会先消耗输出 token 进行思考
        "max_tokens": 1500,
        # 推理模型限制思考长度，保证留有预算产出最终摘要
        "reasoning_effort": "low",
    }
    text = ""
    try:
        try:
            text = _request(payload)
        except Exception:
            # 部分严格服务不认识 reasoning_effort 参数，去掉后重试一次
            payload.pop("reasoning_effort", None)
            text = _request(payload)
    except Exception as exc:
        log.error("LLM 调用失败: %s", exc)
        return None
    data = _parse_json(text)
    if not data or not data.get("summary_zh"):
        log.error("LLM 返回无法解析为摘要 JSON: %.120s", text)
        return None
    data["tags"] = _clean_tags(data.get("tags"))
    return data
