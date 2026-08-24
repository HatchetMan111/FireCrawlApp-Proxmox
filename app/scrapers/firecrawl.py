import httpx

from ..config import FIRECRAWL_API_KEY, FIRECRAWL_API_URL
from .base import EXTRACTION_PROMPT, EXTRACTION_SCHEMA, ScrapeResult, parse_price_value


async def fetch(url: str) -> ScrapeResult:
    res = ScrapeResult(source="firecrawl")
    payload = {
        "url": url,
        "formats": ["extract"],
        "extract": {"prompt": EXTRACTION_PROMPT, "schema": EXTRACTION_SCHEMA},
    }
    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{FIRECRAWL_API_URL}/scrape", json=payload, headers=headers)
    if r.status_code != 200:
        res.error = f"HTTP {r.status_code}: {r.text[:300]}"
        return res
    data = r.json()
    if data.get("success") is False:
        res.error = str(data.get("error") or "unknown firecrawl error")
        return res
    inner = data.get("data") or {}
    extracted = inner.get("extract") or inner.get("json") or {}
    res.raw = {"extract": extracted, "metadata": inner.get("metadata") or {}}
    res.price = parse_price_value(extracted.get("price"))
    currency = str(extracted.get("currency") or "EUR")
    res.currency = currency.upper()[:8]
    res.availability = str(extracted.get("availability") or "")
    res.product_name = str(extracted.get("product_name") or "")
    if res.price is None:
        res.error = "no price found in extraction"
        return res
    res.ok = True
    return res
