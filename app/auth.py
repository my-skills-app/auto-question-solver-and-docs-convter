"""Auth layer — local_chatgpt OAuth / API key (no secrets in source)."""

from __future__ import annotations

from pathlib import Path

from local_chatgpt.auth import AuthManager, login as oauth_login
from local_chatgpt.client import get_client


def status() -> dict:
    am = AuthManager()
    if am.has_oauth:
        return {
            "connected": True,
            "mode": "oauth",
            "path": str(am.path),
            "account": am.account_id(),
        }
    if am.has_api_key:
        return {
            "connected": True,
            "mode": "api_key",
            "path": str(am.path),
            "account": None,
        }
    # env key counts as connected for processing
    from local_chatgpt.client import _env_api_key

    if _env_api_key():
        return {
            "connected": True,
            "mode": "api_key_env",
            "path": None,
            "account": None,
        }
    return {"connected": False, "mode": None, "path": str(am.path), "account": None}


def ensure_auth() -> None:
    info = status()
    if not info["connected"]:
        raise RuntimeError(
            "Not authenticated.\n"
            "Run: .\\.venv\\Scripts\\python.exe -m local_chatgpt login\n"
            "Or:  set OPENAI_API_KEY=sk-..."
        )


def sign_in(*, headless: bool = False) -> None:
    if headless:
        from local_chatgpt.auth import login_headless

        login_headless()
    else:
        oauth_login()


def make_openai_client():
    ensure_auth()
    return get_client(auth="auto")


def using_oauth_backend() -> bool:
    info = status()
    return info["mode"] == "oauth"