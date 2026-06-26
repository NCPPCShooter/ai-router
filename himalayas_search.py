"""
himalayas_search.py
-------------------
Fetches remote job listings from the Himalayas public API and returns
them in a format compatible with Cindy's existing job_db.py schema.

API: https://himalayas.app/jobs/api/search
No API key or authentication required.
Rate limit: once per day is fine; data refreshes every 24 hours.

Attribution: job listings sourced from Himalayas (https://himalayas.app)
"""

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Callable

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — tune these to Cindy's target profile
# ---------------------------------------------------------------------------

SEARCH_URL = "https://himalayas.app/jobs/api/search"

# Keywords that reflect Cindy's seniority and function.
# Kept tightly scoped to sourcing/procurement to avoid irrelevant results.
SEARCH_QUERIES = [
    "sourcing procurement director",
    "strategic sourcing director",
    "director of procurement",
    "VP procurement",
    "VP sourcing",
    "head of procurement",
    "head of sourcing",
    "chief procurement officer",
    "indirect procurement director",
    "global sourcing director",
]

# Seniority values accepted by the Himalayas API:
# Entry-level | Mid-level | Senior | Manager | Director | Executive
TARGET_SENIORITY = ["Senior", "Manager", "Director", "Executive"]

# ---------------------------------------------------------------------------
# Relevance filter — jobs MUST match at least one term in TITLE_MUST_MATCH
# or at least MIN_BODY_HITS terms in the description to be accepted.
# This prevents off-target results (Finance, HR, Sales, etc.) from slipping
# through when the API returns broad seniority-level matches.
# ---------------------------------------------------------------------------

# If the job TITLE contains any of these → accept immediately
TITLE_MUST_MATCH = [
    "sourcing",
    "procurement",
    "purchasing",
    "supply chain",
    "supplier relations",
    "category management",
    "category manager",
    "vendor management",
    "strategic sourcing",
    "indirect procurement",
    "direct procurement",
    "global sourcing",
    "chief procurement",
    "cpo",
]

# If the title contains any of these → reject immediately, no further checks
TITLE_BLOCKLIST = [
    "sales",
    "revenue",
    "marketing",
    "channel",
    "finance",
    "financial planning",
    "talent acquisition",
    "recruiting",
    "engineering",
    "technology",
    "product",
    "operations",  # too generic on its own
    "partnerships",
    "business development",
    "account executive",
    "account director",
    "client",
    "medical",
    "diagnostics",
    "legal",
    "tax",
    "investment",
    "chief of staff",
]

# Tighter body keyword list — these are procurement-specific terms
# that rarely appear in unrelated job descriptions
MIN_BODY_HITS = 4
BODY_KEYWORDS = [
    "sourcing",
    "procurement",
    "purchasing",
    "supplier management",
    "supply base",
    "category management",
    "rfp",
    "rfq",
    "spend management",
    "contract negotiation",
    "strategic sourcing",
    "indirect spend",
    "direct spend",
    "vendor negotiations",
    "purchase orders",
    "supply chain optimization",
]
# How many pages to fetch per query (20 jobs/page, so 2 pages = 40 jobs max per query).
PAGES_PER_QUERY = 2

# Seconds to wait between API requests — be a good citizen.
REQUEST_DELAY = 1.5

# Request timeout in seconds.
REQUEST_TIMEOUT = 20

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fingerprint(title: str, company: str, url: str = "") -> str:
    key = f"{title.lower().strip()}|{company.lower().strip()}|{url.lower().strip()}"
    return hashlib.sha256(key.encode()).hexdigest()


def _strip_html(html: str) -> str:
    """Return plain text from sanitised HTML description."""
    if not html:
        return ""
    try:
        return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
    except Exception:
        return html


def _salary_label(job: dict) -> str:
    """Human-readable salary string for logging / display."""
    lo = job.get("minSalary")
    hi = job.get("maxSalary")
    cur = job.get("currency", "USD")
    if lo and hi:
        return f"{cur} {lo:,}–{hi:,}"
    if lo:
        return f"{cur} {lo:,}+"
    return ""


def _is_relevant(job: dict) -> bool:
    title = job.get("title", "").lower()
    description = job.get("description", "").lower()

    # Fast reject: title blocklist
    for term in TITLE_BLOCKLIST:
        if term in title:
            logger.info(
                "Relevance FAIL (blocklist) — rejected: %r @ %r",
                job["title"], job["company"]
            )
            return False

    # Fast accept: title must-match
    for term in TITLE_MUST_MATCH:
        if term in title:
            logger.debug("Relevance PASS (title): %r contains %r", job["title"], term)
            return True

    # Fallback: body keyword count
    hits = sum(1 for kw in BODY_KEYWORDS if kw in description)
    if hits >= MIN_BODY_HITS:
        logger.debug(
            "Relevance PASS (body %d hits): %r @ %r",
            hits, job["title"], job["company"]
        )
        return True

    logger.info(
        "Relevance FAIL — rejected: %r @ %r (title no match, body hits=%d)",
        job.get("title"), job.get("company"), hits
    )
    return False


