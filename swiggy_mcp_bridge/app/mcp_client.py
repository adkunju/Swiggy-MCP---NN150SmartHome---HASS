"""
Minimal MCP "Streamable HTTP" client.

Swiggy's servers (mcp.swiggy.com/food, /im, /dineout, /scenes) speak standard
MCP over Streamable HTTP: a single POST endpoint per server, JSON-RPC 2.0
bodies, and a response that is either a plain `application/json` object or a
one-shot `text/event-stream` carrying the same JSON-RPC response as an SSE
`data:` event. A session is established with an `initialize` call; the server
hands back an `Mcp-Session-Id` header that must be echoed on every later
request to that server.

This client does NOT hardcode Swiggy-specific tool names -- discover them at
runtime with `list_tools()` (see /api/<server>/tools in server.py) and fill
in the mapping in tool_map.py once you have real production access, since the
tool schemas aren't published outside the Builders Club program.
"""
from __future__ import annotations

import itertools
import json
import logging
import re
from typing import Any, Optional

import aiohttp

log = logging.getLogger("swiggy_bridge.mcp")

SERVER_URLS = {
    "food": "https://mcp.swiggy.com/food",
    "instamart": "https://mcp.swiggy.com/im",
    "dineout": "https://mcp.swiggy.com/dineout",
    "scenes": "https://mcp.swiggy.com/scenes",
}

PROTOCOL_VERSION = "2025-06-18"  # MCP spec version this client targets


class McpAuthExpired(Exception):
    """401 from the MCP server -- caller should refresh the token and retry once."""


class McpAccessDenied(Exception):
    """403 from the MCP server -- not retryable. Usually means this server
    (food/instamart/dineout) hasn't been granted to this OAuth client yet,
    even though the user is authenticated. See Swiggy Builders access review."""

    def __init__(self, server: str, body: str):
        super().__init__(f"{server}: {_describe_403(body)}")
        self.server = server


def _describe_403(body: str) -> str:
    """Swiggy answers refused MCP calls with its website's HTML error page,
    not a JSON-RPC error -- don't dump that HTML into the UI."""
    stripped = body.lstrip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            err = data.get("error", data)
            msg = err.get("message") if isinstance(err, dict) else str(err)
            return f"Swiggy refused access (HTTP 403): {msg}"
        except (json.JSONDecodeError, AttributeError):
            pass
    if stripped.lower().startswith("<"):
        match = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
        title = f' (page title: "{match.group(1).strip()[:80]}")' if match and match.group(1).strip() else ""
        return (
            f"Swiggy refused access (HTTP 403, HTML error page{title}). This usually means "
            "this integration hasn't been granted production access to this server yet."
        )
    return f"Swiggy refused access (HTTP 403): {body[:200]}"


class McpError(Exception):
    def __init__(self, server: str, status: int, body: str):
        super().__init__(f"{server}: HTTP {status}: {body[:300]}")
        self.server = server
        self.status = status


class McpServerSession:
    """One persistent session against one Swiggy MCP server."""

    def __init__(self, name: str, http: aiohttp.ClientSession, token_getter):
        if name not in SERVER_URLS:
            raise ValueError(f"unknown MCP server {name!r}")
        self.name = name
        self.url = SERVER_URLS[name]
        self._http = http
        self._token_getter = token_getter
        self._session_id: Optional[str] = None
        self._id_counter = itertools.count(1)
        self._initialized = False

    async def _headers(self) -> dict:
        token = await self._token_getter()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    async def _post(self, body: dict) -> dict:
        headers = await self._headers()
        async with self._http.post(self.url, json=body, headers=headers) as resp:
            session_id = resp.headers.get("Mcp-Session-Id")
            if session_id:
                self._session_id = session_id

            raw = await resp.read()

            if resp.status == 401:
                raise McpAuthExpired(self.name)
            if resp.status == 403:
                raise McpAccessDenied(self.name, raw.decode(errors="replace"))
            if resp.status >= 400:
                raise McpError(self.name, resp.status, raw.decode(errors="replace"))

            content_type = resp.content_type
            if content_type == "text/event-stream":
                return self._parse_sse(raw.decode(errors="replace"), body.get("id"))
            return json.loads(raw)

    @staticmethod
    def _parse_sse(text: str, want_id) -> dict:
        """Pull the JSON-RPC response matching `want_id` out of an SSE stream,
        ignoring any progress notifications along the way."""
        last_parsed = None
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            chunk = line[len("data:"):].strip()
            if not chunk:
                continue
            try:
                parsed = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            last_parsed = parsed
            if parsed.get("id") == want_id:
                return parsed
        if last_parsed is not None:
            return last_parsed
        raise McpError("sse", 0, "no JSON-RPC response found in event stream")

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        req_id = next(self._id_counter)
        await self._post(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "swiggy-mcp-bridge", "version": "0.1.0"},
                },
            }
        )
        # Per spec, the client must send this notification (no response expected)
        # before issuing any other request.
        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._initialized = True

    async def _call(self, method: str, params: Optional[dict] = None) -> Any:
        await self._ensure_initialized()
        req_id = next(self._id_counter)
        resp = await self._post(
            {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        )
        if "error" in resp:
            err = resp["error"]
            raise McpError(self.name, 0, f"{err.get('code')}: {err.get('message')}")
        return resp.get("result")

    async def list_tools(self) -> list[dict]:
        result = await self._call("tools/list")
        return result.get("tools", [])

    async def call_tool(self, tool_name: str, arguments: Optional[dict] = None) -> Any:
        result = await self._call("tools/call", {"name": tool_name, "arguments": arguments or {}})
        if result and result.get("isError"):
            content = result.get("content", [])
            text = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
            raise McpError(self.name, 0, text or "tool reported an error")
        return result


class McpClientPool:
    """Keeps one McpServerSession per server name, reused across requests."""

    def __init__(self, http: aiohttp.ClientSession, token_getter):
        self._http = http
        self._token_getter = token_getter
        self._sessions: dict[str, McpServerSession] = {}

    def get(self, server: str) -> McpServerSession:
        if server not in self._sessions:
            self._sessions[server] = McpServerSession(server, self._http, self._token_getter)
        return self._sessions[server]

    def reset(self, server: str) -> None:
        """Drop a session (e.g. after a 401 that a token refresh should fix)."""
        self._sessions.pop(server, None)
