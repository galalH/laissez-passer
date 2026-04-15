"""WMO Job Scraper - uses the Oracle HCM Cloud REST API."""

import re
import requests
import json
from concurrent.futures import ThreadPoolExecutor

from scrapers._utils import html_to_md, trim

AGENCY = "WMO"
AGENCY_NAME = "World Meteorological Organization"
JOBS_URL = "https://estm.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_5001/jobs"
API_BASE = "https://estm.fa.em2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
DETAIL_API = "https://estm.fa.em2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

_DESC_FIELDS = ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")


def _split_location(s):
    if s is None:
        return None, None
    if "home based" in s.lower():
        return "Home Based", None
    if "," in s:
        parts = s.rsplit(",", 1)
        return parts[0].strip(), parts[1].strip()
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
        start_date = item.get("ExternalPostedStartDate") or None
        pubdate = start_date[:10] if start_date else None
        parts = [html_to_md(item.get(f) or "") or "" for f in _DESC_FIELDS]
        description = "\n\n".join(p for p in parts if p) or None
        description = trim(description, after=re.compile(r"\n[^\n]*?\*+[^*\n]*additional information[^*\n]*\*+", re.IGNORECASE))
        return grade, deadline, pubdate, description
    except Exception:
        return None, None, None


def scrape() -> list[dict]:
    session = requests.Session()
    session.headers.update(HEADERS)
    stubs = []
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
            job_url = f"https://estm.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_5001/job/{job_id}"
            stubs.append({"_id": job_id, "agency": AGENCY, "agency_name": AGENCY_NAME,
                          "job_title": job_title, "city": city, "country": country, "url": job_url})

        total_jobs = search_result.get("TotalJobsCount", 0)
        if offset + limit >= total_jobs:
            break
        offset += limit

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [(s, ex.submit(_fetch_detail, session, s.pop("_id"))) for s in stubs]

    jobs = []
    for stub, fut in futures:
        grade, deadline, pubdate, description = fut.result()
        jobs.append({**stub, "grade": grade, "deadline": deadline, "pubdate": pubdate, "description": description})
    return jobs


if __name__ == "__main__":
    print(json.dumps(scrape()))
