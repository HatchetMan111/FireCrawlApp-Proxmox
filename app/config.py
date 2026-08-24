import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "").strip()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()
FIRECRAWL_API_URL = os.getenv("FIRECRAWL_API_URL", "https://api.firecrawl.dev/v1").rstrip("/")
TAVILY_API_URL = os.getenv("TAVILY_API_URL", "https://api.tavily.com").rstrip("/")
CHECK_SCHEDULE = os.getenv("CHECK_SCHEDULE", "08:00").strip()
TIMEZONE = os.getenv("TZ", "Europe/Berlin")
DEMO_MODE = os.getenv("DEMO_MODE", "auto").strip().lower()
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "prices.db"


def demo_enabled() -> bool:
    if DEMO_MODE == "on":
        return True
    if DEMO_MODE == "off":
        return False
    return not FIRECRAWL_API_KEY and not TAVILY_API_KEY
