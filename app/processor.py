"""Read PDF / images — lazy page render, reusable PDF handle."""

from __future__ import annotations

import base64
import io
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SUPPORTED_IMAGES = {".png", ".jpg", ".jpeg", ".webp"}
SUPPORTED_DOCS = {".pdf"}
SUPPORTED = SUPPORTED_IMAGES | SUPPORTED_DOCS


@dataclass
class PageContent:
    page_index: int
    text: str = ""
    image_b64: str | None = None
    mime: str = "image/jpeg"
    is_image_heavy: bool = False


@dataclass
class DocumentInput:
    path: Path
    source_type: str
    page_count: int = 0
    force_images: bool = False
    pages: list[PageContent] = field(default_factory=list)
    _pdf: Any = field(default=None, repr=False, compare=False)

    def close(self) -> None:
        if self._pdf is not None:
            try:
                self._pdf.close()
            except Exception:
                pass
            self._pdf = None
        self.pages.clear()

    def __enter__(self) -> DocumentInput:
        return self

    def __exit__(self, *_) -> None:
        self.close()


def validate_file(path: str | Path) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    if not p.is_file():
        raise ValueError(f"Not a file: {p}")
    if p.suffix.lower() not in SUPPORTED:
        raise ValueError(
            f"Unsupported format: {p.suffix}. Allowed: {', '.join(sorted(SUPPORTED))}"
        )
    return p


def _pil_to_jpeg_b64(img, *, max_side: int = 1600, quality: int = 80) -> tuple[str, str]:
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    scale = min(1.0, max_side / max(w, h))
    if scale < 1.0:
        from PIL import Image

        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"


def _image_file_to_b64(path: Path, max_side: int = 1600) -> tuple[str, str]:
    from PIL import Image

    with Image.open(path) as im:
        return _pil_to_jpeg_b64(im, max_side=max_side)


def _pdf_page_to_b64(page, max_side: int = 1600) -> tuple[str, str]:
    import pymupdf
    from PIL import Image

    zoom = 110 / 72
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    # Free pixmap buffer ASAP
    del pix
    return _pil_to_jpeg_b64(img, max_side=max_side)


def load_document(path: str | Path, *, force_images: bool = False) -> DocumentInput:
    p = validate_file(path)
    suffix = p.suffix.lower()

    if suffix in SUPPORTED_IMAGES:
        b64, mime = _image_file_to_b64(p)
        return DocumentInput(
            path=p,
            source_type="image",
            page_count=1,
            force_images=True,
            pages=[
                PageContent(page_index=0, image_b64=b64, mime=mime, is_image_heavy=True)
            ],
        )

    import pymupdf

    pdf = pymupdf.open(p)
    return DocumentInput(
        path=p,
        source_type="pdf",
        page_count=pdf.page_count,
        force_images=force_images,
        _pdf=pdf,
    )


def get_page(document: DocumentInput, page_index: int) -> PageContent:
    if document.source_type == "image":
        return document.pages[page_index]

    if document._pdf is None:
        import pymupdf

        document._pdf = pymupdf.open(document.path)

    page = document._pdf[page_index]
    text = (page.get_text("text") or "").strip()
    scanned = document.force_images or len(text) < 40
    if scanned:
        b64, mime = _pdf_page_to_b64(page)
        return PageContent(
            page_index=page_index,
            text=text,
            image_b64=b64,
            mime=mime,
            is_image_heavy=True,
        )
    return PageContent(page_index=page_index, text=text, is_image_heavy=False)
