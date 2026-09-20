"""主流程：抓取 → 去重 → 封面图补齐 → 摘要 → 发帖 → 标记。

用法：
    python -m bot.main            # 完整流程（需要配置密钥）
    python -m bot.main --dry-run  # 只抓取与展示候选条目，不调用 LLM、不发帖
"""
import argparse
import logging
import os
import sys
import time

from . import config, dedup, fetcher, publisher, summarizer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("newschanel")


def run(dry_run: bool) -> int:
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    items = fetcher.fetch_all()
    fresh = [i for i in items if not dedup.is_posted(i["link"])]
    log.info("其中未发布过的新条目 %d 条", len(fresh))
    candidates = fresh[: config.MAX_POSTS_PER_RUN]
    if not candidates:
        log.info("没有需要发布的新内容，本次结束")
        return 0

    sent = 0
    for item in candidates:
        if dry_run:
            log.info("[dry-run] 将发布: %s | %s", item["source"], item["title"])
            continue
        digest = summarizer.summarize(item["title"], item["source"], item["summary"])
        if digest is None:
            log.warning("摘要生成失败，降级用原文概要: %s", item["title"])
        image = ""
        if config.CARD_MODE in ("auto", "image"):  # text 模式跳过一切图片抓取，省时省流量
            image = item.get("image", "") or fetcher.og_image(item["link"])
        caption = publisher.render(item, digest)
        message_id = publisher.deliver(image, caption)
        if message_id:
            dedup.mark_posted(item["link"], item["title"])
            sent += 1
            publisher.add_reaction(message_id)
            kind = "图片卡片" if image else "文字卡片"
            log.info("已发布(%s): %s", kind, item["title"])
        else:
            log.error("发送失败，该条未标记，下次运行会重试: %s", item["title"])
        time.sleep(config.SEND_INTERVAL)

    if dry_run:
        log.info("dry-run 结束，共 %d 条候选（未实际调用 LLM / 发帖）", len(candidates))
    else:
        log.info("本次发布 %d/%d 条", sent, len(candidates))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Telegram 双语资讯频道发帖机器人")
    parser.add_argument("--dry-run", action="store_true", help="只抓取与展示，不调用 LLM、不发帖")
    args = parser.parse_args()
    sys.exit(run(args.dry_run))
