"""UNIDIR Job Scraper - parses the join-our-team page."""

import requests
from bs4 import BeautifulSoup
import json
from dateutil import parser as dateutil_parser

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


def scrape() -> list[dict]:
    try:
        resp = requests.get(JOBS_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(resp.content, "html.parser")
    job_list_section = soup.find("section", class_="job-list")
    if not job_list_section:
        return []

    if job_list_section.find("div", class_="job-list__empty"):
        return []

    jobs = []
    for item in job_list_section.find_all("div", class_="job-item"):
        try:
            title_el = item.find("h3", class_="job-item__title")
            job_title = title_el.get_text(strip=True) if title_el else None
            if not job_title:
                continue

            location_el = item.find("span", class_="job-item__location")
            location = location_el.get_text(strip=True) if location_el else None
            city, country = _split_location(location)

            deadline_el = item.find("span", class_="job-item__deadline")
            deadline_raw = deadline_el.get_text(strip=True) if deadline_el else None
            deadline = _parse_deadline(deadline_raw)

            grade_el = item.find("span", class_="job-item__grade")
            grade = grade_el.get_text(strip=True) if grade_el else None

            link_el = item.find("a")
            href = link_el.get("href") if link_el else None
            if href and not href.startswith("http"):
                href = "https://unidir.org" + href

            jobs.append({
                "agency": AGENCY,
                "agency_name": AGENCY_NAME,
                "job_title": job_title,
                "grade": grade,
                "city": city,
                "country": country,
                "deadline": deadline,
                "url": href or JOBS_URL,
            })
        except Exception:
            continue

    return jobs


if __name__ == "__main__":
    print(json.dumps(scrape()))
