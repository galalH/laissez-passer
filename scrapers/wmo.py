"""WMO Job Scraper - uses the Oracle HCM Cloud REST API."""

import requests
import json

AGENCY = "WMO"
AGENCY_NAME = "World Meteorological Organization"
JOBS_URL = "https://estm.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_5001/jobs"
API_BASE = "https://estm.fa.em2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
DETAIL_API = "https://estm.fa.em2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def _split_location(s):
    """Split location string into city and country components.

    Args:
        s: Location string (e.g., "Geneve, Switzerland" or "Home Based")

    Returns:
        Tuple of (city, country) where both are strings or None
    """
    if s is None:
        return None, None

    # Check if "Home Based" appears in the string
    if "home based" in s.lower():
        # Return city="Home Based", country=None
        return "Home Based", None

    # Split on last comma
    if "," in s:
        parts = s.rsplit(",", 1)
        city = parts[0].strip()
        country = parts[1].strip()
        return city, country

    # No comma: return as city, no country
    return s, None


def _fetch_detail(session, job_id):
    try:
        params = {
            "expand": "all",
            "onlyData": "true",
            "finder": f'ById;Id="{job_id}",siteNumber=CX_5001',
        }
        resp = session.get(DETAIL_API, params=params, timeout=30)
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
    session.headers.update(HEADERS)
    jobs = []
    offset = 0
    limit = 25

    while True:
        finder_param = (
            f"findReqs;siteNumber=CX_5001,"
            f"facetsList=LOCATIONS;WORK_LOCATIONS;WORKPLACE_TYPES;TITLES;CATEGORIES;ORGANIZATIONS;POSTING_DATES;FLEX_FIELDS,"
            f"limit={limit},offset={offset},sortBy=POSTING_DATES_DESC"
        )
        params = {
            "onlyData": "true",
            "expand": "requisitionList.workLocation,requisitionList.otherWorkLocations,requisitionList.secondaryLocations,flexFieldsFacet.values,requisitionList.requisitionFlexFields",
            "finder": finder_param,
        }

        try:
            resp = session.get(API_BASE, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            break

        items = data.get("items", [])
        if not items:
            break

        search_result = items[0]
        requisition_list = search_result.get("requisitionList", [])
        if not requisition_list:
            break

        for job in requisition_list:
            job_title = job.get("Title", "").strip()
            job_id = job.get("Id", "").strip()
            if not job_title or not job_id:
                continue

            location_str = job.get("PrimaryLocation", "").strip() or None
            city, country = _split_location(location_str)

            grade, deadline = _fetch_detail(session, job_id)
            job_url = f"https://estm.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_5001/job/{job_id}"

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

        total_jobs = search_result.get("TotalJobsCount", 0)
        if offset + limit >= total_jobs:
            break
        offset += limit

    return jobs


if __name__ == "__main__":
    print(json.dumps(scrape()))
