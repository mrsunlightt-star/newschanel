"""Telegram 频道发帖：图片媒体卡片（sendPhoto）优先，纯文字自动降级。

卡片版式（对齐参考样式）：
    📰 标题（粗体）
    摘要正文 + 来源名内嵌原文链接
    【EN】英文对照（仅外文源）
    📎 #话题标签
    📢 频道导航行（可配置）
"""
import html
import io
import logging
import re

import requests

from . import config

log = logging.getLogger(__name__)

MAX_CAPTION = 1024  # Telegram 媒体说明文字上限


def _source_tag(source: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", source)
    return "".join(w.capitalize() for w in words[:2]) or "News"


def _escape_cut(text: str, limit: int) -> str:
    """截断已 HTML 转义的文本，并清掉截断产生的半个实体（如 &am）。"""
    return re.sub(r"&[a-zA-Z#0-9]{0,8}$", "", text[:limit]).rstrip()


def _tags_line(item: dict, digest: dict | None) -> str:
    tags = (digest or {}).get("tags") or []
    if not tags:  # LLM 降级时至少保留来源标签
        tags = [_source_tag(item["source"]), "News"]
    return "📎 " + " ".join("#" + t for t in tags[:4])


def _nav_line() -> str:
    """频道导航行：CHANNEL_LINKS 形如「📢 频道|https://t.me/xxx,👥 群组|...」。"""
    links = []
    for part in config.CHANNEL_LINKS.split(","):
        if "|" not in part:
            continue
        name, url = part.split("|", 1)
        name, url = name.strip(), url.strip()
        if name and url:
            links.append(
                f'<a href="{html.escape(url, quote=True)}">{html.escape(name)}</a>'
            )
    return " · ".join(links)


def render(item: dict, digest: dict | None) -> str:
    """组装媒体卡片说明文字，超限时先裁 EN 对照、再裁中文摘要。"""
    zh = (digest or {}).get("summary_zh", "").strip()
    if not zh:  # 摘要失败时降级为 RSS 自带概要或标题
        zh = item["summary"] or item["title"]
    en = (digest or {}).get("summary_en", "").strip()

    title = html.escape(item["title"][:300])
    link = html.escape(item["link"], quote=True)
    source = html.escape(item["source"])
    zh_esc = html.escape(zh)
    en_esc = html.escape(en)
    tail = [_tags_line(item, digest)]
    nav = _nav_line()
    if nav:
        tail.append(nav)

    def build(z_txt: str, e_txt: str) -> str:
        parts = [
            f"📰 <b>{title}</b>",
            f'{z_txt} <a href="{link}">{source}</a>',
        ]
        if e_txt:
            parts.append(f"【EN】{e_txt}")
        parts.extend(tail)
        return "\n\n".join(parts)

    include_en = bool(en_esc)
    caption = build(zh_esc, en_esc if include_en else "")
    if len(caption) > MAX_CAPTION and include_en:
        base = len(build(zh_esc, ""))
        room = MAX_CAPTION - base - 10
        if room > 40:
            en_esc = _escape_cut(en_esc, room - 1) + "…"
        else:
            include_en = False
        caption = build(zh_esc, en_esc if include_en else "")
    if len(caption) > MAX_CAPTION:
        overhead = len(caption) - len(zh_esc)
        room = max(MAX_CAPTION - overhead - 4, 120)
        zh_esc = _escape_cut(zh_esc, room - 1) + "…"
        caption = build(zh_esc, en_esc if include_en else "")
    return caption


def _crop_wide(image_url: str) -> bytes | None:
    """下载封面图，统一居中裁剪为宽幅比例并压缩，返回 JPEG 字节；失败返回 None。

    宽幅卡片在 Telegram 里占屏高度小，一屏能看到更多帖子；
    本地下载处理也顺带绕过了部分网站的图片防盗链。
    """
    try:
        from PIL import Image
    except ImportError:
        log.warning("未安装 Pillow，跳过封面裁剪")
        return None
    try:
        resp = requests.get(
            image_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; newschanel-bot/1.0)"},
            timeout=15,
        )
        if resp.status_code != 200 or len(resp.content) > 15 * 1024 * 1024:
            return None
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception as exc:
        log.warning("封面图下载/解析失败: %s", exc)
        return None
    w, h = img.size
    if w < 200 or h < 120:  # 太小的图裁剪没有意义，交由原图直发
        return None
    try:
        aw, ah = (int(x) for x in config.COVER_ASPECT.split(":"))
        if aw <= 0 or ah <= 0:
            raise ValueError
    except Exception:
        aw, ah = 16, 9
    ratio, target = w / h, aw / ah
    if ratio < target:  # 偏竖：保宽裁高，重心略偏上保留主体
        new_h = int(w / target)
        top = int((h - new_h) * 0.40)
        img = img.crop((0, top, w, top + new_h))
    elif ratio > target:  # 偏横：保高裁宽
        new_w = int(h * target)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    if img.width > config.COVER_WIDTH:
        img = img.resize(
            (config.COVER_WIDTH, int(img.height * config.COVER_WIDTH / img.width)),
            Image.LANCZOS,
        )
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def deliver(image_url: str, caption: str) -> int | None:
    """有封面图走 sendPhoto 媒体卡片；无图或图片发送失败时降级为纯文字。

    图片三级降级：本地裁剪成宽幅上传 → 原图 URL 直发 → 纯文字。
    """
    if not config.BOT_TOKEN or not config.CHAT_ID:
        log.error("缺少 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID，无法发送")
        return None
    if image_url:
        base = {"chat_id": config.CHAT_ID, "caption": caption, "parse_mode": "HTML"}
        api = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendPhoto"
        try:
            cropped = _crop_wide(image_url)
            if cropped:
                resp = requests.post(
                    api,
                    data=base,
                    files={"photo": ("cover.jpg", cropped, "image/jpeg")},
                    timeout=90,
                )
            else:  # 裁剪失败（无 Pillow/下载失败/图太小），让 Telegram 自行抓原图
                resp = requests.post(api, json={**base, "photo": image_url}, timeout=60)
            if resp.status_code == 200:
                return resp.json()["result"]["message_id"]
            log.warning(
                "图片卡片发送失败 %s，降级为纯文字: %s",
                resp.status_code,
                resp.text[:150],
            )
        except Exception as exc:
            log.warning("图片卡片发送异常，降级为纯文字: %s", exc)
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage",
            json={
                "chat_id": config.CHAT_ID,
                "text": caption,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
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
