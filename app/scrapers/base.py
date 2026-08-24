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
    "required": ["product_name", "price"],
}

EXTRACTION_PROMPT = (
    "Extract the current selling price of the main product shown on this page. "
    "Use the displayed sales price including VAT, not a crossed-out list/UVP price. "
    "Return currency as ISO code (EUR, USD, ...). "
    "In availability describe the stock status (e.g. 'in stock', 'out of stock'). "
    "unit_price is the displayed price per unit like '12,67 EUR/m2' if shown, else empty."
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
