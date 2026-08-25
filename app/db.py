import sqlite3
from contextlib import contextmanager

from .config import DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL DEFAULT '',
  retailer TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1,
  last_price REAL,
  last_currency TEXT DEFAULT 'EUR',
  last_availability TEXT DEFAULT '',
  last_source TEXT DEFAULT '',
  last_checked TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS price_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  price REAL,
  currency TEXT DEFAULT 'EUR',
  availability TEXT DEFAULT '',
  source TEXT DEFAULT '',
  error TEXT DEFAULT '',
  checked_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  message TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_product ON price_history(product_id, checked_at);
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with get_db() as db:
        db.executescript(SCHEMA)
        cols = {r["name"] for r in db.execute("PRAGMA table_info(products)")}
        if "interval_hours" not in cols:
            db.execute(
                "ALTER TABLE products ADD COLUMN interval_hours INTEGER NOT NULL DEFAULT 24"
            )


def list_products() -> list[dict]:
    with get_db() as db:
        return [dict(r) for r in db.execute("SELECT * FROM products ORDER BY id")]


def get_product(pid: int) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        return dict(row) if row else None


def get_product_by_url(url: str) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM products WHERE url=?", (url,)).fetchone()
        return dict(row) if row else None


def create_product(url: str, name: str = "", retailer: str = "") -> int:
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO products(url,name,retailer) VALUES(?,?,?)",
            (url, name, retailer),
        )
        return cur.lastrowid


def update_product(pid: int, **fields) -> None:
    allowed = {"name", "active", "interval_hours"}
    keys = [k for k in fields if k in allowed and fields[k] is not None]
    if not keys:
        return
    sets = ", ".join(f"{k}=?" for k in keys)
    vals = [fields[k] for k in keys] + [pid]
    with get_db() as db:
        db.execute(f"UPDATE products SET {sets} WHERE id=?", vals)


def delete_product(pid: int) -> None:
    with get_db() as db:
        db.execute("DELETE FROM products WHERE id=?", (pid,))


def last_price_row(pid: int) -> dict | None:
    with get_db() as db:
        row = db.execute(
            "SELECT price, checked_at FROM price_history "
            "WHERE product_id=? AND price IS NOT NULL "
            "ORDER BY checked_at DESC, id DESC LIMIT 1",
            (pid,),
        ).fetchone()
        return dict(row) if row else None


def previous_price(pid: int) -> dict | None:
    with get_db() as db:
        row = db.execute(
            "SELECT price, checked_at FROM price_history "
            "WHERE product_id=? AND price IS NOT NULL "
            "ORDER BY checked_at DESC, id DESC LIMIT 1 OFFSET 1",
            (pid,),
        ).fetchone()
        return dict(row) if row else None


def due_products() -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM products WHERE active=1 AND ("
            "last_checked IS NULL OR "
            "last_checked <= datetime('now', '-' || interval_hours || ' hours')) "
            "ORDER BY last_checked"
        ).fetchall()
        return [dict(r) for r in rows]


def insert_history(
    pid: int,
    price: float | None,
    currency: str = "EUR",
    availability: str = "",
    source: str = "",
    error: str = "",
    checked_at: str | None = None,
) -> None:
    with get_db() as db:
        if checked_at:
            db.execute(
                "INSERT INTO price_history(product_id,price,currency,availability,source,error,checked_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (pid, price, currency, availability, source, error, checked_at),
            )
        else:
            db.execute(
                "INSERT INTO price_history(product_id,price,currency,availability,source,error) "
                "VALUES(?,?,?,?,?,?)",
                (pid, price, currency, availability, source, error),
            )


def history(pid: int, days: int = 30) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT price, availability, source, error, checked_at FROM price_history "
            "WHERE product_id=? AND checked_at >= datetime('now', ?) "
            "ORDER BY checked_at",
            (pid, f"-{int(days)} days"),
        ).fetchall()
        return [dict(r) for r in rows]


def update_after_check(
    pid: int, price: float, currency: str, availability: str, source: str
) -> None:
    with get_db() as db:
        db.execute(
            "UPDATE products SET last_price=?, last_currency=?, last_availability=?, "
            "last_source=?, last_checked=datetime('now') WHERE id=?",
            (price, currency, availability, source, pid),
        )


def mark_checked(pid: int) -> None:
    with get_db() as db:
        db.execute("UPDATE products SET last_checked=datetime('now') WHERE id=?", (pid,))


def add_event(pid: int | None, etype: str, message: str) -> None:
    with get_db() as db:
        db.execute(
            "INSERT INTO events(product_id,type,message) VALUES(?,?,?)",
            (pid, etype, message),
        )


def list_events(limit: int = 50) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT e.*, p.name AS product_name FROM events e "
            "LEFT JOIN products p ON p.id=e.product_id "
            "ORDER BY e.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_setting(key: str, default: str | None = None) -> str | None:
    with get_db() as db:
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row and row["value"] != "" else default


def set_setting(key: str, value: str | None) -> None:
    with get_db() as db:
        if value is None or value == "":
            db.execute("DELETE FROM settings WHERE key=?", (key,))
        else:
            db.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )


def delete_history(pid: int) -> None:
    with get_db() as db:
        db.execute("DELETE FROM price_history WHERE product_id=?", (pid,))


def reset_product(pid: int, name: str = "") -> None:
    with get_db() as db:
        if name:
            db.execute("UPDATE products SET name=?, last_price=NULL, last_availability='', "
                       "last_source='', last_checked=NULL WHERE id=?", (name, pid))
        else:
            db.execute("UPDATE products SET last_price=NULL, last_availability='', "
                       "last_source='', last_checked=NULL WHERE id=?", (pid,))


def stats() -> dict:
    with get_db() as db:
        products = db.execute("SELECT COUNT(*) c FROM products").fetchone()["c"]
        checks_today = db.execute(
            "SELECT COUNT(*) c FROM price_history WHERE checked_at >= date('now')"
        ).fetchone()["c"]
        drops = db.execute(
            "SELECT COUNT(*) c FROM events WHERE type='price_drop' "
            "AND created_at >= datetime('now','-7 days')"
        ).fetchone()["c"]
        rises = db.execute(
            "SELECT COUNT(*) c FROM events WHERE type='price_rise' "
            "AND created_at >= datetime('now','-7 days')"
        ).fetchone()["c"]
        return {
            "products": products,
            "checks_today": checks_today,
            "drops_7d": drops,
            "rises_7d": rises,
        }
