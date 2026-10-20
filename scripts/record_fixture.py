"""Turn a run log into a recorded fixture for tests/test_recorded.py.

    agentic/bin/python scripts/record_fixture.py runs/<run_id>.jsonl

Writes tests/fixtures/recorded/<provider>_<ticket>.json. Re-record whenever a change to the
request shape is intended; tests/test_recorded.py fails until you do.
"""

import json
import sys
from pathlib import Path

from arl import ROOT
from arl.tracing.tracer import read_events


def record(log: Path) -> Path:
    events = read_events(log)
    start = events[0]
    fixture = {
        "source_run": start["run_id"], "recorded_at": start["ts"], "model": start["model"],
        "provider": start["provider"], "ticket_id": start["ticket_id"], "ticket": start["ticket"],
        "requests": [e["request"] for e in events if e["type"] == "model_request"],
        "responses": [e["response"] for e in events if e["type"] == "model_response"],
        "tool_calls": [{k: e[k] for k in ("call_id", "name", "arguments", "result")}
                       for e in events if e["type"] == "tool_call"],
    }
    out = ROOT / "tests" / "fixtures" / "recorded" / f"{start['provider']}_{start['ticket_id']}.json"
    out.write_text(json.dumps(fixture, indent=1) + "\n")
    return out


if __name__ == "__main__":
    for path in sys.argv[1:]:
        print(record(Path(path)))
