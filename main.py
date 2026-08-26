"""
AI Question Solver — CLI

  .\\.venv\\Scripts\\python.exe main.py auth
  .\\.venv\\Scripts\\python.exe main.py login
  .\\.venv\\Scripts\\python.exe main.py solve examples\\inputpdf.pdf --force-images
  .\\.venv\\Scripts\\python.exe main.py docx-from-csv output\\inputpdf\\solved_questions.csv
  .\\.venv\\Scripts\\python.exe main.py clean
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cmd_auth(_: argparse.Namespace) -> int:
    from app.auth import status

    info = status()
    print(json.dumps(info, indent=2))
    return 0 if info["connected"] else 1


def cmd_login(args: argparse.Namespace) -> int:
    from app.auth import sign_in, status

    sign_in(headless=args.headless)
    print(json.dumps(status(), indent=2))
    return 0


def cmd_solve(args: argparse.Namespace) -> int:
    from app.pipeline import solve_file

    result = solve_file(
        args.path,
        out_dir=args.out,
        model=args.model,
        force_images=args.force_images,
        max_pages=args.max_pages,
        set_name=args.set_name,
    )
    paths = result["paths"]
    print("\n=== Result ===")
    print(f"Questions : {len(result.get('questions_raw') or [])}")
    print(f"CSV       : {paths.get('csv')}")
    print(f"JSON      : {paths['json']}")
    print(f"Word      : {paths['docx']}")
    print(f"Report    : {paths['report']}")
    return 0


def cmd_docx_from_csv(args: argparse.Namespace) -> int:
    from app.exporter import save_docx_from_csv

    csv_path = Path(args.csv)
    out = Path(args.out) if args.out else csv_path.with_name("solved_questions.docx")
    path = save_docx_from_csv(csv_path, out, set_name=args.set_name)
    print(f"Word saved: {path}")
    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    from app.cleanup import clean_project, promote_best_csv

    root = Path(__file__).resolve().parent
    # Try promote full CSV before deleting partials
    out = root / "output" / "inputpdf"
    if out.exists():
        promoted = promote_best_csv(out)
        if promoted:
            print(f"CSV ready: {promoted}")
    stats = clean_project(root, deep=args.deep)
    print(f"Cleaned. Deleted items: {stats['deleted']}")
    if args.deep:
        print("Deep clean: output/* wiped (except .gitignore).")
    else:
        print("Kept: solved_questions.csv/json/docx + processing_report.json")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ai-question-solver",
        description="Solve PDF/image papers → CSV template + JSON + Word",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("auth", help="Auth status").set_defaults(func=cmd_auth)

    p_login = sub.add_parser("login", help="ChatGPT OAuth login")
    p_login.add_argument("--headless", action="store_true")
    p_login.set_defaults(func=cmd_login)

    p_solve = sub.add_parser("solve", help="Solve PDF / image")
    p_solve.add_argument("path")
    p_solve.add_argument("--out", default=None)
    p_solve.add_argument("-m", "--model", default=None)
    p_solve.add_argument("--force-images", action="store_true")
    p_solve.add_argument("--max-pages", type=int, default=None)
    p_solve.add_argument("--set-name", default=None)
    p_solve.set_defaults(func=cmd_solve)

    p_docx = sub.add_parser("docx-from-csv", help="Rebuild Word from CSV")
    p_docx.add_argument("csv")
    p_docx.add_argument("--out", default=None)
    p_docx.add_argument("--set-name", default=None)
    p_docx.set_defaults(func=cmd_docx_from_csv)

    p_clean = sub.add_parser("clean", help="Delete temp + partial local files")
    p_clean.add_argument(
        "--deep",
        action="store_true",
        help="Also wipe entire output/ folder",
    )
    p_clean.set_defaults(func=cmd_clean)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    raise SystemExit(main())
