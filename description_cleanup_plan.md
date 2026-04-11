# Description Cleanup Plan

## Overview

Job descriptions scraped from agency websites contain two distinct problems:
1. **Boilerplate** — repeated header/footer text identical across all jobs from an agency
2. **Scraper bugs** — malformed output (leaked JS, encoding errors, table artifacts)

The fix strategy is sentinel-based trimming: `text.split(sentinel)[0]` for footers, `text.split(sentinel)[-1]` for headers. Sentinels should be the stable opening words of each boilerplate block, not variable parts (dates, names). A shared `trim(text, before=None, after=None)` helper will be added to `scrapers/_utils.py` to keep scraper code clean.

---

## 1. Shared helper — `scrapers/_utils.py`

Add:
```python
def trim(text: str | None, before: str | None = None, after: str | None = None) -> str | None:
    """Strip leading and/or trailing boilerplate from a description.

    before: strip everything up to and including this sentinel (header trim)
    after:  strip this sentinel and everything following it (footer trim)
    """
    if not text:
        return text
    if before and before in text:
        text = text.split(before, 1)[1]
    if after and after in text:
        text = text.split(after, 1)[0]
    return text.strip() or None
```

---

## 2. Per-scraper changes

### `scrapers/icc.py` — ✅ DONE (this session)
Description extraction was targeting the wrong element (first large table = metadata). Fixed by:
- Targeting `div.externalPosting`
- Filtering to element children only (skipping text nodes)
- Skipping first 3 children (div, div, p metadata)
- Joining remainder as HTML and converting to markdown

Result: 65 jobs now have full 6–10k char descriptions.

---

### `scrapers/un_secretariat.py` — footer
**Scope:** covers ALL UN Secretariat departments (DESA, DPO, ECA, ECLAC, ESCAP, OHCHR, DPPA, OCT, UNAMA, UNLB, UNON, UNOV, UNSMIL, and ~30 more). Single fix covers them all.

**Strip footer sentinel:**
```
"No Fee\n\nTHE UNITED NATIONS DOES NOT CHARGE A FEE"
```
Applied to every description produced by this scraper.

**ICJ additional footer sentinel** (applied only where `agency == "ICJ"`):
```
"United Nations Considerations\n\nIn accordance with the ICJ"
```
Apply this trim only to ICJ jobs as a second pass, before the "No Fee" trim. ICJ jobs carry a "United Nations Considerations" block that sits before the "No Fee" section.

---

### `scrapers/wfp.py` — header + footer

**Header sentinel** (100% coverage — all 103 jobs):
```
"Terms and Conditions** section of this vacancy announcement).\n\n"
```
Strip everything up to and including this sentinel. The WHY JOIN WFP preamble reliably ends here; the next paragraph is always job-specific.

**Footer sentinel** (100% coverage — all 103 jobs):
```
"**WFP LEADERSHIP FRAMEWORK**"
```
Strip from here to end.

---

### `scrapers/unops.py` — footer
**Strip footer sentinel:**
```
"Please note that UNOPS does not accept unsolicited resumes."
```

---

### `scrapers/unicef.py` — multilingual header + footer

200+ jobs, three languages. Each language has a consistent preamble and a consistent footer that can be trimmed with per-language sentinels.

**English — "works in over 190" variant (171 jobs)**

Header sentinel (strip everything up to and including):
```
"to learn more about what we do at UNICEF.\n"
```
Footer sentinel (strip from here to end):
```
"UNICEF will not ask for applicants' bank account information"
```

**English — "works in some of the world's toughest places" variant (8 jobs)**

This variant has a longer, differently-worded preamble that repeats UNICEF's mission twice. No clean single-line sentinel — footer-only trim is the safe option:
```
"UNICEF will not ask for applicants' bank account information"
```
(same footer sentinel as above)

**French (6 jobs)**

Header sentinel:
```
"pour en savoir plus sur nos actions à l'UNICEF.\n"
```
Footer: spot-check one FR description's tail to confirm the sentinel — likely a French equivalent of the "positions are advertised" line or the careers link. Confirm during implementation.

**Spanish (11 jobs)**

Header sentinel (strip the three-paragraph preamble):
```
"¡Y nunca nos rendimos!\n\n"
```
The job-specific content begins immediately after with the `"**¿Cómo puedes marcar la diferencia?**"` heading (or equivalent). Footer: spot-check one ES description's tail to confirm sentinel during implementation.

**Other (7 jobs)**

Mixed — some start directly with job content (no preamble), some are the alt-EN variant. No trim applied; leave as-is.

---

### `scrapers/un_women.py` — opening paragraph + footer

**Header:** Remove the entire paragraph containing `"grounded in the vision of equality"`, regardless of how it starts or ends. Split on double newlines, filter out any paragraph containing the marker, rejoin:

```python
MARKER = "grounded in the vision of equality"
if description and MARKER in description:
    paragraphs = description.split('\n\n')
    paragraphs = [p for p in paragraphs if MARKER not in p]
    description = '\n\n'.join(paragraphs).strip()
```

**Footer:** two sentinels cover all 54 jobs —

```python
"At UN Women, we are committed"   # 48 jobs
"Statements:"                     # remaining jobs
```

Apply whichever appears first.

---

### `scrapers/who.py` — "Additional Information" section

31/32 WHO jobs contain an "Additional Information" section at the end, but the
heading is formatted inconsistently (`## ADDITIONAL INFORMATION`, `### Additional
Information:`, `**Additional Information**`, `**ADDITIONAL INFORMATION****`, etc.).
A single regex covers all variants:

