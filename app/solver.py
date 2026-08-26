"""AI calls via local_chatgpt — output matches examples CSV template fields."""

from __future__ import annotations

import json
import re
from typing import Any

from openai import AuthenticationError

from . import auth as auth_layer
from .processor import PageContent

SYSTEM_SOLVE = """You are an expert bilingual (Hindi + English) exam question extractor and solver.

From the given page (image and/or text), extract EVERY distinct question.

Return ONLY valid JSON:
{
  "questions": [
    {
      "question_r": 1,
      "question_type": "MCQ",
      "question_hi": "...",
      "options_hi": {"1":"...","2":"...","3":"...","4":"...","5":""},
      "solution_hi": "step by step in Hindi",
      "question_en": "...",
      "options_en": {"1":"...","2":"...","3":"...","4":"...","5":""},
      "solution_en": "step by step in English",
      "answer": "D",
      "difficulty_level": "medium",
      "confidence": 0.9
    }
  ]
}

question_type must be one of: MCQ | MSQ | NAT

answer format (STRICT):
- MCQ: single letter "A"|"B"|"C"|"D"|"E"  (preferred) OR single option number "1".."5"
- MSQ: JSON array of option NUMBERS as strings, e.g. ["3","4"]
- NAT: JSON object {"start":"86","end":"86"} (same value if exact)

Rules:
- Never merge multiple questions into one.
- Fill Hindi fields when Hindi is present on the page; otherwise leave Hindi empty and fill English.
- If only one language is on the page, still provide a clear English translation in question_en / options_en / solution_en when possible.
- option5 may be empty when only 4 options exist.
- Do not invent options that are not on the page.
- Solve carefully; if unsure set confidence < 0.6 but still give best answer.
- Output JSON only. No markdown fences."""


def _default_model() -> str:
    if auth_layer.using_oauth_backend():
        return "gpt-5.4-mini"
    return "gpt-4o-mini"


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise
        return json.loads(m.group(0))


def _responses_input_for_page(page: PageContent, page_label: str) -> list[dict]:
    content: list[dict] = [
        {
            "type": "input_text",
            "text": (
                f"{page_label}\n"
                "Extract and solve all questions on this page. "
                "Return JSON matching the bilingual exam CSV schema."
            ),
        }
    ]
    if page.text:
        content.append(
            {
                "type": "input_text",
                "text": f"Extracted text:\n{page.text[:12000]}",
            }
        )
    if page.image_b64:
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:{page.mime};base64,{page.image_b64}",
            }
        )
    return [{"role": "user", "content": content}]


def _chat_messages_for_page(page: PageContent, page_label: str) -> list[dict]:
    parts: list[dict] = [
        {
            "type": "text",
            "text": (
                f"{page_label}\n"
                "Extract and solve all questions on this page. "
                "Return JSON matching the bilingual exam CSV schema."
            ),
        }
    ]
    if page.text:
        parts.append({"type": "text", "text": f"Extracted text:\n{page.text[:12000]}"})
    if page.image_b64:
        parts.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{page.mime};base64,{page.image_b64}",
                },
            }
        )
    return [
        {"role": "system", "content": SYSTEM_SOLVE},
        {"role": "user", "content": parts},
    ]


class AISolver:
    def __init__(self, *, model: str | None = None):
        auth_layer.ensure_auth()
        self.model = model or _default_model()
        self.oauth = auth_layer.using_oauth_backend()
        self.client = auth_layer.make_openai_client()

    def _refresh(self) -> None:
        from local_chatgpt.auth import AuthManager

        am = AuthManager()
        if am.has_oauth:
            am.refresh()
        self.client = auth_layer.make_openai_client()

    def solve_page(self, page: PageContent, *, page_number: int) -> list[dict]:
        label = f"Page {page_number}"
        try:
            raw = self._call(page, label)
        except AuthenticationError:
            self._refresh()
            raw = self._call(page, label)

        data = _extract_json(raw)
        questions = data.get("questions")
        if questions is None and isinstance(data, dict) and (
            "question_en" in data or "question" in data or "question_hi" in data
        ):
            questions = [data]
        if not isinstance(questions, list):
            return []
        return [q for q in questions if isinstance(q, dict)]

    def _call(self, page: PageContent, page_label: str) -> str:
        if self.oauth:
            parts: list[str] = []
            with self.client.responses.create(
                model=self.model,
                instructions=SYSTEM_SOLVE,
                input=_responses_input_for_page(page, page_label),
                store=False,
                stream=True,
            ) as stream:
                for event in stream:
                    et = getattr(event, "type", None)
                    if et == "response.output_text.delta":
                        parts.append(getattr(event, "delta", "") or "")
                    elif et == "response.completed":
                        resp = getattr(event, "response", None)
                        if resp is not None:
                            text = getattr(resp, "output_text", None)
                            if text:
                                return text
            return "".join(parts)

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=_chat_messages_for_page(page, page_label),
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        return resp.choices[0].message.content or "{}"
