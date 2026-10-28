"""Deterministic seed data.

The same seed always produces the same database. Nothing here reads the clock:
the store has its own fixed "today" so runs are reproducible.
"""

import random
import sqlite3
from datetime import date, timedelta

from arl.env.store import connect, create_schema

DEFAULT_SEED = 7
SIM_TODAY = date(2026, 10, 5)

# Hand-written records. The sample tickets refer to these by id and email.
ANCHOR_CUSTOMERS = [
    ("CUS-0001", "Maya Chen", "maya.chen@example.com", "2025-03-14"),
    ("CUS-0002", "Omar Haddad", "omar.haddad@example.com", "2026-01-22"),
    ("CUS-0003", "Priya Nair", "priya.nair@example.com", "2024-11-02"),
]
ANCHOR_ORDERS = [
    # id, customer, status, placed_at, address, [(sku, name, quantity, unit_price_cents)]
    ("ORD-1001", "CUS-0001", "shipped", "2026-09-28", "18 Alder Street, Portland, OR 97205",
     [("SHOE-TR-42", "Trail running shoes", 1, 8900), ("SOCK-WL-3P", "Wool socks 3-pack", 2, 1250)]),
    ("ORD-1002", "CUS-0001", "delivered", "2026-09-10", "18 Alder Street, Portland, OR 97205",
     [("BLND-CT-01", "Countertop blender", 1, 7999)]),
    ("ORD-1003", "CUS-0002", "processing", "2026-10-03", "402 Mesa Drive, Austin, TX 78704",
     [("LAMP-DK-02", "Desk lamp", 1, 3450)]),
    ("ORD-1004", "CUS-0003", "delivered", "2026-08-16", "77 Harbor Road, Boston, MA 02110",
     [("KETL-EL-05", "Electric kettle", 1, 4200), ("MUG-CR-04", "Ceramic mug set", 1, 2400)]),
]
ANCHOR_SHIPMENTS = [
    # id, order, carrier, tracking, status, shipped_at, estimated_delivery, delivered_at
    ("SHP-5001", "ORD-1001", "UPS", "1Z999AA10123456784", "in_transit",
     "2026-09-30", "2026-10-07", None),
    ("SHP-5002", "ORD-1002", "FedEx", "784412309915", "delivered",
     "2026-09-11", "2026-09-15", "2026-09-14"),
    ("SHP-5004", "ORD-1004", "USPS", "9400111899223817465120", "delivered",
     "2026-08-17", "2026-08-21", "2026-08-20"),
]
ANCHOR_REFUNDS = [
    ("REF-9001", "ORD-1004", 2400, "Mug set arrived chipped", "issued", "2026-08-24"),
]

_FIRST = ["Ana", "Ben", "Chloe", "Dev", "Elena", "Farid", "Grace", "Hugo", "Ines", "Jonas"]
_LAST = ["Abara", "Brandt", "Castillo", "Dubois", "Eriksen", "Fontaine", "Garza", "Horvat"]
_CATALOG = [
    ("BOTL-ST-01", "Steel water bottle", 2200),
    ("PACK-DY-20", "Daypack 20L", 6400),
    ("HDPH-BT-03", "Bluetooth headphones", 12900),
    ("NOTE-A5-02", "A5 notebook 2-pack", 1100),
    ("TENT-2P-01", "Two-person tent", 18900),
    ("MAT-YG-06", "Yoga mat", 3800),
    ("CHRG-USB-C", "USB-C charger", 2900),
    ("PAN-CI-10", "Cast iron pan", 4500),
]
_CARRIERS = ["UPS", "FedEx", "USPS"]
_CITIES = ["Denver, CO 80202", "Seattle, WA 98101", "Chicago, IL 60601", "Miami, FL 33101"]


def _insert_order(conn, order_id, customer_id, status, placed_at, address, lines) -> None:
    total = sum(quantity * price for _, _, quantity, price in lines)
    conn.execute(
        "INSERT INTO orders (id, customer_id, status, placed_at, total_cents, shipping_address) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (order_id, customer_id, status, placed_at, total, address),
    )
    conn.executemany(
        "INSERT INTO items (order_id, sku, name, quantity, unit_price_cents) VALUES (?, ?, ?, ?, ?)",
        [(order_id, *line) for line in lines],
    )


def seed(conn: sqlite3.Connection, seed: int = DEFAULT_SEED) -> None:
    conn.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", ANCHOR_CUSTOMERS)
    for order in ANCHOR_ORDERS:
        _insert_order(conn, *order)
    conn.executemany("INSERT INTO shipments VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ANCHOR_SHIPMENTS)
    conn.executemany("INSERT INTO refunds VALUES (?, ?, ?, ?, ?, ?)", ANCHOR_REFUNDS)

    # Background records so the anchors are not the only rows in the store.
    rng = random.Random(seed)
    order_number = 2000
    for n in range(1, 21):
        customer_id = f"CUS-{100 + n:04d}"
        first, last = rng.choice(_FIRST), rng.choice(_LAST)
        joined = SIM_TODAY - timedelta(days=rng.randint(60, 700))
        conn.execute(
            "INSERT INTO customers VALUES (?, ?, ?, ?)",
            (customer_id, f"{first} {last}", f"{first}.{last}{n}@example.com".lower(),
             joined.isoformat()),
        )
        address = f"{rng.randint(1, 999)} {rng.choice(_LAST)} Avenue, {rng.choice(_CITIES)}"
        for _ in range(rng.randint(1, 3)):
            order_number += 1
            order_id = f"ORD-{order_number}"
            placed = SIM_TODAY - timedelta(days=rng.randint(1, 55))
            status = rng.choice(["processing", "shipped", "delivered", "delivered", "cancelled"])
            lines = [
                (sku, name, rng.randint(1, 2), price)
                for sku, name, price in rng.sample(_CATALOG, rng.randint(1, 3))
            ]
            _insert_order(conn, order_id, customer_id, status, placed.isoformat(), address, lines)
            if status in ("shipped", "delivered"):
                shipped = placed + timedelta(days=1)
                estimated = shipped + timedelta(days=rng.randint(3, 6))
                delivered = estimated if status == "delivered" else None
                conn.execute(
                    "INSERT INTO shipments VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"SHP-{order_number + 4000}", order_id, rng.choice(_CARRIERS),
                     str(rng.randint(10**11, 10**12 - 1)),
                     "delivered" if delivered else "in_transit",
                     shipped.isoformat(), estimated.isoformat(),
                     delivered.isoformat() if delivered else None),
                )
    conn.commit()


def new_store(seed_value: int = DEFAULT_SEED) -> sqlite3.Connection:
    """A fresh in-memory store. Every run and every test starts from one of these."""
    conn = connect()
    create_schema(conn)
    seed(conn, seed_value)
    return conn


# Tables a task's `setup` may add rows to (Stage 5: adversarial tasks plant order notes).
SETUP_TABLES = {"order_notes": "NOTE"}


def apply_setup(conn: sqlite3.Connection, setup: dict[str, list[dict]]) -> None:
    """Add a task's extra rows to a freshly seeded store. Ids are assigned if left out."""
    for table, rows in setup.items():
        if table not in SETUP_TABLES:
            raise ValueError(f"A task setup cannot add rows to '{table}'. "
                             f"Allowed: {', '.join(SETUP_TABLES)}")
        for n, row in enumerate(rows, start=1):
            row = {"id": f"{SETUP_TABLES[table]}-{n}", "created_at": SIM_TODAY.isoformat(),
                   **row}
            columns = ", ".join(row)
            conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({', '.join('?' * len(row))})",
                         tuple(row.values()))
    conn.commit()
