"""The runner, driven by a scripted model. No API calls.

The scripted model answers request 1 with one get_order call and request 2 with a fixed
reply. Each call reports 1,000 input and 100 output tokens, so on gpt-6-luna prices a
call costs $0.00015 and a trial $0.0003.
"""

import json

import pytest
from typer.testing import CliRunner

from arl.evals import runner
from arl.evals.report import full_report, load_results, show_trial
from arl.evals.runner import Estimate, estimate, run_sweep
from arl.evals.tasks import load_tasks, select
from arl.llm.openai_adapter import OpenAIAdapter

USAGE = {"input_tokens": 1000, "input_tokens_details": {"cached_tokens": 0},
         "output_tokens": 100, "output_tokens_details": {"reasoning_tokens": 0}}
TRIAL_COST = 2 * (1000 * 0.10 + 100 * 0.50) / 1e6
TASKS = select(load_tasks(), "c01")


class ScriptedModel:
    """Calls get_order on ORD-1001, then replies. Can be told to fail on a given call."""

    def __init__(self, fail_on_call: int | None = None):
        self.calls = 0
        self.fail_on_call = fail_on_call

    def __call__(self, request):
        self.calls += 1
        if self.fail_on_call and self.calls % 2 == 0:
            raise RuntimeError("server error")
        if request["tool_choice"] == "auto":
            output = [{"type": "function_call", "id": "fc_1", "call_id": f"call_{self.calls}",
                       "name": "get_order", "arguments": '{"order_id": "ORD-1001"}',
                       "status": "completed"}]
        else:
            output = [{"type": "message", "id": "msg_1", "role": "assistant",
                       "status": "completed",
                       "content": [{"type": "output_text", "text": "It has shipped.",
                                    "annotations": []}]}]
        return {"status": "completed", "output": output, "usage": USAGE}, "req_test"


def _estimate(worst: float, trials: int) -> Estimate:
    return Estimate("gpt-6-luna", trials, 1000, TRIAL_COST, worst, "test")


def _sweep(tmp_path, *, trials: int, cap: float, worst: float, model=None, tasks=TASKS):
    model = model or ScriptedModel()
    doc = run_sweep(tasks, adapter=OpenAIAdapter("gpt-6-luna", send=model),
                    trials_per_task=trials, cap_usd=cap, est=_estimate(worst, trials),
                    results_dir=tmp_path / "results", runs_dir=tmp_path / "runs",
                    sweep_id="test-sweep")
    return doc, model


def test_sweep_runs_every_trial_and_grades_it(tmp_path):
    doc, model = _sweep(tmp_path, trials=3, cap=1.0, worst=0.001)
    assert doc["status"] == "completed" and doc["trials_run"] == 3 and model.calls == 6
    assert [t["success"] for t in doc["trials"]] == [True, True, True]
    assert doc["spent_usd"] == pytest.approx(3 * TRIAL_COST)
    first = doc["trials"][0]
    assert first["model_calls"] == 2 and first["tool_calls"] == 1
    assert first["transcript"]["db_diff"] == {}
    # each trial has its own trace, ending with the recorded end state
    events = [json.loads(line) for line in
              (tmp_path / "runs" / "test-sweep" / "test-sweep-c01-status-shipped-k1.jsonl")
              .read_text().splitlines()]
    assert events[-1]["type"] == "end_state"


def test_cost_cap_halts_the_sweep_before_it_can_be_crossed(tmp_path):
    # Worst case 0.001 per trial, cap 0.0025: a trial starts only while spent <= 0.0015.
    # Each trial actually costs 0.0003, so trials 1-6 run (spent 0.0018) and 7 does not.
    doc, model = _sweep(tmp_path, trials=10, cap=0.0025, worst=0.001)
    assert doc["status"] == "halted_cap"
    assert doc["trials_run"] == 6 and model.calls == 12
    assert doc["spent_usd"] == pytest.approx(6 * TRIAL_COST)
    assert doc["spent_usd"] + 0.001 > 0.0025 >= doc["spent_usd"]
    [row] = runner.read_ledger(tmp_path / "results")
    assert (row["status"], row["trials_run"], row["trials_planned"]) == ("halted_cap", "6", "10")
    assert float(row["spent_usd"]) == pytest.approx(6 * TRIAL_COST)


