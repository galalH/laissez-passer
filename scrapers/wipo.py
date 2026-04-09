"""WIPO Job Scraper - uses the Oracle Taleo REST API."""

import requests
import json

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

    jobs = []
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

            jobs.append({
                "agency": AGENCY,
                "agency_name": AGENCY_NAME,
                "job_title": job_title,
                "grade": grade or None,
                "city": "Geneva",
                "country": "Switzerland",

                "deadline": parse_deadline(deadline_raw),
                "url": f"{JOB_DETAIL_BASE}{contest_no}" if contest_no else JOBS_URL,
            })

        fetched = (page_no - 1) * page_size + len(requisitions)
        if fetched >= total_count or len(requisitions) < page_size:
            break
        page_no += 1

    return jobs


if __name__ == "__main__":
    print(json.dumps(scrape()))
