"""ILO Job Scraper - uses the ILO careers JSON API."""

import re
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

from scrapers._utils import html_to_md

AGENCY = "ILO"
AGENCY_NAME = "International Labour Organization"
JOBS_URL = "https://jobs.ilo.org/"
SEARCH_URL = "https://jobs.ilo.org/search/"
API_URL = "https://jobs.ilo.org/services/recruiting/v1/jobs"
JOB_URL_TEMPLATE = "https://jobs.ilo.org/job/{url_title}/{job_id}-en_GB"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://jobs.ilo.org/search/",
}


def _get_csrf_token(session):
    resp = session.get(SEARCH_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    match = re.search(r'CSRFToken\s*=\s*["\']([a-f0-9-]{36})["\']', resp.text, re.IGNORECASE)
    if match:
        return match.group(1)
    raise RuntimeError("Could not find CSRF token in page HTML")


def _fetch_page(session, csrf_token, page_number):
    payload = {
        "locale": "en_GB",
        "pageNumber": page_number,
        "sortBy": "",
        "keywords": "",
        "location": "",
        "facetFilters": {},
        "brand": "",
        "skills": [],
        "categoryId": 0,
        "alertId": "",
        "rcmCandidateId": "",
    }
    api_headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Referer": SEARCH_URL,
        "X-CSRF-Token": csrf_token,
    }
    resp = session.post(API_URL, json=payload, headers=api_headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _fetch_description(session, url):
    try:
        resp = session.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        el = BeautifulSoup(resp.content, "html.parser").select_one("div.content")
        return html_to_md(str(el)) if el else None
    except Exception:
        return None


def _parse_deadline(s):
    """Convert DD/MM/YYYY format to YYYY-MM-DD."""
    if not s:
        return None
    try:
        parts = s.split("/")
        if len(parts) != 3:
            return None
        day, month, year = parts
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    except Exception:
        return None


def _split_location(s):
    """Split location string into city and country.

    Splits on the last comma. If no comma, city is the value and country is None.
    """
    if not s:
        return None, None
    if "," not in s:
        return s.strip(), None
    first_comma_idx = s.index(",")
    city = s[:first_comma_idx].strip()
    country = s[first_comma_idx + 1:].strip()
    return city, country


def _parse_job(job_item):
    r = job_item.get("response", {})

    job_title = r.get("unifiedStandardTitle") or r.get("unifiedUrlTitle", "").replace("-", " ")
    grade = None
    grades = r.get("filter4", [])
    if grades:
        grade = grades[0]

    locations = r.get("jobLocationShort", [])
    location = locations[0].strip() if locations else None
    city, country = _split_location(location)

    deadline_raw = r.get("unifiedStandardEnd")
    deadline = _parse_deadline(deadline_raw)

    job_id = r.get("id", "")
    url_title = r.get("urlTitle") or r.get("unifiedUrlTitle", "")
    if job_id and url_title:
        url = JOB_URL_TEMPLATE.format(url_title=url_title, job_id=job_id)
    else:
        url = JOBS_URL

    return {
        "agency": AGENCY,
        "agency_name": AGENCY_NAME,
        "job_title": job_title,
        "grade": grade,
        "city": city,
        "country": country,
        "deadline": deadline,
        "url": url,
    }


def scrape() -> list:
    session = requests.Session()
    csrf_token = _get_csrf_token(session)

    stubs = []
    page = 0

    while True:
        data = _fetch_page(session, csrf_token, page)
        results = data.get("jobSearchResult", [])
        total = data.get("totalJobs", 0)

        if not results:
            break

        for item in results:
            stubs.append(_parse_job(item))

        if len(stubs) >= total:
            break

        page += 1

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [(s, ex.submit(_fetch_description, session, s["url"])) for s in stubs]

    return [{**stub, "description": fut.result()} for stub, fut in futures]


if __name__ == "__main__":
    import json
    print(json.dumps(scrape()))
