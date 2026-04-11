"""CTBTO Job Scraper - uses SAP SuccessFactors DWR API in pure Python."""

import re
import uuid
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

from scrapers._utils import html_to_md, trim

AGENCY = "CTBTO"
AGENCY_NAME = "Preparatory Commission for the Comprehensive Nuclear-Test-Ban Treaty Organization"
JOBS_URL = "https://career2.successfactors.eu/career?company=ctbtoprepa&career_ns=job_listing_summary&navBarLevel=JOB_SEARCH"
DWR_URL = "https://career2.successfactors.eu/xi/ajax/remoting/call/plaincall/careerJobSearchControllerProxy.searchJobs.dwr"
DETAIL_BASE = "https://career2.successfactors.eu/career?career_ns=job_listing&company=ctbtoprepa&navBarLevel=JOB_SEARCH&rcm_site_locale=en_GB&career_job_req_id="

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

MONTH_MAP = {
    "January": "01", "February": "02", "March": "03", "April": "04",
    "May": "05", "June": "06", "July": "07", "August": "08",
    "September": "09", "October": "10", "November": "11", "December": "12",
}


def parse_verbose_date(date_str: str) -> str | None:
    """Convert '1 April 2026' -> '2026-04-01'."""
    if not date_str:
        return None
    m = re.match(r"(\d{1,2})\s+(\w+)\s+(\d{4})", date_str.strip())
    if m:
        day, month, year = m.groups()
        month_num = MONTH_MAP.get(month)
        if month_num:
            return f"{year}-{month_num}-{day.zfill(2)}"
    return None


def parse_dwr_jobs(dwr_text: str) -> list[dict]:
    """Extract job listings from DWR response."""
    jobs = []
    # Each job object has .id=NUMBER — find all such variables
    for var, job_id in re.findall(r"(s\d+)\.id=(\d+);", dwr_text):
        title_m = re.search(rf"{re.escape(var)}\.title=\"((?:[^\"\\\\]|\\\\.)*)\";", dwr_text)
        if not title_m:
            continue
        jobs.append({
            "id": int(job_id),
            "title": title_m.group(1),
        })
    return jobs


def fetch_detail(session: requests.Session, job_id: int) -> tuple[str | None, str | None, str | None]:
    """Fetch job detail page and return (grade, deadline, description)."""
    try:
        r = session.get(f"{DETAIL_BASE}{job_id}", timeout=30)
        html = r.text

        grade_m = re.search(
            r"Grade Level:</strong></td>\s*<td>[^<]*?([A-Z]-\d)", html
        )
        grade = grade_m.group(1) if grade_m else None

        deadline_m = re.search(
            r"Deadline for Applications</strong>.*?<td>\s*(\d{1,2}\s+\w+\s+\d{4})\s*</td>",
            html, re.DOTALL
        )
        deadline = parse_verbose_date(deadline_m.group(1)) if deadline_m else None

        soup = BeautifulSoup(html, "html.parser")

        # Find the <p> containing "Organizational Setting" and collect
        # all following siblings up to (not including) "Additional Information"
        posting = soup.find("div", class_="externalPosting")
        description = html_to_md(str(posting)) if posting else None
        description = trim(
            description,
            start=re.compile(r"\*{0,2}organizational\s+setting", re.IGNORECASE),
            after=re.compile(r"\n+[#*\s]*additional\s+information", re.IGNORECASE),
        )

        return grade, deadline, description
    except Exception:
        return None, None, None


def scrape() -> list[dict]:
    session = requests.Session()
    session.headers.update(HEADERS)

    # Establish session and extract CSRF token
    r = session.get(JOBS_URL, timeout=30)
    m = re.search(r'var ajaxSecKey="([^"]+)"', r.text)
    if not m:
        return []
    ajax_sec_key = m.group(1)

    # Generate DWR script session ID
    script_session_id = uuid.uuid4().hex.upper() + "1"

    dwr_body = (
        "callCount=1\n"
        "page=/career?company=ctbtoprepa&career_ns=job_listing_summary&navBarLevel=JOB_SEARCH\n"
        "httpSessionId=\n"
        f"scriptSessionId={script_session_id}\n"
        "c0-scriptName=careerJobSearchControllerProxy\n"
        "c0-methodName=searchJobs\n"
        "c0-id=0\n"
        "c0-e1=null:null\n"
        "c0-e2=boolean:false\n"
        "c0-e3=Object_Object:{}\n"
        "c0-e4=null:null\n"
        "c0-e5=string:\n"
        "c0-e6=Array:[]\n"
        "c0-e7=Object_Object:{}\n"
        "c0-e9=Array:[]\n"
        "c0-e8=Object_Object:{customFilter_filter4:reference:c0-e9}\n"
        "c0-e10=null:null\n"
        "c0-e11=string:1\n"
        "c0-param0=Object_Object:{daysPostedWithin:reference:c0-e1, exactMatch:reference:c0-e2, "
        "fullySelectedPicklists:reference:c0-e3, jobReqId:reference:c0-e4, keyword:reference:c0-e5, "
        "keywordLanguageSelectedValues:reference:c0-e6, objSelectedValues:reference:c0-e7, "
        "picklistSelectedValues:reference:c0-e8, radialField:reference:c0-e10, "
        "searchScope:reference:c0-e11}\n"
        "batchId=1\n"
    )

    dwr_headers = {
        "Content-Type": "text/plain",
        "x-csrf-token": ajax_sec_key,
        "x-ajax-token": ajax_sec_key,
        "x-subaction": "1",
        "viewid": "/ui/rcmcareer/pages/careersite/career.jsp.xhtml",
        "Referer": JOBS_URL,
        "Origin": "https://career2.successfactors.eu",
        "X-Requested-With": "XMLHttpRequest",
    }

    resp = session.post(DWR_URL, data=dwr_body, headers=dwr_headers, timeout=30)
    resp.raise_for_status()

    raw_jobs = parse_dwr_jobs(resp.text)

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [(item, ex.submit(fetch_detail, session, item["id"])) for item in raw_jobs]

    jobs = []
    for item, fut in futures:
        grade, deadline, description = fut.result()
        jobs.append({
            "agency": AGENCY, "agency_name": AGENCY_NAME,
            "job_title": item["title"], "grade": grade,
            "city": "Vienna", "country": "Austria",
            "deadline": deadline,
            "url": f"{DETAIL_BASE}{item['id']}",
            "description": description,
        })
    return jobs


if __name__ == "__main__":
    import json
    print(json.dumps(scrape()))
