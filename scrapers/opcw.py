"""OPCW Job Scraper - uses TalentSoft ATS HTML parsing."""

import re
import requests
from bs4 import BeautifulSoup

AGENCY = "OPCW"
AGENCY_NAME = "Organisation for the Prohibition of Chemical Weapons"
JOBS_URL = "https://jobs.opcw.org/job/list-of-all-jobs.aspx?all=1&mode=layer"
BASE_URL = "https://jobs.opcw.org"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


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
    try:
        response = requests.get(JOBS_URL, headers=HEADERS, timeout=30)
        response.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(response.text, "html.parser")

    jobs = []

    # Find all job cards
    job_cards = soup.find_all("div", class_="ts-offer-card")

    for card in job_cards:
        try:
            # Extract job title and URL
            title_link = card.select_one("h3.ts-offer-card__title > a.ts-offer-card__title-link")
            if not title_link:
                continue

            job_title = title_link.get_text(strip=True)
            href = title_link.get("href", "").strip()

            if not job_title or not href:
                continue

            # Build full job URL
            if href.startswith("/"):
                job_url = BASE_URL + href
            else:
                job_url = href

            # Extract grade from job title
            grade = _extract_grade(job_title)

            # Extract job metadata from content list
            content_list = card.select_one("div.ts-offer-card-content > ul.ts-offer-card-content__list")
            list_items = []
            if content_list:
                list_items = [li.get_text(strip=True) for li in content_list.find_all("li")]

            # Extract deadline from 2nd list item (index 1)
            deadline = None
            if len(list_items) > 1:
                deadline = list_items[1]

            jobs.append({
                "agency": AGENCY,
                "agency_name": AGENCY_NAME,
                "job_title": job_title,
                "grade": grade,
                "city": "The Hague",
                "country": "Netherlands",
                "deadline": _parse_deadline(deadline),
                "url": job_url,
            })

        except Exception:
            continue

    return jobs


if __name__ == "__main__":
    import json
    print(json.dumps(scrape()))
