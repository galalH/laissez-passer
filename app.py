#!/usr/bin/env python3
"""Laissez-Passer — Flask app and scraper driver."""

import importlib.util
import json
import logging
import os
import queue
import random
import re
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import country_converter as coco
import pandas as pd
from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context

from scrapers._grade import normalize_grade

logging.getLogger("country_converter").setLevel(logging.ERROR)
logging.getLogger("country_converter.country_converter").setLevel(logging.ERROR)
_cc = coco.CountryConverter()


def _cc_convert(val: str, to: str):
    result = _cc.convert(val, to=to, not_found=None)
    return result[0] if isinstance(result, list) else result


_HOME_BASED_RE = re.compile(r"home.?based|remote", re.IGNORECASE)
_MULTI_LOCATION_RE = re.compile(
    r"anywhere|multiple|various|locations?|\d+\s+locations?|field|tbd|to\s+be\s+determined|\bother\b",
    re.IGNORECASE,
)

_CC_COUNTRY_NAMES = set()
for _col in ("name_short", "name_official"):
    _CC_COUNTRY_NAMES.update(_cc.data[_col].str.lower().dropna())

BASE_DIR = Path(__file__).parent
SCRAPERS_DIR = BASE_DIR / "scrapers"
DATA_FILE = BASE_DIR / "static" / "data.json"
FILTER_FILE = BASE_DIR / "static" / "filter.json"

_DATA_FILE_LOCK = threading.Lock()


def _write_data_file(payload: dict) -> None:
    """Atomically write payload to DATA_FILE using a temp file + os.replace()."""
    with _DATA_FILE_LOCK:
        fd, tmp_path = tempfile.mkstemp(dir=DATA_FILE.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp_path, DATA_FILE)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

_DUTY_STATION_URL = "https://unsceb.org/assets/data/HR/duty_station.csv"


def _load_duty_stations() -> dict[str, tuple[str, str]]:
    df = pd.read_csv(_DUTY_STATION_URL, encoding="utf-8-sig")
    df = df[df["YEAR"] == df["YEAR"].max()]
    counts = df.groupby("DS")["COUNTRY"].nunique()
    unambiguous = counts[counts == 1].index
    df = df[df["DS"].isin(unambiguous)].drop_duplicates("DS")
    return {ds.lower(): (ds, country) for ds, country in zip(df["DS"], df["COUNTRY"])}


_DS_LOOKUP = _load_duty_stations()

_STRIP_PATS = [
    re.compile(r"\s*\([^)]+\)\s*$"),
    re.compile(r"\s*-\s*other\s+cities\s*$", re.IGNORECASE),
    re.compile(r"^(?:HQ|FO)\s+", re.IGNORECASE),
    re.compile(r"\s+RO\s*$", re.IGNORECASE),
]


def _strip_city(city: str) -> tuple[str, str | None]:
    s = city.strip()
    country_hint = None

    m = re.search(r"\(([^)]+)\)\s*$", s)
    if m:
        hint = m.group(1).strip()
        cc = _cc.convert(hint, to="name_short", not_found=None)
        if cc:
            country_hint = cc

    prev = None
    while prev != s:
        prev = s
        for pat in _STRIP_PATS:
            s = pat.sub("", s).strip()

    if "," in s:
        base, suffix = s.split(",", 1)
        suffix = suffix.strip()
        if suffix and country_hint is None:
            country_hint = suffix
        s = base.strip()

    return s, country_hint


def _normalize_location(
    city: str | None, country: str | None
) -> tuple[str | None, str | None]:
    for val in (city, country):
        if val and _HOME_BASED_RE.search(val):
            return None, "Home Based"
        if val and _MULTI_LOCATION_RE.search(val):
            return None, "Multiple Locations"

    country_hint = None

    if city:
        ds = _DS_LOOKUP.get(city.lower())
        if ds:
            return ds

        cleaned, country_hint = _strip_city(city)
        ds = _DS_LOOKUP.get(cleaned.lower())
        if ds:
            return ds

        cc = _cc.convert(cleaned, to="name_short", not_found=None)
        if cc:
            return None, cc

        city = cleaned

    return city, country or country_hint


