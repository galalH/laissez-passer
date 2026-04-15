import re
import requests
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from bs4 import BeautifulSoup

from scrapers._utils import html_to_md, trim

AGENCY = "UNDP"
AGENCY_NAME = "United Nations Development Programme"
JOBS_URL = "https://jobs.undp.org/cj_view_jobs.cfm"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

_ORACLE_BASE = "https://estm.fa.em2.oraclecloud.com"
_DETAIL_API = f"{_ORACLE_BASE}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
_DESC_FIELDS = ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")


def _fetch_description(session: requests.Session, job_url: str) -> tuple[str | None, str | None]:
    try:
        job_id = job_url.rstrip("/").split("/")[-1]
        params = {"expand": "all", "onlyData": "true", "finder": f'ById;Id="{job_id}",siteNumber=CX_1'}
        resp = session.get(_DETAIL_API, params=params, timeout=30)
        resp.raise_for_status()
        item = (resp.json().get("items") or [{}])[0]
        start_date = item.get("ExternalPostedStartDate") or None
        pubdate = start_date[:10] if start_date else None
        parts = [html_to_md(item.get(f) or "") or "" for f in _DESC_FIELDS]
        description = "\n\n".join(p for p in parts if p) or None
        return trim(description, after=re.compile(r"\*+\s*Equal opportunity")), pubdate
    except Exception:
        return None, None

_MONTHS = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
    "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"
}

def _parse_deadline(s: str) -> Optional[str]:
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
    if not location:
        return None, None
    if ',' in location:
        last_comma = location.rfind(',')
        city = location[:last_comma].strip()
        country = location[last_comma+1:].strip()
        return city, country
    return None, location.strip()

def scrape() -> list[dict]:
    jobs = []
    seen_urls = set()
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        response = session.get(JOBS_URL, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        rows = soup.find_all('a', class_='vacanciesTable__row')
    except Exception:
        return []

    stubs = []
    for row in rows:
        try:
            job_url = row.get('href', '').strip()
            if not job_url or job_url in seen_urls:
                continue
            seen_urls.add(job_url)

            cells = row.find_all('div', class_='vacanciesTable__cell')
            if len(cells) < 5:
                continue

            job_title_span = cells[0].find('span')
            job_title = job_title_span.get_text().strip() if job_title_span else ""

            grade_span = cells[1].find('span')
            grade = grade_span.get_text().strip() if grade_span else None
            grade = grade if grade else None

            deadline_span = cells[2].find('span')
            deadline_raw = deadline_span.get_text().strip() if deadline_span else None
            deadline = _parse_deadline(deadline_raw) if deadline_raw else None

            location_span = cells[4].find('span')
            location_raw = location_span.get_text().strip() if location_span else None
            city, country = _parse_location(location_raw) if location_raw else (None, None)

            if job_title and job_url:
                stubs.append({
                    'agency': AGENCY,
                    'agency_name': AGENCY_NAME,
                    'job_title': job_title,
                    'grade': grade,
                    'city': city,
                    'country': country,
                    'deadline': deadline,
                    'url': job_url,
                })
        except Exception:
            continue

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(_fetch_description, session, s['url']) for s in stubs]
    for stub, fut in zip(stubs, futures):
        description, pubdate = fut.result()
        stub['description'] = description
        stub['pubdate'] = pubdate
        jobs.append(stub)

    return jobs


if __name__ == "__main__":
    import json
    print(json.dumps(scrape()))
