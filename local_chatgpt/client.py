"""OpenAI-compatible client factory — API key ya ChatGPT OAuth."""

from __future__ import annotations

import os
from typing import Any, Literal

from openai import OpenAI, AuthenticationError

from .auth import WHAM_BASE_URL, AuthManager

AuthMode = Literal["auto", "oauth", "api_key"]


def _env_api_key() -> str | None:
    return (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("LOCAL_CHATGPT_API_KEY")
        or None
    )


def get_client(
    *,
    api_key: str | None = None,
    auth: AuthMode = "auto",
    auth_path: str | None = None,
    base_url: str | None = None,
    **kwargs: Any,
) -> OpenAI:
    """
    Kisi bhi project me use karo.

    Auth priority (auth=\"auto\"):
      1. api_key= argument
      2. OPENAI_API_KEY / LOCAL_CHATGPT_API_KEY env
      3. Saved ChatGPT OAuth tokens (~/.local_chatgpt/auth.json ya ~/.codex/auth.json)
    """
    key = api_key or _env_api_key()

    if auth == "api_key" or (auth == "auto" and key):
        if not key:
            raise RuntimeError("API key missing. Set OPENAI_API_KEY or pass api_key=...")
        return OpenAI(
            api_key=key,
            base_url=base_url or os.environ.get("OPENAI_BASE_URL"),
            **kwargs,
        )

    if auth in ("oauth", "auto"):
        manager = AuthManager(path=auth_path)
        if manager.has_api_key:
            return OpenAI(
                api_key=manager.access_token(),
                base_url=base_url or os.environ.get("OPENAI_BASE_URL"),
                **kwargs,
            )
        manager.ensure_valid()
        headers = dict(kwargs.pop("default_headers", {}) or {})
        headers.setdefault("User-Agent", "local_chatgpt/1.0.0")
        if aid := manager.account_id():
            headers["ChatGPT-Account-Id"] = aid
        return OpenAI(
            api_key=manager.access_token(),
            base_url=base_url or WHAM_BASE_URL,
            default_headers=headers,
            **kwargs,
        )

    raise RuntimeError(f"Unknown auth mode: {auth}")


class LocalChatGPT:
    """
    Simple wrapper: chat() helper + raw OpenAI client.

    OAuth mode WHAM Responses API use karta hai.
    API-key mode normal Chat Completions use karta hai.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        auth: AuthMode = "auto",
        auth_path: str | None = None,
        model: str | None = None,
        system: str = "You are a helpful assistant.",
    ):
        self.auth_mode = auth
        self.auth_path = auth_path
        self.api_key = api_key
        self.system = system
        self.model = model or (
            "gpt-4o-mini" if (api_key or _env_api_key()) and auth != "oauth" else "gpt-5.4-mini"
        )
        self._manager = AuthManager(path=auth_path)
        self.client = get_client(api_key=api_key, auth=auth, auth_path=auth_path)

    def _using_oauth_backend(self) -> bool:
        if self.auth_mode == "api_key":
            return False
        if self.api_key or (_env_api_key() and self.auth_mode == "auto"):
            return False
        if self._manager.has_api_key:
            return False
        return True

    def _refresh_client(self) -> None:
        self._manager = AuthManager(path=self.auth_path)
        if self._using_oauth_backend():
            self._manager.refresh()
        self.client = get_client(
            api_key=self.api_key, auth=self.auth_mode, auth_path=self.auth_path
        )

    def chat(
        self,
        message: str,
        *,
        model: str | None = None,
        system: str | None = None,
        stream: bool = False,
    ) -> str:
        """Simple one-shot chat. Returns full text."""
        model = model or self.model
        system = system if system is not None else self.system

        def _run() -> str:
            if self._using_oauth_backend():
                return self._chat_oauth(message, model=model, system=system, stream=stream)
            return self._chat_api(message, model=model, system=system, stream=stream)

        try:
            return _run()
        except AuthenticationError:
            if self._using_oauth_backend():
                self._refresh_client()
                return _run()
            raise

    def _chat_api(
        self, message: str, *, model: str, system: str, stream: bool
    ) -> str:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": message},
        ]
        if stream:
            parts: list[str] = []
            with self.client.chat.completions.create(
                model=model, messages=messages, stream=True
            ) as s:
                for event in s:
                    delta = event.choices[0].delta.content or ""
                    if delta:
                        print(delta, end="", flush=True)
                        parts.append(delta)
            print()
            return "".join(parts)

        resp = self.client.chat.completions.create(model=model, messages=messages)
        return resp.choices[0].message.content or ""

    def _chat_oauth(
        self, message: str, *, model: str, system: str, stream: bool
    ) -> str:
        # WHAM Responses API quirks
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": system,
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": message}],
                }
            ],
            "store": False,
        }
        if stream:
            parts: list[str] = []
            with self.client.responses.create(**kwargs, stream=True) as s:
                for event in s:
                    if getattr(event, "type", None) == "response.output_text.delta":
                        print(event.delta, end="", flush=True)
                        parts.append(event.delta)
            print()
            return "".join(parts)

        resp = self.client.responses.create(**kwargs)
        return getattr(resp, "output_text", None) or str(resp)


def chat(
    message: str,
    *,
    model: str | None = None,
    system: str | None = None,
    stream: bool = False,
    api_key: str | None = None,
    auth: AuthMode = "auto",
    auth_path: str | None = None,
) -> str:
    """One-liner helper for any project."""
    bot = LocalChatGPT(
        api_key=api_key,
        auth=auth,
        auth_path=auth_path,
        model=model,
        system=system or "You are a helpful assistant.",
    )
    return bot.chat(message, model=model, system=system, stream=stream)