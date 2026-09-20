"""抓取 RSS 源，输出统一格式的候选条目。单个源失败不影响其他源。"""
import logging
import re
from datetime import datetime, timedelta, timezone

import feedparser

from . import config

log = logging.getLogger(__name__)


def _entry_time(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def _clean(text: str, limit: int = 600) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def fetch_all() -> list[dict]:
    """返回候选条目列表：[{source, title, link, summary, published}]"""
    since = datetime.now(timezone.utc) - timedelta(hours=config.FETCH_HOURS)
    items = []
    for url in config.RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            if feed.bozo and not feed.entries:
                log.warning("源解析失败，跳过: %s (%s)", url, feed.get("bozo_exception"))
                continue
            for e in feed.entries:
                link = (e.get("link") or "").strip()
                title = (e.get("title") or "").strip()
                if not link or not title:
                    continue
                published = _entry_time(e)
                # 有发布时间的按时间窗过滤；没有时间的交给去重逻辑兜底
                if published and published < since:
                    continue
                items.append(
                    {
                        "source": (feed.feed.get("title") or url).strip(),
                        "title": title,
                        "link": link,
                        "summary": _clean(e.get("summary", "")),
                        "published": published,
                    }
                )
        except Exception as exc:
            log.warning("抓取失败，跳过: %s (%s)", url, exc)
    log.info("共抓到 %d 条候选条目（来自 %d 个源）", len(items), len(config.RSS_FEEDS))
    return items
