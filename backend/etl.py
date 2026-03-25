"""
JobWhiz Lab — ETL Pipeline (Adzuna → PostgreSQL)
Extract → Transform → Load  |  run: python etl.py
"""

import os
import re
import time
import logging
import requests
from datetime import datetime
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
print("DB HOST:", os.getenv("DB_HOST"))

# ── CLEANUP ───────────────────────────────────────────────────────
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


# ── SALARY LOOKUP ─────────────────────────────────────────────────
_salary_cache = {}

def get_salary_estimate(job_title_keyword):
    key = job_title_keyword.lower()
    if key in _salary_cache:
        return _salary_cache[key]
    try:
        r = requests.get(f"{ADZUNA_BASE}/jobs/in/histogram", params={
            "app_id": ADZUNA_APP_ID, "app_key": ADZUNA_APP_KEY, "what": job_title_keyword,
        }, timeout=15)
        r.raise_for_status()
        histogram = r.json().get("histogram", {})
        if not histogram:
            return None, None, None
        buckets = sorted([(int(k), v) for k, v in histogram.items() if v > 0])
        total   = sum(v for _, v in buckets)
        if total == 0:
            return None, None, None
        avg_inr  = sum(k * v for k, v in buckets) / total
        def to_lpa(val): return round(val / 100000, 1)
        result = (to_lpa(avg_inr), to_lpa(buckets[0][0]), to_lpa(buckets[-1][0]))
        _salary_cache[key] = result
        time.sleep(0.5)
        return result
    except Exception as e:
        log.warning(f"Salary lookup failed for '{job_title_keyword}': {e}")
        return None, None, None


ROLE_SALARY_MAP = {
    "data analyst":        "data analyst",
    "senior data analyst": "senior data analyst",
    "data scientist":      "data scientist",
    "data engineer":       "data engineer",
    "ml engineer":         "machine learning engineer",
    "business analyst":    "business analyst",
    "bi analyst":          "business intelligence analyst",
    "analytics engineer":  "analytics engineer",
}

def get_salary_keyword(title):
    t = title.lower()
    for role, keyword in ROLE_SALARY_MAP.items():
        if role in t:
            return keyword
    return "data analyst"


# ── EXTRACT ───────────────────────────────────────────────────────
def extract_jobs(what="data analyst", where="india", num_pages=2):
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        log.info("No Adzuna credentials — using mock data")
        return _mock_jobs()
    all_jobs = []
    for page in range(1, num_pages + 1):
        try:
            r = requests.get(f"{ADZUNA_BASE}/jobs/in/search/{page}", params={
                "app_id": ADZUNA_APP_ID, "app_key": ADZUNA_APP_KEY,
                "what": what, "where": where, "results_per_page": 50,
                "content-type": "application/json", "sort_by": "date",
            }, timeout=30)
            r.raise_for_status()
            jobs = r.json().get("results", [])
            all_jobs.extend(jobs)
            time.sleep(1)
        except Exception as e:
            log.error(f"API error on page {page}: {e}")
    return all_jobs


# ── TRANSFORM ─────────────────────────────────────────────────────
KNOWN_SKILLS = [
    "python", "r", "scala", "java", "javascript",
    "sql", "mysql", "postgresql", "mongodb", "snowflake",
    "bigquery", "redshift", "power bi", "tableau", "looker",
    "excel", "matplotlib", "plotly", "aws", "azure", "gcp",
    "databricks", "machine learning", "deep learning", "nlp",
    "tensorflow", "pytorch", "scikit-learn", "spark", "kafka",
    "airflow", "dbt", "pandas", "numpy", "hadoop", "pyspark",
    "docker", "kubernetes", "git", "fastapi", "flask", "statistics"
]

CITY_NORMALIZE = {
    "bengaluru": "Bangalore", "bangalore": "Bangalore",
    "delhi": "Delhi NCR", "new delhi": "Delhi NCR",
    "gurugram": "Delhi NCR", "gurgaon": "Delhi NCR", "noida": "Delhi NCR",
    "mumbai": "Mumbai", "bombay": "Mumbai", "navi mumbai": "Mumbai",
    "hyderabad": "Hyderabad", "pune": "Pune",
    "chennai": "Chennai", "kolkata": "Kolkata",
    "ahmedabad": "Ahmedabad", "kochi": "Kochi",
}

