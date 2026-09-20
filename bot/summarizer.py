"""调用 OpenAI 兼容接口生成中英双语摘要。

不使用 response_format 参数以最大化免费端点兼容性（Groq/Gemini/OpenRouter 均可），
靠提示词约束 + 解析容错保证拿到 JSON。
"""
import json
import logging
import re

import requests

from . import config

log = logging.getLogger(__name__)

PROMPT = """你是一名科技资讯编辑。请根据下面的新闻内容生成摘要：
- summary_zh: 80-150 字的中文摘要，突出关键事实，不夸张不脑补
- summary_en: 80-150 word English summary, plain text

只输出一个 JSON 对象，格式如下，不要输出任何其他文字：
{{"summary_zh": "...", "summary_en": "..."}}

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
    """返回 {"summary_zh": ..., "summary_en": ...}，失败返回 None。"""
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
    return data
