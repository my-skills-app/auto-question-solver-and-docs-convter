"""Local ChatGPT client — ChatGPT OAuth ya OpenAI API key se use karo."""

from .auth import AuthManager, login

__all__ = [
    "AuthManager",
    "LocalChatGPT",
    "chat",
    "get_client",
    "login",
]

__version__ = "1.0.0"


def __getattr__(name: str):
    # openai sirf tab load ho jab client chahiye (login ke liye zaruri nahi)
    if name in ("LocalChatGPT", "chat", "get_client"):
        from . import client

        return getattr(client, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
