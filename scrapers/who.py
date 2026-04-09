"""WHO Job Scraper - uses the Oracle Taleo REST API (same as FAO)."""

import requests
import json

AGENCY = "WHO"
AGENCY_NAME = "World Health Organization"
JOBS_URL = "https://careers.who.int/careersection/ex/jobsearch.ftl"

API_URL = "https://careers.who.int/careersection/rest/jobboard/searchjobs?lang=en&portal=101430233"
JOB_DETAIL_BASE = "https://careers.who.int/careersection/ex/jobdetail.ftl?job="

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": JOBS_URL,
    "Origin": "https://careers.who.int",
    "X-Requested-With": "XMLHttpRequest",
    "tz": "GMT+00:00",
    "tzname": "UTC",
}

MONTH_MAP = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
    "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
    "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}


def make_payload(page_no):
    return {
        "multilineEnabled": True,
        "sortingSelection": {"sortBySelectionParam": "1", "ascendingSortingOrder": "false"},
        "fieldData": {"fields": {"KEYWORD": "", "LOCATION": "", "JOB_TITLE": ""}, "valid": True},
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
        ]},
        "pageNo": page_no,
    }


def parse_location(raw):
    if not raw:
        return None, None
    try:
        locs = json.loads(raw)
        if isinstance(locs, list) and locs:
            loc = locs[0]
            parts = loc.split("-", 1)
            if len(parts) == 2:
                country = parts[0]
                rest = parts[1]
                city = rest.split("-")[0]
                return city, country
            else:
                # Handle "Home-Based" or "Anywhere" cases
                if loc == "Home" or "-" not in loc:
                    return loc, None
                return loc, None
    except Exception:
        pass
    # Fallback for unparseable raw
    return raw, None


def parse_deadline(raw):
    """Parse 'Mon D, YYYY, H:MM:SS AM/PM' to YYYY-MM-DD."""
    if not raw:
        return None
    try:
        # e.g. "Apr 7, 2026, 9:59:00 PM" -> take first two comma-parts "Apr 7, 2026"
        parts = raw.split(",")
        date_str = f"{parts[0].strip()} {parts[1].strip()}"  # "Apr 7 2026"
        tokens = date_str.split()
        month = MONTH_MAP.get(tokens[0])
        day = tokens[1].zfill(2)
        year = tokens[2]
        if month:
            return f"{year}-{month}-{day}"
    except Exception:
        pass
    return None


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

            # WHO Taleo multiline columns:
            # [0]=title, [1]=contestNo, [2]=location JSON, [3]=grade, [4]=contract type, [5]=deadline, [6]=org
            job_title = columns[0] if len(columns) > 0 else ""
            location_raw = columns[2] if len(columns) > 2 else None
            grade_raw = columns[3].strip() if len(columns) > 3 else None
            grade = grade_raw if grade_raw and grade_raw.lower() != "no grade" else None
            deadline = parse_deadline(columns[5]) if len(columns) > 5 else None

            city, country = parse_location(location_raw)
            jobs.append({
                "agency": AGENCY,
                "agency_name": AGENCY_NAME,
                "job_title": job_title,
                "grade": grade,
                "city": city,
                "country": country,
                "deadline": deadline,
                "url": f"{JOB_DETAIL_BASE}{contest_no}" if contest_no else JOBS_URL,
            })

        fetched = (page_no - 1) * page_size + len(requisitions)
        if fetched >= total_count or len(requisitions) < page_size:
            break
        page_no += 1

    return jobs


if __name__ == "__main__":
    print(json.dumps(scrape()))
