"""调用 OpenAI 兼容接口生成摘要与话题标签。

不使用 response_format 参数以最大化免费端点兼容性（Groq/Gemini/OpenRouter 均可），
靠提示词约束 + 解析容错保证拿到 JSON。
"""
import json
import logging
import re
import time

import requests

from . import config

log = logging.getLogger(__name__)

PROMPT = """你是一名科技资讯编辑。请先判断下面新闻内容的语言，再生成摘要：
- summary_zh: 60-150 字的中文摘要，突出关键事实，不夸张不脑补（原文为英文时即翻译提炼为中文），写足信息量，不要过于简短
- summary_en: 严格执行——若内容为中文，此字段输出空字符串 ""；若内容为英文或其他语言，此字段必须输出 60-150 words 的英文摘要作为对照，绝不能留空
- tags: 2-4 个话题标签，从内容提炼核心主题词，中文为主（专有名词、产品名可保留英文），每个不超过 12 个字

只输出一个 JSON 对象，格式如下，不要输出任何其他文字：
{{"summary_zh": "...", "summary_en": "...", "tags": ["标签1", "标签2"]}}

标题：{title}
来源：{source}
内容：{content}"""


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:  # GLM 等模型习惯用 markdown 围栏包裹 JSON
        text = fenced.group(1)
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
                pass
    # 截断修复：输出预算耗尽时 JSON 被切半，逐字段抢救已生成的内容
    data: dict = {}
    for key in ("summary_zh", "summary_en"):
        fm = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)', text)
        if fm:
            data[key] = (
                fm.group(1)
                .replace('\\"', '"')
                .replace("\\n", "\n")
                .replace("\\\\", "\\")
            )
    tm = re.search(r'"tags"\s*:\s*\[([^\]]*)', text)
    if tm:
        data["tags"] = re.findall(r'"([^"]+)"', tm.group(1))
    return data or None


def _is_chinese(text: str) -> bool:
    """中文字符占比超过 20% 即视为中文内容。"""
    if not text:
        return False
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk / max(len(text), 1) > 0.2


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


# 业务级限流错误码：智谱 1302/1305 = 并发超限/访问量过大（HTTP 仍 200）
RETRYABLE_BIZ_CODES = {"1302", "1305", "429"}


def _request(payload: dict) -> str:
    """发起补全请求；对限流（HTTP 429 / 业务码 1302·1305）与瞬时坏响应自动退避重试。"""
    last_err: Exception | None = None
    for wait in (0, 15, 30, 60, 90):
        if wait:
            log.info("LLM 限流或瞬时错误，%ds 后重试", wait)
            time.sleep(wait)
        try:
            resp = requests.post(
                f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
                json=payload,
                timeout=60,
            )
        except requests.RequestException as exc:
            last_err = exc
            continue
        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after", "")
            last_err = RuntimeError(f"429 rate limit: {resp.text[:120]}")
            if retry_after.isdigit():
                time.sleep(int(retry_after))
                continue
            continue
        try:
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except Exception as exc:  # 空响应/坏 JSON/结构缺失等瞬时问题
            last_err = exc
            continue
        err = data.get("error")
        if err:
            code = str(err.get("code", ""))
            if code in RETRYABLE_BIZ_CODES:
                last_err = RuntimeError(f"{code}: {err.get('message', '')[:100]}")
                continue
            raise RuntimeError(f"{code}: {err.get('message', '')[:150]}")
        return content
    raise last_err or RuntimeError("LLM 请求失败")


NO_THINK_SYSTEM = "跳过一切思考过程，直接输出最终答案。不要分析，不要推理，收到请求后立即输出结果。"


def summarize(title: str, source: str, content: str) -> dict | None:
    """返回 {"summary_zh", "summary_en", "tags"}，失败返回 None。"""
    payload = {
        "model": config.LLM_MODEL,
        "messages": [
            # 摘要无需思考；思考会吃满输出预算（content 变空），须按服务关闭：
            # 智谱 GLM = thinking 参数；Qwen = /no_think 后缀；gpt-oss = reasoning_effort
            {"role": "system", "content": NO_THINK_SYSTEM},
            {
                "role": "user",
                "content": PROMPT.format(
                    title=title, source=source, content=content or title
                )
                + " /no_think",
            },
        ],
        "temperature": 0.3,
        "max_tokens": config.LLM_MAX_TOKENS,
        # 各服务的思考开关/参数不兼容时，依次去掉重新请求（见下方降级序列）
        "reasoning_effort": "low",
        "thinking": {"type": "disabled"},
    }
    text = ""
    last_exc: Exception | None = None
    for drop in ([], ["thinking"], ["thinking", "reasoning_effort"]):
        attempt = {k: v for k, v in payload.items() if k not in drop}
        try:
            text = _request(attempt)
            break
        except Exception as exc:  # 参数不被当前服务支持 → 降一级再试
            last_exc = exc
            text = ""
    if not text:
        log.error("LLM 调用失败: %s", last_exc)
        return None
    data = _parse_json(text)
    if not data or not data.get("summary_zh"):
        log.error("LLM 返回无法解析为摘要 JSON: %.120s", text)
        return None
    if data.get("summary_en") and _is_chinese(f"{title} {content}"):
        # 部分模型（如 GLM）不遵守"中文源 EN 留空"的条件指令，代码层强制兜底
        data["summary_en"] = ""
    data["tags"] = _clean_tags(data.get("tags"))
    return data
