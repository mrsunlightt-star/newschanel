"""集中读取配置：环境变量优先，其次默认值。

本地运行时自动加载同目录 .env 文件（存在才加载，Actions 上静默跳过）。
"""
import os


def _load_dotenv():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


def _env(name: str, default: str = "") -> str:
    """读取环境变量；未设置或为空字符串时返回默认值。

    GitHub Actions 里未配置的 Variables 会展开成空串传入，
    必须视为"未设置"才能落到默认值。
    """
    value = os.environ.get(name, "")
    return value if value.strip() else default


_load_dotenv()

# --- Telegram（必填）---
BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
CHAT_ID = _env("TELEGRAM_CHAT_ID")

# --- LLM：任意 OpenAI 兼容接口（智谱 / Groq / Gemini 的 OpenAI 端点 / OpenRouter 等）---
LLM_API_KEY = _env("LLM_API_KEY")
LLM_BASE_URL = _env("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
LLM_MODEL = _env("LLM_MODEL", "glm-4.7-flash")
# 输出 token 预算：推理模型的思考过程也计入输出。
# Groq 免费档 qwen3.8-27b 的 OTPM 上限是 1000，max_tokens 必须低于它
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "950"))

# --- 抓取与发帖 ---
# hnrss 在部分国内网络下握手异常，GitHub Actions（海外）不受影响
DEFAULT_FEEDS = [
    "https://hnrss.org/frontpage",
    "https://techcrunch.com/feed/",
    "https://www.sspai.com/feed",
    "https://www.ithome.com/rss/",
    "https://www.solidot.org/index.rss",
]
_feeds_env = _env("RSS_FEEDS")
RSS_FEEDS = [u.strip() for u in _feeds_env.split(",") if u.strip()] or DEFAULT_FEEDS

FETCH_HOURS = int(os.environ.get("FETCH_HOURS", "6"))  # 只看最近 N 小时内的条目
MAX_POSTS_PER_RUN = int(os.environ.get("MAX_POSTS_PER_RUN", "5"))  # 每次最多发几条
SEND_INTERVAL = int(os.environ.get("SEND_INTERVAL", "3"))  # 每条帖子的间隔秒数
SHOW_LINK_PREVIEW = os.environ.get("SHOW_LINK_PREVIEW", "0") == "1"  # 是否显示链接预览

# 帖子底部导航行：逗号分隔多项，每项「名称|链接」，名称可含 emoji；留空则不显示
CHANNEL_LINKS = _env("CHANNEL_LINKS", "📢 频道|https://t.me/techscinew")

# 封面图统一裁剪为宽幅比例（宽版卡片，一屏可容纳更多帖子）；设为 0:0 保持原图比例
COVER_ASPECT = _env("COVER_ASPECT", "16:9")
COVER_WIDTH = int(os.environ.get("COVER_WIDTH", "1280"))  # 裁剪后目标宽度（像素）

# 卡片形态（按条分发）：
#   auto  = 自适应（默认）：条目有图走媒体卡片模板，无图自动落到纯文字紧凑卡片
#   text  = 全部纯文字紧凑卡片（跳过一切图片抓取，速度最快）
#   image = 全部尽力带图（og:image 兜底，实在无图才纯文字）
CARD_MODE = _env("CARD_MODE", "auto")

DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "news.db"),
)
DB_PATH = os.path.abspath(DB_PATH)
