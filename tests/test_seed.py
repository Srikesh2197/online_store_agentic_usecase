from arl.env.seed import new_store


def _dump(conn) -> list[str]:
    return list(conn.iterdump())


def test_same_seed_gives_identical_database():
    assert _dump(new_store(7)) == _dump(new_store(7))


def test_different_seed_gives_different_database():
    assert _dump(new_store(7)) != _dump(new_store(8))


def test_anchor_records_survive_any_seed():
    for seed in (7, 8):
        conn = new_store(seed)
        order = conn.execute("SELECT * FROM orders WHERE id = 'ORD-1001'").fetchone()
        assert order["customer_id"] == "CUS-0001"
        assert order["status"] == "shipped"
        assert order["total_cents"] == 8900 + 2 * 1250


def test_every_table_has_rows(conn):
    for table in ("customers", "orders", "items", "shipments", "refunds"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0


def test_order_totals_match_their_items(conn):
    mismatched = conn.execute(
        "SELECT o.id FROM orders o JOIN items i ON i.order_id = o.id "
        "GROUP BY o.id HAVING o.total_cents != SUM(i.quantity * i.unit_price_cents)"
    ).fetchall()
    assert mismatched == []
