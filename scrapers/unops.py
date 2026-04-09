"""UNOPS Careers Scraper - paginates the SearchJobs page."""

import requests
from bs4 import BeautifulSoup
import json
from urllib.parse import urljoin

AGENCY = "UNOPS"
AGENCY_NAME = "United Nations Office for Project Services"
JOBS_URL = "https://careers.unops.org/"

SEARCH_URL = "https://careers.unops.org/careersmarketplace/SearchJobs"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

_MONTHS = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
    "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"
}


def _parse_deadline(s):
    """Parse deadline from DD-Mon-YYYY format to YYYY-MM-DD format."""
    if not s:
        return None
    parts = s.strip().split("-")
    if len(parts) == 3 and len(parts[2]) == 4:
        m = _MONTHS.get(parts[1])
        if m:
            return f"{parts[2]}-{m}-{parts[0].zfill(2)}"
    return None


def _fetch_contract_level(url, session):
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        lines = [l.strip() for l in BeautifulSoup(resp.content, "html.parser").get_text("\n").split("\n") if l.strip()]
        for i, line in enumerate(lines):
            if line.lower() == "contract level" and i + 1 < len(lines):
                return lines[i + 1]
    except Exception:
        pass
    return None


def _parse_location(location_str):
    """UNOPS duty station field contains city names only, no country."""
    if not location_str:
        return None, None
    return location_str.strip(), None


def scrape() -> list[dict]:
    jobs = []
    seen_urls = set()
    offset = 0
    records_per_page = 6
    session = requests.Session()
    session.headers.update(HEADERS)

    while True:
        url = SEARCH_URL if offset == 0 else f"{SEARCH_URL}/?jobRecordsPerPage={records_per_page}&jobOffset={offset}"
        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
        except Exception:
            break

        soup = BeautifulSoup(resp.content, "html.parser")
        articles = soup.find_all("article", class_="article--result")
        if not articles:
            break

        page_has_new = False
        for article in articles:
            try:
                title_link = article.find("a", class_="link")
                if not title_link:
                    continue
                job_title = title_link.get_text(strip=True)
                job_url = title_link.get("href", "")
                if not job_url.startswith("http"):
                    job_url = urljoin(JOBS_URL, job_url)
                if job_url in seen_urls:
                    continue
                seen_urls.add(job_url)
                page_has_new = True

                subtitle = article.find("div", class_="article__header__text__subtitle")
                location_str = grade = deadline_raw = None
                if subtitle:
                    ds = subtitle.find("span", class_="list-item-Duty Station")
                    location_str = ds.get_text(strip=True) if ds else None
                    grade = None
                    po = subtitle.find("span", class_="list-item-posted")
                    deadline_raw = po.get_text(strip=True) if po else None

                city, country = _parse_location(location_str)
                deadline = _parse_deadline(deadline_raw)
                grade = _fetch_contract_level(job_url, session)

                jobs.append({
                    "agency": AGENCY,
                    "agency_name": AGENCY_NAME,
                    "job_title": job_title,
                    "grade": grade,
                    "city": city,
                    "country": country,
                    "deadline": deadline,
                    "url": job_url,
                })
            except Exception:
                continue

        if not page_has_new:
            break
        offset += records_per_page

    return jobs


if __name__ == "__main__":
    print(json.dumps(scrape()))
