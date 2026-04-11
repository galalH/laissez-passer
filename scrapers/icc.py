"""ICC (International Criminal Court) Job Scraper - uses SAP SuccessFactors DWR API."""

import re
import uuid
import requests
import country_converter as coco
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

from scrapers._utils import html_to_md

AGENCY = "ICC"
AGENCY_NAME = "International Criminal Court"
_cc = coco.CountryConverter()
JOBS_URL = "https://career5.successfactors.eu/career?company=1657261P&career_ns=job_listing_summary&navBarLevel=JOB_SEARCH"
DWR_BASE = "https://career5.successfactors.eu/xi/ajax/remoting/call/plaincall/careerJobSearchControllerProxy.{method}.dwr"
DETAIL_BASE = "https://career5.successfactors.eu/career?career_ns=job_listing&company=1657261P&navBarLevel=JOB_SEARCH&rcm_site_locale=en_GB&career_job_req_id="


HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


_MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}


def _parse_deadline(date_str: str) -> str | None:
    """Parse DD/MM/YYYY or 'DD Month YYYY' to YYYY-MM-DD."""
    if not date_str:
        return None
    s = date_str.strip()
    if "/" in s:
        try:
            day, month, year = s.split("/")
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        except ValueError:
            return None
    parts = s.split()
    if len(parts) == 3:
        month = _MONTHS.get(parts[1].lower())
        if month:
            return f"{parts[2]}-{month}-{parts[0].zfill(2)}"
    return None


def _parse_duty_station(ds: str) -> tuple[str | None, str | None]:
    """Parse 'The Hague - NL' → (city, country)."""
    if not ds:
        return None, None

    parts = ds.strip().split(" - ")
    if len(parts) == 2:
        location, code = parts[0].strip(), parts[1].strip()
        country = _cc.convert(code, to="name_short", not_found=None)
        if country is None:
            return location, None
        city = None if location.lower() == country.lower() else location
        return city, country

    token = ds.strip()
    if "hague" in token.lower():
        return "The Hague", "Netherlands"

    return token, None


def _get_job_ids(dwr_text: str) -> list[int]:
    """Extract job IDs from DWR response by finding all 's\\d+.id=\\d+;' tokens."""
    seen = set()
    ids = []
    for job_id_str in re.findall(r's\d+\.id=(\d+);', dwr_text):
        job_id = int(job_id_str)
        if job_id not in seen:
            seen.add(job_id)
            ids.append(job_id)
    return ids


def _fetch_job(session: requests.Session, job_id: int) -> dict | None:
    """Fetch job detail page and extract title, grade, duty station, and deadline."""
    try:
        r = session.get(f"{DETAIL_BASE}{job_id}", timeout=30)
        html = r.text

        # Title from h1 — format: "Career Opportunities: Real Title (G-5) (12345)"
        title_m = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
        title = title_m.group(1).strip() if title_m else None
        if not title:
            return None
        title = re.sub(r'^Career Opportunities:\s*', '', title)
        title = re.sub(r'\s*\(\d+\)\s*$', '', title).strip()

        # Grade from title e.g. "(G-5)", "(P-3)", "(NO-C)"
        grade_m = re.search(r"\(([A-Z]{1,3}-[A-Z0-9])\)", title)
        grade = grade_m.group(1) if grade_m else None

        # Duty station — find <strong> containing "Duty Station:", walk up to
        # its <tr>, take the last <td>'s text (works for 2- and 3-column layouts
        # and any span nesting depth).
        city, country = None, None
        soup = BeautifulSoup(html, "html.parser")
        for strong in soup.find_all("strong"):
            if "Duty Station" in strong.get_text():
                row = strong.find_parent("tr")
                if row:
                    cells = row.find_all("td")
                    val = cells[-1].get_text(strip=True) if cells else None
                    if val:
                        city, country = _parse_duty_station(val)
                break

        # Deadline — "DD/MM/YYYY" or "DD Month YYYY"
        deadline_m = re.search(
            r"Deadline for Applications.*?(\d{1,2}/\d{1,2}/\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})",
            html, re.DOTALL
        )
        deadline = _parse_deadline(deadline_m.group(1)) if deadline_m else None

        desc_table = next(
            (t for t in soup.find_all("table")
             if len(t.get_text(strip=True)) > 100
             and "Grade Level" not in t.get_text()
             and "friend" not in t.get_text()),
            None
        )
        description = html_to_md(str(desc_table)) if desc_table else None

        return {
            "agency": AGENCY,
            "agency_name": AGENCY_NAME,
            "job_title": title,
            "grade": grade,
            "city": city,
            "country": country,
            "deadline": deadline,
            "url": f"{DETAIL_BASE}{job_id}",
            "description": description,
        }
    except Exception:
        return None


