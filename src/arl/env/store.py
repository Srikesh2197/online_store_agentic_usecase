"""The simulated store: a SQLite database.

Money is stored as integer cents. Dates are ISO strings (YYYY-MM-DD).
"""

import sqlite3

SCHEMA = """
CREATE TABLE customers (
    id          TEXT PRIMARY KEY,           -- CUS-0001
    name        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,       -- stored lower-case
    created_at  TEXT NOT NULL
);

CREATE TABLE orders (
    id                TEXT PRIMARY KEY,     -- ORD-1001
    customer_id       TEXT NOT NULL REFERENCES customers(id),
    status            TEXT NOT NULL CHECK (status IN
                          ('processing', 'shipped', 'delivered', 'cancelled')),
    placed_at         TEXT NOT NULL,
    total_cents       INTEGER NOT NULL,
    shipping_address  TEXT NOT NULL
);

CREATE TABLE items (
    id                INTEGER PRIMARY KEY,
    order_id          TEXT NOT NULL REFERENCES orders(id),
    sku               TEXT NOT NULL,
    name              TEXT NOT NULL,
    quantity          INTEGER NOT NULL,
    unit_price_cents  INTEGER NOT NULL
);

CREATE TABLE shipments (
    id                  TEXT PRIMARY KEY,   -- SHP-5001
    order_id            TEXT NOT NULL UNIQUE REFERENCES orders(id),
    carrier             TEXT NOT NULL,
    tracking_number     TEXT NOT NULL,
    status              TEXT NOT NULL CHECK (status IN
                            ('label_created', 'in_transit', 'delayed', 'delivered')),
    shipped_at          TEXT NOT NULL,
    estimated_delivery  TEXT NOT NULL,
    delivered_at        TEXT
);

CREATE TABLE refunds (
    id            TEXT PRIMARY KEY,         -- REF-9001
    order_id      TEXT NOT NULL REFERENCES orders(id),
    amount_cents  INTEGER NOT NULL,
    reason        TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('pending', 'issued')),
    created_at    TEXT NOT NULL
);
"""


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def dollars(cents: int) -> str:
    return f"{cents / 100:.2f}"
