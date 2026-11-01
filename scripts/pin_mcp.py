"""Re-pin the store server's tool definitions after a deliberate change to a tool.

    python scripts/pin_mcp.py          print the current hashes and the difference
    python scripts/pin_mcp.py --write  write them to src/arl/framework/mcp_server/pins.json

tests/test_mcp.py fails while pins.json does not match tool_specs(), as the frozen task-set
hashes do, so a changed description is always a reviewed change."""

import json
import sys

from arl.framework.mcp_server.bridge import PINS_PATH, load_pins, pin_of, pin_problems
from arl.framework.mcp_server.server import SERVER_NAME, tool_definitions

tools = tool_definitions()
current = {SERVER_NAME: pin_of(tools)}
old = load_pins().get(SERVER_NAME) if PINS_PATH.exists() else None
print(json.dumps(current, indent=1))
print("difference from pins.json:", pin_problems(tools, old) or "none")
if "--write" in sys.argv:
    PINS_PATH.write_text(json.dumps(current, indent=1, sort_keys=True) + "\n")
    print(f"wrote {PINS_PATH}")