```python
import re
description = re.split(
    r'\n+[#*\s]*additional\s+information',
    description, maxsplit=1, flags=re.IGNORECASE
)[0].strip()
```

---

### `scrapers/iaea.py` — JS leak (bug)
IAEA descriptions end with raw JavaScript:
```
ftlUtil_loadLiWidget(); _ftl_api.setup();
```
The scraper is picking up a `<script>` block. Fix: strip `<script>` tags from the HTML before passing to `html_to_md()`, or add a footer trim:
```
"ftlUtil_loadLiWidget"
```

---

### `scrapers/unaids.py` — table artifact (bug)
UNAIDS descriptions start with a wall of `| --- |` separators — a malformed table rendering artifact. The actual content comes after.

Fix: strip the table artifact. Either fix the HTML selector to skip the offending table, or trim up to the first non-table-separator line. Inspect the UNAIDS scraper to see which element is being captured.

---

### `scrapers/iom.py` — encoding (bug)
IOM descriptions start with `‚Äã‚Äã` (UTF-8 bytes of `\xe2\x80\x8b` zero-width non-joiners decoded as Windows-1252).

Fix: in `html_to_md()` or in the scraper, ensure HTML is decoded as UTF-8. Alternatively strip zero-width characters from the result:
```python
import unicodedata
text = ''.join(c for c in text if unicodedata.category(c) != 'Cf')
```
Or simpler: add `.replace('\u200b', '')` post-processing.

---

### `scrapers/fao.py` — footer

**Footer sentinel:** `"**ADDITIONAL INFORMATION**"` — present in 49/122 jobs. The phrase also appears in-text in 8 other jobs ("obtain additional information on…") but in those cases it's never formatted as a standalone bold heading, so the sentinel won't fire incorrectly. The remaining 65 jobs don't have the section and are unaffected.

---

### `scrapers/wb.py` — footer

**Footer sentinel:** `"WBG Culture Attributes:"` — present in 59/60 jobs.

---

### `scrapers/unhcr.py` — header + footer

**Header:** All 16 jobs have either "Terms of Reference" or "Standard Job
Description" (or both). Where both exist, TOR always appears first (it's in
consultant postings, before the SJD section). Logic: prefer TOR, fall back to
SJD.

```python
if 'Terms of Reference' in description:
    description = description.split('Terms of Reference', 1)[1]
elif 'Standard Job Description' in description:
    description = description.split('Standard Job Description', 1)[1]
```

**Footer:** `"UNHCR Salary Calculator"` — 7/16 jobs. Confirmed to appear *after*
the "Additional Qualifications" section in all cases, so that section is
preserved.

The remaining 9 jobs end with the structured `Required Languages / Desired
Languages / Additional Qualifications / Other information` block and have no
safe footer sentinel after "Additional Qualifications". No footer trim for
those 9 — header trim only.

---

### `scrapers/itu.py` — prefix

**Strip header sentinel — English (35/37 jobs):**
```
"Achieving gender balance is a high priority for ITU.\n\n"
```
Strip everything up to and including this sentinel.

**Strip header sentinel — French (2/37 jobs):**
```
"UNION INTERNATIONALE DES TÉLÉCOMMUNICATIONS\n\n"
```
Apply this sentinel for the 2 French-language postings. The ITU agency preamble in French starts with this string; strip up to and including it.

Implementation: try EN sentinel first; if not found, try FR sentinel.

---

### `scrapers/wipo.py` — footer
**Strip footer sentinel:**
```
"Applications from qualified women as well as from qualified nationals of unrepresented Member States of WIPO"
```

---

### `scrapers/wto.py` — header

WTO descriptions start with a metadata block (VN Category, Application Deadline, Grade, etc.) followed by boilerplate paragraphs (vacancy type notice, contract type notice, equal opportunity statement).

**Header sentinel** (covers 3/4 jobs; Intern job starts with job-specific content):
```
"are particularly encouraged for all positions.\n\n"
```
Strip everything up to and including this sentinel. Then strip a leading `".\n\n"` if present (2 regular jobs have a standalone dot paragraph between the equal-opportunity text and the job-specific `**The Secretariat...` heading).

Implementation:
```python
PREAMBLE_END = "are particularly encouraged for all positions.\n\n"
if description and PREAMBLE_END in description:
    description = description.split(PREAMBLE_END, 1)[1]
    if description.startswith(".\n"):
        description = description.lstrip(".\n").strip()
```

---

## 3. Implementation order

1. Add `trim()` to `_utils.py`
2. `un_secretariat.py` — highest leverage (covers ~40 agency codes + ICJ in one scraper)
3. `wfp.py` — 103 jobs, most visible
4. `unicef.py` — 200 jobs, multilingual sentinels
5. `unops.py` — 66 jobs
6. `un_women.py` — custom preamble logic + two footer sentinels
7. `who.py` — regex footer trim
8. `iaea.py` — bug fix (JS leak)
9. `unaids.py` — bug fix (table artifact)
10. `iom.py` — encoding fix
11. `fao.py`, `wb.py` — footer sentinels
12. `unhcr.py` — header (TOR/SJD) + salary calculator footer
13. `itu.py`, `wipo.py`, `wto.py` — smaller scope

After each change: spot-check 2–3 descriptions in `data.json` to confirm trim is working and not overcutting.
