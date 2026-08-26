"""CLI: python -m local_chatgpt login | test | logout | status"""

from __future__ import annotations

import argparse
import sys

from .auth import AuthManager, login, login_headless


def cmd_status(_: argparse.Namespace) -> int:
    am = AuthManager()
    print(f"Auth file : {am.path}")
    if am.has_oauth:
        print("Mode      : ChatGPT OAuth")
        print(f"Account   : {am.account_id() or '(unknown)'}")
        print(f"Expires   : {am.data.get('expires')}")
        return 0
    if am.has_api_key:
        print("Mode      : API key (saved)")
        return 0
    print("Mode      : not logged in")
    print("Run: .\\.venv\\Scripts\\python.exe -m local_chatgpt login")
    print("Or:  set OPENAI_API_KEY=sk-...")
    return 1


def cmd_login(args: argparse.Namespace) -> int:
    if args.api_key:
        am = AuthManager(path=args.auth)
        am.save_api_key(args.api_key)
        print(f"API key saved to {am.path}")
        return 0
    if args.headless:
        login_headless(path=args.auth)
    else:
        login(path=args.auth, open_browser=not args.no_browser)
    return 0


def cmd_logout(_: argparse.Namespace) -> int:
    am = AuthManager()
    am.logout()
    print("Logged out.")
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    from .client import LocalChatGPT

    bot = LocalChatGPT(auth_path=args.auth, model=args.model)
    print(f"Model: {bot.model}")
    reply = bot.chat(args.prompt, stream=True)
    print("\n--- done ---")
    print(f"Chars: {len(reply)}")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    import json

    from .client import get_client

    client = get_client(auth_path=args.auth, auth="oauth")
    raw = client.models.with_raw_response.list(
        extra_query={"client_version": "1.0.0"}
    )
    data = json.loads(raw.text)
    models = data.get("models") or data.get("data") or []
    for m in models:
        slug = m.get("slug") or m.get("id")
        print(slug)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="local_chatgpt",
        description="Local ChatGPT OAuth / API-key helper for any Python project",
    )
    parser.add_argument(
        "--auth",
        default=None,
        help="Path to auth.json (default: ~/.local_chatgpt/auth.json)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="Browser ChatGPT OAuth login")
    p_login.add_argument("--headless", action="store_true", help="Paste redirect URL")
    p_login.add_argument("--no-browser", action="store_true")
    p_login.add_argument(
        "--api-key",
        help="Save an OpenAI Platform API key instead of OAuth",
    )
    p_login.set_defaults(func=cmd_login)

    sub.add_parser("logout", help="Delete saved tokens").set_defaults(func=cmd_logout)
    sub.add_parser("status", help="Show auth status").set_defaults(func=cmd_status)

    p_test = sub.add_parser("test", help="Send a test prompt")
    p_test.add_argument("-m", "--model", default=None)
    p_test.add_argument(
        "-p",
        "--prompt",
        default="Say hello in one short sentence.",
    )
    p_test.set_defaults(func=cmd_test)

    p_models = sub.add_parser("models", help="List WHAM models (OAuth)")
    p_models.set_defaults(func=cmd_models)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
