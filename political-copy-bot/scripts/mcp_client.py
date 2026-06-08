#!/usr/bin/env python3
"""
Lightweight MCP client that talks to mcp-capitol-trades via stdio JSON-RPC.
Auto-retries on Capitol Trades 429 rate-limit responses with exponential backoff.
"""

import json
import subprocess
import time


def call_mcp_tool(tool_name: str, arguments: dict, timeout: int = 120) -> dict:
    """
    Call an mcp-capitol-trades tool via stdio JSON-RPC.

    Retry policy: up to 3 attempts on HTTP 429 from Capitol Trades
    (the MCP server surfaces these as isError text containing "429").
    Backoff: 4 s, 8 s between retries.  Other errors raise immediately.
    """
    MAX_ATTEMPTS = 3

    for attempt in range(MAX_ATTEMPTS):
        if attempt:
            backoff = 4 * attempt   # 4 s first retry, 8 s second
            time.sleep(backoff)

        initialize_msg = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "politician-bot", "version": "1.0.0"},
            },
        })
        initialized_msg = json.dumps({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })
        tool_call_msg = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        })

        stdin_data = f"{initialize_msg}\n{initialized_msg}\n{tool_call_msg}\n"

        proc = subprocess.run(
            ["mcp-capitol-trades"],
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        rate_limited = False
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
                            text = item["text"]
                            # Capitol Trades returns 429 as an isError text payload
                            if "429" in text:
                                rate_limited = True
                                break
                            return json.loads(text)
                    else:
                        # All items processed, none triggered 429 or a return
                        return msg.get("result", {})
                    break  # 429 hit — exit line loop, outer loop will retry
            except json.JSONDecodeError:
                continue

        if rate_limited:
            continue  # back to top of attempt loop

        raise RuntimeError(
            f"No valid response from MCP server.\n"
            f"stdout: {proc.stdout[:500]}\nstderr: {proc.stderr[:500]}"
        )

    raise RuntimeError(
        f"Capitol Trades rate-limited after {MAX_ATTEMPTS} attempts (tool={tool_name}). "
        "Try again later or reduce scan frequency."
    )


if __name__ == "__main__":
    print("Testing MCP client...")
    result = call_mcp_tool("get_top_traded_assets", {"limit": 10, "days": 90})
    print(json.dumps(result, indent=2))
