"""UN Women Job Scraper - uses the Oracle HCM Cloud REST API."""

import re
import requests
from concurrent.futures import ThreadPoolExecutor

from scrapers._utils import html_to_md, trim

AGENCY = "UN Women"
AGENCY_NAME = "United Nations Entity for Gender Equality and the Empowerment of Women"
BASE_URL = "https://estm.fa.em2.oraclecloud.com"
JOBS_URL = f"{BASE_URL}/hcmUI/CandidateExperience/en/sites/CX_1001/jobs"
API_URL = f"{BASE_URL}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
DETAIL_API_URL = f"{BASE_URL}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
JOB_URL_TEMPLATE = f"{BASE_URL}/hcmUI/CandidateExperience/en/sites/CX_1001/requisitions/job/{{job_id}}"

EXPAND = (
    "requisitionList.workLocation,"
    "requisitionList.otherWorkLocations,"
    "requisitionList.secondaryLocations,"
    "flexFieldsFacet.values,"
    "requisitionList.requisitionFlexFields"
)
FACETS = "LOCATIONS;WORK_LOCATIONS;WORKPLACE_TYPES;TITLES;CATEGORIES;ORGANIZATIONS;POSTING_DATES;FLEX_FIELDS"
PAGE_SIZE = 100

GRADE_RE = re.compile(
    r'\b(GS-?\d+|G-?\d|P-?\d|D-?\d|FS-?\d|SB-?\d|SC-?\d|L-?\d|NO[-\s]?[A-Ea-e]|NO[-\s]?\d)\b',
    re.IGNORECASE,
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": JOBS_URL,
}

_DESC_FIELDS = ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")


def _split_location(location_str):
    if not location_str:
        return None, None
    if "," in location_str:
        last_comma_idx = location_str.rfind(",")
        return location_str[:last_comma_idx].strip(), location_str[last_comma_idx + 1:].strip()
    return location_str.strip(), None


def _fetch_detail(session, job_id):
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
        parts = [html_to_md(item.get(f) or "") or "" for f in _DESC_FIELDS]
        description = "\n\n".join(p for p in parts if p) or None
        # Remove opening boilerplate paragraph containing the mission statement
        _MARKER = "grounded in the vision of equality"
        if description and _MARKER in description:
            paragraphs = description.split('\n\n')
            paragraphs = [p for p in paragraphs if _MARKER not in p]
            description = '\n\n'.join(paragraphs).strip() or None
        # Strip footer — whichever sentinel appears first
        if description:
            for _sentinel in ("At UN Women, we are committed", "Statements:"):
                if _sentinel in description:
                    description = trim(description, after=_sentinel)
                    break
        return grade, deadline, description
    except Exception:
        return None, None, None


def scrape() -> list[dict]:
    session = requests.Session()
    stubs = []
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
            stubs.append({"_id": job_id, "agency": AGENCY, "agency_name": AGENCY_NAME,
                          "job_title": job_title, "city": city, "country": country, "url": job_url})

        if len(stubs) >= total:
            break
        offset += PAGE_SIZE

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [(s, ex.submit(_fetch_detail, session, s.pop("_id"))) for s in stubs]

    jobs = []
    for stub, fut in futures:
        grade, deadline, description = fut.result()
        if grade is None:
            m = GRADE_RE.search(stub["job_title"])
            if m:
                grade = re.sub(r'\s+', '-', m.group(1).upper())
        jobs.append({**stub, "grade": grade, "deadline": deadline, "description": description})
    return jobs


if __name__ == "__main__":
    import json
    print(json.dumps(scrape()))