def extract_skills_from_text(text):
    text_lower = text.lower()
    return [
        skill.title() if len(skill) > 2 else skill.upper()
        for skill in KNOWN_SKILLS
        if re.search(r'\b' + re.escape(skill) + r'\b', text_lower)
    ]

def normalize_city(raw_city):
    return CITY_NORMALIZE.get((raw_city or "").lower().strip(), (raw_city or "").strip().title())

def extract_experience(text):
    for pat in [r'(\d+)\s*[-to]+\s*(\d+)\s*years?', r'(\d+)\+\s*years?',
                r'minimum\s+(\d+)\s*years?', r'(\d+)\s*years?\s+experience']:
        m = re.search(pat, text.lower())
        if m:
            g = m.groups()
            return int(g[0]), int(g[1]) if len(g) > 1 and g[1] else int(g[0]) + 2
    return 0, 0

def transform_job(raw, salary_cache):
    title   = (raw.get("title") or "").strip()
    company = (raw.get("company") or {}).get("display_name", "").strip()
    if not title or not company:
        return None
    area     = (raw.get("location") or {}).get("area", [])
    city     = normalize_city(area[-1] if area else "")
    desc     = (raw.get("description") or "").strip()
    sal_kw   = get_salary_keyword(title)
    sal_avg, _, sal_max = salary_cache.get(sal_kw, (None, None, None))
    exp_min, exp_max = extract_experience(desc)
    try:
        date_posted = datetime.fromisoformat(raw.get("created", "").replace("Z", "+00:00")).date()
    except Exception:
        date_posted = datetime.today().date()
    return {
        "external_id": str(raw.get("id", "")),
        "title": title, "company": company,
        "location": f"{city}, IN" if city else "India",
        "city": city, "country": "IN",
        "salary_max": sal_max, "salary_avg": sal_avg,
        "employment_type": "FULLTIME",
        "experience_min": exp_min, "experience_max": exp_max,
        "description": desc, "date_posted": date_posted,
        "redirect_url": raw.get("redirect_url", ""),
        "source": "adzuna",
        "skills": extract_skills_from_text(desc + " " + title),
    }


