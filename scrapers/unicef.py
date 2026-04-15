"""UNICEF Job Scraper - uses PageUp RSS feed."""

import re
import requests
import xml.etree.ElementTree as ET
from dateutil import parser as dateutil_parser

from scrapers._utils import html_to_md, trim

AGENCY = "UNICEF"
AGENCY_NAME = "United Nations Children's Fund"
RSS_URL = "https://careers.pageuppeople.com/671/cw/en/rss"
JOB_BASE = "https://jobs.unicef.org/en-us/job/"

JOB_NS = "http://pageuppeople.com/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

GRADE_RE = re.compile(
    r'\b(GS-?\d+|G-?\d|P-?\d|D-?\d|FS-?\d|SB-?\d|SC-?\d|L-?\d|NO[-\s]?[A-Ea-e]|NO[-\s]?\d)\b',
    re.IGNORECASE,
)


def _parse_closing_date(date_str: str) -> str | None:
    """Convert RSS date like 'Wed, 01 Apr 2026 18:55:00 GMT' to YYYY-MM-DD."""
    if not date_str:
        return None
    try:
        return dateutil_parser.parse(date_str).strftime("%Y-%m-%d")
    except Exception:
        return None


def _parse_location(location_str: str) -> tuple[str | None, str | None]:
    """Parse 'Eastern and Southern Africa Region|Uganda' → (None, 'Uganda')."""
    if not location_str:
        return None, None
    parts = location_str.split("|")
    country = parts[-1].strip() or None
    return None, country  # city not available in feed


def scrape() -> list[dict]:
    try:
        resp = requests.get(RSS_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception:
        return []

    root = ET.fromstring(resp.content)
    jobs = []

    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue

        ref_no = item.findtext(f"{{{JOB_NS}}}refNo") or ""
        url = f"{JOB_BASE}{ref_no}" if ref_no else (item.findtext("link") or "")

        location_str = item.findtext(f"{{{JOB_NS}}}location") or ""
        city, country = _parse_location(location_str)

        closing = item.findtext(f"{{{JOB_NS}}}closingDate") or ""
        deadline = _parse_closing_date(closing)

        pubdate = _parse_closing_date(item.findtext("pubDate") or "")

        grade_m = GRADE_RE.search(title)
        grade = re.sub(r'\s+', '-', grade_m.group(1).upper()) if grade_m else None

        html_desc = item.findtext(f"{{{JOB_NS}}}description") or ""
        description = html_to_md(html_desc)
        # Pass 1: strip long multilingual preambles
        if description:
            description = trim(description,
                before=[
                    "to learn more about what we do at UNICEF.\n",
                    "pour en savoir plus sur nos actions à l'UNICEF.\n",
                    "¡Y nunca nos rendimos!\n\n",
                ])
        # Pass 2: strip bold category headers and multilingual footers
        if description:
            description = trim(description,
                before=[
                    re.compile(r"\**\s*TERMS OF REFERENCE\**"),
                    re.compile(r"\**\s*For every child,[^\n]*\**"),
                ],
                after=[
                    re.compile(r"\**\s*(?:For every Child, you demonstrate|Pour chaque enfant, vous démontrez|Para cada (?:infancia, demuestras|niño y niña, tú demuestras))"),
                    "UNICEF will not ask for applicants' bank account information",
                ]
            )

        jobs.append({
            "agency": AGENCY,
            "agency_name": AGENCY_NAME,
            "job_title": title,
            "grade": grade,
            "city": city,
            "country": country,
            "deadline": deadline,
            "pubdate": pubdate,
            "url": url,
            "description": description,
        })

    return jobs


if __name__ == "__main__":
    import json
    print(json.dumps(scrape()))
