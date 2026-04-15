import re
import json
import requests
from urllib.parse import unquote
from concurrent.futures import ThreadPoolExecutor

from scrapers._utils import html_to_md, trim, load_cached_jobs

AGENCY = "FAO"
AGENCY_NAME = "Food and Agriculture Organization"
JOBS_URL = "https://jobs.fao.org/careersection/fao_external/jobsearch.ftl?lang=en"

API_URL = "https://jobs.fao.org/careersection/rest/jobboard/searchjobs?lang=en&portal=8105120163"
JOB_DETAIL_BASE = "https://jobs.fao.org/careersection/fao_external/jobdetail.ftl?job="

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://jobs.fao.org/careersection/fao_external/jobsearch.ftl?lang=en",
    "Origin": "https://jobs.fao.org",
    "X-Requested-With": "XMLHttpRequest",
    "tz": "GMT+00:00",
    "tzname": "UTC",
}


def make_payload(page_no):
    return {
        "multilineEnabled": True,
        "sortingSelection": {
            "sortBySelectionParam": "1",
            "ascendingSortingOrder": "false"
        },
        "fieldData": {
            "fields": {
                "KEYWORD": "",
                "LOCATION": "",
                "JOB_TITLE": ""
            },
            "valid": True
        },
        "filterSelectionParam": {
            "searchFilterSelections": [
                {"id": "JOB_TYPE", "selectedValues": []},
                {"id": "LOCATION", "selectedValues": []},
                {"id": "JOB_FIELD", "selectedValues": []},
                {"id": "POSTING_DATE", "selectedValues": []}
            ]
        },
        "advancedSearchFiltersSelectionParam": {
            "searchFilterSelections": [
                {"id": "ORGANIZATION", "selectedValues": []},
                {"id": "LOCATION", "selectedValues": []},
                {"id": "JOB_FIELD", "selectedValues": []},
                {"id": "JOB_NUMBER", "selectedValues": []},
                {"id": "URGENT_JOB", "selectedValues": []}
            ]
        },
        "pageNo": page_no
    }


def parse_location(location_str):
    if not location_str:
        return (None, None)
    try:
        locs = json.loads(location_str)
        if isinstance(locs, list) and locs:
            loc = locs[0]
            if loc.lower() == "home-based":
                return (None, "Home Based")
            parts = loc.split("-")
            if len(parts) >= 2:
                return (parts[1], parts[0])
            return (loc, None)
    except (json.JSONDecodeError, ValueError):
        pass
    return (location_str, None)


def fetch_detail(session: requests.Session, job_url: str) -> tuple[str | None, str | None]:
    """Fetch job detail page and return (grade, description).
    When Grade Level is N/A, grade is the text before the parenthesis in
    the Type of Requisition field (e.g. 'NPP' from 'NPP (National Project Personnel)').
    Description is extracted from URL-encoded HTML blocks embedded in the page."""
    try:
        r = session.get(job_url, timeout=30)
        html = r.text

        # Grade: standard code (e.g. 'P-5', 'G-3') or Type of Requisition fallback
        grades = re.findall(r"'([A-Z]-\d)'", html)
        if grades:
            grade = grades[0]
        else:
            m = re.search(r'!([^!(|\n]+?)\s*(?:\([^)]+\)\s*)?!\|![^!]*!\|!N/A!', html)
            grade = m.group(1).strip() if m else None

        # Description: longest URL-encoded HTML block (%3C...) in the page
        encoded_blocks = re.findall(r'!(%3C[^!]{500,})!', html, re.IGNORECASE)
        description = None
        if encoded_blocks:
            best = max(encoded_blocks, key=len)
            decoded = unquote(best.replace('%5C:', ':'))
            description = html_to_md(decoded)

        description = trim(description, after="**ADDITIONAL INFORMATION**")
        return grade, description
    except Exception:
        return None, None


def parse_deadline(deadline_str):
    if not deadline_str:
        return None
    date_part = deadline_str.split(",")[0].strip()
    month_map = {
        "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
        "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
        "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"
    }
    parts = date_part.split("/")
    if len(parts) == 3:
        day, month, year = parts
        month_num = month_map.get(month, month)
        return f"{year}-{month_num}-{day.zfill(2)}"
    return deadline_str


def scrape() -> list[dict]:
    session = requests.Session()
    session.headers.update(HEADERS)

    stubs = []
    seen_ids = set()
    page_no = 1
    total_count = None
    page_size = 25

    while True:
        payload = make_payload(page_no)
        response = session.post(API_URL, json=payload, timeout=30)
        response.raise_for_status()

        data = response.json()

        paging = data.get("pagingData", {})
        if total_count is None:
            total_count = paging.get("totalCount", 0)
            page_size = paging.get("pageSize", 25)

        requisitions = data.get("requisitionList", [])
        if not requisitions:
            break

        new_items_on_page = 0
        for item in requisitions:
            columns = item.get("column", [])
            contest_no = item.get("contestNo", "")
            job_id = item.get("jobId", "")

            unique_id = contest_no or job_id
            if unique_id in seen_ids:
                continue

            seen_ids.add(unique_id)
            new_items_on_page += 1

            job_title = columns[0] if len(columns) > 0 else ""
            location_raw = columns[4] if len(columns) > 4 else None
            deadline_raw = columns[6] if len(columns) > 6 else None

            pubdate_raw = columns[5] if len(columns) > 5 else None
            city, country = parse_location(location_raw)
            deadline = parse_deadline(deadline_raw)
            pubdate = parse_deadline(pubdate_raw)
            job_url = f"{JOB_DETAIL_BASE}{contest_no}" if contest_no else f"{JOB_DETAIL_BASE}{job_id}"
            stubs.append({
                "agency": AGENCY, "agency_name": AGENCY_NAME,
                "job_title": job_title, "city": city, "country": country,
                "deadline": deadline, "pubdate": pubdate, "url": job_url,
            })

        if new_items_on_page == 0 or len(requisitions) < page_size:
            break

        page_no += 1

    cache = load_cached_jobs()
    futures = []
    jobs = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        for s in stubs:
            if s["url"] in cache:
                c = cache[s["url"]]
                jobs.append({**s, "grade": c.get("grade"), "description": c.get("description")})
            else:
                futures.append((s, ex.submit(fetch_detail, session, s["url"])))
    for stub, fut in futures:
        grade, description = fut.result()
        jobs.append({**stub, "grade": grade, "description": description})
    return jobs



if __name__ == "__main__":
    print(json.dumps(scrape()))