def test_cap_below_one_worst_case_runs_nothing(tmp_path):
    doc, model = _sweep(tmp_path, trials=2, cap=0.0005, worst=0.001)
    assert doc["status"] == "halted_cap" and doc["trials_run"] == 0 and model.calls == 0


def test_a_crashed_trial_is_an_error_and_its_spend_still_counts(tmp_path):
    doc, _ = _sweep(tmp_path, trials=5, cap=1.0, worst=0.001,
                    model=ScriptedModel(fail_on_call=2))
    # every second call fails, so every trial errors after one paid call
    assert doc["status"] == "halted_errors" and doc["trials_run"] == runner.MAX_CONSECUTIVE_ERRORS
    trial = doc["trials"][0]
    assert trial["success"] is None and trial["error"].startswith("RuntimeError")
    assert trial["cost_usd"] == pytest.approx(TRIAL_COST / 2)
    assert doc["spent_usd"] == pytest.approx(3 * TRIAL_COST / 2)


def test_results_file_and_ledger_are_written(tmp_path):
    _sweep(tmp_path, trials=1, cap=1.0, worst=0.001)
    saved = json.loads((tmp_path / "results" / "test-sweep.json").read_text())
    assert saved["model"] == "gpt-6-luna" and saved["task_ids"] == ["c01-status-shipped"]
    assert saved["task_set_hash"] and saved["git_commit"]
    [row] = runner.read_ledger(tmp_path / "results")
    assert set(row) == set(runner.LEDGER_FIELDS)
    assert row["results_file"] == "test-sweep.json" and row["phase"] == runner.PHASE


def test_report_and_regrade_from_the_results_file(tmp_path):
    _sweep(tmp_path, trials=2, cap=1.0, worst=0.001)
    path = tmp_path / "results" / "test-sweep.json"
    stored, regraded = load_results(path), load_results(path, regrade=True)
    assert [t["verdict"] for t in stored["trials"]] == [t["verdict"] for t in regraded["trials"]]
    note, _, rest = full_report([regraded]).partition("\n\n")
    assert note.startswith("_Re-graded") and rest == full_report([stored])
    text = show_trial(stored, "c01", 2)
    assert "get_order" in text and "It has shipped." in text and "SUCCESS" in text


def test_estimate_prior_and_measured(tmp_path):
    prior = estimate(TASKS, "gpt-6-luna", 5, results_dir=tmp_path)
    assert prior.trials == 5 and prior.basis.startswith("prior")
    assert prior.per_trial_worst > prior.per_trial_expected > 0
    _sweep(tmp_path, trials=2, cap=1.0, worst=0.001)
    measured = estimate(TASKS, "gpt-6-luna", 5, results_dir=tmp_path / "results")
    assert measured.basis.startswith("measured")
    assert measured.per_trial_expected == pytest.approx(TRIAL_COST)
    assert measured.per_trial_worst == prior.per_trial_worst   # the cap never uses history


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_chars_per_token_matches_the_recorded_requests(provider):
    from pathlib import Path

    fixture = json.loads((Path(__file__).parent / "fixtures" / "recorded" /
                          f"{provider}_t1.json").read_text())
    usage = fixture["responses"][0]["usage"]
    tokens = (usage["input_tokens"] + (usage.get("cache_read_input_tokens") or 0)
              + (usage.get("cache_creation_input_tokens") or 0)
              if provider == "anthropic" else usage["input_tokens"])
    ratio = len(json.dumps(fixture["requests"][0])) / tokens
    assert ratio == pytest.approx(runner.CHARS_PER_TOKEN[provider], rel=0.05)


