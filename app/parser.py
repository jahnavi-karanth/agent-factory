from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Optional, Tuple


SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".pdf", ".docx", ".pptx", ".xlsx"}


@dataclass(frozen=True)
class NormalizedDocument:
    filename: str
    text: str
    headings: Tuple[Tuple[int, str, int], ...]


def validate_filename(filename: str) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"unsupported BRD format '{suffix or '<none>'}'; supported formats: {supported}")


def parse_document(filename: str, content: bytes) -> NormalizedDocument:
    validate_filename(filename)
    if not content or not content.strip():
        raise ValueError("the uploaded BRD is empty")
    suffix = Path(filename).suffix.lower()
    if suffix in {".md", ".markdown", ".txt"}:
        try:
            text = content.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError as exc:
            raise ValueError("the uploaded BRD must be valid UTF-8 text") from exc
    else:
        try:
            text = _extract_office_text(suffix, content)
        except Exception as exc:
            raise ValueError(f"unsupported BRD format or invalid {suffix} document: {exc}") from exc
    if not text.strip():
        raise ValueError("the uploaded BRD is empty")
    headings = tuple(
        (len(match.group(1)), match.group(2).strip(), index)
        for index, line in enumerate(text.splitlines(), start=1)
        if (match := re.match(r"^(#{1,6})\s+(.+?)\s*$", line))
    )
    return NormalizedDocument(filename=Path(filename).name, text=text, headings=headings)


def _extract_office_text(suffix: str, content: bytes) -> str:
    """Extract logical text from supported binary document formats."""
    import io
    if suffix == ".pdf":
        from pypdf import PdfReader
        return "\n\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages).strip()
    if suffix == ".docx":
        from docx import Document
        return "\n".join(paragraph.text for paragraph in Document(io.BytesIO(content)).paragraphs if paragraph.text.strip()).strip()
    if suffix == ".pptx":
        from pptx import Presentation
        presentation = Presentation(io.BytesIO(content))
        return "\n\n".join(shape.text for slide in presentation.slides for shape in slide.shapes if hasattr(shape, "text") and shape.text.strip()).strip()
    if suffix == ".xlsx":
        from openpyxl import load_workbook
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        rows = []
        for sheet in workbook.worksheets:
            rows.append(f"# Sheet: {sheet.title}")
            rows.extend(" | ".join("" if value is None else str(value) for value in row) for row in sheet.iter_rows(values_only=True))
        return "\n".join(rows).strip()
    raise ValueError(f"unsupported BRD format '{suffix}'")


def heading_for_line(document: NormalizedDocument, line_number: int) -> Tuple[Optional[str], Optional[str]]:
    current: Tuple[Optional[str], Optional[str]] = (None, None)
    for level, title, line in document.headings:
        if line > line_number:
            break
        if level <= 3:
            current = (str(line), title)
    return current