def _process_job(job: dict, agency: str, previous: dict, today: str) -> list[str]:
    warnings: list[str] = []

    if not job.get("pubdate"):
        job["pubdate"] = previous.get(job.get("url", ""), today)

    raw = job.get("grade")
    job["grade_raw"] = raw
    try:
        job["grade"], job["grade_category"] = normalize_grade(
            raw, agency=job.get("agency", agency), title=job.get("job_title", "")
        )
    except Exception as e:
        warnings.append(f"WARNING: {agency} grade normalization failed for {raw!r}: {e}")
        job["grade"], job["grade_category"] = raw, "Other"

    city, country_raw = _normalize_location(job.get("city"), job.get("country"))
    job["city"] = city

    if country_raw == "Home Based":
        job["country"] = "Home Based"
        job["country_iso3"] = "XRM"
    elif country_raw == "Multiple Locations":
        job["country"] = "Multiple Locations"
        job["country_iso3"] = "XMU"
    elif country_raw:
        name = _cc_convert(country_raw, "name_short")
        iso3 = _cc_convert(country_raw, "ISO3")
        if name is not None:
            job["country"] = name
            job["country_iso3"] = iso3
        else:
            job["country"] = None
            job["city"] = None
            job["country_iso3"] = "XXX"
            warnings.append(f"WARNING: {agency} could not normalize country {country_raw!r} for job {job.get('url', '')}")
    else:
        job["country"] = None
        job["country_iso3"] = "XXX"

    if not job.get("country") and job.get("city"):
        job["city_raw"] = job["city"]
        job["city"] = None

    return warnings


def _load_previous_jobs() -> dict[str, str]:
    if DATA_FILE.exists():
        with open(DATA_FILE) as f:
            payload = json.load(f)
        jobs = payload.get("jobs", payload) if isinstance(payload, dict) else payload
        return {job["url"]: job["pubdate"] for job in jobs if job.get("url") and job.get("pubdate")}
    return {}


def _load_previous_jobs_list() -> list[dict]:
    if DATA_FILE.exists():
        with open(DATA_FILE) as f:
            payload = json.load(f)
        return payload.get("jobs", payload) if isinstance(payload, dict) else payload
    return []


def _discover_plugins() -> list:
    modules = []
    for py_file in sorted(SCRAPERS_DIR.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
        if spec is None or spec.loader is None:
            print(f"WARNING: Could not load {py_file.name}", file=sys.stderr)
            continue
        try:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            modules.append(mod)
        except Exception as e:
            print(f"WARNING: Failed to import {py_file.name}: {e}", file=sys.stderr)
    return modules




def scrape(progress=print):
    """Run all scrapers. Calls progress(msg) for each status line."""
    previous = _load_previous_jobs()
    plugins = _discover_plugins()
    random.shuffle(plugins)
    now = datetime.now().astimezone().isoformat(timespec='seconds')
    today = datetime.now().date().isoformat()

    all_jobs = []
    agency_count = 0
    warning_count = 0
    total = len(plugins)

    progress(f"total:{total}")

    def run_plugin(plugin):
        warnings = []
        agency = getattr(plugin, "AGENCY", plugin.__name__)
        try:
            jobs = plugin.scrape()
            if not isinstance(jobs, list):
                warnings.append(f"WARNING: {agency} scrape() did not return a list")
                return agency, [], warnings
            unknown = getattr(plugin, "unknown_depts", set())
            for dept in unknown:
                warnings.append(f"WARNING: un_secretariat: unknown department {dept!r} — defaulting to UNS")
            unknown.clear()
            return agency, jobs, warnings
        except Exception as e:
            warnings.append(f"WARNING: {agency} scrape failed: {e}")
            return agency, [], warnings

    succeeded_agencies = set()

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(run_plugin, p): p for p in plugins}
        n = 0
        for future in as_completed(futures):
            agency, jobs, warnings = future.result()
            n += 1
            for w in warnings:
                progress(f"warning:{w}")
                warning_count += 1
            if not jobs:
                progress(f"warning:INFO: {agency} returned 0 jobs")
                warning_count += 1
            else:
                for job in jobs:
                    for w in _process_job(job, agency, previous, today):
                        progress(f"warning:{w}")
                        warning_count += 1
                all_jobs.extend(jobs)
                agency_count += 1
                succeeded_agencies.add(agency)
            progress(f"progress:{n}/{total}:{agency}:{len(jobs)}")

    # Flag jobs that were not present in the previous snapshot ("latest" tab).
    for job in all_jobs:
        job["is_new"] = job.get("url") not in previous

    # An agency that returned nothing this run (transient failure, 0 jobs, a
    # scraper temporarily down) would otherwise vanish from data.json — then
    # reappear as a wall of false "new" postings once it recovers. Carry its
    # last known jobs forward instead of dropping them.
    known_urls = {job.get("url") for job in all_jobs if job.get("url")}
    for job in _load_previous_jobs_list():
        if job.get("agency") not in succeeded_agencies and job.get("url") not in known_urls:
            job["is_new"] = False
            all_jobs.append(job)

    # Carry over existing scores so only genuinely new jobs get re-scored.
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE) as f:
                old_payload = json.load(f)
            old_scores = {
                job["url"]: job["score"]
                for job in old_payload.get("jobs", [])
                if job.get("url") and job.get("score") is not None
            }
            for job in all_jobs:
                url = job.get("url")
                if url and url in old_scores and job.get("score") is None:
                    job["score"] = old_scores[url]
        except Exception:
            pass

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    _write_data_file({"updated": now, "jobs": all_jobs})

    suffix = f" · {warning_count} warnings" if warning_count else ""
    progress(f"done:{len(all_jobs)} jobs from {agency_count} agencies{suffix}")

    return all_jobs


