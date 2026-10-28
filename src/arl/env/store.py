"""The simulated store: a SQLite database.

Money is stored as integer cents. Dates are ISO strings (YYYY-MM-DD).

A connection carries `env`, the settings of the world for one trial: which tool faults to
inject, whether the write tools enforce the policy invariants, and who the signed-in sender
is. The default is everything off, which is the store as it was before Stage 5. The agent
loop never sees `env`; only the tools read it.
"""

import sqlite3
from dataclasses import dataclass

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
    shipping_address  TEXT NOT NULL,
    cancel_reason     TEXT                  -- set by cancel_order
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

CREATE TABLE returns (
    id          TEXT PRIMARY KEY,           -- RMA-7001
    order_id    TEXT NOT NULL REFERENCES orders(id),
    sku         TEXT NOT NULL,
    quantity    INTEGER NOT NULL,
    condition   TEXT NOT NULL CHECK (condition IN ('unopened', 'opened', 'damaged')),
    reason      TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('authorized', 'received')),
    created_at  TEXT NOT NULL
);

-- Free text attached to an order by someone other than the agent: the customer at checkout,
-- the carrier or the warehouse. get_order shows it only when a note exists. It is the
-- channel for indirect prompt injection (Stage 5); the v1 seed has no notes.
CREATE TABLE order_notes (
    id          TEXT PRIMARY KEY,           -- NOTE-1
    order_id    TEXT NOT NULL REFERENCES orders(id),
    source      TEXT NOT NULL CHECK (source IN ('customer', 'carrier', 'warehouse')),
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

-- A handoff to a person. Kept in the database so an escalation is part of the end state.
CREATE TABLE escalations (
    id           TEXT PRIMARY KEY,          -- ESC-3001
    category     TEXT NOT NULL CHECK (category IN
                     ('policy_exception', 'cannot_verify', 'complaint', 'other')),
    summary      TEXT NOT NULL,
    order_id     TEXT REFERENCES orders(id),
    customer_id  TEXT REFERENCES customers(id),
    status       TEXT NOT NULL CHECK (status IN ('open', 'closed')),
    created_at   TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class EnvConfig:
    invariants: bool = False                 # write tools enforce the policy invariants
    sender_customer_id: str | None = None    # the signed-in sender, if the ticket has one
    faults: object | None = None             # an env.faults.FaultInjector, or None


class Store(sqlite3.Connection):
    """A SQLite connection that carries the trial's environment settings."""

    env: EnvConfig = EnvConfig()


def env_of(conn: sqlite3.Connection) -> EnvConfig:
    return getattr(conn, "env", Store.env)


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path, factory=Store)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def dollars(cents: int) -> str:
    return f"{cents / 100:.2f}"
