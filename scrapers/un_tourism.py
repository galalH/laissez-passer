"""UNWTO Job Scraper - parses the HTML table on the work-with-us page."""

import requests
from bs4 import BeautifulSoup
import json
import re

AGENCY = "UN Tourism"
AGENCY_NAME = "World Tourism Organization"
JOBS_URL = "https://www.untourism.int/work-with-us"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

_MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12"
}


def _parse_deadline(s):
    """Parse deadline string and return YYYY-MM-DD format, or None."""
    if not s:
        return None
    # Extract first "DD Month YYYY" pattern
    m = re.search(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})', s)
    if m:
        mon = _MONTHS.get(m.group(2).lower())
        if mon:
            return f"{m.group(3)}-{mon}-{m.group(1).zfill(2)}"
    return None


def _split_location(location):
    """Split location into city and country. Split on last comma."""
    if not location:
        return None, None
    if "," in location:
        parts = location.rsplit(",", 1)
        city = parts[0].strip()
        country = parts[1].strip()
        return city, country
    else:
        # No comma, treat entire string as city
        return location, None


def scrape() -> list[dict]:
    jobs = []

    try:
        resp = requests.get(JOBS_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue

            # Detect header row
            header_cells = rows[0].find_all(["th", "td"])
            header_text = [c.get_text(strip=True).lower() for c in header_cells]

            # Skip tables that don't look like job listings
            if not any("title" in h or "post" in h or "type" in h or "intern" in h for h in header_text):
                continue

            # Determine column indices
            col_title = next((i for i, h in enumerate(header_text) if "title" in h or "post title" in h), 0)
            col_grade = next((i for i, h in enumerate(header_text) if "grade" in h or "area" in h), 1)
            col_location = next((i for i, h in enumerate(header_text) if "location" in h), None)
            col_deadline = next((i for i, h in enumerate(header_text) if "closing" in h or "deadline" in h), None)

            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue

                # Job title
                job_title = cells[col_title].get_text(strip=True) if len(cells) > col_title else ""
                if not job_title or job_title.lower() in ("post title", "type of post"):
                    continue

                # Grade
                grade = cells[col_grade].get_text(strip=True) if col_grade is not None and len(cells) > col_grade else None
                grade = grade or None

                # Location
                location = cells[col_location].get_text(strip=True) if col_location is not None and len(cells) > col_location else None
                location = location or None
                city, country = _split_location(location)

                # Deadline
                deadline = cells[col_deadline].get_text(strip=True) if col_deadline is not None and len(cells) > col_deadline else None
                deadline = deadline or None
                deadline = _parse_deadline(deadline)

                # URL — find a link in the row; strip whitespace and take the
                # last space-separated token in case the href contains a
                # concatenated base URL (e.g. "https://base https://actual").
                link = row.find("a", href=True)
                if link:
                    raw_href = link["href"].strip()
                    url = raw_href.split()[-1] if " " in raw_href else raw_href
                    if not url.startswith("http"):
                        url = "https://www.untourism.int" + url
                else:
                    url = JOBS_URL

                jobs.append({
                    "agency": AGENCY,
                    "agency_name": AGENCY_NAME,
                    "job_title": job_title,
                    "grade": grade,
                    "city": city,
                    "country": country,
                    "deadline": deadline,
                    "url": url,
                })

    except Exception:
        pass

    return jobs


if __name__ == "__main__":
    print(json.dumps(scrape()))
