"""
JobWhiz Lab — EDA Routes
"""

from fastapi import APIRouter
from db import query

router = APIRouter(prefix="/api/eda", tags=["EDA"])


@router.get("/summary")
def eda_summary():
    return query("""
        SELECT
            COUNT(*)                              AS total_jobs,
            COUNT(DISTINCT company)               AS unique_companies,
            COUNT(DISTINCT city)                  AS unique_cities,
            ROUND(AVG(salary_avg)::numeric, 2)    AS mean_salary,
            ROUND(MAX(salary_avg)::numeric, 2)    AS max_salary,
            SUM(CASE WHEN salary_avg IS NULL THEN 1 ELSE 0 END) AS missing_salary,
            COUNT(DISTINCT date_posted)           AS date_range_days
        FROM jobs
    """)[0]


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
        nulls = query(f"SELECT COUNT(*) AS c FROM jobs WHERE {c} IS NULL")[0]["c"]
        zeros = 0
        if c in ["experience_min", "experience_max"]:
            zeros = query(f"SELECT COUNT(*) AS c FROM jobs WHERE {c} = 0")[0]["c"]
        result.append({"column": c, "nulls": nulls, "zeros": zeros})
    return result


@router.get("/salary-by-city")
def salary_by_city():
    # city is a real column — GROUP BY city is fine
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
    # FIX: PostgreSQL forbids GROUP BY on a SELECT alias (CASE ... END AS role).
    # Wrap in a subquery so the outer query groups by the materialised column.
    return query("""
        SELECT role,
               ROUND(COALESCE(AVG(NULLIF(salary_avg, 0)), 0)::numeric, 2) AS avg_salary,
               ROUND(COALESCE(MAX(NULLIF(salary_max, 0)), 0)::numeric, 2) AS max_salary,
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
                salary_max
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
    # FIX: GROUP BY alias 'date' — wrap in subquery
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
    # FIX: GROUP BY alias 'role' — wrap in subquery
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