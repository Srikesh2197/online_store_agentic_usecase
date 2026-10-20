"""Trajectory checks: did the run take a forbidden or unverified path?

    must_call      a successful call of this tool happened (a failed lookup is not a lookup)
    must_not_call  no attempt at this tool, errors included: trying is the violation
    order          a successful `first` call came in an earlier model turn than `then`

The end state is the headline. A step rule earns its place only when a correct end state
can hide a fault, such as a refund issued without seeing the delivery date.
"""

from arl.evals.graders.types import Check
from arl.evals.tasks import CallSpec, Task, expand_tools
from arl.evals.transcript import ToolCallRecord, Transcript


def _same(expected, actual) -> bool:
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip().casefold() == actual.strip().casefold()
    return expected == actual


def _args_match(expected: dict, call: ToolCallRecord) -> bool:
    args = call.args
    return args is not None and all(_same(v, args.get(k)) for k, v in expected.items())


def check_must_call(task: Task, transcript: Transcript) -> list[Check]:
    checks = []
    for spec in task.trajectory.must_call:
        spec = CallSpec(tool=spec) if isinstance(spec, str) else spec
        label = spec.tool + (f"({', '.join(f'{k}={v}' for k, v in spec.args.items())})"
                             if spec.args else "")
        ok = [c for c in transcript.tool_calls
              if c.name == spec.tool and not c.is_error and _args_match(spec.args, c)]
        tried = [c for c in transcript.tool_calls if c.name == spec.tool]
        detail = (f"called in turn {ok[0].turn}" if ok
                  else f"called {len(tried)} time(s), none successful with these arguments"
                  if tried else "never called")
        checks.append(Check("trajectory", f"must_call {label}", bool(ok), detail))
    return checks


def check_must_not_call(task: Task, transcript: Transcript) -> list[Check]:
    if not task.trajectory.must_not_call:
        return []
    forbidden = expand_tools(task.trajectory.must_not_call)
    hits = [c for c in transcript.tool_calls if c.name in forbidden]
    detail = (", ".join(f"{c.name} in turn {c.turn}" + (" (error)" if c.is_error else "")
                        for c in hits) if hits else "none of " + ", ".join(sorted(forbidden)))
    return [Check("trajectory", "must_not_call", not hits, detail)]


def check_order(task: Task, transcript: Transcript) -> list[Check]:
    checks = []
    for rule in task.trajectory.order:
        label = f"order {'/'.join(rule.first)} before {rule.then}"
        then_calls = [c for c in transcript.tool_calls if c.name == rule.then]
        if not then_calls:
            checks.append(Check("trajectory", label, True, f"{rule.then} was not called"))
            continue
        then_turn = min(c.turn for c in then_calls)
        before = [c for c in transcript.tool_calls
                  if c.name in rule.first and not c.is_error and c.turn < then_turn]
        same_turn = [c for c in transcript.tool_calls
                     if c.name in rule.first and c.turn == then_turn]
        if before:
            detail = f"{before[0].name} in turn {before[0].turn}, {rule.then} in turn {then_turn}"
        elif same_turn:
            detail = (f"{same_turn[0].name} came in the same batch as {rule.then} "
                      f"(turn {then_turn}), so its result was not seen first")
        else:
            detail = f"{rule.then} in turn {then_turn} with no successful {'/'.join(rule.first)} before it"
        checks.append(Check("trajectory", label, bool(before), detail))
    return checks


def grade_trajectory(task: Task, transcript: Transcript) -> list[Check]:
    return (check_must_call(task, transcript) + check_must_not_call(task, transcript)
            + check_order(task, transcript))