def _make_dwr_headers(ajax_sec_key: str) -> dict:
    return {
        "Content-Type": "text/plain",
        "x-csrf-token": ajax_sec_key,
        "x-ajax-token": ajax_sec_key,
        "x-subaction": "1",
        "viewid": "/ui/rcmcareer/pages/careersite/career.jsp.xhtml",
        "Referer": JOBS_URL,
        "Origin": "https://career5.successfactors.eu",
        "X-Requested-With": "XMLHttpRequest",
    }


def scrape() -> list[dict]:
    session = requests.Session()
    session.headers.update(HEADERS)

    # Establish session and extract CSRF token
    r = session.get(JOBS_URL, timeout=30)
    m = re.search(r'var ajaxSecKey="([^"]+)"', r.text)
    if not m:
        return []
    ajax_sec_key = m.group(1)
    dwr_headers = _make_dwr_headers(ajax_sec_key)

    script_session_id = uuid.uuid4().hex.upper() + "1"
    page_ref = "/career?company=1657261P&career_ns=job_listing_summary&navBarLevel=JOB_SEARCH"

    # Page 1 via getInitialJobSearchData to get total count
    init_body = (
        "callCount=1\n"
        f"page={page_ref}\n"
        "httpSessionId=\n"
        f"scriptSessionId={script_session_id}\n"
        "c0-scriptName=careerJobSearchControllerProxy\n"
        "c0-methodName=getInitialJobSearchData\n"
        "c0-id=0\n"
        "c0-e1=string:\n"
        "c0-e2=string:\n"
        "c0-e3=string:\n"
        "c0-e4=string:UTC\n"
        "c0-param0=Object_Object:{filterOnly:reference:c0-e1, jobAlertId:reference:c0-e2, "
        "returnToList:reference:c0-e3, browserTimeZone:reference:c0-e4}\n"
        "batchId=0\n"
    )

    resp1 = session.post(
        DWR_BASE.format(method="getInitialJobSearchData"),
        data=init_body, headers=dwr_headers, timeout=30
    )
    resp1.raise_for_status()

    total_m = re.search(r"\.totalCount=(\d+);", resp1.text)
    total_count = int(total_m.group(1)) if total_m else 0

    # Fetch all jobs in one search call using totalCount as pageSize
    search_body = (
        "callCount=1\n"
        f"page={page_ref}\n"
        "httpSessionId=\n"
        f"scriptSessionId={script_session_id}\n"
        "c0-scriptName=careerJobSearchControllerProxy\n"
        "c0-methodName=search\n"
        "c0-id=0\n"
        "c0-e2=number:1\n"
        f"c0-e3=number:{total_count}\n"
        "c0-e4=boolean:false\n"
        f"c0-e5=number:{total_count}\n"
        "c0-e6=number:1\n"
        f"c0-e7=number:{total_count}\n"
        "c0-e1=Object_Object:{currentPage:reference:c0-e2, endRow:reference:c0-e3, "
        "increaseCandSummaryPagination:reference:c0-e4, pageSize:reference:c0-e5, "
        "startRow:reference:c0-e6, totalCount:reference:c0-e7}\n"
        "c0-e8=string:JOB_POSTING_DATE\n"
        "c0-e9=string:DESC\n"
        "c0-param0=Object_Object:{pagination:reference:c0-e1, sortByColumn:reference:c0-e8, "
        "sortOrder:reference:c0-e9}\n"
        "batchId=1\n"
    )
    resp_all = session.post(
        DWR_BASE.format(method="search"),
        data=search_body, headers=dwr_headers, timeout=30
    )
    resp_all.raise_for_status()

    job_ids = _get_job_ids(resp_all.text)

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(_fetch_job, session, job_id) for job_id in job_ids]

    return [job for fut in futures if (job := fut.result()) is not None]


if __name__ == "__main__":
    import json
    print(json.dumps(scrape()))
