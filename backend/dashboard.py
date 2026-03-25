"""
JobWhiz Lab — Dashboard Routes
"""

from fastapi import APIRouter
from db import query

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/kpis")
def dashboard_kpis():
    return query("""
        SELECT
            COUNT(*)                          AS total_jobs,
            ROUND(AVG(salary_avg)::numeric, 2) AS avg_salary,
            COUNT(DISTINCT company)           AS total_companies,
            COUNT(DISTINCT city)              AS total_cities,
            COUNT(DISTINCT date_posted)       AS active_days
        FROM jobs
    """)[0]


@router.get("/jobs-by-city")
def jobs_by_city():
    return query("""
        SELECT city, COUNT(*) AS job_count
        FROM jobs
        WHERE city IS NOT NULL AND city != ''
        GROUP BY city
        ORDER BY job_count DESC
        LIMIT 10
    """)


@router.get("/jobs-by-role")
def jobs_by_role():
    return query("""
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
            COUNT(*) AS job_count
        FROM jobs
        GROUP BY role
        ORDER BY job_count DESC
    """)


@router.get("/salary-distribution")
def salary_distribution():
    return query("""
        SELECT
            CASE
                WHEN salary_avg < 5  THEN 'Under 5L'
                WHEN salary_avg < 8  THEN '5–8L'
                WHEN salary_avg < 12 THEN '8–12L'
                WHEN salary_avg < 18 THEN '12–18L'
                WHEN salary_avg < 25 THEN '18–25L'
                ELSE '25L+'
            END AS salary_range,
            COUNT(*) AS count
        FROM jobs
        WHERE salary_avg IS NOT NULL
        GROUP BY salary_range
        ORDER BY MIN(salary_avg)
    """)


@router.get("/hiring-trend")
def hiring_trend():
    return query("""
        SELECT
            TO_CHAR(date_posted, 'YYYY-MM') AS month,
            COUNT(*) AS job_count
        FROM jobs
        WHERE date_posted IS NOT NULL
        GROUP BY month
        ORDER BY month ASC
        LIMIT 12
    """)


@router.get("/top-companies")
def top_companies():
    return query("""
        SELECT company, COUNT(*) AS job_count
        FROM jobs
        WHERE company IS NOT NULL AND company != ''
        GROUP BY company
        ORDER BY job_count DESC
        LIMIT 10
    """)
