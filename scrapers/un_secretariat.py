"""Scraper for the UN Secretariat central job portal (careers.un.org)."""

import requests

from scrapers._utils import html_to_md

AGENCY = "UNS"
unknown_depts: set[str] = set()

DEPT_ABBR = {
    "Department of Global Communications": "DGC",
    "Economic Commission for Africa": "ECA",
    "Economic Commission for Europe": "ECE",
    "Economic Commission for Latin America and the Caribbean": "ECLAC",
    "Economic and Social Commission for Asia and the Pacific": "ESCAP",
    "Secretariat of the Advisory Committee on Administrative and Budgetary Questions": "ACABQ",
    "Economic and Social Commission for Western Asia": "ESCWA",
    "United Nations Office at Geneva": "UNOG",
    "Office of the High Commissioner for Human Rights": "OHCHR",
    "Office of the SRSG for Children and Armed Conflict": "SRSG-CAAC",
    "Executive Office of the Secretary-General": "EOSG",
    "United Nations Human Settlements Programme": "UN-HABITAT",
    "United Nations Conference on Trade and Development": "UNCTAD",
    "United Nations Environment Programme": "UNEP",
    "United Nations Interregional Crime and Justice Research Institute": "UNICRI",
    "United Nations Office at Vienna": "UNOV",
    "Office of Internal Oversight Services": "OIOS",
    "International Court of Justice": "ICJ",
    "Department of Economic and Social Affairs": "DESA",
    "United Nations Office at Nairobi": "UNON",
    "Office for Disarmament Affairs": "ODA",
    "Office for the Coordination of Humanitarian Affairs": "OCHA",
    "United Nations Office for Disaster Risk Reduction": "UNDRR",
    "Convention to Combat Desertification": "UNCCD",
    "United Nations Office on Drugs and Crime": "UNODC",
    "Regional Service Centre at Entebbe": "RSCE",
    "UN Office to the African Union": "UNOAU",
    "United Nations Support Mission in Libya": "UNSMIL",
    "United Nations Mission for the Referendum in Western Sahara": "MINURSO",
    "United Nations Disengagement Observer Force": "UNDOF",
    "United Nations Peacekeeping Force in Cyprus": "UNFICYP",
    "United Nations Logistic Base": "UNLB",
    "United Nations Observer Group in India and Pakistan": "UNMOGIP",
    "United Nations Assistance Mission in Afghanistan": "UNAMA",
    "United Nations Regional Center for Preventive Diplomacy for Central Asia": "UNRCCA",
    "Office of the United Nations Ombudsman and Mediation Services": "UNOMS",
    "Department of Safety and Security": "DSS",
    "Counter-Terrorism Committee Executive Directorate": "CTED",
    "Ethics Office": "UNS",
    "Resident Coordinator System": "RCS",
    "Department of Operational Support": "DOS",
    "Department of Political and Peacebuilding Affairs": "DPPA",
    "Department of Peace Operations": "DPO",
    "United Nations Joint Staff Pension Fund": "UNJSPF",
    "United Nations Joint Staff Pension Fund - Pension Administration": "UNJSPF",
    "United Nations Joint Staff Pension Fund \u2013 Office of Investment Management": "UNJSPF",
    "Office of the Special Representative of the Secretary-General on Sexual Violence": "SRSG-SVC",
    "Office of the Special Representative to the Secretary-General on Violence Against Children": "SRSG-VAC",
    "Rosters Administered by Department of Operational Support": "UNS",
    "INDEPENDENT INVESTIGATIVE MECHANISM FOR MYANMAR": "IIMM",
    "United Nations Office for Outer Space Affairs": "UNOOSA",
    "International Civil Aviation Organization": "ICAO",
    "Independent Institution on Missing Persons in the Syrian Arab Republic (IIMP)": "IIMP",
    "UN Support Office in Haiti": "UNSOH",
    "Independent Investigative Mechanism for Afghanistan": "IIMA",
    "Office of Administration of Justice": "OAJ",
    "Office of Information and Communications Technology": "OICT",
    "International Trade Centre": "ITC",
    "International Seabed Authority": "ISA",
    "Operations and Risk Management Unit": "UNS",
    "United Nations Secretariat": "UNS",
    "Department of Management Strategy, Policy and Compliance Office of Human Resources": "DMSPC",
    "Department of Management Strategy, Policy and Compliance Office of Programme Planning, Finance and Budget": "DMSPC",
    "Office of Counter-Terrorism": "OCT",
    "Logistics": "UNS",
    "Syria International, Impartial and Independent Mechanism": "IIIM",
    "Engineering & Facility Maintenance": "UNS",
    "Department of Political and Peacebuilding Affairs-Department of Peace Operations-Shared Structure": "DPPA",
    "Administrative and Personnel Division": "UNS",
    "Publications Division": "UNS",
    "United Nations Relief and Works Agency (UNRWA)": "UNRWA",
    "UNRWA - Programme Relief & Social Services - Headquarters Amman": "UNRWA",
    "UNRWA - Information Management - Headquarters Amman": "UNRWA",
    "UNRWA - External Relations - Headquarters Amman": "UNRWA",
}
JOBS_URL = "https://careers.un.org/jobopening"

API_URL = "https://careers.un.org/api/public/opening/jo/list/filteredV2/en"
ITEMS_PER_PAGE = 50
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://careers.un.org",
    "Referer": "https://careers.un.org/jobopening?language=en",
    "Content-Type": "application/json",
}


def scrape() -> list[dict]:
    """Scrape all job openings from careers.un.org via its JSON API."""
    all_jobs = []
    page = 0

    while True:
        payload = {
            "filterConfig": {},
            "pagination": {
                "page": page,
                "itemPerPage": ITEMS_PER_PAGE,
                "sortBy": "startDate",
                "sortDirection": -1,
            },
        }
        resp = requests.post(API_URL, json=payload, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        items = data.get("list", [])

        if not items:
            break

        for item in items:
            duty_stations = item.get("dutyStation", [])
            city = ", ".join(ds.get("description", "") for ds in duty_stations) if duty_stations else None
            dept = item.get("dept", {})
            dept_name = dept.get("name", "")
            if dept_name and dept_name not in DEPT_ABBR:
                unknown_depts.add(dept_name)
            agency_abbr = DEPT_ABBR.get(dept_name, "UNS")
            deadline = item.get("endDate")

            desc_html = item.get("jobDescription") or ""
            description = html_to_md(desc_html)

            all_jobs.append({
                "agency": agency_abbr,
                "agency_name": dept_name or "United Nations Secretariat",
                "job_title": item.get("postingTitle") or item.get("jobTitle", ""),
                "grade": item.get("jobLevel"),
                "city": city,
                "country": None,
                "deadline": deadline[:10] if deadline else None,
                "url": f"https://careers.un.org/jobSearchDescription/{item.get('jobId')}",
                "description": description,
            })

        total_count = items[0].get("totalCount", 0) if items else 0
        if (page + 1) * ITEMS_PER_PAGE >= total_count:
            break
        page += 1

    return all_jobs


if __name__ == "__main__":
    import json
    print(json.dumps(scrape()))