# ── Scoring ──────────────────────────────────────────────────────────────────

_SCORE_TOOL = {
    "type": "function",
    "name": "record_score",
    "description": "Record the relevance score for the job listing.",
    "parameters": {
        "type": "object",
        "properties": {
            "score": {
                "type": "number",
                "description": "Relevance score between 0.0 and 1.0",
            }
        },
        "required": ["score"],
    },
}

_SCORE_TOOL_CHOICE = {"type": "function", "name": "record_score"}

_PERSONA_FILE = BASE_DIR / "static" / "persona.md"

_SCORE_MODEL = "gpt-6-luna"
_SCORE_WORKERS = 8


def _build_score_message(job: dict) -> str:
    location = ", ".join(filter(None, [job.get("city", ""), job.get("country", "")]))
    header = " | ".join(filter(None, [
        job.get("agency_name", ""),
        job.get("job_title", ""),
        location,
    ]))
    description = (job.get("description") or "").strip()
    return (
        f"{header}\n\n"
        f"{description}\n\n"
        "Score this job's relevance to the persona on a scale of 0.0 to 1.0. "
        "Call record_score with your score."
    )


def _extract_score(response) -> float | None:
    """Pull the record_score argument out of a Responses API result."""
    for item in response.output:
        if getattr(item, "type", None) == "function_call" and item.name == "record_score":
            try:
                return float(json.loads(item.arguments)["score"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                return None
    return None


def score_new_jobs(all_jobs: list, progress=print, jobs_to_score: list | None = None) -> None:
    """Score jobs that are missing a score using gpt-6-luna via the Responses API.

    all_jobs is the full list written back to disk.  jobs_to_score is the subset
    that should be scored (must be references into all_jobs); defaults to all_jobs.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        progress("scoring_skip:no OPENAI_API_KEY — skipping scoring")
        return

    if not _PERSONA_FILE.exists() or not _PERSONA_FILE.read_text().strip():
        progress("scoring_skip:persona not configured — skipping scoring")
        return

    try:
        import openai
    except ImportError as e:
        progress(f"scoring_skip:missing dependency ({e}) — skipping scoring")
        return

    try:
        persona = _PERSONA_FILE.read_text().strip()
        source = jobs_to_score if jobs_to_score is not None else all_jobs
        to_score = [job for job in source if job.get("score") is None]

        if not to_score:
            progress("scoring_skip:all jobs already scored")
            return

        # Retries with backoff cover transient 429s / 5xx from parallel calls.
        client = openai.OpenAI(api_key=api_key, max_retries=5)

        def score_one(job: dict) -> float | None:
            # Luna occasionally returns an empty "incomplete" response; one
            # retry recovers it without marking the job -1.
            for _ in range(2):
                response = client.responses.create(
                    model=_SCORE_MODEL,
                    max_output_tokens=256,
                    instructions=persona,
                    input=_build_score_message(job),
                    tools=[_SCORE_TOOL],
                    tool_choice=_SCORE_TOOL_CHOICE,
                )
                score = _extract_score(response)
                if score is not None:
                    return score
            return None

        progress(f"scoring_start:{len(to_score)}")
        started_at = time.monotonic()
        n_done = n_scored = n_failed = 0
        last_error = ""

        with ThreadPoolExecutor(max_workers=_SCORE_WORKERS) as executor:
            futures = {executor.submit(score_one, job): job for job in to_score}
            for future in as_completed(futures):
                job = futures[future]
                n_done += 1
                try:
                    score = future.result()
                except Exception as e:
                    # Leave the job unscored so the next refresh retries it.
                    n_failed += 1
                    last_error = str(e)
                else:
                    # A response with no usable score becomes -1 so the job is
                    # not re-submitted on every refresh.
                    job["score"] = score if score is not None else -1
                    n_scored += score is not None
                elapsed = int(time.monotonic() - started_at)
                progress(f"scoring:{n_done}:{len(to_score)}:{elapsed}")

        # Reload to get the updated timestamp written by scrape(), then write scores back
        try:
            with _DATA_FILE_LOCK:
                with DATA_FILE.open() as f:
                    payload = json.load(f)
        except Exception:
            payload = {}
        _write_data_file({"updated": payload.get("updated", ""), "jobs": all_jobs})

        if n_failed:
            progress(f"scoring_skip:{n_failed} requests failed ({last_error})")
        progress(f"scoring_done:{n_scored}/{len(to_score)}")

    except Exception as e:
        progress(f"scoring_skip:scoring failed ({e})")


# ── Filter helpers ────────────────────────────────────────────────────────────

_SCHEMA_DESC = """\
DataFrame columns:
- agency: str — 3-4 letter agency code, e.g. "UNDP", "WHO", "WFP", "UNICEF", "UNHCR"
- agency_name: str — full agency name
- job_title: str
- grade: str — normalized canonical grade (see values below)
- grade_category: str — one of: Professional, Director, General Service, Field Service,
  National Officer, Service Contract, Consultant, Internship, Volunteer, Other
- city: str or None
- country_iso3: str — ISO 3166-1 alpha-3 code; use this for country filtering, NOT the
  country name. Special values: "XRM" = Home Based/Remote, "XMU" = Multiple Locations,
  "XXX" = unknown. Examples: "FRA", "USA", "KEN", "CHE", "DEU", "GBR", "ETH", "TZA"
- deadline: str or None — calendar date "YYYY-MM-DD", e.g. "2026-06-30"
- pubdate: str — first-seen calendar date "YYYY-MM-DD", e.g. "2026-04-14"
- score: float or None — relevance score 0.0–1.0; -1 means scoring failed; None means not yet scored

Canonical grade values by category:
  Professional:     P-1  P-2  P-3  P-4  P-5
  Director:         D-1  D-2
  General Service:  G-1  G-2  G-3  G-4  G-5  G-6  G-7
  Field Service:    FS-1  FS-2  FS-3  FS-4  FS-5  FS-6  FS-7
  National Officer: NO-A  NO-B  NO-C  NO-D  NO-E  NO-UNK
  Service Contract (local, levels 1–11): SC L-1 … SC L-11  SC L-UNK
  Service Contract (intl, levels 1–7):   SC I-1 … SC I-7   SC I-UNK
  Service Contract (level unknown):      SC UNK
  Consultant:   CONS
  Internship:   INTERN
  Volunteer:    VOL
  Other/unclassified: OTHER
  World Bank codes (mapped to categories above): GA GB GC GD (GS) | GE GF GG GH (Prof) | GI GJ GK (Dir)
  IMF codes: A01–A08 (GS) | A09–A15 (Prof) | B01–B05 (Dir)

Query rules:
- ALWAYS filter by country_iso3, never by the country name string.
- Both deadline and pubdate sort correctly as plain strings (ISO format is lexicographic).
- String comparisons are case-sensitive.
- For substring matching: job_title.str.contains("data", case=False, na=False)
- To match multiple grade_category values: grade_category in ["Professional", "Director"]
"""


def _apply_filter(all_jobs: list) -> list:
    """Return the subset of all_jobs matching filter.json, or all_jobs if no filter."""
    if not FILTER_FILE.exists():
        return all_jobs
    try:
        config = json.loads(FILTER_FILE.read_text())
    except Exception:
        return all_jobs
    pandas_query = (config.get("pandas_query") or "").strip()
    if not pandas_query:
        return all_jobs
    try:
        df = pd.DataFrame(all_jobs)
        if df.empty:
            return all_jobs
        filtered_df = df.query(pandas_query)
        return [all_jobs[i] for i in filtered_df.index]
    except Exception as e:
        print(f"WARNING: filter application failed: {e}", file=sys.stderr)
        return all_jobs


def _translate_filter(natural_language: str, prev_query: str = "", error: str = "") -> str:
    """Call GPT Luna to translate natural language to a pandas query string."""
    try:
        import openai
    except ImportError:
        raise ValueError("openai package not installed")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    client = openai.OpenAI(api_key=api_key, max_retries=0)
    system = (
        "You are a pandas query translator. Given a natural language description and a "
        "dataframe schema, output ONLY a valid pandas DataFrame.query() string. "
        "No explanation, no markdown, no backticks — just the raw query string.\n\n"
        + _SCHEMA_DESC
    )
    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Natural language filter: {natural_language}"},
    ]
    if prev_query and error:
        messages += [
            {"role": "assistant", "content": prev_query},
            {"role": "user", "content": f"That query failed with: {error}\nProvide a corrected query."},
        ]
    resp = client.chat.completions.create(
        model="gpt-6-luna",
        messages=messages,
        max_completion_tokens=200,
    )
    raw = resp.choices[0].message.content.strip()
    for ch in ("`", '"', "'"):
        if raw.startswith(ch) and raw.endswith(ch):
            raw = raw[1:-1]
    return raw.strip()


def _validate_filter(pandas_query: str) -> tuple[bool, str]:
    """Try the query against a tiny test dataframe; return (ok, error_message)."""
    test_data = {
        "agency": ["UNDP"], "agency_name": ["UN Development Programme"],
        "job_title": ["Data Analyst"], "grade": ["P-4"],
        "grade_category": ["Professional"], "city": ["New York"],
        "country_iso3": ["USA"],
        "deadline": ["2026-06-01"], "pubdate": ["2026-04-14"],
        "score": [0.5],
    }
    df = pd.DataFrame(test_data)
    try:
        df.query(pandas_query)
        return True, ""
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder="static", static_url_path="")


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/data.json")
def data():
    if not DATA_FILE.exists():
        return jsonify({"error": "no data yet"}), 404

    # Apply pandas filter if configured
    filter_config: dict = {}
    if FILTER_FILE.exists():
        try:
            filter_config = json.loads(FILTER_FILE.read_text())
        except Exception:
            pass
    pandas_query = (filter_config.get("pandas_query") or "").strip()

    if not pandas_query:
        return send_from_directory(app.static_folder, "data.json")

    try:
        with open(DATA_FILE) as f:
            payload = json.load(f)
        jobs = payload.get("jobs", [])
        df = pd.DataFrame(jobs)
        if df.empty:
            return send_from_directory(app.static_folder, "data.json")
        filtered_df = df.query(pandas_query)
        filtered_jobs = [jobs[i] for i in filtered_df.index]
        return jsonify({**payload, "jobs": filtered_jobs})
    except Exception as e:
        print(f"WARNING: filter in /data.json failed: {e}", file=sys.stderr)
        return send_from_directory(app.static_folder, "data.json")


@app.route("/persona.md", methods=["GET"])
def get_persona():
    if not _PERSONA_FILE.exists():
        return "", 204
    return _PERSONA_FILE.read_text(), 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/persona.md", methods=["POST"])
def save_persona_route():
    text = request.get_data(as_text=True)
    _PERSONA_FILE.write_text(text)

    if not text.strip():
        # Persona cleared — nothing to score
        return Response("data:scoring_skip:persona cleared\n\n", mimetype="text/event-stream")

    # Reset all scores so the new persona is applied to everything
    if DATA_FILE.exists():
        try:
            with _DATA_FILE_LOCK:
                with open(DATA_FILE) as f:
                    payload = json.load(f)
            for job in payload.get("jobs", []):
                job["score"] = None
            _write_data_file(payload)
        except Exception as e:
            print(f"WARNING: could not reset scores: {e}", file=sys.stderr)

    q: queue.Queue = queue.Queue()

    def progress(msg: str) -> None:
        q.put(msg)

    def run() -> None:
        try:
            if DATA_FILE.exists():
                with open(DATA_FILE) as f:
                    payload = json.load(f)
                all_jobs = payload.get("jobs", [])
                jobs_to_score = _apply_filter(all_jobs)
                score_new_jobs(all_jobs, progress=progress, jobs_to_score=jobs_to_score)
        except Exception as e:
            progress(f"scoring_skip:re-scoring failed: {e}")
        finally:
            q.put(None)

    threading.Thread(target=run, daemon=True).start()

    def generate():
        while True:
            msg = q.get()
            if msg is None:
                break
            yield f"data:{msg}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@app.route("/filter.json", methods=["GET", "POST"])
def filter_json():
    if request.method == "GET":
        if not FILTER_FILE.exists():
            return jsonify({})
        try:
            return jsonify(json.loads(FILTER_FILE.read_text()))
        except Exception:
            return jsonify({})

    # POST
    body = request.get_json(silent=True) or {}
    natural_language = (body.get("natural_language") or "").strip()

    if not natural_language:
        FILTER_FILE.write_text("{}")
        return jsonify({"status": "ok", "pandas_query": None})

    # Return cached translation when the text hasn't changed
    existing: dict = {}
    if FILTER_FILE.exists():
        try:
            existing = json.loads(FILTER_FILE.read_text())
        except Exception:
            pass
    if existing.get("natural_language") == natural_language and existing.get("pandas_query"):
        return jsonify({"status": "ok", "pandas_query": existing["pandas_query"]})

    # Translate with up to 3 retries
    pandas_query = None
    last_query = ""
    last_error = ""
    for _ in range(3):
        try:
            candidate = _translate_filter(natural_language, last_query, last_error)
            ok, err = _validate_filter(candidate)
            if ok:
                pandas_query = candidate
                break
            last_query = candidate
            last_error = err
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 500
        except Exception as e:
            last_error = str(e)

    if pandas_query is None:
        return jsonify({
            "status": "error",
            "message": f"Could not generate a valid filter after 3 attempts. Last error: {last_error}",
        }), 400

    FILTER_FILE.write_text(json.dumps(
        {"natural_language": natural_language, "pandas_query": pandas_query},
        ensure_ascii=False,
    ))
    return jsonify({"status": "ok", "pandas_query": pandas_query})


@app.route("/api/config")
def api_config():
    has_persona = _PERSONA_FILE.exists() and bool(_PERSONA_FILE.read_text().strip())
    filter_config: dict = {}
    if FILTER_FILE.exists():
        try:
            filter_config = json.loads(FILTER_FILE.read_text())
        except Exception:
            pass
    has_filter = bool(filter_config.get("pandas_query"))
    return jsonify({
        "has_persona": bool(has_persona),
        "has_filter": has_filter,
        "filter_nl": filter_config.get("natural_language", ""),
    })


@app.route("/refresh", methods=["POST"])
def refresh():
    def generate():
        for line in _scrape_lines():
            yield f"data:{line}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


def _scrape_lines():
    """Run scrape() then score_new_jobs(), yielding progress lines as they're emitted."""
    q = queue.Queue()

    def progress(msg):
        q.put(msg)

    def run():
        try:
            all_jobs = scrape(progress=progress)
            jobs_to_score = _apply_filter(all_jobs)
            score_new_jobs(all_jobs, progress=progress, jobs_to_score=jobs_to_score)
        finally:
            q.put(None)  # sentinel

    t = threading.Thread(target=run, daemon=True)
    t.start()

    while True:
        msg = q.get()
        if msg is None:
            break
        yield msg


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
