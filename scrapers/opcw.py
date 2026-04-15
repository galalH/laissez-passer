"""OPCW Job Scraper - uses TalentSoft ATS HTML parsing."""

import re
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

from scrapers._utils import html_to_md, trim

AGENCY = "OPCW"
AGENCY_NAME = "Organisation for the Prohibition of Chemical Weapons"
JOBS_URL = "https://jobs.opcw.org/job/list-of-all-jobs.aspx?all=1&mode=layer"
BASE_URL = "https://jobs.opcw.org"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _fetch_description(session: requests.Session, job_url: str) -> tuple[str | None, str | None]:
    try:
        resp = session.get(job_url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        pubdate = None
        meta_desc = soup.find("meta", {"name": "Description"})
        if meta_desc:
            m = re.search(r"Date:\s*(\d{1,2}/\d{1,2}/\d{4})", meta_desc.get("content", ""))
            if m:
                day, month, year = m.group(1).split("/")
                pubdate = f"{year}-{month.zfill(2)}-{day.zfill(2)}"

        description = None
        details = soup.find("div", class_="ts-offer-page__content-details")
        if details:
            span = details.find("span")
            if span:
                description = trim(html_to_md(str(span)), start="### Job Summary", after="Additional Information")

        return description, pubdate
    except Exception:
        pass
    return None, None


def _extract_grade(job_title):
    """Extract grade from job title using regex pattern like (P3), (GS-6), etc."""
    match = re.search(r"\(([A-Z]{1,2}-?\d+)\)", job_title)
    return match.group(1) if match else None


def _parse_deadline(deadline_str):
    """Convert deadline from DD/MM/YYYY format to YYYY-MM-DD format."""
    if not deadline_str:
        return None
    try:
        from dateutil import parser as dateutil_parser
        return dateutil_parser.parse(deadline_str.strip(), dayfirst=True).strftime("%Y-%m-%d")
    except Exception:
        return deadline_str


def scrape() -> list[dict]:
    """Scrape jobs from OPCW careers portal."""
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        response = session.get(JOBS_URL, timeout=30)
        response.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(response.text, "html.parser")

    stubs = []

    for card in soup.find_all("div", class_="ts-offer-card"):
        try:
            title_link = card.select_one("h3.ts-offer-card__title > a.ts-offer-card__title-link")
            if not title_link:
                continue

            job_title = title_link.get_text(strip=True)
            href = title_link.get("href", "").strip()
            if not job_title or not href:
                continue

            job_url = (BASE_URL + href) if href.startswith("/") else href
            grade = _extract_grade(job_title)

            content_list = card.select_one("div.ts-offer-card-content > ul.ts-offer-card-content__list")
            list_items = [li.get_text(strip=True) for li in content_list.find_all("li")] if content_list else []
            deadline = _parse_deadline(list_items[1]) if len(list_items) > 1 else None

            stubs.append({
                "agency": AGENCY, "agency_name": AGENCY_NAME,
                "job_title": job_title, "grade": grade,
                "city": "The Hague", "country": "Netherlands",
                "deadline": deadline, "url": job_url,
            })
        except Exception:
            continue

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [(s, ex.submit(_fetch_description, session, s["url"])) for s in stubs]

    results = []
    for stub, fut in futures:
        description, pubdate = fut.result()
        results.append({**stub, "pubdate": pubdate, "description": description})
    return results


if __name__ == "__main__":
    import json
    print(json.dumps(scrape()))
