"""
job_db.py — SQLite deduplication layer for AI Router job search results.

Stores job postings, deduplicates by fingerprint (title + company + url hash),
and returns counts of net-new postings per run.

Usage:
    from job_db import init_db, store_jobs, get_new_jobs_count

DB location: C:\\Users\\kirkk\\Projects\\ai-router\\data\\job_postings.db
"""

import sqlite3
import hashlib
import json
import os
import re
from datetime import date, datetime
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "job_postings.db")

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS job_postings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint   TEXT    NOT NULL UNIQUE,          -- SHA-256 of title+company+url
    title         TEXT    NOT NULL,
    company       TEXT    NOT NULL,
    url           TEXT,
    location      TEXT,
    salary        TEXT,
    source        TEXT,                             -- e.g. 'US Search', 'Global Search'
    raw_snippet   TEXT,                             -- raw text block from Grok
    date_found    TEXT    NOT NULL,                 -- ISO date: 2026-06-15
    created_at    TEXT    NOT NULL                  -- ISO datetime
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_date_found ON job_postings (date_found);
"""

# ---------------------------------------------------------------------------
# DB init
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create the database and table if they don't exist."""
    os.makedirs(DB_DIR, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(CREATE_TABLE_SQL)
        conn.execute(CREATE_INDEX_SQL)
        conn.commit()


def get_connection() -> sqlite3.Connection:
    """Return a connection with row_factory set."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------

def _make_fingerprint(title: str, company: str, url: str = "") -> str:
    """
    Create a stable SHA-256 fingerprint for deduplication.
    Normalizes text to lowercase and strips whitespace before hashing.
    """
    raw = f"{title.lower().strip()}|{company.lower().strip()}|{url.lower().strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Parsing Grok's raw job text
# ---------------------------------------------------------------------------

def parse_jobs_from_grok(raw_text: str, source: str = "Search") -> list[dict]:
    """
    Parse Grok's job search output. Handles multiple formats:
      Format A: **1. Job Title**  (number+title in bold on first line)
      Format B: **Job Title**: Actual Title  (labeled field)
      Format C: **1. Job Title – Company**  (title and company combined)
    Fields use either **Field**: or **Field:** format.
    """
    jobs = []

    # Split on bold-numbered items (**1. or **2. etc.) or plain numbered items
    blocks = re.split(r'\n(?=\*\*\d+[\.\)]|\d+[\.\)]\s)', raw_text.strip())

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        # Skip intro paragraphs — must start with a number or **number
        if not re.match(r'^(\*\*)?(\d+)[\.\)]', block):
            continue

        job = {
            "title":       "",
            "company":     "",
            "url":         "",
            "location":    "",
            "salary":      "",
            "source":      source,
            "raw_snippet": block[:2000],
        }

        lines = [l.strip() for l in block.split("\n") if l.strip()]
        if not lines:
            continue

        # --- Title from first line ---
        first_line = re.sub(r'^(\*\*)?(\d+)[\.\)]\s*\*?\*?', '', lines[0]).strip()
        first_line = first_line.strip('*').strip()

        # Check for "Job Title": label format
        title_label = re.search(r'(?:Job Title)\s*[:\-]\s*(.+)', first_line, re.IGNORECASE)
        if title_label:
            job["title"] = title_label.group(1).strip()[:120]
        # Check for "Title – Company" format on first line
        elif ' – ' in first_line or ' - ' in first_line:
            parts = re.split(r'\s[–-]\s', first_line, maxsplit=1)
            job["title"] = parts[0].strip()[:120]
            if len(parts) > 1 and not job["company"]:
                job["company"] = parts[1].strip()[:100]
        else:
            job["title"] = first_line[:120]

        # --- Structured fields: handles both **Field**: and **Field:** ---
        field_pattern = re.compile(
            r'\*\*(Job Title|Company|Salary|Location|URL|Link|Apply|Website)\*?\*?\s*[:\-]\s*(.+)',
            re.IGNORECASE
        )
        for line in lines:
            m = field_pattern.search(line)
            if m:
                field = m.group(1).lower().strip()
                value = m.group(2).strip()
                value = re.sub(r'\*+', '', value).strip()
                value = re.sub(r'\s*\(.*?\)\s*$', '', value).strip()

                if field == "job title"                            and not job["title"]:
                    job["title"]    = value[:120]
                elif field == "company"                            and not job["company"]:
                    job["company"]  = value[:100]
                elif field == "salary"                             and not job["salary"]:
                    job["salary"]   = value[:50]
                elif field == "location"                           and not job["location"]:
                    job["location"] = value[:100]
                elif field in ("url", "link", "apply", "website") and not job["url"]:
                    job["url"]      = value[:500]

        # --- Company fallback: "Title – Company" in subsequent lines ---
        if not job["company"]:
            for line in lines[1:4]:
                dash_match = re.search(r'[–-]\s*([A-Z][^\n\|,\*]{2,50})', line)
                if dash_match:
                    job["company"] = dash_match.group(1).strip()[:100]
                    break

        # --- URL fallback ---
        if not job["url"] and job["title"] and job["company"]:
            from router import build_verified_search_urls
            search_urls = build_verified_search_urls(job["title"], job["company"])
            job["url"] = search_urls.get("LinkedIn", "")

        if job["title"]:
            jobs.append(job)

    return jobs

# ---------------------------------------------------------------------------
# Core store function
# ---------------------------------------------------------------------------

def store_jobs(
    raw_grok_text: str,
    source: str = "Search",
    verbose: bool = False
) -> dict:
    """
    Parse raw Grok output, deduplicate against the DB, insert new records.

    Returns a summary dict:
        {
            "parsed":    int,   # total jobs parsed from Grok text
            "new":       int,   # net-new jobs inserted
            "duplicate": int,   # jobs already in DB (skipped)
            "new_jobs":  list   # list of the newly inserted job dicts
        }
    """
    init_db()
    jobs = parse_jobs_from_grok(raw_grok_text, source=source)

    today     = date.today().isoformat()
    now       = datetime.now().isoformat()
    new_jobs  = []
    dupes     = 0

    with get_connection() as conn:
        for job in jobs:
            fp = _make_fingerprint(job["title"], job["company"], job["url"])

            # Check for duplicate
            existing = conn.execute(
                "SELECT id FROM job_postings WHERE fingerprint = ?", (fp,)
            ).fetchone()

            if existing:
                dupes += 1
                if verbose:
                    print(f"  [DUPE]  {job['title']} @ {job['company']}")
                continue

            # Build search URL fallback if no URL found
            if not job.get("url") and job.get("title") and job.get("company"):
                from router import build_verified_search_urls
                search_urls = build_verified_search_urls(job["title"], job["company"])
                job["url"] = search_urls.get("LinkedIn", "")
            
            # Insert new record
            conn.execute(
                """
                INSERT INTO job_postings
                    (fingerprint, title, company, url, location, salary,
                     source, raw_snippet, date_found, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fp,
                    job["title"],
                    job["company"],
                    job["url"],
                    job["location"],
                    job["salary"],
                    job["source"],
                    job["raw_snippet"],
                    today,
                    now,
                )
            )
            new_jobs.append(job)
            if verbose:
                print(f"  [NEW]   {job['title']} @ {job['company']}")

        conn.commit()

    return {
        "parsed":    len(jobs),
        "new":       len(new_jobs),
        "duplicate": dupes,
        "new_jobs":  new_jobs,
    }


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_all_jobs(limit: int = 100) -> list[dict]:
    """Return the most recent job postings from the DB."""
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM job_postings ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_jobs_by_date(target_date: str = None) -> list[dict]:
    """Return jobs found on a specific date (default: today). Date format: YYYY-MM-DD."""
    init_db()
    target_date = target_date or date.today().isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM job_postings WHERE date_found = ? ORDER BY created_at DESC",
            (target_date,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_total_count() -> int:
    """Return total number of unique job postings in the DB."""
    init_db()
    with get_connection() as conn:
        result = conn.execute("SELECT COUNT(*) FROM job_postings").fetchone()
    return result[0]


def get_db_path() -> str:
    """Return the resolved DB file path."""
    return DB_PATH


# ---------------------------------------------------------------------------
# CLI quick-check (python job_db.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    total = get_total_count()
    today_jobs = get_jobs_by_date()
    print(f"DB: {DB_PATH}")
    print(f"Total unique postings: {total}")
    print(f"Found today ({date.today().isoformat()}): {len(today_jobs)}")
    if today_jobs:
        print("\nToday's postings:")
        for j in today_jobs:
            print(f"  {j['title']} @ {j['company']} | {j['location']} | {j['salary']}")
