from dataclasses import dataclass, field
import re


@dataclass
class ScrapeResult:
    ok: bool = False
    price: float | None = None
    currency: str | None = None
    availability: str = ""
    product_name: str = ""
    source: str = ""
    raw: dict = field(default_factory=dict)
    error: str = ""


EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "product_name": {"type": "string"},
        "price": {"type": ["number", "null"]},
        "currency": {"type": "string"},
        "availability": {"type": "string"},
        "unit_price": {"type": "string"},
    },
    "required": ["product_name"],
}

EXTRACTION_PROMPT = (
    "Find the current selling price of the MAIN product on this shop page. "
    "Look for price elements near the product title or the add-to-cart button, "
    "e.g. elements with class/id containing 'price', aria-labels like 'Preis', "
    "or meta tags like product:price:amount. "
    "German shops format prices as '1.299,99' or '701,00'; English as '1,299.99'. "
    "Return the CURRENT purchase price including VAT - NOT a crossed-out old/UVP/statt "
    "price and NOT prices of related products or recommendations. "
    "If no price is visible at all, set price to null. "
    "currency: ISO code (EUR, USD...). availability: stock status ('in stock', 'out of stock'). "
    "unit_price: the displayed per-unit price like '12,67 EUR/m2' or 'EUR 3,49/Stk' if shown, else empty."
)


def parse_price_value(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if 0 < float(value) < 10_000_000 else None
    s = str(value).strip().replace("\u00a0", " ").replace("€", "").replace("EUR", "").strip()
    if not s:
        return None
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
    return p if 0 < p < 10_000_000 else None
