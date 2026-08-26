"""End-to-end pipeline: input → AI solve → CSV/JSON/DOCX → cleanup."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .cleanup import clean_partial_csvs, clean_temp, release_page
from .csv_template import save_template_csv
from .excel_export import save_xlsx
from .exporter import export_all
from .json_schema import empty_document, validate_document
from .processor import get_page, load_document
from .solver import AISolver

ProgressCb = Callable[[str, float], None]
CHECKPOINT_EVERY = 5  # pages


def _renumber(questions: list[dict]) -> None:
    for idx, q in enumerate(questions, start=1):
        q["question_r"] = idx
        q["question_number"] = idx


def _page_error(page_no: int, exc: Exception, next_num: int) -> dict:
    return {
        "question_r": next_num,
        "question_type": "MCQ",
        "question_hi": "",
        "question_en": f"[Page {page_no} failed to process]",
        "options_hi": {},
        "options_en": {},
        "solution_hi": "",
        "solution_en": str(exc),
        "answer": "",
        "difficulty_level": "medium",
        "confidence": 0.0,
        "status": "needs_review",
        "warnings": ["page_error"],
    }


def solve_file(
    path: str | Path,
    *,
    out_dir: str | Path | None = None,
    model: str | None = None,
    force_images: bool = False,
    max_pages: int | None = None,
    set_name: str | None = None,
    progress: ProgressCb | None = None,
) -> dict:
    def report(msg: str, pct: float) -> None:
        if progress:
            progress(msg, pct)
        else:
            print(f"[{pct:5.1f}%] {msg}", flush=True)

    src = Path(path)
    paper_name = set_name or src.stem
    out = Path(out_dir) if out_dir else Path("output") / src.stem
    out.mkdir(parents=True, exist_ok=True)
    clean_temp()
    clean_partial_csvs(out)

    report("Opening document...", 3)
    with load_document(src, force_images=force_images) as document:
        total = document.page_count
        if max_pages is not None:
            total = min(total, max(0, max_pages))

        result = empty_document(
            source_file=src.name,
            source_type=document.source_type,
            title=f"Solved — {src.stem}",
        )

        report("Checking authentication...", 6)
        solver = AISolver(model=model)
        all_questions: list[dict] = []
        checkpoint = out / "solved_questions.csv"
        n = max(total, 1)

        for i in range(total):
            pct = 8 + (82 * (i / n))
            report(f"Page {i + 1}/{total}...", pct)
            page = get_page(document, i)
            try:
                qs = solver.solve_page(page, page_number=i + 1)
                all_questions.extend(qs)
            except Exception as exc:  # noqa: BLE001
                all_questions.append(
                    _page_error(i + 1, exc, len(all_questions) + 1)
                )
            finally:
                release_page(page)

            _renumber(all_questions)

            # Checkpoint every N pages + last page (not every page → less lock spam)
            if (i + 1) % CHECKPOINT_EVERY == 0 or (i + 1) == total:
                save_template_csv(
                    all_questions, checkpoint, set_name=paper_name
                )
                report(f"Checkpoint: {len(all_questions)} questions", pct + 1)

        result["questions"] = all_questions
        report("Exporting CSV / JSON / Word...", 94)
        result = validate_document(result)
        paths = export_all(
            result,
            out,
            set_name=paper_name,
            questions_raw=all_questions,
        )
        paths["csv"] = save_template_csv(
            all_questions, checkpoint, set_name=paper_name
        )
        paths["xlsx"] = save_xlsx(
            all_questions, out / "solved_questions.xlsx", set_name=paper_name
        )

    # Drop lock-fallback junk; keep only final artifacts
    clean_partial_csvs(out)
    clean_temp()
    report("Done.", 100)
    return {"document": result, "paths": paths, "questions_raw": all_questions}
