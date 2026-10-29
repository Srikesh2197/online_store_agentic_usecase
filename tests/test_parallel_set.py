"""Stage 8: the parallel task set (8 bulk audits). No API calls.

Each task names several orders whose lookups and judgements are independent, so the work can
be split between agents. The checks here are about validity, not difficulty: every
reference solution passes the real graders, the tasks are consistent with the store, and a
single agent doing the reference run stays well inside its own token budget.
"""

import json

import pytest

from arl.evals.graders import grade
from arl.evals.runner import CHARS_PER_TOKEN, request_chars
from arl.evals.tasks import (
    ADVERSARIAL_SET,
    FROZEN_ADVERSARIAL_HASH,
    FROZEN_PARALLEL_HASH,
    FROZEN_V1_HASH,
    PARALLEL_SET,
    consistency_problems,
    load_tasks,
    task_set_hash,
)
from arl.evals.transcript import replay_reference
from arl.guardrails import ALL

PARALLEL = load_tasks(PARALLEL_SET)
# JSON tool results tokenize more densely than prose; 4 characters a token is conservative.
RESULT_CHARS_PER_TOKEN = 4
REPLY_TOKENS = 300   # a generous reply or a batch of calls, per model call


def test_the_set_has_eight_tasks_five_read_and_three_write():
    assert len(PARALLEL) == 8
    assert [t.category for t in PARALLEL].count("read") == 5
    assert [t.category for t in PARALLEL].count("write") == 3
    assert {t.provenance for t in PARALLEL} == {"parallel-v1"}


def test_no_task_needs_the_environment_changed():
    for task in PARALLEL:
        assert not task.setup and not task.faults and not task.sender and task.attack is None


@pytest.mark.parametrize("task", PARALLEL, ids=lambda t: t.id)
def test_each_task_is_consistent_with_the_store(task):
    assert consistency_problems(task) == []


@pytest.mark.parametrize("task", PARALLEL, ids=lambda t: t.id)
@pytest.mark.parametrize("invariants", [False, True])
def test_each_reference_passes_the_real_graders(task, invariants):
    verdict = grade(task, replay_reference(task, invariants=invariants))
    assert verdict.success, [c for c in verdict.checks if not c.passed]


@pytest.mark.parametrize("task", PARALLEL, ids=lambda t: t.id)
def test_a_single_agent_doing_the_reference_stays_well_inside_its_budget(task):
    """Every call resends the history: request 1, then each turn's results and output."""
    transcript = replay_reference(task)
    base = request_chars("gpt-6-luna", task.ticket) / CHARS_PER_TOKEN["openai"]
    turns = len(task.reference.turns)
    by_turn = [sum(len(json.dumps(c.result)) for c in transcript.tool_calls if c.turn == n)
               / RESULT_CHARS_PER_TOKEN for n in range(1, turns + 1)]
    total = sum(base + sum(by_turn[:i]) + i * REPLY_TOKENS + REPLY_TOKENS
                for i in range(turns + 1))
    assert total < 0.75 * ALL.limits.max_tokens, round(total)


def test_bulk_audits_name_six_orders_each():
    for task in PARALLEL:
        if task.id[:3] in ("p01", "p02", "p03", "p04"):
            assert len(task.trajectory.must_call) == 6


def test_the_other_sets_are_unchanged():
    assert task_set_hash() == FROZEN_V1_HASH
    assert task_set_hash(ADVERSARIAL_SET) == FROZEN_ADVERSARIAL_HASH


def test_the_parallel_set_is_frozen_once_calibrated():
    if FROZEN_PARALLEL_HASH is None:
        pytest.skip("not frozen yet: calibration on the single agent comes first")
    assert task_set_hash(PARALLEL_SET) == FROZEN_PARALLEL_HASH
