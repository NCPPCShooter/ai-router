"""
tailor.py — Job tailoring engine for Cindy's job search app.

Given a job posting (URL or pasted text), this module:
  1. Fetches the job description (URL first, paste fallback)
  2. Reads Cindy's master resume and cover letter from ~/cindy/resume/
  3. Calls Claude to tailor both documents
  4. Saves tailored .docx files to ~/cindy/output/<Company>_<Date>/

Usage:
    from tailor import tailor_for_job
    result = tailor_for_job(job_id, url, pasted_text)
"""

import os
import re
import requests
from datetime import date
from pathlib import Path
from docx import Document
from docx.shared import Pt
import anthropic

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HOME           = Path.home()
RESUME_DIR     = HOME / "cindy" / "resume"
OUTPUT_DIR     = HOME / "cindy" / "output"
MASTER_RESUME  = RESUME_DIR / "Cindy_Keller_Resume_v2.docx"
MASTER_COVER   = RESUME_DIR / "Cindy_Keller_Cover_Letter_Master.docx"

# ---------------------------------------------------------------------------
# Anthropic client
# ---------------------------------------------------------------------------

def _get_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set in environment")
    return anthropic.Anthropic(api_key=api_key)


# ---------------------------------------------------------------------------
# Job description fetching
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

def fetch_job_description(url: str) -> tuple[str, str]:
    """
    Attempt to fetch and extract job description text from a URL.

    Returns:
        (text, status) where status is 'ok', 'blocked', or 'error'
    """
    if not url or not url.startswith("http"):
        return "", "no_url"

    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            # Strip HTML tags — simple but effective for job boards
            text = re.sub(r'<[^>]+>', ' ', response.text)
            text = re.sub(r'\s+', ' ', text).strip()
            # Keep only the most relevant portion (cap at 8000 chars)
            if len(text) > 8000:
                text = text[:8000]
            if len(text) < 200:
                return "", "blocked"
            return text, "ok"
        elif response.status_code in (403, 429):
            return "", "blocked"
        else:
            return "", f"error_{response.status_code}"
    except Exception as e:
        return "", f"error: {str(e)[:100]}"


# ---------------------------------------------------------------------------
# Document reading
# ---------------------------------------------------------------------------

