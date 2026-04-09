"""Grade normalization for UN jobs scraper."""
from __future__ import annotations
import re


# ---------------------------------------------------------------------------
# Helpers to build the map programmatically for grade ranges
# ---------------------------------------------------------------------------

def _p(nums: range, prefix: str, category: str) -> dict[str, tuple[str, str]]:
    """Generate hyphenated and non-hyphenated variants for a numeric grade range."""
    out = {}
    for n in nums:
        canonical = f"{prefix}-{n}"
        out[canonical] = (canonical, category)
        out[f"{prefix}{n}"] = (canonical, category)
    return out


def _letter(letters: str, prefix: str, category: str) -> dict[str, tuple[str, str]]:
    """Generate hyphenated and non-hyphenated variants for a letter grade range."""
    out = {}
    for ch in letters:
        canonical = f"{prefix}-{ch}"
        out[canonical] = (canonical, category)
        out[f"{prefix}{ch}"] = (canonical, category)
    return out


# ---------------------------------------------------------------------------
# Main mapping table
# ---------------------------------------------------------------------------

GRADE_MAP: dict[str, tuple[str | None, str]] = {}

# P-series: P-1 to P-5 Professional, P-6/P-7 Director
GRADE_MAP.update(_p(range(1, 6), "P", "Professional"))
GRADE_MAP.update(_p(range(6, 8), "P", "Director"))

# PR-series (UNHCR): map to standard P grades
GRADE_MAP.update({f"PR-{n}": (f"P-{n}", "Professional") for n in range(1, 6)})
GRADE_MAP.update({f"PR{n}": (f"P-{n}", "Professional") for n in range(1, 6)})
GRADE_MAP.update({f"PR-{n}": (f"P-{n}", "Director") for n in range(6, 8)})
GRADE_MAP.update({f"PR{n}": (f"P-{n}", "Director") for n in range(6, 8)})

# D-series
GRADE_MAP.update(_p(range(1, 3), "D", "Director"))
GRADE_MAP["ADG"] = ("ADG", "Director")

# IP P-series and IP D-series (UNOPS) — mapped to standard grades
GRADE_MAP.update({f"IP P-{n}": (f"P-{n}", "Professional") for n in range(1, 6)})
GRADE_MAP.update({f"IP P-{n}": (f"P-{n}", "Director") for n in range(6, 8)})
GRADE_MAP.update({f"IP D-{n}": (f"D-{n}", "Director") for n in range(1, 3)})

# FS-series
GRADE_MAP.update(_p(range(1, 8), "FS", "Field Service"))

# G-series
GRADE_MAP.update(_p(range(1, 8), "G", "General Service"))

# GS-series (UNICEF, UNHCR): map to standard G grades
GRADE_MAP.update({f"GS-{n}": (f"G-{n}", "General Service") for n in range(1, 8)})
GRADE_MAP.update({f"GS{n}": (f"G-{n}", "General Service") for n in range(1, 8)})

# NO-series: letters A-E and numbers 1-5
GRADE_MAP.update(_letter("ABCDE", "NO", "National Officer"))
_NO_NUM_TO_LETTER = dict(enumerate("ABCDE", 1))
GRADE_MAP.update({f"NO-{n}": (f"NO-{_NO_NUM_TO_LETTER[n]}", "National Officer") for n in range(1, 6)})
GRADE_MAP.update({f"NO{n}": (f"NO-{_NO_NUM_TO_LETTER[n]}", "National Officer") for n in range(1, 6)})

# ISA-series (UNIDO) — mapped to standard grades
GRADE_MAP.update({f"ISA-G{n}": (f"G-{n}", "General Service") for n in range(1, 8)})
GRADE_MAP.update({f"ISA-P{n}": (f"P-{n}", "Professional") for n in range(1, 6)})
GRADE_MAP.update({f"ISA-P{n}": (f"P-{n}", "Director") for n in range(6, 8)})
GRADE_MAP.update({f"ISA-NO{ch}": (f"NO-{ch}", "National Officer") for ch in "ABCDE"})
GRADE_MAP["ISA -G3"] = ("G-3", "General Service")  # data artifact with space

