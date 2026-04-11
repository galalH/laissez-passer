"""IFAD Job Scraper - scrapes from the IFAD careers portal."""

import requests
from bs4 import BeautifulSoup

from scrapers._utils import html_to_md, trim

AGENCY = "IFAD"
AGENCY_NAME = "International Fund for Agricultural Development"
JOBS_URL = "https://job.ifad.org/psc/IFHRPRDE/CAREERS/JOBS/c/HRS_HRAM_FL.HRS_CG_SEARCH_FL.GBL?Page=HRS_APP_SCHJOB_FL&Action=U"

BASE_URL = "https://job.ifad.org"
SEARCH_URL = "https://job.ifad.org/psc/IFHRPRDE/CAREERS/JOBS/c/HRS_HRAM_FL.HRS_CG_SEARCH_FL.GBL"
JOB_DETAIL_URL = (
    "https://job.ifad.org/psc/IFHRPRDE/CAREERS/JOBS/c/"
    "HRS_HRAM_FL.HRS_CE_JO_PST_FL.GBL"
    "?Page=HRS_CE_JO_PST_FL&Action=U&JobOpeningId={job_id}"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _parse_deadline(s):
    """Convert MM/DD/YYYY to YYYY-MM-DD format."""
    if not s:
        return None
    parts = s.split("/")
    if len(parts) != 3:
        return None
    month, day, year = parts
    return f"{year}-{month.zfill(2)}-{day.zfill(2)}"


def _get_session_and_icsid():
    session = requests.Session()
    session.headers.update(HEADERS)
    resp = session.get(JOBS_URL, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    icsid_el = soup.find("input", {"name": "ICSID"})
    state_el = soup.find("input", {"name": "ICStateNum"})
    icsid = icsid_el["value"] if icsid_el else ""
    state_num = state_el["value"] if state_el else "1"
    return session, icsid, state_num


def _fetch_job_listings(session, icsid, state_num):
    post_data = {
        "ICAJAX": "0",
        "ICNAVTYPEDROPDOWN": "0",
        "ICType": "Panel",
        "ICElementNum": "0",
        "ICStateNum": state_num,
        "ICAction": "NAV_PB$0",
        "ICModelCancel": "0",
        "ICXPos": "0",
        "ICYPos": "0",
        "ResponsetoDiffFrame": "-1",
        "TargetFrameName": "None",
        "FacetPath": "None",
        "PrmtTbl": "",
        "PrmtTbl_fn": "",
        "PrmtTbl_fv": "",
        "TA_SkipFldNms": "",
        "ICFocus": "",
        "ICSaveWarningFilter": "0",
        "ICChanged": "0",
        "ICSkipPending": "0",
        "ICAutoSave": "0",
        "ICResubmit": "0",
        "ICSID": icsid,
        "ICActionPrompt": "false",
        "ICTypeAheadID": "",
        "ICBcDomData": "",
        "ICDNDSrc": "",
        "ICPanelHelpUrl": "",
        "ICPanelName": "",
        "ICPanelControlStyle": "",
        "ICFind": "",
        "ICAddCount": "",
        "ICAppClsData": "",
        "HRS_SCH_WRK_HRS_SCH_TEXT100": "",
    }
    resp = session.post(SEARCH_URL, data=post_data, timeout=30)
    resp.raise_for_status()
    return resp.text


def _post_action(session, icsid, action, state_num):
    data = {
        "ICAJAX": "0", "ICNAVTYPEDROPDOWN": "0", "ICType": "Panel",
        "ICElementNum": "0", "ICStateNum": state_num, "ICAction": action,
        "ICModelCancel": "0", "ICXPos": "0", "ICYPos": "0",
        "ResponsetoDiffFrame": "-1", "TargetFrameName": "None",
        "FacetPath": "None", "PrmtTbl": "", "PrmtTbl_fn": "", "PrmtTbl_fv": "",
        "TA_SkipFldNms": "", "ICFocus": "", "ICSaveWarningFilter": "0",
        "ICChanged": "0", "ICSkipPending": "0", "ICAutoSave": "0",
        "ICResubmit": "0", "ICSID": icsid, "ICActionPrompt": "false",
        "ICTypeAheadID": "", "ICBcDomData": "", "ICDNDSrc": "",
        "ICPanelHelpUrl": "", "ICPanelName": "", "ICPanelControlStyle": "",
        "ICFind": "", "ICAddCount": "", "ICAppClsData": "",
        "HRS_SCH_WRK_HRS_SCH_TEXT100": "",
    }
    r = session.post(SEARCH_URL, data=data, timeout=30)
    r.raise_for_status()
    s = BeautifulSoup(r.text, "html.parser")
    state_el = s.find("input", {"name": "ICStateNum"})
    new_state = state_el["value"] if state_el else state_num
    return s, new_state


def _parse_jobs(html):
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    i = 0
    while True:
        title_el = soup.find("span", id=f"SCH_JOB_TITLE${i}")
        if not title_el:
            break

        job_id_el = soup.find("span", id=f"HRS_APP_JBSCH_I_HRS_JOB_OPENING_ID${i}")
        location_el = soup.find("span", id=f"LOCATION${i}")
        close_date_el = soup.find("span", id=f"HRS_JO_PST_CLS_DT${i}")
        close_descr_el = soup.find("span", id=f"HRS_CLS_DT_DESCR${i}")

        job_title = title_el.get_text(strip=True)
        job_id = job_id_el.get_text(strip=True) if job_id_el else ""

        location_raw = location_el.get_text(strip=True) if location_el else ""
        location = location_raw if location_raw else None

        deadline_raw = None
        if close_date_el:
            d = close_date_el.get_text(strip=True)
            if d:
                deadline_raw = d
        if not deadline_raw and close_descr_el:
            d = close_descr_el.get_text(strip=True)
            if d:
                deadline_raw = d
        deadline = _parse_deadline(deadline_raw)

        url = JOBS_URL

        jobs.append({
            "agency": AGENCY,
            "agency_name": AGENCY_NAME,
            "job_title": job_title,
            "grade": None,
            "city": location,
            "country": None,
            "deadline": deadline,
            "url": url,
        })
        i += 1

    return jobs


def _fetch_grades_and_descriptions(session, icsid, state_num, count):
    """Navigate to each job detail page and extract grade and description."""
    import re as _re
    grades = [None] * count
    descriptions = [None] * count
    if count == 0:
        return grades, descriptions

    soup_d, state_d = _post_action(session, icsid, "HRS_VIEW_DETAILSPB$0", state_num)
    for i in range(count):
        grade_el = soup_d.find(id="IFA_HRS_SCH_WRK_DESCR")
        grades[i] = grade_el.get_text(strip=True) if grade_el else None

        # Build description from labeled sections (label → bold heading + content)
        parts = []
        for lbl_el in soup_d.find_all(id=_re.compile(r'^HRS_SCH_WRK_DESCR100\$\d+lbl$')):
            n = _re.search(r'\$(\d+)lbl$', lbl_el['id']).group(1)
            label = lbl_el.get_text(strip=True)
            content_el = soup_d.find(id=f'HRS_SCH_PSTDSC_DESCRLONG${n}')
            content = html_to_md(str(content_el)) if content_el else None
            if content:
                parts.append(f'**{label}**\n\n{content}')
        description = '\n\n'.join(parts) or None
        description = trim(description, after="**Other Information**")
        descriptions[i] = description

        if i < count - 1:
            soup_d, state_d = _post_action(
                session, icsid, "DERIVED_HRS_FLU_HRS_NEXT_PB", state_d
            )

    return grades, descriptions


def scrape() -> list:
    session, icsid, state_num = _get_session_and_icsid()
    html = _fetch_job_listings(session, icsid, state_num)

    soup_listing = BeautifulSoup(html, "html.parser")
    state_el = soup_listing.find("input", {"name": "ICStateNum"})
    listing_state = state_el["value"] if state_el else state_num

    jobs = _parse_jobs(html)
    grades, descriptions = _fetch_grades_and_descriptions(session, icsid, listing_state, len(jobs))
    for job, grade, description in zip(jobs, grades, descriptions):
        job["grade"] = grade or None
        job["description"] = description

    return jobs


if __name__ == "__main__":
    import json
    print(json.dumps(scrape()))
