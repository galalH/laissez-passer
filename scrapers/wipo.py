"""WIPO Job Scraper - uses the Oracle Taleo REST API."""

import re
import requests
import json
from urllib.parse import unquote
from concurrent.futures import ThreadPoolExecutor

from scrapers._utils import html_to_md

AGENCY = "WIPO"
AGENCY_NAME = "World Intellectual Property Organization"
JOBS_URL = "https://wipo.taleo.net/careersection/wp_2/jobsearch.ftl?lang=en"

API_URL = "https://wipo.taleo.net/careersection/rest/jobboard/searchjobs?lang=en&portal=101430233"
JOB_DETAIL_BASE = "https://wipo.taleo.net/careersection/wp_2/jobdetail.ftl?job="

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": JOBS_URL,
    "X-Requested-With": "XMLHttpRequest",
    "tz": "GMT+00:00",
    "tzname": "UTC",
}

MONTH_MAP = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
    "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
    "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}


def fetch_detail(session: requests.Session, job_url: str) -> str | None:
    """Fetch job detail page and return description markdown."""
    try:
        r = session.get(job_url, timeout=30)
        encoded_blocks = re.findall(r'!(%3C[^!]{500,})!', r.text, re.IGNORECASE)
        if encoded_blocks:
            best = max(encoded_blocks, key=len)
            decoded = unquote(best.replace('%5C:', ':'))
            return html_to_md(decoded)
    except Exception:
        pass
    return None


def parse_deadline(raw):
    """Parse '02-Apr-2026, 9:59:00 PM' -> '2026-04-02'."""
    if not raw:
        return None
    date_part = raw.split(",")[0].strip()
    parts = date_part.split("-")
    if len(parts) == 3:
        day, month, year = parts
        return f"{year}-{MONTH_MAP.get(month, month)}-{day.zfill(2)}"
    return raw


def make_payload(page_no):
    return {
        "multilineEnabled": True,
        "sortingSelection": {"sortBySelectionParam": "1", "ascendingSortingOrder": "false"},
        "fieldData": {"fields": {"KEYWORD": "", "LOCATION": "", "JOB_TITLE": ""}, "valid": True},
        "filterSelectionParam": {"searchFilterSelections": []},
        "advancedSearchFiltersSelectionParam": {"searchFilterSelections": []},
        "pageNo": page_no,
    }


def scrape() -> list[dict]:
    session = requests.Session()
    session.headers.update(HEADERS)

    stubs = []
    page_no = 1
    total_count = None
    page_size = 25

    while True:
        resp = session.post(API_URL, json=make_payload(page_no), timeout=30)
        resp.raise_for_status()
        data = resp.json()

        paging = data.get("pagingData", {})
        if total_count is None:
            total_count = paging.get("totalCount", 0)
            page_size = paging.get("pageSize", 25)

        requisitions = data.get("requisitionList", [])
        if not requisitions:
            break

        for item in requisitions:
            columns = item.get("column", [])
            contest_no = item.get("contestNo", "")

            # multiline columns: [0]=title, [1]=grade, [2]=org, [3]=contestNo, [4]=contract type,
            #                    [5]=category, [6]=location JSON, [7]=int/local, [8]=deadline
            job_title = columns[0] if len(columns) > 0 else ""
            grade = (columns[1].strip() or None) if len(columns) > 1 else None
            deadline_raw = columns[8] if len(columns) > 8 else None

            job_url = f"{JOB_DETAIL_BASE}{contest_no}" if contest_no else JOBS_URL
            stubs.append({
                "agency": AGENCY, "agency_name": AGENCY_NAME,
                "job_title": job_title, "grade": grade or None,
                "city": "Geneva", "country": "Switzerland",
                "deadline": parse_deadline(deadline_raw), "url": job_url,
            })

        fetched = (page_no - 1) * page_size + len(requisitions)
        if fetched >= total_count or len(requisitions) < page_size:
            break
        page_no += 1

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [(s, ex.submit(fetch_detail, session, s["url"])) for s in stubs]

    jobs = []
    for stub, fut in futures:
        jobs.append({**stub, "description": fut.result()})
    return jobs


if __name__ == "__main__":
    print(json.dumps(scrape()))