def test_dry_run_prints_the_estimate_and_calls_no_model(monkeypatch):
    from arl import cli

    def no_adapter(model):
        raise AssertionError("a dry run must not build an adapter")

    monkeypatch.setattr("arl.llm.make_adapter", no_adapter)
    result = CliRunner().invoke(cli.app, ["eval", "--dry-run", "--tasks", "c01", "-k", "2"])
    assert result.exit_code == 0, result.output
    assert "1 tasks × 2 trials" in result.output and "worst:" in result.output


# --- Strategies (Stage 3) --------------------------------------------------------------

class LoopingModel:
    """Looks up the order, cancels it, then replies: three calls, the shape of a loop run."""

    def __init__(self):
        from scripted import ScriptedModel, calls, reply

        self.calls = 0
        self._script = ScriptedModel(
            "openai",
            calls(("get_order", {"order_id": "ORD-1003"})),
            calls(("cancel_order", {"order_id": "ORD-1003", "reason": "Wrong lamp"})),
            reply("Your order ORD-1003 is cancelled."),
        )

    def __call__(self, request):
        self.calls += 1
        return self._script(request)


def test_sweep_runs_the_loop_strategy_and_records_it(tmp_path):
    model = LoopingModel()
    doc = run_sweep(select(load_tasks(), "c07"), adapter=OpenAIAdapter("gpt-6-luna", send=model),
                    trials_per_task=1, cap_usd=1.0, est=_estimate(0.05, 1),
                    results_dir=tmp_path / "results", runs_dir=tmp_path / "runs",
                    sweep_id="loop-sweep", strategy="hand_loop")
    assert doc["strategy"] == "hand_loop" and doc["max_model_calls"] == runner.MAX_STEPS
    [trial] = doc["trials"]
    assert trial["success"] is True, trial["verdict"]
    assert (trial["model_calls"], trial["tool_calls"]) == (3, 2)
    assert trial["transcript"]["strategy"] == "hand_loop"
    [row] = runner.read_ledger(tmp_path / "results")
    assert row["strategy"] == "hand_loop"
    with pytest.raises(ValueError):
        run_sweep(TASKS, adapter=OpenAIAdapter("gpt-6-luna", send=model), trials_per_task=1,
                  cap_usd=1.0, est=_estimate(0.05, 1), results_dir=tmp_path / "results",
                  runs_dir=tmp_path / "runs", strategy="no_such_strategy")


def test_the_loop_worst_case_uses_the_step_cap(tmp_path):
    one = estimate(TASKS, "gpt-6-luna", 1, results_dir=tmp_path)
    loop = estimate(TASKS, "gpt-6-luna", 1, results_dir=tmp_path, strategy="hand_loop")
    assert loop.strategy == "hand_loop" and "4 calls" in loop.basis
    assert loop.per_trial_worst > 5 * one.per_trial_worst
    assert loop.per_trial_worst == pytest.approx(runner.worst_trial_cost(
        loop.input_tokens_per_call, 0.125, 0.50, runner.MAX_STEPS), rel=0.01)
    assert loop.per_trial_expected == pytest.approx(2 * one.per_trial_expected)


def test_measured_costs_are_kept_apart_by_strategy(tmp_path):
    _sweep(tmp_path, trials=2, cap=1.0, worst=0.001)   # a single_round sweep
    results = tmp_path / "results"
    assert estimate(TASKS, "gpt-6-luna", 1, results).basis.startswith("measured")
    assert estimate(TASKS, "gpt-6-luna", 1, results, strategy="hand_loop").basis.startswith("prior")


def test_dry_run_of_the_loop_shows_its_worst_case(monkeypatch):
    from arl import cli

    def no_adapter(model):
        raise AssertionError("a dry run must not build an adapter")

    monkeypatch.setattr("arl.llm.make_adapter", no_adapter)
    result = CliRunner().invoke(cli.app, ["eval", "--dry-run", "--tasks", "c01", "-k", "1",
                                          "--strategy", "hand_loop"])
    assert result.exit_code == 0, result.output
    assert "hand_loop" in result.output and f"{runner.MAX_STEPS} calls" in result.output
    bad = CliRunner().invoke(cli.app, ["eval", "--dry-run", "--strategy", "nope"])
    assert bad.exit_code != 0


