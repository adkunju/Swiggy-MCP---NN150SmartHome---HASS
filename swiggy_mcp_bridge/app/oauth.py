"""
OAuth 2.1 + PKCE + Dynamic Client Registration against Swiggy's Builders Club
MCP auth server.

Reference (as published by Swiggy, Aug 2026):
  Base:          https://mcp.swiggy.com
  Authorize:     GET  /auth/authorize
  Token:         POST /auth/token
  Logout:        POST /auth/logout
  DCR register:  POST /auth/register
  Metadata:      /.well-known/oauth-authorization-server
                 /.well-known/oauth-protected-resource

Scopes: mcp:tools, mcp:resources, mcp:prompts (server-level, not read/write split --
access to food/instamart/dineout/scenes is governed by the user's Swiggy account
and by whether this integration has been granted production access).

Redirect URI: Swiggy requires HTTPS except for http://localhost, which is allowed
for local development. Since an HA add-on isn't normally reachable over public
HTTPS, we use the same "code-paste" pattern as other local-first MCP clients:
we send the user to /auth/authorize with redirect_uri=http://localhost/callback,
the browser lands on a page that doesn't resolve to anything (that's expected),
and the user copies that URL back into the add-on UI, where we parse the
`code` and `state` query params out of it ourselves.

Token lifetimes: access token ~5 days, refresh token ~30 days (rotates on every
refresh), authorization code is single-use and expires in 120s. We refresh
proactively a few minutes before expiry.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import aiohttp

log = logging.getLogger("swiggy_bridge.oauth")

AUTH_BASE = "https://mcp.swiggy.com"
REDIRECT_URI = "http://localhost/callback"
SCOPES = "mcp:tools mcp:resources mcp:prompts"

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
CLIENT_FILE = DATA_DIR / "oauth_client.json"
TOKEN_FILE = DATA_DIR / "oauth_tokens.json"

# Refresh this many seconds before the access token actually expires.
REFRESH_SKEW_SECONDS = 600


class AuthNotReady(Exception):
    """Raised when there is no valid session yet; caller should start login."""


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@dataclass
class PendingLogin:
    state: str
    code_verifier: str
    created_at: float


class SwiggyOAuth:
    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._client = self._load_json(CLIENT_FILE)
        self._tokens = self._load_json(TOKEN_FILE)
        self._pending: Optional[PendingLogin] = None

    # ---------- persistence ----------

    @staticmethod
    def _load_json(path: Path) -> dict:
        if path.exists():
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                log.warning("Could not parse %s, ignoring", path)
        return {}

    def _save_client(self) -> None:
        CLIENT_FILE.write_text(json.dumps(self._client))
        os.chmod(CLIENT_FILE, 0o600)

    def _save_tokens(self) -> None:
        TOKEN_FILE.write_text(json.dumps(self._tokens))
        os.chmod(TOKEN_FILE, 0o600)

    # ---------- status ----------

    @property
    def is_authenticated(self) -> bool:
        return bool(self._tokens.get("access_token"))

    @property
    def expires_at(self) -> Optional[float]:
        return self._tokens.get("expires_at")

    def status(self) -> dict:
        return {
            "authenticated": self.is_authenticated,
            "expires_at": self.expires_at,
            "client_registered": bool(self._client.get("client_id")),
        }

    def logout_local(self) -> None:
        self._tokens = {}
        self._save_tokens()

    # ---------- dynamic client registration ----------

    async def _ensure_client(self, session: aiohttp.ClientSession) -> str:
        if self._client.get("client_id"):
            return self._client["client_id"]

        payload = {
            "client_name": "Swiggy MCP Bridge (Home Assistant add-on)",
            "redirect_uris": [REDIRECT_URI],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",  # public client, PKCE only
        }
        async with session.post(f"{AUTH_BASE}/auth/register", json=payload) as resp:
            body = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(
                    f"Dynamic client registration failed: {resp.status} {body[:300]}"
                )
            data = json.loads(body)

        self._client = {
            "client_id": data["client_id"],
            "client_secret": data.get("client_secret"),  # expect None for public clients
        }
        self._save_client()
        log.info("Registered OAuth client via DCR: %s", self._client["client_id"])
        return self._client["client_id"]

    # ---------- authorization code flow ----------

    async def start_login(self, session: aiohttp.ClientSession) -> str:
        """Returns the authorize URL the user should open in a browser."""
        client_id = await self._ensure_client(session)

        verifier = _b64url(secrets.token_bytes(32))
        challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
        state = _b64url(secrets.token_bytes(16))

        self._pending = PendingLogin(state=state, code_verifier=verifier, created_at=time.time())

        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        return f"{AUTH_BASE}/auth/authorize?{urllib.parse.urlencode(params)}"

    @staticmethod
    def _parse_redirect(redirect_url: str) -> tuple[str, str]:
        parsed = urllib.parse.urlparse(redirect_url.strip())
        qs = urllib.parse.parse_qs(parsed.query)
        if "error" in qs:
            desc = qs.get("error_description", [""])[0]
            raise RuntimeError(f"Swiggy returned an error: {qs['error'][0]} {desc}")
        if "code" not in qs or "state" not in qs:
            raise RuntimeError(
                "That doesn't look like the redirect URL -- it should contain "
                "?code=...&state=... (copy the whole address bar contents)."
            )
        return qs["code"][0], qs["state"][0]

    async def finish_login(self, session: aiohttp.ClientSession, redirect_url: str) -> None:
        if not self._pending:
            raise RuntimeError("No login in progress -- click Login first.")
        if time.time() - self._pending.created_at > 600:
            self._pending = None
            raise RuntimeError("That login link expired (10 min). Click Login and try again.")

        code, state = self._parse_redirect(redirect_url)
        if state != self._pending.state:
            raise RuntimeError("State mismatch -- possible CSRF, or a stale link. Try logging in again.")

        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": self._client["client_id"],
            "code_verifier": self._pending.code_verifier,
        }
        async with session.post(f"{AUTH_BASE}/auth/token", json=payload) as resp:
            body = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"Token exchange failed: {resp.status} {body[:300]}")
            data = json.loads(body)

        self._store_tokens(data)
        self._pending = None
        log.info("Login complete, access token expires at %s", self.expires_at)

    def _store_tokens(self, data: dict) -> None:
        now = time.time()
        expires_in = data.get("expires_in", 5 * 24 * 3600)
        self._tokens = {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token", self._tokens.get("refresh_token")),
            "expires_at": now + expires_in,
        }
        self._save_tokens()

    # ---------- refresh + access ----------

    async def _refresh(self, session: aiohttp.ClientSession) -> None:
        refresh_token = self._tokens.get("refresh_token")
        if not refresh_token:
            raise AuthNotReady("No refresh token stored -- log in again.")

        payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
        async with session.post(f"{AUTH_BASE}/auth/token", json=payload) as resp:
            body = await resp.text()
            if resp.status == 400:
                # invalid_grant: refresh token is dead, session expired -- don't retry
                self.logout_local()
                raise AuthNotReady(f"Refresh rejected ({body[:200]}) -- log in again.")
            if resp.status >= 500:
                raise RuntimeError(f"Swiggy auth server error on refresh: {resp.status}")
            if resp.status >= 400:
                raise RuntimeError(f"Refresh failed: {resp.status} {body[:300]}")
            data = json.loads(body)

        self._store_tokens(data)
        log.info("Refreshed access token, now expires at %s", self.expires_at)

    async def get_access_token(self, session: aiohttp.ClientSession) -> str:
        if not self.is_authenticated:
            raise AuthNotReady("Not logged in yet.")
        if (self.expires_at or 0) - REFRESH_SKEW_SECONDS < time.time():
            await self._refresh(session)
        return self._tokens["access_token"]
