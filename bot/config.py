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


_load_dotenv()

# --- Telegram（必填）---
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# --- LLM：任意 OpenAI 兼容接口（Groq / Gemini 的 OpenAI 端点 / OpenRouter / DeepSeek 等）---
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")

# --- 抓取与发帖 ---
# hnrss 在部分国内网络下握手异常，GitHub Actions（海外）不受影响
DEFAULT_FEEDS = [
    "https://hnrss.org/frontpage",
    "https://techcrunch.com/feed/",
    "https://www.sspai.com/feed",
    "https://www.ithome.com/rss/",
    "https://www.solidot.org/index.rss",
]
_feeds_env = os.environ.get("RSS_FEEDS", "")
RSS_FEEDS = [u.strip() for u in _feeds_env.split(",") if u.strip()] or DEFAULT_FEEDS

FETCH_HOURS = int(os.environ.get("FETCH_HOURS", "6"))  # 只看最近 N 小时内的条目
MAX_POSTS_PER_RUN = int(os.environ.get("MAX_POSTS_PER_RUN", "5"))  # 每次最多发几条
SEND_INTERVAL = int(os.environ.get("SEND_INTERVAL", "3"))  # 每条帖子的间隔秒数
SHOW_LINK_PREVIEW = os.environ.get("SHOW_LINK_PREVIEW", "0") == "1"  # 是否显示链接预览

DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "news.db"),
)
DB_PATH = os.path.abspath(DB_PATH)