def read_docx_text(path: Path) -> str:
    """Extract plain text from a .docx file."""
    doc = Document(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


# ---------------------------------------------------------------------------
# Claude tailoring
# ---------------------------------------------------------------------------

RESUME_SYSTEM = """You are an expert resume writer specializing in Supply Chain, 
Sourcing, and Procurement roles. You tailor resumes to match job postings precisely, 
mirroring the employer's language and keywords while keeping all content truthful.

Rules:
- Mirror the job posting's exact terminology and keywords
- Reorder bullet points to lead with most relevant experience
- Adjust the professional summary to speak directly to this role
- Keep all facts, dates, companies, and metrics exactly as provided
- Do not invent experience or qualifications
- Output the complete tailored resume as plain text, preserving section structure
- Use the same section headers as the original resume"""

COVER_SYSTEM = """You are an expert cover letter writer specializing in Supply Chain, 
Sourcing, and Procurement roles. You write concise, targeted cover letters that 
speak directly to the employer's needs.

Rules:
- Write exactly 3 paragraphs: hook/fit, proof/experience, close
- Mirror the job posting's language and priorities
- Reference the company name and role title specifically
- Keep it under 300 words
- Professional but warm tone
- Output only the cover letter body (no address headers needed)"""


def tailor_resume_with_claude(
    master_resume: str,
    job_description: str,
    company: str,
    title: str
) -> str:
    """Call Claude to tailor the resume for this job posting."""
    client = _get_client()

    prompt = f"""Please tailor this resume for the following job posting.

JOB POSTING:
Company: {company}
Title: {title}

{job_description}

---

MASTER RESUME:
{master_resume}

---

Output the complete tailored resume as plain text."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=RESUME_SYSTEM,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


def tailor_cover_letter_with_claude(
    master_cover: str,
    job_description: str,
    company: str,
    title: str
) -> str:
    """Call Claude to write a targeted cover letter for this job posting."""
    client = _get_client()

    prompt = f"""Please write a tailored cover letter for this job posting.

JOB POSTING:
Company: {company}
Title: {title}

{job_description}

---

MASTER COVER LETTER (for reference/tone):
{master_cover}

---

Output only the cover letter body, 3 paragraphs, under 300 words."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=COVER_SYSTEM,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


# ---------------------------------------------------------------------------
# Document writing
# ---------------------------------------------------------------------------

def _sanitize_filename(name: str) -> str:
    """Strip characters that are unsafe in filenames."""
    return re.sub(r'[^\w\s-]', '', name).strip().replace(' ', '_')


def write_docx(text: str, output_path: Path, template_path: Path = None) -> None:
    """
    Write plain text content to a .docx file.
    Uses the template's styles if provided, otherwise creates a clean document.
    """
    doc = Document()

    # Set reasonable margins (1 inch)
    for section in doc.sections:
        section.top_margin    = Pt(72)
        section.bottom_margin = Pt(72)
        section.left_margin   = Pt(72)
        section.right_margin  = Pt(72)

    for line in text.split('\n'):
        line = line.strip()
        if not line:
            doc.add_paragraph('')
            continue

        # Detect section headers (ALL CAPS lines or lines ending with :)
        if line.isupper() or (line.endswith(':') and len(line) < 50):
            p = doc.add_paragraph()
            run = p.add_run(line)
            run.bold = True
            run.font.size = Pt(11)
        else:
            p = doc.add_paragraph(line)
            p.style.font.size = Pt(10.5)

    doc.save(str(output_path))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def tailor_for_job(
    company: str,
    title: str,
    url: str = "",
    pasted_text: str = ""
) -> dict:
    """
    Full tailoring pipeline for a single job posting.

    Args:
        company:     Company name (from DB or user input)
        title:       Job title (from DB or user input)
        url:         Job posting URL (tried first)
        pasted_text: Fallback if URL fetch fails

    Returns:
        {
            "success":       bool,
            "resume_path":   str,
            "cover_path":    str,
            "output_dir":    str,
            "fetch_status":  str,   # 'url', 'pasted', 'failed'
            "error":         str,   # empty if success
        }
    """
    result = {
        "success":      False,
        "resume_path":  "",
        "cover_path":   "",
        "output_dir":   "",
        "fetch_status": "",
        "error":        "",
    }

    # --- Validate master files exist ---
    if not MASTER_RESUME.exists():
        result["error"] = f"Master resume not found at {MASTER_RESUME}"
        return result
    if not MASTER_COVER.exists():
        result["error"] = f"Master cover letter not found at {MASTER_COVER}"
        return result

    # --- Get job description ---
    job_description = ""

    if url:
        fetched, status = fetch_job_description(url)
        if status == "ok" and fetched:
            job_description = fetched
            result["fetch_status"] = "url"
        else:
            result["fetch_status"] = f"url_failed({status})"

    if not job_description and pasted_text and pasted_text.strip():
        job_description = pasted_text.strip()
        result["fetch_status"] = "pasted"

    if not job_description:
        result["error"] = (
            "Could not retrieve job description. "
            "URL fetch failed and no pasted text was provided."
        )
        result["fetch_status"] = "failed"
        return result

    # --- Read master documents ---
    try:
        master_resume_text = read_docx_text(MASTER_RESUME)
        master_cover_text  = read_docx_text(MASTER_COVER)
    except Exception as e:
        result["error"] = f"Failed to read master documents: {e}"
        return result

    # --- Create output directory ---
    safe_company = _sanitize_filename(company) or "Unknown_Company"
    today        = date.today().strftime("%Y-%m-%d")
    job_dir      = OUTPUT_DIR / f"{safe_company}_{today}"
    job_dir.mkdir(parents=True, exist_ok=True)

    # --- Tailor resume ---
    try:
        tailored_resume = tailor_resume_with_claude(
            master_resume_text, job_description, company, title
        )
    except Exception as e:
        result["error"] = f"Claude resume tailoring failed: {e}"
        return result

    # --- Tailor cover letter ---
    try:
        tailored_cover = tailor_cover_letter_with_claude(
            master_cover_text, job_description, company, title
        )
    except Exception as e:
        result["error"] = f"Claude cover letter tailoring failed: {e}"
        return result

    # --- Save documents ---
    resume_filename = f"Cindy_Keller_Resume_{safe_company}.docx"
    cover_filename  = f"Cindy_Keller_CoverLetter_{safe_company}.docx"
    resume_path     = job_dir / resume_filename
    cover_path      = job_dir / cover_filename

    try:
        write_docx(tailored_resume, resume_path, MASTER_RESUME)
        write_docx(tailored_cover,  cover_path,  MASTER_COVER)
    except Exception as e:
        result["error"] = f"Failed to save documents: {e}"
        return result

    result.update({
        "success":     True,
        "resume_path": str(resume_path),
        "cover_path":  str(cover_path),
        "output_dir":  str(job_dir),
    })
    return result
