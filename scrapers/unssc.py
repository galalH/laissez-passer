"""UNSSC Job Scraper - scrapes UNSSC employment opportunities from Drupal CMS."""

import requests
import re
from bs4 import BeautifulSoup

AGENCY = "UNSSC"
AGENCY_NAME = "United Nations System Staff College"
JOBS_URL = "https://www.unssc.org/about/employment-opportunities"
BASE_URL = "https://www.unssc.org"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

_MONTHS = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
    "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"
}


def _parse_deadline(s: str) -> str | None:
    """Parse deadline from 'DD Mon YYYY' format to 'YYYY-MM-DD' format."""
    if not s:
        return None
    parts = s.strip().split()
    if len(parts) == 3:
        m = _MONTHS.get(parts[1])
        if m:
            return f"{parts[2]}-{m}-{parts[0].zfill(2)}"
    return None


def extract_grade(title: str) -> str | None:
    """Extract grade from job title using regex patterns."""
    if not title:
        return None

    # Look for patterns like P3, P-4, P-5, G-2, D-1, etc.
    patterns = [
        r'\bP\d+\b',           # P3, P4, etc.
        r'\bP-\d+\b',          # P-3, P-4, etc.
        r'\bG-\d+\b',          # G-2, G-3, etc.
        r'\bD-\d+\b',          # D-1, D-2, etc.
    ]

    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            return match.group(0)

    return None


def scrape() -> list[dict]:
    """Scrape job openings from UNSSC employment opportunities page."""
    jobs = []

    try:
        response = requests.get(JOBS_URL, headers=HEADERS, timeout=30)
        response.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(response.text, "html.parser")

    # Find the main table
    table = soup.find("table", class_="views-view-table")
    if not table:
        return []

    tbody = table.find("tbody")
    if not tbody:
        return []

    # Iterate through each row
    for row in tbody.find_all("tr"):
        cells = row.find_all("td")

        # We expect 5 columns
        if len(cells) < 5:
            continue

        # Column 0: Vacancy code
        vacancy_code = cells[0].get_text(strip=True)

        # Column 1: Title and href
        title_cell = cells[1].find("a")
        if not title_cell:
            continue

        job_title = title_cell.get_text(strip=True)
        href = title_cell.get("href", "").strip()

        if not job_title or not href:
            continue

        # Build full URL from href
        if href.startswith("/"):
            url = BASE_URL + href
        elif href.startswith("http"):
            url = href
        else:
            url = BASE_URL + "/" + href

        # Column 2: Issue date (time element)
        issue_date = None
        issue_date_cell = cells[2].find("time")
        if issue_date_cell:
            issue_date = issue_date_cell.get_text(strip=True)

        # Column 3: Application deadline (time element)
        deadline = None
        deadline_cell = cells[3].find("time")
        if deadline_cell:
            deadline = deadline_cell.get_text(strip=True)

        # Extract grade from title
        grade = extract_grade(job_title)

        # Parse deadline to YYYY-MM-DD format
        parsed_deadline = _parse_deadline(deadline)

        # UNSSC is based in Turin, Italy
        city = "Turin"
        country = "Italy"

        jobs.append({
            "agency": AGENCY,
            "agency_name": AGENCY_NAME,
            "job_title": job_title,
            "grade": grade,
            "city": city,
            "country": country,

            "deadline": parsed_deadline,
            "url": url,
        })

    return jobs


if __name__ == "__main__":
    import json
    print(json.dumps(scrape()))
