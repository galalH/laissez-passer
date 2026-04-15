import requests
import json
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

import re
from datetime import datetime
from scrapers._utils import html_to_md, trim, load_cached_jobs

AGENCY = "UNIDO"
AGENCY_NAME = "United Nations Industrial Development Organization"
JOBS_URL = "https://careers.unido.org/search/?createNewAlert=false&q=&optionsFacetsDD_country=&optionsFacetsDD_lang=&optionsFacetsDD_department=&optionsFacetsDD_location=&locationsearch="

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

_MONTHS = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
    "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"
}


def _parse_deadline(s):
    """Convert deadline from DD-Mon-YYYY to YYYY-MM-DD format."""
    if not s:
        return None
    parts = s.strip().split("-")
    if len(parts) == 3 and len(parts[2]) == 4:
        m = _MONTHS.get(parts[1])
        if m:
            return f"{parts[2]}-{m}-{parts[0].zfill(2)}"
    return None


def _split_location(s):
    """Split location into city and country.

    Returns (city, country) tuple.
    - If "Home Based" in s (case-insensitive): city="Home Based", country=None
    - Else split on last comma: city=before, country=after
    - If no comma: city=value, country=None
    """
    if not s:
        return None, None

    if "Home Based" in s or "home based" in s.lower():
        return "Home Based", None

    if "," in s:
        parts = s.rsplit(",", 1)
        return parts[0].strip(), parts[1].strip()

    return s.strip(), None


def _fetch_description(session, job_url: str) -> tuple[str | None, str | None]:
    try:
        resp = session.get(job_url, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
        pubdate = None
        tag = soup.find(attrs={"itemprop": "datePosted"})
        if tag:
            raw = tag.get("content", "")
            try:
                pubdate = datetime.strptime(raw, "%a %b %d %H:%M:%S %Z %Y").strftime("%Y-%m-%d")
            except Exception:
                pass
        el = soup.find(class_="jobdescription")
        description = trim(
            html_to_md(str(el)) if el else None,
            start=re.compile(r"\*+ORGANIZATIONAL CONTEXT", re.IGNORECASE),
            before="Such core functions are carried out in Divisions/Offices in its Headquarters, Sub-regional Offices and Country Offices.",
            after=re.compile(r"\n[^\n]*?\*+[^*\n]*competencies[^*\n]*\*+", re.IGNORECASE),
        )
        return description, pubdate
    except Exception:
        return None, None


def scrape() -> list[dict]:
    stubs = []
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        response = session.get(JOBS_URL, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        table = soup.find("table", {"id": "searchresults"})
        if not table:
            return stubs
        tbody = table.find("tbody")
        if not tbody:
            return stubs
        rows = tbody.find_all("tr", {"class": "data-row"})
        for row in rows:
            title_link = row.find("a", {"class": "jobTitle-link"})
            if not title_link:
                continue
            job_title = title_link.get_text(strip=True)
            job_url = title_link.get("href", "")
            if job_url and not job_url.startswith("http"):
                job_url = "https://careers.unido.org" + job_url
            location_span = row.find("span", {"class": "jobLocation"})
            location = location_span.get_text(strip=True) or None if location_span else None
            city, country = _split_location(location)
            facility_span = row.find("span", {"class": "jobFacility"})
            grade = facility_span.get_text(strip=True) or None if facility_span else None
            deadline_span = row.find("span", {"class": "jobShifttype"})
            deadline_str = deadline_span.get_text(strip=True) or None if deadline_span else None
            deadline = _parse_deadline(deadline_str)
            if job_title and job_url:
                stubs.append({
                    "agency": AGENCY, "agency_name": AGENCY_NAME,
                    "job_title": job_title, "grade": grade,
                    "city": city, "country": country,
                    "deadline": deadline, "url": job_url,
                })
    except Exception:
        pass

    cache = load_cached_jobs()
    futures = []
    jobs = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        for s in stubs:
            if s["url"] in cache:
                c = cache[s["url"]]
                jobs.append({**s, "pubdate": c.get("pubdate"), "description": c.get("description")})
            else:
                futures.append((s, ex.submit(_fetch_description, session, s["url"])))
    for stub, fut in futures:
        description, pubdate = fut.result()
        jobs.append({**stub, "pubdate": pubdate, "description": description})
    return jobs


if __name__ == "__main__":
    print(json.dumps(scrape()))
