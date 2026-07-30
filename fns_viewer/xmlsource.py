"""Reading the multi-gigabyte export.

Nothing here loads the whole file. The indexer streams it through mmap once, and
individual documents are read back by byte offset when someone opens them.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET

from .config import XML

START_TAG = re.compile(rb"<tp\s+([^>]*?)>")
ATTRIBUTE = re.compile(rb'''([:\w.-]+)\s*=\s*(["'])(.*?)\2''', re.DOTALL)


def attrs(raw: bytes) -> dict[str, str]:
    # This export's List section contains a few legacy values that are not
    # strict XML, so parse quoted attributes directly for indexing. ElementTree
    # is still used for the individual document fragment when it is opened.
    return {m.group(1).decode('ascii'): html.unescape(m.group(3).decode('utf-8', 'replace'))
            for m in ATTRIBUTE.finditer(raw)}


def object_group(text: str) -> tuple[str, str]:
    """Split an object of taxation into its group and the qualifying detail.

    Many objects repeat one group with different limits, for example
    "Гидроциклы … (с каждой лошадиной силы): Свыше 100 л.с.", so rates can be
    ranked by group instead of arriving in the order the region typed them.
    """
    text = ' '.join(str(text or '').split())
    head, separator, tail = text.partition(':')
    if separator and head.strip():
        return head.strip(), tail.strip()
    return text, ''


def number(text) -> float | None:
    try:
        return float(str(text).replace(',', '.'))
    except (TypeError, ValueError):
        return None


def source_stamp() -> str:
    stat = XML.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def fetch_record(offset: int) -> ET.Element:
    with XML.open("rb") as fh:
        fh.seek(offset)
        parts: list[bytes] = []
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                raise ValueError("Неожиданный конец XML-файла")
            parts.append(chunk)
            joined = b"".join(parts)
            end = joined.find(b"</tp>")
            if end != -1:
                return ET.fromstring(joined[:end + 5])
