from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import aiohttp
from aiohttp import web

import demo
import oauth
import tool_map
from mcp_client import McpAccessDenied, McpAuthExpired, McpClientPool, McpError

LOG_LEVEL = os.environ.get("LOG_LEVEL", "info").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("swiggy_bridge")

ENABLED_SERVERS = [s for s in os.environ.get("ENABLED_SERVERS", "instamart").split(",") if s]
DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() == "true"
PORT = int(os.environ.get("PORT", "8099"))
STATIC_DIR = Path(__file__).parent / "static"

routes = web.RouteTableDef()


def _ok(data=None):
    return web.json_response({"ok": True, "data": data})


def _err(message, status=400):
    return web.json_response({"ok": False, "error": str(message)}, status=status)


def _unwrap(result):
    """MCP tools/call returns {"content": [...], "structuredContent": {...}?}.
    Hand the integration the actual payload: structuredContent if present,
    else a single text block parsed as JSON if it is JSON, else the text."""
    if not isinstance(result, dict):
        return result
    if "structuredContent" in result:
        return result["structuredContent"]
    content = result.get("content")
    if isinstance(content, list):
        texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
        if len(texts) == 1:
            try:
                return json.loads(texts[0])
            except (json.JSONDecodeError, TypeError):
                return texts[0]
        if texts:
            return texts
    return result


@routes.get("/")
async def index(request: web.Request) -> web.Response:
    return web.FileResponse(STATIC_DIR / "index.html")


@routes.get("/api/status")
async def status(request: web.Request) -> web.Response:
    auth: oauth.SwiggyOAuth = request.app["auth"]
    data = {**auth.status(), "enabled_servers": ENABLED_SERVERS, "demo_mode": DEMO_MODE}
    if DEMO_MODE:
        data["demo_seconds"] = request.app["demo"].seconds_since_reset()
    return _ok(data)


@routes.post("/auth/start")
async def auth_start(request: web.Request) -> web.Response:
    auth: oauth.SwiggyOAuth = request.app["auth"]
    http: aiohttp.ClientSession = request.app["http"]
    try:
        url = await auth.start_login(http)
    except Exception as exc:  # noqa: BLE001 -- surfaced to the UI, not swallowed
        log.exception("start_login failed")
        return _err(exc)
    return _ok({"authorize_url": url})


@routes.post("/auth/submit")
async def auth_submit(request: web.Request) -> web.Response:
    auth: oauth.SwiggyOAuth = request.app["auth"]
    http: aiohttp.ClientSession = request.app["http"]
    body = await request.json()
    redirect_url = body.get("redirect_url", "")
    try:
        await auth.finish_login(http, redirect_url)
    except Exception as exc:  # noqa: BLE001
        log.exception("finish_login failed")
        return _err(exc)
    return _ok(auth.status())


@routes.post("/auth/logout")
async def auth_logout(request: web.Request) -> web.Response:
    auth: oauth.SwiggyOAuth = request.app["auth"]
    auth.logout_local()
    request.app["mcp_pool"] = _new_pool(request.app)
    return _ok()


@routes.post("/api/demo/reset")
async def demo_reset(request: web.Request) -> web.Response:
    if not DEMO_MODE:
        return _err("demo mode is off", status=404)
    request.app["demo"].reset()
    return _ok({"demo_seconds": 0})


@routes.get("/api/tool-map")
async def get_tool_map(request: web.Request) -> web.Response:
    return _ok(tool_map.load())


@routes.post("/api/tool-map")
async def set_tool_map(request: web.Request) -> web.Response:
    body = await request.json()
    tool_map.save(body)
    return _ok(tool_map.load())


@routes.get("/api/{server}/tools")
async def discover_tools(request: web.Request) -> web.Response:
    server = request.match_info["server"]
    if server not in ENABLED_SERVERS:
        return _err(f"{server!r} is not enabled in the add-on's options", status=404)
    if DEMO_MODE:
        return _ok(demo.TOOLS)
    pool: McpClientPool = request.app["mcp_pool"]
    try:
        tools = await pool.get(server).list_tools()
    except McpAccessDenied as exc:
        return _err(str(exc), status=403)
    except (McpError, McpAuthExpired) as exc:
        return _err(str(exc), status=502)
    return _ok(tools)


