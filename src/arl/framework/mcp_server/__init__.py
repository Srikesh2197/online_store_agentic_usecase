"""The store tools over MCP (Stage 9).

    server.py    an MCP server (the official SDK's low-level Server) serving the ten store
                 tools exactly as tool_specs() defines them, with execute_tool behind it
    __main__.py  the same server over stdio: python -m arl.framework.mcp_server
    bridge.py    the client side: a sync wrapper around mcp.Client, the definition pin, and
                 the store handed to the server as a file and copied back after the run
    pins.json    the pinned hash of every tool definition
"""
