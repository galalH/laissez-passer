"""IAEA Job Scraper - uses Oracle Taleo REST API."""

import requests
import json
import re
from urllib.parse import quote

AGENCY = "IAEA"
AGENCY_NAME = "International Atomic Energy Agency"
JOBS_URL = "https://iaea.taleo.net/careersection/ex/jobsearch.ftl"
API_URL = "https://iaea.taleo.net/careersection/rest/jobboard/searchjobs"
PORTAL = "8105100373"
JOB_DETAIL_BASE = "https://iaea.taleo.net/careersection/ex/jobdetail.ftl?job="

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": JOBS_URL,
    "Origin": "https://iaea.taleo.net",
    "X-Requested-With": "XMLHttpRequest",
    "tz": "GMT+00:00",
    "tzname": "UTC",
}


def make_payload(page_no):
    return {
        "multilineEnabled": True,
        "sortingSelection": {"sortBySelectionParam": "1", "ascendingSortingOrder": "false"},
        "fieldData": {
            "fields": {"KEYWORD": "", "LOCATION": "", "JOB_TITLE": ""},
            "valid": True,
        },
        "filterSelectionParam": {"searchFilterSelections": [
            {"id": "JOB_TYPE", "selectedValues": []},
            {"id": "LOCATION", "selectedValues": []},
            {"id": "JOB_FIELD", "selectedValues": []},
            {"id": "POSTING_DATE", "selectedValues": []},
        ]},
        "advancedSearchFiltersSelectionParam": {"searchFilterSelections": [
            {"id": "ORGANIZATION", "selectedValues": []},
            {"id": "LOCATION", "selectedValues": []},
            {"id": "JOB_FIELD", "selectedValues": []},
            {"id": "JOB_NUMBER", "selectedValues": []},
            {"id": "URGENT_JOB", "selectedValues": []},
        ]},
        "pageNo": page_no,
    }


def parse_location(location_json_str):
    if not location_json_str:
        return None, None
    try:
        locs = json.loads(location_json_str)
        if isinstance(locs, list) and locs:
            loc = locs[0]
            if "Home" in loc and "Based" in loc:
                return "Home Based", None
            parts = loc.split("-")
            if len(parts) >= 2:
                return parts[1], parts[0]
            return loc, None
    except Exception:
        pass
    return location_json_str, None


def fetch_closing_date(session: requests.Session, job_url: str) -> str | None:
    """Fetch a job detail page and extract the closing date."""
    try:
        r = session.get(job_url, timeout=30)
        dates = re.findall(r"(\d{4}-\d{2}-\d{2}), \d{1,2}:\d{2}:\d{2} [AP]M", r.text)
        # Dates appear in order: posted, posted, closing, closing — take index 2
        if len(dates) >= 3:
            return dates[2]
    except Exception:
        pass
    return None


def scrape() -> list[dict]:
    session = requests.Session()
    session.headers.update(HEADERS)
    # Establish session/cookies first
    session.get(JOBS_URL, timeout=30)

    jobs = []
    seen = set()
    page_no = 1
    total_count = None
    page_size = 25

    while True:
        resp = session.post(
            API_URL,
            params={"lang": "en", "portal": PORTAL},
            json=make_payload(page_no),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        paging = data.get("pagingData", {})
        if total_count is None:
            total_count = paging.get("totalCount", 0)
            page_size = paging.get("pageSize", 25)

        requisitions = data.get("requisitionList", [])
        if not requisitions:
            break

        new_on_page = 0
        for item in requisitions:
            cols = item.get("column", [])
            contest_no = item.get("contestNo", "")
            job_id = item.get("jobId", "")

            unique_id = contest_no or job_id
            if unique_id in seen:
                continue
            seen.add(unique_id)
            new_on_page += 1

            raw_title = cols[0] if cols else ""
            city, country = parse_location(cols[1]) if len(cols) > 1 else (None, None)

            # Extract grade from title, e.g. "(P4)", "(G5)", "(D1)"
            grade_match = re.search(r"\(([GPD]\d)\)", raw_title)
            grade = grade_match.group(1) if grade_match else None
            job_title = re.sub(r"\s*\([GPD]\d\)", "", raw_title).strip()

            # URL-encode spaces/special chars but keep /, (, ) as-is
            job_id_encoded = quote(contest_no, safe="/()") if contest_no else quote(job_id, safe="/()")
            job_url = f"{JOB_DETAIL_BASE}{job_id_encoded}"
            deadline = fetch_closing_date(session, job_url)

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

        # Stop only when no new items — don't stop on short page (API count can drift)
        if new_on_page == 0:
            break

        page_no += 1

    return jobs


if __name__ == "__main__":
    print(json.dumps(scrape()))
