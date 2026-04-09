"""WFP Job Scraper - iterates Management_Level grade facet for authoritative grades."""

import requests
import json

AGENCY = "WFP"
AGENCY_NAME = "World Food Programme"
JOBS_URL = "https://wd3.myworkdaysite.com/recruiting/wfp/job_openings"
API_URL = "https://wd3.myworkdaysite.com/wday/cxs/wfp/job_openings/jobs"
DETAIL_BASE = "https://wd3.myworkdaysite.com/wday/cxs/wfp/job_openings"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Referer": JOBS_URL,
}


def _split_location(s):
    if not s or not isinstance(s, str):
        return None, None
    s = s.strip()
    if "," not in s:
        return None, s
    parts = s.split(",", 1)
    city = parts[0].strip() or None
    country = parts[1].strip() or None
    return city, country


def _fetch_deadline(session, external_path):
    try:
        detail = session.get(f"{DETAIL_BASE}{external_path}", headers=HEADERS, timeout=30)
        detail.raise_for_status()
        end_date = detail.json().get("jobPostingInfo", {}).get("endDate")
        return end_date[:10] if end_date else None
    except Exception:
        return None


def _fetch_grade_facets(session):
    """Fetch the first page and return Management_Level facet values as list of (descriptor, id)."""
    try:
        payload = {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
        resp = session.post(API_URL, json=payload, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        facets = resp.json().get("facets", [])
        for facet in facets:
            if facet.get("facetParameter") == "Management_Level":
                return [(v["descriptor"], v["id"]) for v in facet.get("values", [])]
    except Exception:
        pass
    return []


def _fetch_jobs_for_grade(session, grade_descriptor, grade_id):
    """Fetch all jobs for a given grade filter. Returns list of job dicts."""
    jobs = []
    offset = 0
    limit = 20

    while True:
        try:
            payload = {
                "appliedFacets": {"Management_Level": [grade_id]},
                "limit": limit,
                "offset": offset,
                "searchText": "",
            }
            resp = session.post(API_URL, json=payload, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            break

        postings = data.get("jobPostings", [])
        if not postings:
            break

        for job in postings:
            external_path = job.get("externalPath", "")
            if not external_path:
                continue
            slug = external_path.rstrip("/").split("/")[-1]
            url = f"https://wd3.myworkdaysite.com/en-US/recruiting/wfp/job_openings/details/{slug}"
            city, country = _split_location(job.get("locationsText"))
            deadline = _fetch_deadline(session, external_path)

            jobs.append({
                "agency": AGENCY,
                "agency_name": AGENCY_NAME,
                "job_title": job.get("title", ""),
                "grade": grade_descriptor,
                "city": city,
                "country": country,
                "deadline": deadline,
                "url": url,
            })

        total = data.get("total", 0)
        if offset + limit >= total:
            break
        offset += limit

    return jobs


def scrape() -> list[dict]:
    session = requests.Session()
    all_jobs = []

    grade_facets = _fetch_grade_facets(session)
    for descriptor, grade_id in grade_facets:
        all_jobs.extend(_fetch_jobs_for_grade(session, descriptor, grade_id))

    return all_jobs


if __name__ == "__main__":
    print(json.dumps(scrape()))
