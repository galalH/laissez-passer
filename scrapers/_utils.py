"""Shared utilities for scrapers."""

import io
import re as _re
from markitdown import MarkItDown

_md = MarkItDown()


def html_to_md(html: str | None) -> str | None:
    """Convert an HTML string or fragment to Markdown. Returns None if empty."""
    if not html:
        return None
    try:
        result = _md.convert_stream(
            io.BytesIO(html.encode("utf-8", errors="replace")),
            file_extension=".html",
        )
        text = result.text_content.strip()
        return text or None
    except Exception:
        return None


def pdf_to_md(data: bytes) -> str | None:
    """Convert PDF bytes to Markdown. Returns None if empty or on error."""
    try:
        result = _md.convert_stream(io.BytesIO(data), file_extension=".pdf")
        text = result.text_content.strip()
        return text or None
    except Exception:
        return None


def _find(text: str, sentinel) -> tuple[int, int] | None:
    """Return (start, end) of the first occurrence of sentinel in text.

    sentinel can be:
      - str: exact substring match
      - re.Pattern: regex search
      - list of str/re.Pattern: returns the earliest match across all items
    """
    if isinstance(sentinel, list):
        results = [_find(text, s) for s in sentinel]
        valid = [r for r in results if r is not None]
        return min(valid, key=lambda r: r[0]) if valid else None
    if isinstance(sentinel, _re.Pattern):
        m = sentinel.search(text)
        return (m.start(), m.end()) if m else None
    idx = text.find(sentinel)
    return (idx, idx + len(sentinel)) if idx >= 0 else None


def trim(
    text: str | None,
    start=None,
    before=None,
    after=None,
) -> str | None:
    """Strip leading and/or trailing boilerplate from a description.

    start:  keep from the first occurrence of this sentinel onward (inclusive).
            Use this when the sentinel IS the first line of real content.
    before: strip everything up to and including this sentinel (exclusive keep).
            Use this when the sentinel is the last line of the preamble.
    after:  strip this sentinel and everything following it.
            Use this when the sentinel marks the start of the footer.

    Each sentinel can be a plain str, a compiled re.Pattern, or a list of
    either — lists pick the earliest match in the text.
    """
    if not text:
        return text
    if start is not None:
        pos = _find(text, start)
        if pos:
            text = text[pos[0]:]
    if before is not None:
        pos = _find(text, before)
        if pos:
            text = text[pos[1]:]
    if after is not None:
        pos = _find(text, after)
        if pos:
            text = text[:pos[0]]
    return text.strip() or None
