"""Scraper for UNAIDS (Joint United Nations Programme on HIV/AIDS) job openings.

API endpoints provide XML feeds for:
- Professional vacancies
- General Service positions
- Internships

Each endpoint returns XML with job listings that are parsed and deduplicated.
"""

import requests
import xml.etree.ElementTree as ET
from typing import Optional

AGENCY = "UNAIDS"
AGENCY_NAME = "Joint United Nations Programme on HIV/AIDS"

# XML API endpoints
ENDPOINTS = [
    "https://erecruit.unaids.org/xml/xml_unaids_ppub.asp",  # Professional vacancies
    "https://erecruit.unaids.org/xml/xml_unaids_gpub.asp",  # General Service
    "https://erecruit.unaids.org/xml/xml_unaids_iship.asp",  # Internships
]

JOB_DETAIL_URL_TEMPLATE = "https://erecruit.unaids.org/public/hrd-cl-vac-view.asp?o_c=1000&jobinfo_uid_c={uid}&vaclng=en"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def parse_closing_date(closing_date_str: Optional[str]) -> Optional[str]:
    """
    Parse closing date from various formats.
    Returns the date string as-is if provided (YYYYMMDD format or other).
    """
    if not closing_date_str:
        return None
    return closing_date_str.strip() if isinstance(closing_date_str, str) else None


def _parse_deadline(s: Optional[str]) -> Optional[str]:
    """
    Convert deadline from YYYYMMDD format to YYYY-MM-DD format.
    If s is 8 digits, convert to YYYY-MM-DD. Otherwise return None.
    """
    if not s:
        return None
    s = s.strip() if isinstance(s, str) else None
    if s and len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


def _parse_location(location: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """
    Parse location string into city and country using last-comma split.
    If comma present: city=before last comma, country=after last comma.
    If no comma: city=value, country=None.
    """
    if not location:
        return None, None
    location = location.strip()
    if ',' in location:
        parts = location.rsplit(',', 1)
        city = parts[0].strip()
        country = parts[1].strip()
        return city, country
    else:
        return location, None


def extract_text_from_element(element, tag: str) -> Optional[str]:
    """Extract text from an XML element by tag name, handling missing elements."""
    if element is None:
        return None
    child = element.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return None


def parse_job_from_xml(job_element) -> Optional[dict]:
    """
    Parse a single job from an XML job element.
    Extracts common fields and handles various tag name possibilities.
    The actual structure uses JobPositionInformation wrapper with specific tag names.
    """
    if job_element is None:
        return None

    try:
        # The structure is: JobPositionPosting > JobPositionInformation
        # Try to find JobPositionInformation child first
        info_element = job_element.find("JobPositionInformation")
        if info_element is None:
            # If not found, use the job_element itself
            info_element = job_element

        # Extract jobinfo_uid_c (unique identifier) - try multiple tag names
        uid = extract_text_from_element(info_element, "JobPositionPostingId")
        if not uid:
            uid = extract_text_from_element(info_element, "jobinfo_uid_c")
        if not uid:
            uid = extract_text_from_element(info_element, "uid")
        if not uid:
            uid = extract_text_from_element(info_element, "id")

        if not uid:
            return None

        # Extract title - try multiple possible tag names
        title = extract_text_from_element(info_element, "JobPositionTitle")
        if not title:
            title = extract_text_from_element(info_element, "title")
        if not title:
            title = extract_text_from_element(info_element, "job_title")
        if not title:
            title = extract_text_from_element(info_element, "position_title")

        if not title:
            return None

        # Extract grade/level - try multiple possible tag names
        grade = extract_text_from_element(info_element, "JobPositionGrade")
        if not grade:
            grade = extract_text_from_element(info_element, "grade")
        if not grade:
            grade = extract_text_from_element(info_element, "level")
        if not grade:
            grade = extract_text_from_element(info_element, "post_level")

        # Extract location - try multiple possible tag names
        location = extract_text_from_element(info_element, "JobPositionDutyStation")
        if not location:
            location = extract_text_from_element(info_element, "location")
        if not location:
            location = extract_text_from_element(info_element, "duty_station")
        if not location:
            location = extract_text_from_element(info_element, "location_duty_station")

        # Extract closing/deadline date - try multiple possible tag names
        closing_date = extract_text_from_element(info_element, "JobPositionClosingDate")
        if not closing_date:
            closing_date = extract_text_from_element(info_element, "closing_date")
        if not closing_date:
            closing_date = extract_text_from_element(info_element, "deadline")
        if not closing_date:
            closing_date = extract_text_from_element(info_element, "closing_deadline")

        closing_date = parse_closing_date(closing_date)
        deadline = _parse_deadline(closing_date)

        # Parse location into city and country
        city, country = _parse_location(location)

        # Construct job detail URL
        job_url = JOB_DETAIL_URL_TEMPLATE.format(uid=uid)

        return {
            "agency": AGENCY,
            "agency_name": AGENCY_NAME,
            "job_title": title,
            "grade": grade,
            "city": city,
            "country": country,

            "deadline": deadline,
            "url": job_url,
        }

    except Exception:
        return None


def scrape() -> list[dict]:
    """
    Scrapes UNAIDS job listings from all three XML endpoints.
    Returns a list of job dictionaries, deduplicated by jobinfo_uid_c.

    Structure: root > JobPositionPosting > JobPositionInformation
    """
    jobs = []
    seen_uids = set()

    for endpoint_url in ENDPOINTS:
        try:
            response = requests.get(endpoint_url, headers=HEADERS, timeout=30)
            response.raise_for_status()

            # Parse XML
            root = ET.fromstring(response.content)

            # Find all JobPositionPosting elements (the primary structure)
            job_elements = root.findall("JobPositionPosting")

            # If no "JobPositionPosting" elements found, try alternative tag names
            if not job_elements:
                job_elements = root.findall("job")
            if not job_elements:
                job_elements = root.findall("jobinfo")
            if not job_elements:
                job_elements = root.findall("vacancy")
            if not job_elements:
                # Try direct iteration over all children
                job_elements = list(root)

            for job_element in job_elements:
                # Skip non-job elements and root element
                if job_element.tag in ["root"]:
                    continue

                parsed_job = parse_job_from_xml(job_element)

                if parsed_job:
                    # Extract UID for deduplication
                    info_element = job_element.find("JobPositionInformation")
                    if info_element is None:
                        info_element = job_element

                    uid_elem = info_element.find("JobPositionPostingId")
                    if uid_elem is None:
                        uid_elem = info_element.find("jobinfo_uid_c")
                    if uid_elem is None:
                        uid_elem = info_element.find("uid")
                    if uid_elem is None:
                        uid_elem = info_element.find("id")

                    uid = uid_elem.text if uid_elem is not None else None

                    # Deduplicate by UID
                    if uid and uid not in seen_uids:
                        seen_uids.add(uid)
                        jobs.append(parsed_job)
                    elif not uid:
                        # If no UID, add it anyway (no way to deduplicate)
                        jobs.append(parsed_job)

        except requests.RequestException:
            # Continue to next endpoint on network errors
            continue
        except ET.ParseError:
            # Continue to next endpoint on XML parse errors
            continue
        except Exception:
            # Continue to next endpoint on other errors
            continue

    return jobs


if __name__ == "__main__":
    import json
    print(json.dumps(scrape()))
