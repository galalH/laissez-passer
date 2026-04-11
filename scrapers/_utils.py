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
