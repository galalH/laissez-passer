"""UNFCCC (UN Framework Convention on Climate Change) Job Scraper."""

import re
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from scrapers._utils import pdf_to_md, trim

AGENCY = "UNFCCC"
AGENCY_NAME = "United Nations Framework Convention on Climate Change"
JOBS_URL = "https://unfccc.int/secretariat/employment/recruitment"

_MONTH_MAP = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}

_SKIP_HEADINGS = re.compile(
    r"general service categor|professional and managerial categor",
    re.IGNORECASE,
)


def _parse_deadline(date_range: str) -> str | None:
    """Extract closing date from a range like '27 Mar - 12 Apr' → 'YYYY-MM-DD'.
    Also handles long form: '22 Nov 2024 - 21 Dec 2024'.
    """
    if not date_range:
        return None
    parts = date_range.split(" - ")
    date_str = parts[-1].strip()
    m = re.match(r"(\d{1,2})\s+([A-Za-z]{3})(?:\s+(\d{4}))?", date_str)
    if not m:
        return None
    day = m.group(1).zfill(2)
    month = _MONTH_MAP.get(m.group(2).lower())
    if not month:
        return None
    if m.group(3):
        year = int(m.group(3))
    else:
        year = datetime.now().year
        if int(month) < datetime.now().month:
            year += 1
    return f"{year}-{month}-{day}"


_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def _fetch_description(cookies: dict, url: str) -> str | None:
    """Download the job PDF (identified by URL path or Content-Type) and extract its text.
    Each call creates its own session to avoid thread-safety issues. Cookies are applied
    without domain restriction so they reach the file-storage host too.
    """
    try:
        session = requests.Session()
        session.headers.update(_HEADERS)
        session.cookies.update(cookies)
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        ct = resp.headers.get("Content-Type", "")
        if "pdf" not in ct.lower() and ".pdf" not in url.split("?")[0].lower():
            return None
        return trim(pdf_to_md(resp.content), start="Where you will be working", after="What is the selection process?")
    except Exception:
        return None


def scrape() -> list[dict]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(JOBS_URL, wait_until="networkidle", timeout=60_000)
            html = page.content()
            cookies = page.context.cookies()
        finally:
            browser.close()

    # Extract cookies as a plain dict; passed to each worker thread which builds
    # its own session (requests.Session is not thread-safe for concurrent use).
    # No domain restriction so cookies also reach the CDN/file-storage host.
    cookie_dict = {c["name"]: c["value"] for c in cookies}

    soup = BeautifulSoup(html, "html.parser")
    stubs = []

    for table in soup.find_all("table"):
        heading = ""
        for tag in table.find_all_previous(["h2", "h3", "h4"]):
            heading = tag.get_text(strip=True)
            break

        if _SKIP_HEADINGS.search(heading):
            continue

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) != 6:
                continue

            if "apply" not in cells[5].get_text(strip=True).lower():
                continue

            title_tag = cells[0].find("a")
            if not title_tag:
                continue
            job_title = title_tag.get_text(strip=True).rstrip("»").strip()
            if not job_title:
                continue

            href = title_tag.get("href", "")
            job_url = ("https://unfccc.int" + href) if href.startswith("/") else JOBS_URL

            grade_raw = cells[1].get_text(strip=True)
            grade = None if grade_raw.upper() in ("N/A", "") else grade_raw

            deadline = _parse_deadline(cells[3].get_text(strip=True))

            stubs.append({
                "agency": AGENCY, "agency_name": AGENCY_NAME,
                "job_title": job_title, "grade": grade,
                "city": "Bonn", "country": "Germany",
                "deadline": deadline, "url": job_url,
            })

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [(s, ex.submit(_fetch_description, cookie_dict, s["url"])) for s in stubs]

    return [{**stub, "description": fut.result()} for stub, fut in futures]


if __name__ == "__main__":
    import json
    print(json.dumps(scrape(), indent=2))
