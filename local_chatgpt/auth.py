"""ChatGPT OAuth (PKCE) + token storage / refresh."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

AUTH_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
# Codex / ChatGPT WHAM backend (subscription-backed, not Platform API credits)
WHAM_BASE_URL = "https://chatgpt.com/backend-api/wham"

# Official Codex CLI public client id (same redirect used by Codex)
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
SCOPE = "openid profile email offline_access"
REDIRECT_PORT = 1455
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/auth/callback"
SAFETY_MARGIN_SEC = 30

DEFAULT_AUTH_DIR = Path.home() / ".local_chatgpt"
DEFAULT_AUTH_PATH = DEFAULT_AUTH_DIR / "auth.json"
CODEX_AUTH_PATH = Path.home() / ".codex" / "auth.json"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def extract_account_id(
    id_token: str | None, access_token: str | None
) -> str | None:
    for token in (id_token, access_token):
        if not token:
            continue
        try:
            payload_b64 = token.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        except Exception:
            continue
        if aid := payload.get("chatgpt_account_id"):
            return aid
        auth_ns = payload.get("https://api.openai.com/auth") or {}
        if aid := auth_ns.get("chatgpt_account_id"):
            return aid
        orgs = payload.get("organizations") or []
        if orgs and (aid := orgs[0].get("id")):
            return aid
    return None


def resolve_auth_path(path: str | Path | None = None) -> Path:
    if path:
        return Path(path).expanduser()
    env = os.environ.get("LOCAL_CHATGPT_AUTH")
    if env:
        return Path(env).expanduser()
    if DEFAULT_AUTH_PATH.exists():
        return DEFAULT_AUTH_PATH
    if CODEX_AUTH_PATH.exists():
        return CODEX_AUTH_PATH
    return DEFAULT_AUTH_PATH


class AuthManager:
    """Load / save / refresh ChatGPT OAuth tokens."""

    def __init__(self, path: str | Path | None = None, tokens: dict | None = None):
        self.path = resolve_auth_path(path)
        if tokens is not None:
            self._set_data(tokens)
        else:
            self.data = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _set_data(
        self, tokens: dict[str, Any], fallback_account_id: str | None = None
    ) -> None:
        expires_in = int(tokens.get("expires_in") or 3600)
        expires = int(time.time() * 1000) + expires_in * 1000
        id_token = tokens.get("id_token")
        access_token = tokens.get("access_token") or tokens.get("access")
        refresh_token = tokens.get("refresh_token") or tokens.get("refresh")
        account_id = (
            extract_account_id(id_token, access_token)
            or tokens.get("accountId")
            or fallback_account_id
        )
        data: dict[str, Any] = {
            "type": "oauth",
            "access": access_token,
            "refresh": refresh_token,
            "expires": expires,
        }
        if account_id:
            data["accountId"] = account_id
        self.data = data

    @property
    def has_oauth(self) -> bool:
        return bool(self.data.get("access") and self.data.get("refresh"))

    @property
    def has_api_key(self) -> bool:
        return self.data.get("type") == "api_key" and bool(self.data.get("api_key"))

    def save_api_key(self, api_key: str) -> None:
        self.data = {"type": "api_key", "api_key": api_key.strip()}
        self._save()

    def refresh(self) -> None:
        if not self.data.get("refresh"):
            raise RuntimeError("No refresh token. Run: python -m local_chatgpt login")
        resp = httpx.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.data["refresh"],
                "client_id": CLIENT_ID,
            },
            timeout=60,
        )
        if not (200 <= resp.status_code < 300):
            raise RuntimeError(
                f"Token refresh failed ({resp.status_code}): {resp.text[:300]}"
            )
        self._set_data(resp.json(), self.data.get("accountId"))
        self._save()

    def ensure_valid(self) -> None:
        if self.has_api_key:
            return
        if not self.has_oauth:
            raise RuntimeError(
                "Not logged in. Run: python -m local_chatgpt login\n"
                "Or set OPENAI_API_KEY / pass api_key=..."
            )
        now_ms = int(time.time() * 1000)
        expires = int(self.data.get("expires") or 0)
        if expires < now_ms + SAFETY_MARGIN_SEC * 1000:
            self.refresh()

    def access_token(self) -> str:
        self.ensure_valid()
        if self.has_api_key:
            return str(self.data["api_key"])
        return str(self.data["access"])

    def account_id(self) -> str | None:
        return self.data.get("accountId")

    def logout(self) -> None:
        if self.path.exists():
            self.path.unlink()
        self.data = {}


def _exchange_code_for_tokens(
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    retries: int = 3,
) -> dict[str, Any]:
    """Token endpoint pe POST — timeout/retry ke sath (authlib default timeout chhota hota hai)."""
    data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            print(f"  Token request attempt {attempt}/{retries}...")
            resp = httpx.post(
                TOKEN_URL,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=httpx.Timeout(60.0, connect=30.0),
            )
            if not (200 <= resp.status_code < 300):
                raise RuntimeError(
                    f"Token exchange failed ({resp.status_code}): {resp.text[:400]}"
                )
            return resp.json()
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_err = exc
            print(f"  Network issue: {exc}. Retrying...")
    raise RuntimeError(f"Token exchange timed out after {retries} tries: {last_err}")


def _build_auth_url(redirect_uri: str) -> tuple[str, str, str]:
    """Returns (auth_url, state, code_verifier)."""
    from authlib.integrations.httpx_client import OAuth2Client

    code_verifier = secrets.token_urlsafe(96)
    code_challenge = _b64url(hashlib.sha256(code_verifier.encode()).digest())
    oauth = OAuth2Client(
        client_id=CLIENT_ID, redirect_uri=redirect_uri, scope=SCOPE
    )
    auth_url, state = oauth.create_authorization_url(
        AUTH_URL,
        code_challenge=code_challenge,
        code_challenge_method="S256",
        id_token_add_organizations="true",
        codex_cli_simplified_flow="true",
        originator="local_chatgpt",
    )
    return auth_url, state, code_verifier


def login(
    *,
    path: str | Path | None = None,
    open_browser: bool = True,
    port: int = REDIRECT_PORT,
) -> AuthManager:
    """Browser OAuth PKCE login. Tokens ~/.local_chatgpt/auth.json me save hote hain."""
    redirect_uri = f"http://localhost:{port}/auth/callback"
    auth_url, state, code_verifier = _build_auth_url(redirect_uri)

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/auth/callback":
                self.send_response(404)
                self.end_headers()
                return

            params = parse_qs(parsed.query)
            received_state = params.get("state", [None])[0]
            error = None
            code = None
            if received_state != self.server.expected_state:  # type: ignore[attr-defined]
                error = "CSRF error: state mismatch"
            elif "error" in params:
                error = params.get("error_description", ["Unknown error"])[0]
            else:
                code = params.get("code", [None])[0]

            self.server.auth_code = code  # type: ignore[attr-defined]
            self.server.error = error  # type: ignore[attr-defined]

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if code:
                body = (
                    "<h2>Login successful</h2>"
                    "<p>You can close this tab and return to the terminal.</p>"
                )
            else:
                body = f"<h2>Login failed</h2><p>{error}</p>"
            self.wfile.write(body.encode())
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, format, *args):  # noqa: A003
            return

    server = HTTPServer(("localhost", port), CallbackHandler)
    server.auth_code = None  # type: ignore[attr-defined]
    server.error = None  # type: ignore[attr-defined]
    server.expected_state = state  # type: ignore[attr-defined]

    print("ChatGPT OAuth login...")
    print(f"Agar browser na khule to ye URL kholo:\n\n{auth_url}\n")
    if open_browser:
        webbrowser.open(auth_url)

    print(f"Waiting for callback on {redirect_uri} ...")
    server.serve_forever()

    if server.error:  # type: ignore[attr-defined]
        raise RuntimeError(f"Authentication error: {server.error}")
    if not server.auth_code:  # type: ignore[attr-defined]
        raise RuntimeError("No authorization code received.")

    print("Exchanging code for tokens...")
    token = _exchange_code_for_tokens(
        code=server.auth_code,  # type: ignore[attr-defined]
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
    )

    auth_path = resolve_auth_path(path)
    # Prefer our default dir unless user passed an explicit path
    if path is None and not os.environ.get("LOCAL_CHATGPT_AUTH"):
        auth_path = DEFAULT_AUTH_PATH

    am = AuthManager(path=auth_path, tokens=token)
    am._save()
    print("\nLogin SUCCESSFUL")
    print(f"Saved: {am.path}")
    if am.account_id():
        print(f"Account: {am.account_id()}")
    return am


def login_headless(*, path: str | Path | None = None) -> AuthManager:
    """Headless: URL print + redirect URL paste (SSH / remote)."""
    auth_url, state, code_verifier = _build_auth_url(REDIRECT_URI)

    print("1) Browser me ye URL kholo:\n")
    print(auth_url)
    print(
        "\n2) Login ke baad redirect URL paste karo "
        "(http://localhost:1455/auth/callback?code=...&state=...):\n"
    )
    callback = input("Redirect URL: ").strip()
    parsed = urlparse(callback)
    params = parse_qs(parsed.query)
    if params.get("state", [None])[0] != state:
        raise RuntimeError("CSRF error: state mismatch")
    if "error" in params:
        raise RuntimeError(params.get("error_description", ["Unknown error"])[0])
    code = params.get("code", [None])[0]
    if not code:
        raise RuntimeError("No code in redirect URL")

    print("Exchanging code for tokens...")
    token = _exchange_code_for_tokens(
        code=code,
        code_verifier=code_verifier,
        redirect_uri=REDIRECT_URI,
    )
    auth_path = resolve_auth_path(path)
    if path is None and not os.environ.get("LOCAL_CHATGPT_AUTH"):
        auth_path = DEFAULT_AUTH_PATH
    am = AuthManager(path=auth_path, tokens=token)
    am._save()
    print("\nLogin SUCCESSFUL")
    print(f"Saved: {am.path}")
    return am