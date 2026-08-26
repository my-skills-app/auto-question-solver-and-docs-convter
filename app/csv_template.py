"""Export solved rows in the exact CSV template format."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

# Exact header order from: examples/outpu template hai.csv
CSV_HEADERS = [
    "question_r",
    "question_hi",
    "option1_hi",
    "option2_hi",
    "option3_hi",
    "option4_hi",
    "option5_hi",
    "solution_hi",
    "question_en",
    "option1_en",
    "option2_en",
    "option3_en",
    "option4_en",
    "option5_en",
    "solution_en",
    "answer",
    "set_name",
    "difficulty_level",
]


def _as_html_p(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    if re.match(r"(?is)^\s*<p[\s>]", text):
        return text
    safe = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>")
    )
    return f"<p>{safe}</p>"


def _option_list(raw: Any) -> list[str]:
    """Return exactly 5 option strings."""
    if raw is None:
        return ["", "", "", "", ""]
    if isinstance(raw, dict):
        out: list[str] = []
        for i in range(1, 6):
            key = str(i)
            letter = chr(ord("A") + i - 1)
            val = raw.get(key)
            if val is None:
                val = raw.get(letter) or raw.get(letter.lower())
            if val is None:
                val = raw.get(f"option{i}") or raw.get(f"option{i}_hi") or raw.get(
                    f"option{i}_en"
                )
            out.append("" if val is None else str(val).strip())
        return out
    if isinstance(raw, list):
        vals = [str(x).strip() for x in raw]
        return (vals + ["", "", "", "", ""])[:5]
    return ["", "", "", "", ""]


def _format_answer(raw: Any, qtype: str = "") -> str:
    """
    Template rules:
      MCQ → D
      MSQ → ["3","4"]
      NAT → {"start":"86","end":"86"}
    """
    if raw is None:
        return ""
    if isinstance(raw, (dict, list)):
        return json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    s = str(raw).strip()
    if not s:
        return ""
    if (s.startswith("[") and s.endswith("]")) or (
        s.startswith("{") and s.endswith("}")
    ):
        try:
            return json.dumps(json.loads(s), ensure_ascii=False, separators=(",", ":"))
        except json.JSONDecodeError:
            return s

    qtype = (qtype or "").upper()
    if qtype == "NAT":
        return json.dumps({"start": s, "end": s}, ensure_ascii=False, separators=(",", ":"))
    if qtype == "MSQ":
        parts = [p for p in re.split(r"[\s,|+/]+", s) if p]
        nums: list[str] = []
        for p in parts:
            if len(p) == 1 and p.isalpha():
                nums.append(str(ord(p.upper()) - ord("A") + 1))
            else:
                nums.append(p)
        return json.dumps(nums, ensure_ascii=False, separators=(",", ":"))
    if len(s) == 1 and s.isalpha():
        return s.upper()
    return s


def _normalize_type(q: dict[str, Any]) -> str:
    qtype = str(q.get("question_type") or q.get("type") or "MCQ").upper()
    if qtype in {"MULTIPLE_CHOICE", "MCQ"}:
        return "MCQ"
    if qtype in {"MULTIPLE_SELECT", "MSQ"}:
        return "MSQ"
    if qtype in {"NUMERICAL", "NAT", "NUMERIC"}:
        return "NAT"
    return qtype or "MCQ"


def question_to_row(
    q: dict[str, Any],
    *,
    set_name: str = "Paper Name",
    default_difficulty: str = "medium",
) -> dict[str, str]:
    qtype = _normalize_type(q)
    opts_hi = _option_list(q.get("options_hi"))
    opts_en = _option_list(q.get("options_en"))
    # Fallback: single options map → English (and Hindi if Hindi question exists)
    if not any(opts_en) and q.get("options") is not None:
        opts_en = _option_list(q.get("options"))
    if not any(opts_hi) and q.get("options_hi") is None and (q.get("question_hi") or "").strip():
        opts_hi = _option_list(q.get("options"))

    answer_raw = q.get("answer")
    if answer_raw is None:
        ca = q.get("correct_answer")
        if isinstance(ca, dict):
            answer_raw = ca.get("option") or ca.get("answer") or ca
        else:
            answer_raw = ca

    difficulty = str(
        q.get("difficulty_level") or q.get("difficulty") or default_difficulty
    ).lower()
    set_nm = str(q.get("set_name") or set_name)

    sol_hi = str(q.get("solution_hi") or "").strip()
    sol_en = str(
        q.get("solution_en") or q.get("explanation") or q.get("solution") or ""
    ).strip()
    if not sol_hi and (q.get("question_hi") or "").strip():
        sol_hi = str(q.get("solution") or "").strip()

    return {
        "question_r": str(q.get("question_r") or q.get("question_number") or ""),
        "question_hi": str(q.get("question_hi") or ""),
        "option1_hi": opts_hi[0],
        "option2_hi": opts_hi[1],
        "option3_hi": opts_hi[2],
        "option4_hi": opts_hi[3],
        "option5_hi": opts_hi[4],
        "solution_hi": _as_html_p(sol_hi),
        "question_en": str(q.get("question_en") or q.get("question") or ""),
        "option1_en": opts_en[0],
        "option2_en": opts_en[1],
        "option3_en": opts_en[2],
        "option4_en": opts_en[3],
        "option5_en": opts_en[4],
        "solution_en": _as_html_p(sol_en),
        "answer": _format_answer(answer_raw, qtype),
        "set_name": set_nm,
        "difficulty_level": difficulty or "medium",
    }


def questions_to_rows(
    questions: list[dict[str, Any]],
    *,
    set_name: str = "Paper Name",
) -> list[dict[str, str]]:
    rows = []
    for i, q in enumerate(questions, start=1):
        row = question_to_row(q, set_name=set_name)
        if not row["question_r"]:
            row["question_r"] = str(i)
        rows.append(row)
    return rows


def save_template_csv(
    questions: list[dict[str, Any]],
    path: Path,
    *,
    set_name: str = "Paper Name",
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = questions_to_rows(questions, set_name=set_name)

    def _write(target: Path) -> None:
        with target.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=CSV_HEADERS, quoting=csv.QUOTE_MINIMAL
            )
            writer.writeheader()
            for row in rows:
                writer.writerow({h: row.get(h, "") for h in CSV_HEADERS})

    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        _write(tmp)
        tmp.replace(path)
        return path
    except PermissionError:
        # Single fallback (no timestamp spam). Close Excel to get final name.
        alt = path.with_name(f"{path.stem}.checkpoint{path.suffix}")
        _write(alt)
        print(
            f"WARNING: '{path.name}' locked — wrote {alt.name}. Excel band karo.",
            flush=True,
        )
        return alt
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