# ── LOAD ──────────────────────────────────────────────────────────
def get_or_create_skill(cur, skill_name):
    cur.execute("SELECT id FROM skills WHERE skill_name = %s", (skill_name,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO skills (skill_name) VALUES (%s) ON CONFLICT (skill_name) DO NOTHING RETURNING id",
        (skill_name,)
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("SELECT id FROM skills WHERE skill_name = %s", (skill_name,))
    return cur.fetchone()[0]

def load_all(jobs):
    conn = get_db()
    inserted = duplicates = errors = 0
    with conn:
        with conn.cursor() as cur:
            for job in jobs:
                try:
                    skills = job.pop("skills", [])
                    cur.execute("""
                        INSERT INTO jobs (
                            external_id, title, company, location, city, country,
                            salary_max, salary_avg, employment_type,
                            experience_min, experience_max,
                            description, date_posted, redirect_url, source
                        ) VALUES (
                            %(external_id)s, %(title)s, %(company)s, %(location)s,
                            %(city)s, %(country)s, %(salary_max)s, %(salary_avg)s,
                            %(employment_type)s, %(experience_min)s, %(experience_max)s,
                            %(description)s, %(date_posted)s, %(redirect_url)s, %(source)s
                        )
                        ON CONFLICT (external_id) DO NOTHING
                        RETURNING id
                    """, job)
                    row = cur.fetchone()
                    if not row:
                        duplicates += 1
                        continue
                    job_id = row[0]
                    for skill_name in skills:
                        skill_id = get_or_create_skill(cur, skill_name)
                        cur.execute(
                            "INSERT INTO job_skills (job_id, skill_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                            (job_id, skill_id)
                        )
                    inserted += 1
                except Exception as e:
                    log.error(f"Error loading job: {e}")
                    errors += 1
    conn.close()
    log.info(f"Load done: {inserted} inserted, {duplicates} duplicates, {errors} errors")


# ── ORCHESTRATOR ──────────────────────────────────────────────────
def run_etl():
    log.info("=" * 55)
    log.info("  JOBWHIZ LAB — ETL STARTING (Adzuna → PostgreSQL)")
    log.info("=" * 55)

    delete_old_jobs(days_to_keep=30)

    # Pre-fetch salary benchmarks
    salary_cache = {}
    for role_kw in set(ROLE_SALARY_MAP.values()):
        salary_cache[role_kw] = get_salary_estimate(role_kw)

    queries = [
        {"what": "data analyst",              "where": "india"},
        {"what": "data scientist",            "where": "india"},
        {"what": "data engineer",             "where": "india"},
        {"what": "business analyst",          "where": "india"},
        {"what": "machine learning engineer", "where": "india"},
    ]
    for q in queries:
        log.info(f"→ '{q['what']}' in '{q['where']}'")
        raw   = extract_jobs(q["what"], q["where"], num_pages=2)
        clean = [j for j in (transform_job(r, salary_cache) for r in raw) if j]
        if clean:
            load_all(clean)

    log.info("=" * 55)
    log.info("  ETL COMPLETE")
    log.info("=" * 55)


# ── MOCK DATA ─────────────────────────────────────────────────────
def _mock_jobs():
    return [
        {"id": "mock_001", "title": "Data Analyst", "company": {"display_name": "Flipkart"},
         "location": {"area": ["India", "Karnataka", "Bangalore"]},
         "description": "Data Analyst with Python, SQL, Power BI, Tableau, Excel.",
         "created": "2025-01-15T10:00:00Z", "redirect_url": ""},
        {"id": "mock_002", "title": "Senior Data Analyst", "company": {"display_name": "Swiggy"},
         "location": {"area": ["India", "Karnataka", "Bangalore"]},
         "description": "Senior Data Analyst. Python, SQL, Spark, Airflow, AWS, machine learning.",
         "created": "2025-01-20T10:00:00Z", "redirect_url": ""},
        {"id": "mock_003", "title": "Data Scientist", "company": {"display_name": "Meesho"},
         "location": {"area": ["India", "Karnataka", "Bangalore"]},
         "description": "Data Scientist with Python, TensorFlow, PyTorch, SQL, Scikit-learn, NLP.",
         "created": "2025-01-22T10:00:00Z", "redirect_url": ""},
        {"id": "mock_004", "title": "Data Engineer", "company": {"display_name": "Razorpay"},
         "location": {"area": ["India", "Karnataka", "Bangalore"]},
         "description": "Data Engineer with Python, Spark, Kafka, Airflow, AWS, SQL, Databricks.",
         "created": "2025-01-21T10:00:00Z", "redirect_url": ""},
        {"id": "mock_005", "title": "ML Engineer", "company": {"display_name": "PhonePe"},
         "location": {"area": ["India", "Karnataka", "Bangalore"]},
         "description": "ML Engineer with Python, TensorFlow, PyTorch, Deep Learning, NLP, AWS.",
         "created": "2025-01-24T10:00:00Z", "redirect_url": ""},
        {"id": "mock_006", "title": "BI Analyst", "company": {"display_name": "Zomato"},
         "location": {"area": ["India", "Delhi", "Delhi"]},
         "description": "BI Analyst. SQL, Tableau, Power BI, Excel, Looker.",
         "created": "2025-01-18T10:00:00Z", "redirect_url": ""},
        {"id": "mock_007", "title": "Data Analyst", "company": {"display_name": "Ola"},
         "location": {"area": ["India", "Maharashtra", "Mumbai"]},
         "description": "Data Analyst. SQL, Excel, Python, R, Tableau.",
         "created": "2025-01-19T10:00:00Z", "redirect_url": ""},
        {"id": "mock_008", "title": "Business Analyst", "company": {"display_name": "Paytm"},
         "location": {"area": ["India", "Uttar Pradesh", "Noida"]},
         "description": "Business Analyst. SQL, Excel, Tableau, Python.",
         "created": "2025-01-17T10:00:00Z", "redirect_url": ""},
        {"id": "mock_009", "title": "Data Analyst", "company": {"display_name": "CRED"},
         "location": {"area": ["India", "Karnataka", "Bangalore"]},
         "description": "Data Analyst. Python, SQL, Pandas, NumPy, Matplotlib, Power BI.",
         "created": "2025-01-23T10:00:00Z", "redirect_url": ""},
        {"id": "mock_010", "title": "Data Analyst", "company": {"display_name": "Nykaa"},
         "location": {"area": ["India", "Maharashtra", "Mumbai"]},
         "description": "Data Analyst. SQL, Python, Excel, Looker, Power BI.",
         "created": "2025-01-16T10:00:00Z", "redirect_url": ""},
    ]


if __name__ == "__main__":
    run_etl()
