"""
JobWhiz Lab — ETL Pipeline (Adzuna → PostgreSQL)
Extract → Transform → Load  |  run: python etl.py

Fixes applied vs previous version:
  1. SALARY    — reads salary_min/salary_max from per-job API response first.
                 Histogram fallback only used when the job has no salary fields.
                 Stores salary_is_predicted flag.
  2. EXPERIENCE — en-dash (–), "N yrs", "Exp: N-N", "Experience: N–N",
                 "N years of experience", "Experience Range" all now captured.
  3. SKILLS    — dictionary expanded from 42 → 80+ terms.
                 Hyphenated skills (scikit-learn, ci/cd) handled correctly.
                 Skill → category mapping populated on insert.
  4. CITY      — description text fallback for jobs where area = ["India"].
                 Suburb → major city normalization extended.
  5. DUPLICATES — cross-day dedup: skip if title+company+city already stored
                 within the last 7 days.
"""

import os
import re
import time
import logging
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from db import get_db

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

ADZUNA_APP_ID  = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")
ADZUNA_BASE    = "https://api.adzuna.com/v1/api"


# ─────────────────────────────────────────────────────────────────
# CLEANUP
# ─────────────────────────────────────────────────────────────────
def delete_old_jobs(days_to_keep: int = 30):
    conn = get_db()
    with conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM job_skills
                WHERE job_id IN (
                    SELECT id FROM jobs
                    WHERE date_posted < CURRENT_DATE - INTERVAL '%s days'
                )
            """, (days_to_keep,))
            cur.execute("""
                DELETE FROM jobs
                WHERE date_posted < CURRENT_DATE - INTERVAL '%s days'
            """, (days_to_keep,))
    conn.close()
    log.info(f"Cleanup done (>{days_to_keep} days old)")


# ─────────────────────────────────────────────────────────────────
# FIX 1 — SALARY
# Previous: called histogram API, got one average per role, stamped
#           it on every job regardless of what the API actually returned.
# Fixed:    read salary_min/salary_max from the job record itself.
#           Convert INR → LPA. Fall back to histogram only when absent.
# ─────────────────────────────────────────────────────────────────
_histogram_cache: dict = {}

def _histogram_fallback(role_keyword: str):
    """Fetch market average from Adzuna histogram. Cached per keyword."""
    key = role_keyword.lower()
    if key in _histogram_cache:
        return _histogram_cache[key]
    try:
        r = requests.get(f"{ADZUNA_BASE}/jobs/in/histogram", params={
            "app_id": ADZUNA_APP_ID, "app_key": ADZUNA_APP_KEY,
            "what": role_keyword,
        }, timeout=15)
        r.raise_for_status()
        histogram = r.json().get("histogram", {})
        if not histogram:
            _histogram_cache[key] = None
            return None
        buckets = sorted([(int(k), v) for k, v in histogram.items() if v > 0])
        total   = sum(v for _, v in buckets)
        if total == 0:
            _histogram_cache[key] = None
            return None
        avg_inr = sum(k * v for k, v in buckets) / total
        result  = round(avg_inr / 100_000, 1)   # INR → LPA
        _histogram_cache[key] = result
        time.sleep(0.3)
        return result
    except Exception as e:
        log.warning(f"Histogram failed for '{role_keyword}': {e}")
        _histogram_cache[key] = None
        return None


ROLE_TO_KEYWORD = {
    "data analyst":        "data analyst",
    "senior data analyst": "senior data analyst",
    "data scientist":      "data scientist",
    "data engineer":       "data engineer",
    "ml engineer":         "machine learning engineer",
    "business analyst":    "business analyst",
    "bi analyst":          "business intelligence analyst",
    "analytics engineer":  "analytics engineer",
}

def _role_keyword(title: str) -> str:
    t = title.lower()
    for role, keyword in ROLE_TO_KEYWORD.items():
        if role in t:
            return keyword
    return "data analyst"


def extract_salary(raw: dict, title: str):
    """
    Return (salary_min_lpa, salary_max_lpa, salary_avg_lpa, is_predicted).

    Priority:
      1. salary_min / salary_max from the job record (real per-job data)
      2. Histogram market average as fallback (labelled is_predicted=True)
      3. None when histogram also unavailable
    """
    s_min_raw = raw.get("salary_min")
    s_max_raw = raw.get("salary_max")
    is_predicted = raw.get("salary_is_predicted", False)

    if s_min_raw is not None and s_max_raw is not None:
        s_min = round(float(s_min_raw) / 100_000, 1)
        s_max = round(float(s_max_raw) / 100_000, 1)
        s_avg = round((s_min + s_max) / 2, 1)
        return s_min, s_max, s_avg, bool(is_predicted)

    # Per-job salary absent → fall back to histogram market average
    fallback = _histogram_fallback(_role_keyword(title))
    if fallback is not None:
        return None, None, fallback, True   # mark as predicted/estimated

    return None, None, None, True


# ─────────────────────────────────────────────────────────────────
# FIX 2 — EXPERIENCE EXTRACTION
# Previous: ASCII hyphen only, missed en-dash (–), "yrs", "Exp: N-N",
#           "N years of experience", "Experience Range: N-N".
# Fixed:    unified pattern covers all formats found in real data.
# ─────────────────────────────────────────────────────────────────
_EXP_PATTERNS = [
    # "5–8 years" / "5-8 years" (en-dash and ASCII hyphen)
    r'(\d+)\s*[–\-]\s*(\d+)\s*years?',
    # "5–8 yrs" / "5-8 yrs"
    r'(\d+)\s*[–\-]\s*(\d+)\s*yrs?\b',
    # "Experience: 5–12 years" / "Exp: 3-5 yrs"
    r'exp(?:erience)?[\s:]+(\d+)\s*[–\-]\s*(\d+)\s*(?:years?|yrs?)',
    # "Experience Range: 7-9"
    r'experience\s+range[\s:]+(\d+)\s*[–\-]\s*(\d+)',
    # "2 years of experience" / "5+ years of experience"
    r'(\d+)\+?\s*years?\s+of\s+(?:relevant\s+)?experience',
    # "minimum 3 years" / "at least 5 years"
    r'(?:minimum|at\s+least)\s+(\d+)\s*years?',
    # "5+ years"
    r'(\d+)\s*\+\s*years?',
    # "3 years experience" (no "of")
    r'(\d+)\s*years?\s+experience',
]

def extract_experience(text: str):
    """Return (exp_min, exp_max). Returns (0, 0) when not found."""
    t = text.lower()
    for pat in _EXP_PATTERNS:
        m = re.search(pat, t)
        if m:
            groups = [g for g in m.groups() if g is not None]
            exp_min = int(groups[0])
            exp_max = int(groups[1]) if len(groups) > 1 else exp_min + 2
            # sanity check — ignore garbage like "100 years experience"
            if 0 < exp_min <= 25 and 0 < exp_max <= 30:
                return exp_min, exp_max
    return 0, 0


# ─────────────────────────────────────────────────────────────────
# FIX 3 — SKILLS EXTRACTION
# Previous: 42 terms, plain \b regex breaks on "scikit-learn",
#           no category mapping.
# Fixed:    80+ terms, hyphen-aware matching, category dict populated.
# ─────────────────────────────────────────────────────────────────

# skill_name → category
SKILL_CATALOGUE: dict[str, str] = {
    # ── programming ──────────────────────────────────────────────
    "python":          "programming",
    "r":               "programming",
    "java":            "programming",
    "scala":           "programming",
    "javascript":      "programming",
    "typescript":      "programming",
    "go":              "programming",
    "bash":            "programming",
    "shell scripting": "programming",
    "sql":             "programming",

    # ── database ─────────────────────────────────────────────────
    "mysql":           "database",
    "postgresql":      "database",
    "mongodb":         "database",
    "snowflake":       "database",
    "bigquery":        "database",
    "redshift":        "database",
    "elasticsearch":   "database",
    "cassandra":       "database",
    "dynamodb":        "database",
    "redis":           "database",
    "hive":            "database",
    "oracle":          "database",
    "sql server":      "database",

    # ── cloud ────────────────────────────────────────────────────
    "aws":             "cloud",
    "azure":           "cloud",
    "gcp":             "cloud",
    "google cloud":    "cloud",
    "databricks":      "cloud",
    "azure data factory": "cloud",
    "azure synapse":   "cloud",
    "azure ml":        "cloud",
    "vertex ai":       "cloud",
    "sagemaker":       "cloud",
    "glue":            "cloud",
    "athena":          "cloud",
    "kinesis":         "cloud",
    "emr":             "cloud",
    "lambda":          "cloud",
    "terraform":       "cloud",

    # ── visualization ────────────────────────────────────────────
    "power bi":        "visualization",
    "tableau":         "visualization",
    "looker":          "visualization",
    "looker studio":   "visualization",
    "excel":           "visualization",
    "matplotlib":      "visualization",
    "plotly":          "visualization",
    "qlik":            "visualization",
    "metabase":        "visualization",
    "superset":        "visualization",
    "grafana":         "visualization",
    "streamlit":       "visualization",
    "power query":     "visualization",
    "dax":             "visualization",

    # ── ml_ai ────────────────────────────────────────────────────
    "machine learning": "ml_ai",
    "deep learning":    "ml_ai",
    "nlp":              "ml_ai",
    "tensorflow":       "ml_ai",
    "pytorch":          "ml_ai",
    "scikit-learn":     "ml_ai",
    "xgboost":          "ml_ai",
    "lightgbm":         "ml_ai",
    "mlflow":           "ml_ai",
    "kubeflow":         "ml_ai",
    "hugging face":     "ml_ai",
    "langchain":        "ml_ai",
    "openai":           "ml_ai",
    "generative ai":    "ml_ai",
    "llm":              "ml_ai",
    "rag":              "ml_ai",
    "transformers":     "ml_ai",

    # ── data engineering ─────────────────────────────────────────
    "spark":            "data_engineering",
    "pyspark":          "data_engineering",
    "kafka":            "data_engineering",
    "airflow":          "data_engineering",
    "dbt":              "data_engineering",
    "hadoop":           "data_engineering",
    "flink":            "data_engineering",
    "hudi":             "data_engineering",
    "iceberg":          "data_engineering",
    "delta lake":       "data_engineering",
    "dataflow":         "data_engineering",
    "fivetran":         "data_engineering",
    "airbyte":          "data_engineering",
    "nifi":             "data_engineering",
    "prefect":          "data_engineering",
    "dagster":          "data_engineering",
    "etl":              "data_engineering",
    "elt":              "data_engineering",

    # ── libraries / tools ────────────────────────────────────────
    "pandas":          "library",
    "numpy":           "library",
    "docker":          "library",
    "kubernetes":      "library",
    "git":             "library",
    "fastapi":         "library",
    "flask":           "library",
    "statistics":      "library",
    "dask":            "library",
    "polars":          "library",
    "ci/cd":           "library",
}

# Build pattern list once at import time.
# Multi-word and hyphenated skills need special handling.
def _make_skill_pattern(skill: str) -> re.Pattern:
    """
    For hyphenated skills like 'scikit-learn' or 'ci/cd':
      use a flexible pattern that matches with or without the separator.
    For normal skills: standard word boundary.
    """
    escaped = re.escape(skill)
    # replace escaped hyphen/slash with a flexible separator
    flexible = escaped.replace(r'\-', r'[\-\s]?').replace(r'\/', r'[\/\s]?')
    return re.compile(r'(?<![a-zA-Z])' + flexible + r'(?![a-zA-Z])', re.IGNORECASE)

_SKILL_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    (skill, category, _make_skill_pattern(skill))
    for skill, category in SKILL_CATALOGUE.items()
]


def extract_skills_from_text(text: str) -> list[tuple[str, str]]:
    """
    Returns list of (display_name, category) tuples.
    display_name: properly cased (e.g. "Python", "SQL", "Power BI").
    """
    found = []
    text_lower = text.lower()
    for skill, category, pattern in _SKILL_PATTERNS:
        if pattern.search(text_lower):
            # display name: uppercase short acronyms, title-case the rest
            if len(skill) <= 3 or skill in {"sql", "gcp", "aws", "etl", "elt",
                                             "nlp", "llm", "rag", "dax", "dbt"}:
                display = skill.upper()
            else:
                display = skill.title()
            found.append((display, category))
    return found


# ─────────────────────────────────────────────────────────────────
# FIX 4 — CITY NORMALIZATION + DESCRIPTION FALLBACK
# Previous: area[-1] only, no fallback for area=["India"].
#           Missing suburb → major city mappings.
# Fixed:    try description text extraction when area gives only "India".
# ─────────────────────────────────────────────────────────────────
CITY_NORMALIZE: dict[str, str] = {
    # Bangalore
    "bengaluru": "Bangalore", "bangalore": "Bangalore",
    "electronic city": "Bangalore", "whitefield": "Bangalore",
    "koramangala": "Bangalore", "hsr layout": "Bangalore",
    # Delhi NCR
    "delhi": "Delhi NCR", "new delhi": "Delhi NCR",
    "gurugram": "Delhi NCR", "gurgaon": "Delhi NCR",
    "noida": "Delhi NCR", "faridabad": "Delhi NCR",
    "greater noida": "Delhi NCR",
    # Mumbai
    "mumbai": "Mumbai", "bombay": "Mumbai",
    "navi mumbai": "Mumbai", "thane": "Mumbai",
    "rabale": "Mumbai", "goregaon east": "Mumbai",
    "powai": "Mumbai", "bandra": "Mumbai",
    # Pune
    "pune": "Pune", "yerwada": "Pune",
    "hinjewadi": "Pune", "wakad": "Pune", "baner": "Pune",
    # Other tier-1
    "hyderabad": "Hyderabad", "secunderabad": "Hyderabad",
    "chennai": "Chennai", "madras": "Chennai",
    "kolkata": "Kolkata", "calcutta": "Kolkata",
    "beleghata": "Kolkata", "salt lake": "Kolkata",
    "ahmedabad": "Ahmedabad",
    "kochi": "Kochi", "cochin": "Kochi",
    # Tier-2
    "jaipur": "Jaipur", "sanganer": "Jaipur",
    "chandigarh": "Chandigarh",
    "vadodara": "Vadodara",
    "coimbatore": "Coimbatore",
    "trivandrum": "Thiruvananthapuram",
    "thiruvananthapuram": "Thiruvananthapuram",
    "madurai": "Madurai",
    "nagpur": "Nagpur",
    "indore": "Indore",
    "bhubaneswar": "Bhubaneswar",
}

# Pattern to extract city from description body text
_CITY_FROM_DESC = re.compile(
    r'(?:location|based\s+(?:out\s+of|in)|office\s+(?:in\s+)?|city)\s*[:\-]?\s*'
    r'(bangalore|bengaluru|hyderabad|mumbai|delhi|pune|chennai|kolkata|'
    r'gurgaon|gurugram|noida|ahmedabad|kochi|jaipur|chandigarh|'
    r'coimbatore|trivandrum|thiruvananthapuram|bhubaneswar|indore|nagpur)',
    re.IGNORECASE,
)


def normalize_city(raw_city: str, description: str = "") -> str:
    """
    1. Try normalising the API-provided city name.
    2. If result is empty or "India", scan description text for a city mention.
    3. Return "" if nothing useful found (frontend filters these as remote/pan-India).
    """
    key = (raw_city or "").lower().strip()
    normalized = CITY_NORMALIZE.get(key, (raw_city or "").strip().title())

    if normalized.lower() in ("india", "in", ""):
        # Try extracting from description
        m = _CITY_FROM_DESC.search(description)
        if m:
            found = m.group(1).lower().strip()
            normalized = CITY_NORMALIZE.get(found, found.title())

    if normalized.lower() in ("india", "in"):
        return ""   # caller treats empty string as "Remote / Pan-India"

    return normalized


# ─────────────────────────────────────────────────────────────────
# EXTRACT
# ─────────────────────────────────────────────────────────────────
def extract_jobs(what: str = "data analyst", where: str = "india",
                 num_pages: int = 2) -> list:
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        log.info("No Adzuna credentials — using mock data")
        return _mock_jobs()
    all_jobs = []
    for page in range(1, num_pages + 1):
        try:
            r = requests.get(f"{ADZUNA_BASE}/jobs/in/search/{page}", params={
                "app_id":           ADZUNA_APP_ID,
                "app_key":          ADZUNA_APP_KEY,
                "what":             what,
                "where":            where,
                "results_per_page": 50,
                "content-type":     "application/json",
                "sort_by":          "date",
            }, timeout=30)
            r.raise_for_status()
            jobs = r.json().get("results", [])
            all_jobs.extend(jobs)
            log.info(f"  Page {page}: {len(jobs)} jobs fetched")
            time.sleep(1)
        except Exception as e:
            log.error(f"API error on page {page}: {e}")
    return all_jobs


# ─────────────────────────────────────────────────────────────────
# TRANSFORM
# ─────────────────────────────────────────────────────────────────
def transform_job(raw: dict) -> dict | None:
    title   = (raw.get("title") or "").strip()
    company = (raw.get("company") or {}).get("display_name", "").strip()
    if not title or not company:
        return None

    # Clean encoding artifacts (â€" → –, etc.)
    title = title.encode("utf-8", "ignore").decode("utf-8")
    title = re.sub(r'[\x80-\x9f]', '', title)      # stray control chars
    title = title.replace("â\x80\x93", "–")         # common mis-encoded en-dash

    area     = (raw.get("location") or {}).get("area", [])
    raw_city = area[-1] if area else ""
    desc     = (raw.get("description") or "").strip()
    city     = normalize_city(raw_city, desc)

    s_min, s_max, s_avg, is_predicted = extract_salary(raw, title)
    exp_min, exp_max                  = extract_experience(desc)
    skills_with_cats                  = extract_skills_from_text(desc + " " + title)

    try:
        date_posted = datetime.fromisoformat(
            raw.get("created", "").replace("Z", "+00:00")
        ).date()
    except Exception:
        date_posted = datetime.today().date()

    location = f"{city}, IN" if city else "Remote / Pan-India"

    return {
        "external_id":      str(raw.get("id", "")),
        "title":            title,
        "company":          company,
        "location":         location,
        "city":             city,        # empty string = pan-India / remote
        "country":          "IN",
        "salary_min":       s_min,
        "salary_max":       s_max,
        "salary_avg":       s_avg,
        "salary_is_predicted": is_predicted,
        "employment_type":  "FULLTIME",
        "experience_min":   exp_min,
        "experience_max":   exp_max,
        "description":      desc,
        "date_posted":      date_posted,
        "redirect_url":     raw.get("redirect_url", ""),
        "source":           "adzuna",
        "skills":           skills_with_cats,   # list of (display_name, category)
    }


# ─────────────────────────────────────────────────────────────────
# LOAD
# ─────────────────────────────────────────────────────────────────
def get_or_create_skill(cur, skill_name: str, category: str) -> int | None:
    """Return skill id, creating with correct category if needed."""
    cur.execute("SELECT id FROM skills WHERE skill_name = %s", (skill_name,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        """INSERT INTO skills (skill_name, category)
           VALUES (%s, %s)
           ON CONFLICT (skill_name) DO UPDATE SET category = EXCLUDED.category
           RETURNING id""",
        (skill_name, category)
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("SELECT id FROM skills WHERE skill_name = %s", (skill_name,))
    row = cur.fetchone()
    return row[0] if row else None


# ─────────────────────────────────────────────────────────────────
# FIX 5 — CROSS-DAY DEDUPLICATION
# Previous: ON CONFLICT (external_id) only. Same role re-posted next
#           day gets a new external_id and passes through.
# Fixed:    before insert, check title+company+city within last 7 days.
# ─────────────────────────────────────────────────────────────────
def _is_recent_duplicate(cur, title: str, company: str, city: str) -> bool:
    """True if this title+company+city was stored within the last 7 days."""
    cur.execute("""
        SELECT 1 FROM jobs
        WHERE title = %s
          AND company = %s
          AND city = %s
          AND date_fetched >= NOW() - INTERVAL '7 days'
        LIMIT 1
    """, (title, company, city))
    return cur.fetchone() is not None


def load_all(jobs: list):
    conn = get_db()
    inserted = skipped_dup = skipped_ext = errors = 0

    with conn:
        with conn.cursor() as cur:
            for job in jobs:
                try:
                    skills = job.pop("skills", [])

                    # Cross-day dedup check
                    if _is_recent_duplicate(cur, job["title"],
                                            job["company"], job["city"]):
                        skipped_dup += 1
                        continue

                    cur.execute("""
                        INSERT INTO jobs (
                            external_id, title, company, location, city, country,
                            salary_min, salary_max, salary_avg, salary_is_predicted,
                            employment_type, experience_min, experience_max,
                            description, date_posted, redirect_url, source
                        ) VALUES (
                            %(external_id)s, %(title)s, %(company)s, %(location)s,
                            %(city)s, %(country)s,
                            %(salary_min)s, %(salary_max)s, %(salary_avg)s,
                            %(salary_is_predicted)s,
                            %(employment_type)s, %(experience_min)s, %(experience_max)s,
                            %(description)s, %(date_posted)s, %(redirect_url)s,
                            %(source)s
                        )
                        ON CONFLICT (external_id) DO NOTHING
                        RETURNING id
                    """, job)

                    row = cur.fetchone()
                    if not row:
                        skipped_ext += 1
                        continue

                    job_id = row[0]
                    for skill_name, category in skills:
                        skill_id = get_or_create_skill(cur, skill_name, category)
                        if skill_id:
                            cur.execute(
                                """INSERT INTO job_skills (job_id, skill_id)
                                   VALUES (%s, %s) ON CONFLICT DO NOTHING""",
                                (job_id, skill_id)
                            )
                    inserted += 1

                except Exception as e:
                    log.error(f"Error loading '{job.get('title', '?')}': {e}")
                    errors += 1

    conn.close()
    log.info(
        f"Load done: {inserted} inserted, "
        f"{skipped_dup} cross-day dups, "
        f"{skipped_ext} external_id dups, "
        f"{errors} errors"
    )


# ─────────────────────────────────────────────────────────────────
# ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────
def run_etl():
    log.info("=" * 60)
    log.info("  JOBWHIZ LAB — ETL STARTING (Adzuna → PostgreSQL)")
    log.info("=" * 60)

    delete_old_jobs(days_to_keep=30)

    # Pre-warm histogram cache for common roles so fallback is instant
    for kw in set(ROLE_TO_KEYWORD.values()):
        _histogram_fallback(kw)

    queries = [
        {"what": "data analyst",              "where": "india"},
        {"what": "data scientist",            "where": "india"},
        {"what": "data engineer",             "where": "india"},
        {"what": "business analyst",          "where": "india"},
        {"what": "machine learning engineer", "where": "india"},
    ]

    for q in queries:
        log.info(f"\n→ '{q['what']}' in '{q['where']}'")
        raw_jobs = extract_jobs(q["what"], q["where"], num_pages=2)

        # transform_job no longer takes salary_cache — reads from raw directly
        clean = [j for j in (transform_job(r) for r in raw_jobs) if j]
        log.info(f"  Transformed: {len(clean)} valid jobs")

        if clean:
            load_all(clean)

    log.info("\n" + "=" * 60)
    log.info("  ETL COMPLETE")
    log.info("=" * 60)


# ─────────────────────────────────────────────────────────────────
# MOCK DATA  (used when no Adzuna credentials)
# Updated to include salary_min/salary_max so mock flow mirrors real flow
# ─────────────────────────────────────────────────────────────────
def _mock_jobs():
    return [
        {"id": "mock_001", "title": "Data Analyst", "company": {"display_name": "Flipkart"},
         "location": {"area": ["India", "Karnataka", "Bangalore"]},
         "salary_min": 700000, "salary_max": 1200000, "salary_is_predicted": False,
         "description": "Data Analyst with 3–5 years of experience. Python, SQL, Power BI, Tableau, Excel, Pandas.",
         "created": "2025-01-15T10:00:00Z", "redirect_url": ""},

        {"id": "mock_002", "title": "Senior Data Analyst", "company": {"display_name": "Swiggy"},
         "location": {"area": ["India", "Karnataka", "Bangalore"]},
         "salary_min": 1000000, "salary_max": 1800000, "salary_is_predicted": False,
         "description": "Senior Data Analyst with 5–8 years experience. Python, SQL, Spark, Airflow, AWS, Machine Learning, dbt.",
         "created": "2025-01-20T10:00:00Z", "redirect_url": ""},

        {"id": "mock_003", "title": "Data Scientist", "company": {"display_name": "Meesho"},
         "location": {"area": ["India", "Karnataka", "Bangalore"]},
         "salary_min": 1200000, "salary_max": 2000000, "salary_is_predicted": False,
         "description": "Data Scientist. Experience: 3–6 years. Python, TensorFlow, PyTorch, SQL, Scikit-learn, NLP, MLflow.",
         "created": "2025-01-22T10:00:00Z", "redirect_url": ""},

        {"id": "mock_004", "title": "Data Engineer", "company": {"display_name": "Razorpay"},
         "location": {"area": ["India", "Karnataka", "Bangalore"]},
         "salary_min": 1500000, "salary_max": 2500000, "salary_is_predicted": False,
         "description": "Data Engineer. Exp: 5–8 yrs. Python, Spark, Kafka, Airflow, AWS, SQL, Databricks, dbt, Delta Lake.",
         "created": "2025-01-21T10:00:00Z", "redirect_url": ""},

        {"id": "mock_005", "title": "ML Engineer", "company": {"display_name": "PhonePe"},
         "location": {"area": ["India", "Karnataka", "Bangalore"]},
         "salary_min": 1800000, "salary_max": 3000000, "salary_is_predicted": False,
         "description": "ML Engineer with 4–7 years of experience. Python, TensorFlow, PyTorch, Deep Learning, NLP, AWS, MLflow, Kubernetes, Docker.",
         "created": "2025-01-24T10:00:00Z", "redirect_url": ""},

        {"id": "mock_006", "title": "BI Analyst", "company": {"display_name": "Zomato"},
         "location": {"area": ["India", "Delhi", "Delhi"]},
         "salary_min": 800000, "salary_max": 1400000, "salary_is_predicted": False,
         "description": "BI Analyst. 2–4 years experience. SQL, Tableau, Power BI, Excel, Looker, DAX, Power Query.",
         "created": "2025-01-18T10:00:00Z", "redirect_url": ""},

        {"id": "mock_007", "title": "Data Analyst", "company": {"display_name": "Ola"},
         "location": {"area": ["India", "Maharashtra", "Mumbai"]},
         "salary_min": 650000, "salary_max": 1100000, "salary_is_predicted": True,
         "description": "Data Analyst. Location: Mumbai. 1–3 years experience. SQL, Excel, Python, R, Tableau, Statistics.",
         "created": "2025-01-19T10:00:00Z", "redirect_url": ""},

        {"id": "mock_008", "title": "Business Analyst", "company": {"display_name": "Paytm"},
         "location": {"area": ["India", "Uttar Pradesh", "Noida"]},
         "salary_min": 750000, "salary_max": 1300000, "salary_is_predicted": False,
         "description": "Business Analyst with 3–5 years experience. SQL, Excel, Tableau, Python, Jira, Confluence.",
         "created": "2025-01-17T10:00:00Z", "redirect_url": ""},

        {"id": "mock_009", "title": "Data Engineer", "company": {"display_name": "CRED"},
         "location": {"area": ["India"]},  # no city in area → test description fallback
         "salary_min": None, "salary_max": None, "salary_is_predicted": True,
         "description": "Data Engineer at CRED. Location: Bangalore. Experience range: 6–10 years. Python, PySpark, Kafka, Airflow, GCP, BigQuery, dbt, Terraform.",
         "created": "2025-01-23T10:00:00Z", "redirect_url": ""},

        {"id": "mock_010", "title": "Analytics Engineer", "company": {"display_name": "Nykaa"},
         "location": {"area": ["India", "Maharashtra", "Mumbai"]},
         "salary_min": 1100000, "salary_max": 1900000, "salary_is_predicted": False,
         "description": "Analytics Engineer. Exp: 4–6 yrs. SQL, Python, dbt, Snowflake, Looker, Airflow, Git, Fivetran.",
         "created": "2025-01-16T10:00:00Z", "redirect_url": ""},
    ]


if __name__ == "__main__":
    run_etl()