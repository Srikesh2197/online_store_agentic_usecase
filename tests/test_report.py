"""Report statistics and tables, on fixed results documents."""

import pytest

from arl.evals.graders import GROUPS
from arl.evals.report import (
    min_one_sided_tasks,
    paired_table,
    pass_hat_k,
    per_task,
    sign_test_p,
    summary,
)


def _trial(task_id, success, category="read", error=None, cost=0.001, latency=1000):
    return {"task_id": task_id, "category": category, "trial": 1, "success": success,
            "error": error, "model_calls": 2, "usage": {"input_tokens": 100, "output_tokens": 10},
            "cost_usd": cost, "latency_ms": latency, "max_tokens_endings": 0,
            "verdict": {"success": success, "error": error, "checks": [],
                        "groups": {g: success for g in GROUPS}}}


def _doc(outcomes: dict[str, list], model="m", k=None):
    trials = [_trial(task_id, s, error="boom" if s is None else None)
              for task_id, results in outcomes.items() for s in results]
    return {"model": model, "strategy": "single_round", "status": "completed",
            "trials_per_task": k or max(len(v) for v in outcomes.values()),
            "task_ids": list(outcomes), "trials": trials}


def test_pass_hat_k():
    assert pass_hat_k(5, 5, 5) == 1
    assert pass_hat_k(4, 5, 5) == 0
    assert pass_hat_k(3, 5, 1) == pytest.approx(0.6)
    assert pass_hat_k(4, 5, 2) == pytest.approx(6 / 10)
    with pytest.raises(ValueError):
        pass_hat_k(1, 1, 2)


def test_sign_test():
    assert sign_test_p(6, 0) == pytest.approx(2 / 64)
    assert sign_test_p(5, 0) == pytest.approx(2 / 32)
    assert sign_test_p(3, 3) == 1.0
    assert sign_test_p(0, 0) == 1.0
    assert min_one_sided_tasks() == 6


def test_per_task_leaves_out_error_trials():
    doc = _doc({"a": [True, None, False], "b": [None]})
    assert per_task(doc) == {"a": (1, 2)}


def test_summary_rates_and_pass_k():
    doc = _doc({"a": [True] * 5, "b": [True, True, True, False, False], "c": [False] * 5})
    s = summary(doc)
    assert s["success"] == pytest.approx(8 / 15)
    assert s["pass1"] == pytest.approx((1 + 0.6 + 0) / 3)
    assert s["k"] == 5 and s["pass_k"] == pytest.approx(1 / 3)
    assert (s["always"], s["flaky"], s["never"]) == (1, 1, 1)
    assert s["cost_total"] == pytest.approx(0.015) and s["errors"] == 0


def test_paired_table_counts_wins_losses_and_ties():
    a = _doc({"t1": [True], "t2": [True], "t3": [False], "t4": [True]}, model="A")
    b = _doc({"t1": [False], "t2": [True], "t3": [True], "t4": [False]}, model="B")
    text = paired_table(a, b)
    assert "A better on 2 tasks, B better on 1, tied on 1" in text
    assert "a direction, not a finding" in text
    assert "p = 1.000" in text and "at least 6 differing tasks" in text


def test_paired_table_matches_k_when_the_arms_differ():
    # On t1, 4/5 against 1/1 used to count as a win for the single trial. Compared on the
    # first trial of each task, both passed t1 (a tie); only t2 differs.
    a = _doc({"t1": [True, False, True, True, True], "t2": [False] * 5}, model="A")
    b = _doc({"t1": [True], "t2": [True]}, model="B", k=1)
    text = paired_table(a, b)
    assert "A better on 0 tasks, B better on 1, tied on 1" in text
    assert "compared on its first 1 trial(s) only" in text
    same = paired_table(a, a)
    assert "first" not in same


