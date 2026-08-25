from . import db
from .config import DEMO_MODE, FIRECRAWL_API_KEY, TAVILY_API_KEY

DEMO_PRODUCTS_MARKER = "demo"


def _db_setting(key: str) -> str:
    v = db.get_setting(key)
    return v if v else ""


def firecrawl_key() -> str:
    return _db_setting("firecrawl_api_key") or FIRECRAWL_API_KEY


def tavily_key() -> str:
    return _db_setting("tavily_api_key") or TAVILY_API_KEY


def demo_mode() -> str:
    m = (_db_setting("demo_mode") or DEMO_MODE).lower()
    return m if m in ("auto", "on", "off") else "auto"


def demo_active() -> bool:
    m = demo_mode()
    if m == "on":
        return True
    if m == "off":
        return False
    return not firecrawl_key() and not tavily_key()


def mask(key_str: str) -> str | None:
    if not key_str:
        return None
    tail = key_str[-4:] if len(key_str) >= 8 else "****"
    return f"••••{tail}"


def status() -> dict:
    fc = firecrawl_key()
    tv = tavily_key()
    return {
        "firecrawl": {"configured": bool(fc), "masked": mask(fc), "from_env": bool(not _db_setting("firecrawl_api_key") and FIRECRAWL_API_KEY)},
        "tavily": {"configured": bool(tv), "masked": mask(tv), "from_env": bool(not _db_setting("tavily_api_key") and TAVILY_API_KEY)},
        "demo_mode": demo_mode(),
        "demo_active": demo_active(),
    }
