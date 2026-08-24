import asyncio
import hashlib
import random
from urllib.parse import urlparse

from . import db
from .config import FIRECRAWL_API_KEY, TAVILY_API_KEY, demo_enabled
from .scrapers import firecrawl, tavily
from .scrapers.base import ScrapeResult

SEM = asyncio.Semaphore(5)


def retailer_from_url(url: str) -> str:
    host = urlparse(url).netloc.removeprefix("www.")
    return host.split(".")[0].capitalize() if host else ""


async def scrape_url(url: str) -> ScrapeResult:
    errors = []
    if FIRECRAWL_API_KEY:
        try:
            res = await firecrawl.fetch(url)
            if res.ok:
                return res
            errors.append(f"firecrawl: {res.error}")
        except Exception as exc:
            errors.append(f"firecrawl: {type(exc).__name__}: {exc}")
    if TAVILY_API_KEY:
        try:
            res = await tavily.fetch(url)
            if res.ok:
                return res
            errors.append(f"tavily: {res.error}")
        except Exception as exc:
            errors.append(f"tavily: {type(exc).__name__}: {exc}")
    return ScrapeResult(
        ok=False,
        source="none",
        error="; ".join(errors) or "kein API-Key konfiguriert (Firecrawl/Tavily)",
    )


def simulate(product: dict) -> ScrapeResult:
    digest = int(hashlib.sha256(product["url"].encode()).hexdigest(), 16)
    prev = db.last_price_row(product["id"])
    last = prev["price"] if prev else float(100 + digest % 600)
    new = round(max(1.0, last * random.uniform(0.97, 1.03)), 2)
    avail = random.choices(
        ["in stock", "in stock", "in stock", "low stock"], weights=[8, 8, 8, 1]
    )[0]
    return ScrapeResult(
        ok=True,
        price=new,
        currency="EUR",
        availability=avail,
        product_name=product["name"] or "Demo Produkt",
        source="demo",
        raw={"simulated": True},
    )


async def check_product(product: dict) -> dict:
    async with SEM:
        res = await scrape_url(product["url"])
    if not res.ok and demo_enabled():
        res = simulate(product)
    prev = db.previous_price(product["id"])
    if res.ok:
        currency = res.currency or "EUR"
        db.insert_history(product["id"], res.price, currency, res.availability, res.source)
        db.update_after_check(product["id"], res.price, currency, res.availability, res.source)
        if not product["name"] and res.product_name:
            db.update_product(product["id"], name=res.product_name[:200])
        if prev and prev["price"]:
            diff = round(res.price - prev["price"], 2)
            if abs(diff) >= 0.01:
                pct = round(diff / prev["price"] * 100, 1)
                etype = "price_drop" if diff < 0 else "price_rise"
                arrow = "\U0001F7E9" if diff < 0 else "\U0001F534"
                name = product["name"] or product["url"]
                db.add_event(
                    product["id"],
                    etype,
                    f"{arrow} {name}: {prev['price']:.2f} \u2192 {res.price:.2f} "
                    f"({diff:+.2f} / {pct:+.1f}%)",
                )
        return {
            "ok": True,
            "price": res.price,
            "currency": currency,
            "source": res.source,
            "previous": prev["price"] if prev else None,
        }
    db.insert_history(product["id"], None, "", "", res.source, res.error)
    db.mark_checked(product["id"])
    db.add_event(
        product["id"],
        "error",
        f"\u26A0\uFE0F {product['name'] or product['url']}: {res.error[:300]}",
    )
    return {"ok": False, "error": res.error}


async def check_all() -> dict:
    products = [p for p in db.list_products() if p["active"]]
    results = await asyncio.gather(
        *(check_product(p) for p in products), return_exceptions=True
    )
    ok = sum(1 for r in results if isinstance(r, dict) and r.get("ok"))
    return {"checked": len(products), "ok": ok, "failed": len(products) - ok}
