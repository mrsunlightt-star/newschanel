"""Telegram 频道发帖：Bot API sendMessage，双语同帖格式。"""
import html
import logging
import re

import requests

from . import config

log = logging.getLogger(__name__)


def _source_tag(source: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", source)
    return "".join(w.capitalize() for w in words[:2]) or "News"


def render(item: dict, digest: dict | None) -> str:
    zh = (digest or {}).get("summary_zh", "").strip()
    en = (digest or {}).get("summary_en", "").strip()
    if not zh:  # 摘要失败时降级为 RSS 自带概要或标题
        zh = item["summary"] or item["title"]

    # 中文源：只有【摘要】段；英文源：【摘要】+【EN】对照
    # 原文入口由消息底部的「阅读原文」内联按钮承担
    parts = [f"📰 <b>{html.escape(item['title'])}</b>", f"【摘要】{html.escape(zh)}"]
    if en:
        parts.append(f"【EN】{html.escape(en)}")
    parts.append(f"#{_source_tag(item['source'])} #News")
    return "\n\n".join(parts)


def send(text: str, link: str) -> int | None:
    """发送消息（带「阅读原文」内联按钮），成功返回 message_id。"""
    if not config.BOT_TOKEN or not config.CHAT_ID:
        log.error("缺少 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID，无法发送")
        return None
    payload = {
        "chat_id": config.CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": {
            "inline_keyboard": [[{"text": "🔗 阅读原文", "url": link}]]
        },
    }
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=30,
        )
    except Exception as exc:
        log.error("发送异常: %s", exc)
        return None
    if resp.status_code == 200:
        return resp.json()["result"]["message_id"]
    log.error("发送失败 %s: %s", resp.status_code, resp.text[:200])
    return None


def add_reaction(message_id: int, emoji: str = "👍"):
    """给刚发的消息加一个初始表情回应；失败仅记录，不影响发帖流程。"""
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{config.BOT_TOKEN}/setMessageReaction",
            json={
                "chat_id": config.CHAT_ID,
                "message_id": message_id,
                "reaction": [{"type": "emoji", "emoji": emoji}],
            },
            timeout=15,
        )
        if resp.status_code != 200:
            log.warning("添加表情回应失败 %s: %s", resp.status_code, resp.text[:150])
    except Exception as exc:
        log.warning("添加表情回应异常: %s", exc)