def test_restrict_keeps_only_the_named_tasks():
    from arl.evals.report import full_report, restrict

    doc = _doc({"c07-cancel": [True], "c08-address": [False], "c13-shipped": [True]})
    kept = restrict(doc, ["c07", "c13-shipped"])
    assert kept["task_ids"] == ["c07-cancel", "c13-shipped"]
    assert {t["task_id"] for t in kept["trials"]} == {"c07-cancel", "c13-shipped"}
    assert summary(kept)["success"] == 1.0
    assert full_report([kept]).startswith("_Restricted to 2 tasks")


def test_summary_counts_runs_that_ended_without_a_reply():
    doc = _doc({"a": [True, False, False]})
    for trial, status in zip(doc["trials"], ["completed", "step_cap", "truncated"]):
        trial["transcript"] = {"status": status}
    assert summary(doc)["exits"] == {"step_cap": 1, "truncated": 1}


# --- The advisory judge column and the provenance split ----------------------------------

def _judged_doc():
    doc = _doc({"c01-a": [True, True], "c16-b": [True, False]})
    for n, t in enumerate(doc["trials"]):
        t["trial"] = n % 2 + 1
    # code facts: c01 pass pass; c16 pass (k1), fail (k2)
    doc["trials"][3]["verdict"]["groups"]["facts"] = False
    doc["judge"] = {"prompt_hash": "abc123", "validation": {"tpr": 0.8, "tnr": 0.9},
                    "trials": [
                        {"task_id": "c01-a", "trial": 1, "verdict": "pass", "critique": "ok",
                         "failure_codes": []},
                        {"task_id": "c01-a", "trial": 2, "verdict": None, "critique": "",
                         "failure_codes": [], "error": "refused"},
                        {"task_id": "c16-b", "trial": 1, "verdict": "fail",
                         "critique": "Says Yes | to a repeat", "failure_codes": ["R1"]},
                        {"task_id": "c16-b", "trial": 2, "verdict": "fail", "critique": "x",
                         "failure_codes": []}]}
    return doc


def test_judge_table_is_separate_from_success():
    from arl.evals.report import judge_table

    doc = _judged_doc()
    before = summary(doc)["success"]
    table = judge_table([doc])
    assert summary(doc)["success"] == before == 0.75
    # judged 4, 1 error; judge pass 1/3; corrected = 1 - ((2/3) + 0.9 - 1) / 0.7
    row = table.splitlines()[2]
    assert "| 4 | 1 | 33% | 19% |" in row
    # facts✓judge✓ 1, facts✓judge✗ 1, facts✗judge✓ 0, facts✗judge✗ 1
    assert "| 1 | 1 | 0 | 1 | abc123 |" in row


def test_disagreements_list_the_trials_to_read():
    from arl.evals.report import disagreements

    text = disagreements(_judged_doc())
    assert "c16-b | 1 | pass | fail | R1 | Says Yes / to a repeat" in text
    assert "c01-a" not in text


def test_full_report_has_a_judge_section_only_with_a_sidecar():
    from arl.evals.report import full_report

    assert "Reply judge (advisory" in full_report([_judged_doc()])
    assert "Reply judge" not in full_report([_doc({"c01-a": [True]})])


def test_provenance_table_splits_original_and_failure_derived():
    from arl.evals.report import full_report, provenance_table

    doc = _doc({"c01-status-shipped": [True, True], "c29-refund-one-of-two-units": [False, True]})
    doc["task_set"] = "capability"
    table = provenance_table([doc])
    assert "100% (1 tasks, 2 trials) | 50% (1 tasks, 2 trials)" in table
    assert "Original and failure-derived tasks" in full_report([doc])


def test_load_results_attaches_a_judge_sidecar(tmp_path):
    import json

    from arl.evals.report import load_results

    path = tmp_path / "sweep.json"
    path.write_text(json.dumps(_doc({"a": [True]})))
    assert "judge" not in load_results(path)
    (tmp_path / "sweep.judge.json").write_text(json.dumps({"prompt_hash": "p", "trials": []}))
    assert load_results(path)["judge"]["prompt_hash"] == "p"
