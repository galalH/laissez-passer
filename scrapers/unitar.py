"""UNITAR Job Scraper - scrapes vacancy announcements from unitar.org."""

import requests
from bs4 import BeautifulSoup
import json
import re

AGENCY = "UNITAR"
AGENCY_NAME = "United Nations Institute for Training and Research"
JOBS_URL = "https://unitar.org/vacancy-announcements"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

KNOWN_LOCATIONS = ["Geneva", "Hiroshima", "New York", "Bonn", "Rome", "Madrid", "Vienna"]

_MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12"
}


def _parse_deadline(s: str) -> str | None:
    """Parse deadline from 'DD Month YYYY' format to 'YYYY-MM-DD'."""
    if not s:
        return None
    parts = s.strip().split()
    if len(parts) == 3:
        day, month, year = parts[0], parts[1].lower(), parts[2]
        month_num = _MONTHS.get(month)
        if month_num:
            return f"{year}-{month_num}-{day.zfill(2)}"
    return None


def _split_location(location: str) -> tuple[str | None, str | None]:
    """Split location into (city, country) by splitting on last comma."""
    if not location:
        return None, None
    if "," in location:
        parts = location.rsplit(",", 1)
        city = parts[0].strip()
        country = parts[1].strip() if len(parts) > 1 else None
        return city, country
    return location.strip(), None


def is_location(text: str) -> bool:
    if not text:
        return False
    exclude = ["organizational unit", "expertise", "vacancy type", "duration",
               "deadline", "number of", "area of", "overview", "contract"]
    tl = text.lower()
    if any(e in tl for e in exclude):
        return False
    if "," in text and len(text) > 3:
        return True
    return any(loc in text for loc in KNOWN_LOCATIONS)


def scrape_job_detail(url: str, title: str) -> dict | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
        article = soup.find("article") or soup.find("main") or soup.body
        lines = [l.strip() for l in article.get_text("\n").split("\n") if l.strip()]

        location = None
        grade = None
        deadline = None

        if len(lines) > 1:
            first = lines[0].lower()
            if ("vacancy" in first and "announcement" in first) or "roster" not in first:
                if is_location(lines[1]):
                    location = lines[1]

        for i, line in enumerate(lines):
            ll = line.lower()
            if ("deadline for submission" in ll or "application closes" in ll) and i + 1 < len(lines):
                deadline = lines[i + 1]
            if "vacancy type" in ll:
                after = line[ll.index("vacancy type") + len("vacancy type"):].strip()
                grade = after if after else (lines[i + 1] if i + 1 < len(lines) else None)

        city, country = _split_location(location)
        parsed_deadline = _parse_deadline(deadline)

        return {
            "agency": AGENCY,
            "agency_name": AGENCY_NAME,
            "job_title": title,
            "grade": grade,
            "city": city,
            "country": country,
            "deadline": parsed_deadline,
            "url": url,
        }
    except Exception:
        return None


def scrape() -> list[dict]:
    try:
        resp = requests.get(JOBS_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(resp.content, "html.parser")
    seen = set()
    jobs = []

    for link in soup.find_all("a", href=re.compile(r"/vacancy-announcements/")):
        href = link.get("href", "")
        if not re.search(r"/\d+$", href):
            continue
        text = link.get_text(strip=True)
        if not text or text in ["Job seekers", "Vacancy Announcements"]:
            continue
        full_url = "https://unitar.org" + href if href.startswith("/") else href
        if full_url in seen:
            continue
        seen.add(full_url)
        job = scrape_job_detail(full_url, text)
        if job:
            jobs.append(job)

    return jobs


if __name__ == "__main__":
    print(json.dumps(scrape()))
