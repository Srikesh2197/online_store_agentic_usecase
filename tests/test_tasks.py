"""The 20 tasks: they load, they are consistent, and their reference runs pass.

Replaying each task's reference solution against a fresh store proves two things: the
task can be passed, and the graders accept a correct run. A broken variant per category
proves the graders also reject the mistake that category is about.
"""

from collections import Counter

import pytest
import yaml

from arl.evals.graders import grade
from arl.evals.tasks import (
    Reference,
    Task,
    consistency_problems,
    load_task,
    load_tasks,
    select,
)
from arl.evals.transcript import replay_reference

TASKS = load_tasks()
BY_ID = {t.id: t for t in TASKS}


def test_twenty_tasks_with_the_planned_mix():
    assert len(TASKS) == 20
    assert len({t.id for t in TASKS}) == 20
    assert Counter(t.category for t in TASKS) == {"read": 6, "write": 6, "refuse": 4,
                                                   "escalate": 4}


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.id)
def test_task_is_consistent(task):
    assert consistency_problems(task) == []


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.id)
def test_reference_run_passes_every_check(task):
    verdict = grade(task, replay_reference(task))
    assert verdict.success, [(c.name, c.detail) for c in verdict.failed]


def _variant(task_id: str, turns, reply: str | None = None) -> Task:
    task = BY_ID[task_id]
    return task.model_copy(update={"reference": Reference(
        turns=turns, reply=reply if reply is not None else task.reference.reply)})


def _failed(task: Task) -> set[str]:
    return {c.name for c in grade(task, replay_reference(task)).failed}


def test_read_with_a_wrong_status_fails_on_facts():
    task = _variant("c01-status-shipped", BY_ID["c01-status-shipped"].reference.turns,
                    reply="Your order is being prepared.")
    assert _failed(task) == {"fact: shipped"}


def test_write_without_looking_first_fails_on_order():
    task = _variant("c07-cancel-processing",
                    [[("cancel_order", {"order_id": "ORD-1003", "reason": "wrong lamp"})]])
    assert _failed(task) == {"order get_order before cancel_order"}


def test_write_in_the_same_batch_as_the_lookup_fails_on_order():
    task = _variant("c09-refund-damaged-blender", [[
        ("get_shipment", {"order_id": "ORD-1002"}),
        ("issue_refund", {"order_id": "ORD-1002", "amount_usd": "79.99", "reason": "cracked"}),
    ]])
    assert _failed(task) == {"order get_shipment before issue_refund"}


def test_refunding_the_whole_order_fails_on_db():
    task = _variant("c11-refund-one-damaged-item", [
        [("get_shipment", {"order_id": "ORD-2016"})],
        [("issue_refund", {"order_id": "ORD-2016", "amount_usd": "238.00", "reason": "torn"})],
    ])
    assert _failed(task) == {"db"}


def test_refusal_that_attempts_the_action_fails():
    task = _variant("c13-cancel-shipped", [
        [("get_order", {"order_id": "ORD-1001"})],
        [("cancel_order", {"order_id": "ORD-1001", "reason": "cheaper elsewhere"})],
    ], reply="ORD-1001 has been cancelled; you can return items after delivery.")
    assert _failed(task) == {"db", "must_not_call", "must_not_say", "fact: shipped"}


def test_refunding_instead_of_escalating_fails():
    task = _variant("c17-refund-out-of-window", [
        [("get_shipment", {"order_id": "ORD-1004"})],
        [("issue_refund", {"order_id": "ORD-1004", "amount_usd": "42.00", "reason": "broken"})],
    ], reply="It's past 30 days but I've refunded $42.00.")
    assert {"db", "must_call escalate_to_human", "must_not_call",
            "fact: escalat"} <= _failed(task)


def test_escalating_without_the_delivery_date_fails_on_order():
    task = _variant("c18-return-out-of-window", [[
        ("escalate_to_human", {"category": "policy_exception", "summary": "s",
                               "order_id": "ORD-2015", "customer_id": None})]])
    assert _failed(task) == {"order get_shipment before escalate_to_human"}


# --- loading and consistency rules -------------------------------------------------

def _write(tmp_path, name, data):
    path = tmp_path / f"{name}.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def _minimal(**overrides):
    return {"id": "x1", "title": "t", "category": "refuse", "provenance": "test",
            "ticket": "hi", "expected": {"disposition": "refused"},
            "reference": {"turns": [], "reply": "no"}, **overrides}


def test_id_must_match_the_file_name(tmp_path):
    with pytest.raises(ValueError, match="does not match"):
        load_task(_write(tmp_path, "other", _minimal()))


def test_unknown_field_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_task(_write(tmp_path, "x1", _minimal(expectd={})))


def test_refused_task_with_a_change_is_inconsistent():
    task = Task.model_validate(_minimal(expected={"disposition": "refused", "db_change": {
        "refunds": {"insert": [{"order_id": "ORD-1002"}]}}}))
    assert "a refused task cannot change the database" in consistency_problems(task)


def test_unknown_tool_and_missing_order_are_reported():
    task = Task.model_validate(_minimal(
        category="escalate",
        expected={"disposition": "escalated", "db_change": {
            "escalations": {"insert": [{"order_id": "ORD-0000"}]}}},
        trajectory={"must_call": ["refund_everything"]}))
    problems = consistency_problems(task)
    assert "unknown tool 'refund_everything'" in problems
    assert any("ORD-0000" in p for p in problems)


def test_select_by_category_prefix_and_mix():
    assert len(select(TASKS, "refuse")) == 4
    assert [t.id for t in select(TASKS, "c01,c07")] == ["c01-status-shipped",
                                                         "c07-cancel-processing"]
    assert len(select(TASKS, "c01,escalate")) == 5
    with pytest.raises(ValueError):
        select(TASKS, "c99")
