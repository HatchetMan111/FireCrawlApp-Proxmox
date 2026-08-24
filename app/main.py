import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl

from . import db, demo, scheduler
from .config import (
    CHECK_SCHEDULE,
    FIRECRAWL_API_KEY,
    FIRECRAWL_API_URL,
    TAVILY_API_KEY,
    TAVILY_API_URL,
    demo_enabled,
)
from .services import check_all, check_product, retailer_from_url

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

_background_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    if demo_enabled():
        demo.seed_if_empty()
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="FireCrawlApp", lifespan=lifespan)


class ProductCreate(BaseModel):
    url: HttpUrl
    name: str = ""


class ProductUpdate(BaseModel):
    name: str | None = None
    active: bool | None = None


def _spawn(coro) -> None:
    task = asyncio.get_running_loop().create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@app.get("/api/status")
def status():
    return {
        "firecrawl": bool(FIRECRAWL_API_KEY),
        "tavily": bool(TAVILY_API_KEY),
        "demo": demo_enabled(),
        "firecrawl_url": FIRECRAWL_API_URL,
        "tavily_url": TAVILY_API_URL,
        "schedule": CHECK_SCHEDULE,
        "next_run": scheduler.next_run(),
        "stats": db.stats(),
    }


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
    return {
        **p,
        "active": bool(p["active"]),
        "change_abs": change_abs,
        "change_pct": change_pct,
        "min_30d": min(prices) if prices else None,
        "max_30d": max(prices) if prices else None,
        "sparkline": [{"t": h["checked_at"], "p": h["price"]} for h in hist[-40:]],
    }


@app.get("/api/products")
def list_products():
    return [_product_payload(p) for p in db.list_products()]


@app.post("/api/products", status_code=201)
async def add_product(body: ProductCreate):
    url = str(body.url).rstrip("/")
    existing = db.get_product_by_url(url)
    if existing:
        raise HTTPException(status_code=409, detail="URL wird bereits getrackt")
    pid = db.create_product(url, body.name.strip(), retailer_from_url(url))
    product = db.get_product(pid)
    _spawn(check_product(product))
    return _product_payload(product)


@app.patch("/api/products/{pid}")
def patch_product(pid: int, body: ProductUpdate):
    if not db.get_product(pid):
        raise HTTPException(status_code=404, detail="Produkt nicht gefunden")
    db.update_product(pid, name=body.name, active=body.active)
    return db.get_product(pid)


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
