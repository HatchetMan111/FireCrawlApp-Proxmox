import re

import httpx

from ..config import TAVILY_API_KEY, TAVILY_API_URL
from .base import ScrapeResult

PRICE_PATTERNS = [
    re.compile(r"(\d{1,3}(?:[. ]\d{3})*,\d{2})\s*(?:€|\beur\b)", re.I),
    re.compile(r"(?:€|\beur\b)\s*(\d{1,3}(?:,\d{3})+\.\d{2})", re.I),
    re.compile(r"(?:€|\beur\b)\s*(\d{1,3}(?:\.\d{3})*,\d{2})", re.I),
    re.compile(r"(?:€|\beur\b)\s*(\d{1,3}(?:\.\d{3})+)", re.I),
    re.compile(r"(?:€|\beur\b)\s*(\d+(?:\.\d{2})?)", re.I),
    re.compile(r"(\d{1,3}(?:\.\d{3})*)\s*,-\s*(?:€|\beur\b)", re.I),
]
IN_STOCK = ("auf lager", "sofort verfügbar", "verfügbar", "lieferbar", "in stock", "versandfertig")
OUT_OF_STOCK = ("nicht verfügbar", "ausverkauft", "out of stock", "nicht lieferbar")


def _normalize(s: str) -> float | None:
    s = s.replace(" ", "").replace("\u00a0", "")
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
        return float(s.replace(".", ""))
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        p = float(s)
    except ValueError:
        return None
    return p if 0.01 <= p <= 10_000_000 else None


def _all_matches(text: str) -> list[tuple[int, float]]:
    found: dict[int, float] = {}
    for pat in PRICE_PATTERNS:
        for m in pat.finditer(text):
            pos = m.start(1)
            if pos not in found:
                v = _normalize(m.group(1))
                if v:
                    found[pos] = v
    return sorted(found.items())


def extract_price(text: str) -> float | None:
    matches = _all_matches(text)
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0][1]
    lowered = text.lower()
    promo_positions = [
        i
        for i in (
            lowered.find("statt"),
            lowered.find("uvp"),
            lowered.find("instead of"),
            lowered.find("reduziert von"),
        )
        if i != -1
    ]
    if promo_positions:
        promo_idx = min(promo_positions)
        after_promo = [(p, v) for p, v in matches if p > promo_idx]
        if after_promo:
            return after_promo[-1][1]
    anchor = max(lowered.rfind("preis"), lowered.rfind("price"))
    if anchor != -1:
        after_anchor = [(p, v) for p, v in matches if p > anchor]
        if after_anchor:
            return after_anchor[0][1]
    return matches[0][1]


def detect_availability(text: str) -> str:
    low = text.lower()
    if any(k in low for k in OUT_OF_STOCK):
        return "out of stock"
    if any(k in low for k in IN_STOCK):
        return "in stock"
    return ""


async def fetch(url: str) -> ScrapeResult:
    res = ScrapeResult(source="tavily")
    headers = {
        "Authorization": f"Bearer {TAVILY_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"urls": [url], "extract_depth": "advanced"}
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(f"{TAVILY_API_URL}/extract", json=payload, headers=headers)
    if r.status_code != 200:
        res.error = f"HTTP {r.status_code}: {r.text[:300]}"
        return res
    data = r.json()
    results = data.get("results") or []
    failed = data.get("failed_results") or []
    if not results:
        res.error = f"no result{': ' + str(failed[0]) if failed else ''}"
        return res
    content = results[0].get("raw_content") or ""
    res.raw = {"content_chars": len(content)}
    if not content:
        res.error = "empty raw_content"
        return res
    res.price = extract_price(content)
    if res.price is None:
        res.error = "no price found in raw_content"
        return res
    res.currency = "EUR"
    res.availability = detect_availability(content)
    res.ok = True
    return res
