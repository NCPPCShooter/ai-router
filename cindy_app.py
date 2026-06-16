"""
cindy_app.py — Cindy's Job Board

Local Streamlit app showing job postings from SQLite DB.
Lets Cindy review, filter, track status, and tailor resume/cover letter.

Run via systemd service or:
    source ~/ai-router/venv/bin/activate
    streamlit run ~/ai-router/cindy_app.py --server.port 8502

Access: http://192.168.1.35:8502
"""

import os
import sys
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote_plus

import streamlit as st

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from job_db import init_db, get_total_count, DB_PATH
from tailor import tailor_for_job, OUTPUT_DIR

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Cindy's Job Board",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

st.markdown("""
<style>
    .main { background-color: #f8f9fa; }
    .job-card {
        background: white;
        border-radius: 8px;
        padding: 16px 20px;
        margin-bottom: 12px;
        border-left: 4px solid #4A90D9;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }
    .job-card.applied    { border-left-color: #28a745; }
    .job-card.skipped    { border-left-color: #dc3545; opacity: 0.6; }
    .job-card.interested { border-left-color: #fd7e14; }
    .job-card.rejected   { border-left-color: #6f42c1; opacity: 0.6; }
    .job-title { font-size: 1.05rem; font-weight: 600; color: #1a1a2e; margin: 0; }
    .job-meta  { font-size: 0.85rem; color: #6c757d; margin-top: 4px; }
    .badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 600;
        margin-left: 8px;
    }
    .badge-new        { background: #e3f2fd; color: #1565c0; }
    .badge-interested { background: #fff3e0; color: #e65100; }
    .badge-applied    { background: #e8f5e9; color: #2e7d32; }
    .badge-skipped    { background: #fce4ec; color: #c62828; }
    .badge-rejected   { background: #f3e5f5; color: #6a1b9a; }
    .stat-box {
        background: white;
        border-radius: 8px;
        padding: 16px;
        text-align: center;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        margin-bottom: 8px;
    }
    .stat-number { font-size: 2rem; font-weight: 700; color: #4A90D9; }
    .stat-label  { font-size: 0.8rem; color: #6c757d; margin-top: 4px; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_status_column():
    with get_connection() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(job_postings)").fetchall()]
        if "status" not in cols:
            conn.execute("ALTER TABLE job_postings ADD COLUMN status TEXT DEFAULT 'new'")
            conn.commit()


def get_filtered_jobs(status_filter=None, source_filter=None, days_back=30):
    init_db()
    ensure_status_column()
    cutoff = (date.today() - timedelta(days=days_back)).isoformat()
    query  = "SELECT * FROM job_postings WHERE date_found >= ?"
    params = [cutoff]
    if status_filter and status_filter != "All":
        query  += " AND status = ?"
        params.append(status_filter.lower())
    if source_filter and source_filter != "All":
        query  += " AND source = ?"
        params.append(source_filter)
    query += " ORDER BY created_at DESC"
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def update_status(job_id: int, new_status: str):
    ensure_status_column()
    with get_connection() as conn:
        conn.execute(
            "UPDATE job_postings SET status = ? WHERE id = ?",
            (new_status, job_id)
        )
        conn.commit()


def get_stats():
    ensure_status_column()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT COALESCE(status,'new') as status, COUNT(*) as cnt "
            "FROM job_postings GROUP BY status"
        ).fetchall()
    return {r["status"]: r["cnt"] for r in rows}

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "expanded_job"  not in st.session_state: st.session_state.expanded_job  = None
if "tailor_job_id" not in st.session_state: st.session_state.tailor_job_id = None
if "tailor_result" not in st.session_state: st.session_state.tailor_result = None
if "pasted_jd"     not in st.session_state: st.session_state.pasted_jd     = {}

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("💼 Cindy's Job Board")
    st.caption("Powered by Kirk's AI Router")
    st.divider()

    st.subheader("Filters")
    status_filter = st.selectbox(
        "Status",
        ["All", "New", "Interested", "Applied", "Skipped", "Rejected"],
        index=0
    )
    days_back = st.slider("Days to show", min_value=7, max_value=90, value=30, step=7)

    with get_connection() as conn:
        ensure_status_column()
        sources = [r[0] for r in conn.execute(
            "SELECT DISTINCT source FROM job_postings WHERE source IS NOT NULL"
        ).fetchall()]
    source_filter = st.selectbox("Source", ["All"] + sources)

    st.divider()
    st.subheader("My Progress")
    stats    = get_stats()
    total    = sum(stats.values())
    new_c    = stats.get("new",        0)
    inter_c  = stats.get("interested", 0)
    app_c    = stats.get("applied",    0)
    skip_c   = stats.get("skipped",   0)
    rej_c    = stats.get("rejected",   0)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f'<div class="stat-box"><div class="stat-number">{total}</div><div class="stat-label">Total Found</div></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="stat-box"><div class="stat-number" style="color:#28a745">{app_c}</div><div class="stat-label">Applied</div></div>', unsafe_allow_html=True)
    c3, c4 = st.columns(2)
    with c3:
        st.markdown(f'<div class="stat-box"><div class="stat-number" style="color:#fd7e14">{inter_c}</div><div class="stat-label">Interested</div></div>', unsafe_allow_html=True)
    with c4:
        st.markdown(f'<div class="stat-box"><div class="stat-number" style="color:#6f42c1">{rej_c}</div><div class="stat-label">Rejected</div></div>', unsafe_allow_html=True)

    st.divider()
    st.caption(f"DB: `{DB_PATH}`")
    st.caption(f"Output: `{OUTPUT_DIR}`")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

st.header("Job Postings")

jobs = get_filtered_jobs(status_filter, source_filter, days_back)

if not jobs:
    st.info("No job postings found for the selected filters.")
    st.stop()

st.caption(f"Showing {len(jobs)} posting{'s' if len(jobs) != 1 else ''}")
st.divider()

# ---------------------------------------------------------------------------
# Job cards
# ---------------------------------------------------------------------------

for idx, job in enumerate(jobs):
    job_id  = job["id"]
    status  = (job.get("status") or "new").lower()
    title   = job.get("title",    "Unknown Title")
    company = job.get("company",  "Unknown Company")
    loc     = job.get("location", "")
    sal     = job.get("salary",   "")
    url     = job.get("url",      "")
    source  = job.get("source",   "")
    found   = job.get("date_found", "")
    snippet = job.get("raw_snippet", "")

    # Build Google fallback URL if no direct URL
    if not url:
        search_query = quote_plus(f"{title} {company} job")
        url = f"https://www.google.com/search?q={search_query}"
        url_label = "🔍 Search Google"
    else:
        url_label = "🔗 View Posting"

    meta_parts = [c for c in [company, loc, sal, source] if c]
    meta_str   = "  ·  ".join(meta_parts)

    # Card HTML
    st.markdown(f"""
    <div class="job-card {status if status != 'new' else ''}">
        <p class="job-title">
            {title}
            <span class="badge badge-{status}">{status.upper()}</span>
        </p>
        <p class="job-meta">{meta_str}</p>
        <p class="job-meta">Found: {found}</p>
    </div>
    """, unsafe_allow_html=True)

    # Action row — unique keys using idx + job_id
    ca, cb, cc, cd, ce, cf, cg = st.columns([1, 1, 1, 1, 1, 1, 1])

    with ca:
        st.markdown(f"[{url_label}]({url})")

    with cb:
        expand_label = "▲ Hide" if st.session_state.expanded_job == job_id else "▼ Details"
        if st.button(expand_label, key=f"exp_{idx}_{job_id}"):
            st.session_state.expanded_job = None if st.session_state.expanded_job == job_id else job_id
            st.rerun()

    with cc:
        if st.button("⭐ Interested", key=f"int_{idx}_{job_id}"):
            update_status(job_id, "interested")
            st.rerun()

    with cd:
        if st.button("✅ Applied", key=f"app_{idx}_{job_id}"):
            update_status(job_id, "applied")
            st.rerun()

    with ce:
        if st.button("❌ Skip", key=f"skp_{idx}_{job_id}"):
            update_status(job_id, "skipped")
            st.rerun()

    with cf:
        if st.button("🚫 Rejected", key=f"rej_{idx}_{job_id}"):
            update_status(job_id, "rejected")
            st.rerun()

    with cg:
        if st.button("✏️ Tailor", key=f"tlr_{idx}_{job_id}", type="primary"):
            st.session_state.tailor_job_id = job_id
            st.session_state.tailor_result = None
            st.session_state.expanded_job  = job_id
            st.rerun()

    # ---------------------------------------------------------------------------
    # Expanded panel
    # ---------------------------------------------------------------------------

    if st.session_state.expanded_job == job_id:
        with st.container():
            st.markdown("---")

            if snippet:
                with st.expander("📄 Job Description Snippet", expanded=False):
                    st.text(snippet[:1500] + ("..." if len(snippet) > 1500 else ""))

            if st.session_state.tailor_job_id == job_id:
                st.subheader("✏️ Tailor Resume & Cover Letter")

                url_input = st.text_input(
                    "Job Posting URL",
                    value=job.get("url", ""),
                    key=f"url_{idx}_{job_id}",
                    help="Edit if needed — used to fetch the full job description."
                )

                pasted = st.text_area(
                    "Paste Job Description Here (fallback if URL fetch fails)",
                    value=st.session_state.pasted_jd.get(job_id, ""),
                    height=200,
                    key=f"pst_{idx}_{job_id}",
                    placeholder="Paste the full job description here..."
                )
                st.session_state.pasted_jd[job_id] = pasted

                go_col, cancel_col = st.columns([1, 4])
                with go_col:
                    go = st.button("🚀 Generate Documents", key=f"go_{idx}_{job_id}", type="primary")
                with cancel_col:
                    if st.button("Cancel", key=f"can_{idx}_{job_id}"):
                        st.session_state.tailor_job_id = None
                        st.session_state.tailor_result = None
                        st.rerun()

                if go:
                    with st.spinner("Claude is tailoring your resume and cover letter..."):
                        result = tailor_for_job(
                            company=company,
                            title=title,
                            url=url_input,
                            pasted_text=pasted,
                        )
                    st.session_state.tailor_result = result

                if st.session_state.tailor_result:
                    res = st.session_state.tailor_result
                    if res["success"]:
                        st.success("✅ Documents saved successfully!")
                        st.markdown(f"""
**Resume:** `{res['resume_path']}`

**Cover Letter:** `{res['cover_path']}`

**Source:** {res['fetch_status']}
                        """)
                        if status == "new":
                            update_status(job_id, "interested")
                            st.info("Status updated to Interested.")
                    else:
                        st.error(f"❌ {res['error']}")
                        if "url_failed" in res.get("fetch_status", ""):
                            st.warning("URL fetch failed — please paste the job description above and try again.")

            st.markdown("---")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown(
    f"<br><p style='text-align:center;color:#aaa;font-size:0.8rem;'>"
    f"Kirk's AI Router · Cindy's Job Board · {date.today().strftime('%B %d, %Y')}"
    f"</p>",
    unsafe_allow_html=True
)