"""The store server over stdio: python -m arl.framework.mcp_server --store FILE --env FILE

`--env` is a JSON file with the trial's environment: {"invariants": bool,
"sender_customer_id": str | null}. Faults are not served over stdio (the injector's counts
live in the client process); the client refuses a task that has them."""

import argparse
import json
from pathlib import Path

import anyio
from mcp.server.stdio import stdio_server

from arl.env.store import EnvConfig
from arl.framework.mcp_server.server import build_server, open_store


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m arl.framework.mcp_server")
    parser.add_argument("--store", required=True)
    parser.add_argument("--env", required=True)
    args = parser.parse_args()
    env = EnvConfig(**json.loads(Path(args.env).read_text()))
    server = build_server(lambda: open_store(args.store, env))

    async def serve():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    try:
        anyio.run(serve)
    finally:
        server.close_store()


if __name__ == "__main__":
    main()
