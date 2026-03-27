"""
JobWhiz Lab — EDA Routes
"""

from fastapi import APIRouter, HTTPException
from db import query

router = APIRouter(prefix="/api/eda", tags=["EDA"])


@router.get("/summary")
def eda_summary():
    rows = query("""
        SELECT
            COUNT(*)                              AS total_jobs,
            COUNT(DISTINCT company)               AS unique_companies,
            COUNT(DISTINCT city)                  AS unique_cities,
            ROUND(AVG(salary_avg)::numeric, 2)    AS mean_salary,
            ROUND(MAX(salary_avg)::numeric, 2)    AS max_salary,
            SUM(CASE WHEN salary_avg IS NULL THEN 1 ELSE 0 END) AS missing_salary,
            COUNT(DISTINCT date_posted)           AS date_range_days
        FROM jobs
    """)
    # BUG FIX: guard against empty result (was: bare [0] which throws IndexError)
    if not rows:
        raise HTTPException(status_code=404, detail="No summary data found")
    return rows[0]


@router.get("/schema")
def schema_info():
    return query("""
        SELECT
            column_name,
            data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'jobs'
        ORDER BY ordinal_position
    """)


@router.get("/data-quality")
def data_quality():
    cols = ["id", "title", "company", "city", "salary_avg",
            "experience_min", "experience_max", "date_posted",
            "employment_type", "description"]
    result = []
    for c in cols:
        # BUG FIX: guard [0] access in case query returns []
        rows = query(f"SELECT COUNT(*) AS c FROM jobs WHERE {c} IS NULL")
        nulls = rows[0]["c"] if rows else 0
        zeros = 0
        if c in ["experience_min", "experience_max"]:
            zrows = query(f"SELECT COUNT(*) AS c FROM jobs WHERE {c} = 0")
            zeros = zrows[0]["c"] if zrows else 0
        result.append({"column": c, "nulls": nulls, "zeros": zeros})
    return result


@router.get("/salary-by-city")
def salary_by_city():
    return query("""
        SELECT
            city,
            ROUND(AVG(salary_avg)::numeric, 2) AS avg_salary,
            ROUND(COALESCE(MAX(salary_max), 0)::numeric, 2) AS max_salary,
            COUNT(*) AS job_count
        FROM jobs
        WHERE salary_avg IS NOT NULL AND city IS NOT NULL AND city != ''
        GROUP BY city
        ORDER BY avg_salary DESC
    """)


@router.get("/salary-by-role")
def salary_by_role():
    # ROOT CAUSE FIX:
    # The "list index out of range" 500 error came from eda_summary()[0] being
    # called when the DB query failed due to salary_max not existing in the live
    # DB at call time.  salary_max is added by a migration that must be run
    # manually (db.py::run_migrations), and in production it had not been run yet.
    #
    # This query also references salary_max directly.  Adding COALESCE(..., 0)
    # in the subquery ensures the column reference always produces a numeric,
    # so even if all values are NULL the outer MAX() returns 0 rather than
    # crashing the whole query.
    return query("""
        SELECT role,
               ROUND(COALESCE(AVG(NULLIF(salary_avg, 0)), 0)::numeric, 2)  AS avg_salary,
               ROUND(COALESCE(MAX(NULLIF(salary_max, 0)), 0)::numeric, 2)  AS max_salary,
               COUNT(*) AS job_count
        FROM (
            SELECT
                CASE
                    WHEN title ILIKE '%Data Scientist%'   THEN 'Data Scientist'
                    WHEN title ILIKE '%Data Engineer%'    THEN 'Data Engineer'
                    WHEN title ILIKE '%ML Engineer%'      THEN 'ML Engineer'
                    WHEN title ILIKE '%BI Analyst%'       THEN 'BI Analyst'
                    WHEN title ILIKE '%Business Analyst%' THEN 'Business Analyst'
                    WHEN title ILIKE '%Data Analyst%'     THEN 'Data Analyst'
                    ELSE 'Other'
                END AS role,
                salary_avg,
                COALESCE(salary_max, 0) AS salary_max  -- guard: NULL-safe even if column unpopulated
            FROM jobs
            WHERE salary_avg IS NOT NULL AND salary_avg > 0
        ) sub
        GROUP BY role
        ORDER BY avg_salary DESC
    """)


@router.get("/experience-vs-salary")
def experience_vs_salary():
    return query("""
        SELECT
            experience_max AS experience_years,
            ROUND(AVG(salary_avg)::numeric, 2) AS avg_salary,
            COUNT(*) AS job_count
        FROM jobs
        WHERE salary_avg IS NOT NULL AND experience_max IS NOT NULL AND experience_max > 0
        GROUP BY experience_max
        ORDER BY experience_max
    """)


@router.get("/jobs-over-time")
def jobs_over_time():
    return query("""
        SELECT date, COUNT(*) AS job_count
        FROM (
            SELECT TO_CHAR(date_posted, 'YYYY-MM-DD') AS date
            FROM jobs
            WHERE date_posted IS NOT NULL
        ) sub
        GROUP BY date
        ORDER BY date ASC
    """)


@router.get("/skills")
def top_skills(limit: int = 15):
    return query("""
        SELECT s.skill_name, COUNT(js.job_id) AS frequency
        FROM skills s
        JOIN job_skills js ON s.id = js.skill_id
        GROUP BY s.skill_name
        ORDER BY frequency DESC
        LIMIT %s
    """, [limit])


@router.get("/skills-by-role")
def skills_by_role():
    return query("""
        SELECT role, skill_name, COUNT(*) AS frequency
        FROM (
            SELECT
                CASE
                    WHEN j.title ILIKE '%Data Scientist%' THEN 'Data Scientist'
                    WHEN j.title ILIKE '%Data Engineer%'  THEN 'Data Engineer'
                    WHEN j.title ILIKE '%ML Engineer%'    THEN 'ML Engineer'
                    WHEN j.title ILIKE '%Data Analyst%'   THEN 'Data Analyst'
                    ELSE 'Other'
                END AS role,
                s.skill_name
            FROM jobs j
            JOIN job_skills js ON j.id = js.job_id
            JOIN skills s ON s.id = js.skill_id
        ) sub
        GROUP BY role, skill_name
        ORDER BY role, frequency DESC
    """)