# --- Stage 6: the framework strategies through the same harness ----------------------------

def _framework_sweep(tmp_path, monkeypatch, strategy, *steps, task="c07"):
    from scripted import ScriptedModel
    from wire import wire_setup

    for module in ("graph_agent", "workflow"):
        monkeypatch.setattr(f"arl.framework.{module}.make_chat_model",
                            lambda model: wire_setup(ScriptedModel("openai", *steps), "openai"))
    return run_sweep(select(load_tasks(), task), adapter=OpenAIAdapter("gpt-6-luna", send=None),
                     trials_per_task=2, cap_usd=1.0, est=_estimate(0.05, 2),
                     results_dir=tmp_path / "results", runs_dir=tmp_path / "runs",
                     sweep_id=f"{strategy}-sweep", strategy=strategy)


@pytest.mark.parametrize("strategy", ["graph_off", "graph_all"])
def test_sweep_runs_the_graph_agent(strategy, tmp_path, monkeypatch):
    from scripted import calls, reply

    doc = _framework_sweep(
        tmp_path, monkeypatch, strategy,
        calls(("get_order", {"order_id": "ORD-1003"})),
        calls(("cancel_order", {"order_id": "ORD-1003", "reason": "Wrong lamp"})),
        reply("Your order ORD-1003 is cancelled."))
    assert doc["strategy"] == strategy and doc["phase"] == "phase-6"
    assert all(t["success"] for t in doc["trials"]), [t["verdict"] for t in doc["trials"]]
    assert {(t["model_calls"], t["tool_calls"]) for t in doc["trials"]} == {(3, 2)}
    assert {t["transcript"]["strategy"] for t in doc["trials"]} == {strategy}
    assert doc["spent_usd"] == pytest.approx(2 * 3 * (1000 * 0.10 + 100 * 0.50) / 1e6)


def test_sweep_runs_the_workflow(tmp_path, monkeypatch):
    from scripted import calls, reply

    route = json.dumps({"intent": "cancel", "order_ids": ["ORD-1003"], "email": None,
                        "summary": "Cancel ORD-1003."})
    doc = _framework_sweep(
        tmp_path, monkeypatch, "workflow", reply(route),
        calls(("cancel_order", {"order_id": "ORD-1003", "reason": "Wrong lamp"})),
        reply("Your order ORD-1003 is cancelled."))
    assert doc["max_model_calls"] == 5
    assert all(t["success"] for t in doc["trials"]), [t["verdict"] for t in doc["trials"]]
    assert {t["transcript"]["strategy"] for t in doc["trials"]} == {"workflow"}


def test_framework_strategies_borrow_a_measured_cost_and_are_bounded(tmp_path):
    _sweep(tmp_path, trials=1, cap=1.0, worst=0.001)            # nothing to borrow for these
    graph = estimate(TASKS, "gpt-6-luna", 1, tmp_path / "results", strategy="graph_all")
    assert graph.basis.startswith("prior") and runner.STRATEGIES["graph_all"].max_calls == 11
    workflow = estimate(TASKS, "gpt-6-luna", 1, tmp_path / "results", strategy="workflow")
    assert workflow.per_trial_worst <= 0.01 + 0.01   # the dollar budget bounds it
    assert runner.STRATEGIES["graph_off"].cost_basis == "hand_loop"
    assert runner.STRATEGIES["graph_all"].invariants and runner.STRATEGIES["workflow"].invariants


def test_the_cli_knows_the_framework_strategies(monkeypatch):
    from arl import cli

    monkeypatch.setattr("arl.llm.make_adapter", lambda model: (_ for _ in ()).throw(
        AssertionError("a dry run must not build an adapter")))
    for strategy in ("graph_all", "workflow"):
        result = CliRunner().invoke(cli.app, ["eval", "--dry-run", "--tasks", "c01", "-k", "1",
                                              "--strategy", strategy])
        assert result.exit_code == 0, result.output
        assert strategy in result.output
