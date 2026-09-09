from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt"}


@dataclass(frozen=True)
class NormalizedDocument:
    filename: str
    text: str
    headings: tuple[tuple[int, str, int], ...]


def validate_filename(filename: str) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"unsupported BRD format '{suffix or '<none>'}'; supported formats: {supported}")


def parse_document(filename: str, content: bytes) -> NormalizedDocument:
    validate_filename(filename)
    if not content or not content.strip():
        raise ValueError("the uploaded BRD is empty")
    try:
        text = content.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError as exc:
        raise ValueError("the uploaded BRD must be valid UTF-8 text") from exc
    if not text.strip():
        raise ValueError("the uploaded BRD is empty")
    headings = tuple(
        (len(match.group(1)), match.group(2).strip(), index)
        for index, line in enumerate(text.splitlines(), start=1)
        if (match := re.match(r"^(#{1,6})\s+(.+?)\s*$", line))
    )
    return NormalizedDocument(filename=Path(filename).name, text=text, headings=headings)


def heading_for_line(document: NormalizedDocument, line_number: int) -> tuple[str | None, str | None]:
    current: tuple[str | None, str | None] = (None, None)
    for level, title, line in document.headings:
        if line > line_number:
            break
        if level <= 3:
            current = (str(line), title)
    return current
