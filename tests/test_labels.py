"""Labelling: pool sampling, label storage, the interactive loop, and the grouped split."""

from collections import Counter

import pytest

from arl.evals import labels as lab


def _trial(task_id, reply, success=True, facts=True, k=1):
    return {"task_id": task_id, "trial": k, "success": success,
            "verdict": {"groups": {"facts": facts}},
            "transcript": {"ticket": f"ticket {task_id}", "reply": reply,
                           "tool_calls": [{"turn": 1, "name": "get_order",
                                           "arguments": '{"order_id":"ORD-1"}',
                                           "result": {"order": {"id": "ORD-1"}},
                                           "is_error": False}]}}


def _doc(trials, provider="openai", strategy="single_round", phase="phase-2", sweep="s1"):
    return {"provider": provider, "strategy": strategy, "phase": phase, "sweep_id": sweep,
            "model": "m", "trials": trials}


def test_candidates_dedupe_skip_anthropic_and_classify():
    docs = [
        _doc([_trial("c01", "Shipped."), _trial("c01", "shipped.", k=2),     # same after normalise
              _trial("c02", "No.", success=False, facts=False),
              _trial("c03", "Done?", success=False)]),
        _doc([_trial("c04", "Haiku reply")], provider="anthropic"),
        _doc([_trial("c05", "Later phase")], phase="phase-4"),
        _doc([_trial("c06", "Loop pass")], strategy="hand_loop", phase="phase-3"),
    ]
    items = lab.candidates(docs)
    assert [(i.task_id, i.stratum) for i in items] == [
        ("c01", "pass_r1"), ("c02", "facts_fail"), ("c03", "action_fail"), ("c06", "pass_r2")]


def _pool(n_per_stratum=10, tasks=8):
    items = []
    for stratum in lab.TARGETS:
        for n in range(n_per_stratum):
            items.append(lab.Item("", f"c{n % tasks:02d}", "t", [], f"{stratum} reply {n}",
                                  stratum=stratum))
    return items


def test_sample_hits_targets_and_caps_per_task():
    targets = {"facts_fail": 3, "action_fail": 3, "pass_r1": 2, "pass_r2": 2}
    chosen = lab.sample(_pool(), targets, max_per_task=2)
    assert Counter(i.stratum for i in chosen) == targets
    assert max(Counter(i.task_id for i in chosen).values()) <= 2
    assert lab.sample(_pool(), targets, max_per_task=2) == chosen       # fixed seed


def test_sample_top_up_excludes_existing():
    first = lab.sample(_pool(), {"facts_fail": 3}, max_per_task=4)
    more = lab.sample(_pool(), {"facts_fail": 3}, seed=1, max_per_task=4, exclude=first)
    assert not {i.reply for i in first} & {i.reply for i in more}


def test_render_hides_model_strategy_and_verdict():
    item = lab.Item("L01", "c01", "Where is it?", [{"turn": 1, "name": "get_order",
                    "arguments": "{}", "result": {"x": 1}, "is_error": True}], "On its way.",
                    model="gpt-6-luna", strategy="hand_loop", stratum="facts_fail",
                    code_success=False)
    text = lab.render(item)
    assert "Where is it?" in text and "On its way." in text and "[error]" in text
    for hidden in ("gpt-6-luna", "hand_loop", "facts_fail", "False"):
        assert hidden not in text


def _items(n):
    return lab.number([lab.Item("", f"c{i:02d}", "t", [], f"reply {i}") for i in range(n)])


def _asker(answers):
    answers = iter(answers)
    return lambda prompt, default=None: next(answers)


def test_label_loop_records_resumes_and_requires_fail_critique(tmp_path):
    path = tmp_path / "labels.jsonl"
    items = _items(3)
    # pass with no critique, then fail with an empty critique first, then quit
    lab.label_loop(items, path, ask=_asker(["p", "", "f", "", "says yes wrongly", "q"]),
                   echo=lambda _: None)
    labels = lab.read_labels(path)
    assert labels["L01"].label == "pass" and labels["L01"].critique == ""
    assert labels["L02"].label == "fail" and labels["L02"].critique == "says yes wrongly"
    assert "L03" not in labels
    # resume: starts at L03; go back, relabel L02 as pass, then skip L03
    lab.label_loop(items, path, ask=_asker(["b", "p", "fine", "s"]), echo=lambda _: None)
    labels = lab.read_labels(path)
    assert labels["L02"].label == "pass" and labels["L02"].critique == "fine"
    assert labels["L03"].label == "skip"


def test_label_loop_back_relabels(tmp_path):
    path = tmp_path / "labels.jsonl"
    items = _items(2)
    lab.label_loop(items, path, ask=_asker(["f", "bad", "b", "p", "ok now", "p", ""]),
                   echo=lambda _: None)
    labels = lab.read_labels(path)
    assert labels["L01"].label == "pass" and labels["L01"].critique == "ok now"
    assert labels["L02"].label == "pass"


def _labelled(n_tasks=20, per_task=3, fail_every=2):
    items, labels = [], {}
    n = 0
    for t in range(n_tasks):
        for _ in range(per_task):
            n += 1
            item = lab.Item(f"L{n:02d}", f"c{t:02d}", "t", [], f"r{n}")
            items.append(item)
            labels[item.item_id] = lab.Label(item.item_id, "fail" if n % fail_every else "pass")
    return items, labels


def test_split_is_grouped_sized_balanced_and_deterministic():
    items, labels = _labelled()
    split = lab.make_split(items, labels)
    assert abs(len(split["examples"]) - 10) <= lab.SIZE_TOLERANCE
    assert abs(len(split["test"]) - 30) <= lab.SIZE_TOLERANCE
    assert len(split["examples"]) + len(split["tuning"]) + len(split["test"]) == 60
    assert all(not set(split["tasks"][a]) & set(split["tasks"][b])
               for a, b in [("examples", "test"), ("tuning", "test"), ("examples", "tuning")])
    for s in ("examples", "tuning", "test"):
        share = sum(labels[i].label == "fail" for i in split[s]) / len(split[s])
        assert lab.FAIL_SHARE[0] <= share <= lab.FAIL_SHARE[1]
    assert lab.make_split(items, labels) == split


def test_split_skips_skipped_and_fails_when_impossible():
    items, labels = _labelled()
    labels["L01"] = lab.Label("L01", "skip")
    split = lab.make_split(items, labels)
    assert "L01" not in split["examples"] + split["tuning"] + split["test"]
    all_pass = {k: lab.Label(k, "pass") for k in labels}
    with pytest.raises(ValueError):
        lab.make_split(items, all_pass, tries=50)
