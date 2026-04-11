"""UNOPS Careers Scraper - paginates the SearchJobs page."""

import re
import requests
from bs4 import BeautifulSoup
import json
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor

from scrapers._utils import html_to_md, trim

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


def _fetch_detail(url, session):
    """Return (contract_level, description) from a job detail page."""
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")

        lines = [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]
        grade = None
        for i, line in enumerate(lines):
            if line.lower() == "contract level" and i + 1 < len(lines):
                grade = lines[i + 1]
                break

        html_parts = []
        in_range = False
        for h3 in soup.find_all("h3", id=re.compile(r"^section\d+__title$")):
            text = h3.get_text(strip=True)
            if "Additional Information" in text:
                break
            if "Job Specific Context" in text:
                in_range = True
            if in_range:
                content_div = soup.find("div", id=h3["id"].replace("__title", "__content"))
                html_parts.append(str(h3))
                if content_div:
                    for img in content_div.find_all("img"):
                        img.decompose()
                    html_parts.append(str(content_div))
        description = html_to_md("".join(html_parts)) or None

        return grade, description
    except Exception:
        return None, None


def _parse_location(location_str):
    """UNOPS duty station field contains city names only, no country."""
    if not location_str:
        return None, None
    return location_str.strip(), None


def scrape() -> list[dict]:
    stubs = []
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
                location_str = deadline_raw = None
                if subtitle:
                    ds = subtitle.find("span", class_="list-item-Duty Station")
                    location_str = ds.get_text(strip=True) if ds else None
                    po = subtitle.find("span", class_="list-item-posted")
                    deadline_raw = po.get_text(strip=True) if po else None

                city, country = _parse_location(location_str)
                deadline = _parse_deadline(deadline_raw)
                stubs.append({
                    "agency": AGENCY, "agency_name": AGENCY_NAME,
                    "job_title": job_title, "city": city, "country": country,
                    "deadline": deadline, "url": job_url,
                })
            except Exception:
                continue

        if not page_has_new:
            break
        offset += records_per_page

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [(s, ex.submit(_fetch_detail, s["url"], session)) for s in stubs]

    jobs = []
    for stub, fut in futures:
        grade, description = fut.result()
        jobs.append({**stub, "grade": grade, "description": description})
    return jobs


if __name__ == "__main__":
    print(json.dumps(scrape()))
