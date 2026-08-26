"""Local temp / partial output cleanup."""

from __future__ import annotations

import gc
import re
import shutil
from pathlib import Path

from .processor import PageContent

# Final keep list inside an output run folder
KEEP_NAMES = {
    "solved_questions.csv",
    "solved_questions.xlsx",
    "solved_questions.json",
    "solved_questions.docx",
    "processing_report.json",
    "solved_questions.recovered.csv",
}


# Timestamped lock-fallback files: solved_questions_134903.csv
PARTIAL_CSV_RE = re.compile(r"^solved_questions_\d{6}\.csv$", re.I)
CHECKPOINT_NAMES = {"solved_questions.checkpoint.csv"}


def release_page(page: PageContent | None) -> None:
    """Drop large base64 image from memory after AI call."""
    if page is None:
        return
    page.image_b64 = None
    page.text = ""
    gc.collect()


def clear_dir(path: Path, *, keep: set[str] | None = None) -> list[Path]:
    """Delete files in dir except keep names. Returns deleted paths."""
    path = Path(path)
    if not path.exists() or not path.is_dir():
        return []
    keep = keep or set()
    deleted: list[Path] = []
    for item in path.iterdir():
        if item.name in keep:
            continue
        try:
            if item.is_file():
                item.unlink()
                deleted.append(item)
            elif item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
                deleted.append(item)
        except OSError:
            pass
    return deleted


def clean_partial_csvs(out_dir: Path, *, keep_final: bool = True) -> list[Path]:
    """Remove solved_questions_HHMMSS.csv / checkpoint junk left when Excel locked the file."""
    out_dir = Path(out_dir)
    if not out_dir.exists():
        return []
    deleted: list[Path] = []
    for item in out_dir.iterdir():
        if not item.is_file():
            continue
        name = item.name
        drop = False
        if PARTIAL_CSV_RE.match(name):
            drop = True
        elif name in CHECKPOINT_NAMES:
            drop = True
        elif name.endswith(".csv.tmp") or name.endswith(".docx.tmp"):
            drop = True
        if keep_final and name == "solved_questions.csv":
            drop = False
        if drop:
            try:
                item.unlink()
                deleted.append(item)
            except OSError:
                pass
    return deleted


def clean_run_folder(out_dir: Path) -> list[Path]:
    """Keep only final 4 output files in a solve run folder."""
    out_dir = Path(out_dir)
    deleted = clean_partial_csvs(out_dir)
    deleted.extend(clear_dir(out_dir, keep=KEEP_NAMES))
    return deleted


# Web UI stores uploads + job outputs here — never wipe during solve
PRESERVE_TEMP_DIRS = {"jobs"}


def clean_temp(project_root: Path | None = None) -> list[Path]:
    """
    Clean loose temp files / uploads.
    Does NOT delete temp/jobs (web uploads + live outputs live there).
    """
    root = Path(project_root) if project_root else Path.cwd()
    temp = root / "temp"
    if not temp.exists():
        return []
    deleted: list[Path] = []
    for item in temp.iterdir():
        if item.name == ".gitignore":
            continue
        if item.name in PRESERVE_TEMP_DIRS:
            continue
        try:
            if item.is_file():
                item.unlink()
            elif item.is_dir() and item.name == "uploads":
                # clear old upload cache only
                for child in item.iterdir():
                    try:
                        if child.is_file():
                            child.unlink()
                        else:
                            shutil.rmtree(child, ignore_errors=True)
                        deleted.append(child)
                    except OSError:
                        pass
            elif item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
                deleted.append(item)
        except OSError:
            pass
    return deleted


def promote_best_csv(out_dir: Path) -> Path | None:
    """Prefer recovered/checkpoint/largest partial over a smaller locked main CSV."""
    out_dir = Path(out_dir)
    if not out_dir.exists():
        return None
    final = out_dir / "solved_questions.csv"
    candidates = [
        out_dir / "solved_questions.recovered.csv",
        out_dir / "solved_questions.checkpoint.csv",
        *sorted(
            out_dir.glob("solved_questions_*.csv"),
            key=lambda p: p.stat().st_size,
            reverse=True,
        ),
    ]
    best = next((p for p in candidates if p.exists() and p.stat().st_size > 0), None)
    if best is None:
        return final if final.exists() else None
    if (not final.exists()) or final.stat().st_size < best.stat().st_size:
        try:
            shutil.copy2(best, final)
            return final
        except OSError:
            return best
    return final


def clean_project(
    project_root: Path | None = None,
    *,
    output_dir: Path | None = None,
    deep: bool = False,
) -> dict[str, int]:
    """
    Clean local junk so next run is fresh.
    deep=True → also wipe entire output/* (except .gitignore).
    """
    root = Path(project_root) if project_root else Path.cwd()
    deleted = 0
    deleted += len(clean_temp(root))

    out_root = Path(output_dir) if output_dir else root / "output"
    if out_root.exists():
        if deep:
            for item in out_root.iterdir():
                if item.name == ".gitignore":
                    continue
                try:
                    if item.is_file():
                        item.unlink()
                    else:
                        shutil.rmtree(item, ignore_errors=True)
                    deleted += 1
                except OSError:
                    pass
        else:
            for item in out_root.iterdir():
                if item.is_dir() and item.name != "_csv_smoke":
                    promote_best_csv(item)
                    deleted += len(clean_run_folder(item))
                elif item.name == "_csv_smoke":
                    shutil.rmtree(item, ignore_errors=True)
                    deleted += 1
                elif PARTIAL_CSV_RE.match(item.name):
                    try:
                        item.unlink()
                        deleted += 1
                    except OSError:
                        pass

    return {"deleted": deleted}
