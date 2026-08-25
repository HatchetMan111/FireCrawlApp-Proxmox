import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, demo, scheduler
from .config import CHECK_INTERVAL_MINUTES
from .services import check_all, check_product, normalize_url, retailer_from_url
from .settings_store import demo_active, status as settings_status

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

_background_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    if demo_active():
        demo.seed_if_empty()
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="FireCrawlApp", lifespan=lifespan)


class ProductCreate(BaseModel):
    url: str
    name: str = ""
    interval_hours: int | None = None


class ProductUpdate(BaseModel):
    name: str | None = None
    active: bool | None = None
    interval_hours: int | None = None
    note: str | None = None


def _clamp_interval(hours: int | None) -> int | None:
    if hours is None:
        return None
    return min(max(int(hours), 1), 24 * 30)


class SettingsUpdate(BaseModel):
    firecrawl_api_key: str | None = None
    tavily_api_key: str | None = None
    demo_mode: str | None = None


def _spawn(coro) -> None:
    task = asyncio.get_running_loop().create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@app.get("/api/status")
def status():
    ss = settings_status()
    return {
        "firecrawl": ss["firecrawl"]["configured"],
        "tavily": ss["tavily"]["configured"],
        "demo": ss["demo_active"],
        "check_interval_minutes": CHECK_INTERVAL_MINUTES,
        "next_run": scheduler.next_run(),
        "stats": db.stats(),
    }


@app.get("/api/settings")
def get_settings():
    return settings_status()


@app.post("/api/settings")
async def update_settings(body: SettingsUpdate):
    if body.firecrawl_api_key is not None:
        db.set_setting("firecrawl_api_key", body.firecrawl_api_key.strip() or None)
    if body.tavily_api_key is not None:
        db.set_setting("tavily_api_key", body.tavily_api_key.strip() or None)
    if body.demo_mode is not None:
        if body.demo_mode not in ("auto", "on", "off"):
            raise HTTPException(status_code=400, detail="demo_mode muss auto|on|off sein")
        db.set_setting("demo_mode", body.demo_mode or None)
    return settings_status()


@app.post("/api/demo/exit")
async def demo_exit():
    db.set_setting("demo_mode", "off")
    return {"ok": True, **settings_status()}


@app.post("/api/demo/clear-products")
async def demo_clear_products():
    removed = 0
    for p in db.list_products():
        if p["last_source"] == "demo":
            db.delete_product(p["id"])
            removed += 1
    db.add_event(None, "info", f"\U0001F9F9 {removed} Demo-Produkte entfernt.")
    return {"removed": removed}


def _product_payload(p: dict) -> dict:
    hist = [
        h
        for h in db.history(p["id"], days=30)
        if h["price"] is not None
    ]
    prev = db.previous_price(p["id"])
    change_abs = change_pct = None
    if prev and prev["price"] and p["last_price"]:
        change_abs = round(p["last_price"] - prev["price"], 2)
        change_pct = round(change_abs / prev["price"] * 100, 1)
    prices = [h["price"] for h in hist]
    next_check = None
    if p["last_checked"]:
        from datetime import datetime, timedelta

        lc = datetime.strptime(p["last_checked"], "%Y-%m-%d %H:%M:%S")
        next_check = (lc + timedelta(hours=p.get("interval_hours") or 24)).isoformat()
    return {
        **p,
        "active": bool(p["active"]),
        "change_abs": change_abs,
        "change_pct": change_pct,
        "min_30d": min(prices) if prices else None,
        "max_30d": max(prices) if prices else None,
        "next_check_at": next_check,
        "sparkline": [{"t": h["checked_at"], "p": h["price"]} for h in hist[-40:]],
    }


@app.get("/api/products")
def list_products():
    return [_product_payload(p) for p in db.list_products()]


@app.post("/api/products", status_code=201)
async def add_product(body: ProductCreate):
    url = normalize_url(body.url)
    if not url or not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Bitte eine gültige Produkt-URL angeben")
    existing = db.get_product_by_url(url)
    if existing:
        if existing["last_source"] != "demo" and existing["last_price"] is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "URL wird bereits getrackt",
                    "product_id": existing["id"],
                },
            )
        db.reset_product(existing["id"], body.name.strip())
        db.delete_history(existing["id"])
        product = db.get_product(existing["id"])
        _spawn(check_product(product))
        return {"replaced_existing": True, **_product_payload(product)}
    pid = db.create_product(url, body.name.strip(), retailer_from_url(url))
    interval = _clamp_interval(body.interval_hours)
    if interval is not None:
        db.update_product(pid, interval_hours=interval)
    product = db.get_product(pid)
    _spawn(check_product(product))
    return _product_payload(product)


@app.patch("/api/products/{pid}")
def patch_product(pid: int, body: ProductUpdate):
    if not db.get_product(pid):
        raise HTTPException(status_code=404, detail="Produkt nicht gefunden")
    note = body.note[:2000] if body.note is not None else None
    db.update_product(
        pid,
        name=body.name,
        active=body.active,
        interval_hours=_clamp_interval(body.interval_hours),
        note=note,
    )
    return _product_payload(db.get_product(pid))


@app.post("/api/products/{pid}/reset")
async def reset_product(pid: int):
    product = db.get_product(pid)
    if not product:
        raise HTTPException(status_code=404, detail="Produkt nicht gefunden")
    db.delete_history(pid)
    db.reset_product(pid, product["name"])
    db.add_event(pid, "info", f"🔄 {product['name'] or product['url']}: zurückgesetzt, neue Prüfung läuft …")

    async def run():
        await check_product(db.get_product(pid))

    _spawn(run())
    return {"reset": True}


@app.delete("/api/products/{pid}")
def remove_product(pid: int):
    if not db.get_product(pid):
        raise HTTPException(status_code=404, detail="Produkt nicht gefunden")
    db.delete_product(pid)
    return {"deleted": pid}


@app.post("/api/products/{pid}/check")
async def check_one(pid: int):
    product = db.get_product(pid)
    if not product:
        raise HTTPException(status_code=404, detail="Produkt nicht gefunden")

    async def run():
        await check_product(product)

    _spawn(run())
    return {"started": True, "product": product["name"] or product["url"]}


@app.post("/api/check-all")
async def check_everything():
    _spawn(check_all())
    return {"started": True}


@app.get("/api/products/{pid}/history")
def product_history(pid: int, days: int = 30):
    if not db.get_product(pid):
        raise HTTPException(status_code=404, detail="Produkt nicht gefunden")
    return db.history(pid, days=min(max(days, 1), 365))


@app.get("/api/events")
def events(limit: int = 50):
    return db.list_events(limit=min(max(limit, 1), 200))


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
