#!/usr/bin/env python3
"""
Zero-manual bootstrap:
  - installs uv if needed (uv can fetch Python)
  - creates venv + installs deps
  - ChatGPT login if not connected
  - starts web server only after login success

Run:  double-click START.bat   OR   python START.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQ = ROOT / "requirements.txt"
URL = "http://127.0.0.1:7860"


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def which(name: str) -> str | None:
    return shutil.which(name)


def run(cmd: list[str], check: bool = True) -> int:
    print(">", " ".join(str(c) for c in cmd))
    completed = subprocess.run(cmd, cwd=ROOT)
    if check and completed.returncode != 0:
        raise SystemExit(completed.returncode)
    return completed.returncode


def find_uv() -> str | None:
    p = which("uv")
    if p:
        return p
    home = Path.home()
    candidates = [
        home / ".local" / "bin" / "uv.exe",
        home / ".local" / "bin" / "uv",
        home / ".cargo" / "bin" / "uv.exe",
        home / ".cargo" / "bin" / "uv",
        ROOT / "tools" / "uv.exe",
        ROOT / "tools" / "uv",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def install_uv() -> str:
    if os.name == "nt":
        print("[setup] uv install via PowerShell...")
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "irm https://astral.sh/uv/install.ps1 | iex",
            ],
            cwd=ROOT,
        )
    else:
        print("[setup] uv install via curl...")
        subprocess.run(
            "curl -LsSf https://astral.sh/uv/install.sh | sh",
            shell=True,
            cwd=ROOT,
            check=False,
        )
    found = find_uv()
    if found:
        return found
    raise SystemExit(
        "[ERROR] uv install fail. Internet check karo.\n"
        "https://docs.astral.sh/uv/getting-started/installation/"
    )


def ensure_runtime() -> Path:
    uv = find_uv() or install_uv()
    print(f"[1/5] setup tool: {uv}")

    print("[2/5] Python ensure (auto-download if needed)...")
    run([uv, "python", "install", "3.12"], check=False)

    py = venv_python()
    if not py.exists():
        print("[3/5] Creating virtual env...")
        code = run([uv, "venv", str(VENV), "--python", "3.12"], check=False)
        if code != 0:
            run([uv, "venv", str(VENV)])
    else:
        print("[3/5] Virtual env ready.")

    py = venv_python()
    if not py.exists():
        raise SystemExit("[ERROR] venv python missing")

    print("[4/5] Installing dependencies...")
    run([uv, "pip", "install", "--python", str(py), "-r", str(REQ)])
    run([uv, "pip", "install", "--python", str(py), "-e", str(ROOT)])
    return py


def connected(py: Path) -> bool:
    code = subprocess.run(
        [
            str(py),
            "-c",
            "from app.auth import status; import sys; "
            "s=status(); print(s); sys.exit(0 if s.get('connected') else 1)",
        ],
        cwd=ROOT,
    ).returncode
    return code == 0


def ensure_login(py: Path) -> None:
    print("[5/5] ChatGPT login check...")
    if connected(py):
        print("    Already connected.")
        return
    print()
    print("    Login zaroori hai. Browser khulega — ChatGPT se sign in karo.")
    print("    Success ke baad server AUTOMATIC start hoga.")
    print()
    code = subprocess.run([str(py), str(ROOT / "main.py"), "login"], cwd=ROOT).returncode
    if code != 0 or not connected(py):
        raise SystemExit("[ERROR] Login fail / verify fail. Dobara START chalao.")
    print("    Login SUCCESS.")


def main() -> int:
    print()
    print("============================================")
    print("  AI Question Solver — fully automatic")
    print("============================================")
    print()

    py = ensure_runtime()
    ensure_login(py)

    print()
    print(f"    Server start...  {URL}")
    print("    Band: Ctrl+C")
    print()

    def _open() -> None:
        time.sleep(1.6)
        try:
            webbrowser.open(URL)
        except Exception:
            pass

    import threading

    threading.Thread(target=_open, daemon=True).start()
    return subprocess.call([str(py), "-m", "web.server"], cwd=ROOT)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
        raise SystemExit(0)
