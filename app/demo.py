import hashlib
import random
from datetime import datetime, timedelta
from urllib.parse import urlparse

from . import db

DEMO_PRODUCTS = [
    (
        "https://www.bauhaus.info/verlegeplatten/osb-verlegeplatte-palette/p/28582379",
        "OSB Verlegeplatte Palette 22 mm (BAUHAUS)",
    ),
    (
        "https://www.hornbach.de/p/osb-3-verlegeplatte-palette-18-mm/8324512/",
        "OSB 3 Verlegeplatte Palette 18 mm (Hornbach)",
    ),
    (
        "https://www.toom.de/p/osb-verlegeplatte-palette-12-mm/9512837",
        "OSB Verlegeplatte Palette 12 mm (toom)",
    ),
]


def seed_if_empty() -> None:
    if db.list_products():
        return
    for url, name in DEMO_PRODUCTS:
        digest = int(hashlib.sha256(url.encode()).hexdigest(), 16)
        base = 100 + digest % 600
        retailer = urlparse(url).netloc.removeprefix("www.").split(".")[0].capitalize()
        pid = db.create_product(url, name, retailer)
        price = float(base + digest % 40)
        now = datetime.now()
        for d in range(30, -1, -1):
            price = round(max(1.0, price * random.uniform(0.975, 1.025)), 2)
            ts = (now - timedelta(days=d)).strftime("%Y-%m-%d %H:%M:%S")
            avail = "in stock" if random.random() > 0.08 else "low stock"
            db.insert_history(pid, price, "EUR", avail, "demo", checked_at=ts)
        last = db.last_price_row(pid)
        if last:
            db.update_after_check(pid, last["price"], "EUR", "in stock", "demo")
    db.add_event(None, "info", "\U0001F4A1 Demo-Modus aktiv: keine API-Keys gesetzt. Preise sind simuliert.")
