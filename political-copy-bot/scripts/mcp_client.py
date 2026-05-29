#!/usr/bin/env python3
"""
Lightweight MCP client that talks to mcp-capitol-trades via stdio JSON-RPC.
"""

import json
import subprocess


def call_mcp_tool(tool_name: str, arguments: dict, timeout: int = 120) -> dict:
    initialize_msg = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "politician-bot", "version": "1.0.0"}
        }
    })

    initialized_msg = json.dumps({
        "jsonrpc": "2.0",
        "method": "notifications/initialized"
    })

    tool_call_msg = json.dumps({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments}
    })

    stdin_data = f"{initialize_msg}\n{initialized_msg}\n{tool_call_msg}\n"

    proc = subprocess.run(
        ["mcp-capitol-trades"],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    for line in proc.stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            if msg.get("id") == 2:
                if "error" in msg:
                    raise RuntimeError(f"MCP error: {msg['error']}")
                content = msg.get("result", {}).get("content", [])
                for item in content:
                    if item.get("type") == "text":
                        return json.loads(item["text"])
                return msg.get("result", {})
        except json.JSONDecodeError:
            continue

    raise RuntimeError(f"No valid response from MCP server.\nstdout: {proc.stdout[:500]}\nstderr: {proc.stderr[:500]}")


if __name__ == "__main__":
    print("Testing MCP client...")
    result = call_mcp_tool("get_top_traded_assets", {"limit": 10, "days": 90})
    print(json.dumps(result, indent=2))
