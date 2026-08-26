"""JSON schema + validation for solved question papers."""

from __future__ import annotations

from typing import Any

QUESTION_TYPES = {
    "multiple_choice",
    "true_false",
    "short_answer",
    "numerical",
    "other",
    "mcq",
    "msq",
    "nat",
}


def empty_document(source_file: str, source_type: str, title: str = "Question Paper") -> dict:
    return {
        "document": {
            "title": title,
            "source_file": source_file,
            "source_type": source_type,
            "total_questions": 0,
        },
        "questions": [],
    }


def _options_from_bilingual(raw: dict[str, Any]) -> dict[str, str]:
    letters = ["A", "B", "C", "D", "E"]
    out: dict[str, str] = {}

    def from_map(m: Any) -> None:
        if not isinstance(m, dict):
            return
        for i, L in enumerate(letters, start=1):
            val = m.get(str(i)) or m.get(L) or m.get(L.lower())
            if val is not None and str(val).strip():
                out[L] = str(val).strip()

    from_map(raw.get("options_en"))
    if len(out) < 2:
        from_map(raw.get("options_hi"))
    if len(out) < 2:
        from_map(raw.get("options"))

    # already option1_en style
    if len(out) < 2:
        for i, L in enumerate(letters, start=1):
            val = raw.get(f"option{i}_en") or raw.get(f"option{i}_hi") or raw.get(f"option{i}")
            if val is not None and str(val).strip():
                out[L] = str(val).strip()
    return out


def normalize_question(raw: dict[str, Any], index: int = 0) -> dict[str, Any]:
    """Normalize one AI question object into schema shape + review flags."""
    qnum = raw.get("question_r") or raw.get("question_number")
    try:
        qnum = int(qnum) if qnum is not None else index + 1
    except (TypeError, ValueError):
        qnum = index + 1

    options = _options_from_bilingual(raw)

    # legacy list options
    if not options and isinstance(raw.get("options"), list):
        converted = {}
        for item in raw["options"]:
            s = str(item).strip()
            if len(s) >= 2 and s[0].isalpha() and s[1] in ".)":
                converted[s[0].upper()] = s[2:].strip(" .)")
            else:
                converted[chr(ord("A") + len(converted))] = s
        options = converted

    answer_raw = raw.get("answer")
    ca = raw.get("correct_answer") or {}
    if answer_raw is None:
        if isinstance(ca, str):
            answer_raw = ca
        elif isinstance(ca, dict):
            answer_raw = ca.get("option") or ca.get("answer")

    option_letter = ""
    answer_text = ""
    if isinstance(answer_raw, str):
        s = answer_raw.strip()
        if len(s) == 1 and s.isalpha():
            option_letter = s.upper()
        else:
            answer_text = s
            if len(s) >= 1 and s[0].isalpha() and s[0].upper() in options:
                option_letter = s[0].upper()
    elif isinstance(answer_raw, dict):
        answer_text = str(answer_raw)
    elif isinstance(answer_raw, list):
        answer_text = str(answer_raw)

    if option_letter and not answer_text and option_letter in options:
        answer_text = options[option_letter]

    qtype = str(raw.get("question_type") or "multiple_choice").strip().lower()
    if qtype in {"mcq", "multiple_choice"}:
        qtype = "multiple_choice"
    elif qtype not in QUESTION_TYPES:
        qtype = "other"

    try:
        confidence = float(raw.get("confidence", 0.85))
    except (TypeError, ValueError):
        confidence = 0.85
    confidence = max(0.0, min(1.0, confidence))

    question_text = str(
        raw.get("question_en")
        or raw.get("question")
        or raw.get("question_hi")
        or ""
    ).strip()
    solution = str(
        raw.get("solution_en")
        or raw.get("solution")
        or raw.get("solution_hi")
        or ""
    ).strip()
    explanation = str(
        raw.get("explanation")
        or raw.get("solution_en")
        or raw.get("solution_hi")
        or ""
    ).strip()

    status = "ok"
    warnings: list[str] = []

    if not question_text:
        status = "needs_review"
        warnings.append("empty_question")
    if qtype == "multiple_choice" and len(options) < 2:
        status = "needs_review"
        warnings.append("missing_options")
    if not option_letter and not answer_text:
        status = "needs_review"
        warnings.append("missing_answer")
    if option_letter and options and option_letter not in options:
        status = "needs_review"
        warnings.append("answer_not_in_options")
    if not solution:
        status = "needs_review"
        warnings.append("empty_solution")
    if confidence < 0.6:
        status = "needs_review"
        warnings.append("low_confidence")

    out: dict[str, Any] = {
        "question_number": qnum,
        "question_type": qtype,
        "question": question_text,
        "question_hi": str(raw.get("question_hi") or ""),
        "question_en": str(raw.get("question_en") or question_text),
        "options": options,
        "options_hi": raw.get("options_hi") or {},
        "options_en": raw.get("options_en") or {},
        "correct_answer": {"option": option_letter, "answer": answer_text},
        "answer": raw.get("answer") if raw.get("answer") is not None else option_letter,
        "solution": solution,
        "solution_hi": str(raw.get("solution_hi") or ""),
        "solution_en": str(raw.get("solution_en") or solution),
        "explanation": explanation,
        "confidence": confidence,
        "status": status,
        "difficulty_level": str(raw.get("difficulty_level") or "medium"),
        "set_name": str(raw.get("set_name") or ""),
    }
    if warnings:
        out["warnings"] = warnings
    if raw.get("has_diagram"):
        out["has_diagram"] = True
        out["diagram_description"] = str(raw.get("diagram_description") or "")
    return out


def validate_document(doc: dict[str, Any]) -> dict[str, Any]:
    questions = doc.get("questions") or []
    normalized = [normalize_question(q, i) for i, q in enumerate(questions)]
    normalized.sort(key=lambda q: q.get("question_number") or 0)
    meta = dict(doc.get("document") or {})
    meta["total_questions"] = len(normalized)
    return {"document": meta, "questions": normalized}


def processing_report(doc: dict[str, Any]) -> dict[str, Any]:
    qs = doc.get("questions") or []
    needs = [q for q in qs if q.get("status") == "needs_review"]
    return {
        "total_questions": len(qs),
        "solved_ok": len(qs) - len(needs),
        "needs_review": len(needs),
        "review_question_numbers": [q.get("question_number") for q in needs],
    }
