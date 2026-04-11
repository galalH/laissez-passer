"""ITU Job Scraper - scrapes from jobs.itu.int."""

import requests
from bs4 import BeautifulSoup
import re
from dateutil import parser as dateutil_parser
from concurrent.futures import ThreadPoolExecutor

from scrapers._utils import html_to_md

AGENCY = "ITU"
AGENCY_NAME = "International Telecommunication Union"
JOBS_URL = "https://jobs.itu.int/go/View-all-categories/8942455/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

BASE_URL = "https://jobs.itu.int"

_FR_MONTHS = {
    "janvier": "January", "février": "February", "mars": "March",
    "avril": "April", "mai": "May", "juin": "June",
    "juillet": "July", "août": "August", "septembre": "September",
    "octobre": "October", "novembre": "November", "décembre": "December",
}

_FR_MONTH_RE = re.compile("|".join(_FR_MONTHS), re.IGNORECASE)


def _normalize_date_str(s: str) -> str:
    """Replace French month names with English equivalents."""
    return _FR_MONTH_RE.sub(lambda m: _FR_MONTHS[m.group().lower()], s)


def _split_location(s):
    if s is None:
        return None, None
    if "home based" in s.lower():
        return "Home Based", None
    if "multiple duty" in s.lower():
        return None, "Multiple duty stations"
    if "," in s:
        parts = s.rsplit(",", 1)
        return parts[0].strip(), parts[1].strip()
    return s, None


def _get_job_details(job_url, session):
    """Fetch grade, deadline, and description from vacancy notice page."""
    try:
        resp = session.get(job_url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        text = soup.get_text(separator="\n", strip=True)

        grade = None
        m = re.search(r'Grade:\s*\n\s*(\S+)', text)
        if m:
            raw_grade = m.group(1).strip()
            if not raw_grade.startswith("[["):
                grade = raw_grade

        deadline = None
        m2 = re.search(
            r'(?:Application deadline|Date limite de candidature)[^:\n]*:?\s*\n?\s*([^\n]+)',
            text, re.IGNORECASE
        )
        if m2:
            raw = _normalize_date_str(m2.group(1).strip())
            try:
                deadline = dateutil_parser.parse(raw).strftime("%Y-%m-%d")
            except Exception:
                deadline = raw

        desc_el = soup.find(class_="jobdescription")
        description = html_to_md(str(desc_el)) if desc_el else None

        return grade, deadline, description
    except Exception:
        return None, None, None


def scrape_page(url, session):
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    jobs = []
    rows = soup.select("tr.data-row")

    for row in rows:
        title_link = row.select_one("span.jobTitle.hidden-phone a.jobTitle-link")
        if not title_link:
            title_link = row.select_one("a.jobTitle-link")
        if not title_link:
            continue

        job_title = title_link.get_text(strip=True)
        job_href = title_link.get("href", "")
        if job_href.startswith("/"):
            job_url = BASE_URL + job_href
        else:
            job_url = job_href

        location_el = row.select_one("td.colLocation span.jobLocation")
        location = location_el.get_text(strip=True) if location_el else None
        city, country = _split_location(location)

        jobs.append({"job_title": job_title, "url": job_url, "city": city, "country": country})

    return jobs, soup


def get_page_urls(soup):
    pagination_links = soup.select(".paginationShell a")
    urls = set()
    for link in pagination_links:
        href = link.get("href", "")
        if href and "jobs.itu.int" in href:
            urls.add(href)
        elif href and href.startswith("/"):
            urls.add(BASE_URL + href)
    return urls


def scrape() -> list[dict]:
    session = requests.Session()
    session.headers.update(HEADERS)

    all_jobs = []
    first_jobs, first_soup = scrape_page(JOBS_URL, session)
    all_jobs.extend(first_jobs)

    page_urls = get_page_urls(first_soup)
    for page_url in sorted(page_urls):
        if page_url.rstrip("/").endswith("8942455") or (
            "/8942455/?" in page_url and not re.search(r'/8942455/\d+/', page_url)
        ):
            continue
        try:
            page_jobs, _ = scrape_page(page_url, session)
            all_jobs.extend(page_jobs)
        except Exception:
            pass

    seen_urls = set()
    unique_jobs = []
    for job in all_jobs:
        url = job["url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        unique_jobs.append(job)

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [(job, ex.submit(_get_job_details, job["url"], session)) for job in unique_jobs]

    results = []
    for job, fut in futures:
        grade, deadline, description = fut.result()
        results.append({
            "agency": AGENCY, "agency_name": AGENCY_NAME,
            "job_title": job["job_title"], "grade": grade,
            "city": job["city"], "country": job["country"],
            "deadline": deadline, "url": job["url"],
            "description": description,
        })
    return results


if __name__ == "__main__":
    import json
    print(json.dumps(scrape()))
