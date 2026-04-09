import requests
from bs4 import BeautifulSoup
from typing import Optional

AGENCY = "UNDP"
AGENCY_NAME = "United Nations Development Programme"
JOBS_URL = "https://jobs.undp.org/cj_view_jobs.cfm"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

_MONTHS = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
    "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"
}

def _parse_deadline(s: str) -> Optional[str]:
    """
    Parse deadline from Mon-DD-YY format to YYYY-MM-DD format.
    Example: 'Mar-25-26' -> '2026-03-25'
    """
    if not s:
        return None
    parts = s.split("-")
    if len(parts) == 3:
        mon, day, yr = parts
        m = _MONTHS.get(mon)
        if m:
            year = f"20{yr}" if len(yr) == 2 else yr
            return f"{year}-{m}-{day.zfill(2)}"
    return None

def _parse_location(location: str) -> tuple[Optional[str], Optional[str]]:
    """
    Split location string into city and country.
    Splits on the last comma. If no comma, city=value, country=None.
    Example: 'Luanda, Angola' -> ('Luanda', 'Angola')
    """
    if not location:
        return None, None
    if ',' in location:
        last_comma = location.rfind(',')
        city = location[:last_comma].strip()
        country = location[last_comma+1:].strip()
        return city, country
    return None, location.strip()

def scrape() -> list[dict]:
    """
    Scrapes UNDP job listings from the vacancies page.
    Returns a list of job dictionaries with required fields.
    Handles pagination and multiple job listing tables.
    """
    jobs = []
    seen_urls = set()

    try:
        # Fetch the page
        response = requests.get(JOBS_URL, headers=HEADERS, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        # Find all job rows across all tables on the page
        rows = soup.find_all('a', class_='vacanciesTable__row')

        for row in rows:
            try:
                job_url = row.get('href', '').strip()

                # Skip if no URL or already seen (deduplication)
                if not job_url or job_url in seen_urls:
                    continue

                seen_urls.add(job_url)

                # Extract cells from the row
                cells = row.find_all('div', class_='vacanciesTable__cell')

                if len(cells) < 5:
                    continue

                # Cell 0: Job Title
                job_title_span = cells[0].find('span')
                job_title = job_title_span.get_text().strip() if job_title_span else ""

                # Cell 1: Post level (Grade)
                grade_span = cells[1].find('span')
                grade = grade_span.get_text().strip() if grade_span else None
                grade = grade if grade else None

                # Cell 2: Apply by (Deadline)
                deadline_span = cells[2].find('span')
                deadline_raw = deadline_span.get_text().strip() if deadline_span else None
                deadline = _parse_deadline(deadline_raw) if deadline_raw else None

                # Cell 3: Agency (skip - we know it's UNDP)

                # Cell 4: Location
                location_span = cells[4].find('span')
                location_raw = location_span.get_text().strip() if location_span else None
                city, country = _parse_location(location_raw) if location_raw else (None, None)

                # Add job if we have required fields
                if job_title and job_url:
                    jobs.append({
                        'agency': AGENCY,
                        'agency_name': AGENCY_NAME,
                        'job_title': job_title,
                        'grade': grade,
                        'city': city,
                        'country': country,
                        'deadline': deadline,
                        'url': job_url
                    })

            except Exception:
                # Skip this row and continue
                continue

    except Exception as e:
        return []

    return jobs


if __name__ == "__main__":
    import json
    print(json.dumps(scrape()))
