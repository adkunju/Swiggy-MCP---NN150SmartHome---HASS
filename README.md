# Swiggy MCP Bridge (for Home Assistant)

A from-scratch, independently-built alternative to `pranjal-joshi/ha-swiggy-mcp`,
with the same two-piece shape (local OAuth add-on + HACS integration) but a
different internal design, chosen specifically to avoid a bug we hit in that
project: one unauthorized MCP server call (`/food`, 403) blocking the entire
sensor refresh, even for the services that *were* working.

This repo is a **working scaffold**, not a finished, Swiggy-certified product.
The two things that genuinely can't be faked from outside Swiggy's program are
called out explicitly below -- read that section first.

## Architecture

```
Home Assistant
  └─ custom_components/swiggy_bridge  (HACS integration)
       polls  GET /api/poll  every 60s
       │
       ▼
  swiggy_mcp_bridge  (HA add-on, Docker, ingress UI)
       owns OAuth session (DCR + PKCE, token refresh)
       translates REST ↔ MCP JSON-RPC (Streamable HTTP)
       │
       ▼
  mcp.swiggy.com/{im,dineout,food,scenes}   (Swiggy's real MCP servers)
```

The add-on is the only thing that talks to Swiggy. The integration never sees
a Swiggy token -- it only reads `GET /api/poll`, a plain JSON snapshot. This
mirrors the "add-on owns auth" split the reference project uses, which is a
good pattern; we kept it.

**The key design difference:** `/api/poll` fetches every configured
server/operation *independently* (`asyncio.gather`, each wrapped in its own
try/except) and returns per-operation `{"ok": bool, ...}` entries. A 403 on
one operation shows up as `{"ok": false, "error": "access_denied"}` for that
one entry -- it cannot prevent the other entries in the same snapshot from
populating. The HA-side coordinator (`coordinator.py`) only raises
`UpdateFailed` when it can't reach the add-on at all, never because of a
single bad upstream call. This was verified with a test harness that mocks
Swiggy's MCP responses and asserts a 403 on one op doesn't blank out the rest
(see "What's been tested" below).

## Before you install anything: Swiggy access

This only works at all if Swiggy has granted *your* integration access to
their Builders Club MCP program. That is not something code can route around:

- **Auth is open.** Dynamic Client Registration (RFC 7591) means the add-on
  can register itself and complete OAuth login without any manual whitelist --
  that's why the reference project could show "✓ Authenticated" at all.
- **Tool calls are not open.** Actually calling a tool on `/im` (Instamart),
  `/dineout`, or `/food` requires *production access*, which Swiggy grants
  per integration after an application review. Until that's approved, expect
  403s on every tool call, same as we saw with the reference project.
- **Food is currently a dead end for third-party apps.** Per Swiggy's own
  published pages (Aug 2026), Food ordering through MCP is described as
  ChatGPT-only, with third-party app development "not permitted at this
  time." `tool_map.py` leaves the `food` mapping empty on purpose, and the
  add-on's default options only enable `instamart` (the current priority --
  add `dineout` back in the add-on's options whenever you want it). Don't
  bother applying for Food access yet -- check Swiggy's docs again before you
  do, in case this has changed.
- **How to apply:** https://mcp.swiggy.com/builders/access/ (or email
  builders@swiggy.in if there's no form). You'll need: integration name +
  org, your redirect URI (`http://localhost/callback` for this add-on, since
  it's a local dev client), which servers you want (`instamart`, `dineout`),
  expected volume, a one-paragraph use case, and a technical contact. Build
  and demo against Swiggy's dev stub or staging first -- the application asks
  for a short screen recording of a working flow. Staging access typically
  precedes production by about 48 hours once your redirect URI is
  allowlisted; there's no fixed SLA for the initial review.

Everything below works regardless of where you are in that process -- the
add-on will authenticate and run, it just won't return real data until
production access lands.

## Installing

1. Push this repo's contents to
   https://github.com/adkunju/Swiggy-MCP---NN150SmartHome---HASS (it already
   has a LICENSE + README from GitHub's "create repo" flow, so clone it first
   and copy these files in rather than force-pushing over it -- see the exact
   commands below).
