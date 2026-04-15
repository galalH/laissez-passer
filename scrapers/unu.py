"""UNU (United Nations University) Job Scraper - uses Recruitee public API."""

import requests
import re
import json
import warnings
from dateutil import parser as dateutil_parser
from dateutil.parser import UnknownTimezoneWarning

from bs4 import BeautifulSoup
from scrapers._utils import html_to_md

AGENCY = "UNU"
AGENCY_NAME = "United Nations University"
JOBS_URL = "https://careers.unu.edu"
API_URL = "https://careers.unu.edu/api/offers"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

GRADE_RE = re.compile(r'\b((?:PSA|P|NO[ABCD]?|GS|D|L|FS|SB|SC|CTC|ICS)-?\d+)\b')


def _deadline_from_requirements(html: str) -> str | None:
    """Extract deadline date from the requirements HTML field.

    Looks for 'Application Deadline' then takes the first text node after
    the following HTML tags and parses it with dateutil fuzzy mode (to
    tolerate trailing time/timezone noise like '12pm NY time').
    Returns None when no parseable date is found (e.g. 'open').
    """
    if not html:
        return None
    m = re.search(r'Application Deadline[^<]*(?:<[^>]+>)*([^<]+)', html, re.IGNORECASE)
    if not m:
        return None
    text = m.group(1).strip()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UnknownTimezoneWarning)
            return dateutil_parser.parse(text, fuzzy=True).strftime("%Y-%m-%d")
    except Exception:
        return None


def scrape() -> list[dict]:
    try:
        resp = requests.get(API_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        offers = resp.json().get("offers", [])
    except Exception:
        return []

    jobs = []
    for o in offers:
        title = o.get("title") or ""
        if not title:
            continue

        url = o.get("careers_url") or JOBS_URL
        city = o.get("city") or None
        country = o.get("country") or None

        close_at = o.get("close_at")
        if close_at:
            deadline = close_at[:10]
        else:
            deadline = _deadline_from_requirements(o.get("requirements") or "")

        m = GRADE_RE.search(title)
        grade = m.group(1) if m else None

        html_desc = o.get("description") or ""
        soup = BeautifulSoup(html_desc, "html.parser")
        h3s = soup.find_all("h3")
        if len(h3s) >= 3:
            third_h3 = h3s[2]
            html_desc = str(third_h3) + "".join(str(s) for s in third_h3.next_siblings)
        description = html_to_md(html_desc)

        pubdate = (o.get("published_at") or "")[:10] or None

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
    print(json.dumps(scrape()))
