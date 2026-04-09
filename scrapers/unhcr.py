"""UNHCR Job Scraper - uses the Workday CXS JSON API."""

import requests
import json

AGENCY = "UNHCR"
AGENCY_NAME = "United Nations High Commissioner for Refugees"
JOBS_URL = "https://unhcr.wd3.myworkdayjobs.com/External"

API_URL = "https://unhcr.wd3.myworkdayjobs.com/wday/cxs/unhcr/External/jobs"
DETAIL_BASE = "https://unhcr.wd3.myworkdayjobs.com/wday/cxs/unhcr/External"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Referer": JOBS_URL,
}


def _split_location(location_str):
    """Split location string on the last comma to extract city and country.

    Args:
        location_str: String in "City, Country" format or None

    Returns:
        Tuple of (city, country). If no comma found, returns (city, None).
        If input is None, returns (None, None).
    """
    if location_str is None:
        return None, None

    if "," not in location_str:
        return location_str.strip(), None

    # Split on last comma
    parts = location_str.rsplit(",", 1)
    city = parts[0].strip()
    country = parts[1].strip()
    return city, country


def scrape() -> list[dict]:
    jobs = []
    offset = 0
    limit = 20

    while True:
        try:
            payload = {"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": ""}
            resp = requests.post(API_URL, json=payload, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            postings = data.get("jobPostings", [])
            if not postings:
                break

            for job in postings:
                title = job.get("title", "")
                location_str = job.get("locationsText") or None
                city, country = _split_location(location_str)

                grade = None
                bullet = job.get("bulletFields", [])
                if len(bullet) > 1:
                    grade = bullet[1]

                external_path = job.get("externalPath", "")
                if not external_path:
                    continue
                slug = external_path.rstrip("/").split("/")[-1]
                url = f"https://unhcr.wd3.myworkdayjobs.com/en-US/External/details/{slug}"

                deadline = None
                try:
                    detail = requests.get(f"{DETAIL_BASE}{external_path}", headers=HEADERS, timeout=30)
                    detail.raise_for_status()
                    end_date = detail.json().get("jobPostingInfo", {}).get("endDate")
                    if end_date:
                        deadline = end_date[:10]
                except Exception:
                    pass

                jobs.append({
                    "agency": AGENCY,
                    "agency_name": AGENCY_NAME,
                    "job_title": title,
                    "grade": grade,
                    "city": city,
                    "country": country,
                    "deadline": deadline,
                    "url": url,
                })

            total = data.get("total", 0)
            if offset + limit >= total:
                break
            offset += limit

        except Exception:
            break

    return jobs


if __name__ == "__main__":
    print(json.dumps(scrape()))
