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

    parts = [f"📰 <b>{html.escape(item['title'])}</b>", f"【中文】{html.escape(zh)}"]
    if en:
        parts.append(f"【EN】{html.escape(en)}")
    parts.append(f"🔗 <a href=\"{html.escape(item['link'])}\">阅读原文</a>")
    parts.append(f"#{_source_tag(item['source'])} #News")
    return "\n\n".join(parts)


def send(text: str) -> bool:
    if not config.BOT_TOKEN or not config.CHAT_ID:
        log.error("缺少 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID，无法发送")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage",
            json={
                "chat_id": config.CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": not config.SHOW_LINK_PREVIEW,
            },
            timeout=30,
        )
    except Exception as exc:
        log.error("发送异常: %s", exc)
        return False
    if resp.status_code == 200:
        return True
    log.error("发送失败 %s: %s", resp.status_code, resp.text[:200])
    return False