@routes.post("/api/{server}/call")
async def call_tool(request: web.Request) -> web.Response:
    """Body: {"op": "<logical op>", "arguments": {...}} (preferred -- resolved
    through the tool map), or {"tool": "<raw MCP tool name>", ...}."""
    server = request.match_info["server"]
    if server not in ENABLED_SERVERS:
        return _err(f"{server!r} is not enabled in the add-on's options", status=404)
    body = await request.json()
    op = body.get("op")
    arguments = body.get("arguments") or {}

    if DEMO_MODE:
        if not op:
            return _err("demo mode only supports {'op': ...} calls")
        try:
            return _ok(request.app["demo"].run(op, arguments))
        except KeyError as exc:
            return _err(str(exc))

    tool_name = tool_map.load().get(server, {}).get(op) if op else body.get("tool")
    if not tool_name:
        return _err(f"no tool mapped for op {op!r}" if op else "missing 'op' or 'tool'")

    pool: McpClientPool = request.app["mcp_pool"]
    try:
        result = await pool.get(server).call_tool(tool_name, arguments)
    except McpAuthExpired:
        pool.reset(server)
        return _err("auth expired mid-call, retry", status=401)
    except McpAccessDenied as exc:
        return _err(str(exc), status=403)
    except McpError as exc:
        return _err(str(exc), status=502)
    return _ok(_unwrap(result))


async def _poll_one(pool: McpClientPool, server: str, op: str, tool_name: str):
    """Each sub-fetch is isolated: one server/tool being unavailable (e.g. not
    yet whitelisted, 403) must never block the others from reporting data."""
    try:
        data = await pool.get(server).call_tool(tool_name, {})
        return {"ok": True, "data": _unwrap(data)}
    except McpAccessDenied as exc:
        return {"ok": False, "error": "access_denied", "detail": str(exc)}
    except McpAuthExpired:
        pool.reset(server)
        return {"ok": False, "error": "auth_expired"}
    except McpError as exc:
        return {"ok": False, "error": "mcp_error", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 -- never let one bad op kill the poll
        log.exception("unexpected error polling %s/%s", server, op)
        return {"ok": False, "error": "unexpected", "detail": str(exc)}


@routes.get("/api/poll")
async def poll(request: web.Request) -> web.Response:
    """The endpoint the integration's coordinator polls. Only read-only ops
    are ever called here (never clear_cart/add_to_cart). Failures are inline
    per op, not exceptions, so partial results still reach Home Assistant."""
    if DEMO_MODE:
        snapshot = {"instamart": request.app["demo"].snapshot(demo.READ_OPS)} if "instamart" in ENABLED_SERVERS else {}
        snapshot["_meta"] = {"demo": True}
        return _ok(snapshot)

    auth: oauth.SwiggyOAuth = request.app["auth"]
    if not auth.is_authenticated:
        return _err("not authenticated", status=401)

    pool: McpClientPool = request.app["mcp_pool"]
    mapping = tool_map.load()
    jobs = []
    job_keys = []
    for server in ENABLED_SERVERS:
        for op in tool_map.READ_OPS.get(server, []):
            tool_name = mapping.get(server, {}).get(op)
            if not tool_name:
                continue
            job_keys.append((server, op))
            jobs.append(_poll_one(pool, server, op, tool_name))

    results = await asyncio.gather(*jobs) if jobs else []
    snapshot: dict = {"_meta": {"demo": False}}
    for (server, op), result in zip(job_keys, results):
        snapshot.setdefault(server, {})[op] = result

    return _ok(snapshot)


def _new_pool(app: web.Application) -> McpClientPool:
    auth: oauth.SwiggyOAuth = app["auth"]
    http: aiohttp.ClientSession = app["http"]

    async def token_getter():
        return await auth.get_access_token(http)

    return McpClientPool(http, token_getter)


async def on_startup(app: web.Application) -> None:
    app["http"] = aiohttp.ClientSession(headers={"User-Agent": "swiggy-mcp-bridge/0.2.0 (Home Assistant add-on)"})
    app["auth"] = oauth.SwiggyOAuth()
    app["mcp_pool"] = _new_pool(app)
    app["demo"] = demo.DemoState()


async def on_cleanup(app: web.Application) -> None:
    await app["http"].close()


def main() -> None:
    app = web.Application()
    app.add_routes(routes)
    app.router.add_static("/static/", STATIC_DIR)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    log.info("Swiggy MCP Bridge listening on :%s (servers: %s, demo: %s)", PORT, ENABLED_SERVERS, DEMO_MODE)
    web.run_app(app, host="0.0.0.0", port=PORT, print=None)


if __name__ == "__main__":
    main()
