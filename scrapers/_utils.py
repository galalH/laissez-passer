"""Shared utilities for scrapers."""

import io
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


def trim(text: str | None, before: str | None = None, after: str | None = None) -> str | None:
    """Strip leading and/or trailing boilerplate from a description.

    before: strip everything up to and including this sentinel (header trim)
    after:  strip this sentinel and everything following it (footer trim)
    """
    if not text:
        return text
    if before and before in text:
        text = text.split(before, 1)[1]
    if after and after in text:
        text = text.split(after, 1)[0]
    return text.strip() or None