# SC/SB-series (Service Contract)
GRADE_MAP.update(_p(range(1, 12), "SC", "Service Contract"))
GRADE_MAP.update(_p(range(1, 6), "SB", "Service Contract"))

# NPP / PSA (FAO non-staff contract types)
GRADE_MAP["NPP"] = ("NPP", "Service Contract")
GRADE_MAP["PSA"] = ("PSA", "Service Contract")

# WFP-specific grades from Management_Level facet
for n in range(1, 12):
    GRADE_MAP[f"SC L{n}"] = (f"SC L{n}", "Service Contract")
    GRADE_MAP[f"SSA L{n}"] = (f"SSA L{n}", "Service Contract")
GRADE_MAP["CST"] = ("CST", "Consultant")
GRADE_MAP["VO"] = ("VOL", "Volunteer")
GRADE_MAP["Volunteer"] = ("VOL", "Volunteer")
GRADE_MAP["Volunteer Programme"] = ("VOL", "Volunteer")
GRADE_MAP["INT"] = ("INT", "Internship")

# TC (DOS service contract)
for n in (4, 6, 7):
    GRADE_MAP[f"TC-{n}"] = (f"TC-{n}", "Service Contract")
    GRADE_MAP[f"TC{n}"] = (f"TC-{n}", "Service Contract")

# LSC-series (Service Contract)
GRADE_MAP.update(_p(range(1, 8), "LSC", "Service Contract"))

# Consultant
for raw, norm in [
    ("CON", "CON"),
    ("Consultant", "CON"),
    ("Consultant/Individual Contractor", "CON"),
    ("Consultant / PSA (Personal Services Agreement)", "CON"),
    ("Consultant / PSA", "CON"),
    ("C-1", "C-1"),
    ("C1", "C-1"),
    ("C-2", "C-2"),
    ("C2", "C-2"),
]:
    GRADE_MAP[raw] = (norm, "Consultant")
GRADE_MAP["Level 1 - Junior"] = ("Level 1", "Consultant")
GRADE_MAP["Level 2 - Middle"] = ("Level 2", "Consultant")
GRADE_MAP["Level 3 - Senior"] = ("Level 3", "Consultant")

# World Bank: GA-GD=GS, GE-GH=Professional, GI-GK=Director, EC/ET=Consultant
_WB_CAT = {
    **{f"G{ch}": "General Service" for ch in "ABCD"},
    **{f"G{ch}": "Professional" for ch in "EFGH"},
    **{f"G{ch}": "Director" for ch in "IJK"},
}
for code, cat in _WB_CAT.items():
    GRADE_MAP[code] = (code, cat)
for n in range(1, 5):
    GRADE_MAP[f"EC{n}"] = (f"EC{n}", "Consultant")
for n in range(1, 5):
    GRADE_MAP[f"ET{n}"] = (f"ET{n}", "Service Contract")

# IMF: A01-A08=GS, A09-A15=Professional, B01-B05=Director
GRADE_MAP.update({f"A{n:02d}": (f"A{n:02d}", "General Service") for n in range(1, 9)})
GRADE_MAP.update({f"A{n:02d}": (f"A{n:02d}", "Professional") for n in range(9, 16)})
GRADE_MAP.update({f"B{n:02d}": (f"B{n:02d}", "Director") for n in range(1, 6)})

# Internship
for raw in (
    "Intern", "Internship", "Internships / fellowships",
    "Internships/fellowships", "Trainee",
    "Affiliate/Internship > Hire", "Internship Programme", "I-1", "IN",
):
    GRADE_MAP[raw] = ("INT", "Internship")