def _normalize(raw: dict) -> dict:
    """
    Map a raw Himalayas job object to the schema used by job_db.py.
    """
    title = raw.get("title", "").strip()
    company = raw.get("companyName", "").strip()

    loc_restrictions = raw.get("locationRestrictions", [])
    if loc_restrictions:
        parts = []
        for r in loc_restrictions:
            if isinstance(r, dict):
                parts.append(r.get("name", "") or r.get("alpha2", ""))
            elif isinstance(r, str):
                parts.append(r)
        countries = ", ".join(p for p in parts if p)
        location = f"Remote ({countries})" if countries else "Remote"
    else:
        location = "Worldwide Remote"

    return {
        "title":       title,
        "company":     company,
        "location":    location,
        "url":         raw.get("applicationLink", ""),
        "source":      "Himalayas",
        "date_found":  datetime.now(timezone.utc).isoformat(),
        "description": _strip_html(raw.get("description", "")),
        "salary_min":  raw.get("minSalary"),
        "salary_max":  raw.get("maxSalary"),
        "fingerprint": _fingerprint(title, company, raw.get("applicationLink", "")),
        "seniority":   raw.get("seniority", []),
        "categories":  raw.get("categories", []),
        "pub_date":    raw.get("pubDate", ""),
    }


# ---------------------------------------------------------------------------
# Core fetch
# ---------------------------------------------------------------------------

def _fetch_page(query: str, page: int) -> list[dict]:
    """
    Fetch one page of search results for a single query.
    Returns a list of raw job dicts (or empty list on error).
    """
    params = {
        "q":               query,
        "employment_type": "Full Time",
        "sort":            "recent",
        "page":            page,
        "seniority":       TARGET_SENIORITY,
    }

    try:
        resp = requests.get(SEARCH_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        jobs = data.get("jobs", [])
        logger.debug(
            "Himalayas | query=%r page=%d -> %d jobs (total available: %s)",
            query, page, len(jobs), data.get("totalCount", "?")
        )
        return jobs
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 429:
            logger.warning("Himalayas rate-limited (429). Skipping remaining pages for %r.", query)
        else:
            logger.error("Himalayas HTTP error for query %r page %d: %s", query, page, e)
        return []
    except requests.exceptions.RequestException as e:
        logger.error("Himalayas request failed for query %r page %d: %s", query, page, e)
        return []


def _fetch_query(query: str) -> list[dict]:
    """Fetch all configured pages for a single search query."""
    raw_jobs = []
    for page in range(1, PAGES_PER_QUERY + 1):
        page_jobs = _fetch_page(query, page)
        if not page_jobs:
            break
        raw_jobs.extend(page_jobs)
        if page < PAGES_PER_QUERY:
            time.sleep(REQUEST_DELAY)
    return raw_jobs


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def search_all(dedup_fn: Callable[[str], bool] | None = None) -> list[dict]:
    """
    Run all SEARCH_QUERIES, normalise results, apply relevance filter,
    and return new jobs only.

    Parameters
    ----------
    dedup_fn : callable, optional
        A function that accepts a fingerprint (str) and returns True if that
        job is already stored in the SQLite database.  Pass in:
            lambda fp: db.fingerprint_exists(fp)
        If None, only intra-batch deduplication is performed.

    Returns
    -------
    list[dict]
        Normalised, relevance-filtered job records ready for job_db.py.
    """
    seen_in_batch: set[str] = set()
    new_jobs: list[dict] = []
    total_fetched = 0
    total_rejected = 0

    for i, query in enumerate(SEARCH_QUERIES):
        logger.info("Himalayas | searching: %r", query)
        raw_jobs = _fetch_query(query)
        total_fetched += len(raw_jobs)

        for raw in raw_jobs:
            job = _normalize(raw)
            fp = job["fingerprint"]

            # Skip duplicates within this batch
            if fp in seen_in_batch:
                continue
            seen_in_batch.add(fp)

            # Skip jobs already in the SQLite DB
            if dedup_fn and dedup_fn(fp):
                continue

            # === RELEVANCE FILTER — new in this version ===
            if not _is_relevant(job):
                total_rejected += 1
                continue

            new_jobs.append(job)

        if i < len(SEARCH_QUERIES) - 1:
            time.sleep(REQUEST_DELAY)

    logger.info(
        "Himalayas | done. Fetched %d raw | %d unique batch | %d relevance-rejected | %d new after DB dedup.",
        total_fetched, len(seen_in_batch), total_rejected, len(new_jobs)
    )
    return new_jobs


# ---------------------------------------------------------------------------
# Standalone test — run directly to verify the API is working
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print("=== Himalayas API test run ===\n")
    jobs = search_all()  # no dedup_fn in test mode

    if not jobs:
        print("No jobs returned. Check your queries or network connection.")
    else:
        for j in jobs[:10]:
            sal = ""
            if j.get("salary_min") and j.get("salary_max"):
                sal = f"  [{j['salary_min']:,}–{j['salary_max']:,}]"
            print(f"  {j['title']} @ {j['company']}{sal}")
            print(f"    {j['location']}")
            print(f"    {j['url']}\n")

        if len(jobs) > 10:
            print(f"  ... and {len(jobs) - 10} more.")
