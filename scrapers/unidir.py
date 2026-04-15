"""UNIDIR Job Scraper - parses the join-our-team page."""

import requests
from bs4 import BeautifulSoup
import json
from dateutil import parser as dateutil_parser
from concurrent.futures import ThreadPoolExecutor

from scrapers._utils import html_to_md

AGENCY = "UNIDIR"
AGENCY_NAME = "United Nations Institute for Disarmament Research"
JOBS_URL = "https://unidir.org/who-we-are/join-our-team/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def _parse_deadline(s: str | None) -> str | None:
    """Parse deadline string to YYYY-MM-DD format.

    Supports:
    - "DD Month YYYY" (e.g. "31 March 2026")
    - "DD Mon YYYY" (e.g. "31 Mar 2026")
    - Already YYYY-MM-DD format
    - Returns None if parsing fails
    """
    if not s:
        return None

    s = s.strip()

    try:
        return dateutil_parser.parse(s, dayfirst=True).strftime("%Y-%m-%d")
    except Exception:
        return None


def _split_location(s: str | None) -> tuple[str | None, str | None]:
    """Split location string into city and country.

    Splits on the last comma: city=before, country=after.
    If no comma: city=value, country=None.
    """
    if not s:
        return None, None

    s = s.strip()

    if ',' not in s:
        return s, None

    # Split on last comma
    parts = s.rsplit(',', 1)
    city = parts[0].strip()
    country = parts[1].strip()

    return city, country


def _fetch_description(session: requests.Session, url: str) -> tuple[str | None, str | None]:
    try:
        resp = session.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
        pubdate = None
        tag = soup.find("meta", property="article:published_time")
        if tag:
            raw = tag.get("content", "")
            pubdate = raw[:10] if raw else None
        content = soup.find("div", class_="post-content")
        return html_to_md(str(content)) if content else None, pubdate
    except Exception:
        return None, None


def scrape() -> list[dict]:
    session = requests.Session()
    try:
        resp = session.get(JOBS_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(resp.content, "html.parser")
    job_list_section = soup.find("section", class_="job-list")
    if not job_list_section:
        return []

    if job_list_section.find("div", class_="job-list__empty"):
        return []

    stubs = []
    for item in job_list_section.find_all("li", class_="job-table__item"):
        try:
            a = item.find("a", class_="job-table__item-link")
            if not a:
                continue

            title_el = item.find("span", class_="job-table__item-title")
            job_title = title_el.get_text(strip=True) if title_el else None
            if not job_title:
                continue

            location_el = item.find("span", class_="job-table__item-location")
            location = location_el.get_text(strip=True) if location_el else None
            city, country = _split_location(location)

            date_el = item.find("span", class_="job-table__item-date")
            deadline_raw = date_el.get_text(strip=True) if date_el else None
            if deadline_raw and deadline_raw.lower().startswith("until "):
                deadline_raw = deadline_raw[6:]
            deadline = _parse_deadline(deadline_raw)

            href = a.get("href", "")
            if not href.startswith("http"):
                href = "https://unidir.org" + href

            stubs.append({
                "agency": AGENCY, "agency_name": AGENCY_NAME,
                "job_title": job_title, "grade": None,
                "city": city, "country": country,
                "deadline": deadline, "url": href,
            })
        except Exception:
            continue

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [(s, ex.submit(_fetch_description, session, s["url"])) for s in stubs]

    jobs = []
    for stub, fut in futures:
        description, pubdate = fut.result()
        jobs.append({**stub, "pubdate": pubdate, "description": description})
    return jobs


if __name__ == "__main__":
    print(json.dumps(scrape()))
