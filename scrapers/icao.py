import requests
from bs4 import BeautifulSoup

AGENCY = "ICAO"
AGENCY_NAME = "International Civil Aviation Organization"
JOBS_URL = "https://icaocareers.icao.int/careers/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _parse_deadline(s: str | None) -> str | None:
    """Convert deadline from DD/MM/YYYY to YYYY-MM-DD format."""
    if not s:
        return None
    try:
        day, month, year = s.split("/")
        return f"{year}-{month}-{day}"
    except (ValueError, IndexError):
        return None


def _split_location(s: str | None) -> tuple[str | None, str | None]:
    """Split location into city and country.

    Returns (city, country) tuple.
    If comma present: everything before last comma is city, last part is country.
    If no comma: city is the value, country is None.
    """
    if not s:
        return None, None

    if "," not in s:
        return s, None

    # Split on last comma
    last_comma_idx = s.rfind(",")
    city = s[:last_comma_idx].strip()
    country = s[last_comma_idx + 1:].strip()

    return city, country


def scrape() -> list[dict]:
    response = requests.get(JOBS_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    table = soup.find("table", class_="tablePag")
    if not table:
        return []

    tbody = table.find("tbody")
    if not tbody:
        return []

    jobs = []
    for row in tbody.find_all("tr"):
        cells = row.find_all("td")

        if len(cells) != 5:
            continue

        title_cell = cells[0]
        link = title_cell.find("a")
        if not link:
            continue

        job_title = link.get_text(strip=True)
        url = link.get("href", "").strip()

        if not job_title or not url:
            continue

        if url.startswith("/"):
            url = "https://icaocareers.icao.int" + url

        grade = cells[1].get_text(strip=True) or None
        location_str = cells[3].get_text(strip=True) or None
        deadline_str = cells[4].get_text(strip=True) or None

        city, country = _split_location(location_str)

        jobs.append({
            "agency": AGENCY,
            "agency_name": AGENCY_NAME,
            "job_title": job_title,
            "grade": grade,
            "city": city,
            "country": country,
            "deadline": _parse_deadline(deadline_str),
            "url": url,
        })

    return jobs


if __name__ == "__main__":
    import json
    print(json.dumps(scrape()))
