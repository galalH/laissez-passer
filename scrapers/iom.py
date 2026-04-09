"""IOM Job Scraper - uses the Oracle HCM Cloud REST API."""

import requests
import json

AGENCY = "IOM"
AGENCY_NAME = "International Organization for Migration"
BASE_URL = "https://fa-evlj-saasfaprod1.fa.ocs.oraclecloud.com"
JOBS_URL = f"{BASE_URL}/hcmUI/CandidateExperience/en/sites/CX_1001/jobs"
API_URL = f"{BASE_URL}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
DETAIL_API_URL = f"{BASE_URL}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
JOB_URL_TEMPLATE = f"{BASE_URL}/hcmUI/CandidateExperience/en/sites/CX_1001/job/{{job_id}}"

EXPAND = (
    "requisitionList.workLocation,"
    "requisitionList.otherWorkLocations,"
    "requisitionList.secondaryLocations,"
    "flexFieldsFacet.values,"
    "requisitionList.requisitionFlexFields"
)
FACETS = "LOCATIONS;WORK_LOCATIONS;WORKPLACE_TYPES;TITLES;CATEGORIES;ORGANIZATIONS;POSTING_DATES;FLEX_FIELDS"
PAGE_SIZE = 100

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": JOBS_URL,
}


def _split_location(location_str):
    """Split location string on last comma.

    Args:
        location_str: String like "Geneva, Switzerland" or "New York, USA"

    Returns:
        Tuple of (city, country). If no comma, returns (location_str, None).
    """
    if not location_str:
        return None, None

    if "," in location_str:
        last_comma_idx = location_str.rfind(",")
        city = location_str[:last_comma_idx].strip()
        country = location_str[last_comma_idx + 1:].strip()
        return city, country
    else:
        return location_str.strip(), None


def _fetch_detail(session, job_id):
    """Fetch grade and deadline from job detail API."""
    try:
        params = {
            "expand": "all",
            "onlyData": "true",
            "finder": f'ById;Id="{job_id}",siteNumber=CX_1001',
        }
        resp = session.get(DETAIL_API_URL, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        item = resp.json().get("items", [{}])[0]
        grade = None
        for field in item.get("requisitionFlexFields", []):
            if field.get("Prompt") == "Grade":
                grade = field.get("Value") or None
                break
        end_date = item.get("ExternalPostedEndDate") or None
        deadline = end_date[:10] if end_date else None
        return grade, deadline
    except Exception:
        return None, None


def scrape() -> list[dict]:
    session = requests.Session()
    jobs = []
    offset = 0

    while True:
        finder = (
            f"findReqs;siteNumber=CX_1001,"
            f"facetsList={FACETS},"
            f"limit={PAGE_SIZE},"
            f"offset={offset},"
            f"sortBy=POSTING_DATES_DESC"
        )
        params = {"onlyData": "true", "expand": EXPAND, "finder": finder}
        try:
            resp = session.get(API_URL, params=params, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            break

        result = data.get("items", [{}])[0] if data.get("items") else {}
        req_list = result.get("requisitionList", [])
        total = result.get("TotalJobsCount", 0)

        if not req_list:
            break

        for item in req_list:
            job_id = item.get("Id")
            job_title = item.get("Title", "")
            if not job_title:
                continue

            location_str = item.get("PrimaryLocation") or None
            city, country = _split_location(location_str)
            job_url = JOB_URL_TEMPLATE.format(job_id=job_id) if job_id else JOBS_URL

            grade, deadline = _fetch_detail(session, job_id) if job_id else (None, None)

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

        if len(jobs) >= total:
            break
        offset += PAGE_SIZE

    return jobs


if __name__ == "__main__":
    print(json.dumps(scrape()))
