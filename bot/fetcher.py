"""抓取 RSS 源，输出统一格式的候选条目。单个源失败不影响其他源。"""
import logging
import re
from datetime import datetime, timedelta, timezone

import feedparser
import requests

from . import config

log = logging.getLogger(__name__)

_IMG_TAG_RE = re.compile(r"<img[^>]+src=[\"']([^\"'>]+)[\"']", re.I)
_OG_RE = re.compile(
    r"<meta[^>]+(?:property|name)=[\"']og:image[\"'][^>]*content=[\"']([^\"'>]+)[\"']"
    r"|<meta[^>]+content=[\"']([^\"'>]+)[\"'][^>]*(?:property|name)=[\"']og:image[\"']",
    re.I,
)


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


def _pick_url(url: str) -> str:
    """基本校验：http(s) 开头、非 gif 动图，返回规范化 URL，否则空串。"""
    url = (url or "").strip().replace("&amp;", "&")
    if url.startswith("http") and not url.lower().split("?")[0].endswith(".gif"):
        return url
    return ""


def _entry_image(entry) -> str:
    """从 RSS 条目自带字段找封面图，不产生额外网络请求。找不到返回空串。"""
    for key in ("media_content", "media_thumbnail"):
        for media in entry.get(key) or []:
            url = _pick_url(media.get("url"))
            if url:
                return url
    for link in entry.get("links") or []:
        if str(link.get("type") or "").startswith("image/"):
            url = _pick_url(link.get("href"))
            if url:
                return url
    match = _IMG_TAG_RE.search(entry.get("summary") or "")
    if match:
        return _pick_url(match.group(1))
    return ""


def og_image(link: str) -> str:
    """抓取文章页面，从 og:image 提取封面图。失败返回空串（只读页面前 256KB）。"""
    try:
        resp = requests.get(
            link,
            headers={"User-Agent": "Mozilla/5.0 (compatible; newschanel-bot/1.0)"},
            timeout=10,
            stream=True,
        )
        page = ""
        size = 0
        for chunk in resp.iter_content(8192):
            page += chunk.decode("utf-8", "ignore")
            size += len(chunk)
            if "og:image" in page or size > 262144:
                break
        match = _OG_RE.search(page)
        if match:
            return _pick_url(match.group(1) or match.group(2))
    except Exception:
        pass
    return ""


def fetch_all() -> list[dict]:
    """返回候选条目列表：[{source, title, link, summary, image, published}]"""
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
                source = (feed.feed.get("title") or url).strip()
                if "Google News" in source:
                    # Google News 桥接源：条目标题形如「headline - Publisher」，
                    # 拆出真实标题与来源媒体名，卡片上不显示 Google News
                    m = re.match(r"^(.*)\s+-\s+([^-]+)$", title)
                    if m:
                        title, source = m.group(1).strip(), m.group(2).strip()
                items.append(
                    {
                        "source": source,
                        "title": title,
                        "link": link,
                        "summary": _clean(e.get("summary", "")),
                        "image": _entry_image(e),
                        "published": published,
                    }
                )
        except Exception as exc:
            log.warning("抓取失败，跳过: %s (%s)", url, exc)
    log.info("共抓到 %d 条候选条目（来自 %d 个源）", len(items), len(config.RSS_FEEDS))
    return items