# UNDP NPSA/IPSA (Personal Services Agreement)
for n in range(1, 12):
    GRADE_MAP[f"NPSA-{n}"] = (f"NPSA-{n}", "Service Contract")
for n in range(8, 15):
    GRADE_MAP[f"IPSA-{n}"] = (f"IPSA-{n}", "Service Contract")

# UNOPS LICA/IICA (Personal Services Agreement)
for n in range(1, 12):
    GRADE_MAP[f"LICA {n}"] = (f"LICA {n}", "Service Contract")
for n in range(1, 5):
    GRADE_MAP[f"IICA {n}"] = (f"IICA {n}", "Service Contract")

# UNU PSA (Personal Services Agreement)
GRADE_MAP["PSA-3"] = ("PSA-3", "Service Contract")
GRADE_MAP["PSA-4"] = ("PSA-4", "Service Contract")

# UN Tourism
for raw in (
    "Area I", "Area II", "Area III", "Area IV", "Area V", "Area VI",
    "II/5B", "III/3A", "Not applicable", "To be determined",
):
    GRADE_MAP[raw] = (raw, "UN Tourism")

GRADE_MAP["Fellows Programme"] = ("UG", "Other")

# Explicit Other / unresolvable
for raw in ("NA", "Other", "G level", "UG", "NB5", "E", "L2"):
    GRADE_MAP[raw] = (None if raw in ("NA", "Other") else raw, "Other")


# ---------------------------------------------------------------------------
# Title-based fallback classification
# ---------------------------------------------------------------------------

_TITLE_INTERNSHIP = re.compile(
    r"\b(intern(ship)?|fellowship|fellow|trainee|"
    r"junior\s+professional\s+officer|JPO)\b",
    re.IGNORECASE,
)
_TITLE_CONSULTANT = re.compile(
    r"consult|individual\s+contractor|special\s+service\s+agreement|\bSSA\b",
    re.IGNORECASE,
)
_TITLE_VOLUNTEER = re.compile(r"\bvolunteer\b", re.IGNORECASE)
_TITLE_VISITING_PROF = re.compile(r"\bvisiting\s+professional\b", re.IGNORECASE)
_TITLE_ROSTER = re.compile(r"\broster\b", re.IGNORECASE)


def _classify_by_title(title: str, agency: str = "") -> tuple[str | None, str | None]:
    """
    Last-resort classification based on job title keywords.
    Returns (grade, category) when a signal is found, or (None, 'Other') otherwise.
    """
    if _TITLE_INTERNSHIP.search(title):
        return "INT", "Internship"
    if _TITLE_CONSULTANT.search(title):
        return "CON", "Consultant"
    if _TITLE_VOLUNTEER.search(title):
        return "VOL", "Volunteer"
    if agency == "ICC" and _TITLE_VISITING_PROF.search(title):
        return "UG", "Visiting Professional"
    if _TITLE_ROSTER.search(title):
        return "UG", "Roster"
    return None, "Other"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize_grade(
    raw: str | None,
    *,
    agency: str = "",
    title: str = "",
) -> tuple[str | None, str | None]:
    """
    Return (normalized_grade, grade_category).
    Falls back to title-keyword matching for ungraded positions.
    Raises ValueError for unrecognized grade codes.
    """
    if not raw or not raw.strip():
        return _classify_by_title(title, agency)

    s = raw.strip()

    if s in GRADE_MAP:
        grade, category = GRADE_MAP[s]
        if category in ("Other", "UN Tourism") and title:
            title_grade, title_cat = _classify_by_title(title, agency)
            if title_cat != "Other":
                return title_grade, title_cat
        return grade, category

    # Unknown grade code — try title before giving up
    if title:
        title_grade, title_cat = _classify_by_title(title, agency)
        if title_cat != "Other":
            return title_grade, title_cat

    if agency == "UNRWA":
        return s, "UNRWA Area Staff"

    raise ValueError(f"unclassified grade {s!r}")
