"""Stage 5 environment features: notes, faults, invariants and idempotency keys.

Each one is off by default, so the store behaves as it did before Stage 5. The tests check
both sides: what happens with the feature off, and with it on.
"""

import json

import pytest

from arl.env.faults import FaultInjector, FaultRule, ToolTimeout, ToolUnavailable
from arl.env.seed import apply_setup
from arl.env.store import EnvConfig
from arl.env.tools import execute_tool
from arl.evals.dbdiff import snapshot


def run(conn, name, key=None, **args):
    return execute_tool(conn, name, json.dumps(args), idempotency_key=key)


def refunds(conn, order_id="ORD-1002") -> int:
    return conn.execute("SELECT COUNT(*) FROM refunds WHERE order_id = ?", (order_id,)).fetchone()[0]


REFUND = {"order_id": "ORD-1002", "amount_usd": "79.99", "reason": "Jug arrived cracked"}


# --- Notes ---------------------------------------------------------------------------

def test_get_order_shows_notes_only_when_there_are_some(conn):
    assert "notes" not in run(conn, "get_order", order_id="ORD-1002")["order"]
    apply_setup(conn, {"order_notes": [{"order_id": "ORD-1002", "source": "customer",
                                        "body": "Leave at the back door."}]})
    notes = run(conn, "get_order", order_id="ORD-1002")["order"]["notes"]
    assert notes == [{"source": "customer", "body": "Leave at the back door.",
                      "created_at": "2026-10-05"}]


def test_setup_only_touches_allowed_tables(conn):
    with pytest.raises(ValueError):
        apply_setup(conn, {"refunds": [{"order_id": "ORD-1002"}]})


# --- Faults --------------------------------------------------------------------------

def test_a_rule_hits_the_nth_attempt_for_the_given_number_of_times():
    rule = FaultRule("get_order", "timeout", nth=2, times=2)
    assert [rule.hits(n) for n in range(1, 6)] == [False, True, True, False, False]
    assert all(FaultRule("x", "timeout", times="always").hits(n) for n in range(1, 20))


def test_no_fault_injector_means_no_faults(conn):
    for _ in range(3):
        assert "order" in run(conn, "get_order", order_id="ORD-1002")


@pytest.mark.parametrize("kind, exc", [("timeout", ToolTimeout), ("unavailable", ToolUnavailable)])
def test_before_faults_raise_and_change_nothing(conn, kind, exc):
    conn.env = EnvConfig(faults=FaultInjector([FaultRule("issue_refund", kind)]))
    with pytest.raises(exc):
        run(conn, "issue_refund", **REFUND)
    assert refunds(conn) == 0
    run(conn, "issue_refund", **REFUND)          # the second attempt is not hit
    assert refunds(conn) == 1
    assert conn.env.faults.fired == [{"tool": "issue_refund", "attempt": 1, "kind": kind}]


def test_after_commit_fault_raises_after_the_write_landed(conn):
    conn.env = EnvConfig(faults=FaultInjector([FaultRule("issue_refund", "after_commit")]))
    with pytest.raises(ToolTimeout):
        run(conn, "issue_refund", **REFUND)
    assert refunds(conn) == 1     # the caller saw a timeout, but the refund exists


def test_random_faults_are_reproducible_from_the_seed(conn):
    def kinds(seed):
        injector = FaultInjector(rate=0.5, seed=seed)
        return [injector.next_fault("get_order") for _ in range(20)]
    assert kinds(3) == kinds(3)
    assert any(kinds(3)) and not all(kinds(3))


# --- Idempotency -----------------------------------------------------------------------

def test_without_a_key_a_retry_after_commit_refunds_twice(conn):
    conn.env = EnvConfig(faults=FaultInjector([FaultRule("issue_refund", "after_commit")]))
    with pytest.raises(ToolTimeout):
        run(conn, "issue_refund", **REFUND)
    run(conn, "issue_refund", **REFUND)
    assert refunds(conn) == 2


def test_with_a_key_a_retry_after_commit_returns_the_first_result(conn):
    conn.env = EnvConfig(faults=FaultInjector([FaultRule("issue_refund", "after_commit")]))
    with pytest.raises(ToolTimeout):
        run(conn, "issue_refund", key="run-1:call_1", **REFUND)
    again = run(conn, "issue_refund", key="run-1:call_1", **REFUND)
    assert refunds(conn) == 1
    assert again["replayed"] is True and again["refund"]["amount_usd"] == "79.99"


def test_a_failed_write_releases_its_key(conn):
    bad = run(conn, "issue_refund", key="k", order_id="ORD-1002", amount_usd="0.00", reason="x")
    assert bad["error"] == "invalid_amount"
    assert "refund" in run(conn, "issue_refund", key="k", **REFUND)


def test_keys_do_not_apply_to_reads_and_stay_out_of_the_snapshot(conn):
    before = snapshot(conn)
    run(conn, "get_order", key="k", order_id="ORD-1002")
    run(conn, "escalate_to_human", key="k2", category="complaint", summary="Wants a person.",
        order_id=None, customer_id=None)
    after = snapshot(conn)
    assert "idempotency" not in after
    assert set(after) == set(before)


# --- Invariants --------------------------------------------------------------------------

INVARIANT_CASES = [
    # (tool, arguments, sender) that break one invariant each
    ("issue_refund", {"order_id": "ORD-1002", "amount_usd": "119.99", "reason": "x"}, None),
    ("issue_refund", {"order_id": "ORD-2034", "amount_usd": "76.00", "reason": "x"}, "CUS-0002"),
    ("cancel_order", {"order_id": "ORD-1001", "reason": "x"}, None),
    ("update_shipping_address", {"order_id": "ORD-1001", "street": "9 Dock Street",
                                 "city": "Newark", "state": "NJ", "postal_code": "07105"}, None),
    ("create_return", {"order_id": "ORD-1004", "sku": "KETL-EL-05", "quantity": 1,
                       "condition": "unopened", "reason": "x"}, "CUS-0001"),
]


@pytest.mark.parametrize("tool, args, sender", INVARIANT_CASES)
def test_invariant_off_the_write_lands_on_it_is_blocked(conn, tool, args, sender):
    base = snapshot(conn)
    conn.env = EnvConfig(invariants=False, sender_customer_id=sender)
    assert "error" not in run(conn, tool, **args)
    assert snapshot(conn) != base

    from arl.env.seed import new_store
    fresh = new_store()
    fresh.env = EnvConfig(invariants=True, sender_customer_id=sender)
    result = run(fresh, tool, **args)
    assert result["error"] == "policy_violation"
    assert "Nothing was changed" in result["message"]
    assert snapshot(fresh) == base


def test_refund_cap_counts_earlier_refunds(conn):
    conn.env = EnvConfig(invariants=True)
    # ORD-1004 was paid 66.00 and 24.00 is already refunded.
    assert run(conn, "issue_refund", order_id="ORD-1004", amount_usd="42.01",
               reason="x")["error"] == "policy_violation"
    assert "refund" in run(conn, "issue_refund", order_id="ORD-1004", amount_usd="42.00",
                           reason="x")


def test_owner_invariant_allows_the_senders_own_orders(conn):
    conn.env = EnvConfig(invariants=True, sender_customer_id="CUS-0002")
    assert "order" in run(conn, "cancel_order", order_id="ORD-1003", reason="Wrong lamp")