2. **Add-on:** Settings → Add-ons → Add-on store → ⋮ → Repositories → add
   `https://github.com/adkunju/Swiggy-MCP---NN150SmartHome---HASS` → install
   "Swiggy MCP Bridge" → start it.
3. In the add-on's options, confirm `enabled_servers` (default: `instamart`
   only, matching the current priority -- add `dineout` later if wanted).
4. Open the add-on's Web UI (ingress panel). Click **Login with Swiggy** --
   this opens Swiggy's auth page in a new tab. After you approve, that tab
   will land on `http://localhost/callback?code=...&state=...` and look
   broken (connection refused) -- that's expected, since nothing is actually
   listening on your own machine at that address. Copy the *entire* address
   bar contents and paste them into the add-on UI, then click **Complete
   login**.
5. **Integration:** install HACS if you don't have it, add this same repo as
   a custom HACS repository (category: Integration), install "Swiggy MCP
   Bridge", restart Home Assistant, then Settings → Devices & Services → Add
   Integration → "Swiggy MCP Bridge" → enter the add-on's URL (default
   `http://homeassistant.local:8099`, or `http://<supervisor-hostname>:8099`
   -- check the add-on's Info tab for its hostname).

## Once you have production access: fix the tool names

Swiggy doesn't publish exact MCP tool names/schemas outside the program, so
`tool_map.py`'s defaults (`get_cart`, `clear_cart`, `add_to_cart`,
`get_orders`, `get_addresses`, `get_bookings`, `search_restaurants`) are
educated guesses, not confirmed. Once your access is live:

1. In the add-on UI, pick a server and click **List tools** -- this calls
   `tools/list` for real and shows you the actual names and input schemas.
2. Edit the **Tool name mapping** box to match, and click **Save**. No
   rebuild or restart needed -- it's read from `/data/tool_map.json` on every
   poll.
3. `sensor.py`'s field lookups (`cart.get("total")`, `order.get("eta")`, etc.)
   are similarly best-effort. Use the raw output from a manual
   `POST /api/instamart/call {"tool": "...", "arguments": {}}` (or the
   `extra_state_attributes` on `Instamart Cart Items`) to see real field
   names and adjust.

## What's been tested (and what hasn't)

Tested with a local harness that mocks the Swiggy MCP responses (no real
Swiggy credentials exist for this project):

- PKCE verifier/challenge generation matches the spec (S256).
- Redirect-URL parsing handles success, Swiggy error responses, and
  malformed/missing params.
- The Streamable-HTTP SSE response parser correctly skips progress
  notifications and finds the response matching the request's JSON-RPC id.
- `tool_map.json` persistence and merge-over-defaults.
- The full aiohttp route surface (`/api/status`, `/api/poll`,
  `/api/<server>/call`, `/api/<server>/tools`) end-to-end against a live
  `TestClient`, including the specific case this project exists to fix: one
  mocked tool call returning 403 does **not** blank out the other operations
  in the same `/api/poll` response.

**Not tested** (can't be, without real access): the actual shape of Swiggy's
tool responses, real OAuth round-trip against `mcp.swiggy.com`, and the
`custom_components/swiggy_bridge` HACS integration's Home Assistant
entity/coordinator code -- that needs a real HA instance (or `pytest-homeassistant-custom-component`)
to exercise, which wasn't available in the environment this was built in.
Treat the integration side as reviewed-but-unexercised and watch its logs the
first time you run it for real.

## Known gaps / next steps

- Dineout booking *creation* isn't wired up (read-only `list_bookings` sensor
  only) -- add a tool call once you've confirmed the real tool name/schema.
- No icon.png for the add-on store listing.
- `sensor.py`'s address/order field lookups need a pass once you've seen a
  real payload (see above).
- Consider adding a repair/issue in HA (`homeassistant.helpers.issue_registry`)
  when an op comes back `access_denied`, so "I'm authenticated but getting no
  data" is visible in the UI instead of only in logs -- this is the exact
  confusing state we debugged in the reference project.
