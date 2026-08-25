import asyncio
import hashlib
import random
from urllib.parse import urlparse

from . import db
from .config import FIRECRAWL_API_URL, TAVILY_API_URL
from .scrapers import firecrawl, tavily
from .scrapers.base import ScrapeResult
from .settings_store import demo_active, firecrawl_key, tavily_key

SEM = asyncio.Semaphore(5)


def retailer_from_url(url: str) -> str:
    host = urlparse(url).netloc.removeprefix("www.")
    return host.split(".")[0].capitalize() if host else ""


def normalize_url(raw: str) -> str:
    url = (raw or "").strip()
    if url and not urlparse(url).scheme:
        url = "https://" + url
    return url.rstrip("/")


async def scrape_url(url: str) -> ScrapeResult:
    errors = []
    fc_key = firecrawl_key()
    if fc_key:
        try:
            res = await firecrawl.fetch(url, api_key=fc_key, api_url=FIRECRAWL_API_URL)
            if res.ok:
                return res
            errors.append(f"firecrawl: {res.error}")
        except Exception as exc:
            errors.append(f"firecrawl: {type(exc).__name__}: {exc}")
    tv_key = tavily_key()
    if tv_key:
        try:
            res = await tavily.fetch(url, api_key=tv_key, api_url=TAVILY_API_URL)
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
    if not res.ok and demo_active():
        res = simulate(product)
    prev = db.previous_price(product["id"])
    if res.ok:
        currency = res.currency or "EUR"
        db.insert_history(product["id"], res.price, currency, res.availability, res.source)
        db.update_after_check(product["id"], res.price, currency, res.availability, res.source)
        if not product["name"] and res.product_name:
            db.update_product(product["id"], name=res.product_name[:200])
            product = {**product, "name": res.product_name[:200]}
        name = product["name"] or product["url"]
        if prev and prev["price"]:
            diff = round(res.price - prev["price"], 2)
            if abs(diff) >= 0.01:
                pct = round(diff / prev["price"] * 100, 1)
                etype = "price_drop" if diff < 0 else "price_rise"
                arrow = "\U0001F7E9" if diff < 0 else "\U0001F534"
                db.add_event(
                    product["id"],
                    etype,
                    f"{arrow} {name}: {prev['price']:.2f} \u2192 {res.price:.2f} "
                    f"({diff:+.2f} / {pct:+.1f}%)",
                )
            elif db.get_setting("log_success_events", "1") != "0":
                db.add_event(
                    product["id"],
                    "success",
                    f"\u2705 {name}: unver\u00e4ndert {res.price:.2f} {currency} ({res.source})",
                )
        else:
            db.add_event(
                product["id"],
                "success",
                f"\u2705 {name}: erster Preis {res.price:.2f} {currency} ({res.source})",
            )
        return {
            "ok": True,
            "price": res.price,
            "currency": currency,
            "source": res.source,
            "previous": prev["price"] if prev else None,
        }
    tip = (
        " \u2013 Tipp: zweiten Provider (Firecrawl/Tavily) als Fallback hinterlegen"
        if not (firecrawl_key() and tavily_key())
        else ""
    )
    db.insert_history(product["id"], None, "", "", res.source, res.error)
    db.mark_checked(product["id"])
    db.add_event(
        product["id"],
        "error",
        f"\u26A0\uFE0F {product['name'] or product['url']}: {res.error[:250]}{tip}",
    )
    return {"ok": False, "error": res.error}


async def check_all() -> dict:
    products = [p for p in db.list_products() if p["active"]]
    return await _check_list(products)


async def check_due_products() -> dict:
    due = db.due_products()
    if not due:
        return {"checked": 0, "ok": 0, "failed": 0}
    return await _check_list(due)


async def _check_list(products: list[dict]) -> dict:
    results = await asyncio.gather(
        *(check_product(p) for p in products), return_exceptions=True
    )
    ok = sum(1 for r in results if isinstance(r, dict) and r.get("ok"))
    return {"checked": len(products), "ok": ok, "failed": len(products) - ok}
