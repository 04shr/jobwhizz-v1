"""
JobWhiz Lab — DSS Routes
Decision Support System: gap analysis, skill ROI, career paths, action plans.
All salary values pulled from live DB — zero hardcoding.
"""

import os
import json
import re
import math
from fastapi import APIRouter, Form, HTTPException
from groq import Groq
from db import query

router = APIRouter(prefix="/api/dss", tags=["DSS"])
client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def get_role_salary_map():
    rows = query("""
        SELECT CASE
            WHEN title ILIKE '%Data Engineer%'    THEN 'Data Engineer'
            WHEN title ILIKE '%Data Scientist%'   THEN 'Data Scientist'
            WHEN title ILIKE '%ML Engineer%'      THEN 'ML Engineer'
            WHEN title ILIKE '%Data Analyst%'     THEN 'Data Analyst'
            WHEN title ILIKE '%Business Analyst%' THEN 'Business Analyst'
            WHEN title ILIKE '%AI Engineer%'      THEN 'AI Engineer'
            ELSE 'Other' END AS role,
            ROUND(AVG(salary_avg)::numeric, 2) AS avg_sal
        FROM jobs WHERE salary_avg IS NOT NULL GROUP BY role
    """)
    return {r["role"]: float(r["avg_sal"]) for r in rows}


def get_skill_salary_premium():
    overall = float(query("SELECT ROUND(AVG(salary_avg)::numeric,2) AS avg FROM jobs WHERE salary_avg IS NOT NULL")[0]["avg"])
    rows = query("""
        SELECT s.skill_name,
               ROUND(AVG(j.salary_avg)::numeric, 2) AS skill_avg,
               COUNT(DISTINCT j.id) AS job_count
        FROM skills s
        JOIN job_skills js ON s.id = js.skill_id
        JOIN jobs j ON j.id = js.job_id
        WHERE j.salary_avg IS NOT NULL
        GROUP BY s.skill_name
        HAVING COUNT(DISTINCT j.id) >= 3
        ORDER BY skill_avg DESC
    """)
    return {r["skill_name"]: round(float(r["skill_avg"]) - overall, 2) for r in rows}


_LEARN_WEEKS = {
    "SQL": 4, "Python": 6, "Power Bi": 3, "Tableau": 3, "Azure": 8, "Aws": 8,
    "Spark": 10, "Kafka": 10, "Machine Learning": 16, "Tensorflow": 12, "Pytorch": 12,
    "Docker": 5, "Dbt": 4, "Airflow": 6, "Databricks": 6, "Snowflake": 4,
    "Pyspark": 8, "Nlp": 12, "R": 5, "Scala": 10,
}

_DEFAULT_LADDER = {
    "Data Analyst":     ["Senior Data Analyst", "Data Scientist", "Data Engineer"],
    "Business Analyst": ["Senior Business Analyst", "Data Analyst", "Product Analyst"],
    "Data Scientist":   ["Senior Data Scientist", "ML Engineer", "AI Engineer"],
    "Data Engineer":    ["Senior Data Engineer", "ML Engineer", "Data Architect"],
    "ML Engineer":      ["Senior ML Engineer", "AI Engineer", "Data Scientist"],
    "AI Engineer":      ["Senior AI Engineer", "ML Engineer", "Data Scientist"],
    "Software Engineer":["Senior SWE", "Data Engineer", "ML Engineer"],
}


@router.get("/market-pulse")
def market_pulse():
    rows = query("""
        SELECT COUNT(*) AS total_jobs, ROUND(AVG(salary_avg)::numeric,2) AS avg_salary,
               COUNT(DISTINCT company) AS companies, COUNT(DISTINCT city) AS cities
        FROM jobs
    """)
    top_role = query("""
        SELECT CASE
            WHEN title ILIKE '%Data Engineer%'  THEN 'Data Engineer'
            WHEN title ILIKE '%Data Scientist%' THEN 'Data Scientist'
            WHEN title ILIKE '%ML Engineer%'    THEN 'ML Engineer'
            WHEN title ILIKE '%Data Analyst%'   THEN 'Data Analyst'
            ELSE 'Other' END AS role, COUNT(*) AS cnt
        FROM jobs GROUP BY role ORDER BY cnt DESC LIMIT 1
    """)
    return {**rows[0], "hottest_role": top_role[0]["role"] if top_role else "Data Engineer"}


@router.get("/salary-benchmarks")
def salary_benchmarks():
    by_role = query("""
        SELECT CASE
            WHEN title ILIKE '%Data Engineer%'    THEN 'Data Engineer'
            WHEN title ILIKE '%Data Scientist%'   THEN 'Data Scientist'
            WHEN title ILIKE '%ML Engineer%'      THEN 'ML Engineer'
            WHEN title ILIKE '%Data Analyst%'     THEN 'Data Analyst'
            WHEN title ILIKE '%Business Analyst%' THEN 'Business Analyst'
            WHEN title ILIKE '%AI Engineer%'      THEN 'AI Engineer'
            ELSE 'Other' END AS role,
            ROUND(AVG(salary_avg)::numeric, 2) AS avg_salary
        FROM jobs WHERE salary_avg IS NOT NULL GROUP BY role ORDER BY avg_salary DESC
    """)
    by_city = query("""
        SELECT city, ROUND(AVG(salary_avg)::numeric, 2) AS avg_salary
        FROM jobs WHERE salary_avg IS NOT NULL AND city != '' AND city != 'India'
        GROUP BY city ORDER BY avg_salary DESC LIMIT 10
    """)
    overall = query("SELECT ROUND(AVG(salary_avg)::numeric,2) AS avg FROM jobs WHERE salary_avg IS NOT NULL")[0]
    return {
        "by_role":     {r["role"]: float(r["avg_salary"]) for r in by_role},
        "by_city":     {r["city"]: float(r["avg_salary"]) for r in by_city},
        "overall_avg": float(overall["avg"]),
    }


@router.get("/config/roles")
def config_roles():
    rows = query("""
        SELECT DISTINCT CASE
            WHEN title ILIKE '%Data Engineer%'    THEN 'Data Engineer'
            WHEN title ILIKE '%Data Scientist%'   THEN 'Data Scientist'
            WHEN title ILIKE '%ML Engineer%'      THEN 'ML Engineer'
            WHEN title ILIKE '%Data Analyst%'     THEN 'Data Analyst'
            WHEN title ILIKE '%Business Analyst%' THEN 'Business Analyst'
            WHEN title ILIKE '%AI Engineer%'      THEN 'AI Engineer'
        END AS role FROM jobs WHERE title IS NOT NULL ORDER BY role
    """)
    roles = [r["role"] for r in rows if r["role"]]
    return roles or ["Data Analyst", "Data Scientist", "Data Engineer", "ML Engineer", "Business Analyst"]


@router.get("/config/cities")
def config_cities():
    rows = query("""
        SELECT city, COUNT(*) AS cnt FROM jobs
        WHERE city IS NOT NULL AND city != '' AND city != 'India'
        GROUP BY city HAVING COUNT(*) >= 1 ORDER BY cnt DESC LIMIT 20
    """)
    cities = [r["city"] for r in rows]
    return cities or ["Bangalore", "Hyderabad", "Mumbai", "Delhi NCR", "Chennai", "Pune"]


@router.post("/gap-analysis")
async def gap_analysis(
    current_role: str = Form(...), target_role: str = Form(...),
    city: str = Form(...), experience: int = Form(...), skills: str = Form(...)
):
    user_skills = [s.strip().lower() for s in skills.split(",") if s.strip()]
    role_salary = get_role_salary_map()
    fallback_sal = float(query("SELECT ROUND(AVG(salary_avg)::numeric,2) AS avg FROM jobs WHERE salary_avg IS NOT NULL")[0]["avg"])
    market_salary  = role_salary.get(target_role,  fallback_sal)
    current_salary = role_salary.get(current_role, fallback_sal)

    role_pattern = target_role.replace(" ", "%")
    city_jobs = query("SELECT COUNT(*) AS cnt FROM jobs WHERE title ILIKE %s AND (city = %s OR city = 'India')",
                      [f"%{role_pattern}%", city])
    jobs_available = city_jobs[0]["cnt"]

    market_skills_raw = query("""
        SELECT s.skill_name, COUNT(*) AS freq
        FROM skills s JOIN job_skills js ON s.id = js.skill_id JOIN jobs j ON j.id = js.job_id
        WHERE j.title ILIKE %s GROUP BY s.skill_name ORDER BY freq DESC LIMIT 12
    """, [f"%{role_pattern}%"])

    market_skills = [r["skill_name"].lower() for r in market_skills_raw]
    missing = [s for s in market_skills if s not in user_skills][:5]
    matched = [s for s in market_skills if s in user_skills][:5]

    exp_rows = query("SELECT experience_min, experience_max FROM jobs WHERE title ILIKE %s AND experience_max > 0",
                     [f"%{role_pattern}%"])
    avg_exp_min = round(sum(r["experience_min"] for r in exp_rows) / len(exp_rows), 1) if exp_rows else 2
    avg_exp_max = round(sum(r["experience_max"] for r in exp_rows) / len(exp_rows), 1) if exp_rows else 5
    exp_fit = "Under" if experience < avg_exp_min else "Match" if experience <= avg_exp_max else "Over"

    return {
        "current_role": current_role, "target_role": target_role,
        "market_salary": market_salary, "current_salary": current_salary,
        "salary_gap": round(market_salary - current_salary, 2),
        "jobs_available": jobs_available, "missing_skills": missing, "matched_skills": matched,
        "exp_fit": exp_fit, "avg_exp_required": f"{avg_exp_min}–{avg_exp_max} yrs",
        "skill_match_pct": round(len(matched) / max(len(market_skills), 1) * 100, 1),
    }


@router.post("/skill-roi")
async def skill_roi(current_role: str = Form(...), skills: str = Form(...)):
    user_skills   = [s.strip().lower() for s in skills.split(",") if s.strip()]
    role_salary   = get_role_salary_map()
    skill_premium = get_skill_salary_premium()
    fallback_sal  = float(query("SELECT ROUND(AVG(salary_avg)::numeric,2) AS avg FROM jobs WHERE salary_avg IS NOT NULL")[0]["avg"])
    base_salary   = role_salary.get(current_role, fallback_sal)
    results = []
    for skill, premium in skill_premium.items():
        if premium <= 0 or skill.lower() in user_skills:
            continue
        weeks = _LEARN_WEEKS.get(skill, 8)
        results.append({
            "skill": skill, "salary_premium": premium,
            "weeks_to_learn": weeks,
            "projected_salary": round(base_salary + premium, 2),
            "roi_score": round(premium / (weeks / 52) * 100, 1),
        })
    results.sort(key=lambda x: x["roi_score"], reverse=True)
    return results[:8]


@router.post("/career-paths")
async def career_paths(current_role: str = Form(...), experience: int = Form(...), city: str = Form(...)):
    next_roles  = _DEFAULT_LADDER.get(current_role, ["Data Analyst", "Data Scientist", "Data Engineer"])
    role_salary = get_role_salary_map()
    fallback_sal = float(query("SELECT ROUND(AVG(salary_avg)::numeric,2) AS avg FROM jobs WHERE salary_avg IS NOT NULL")[0]["avg"])
    current_sal  = role_salary.get(current_role, fallback_sal)
    paths = []
    for next_role in next_roles:
        base_key = next_role.replace("Senior ", "")
        sal = role_salary.get(base_key, fallback_sal)
        if "Senior" in next_role:
            sal = round(sal * 1.3, 2)
        pattern = next_role.replace("Senior ", "").replace(" ", "%")
        jcount  = query("SELECT COUNT(*) AS cnt FROM jobs WHERE title ILIKE %s AND (city = %s OR city = 'India')",
                        [f"%{pattern}%", city])
        skills_needed = query("""
            SELECT s.skill_name, COUNT(*) AS freq
            FROM skills s JOIN job_skills js ON s.id = js.skill_id JOIN jobs j ON j.id = js.job_id
            WHERE j.title ILIKE %s GROUP BY s.skill_name ORDER BY freq DESC LIMIT 5
        """, [f"%{pattern}%"])
        jump = sal - current_sal
        paths.append({
            "role": next_role, "avg_salary": sal, "salary_jump": round(jump, 2),
            "jump_pct": round(jump / current_sal * 100, 1) if current_sal else 0,
            "jobs_available": jcount[0]["cnt"],
            "skills_needed": [r["skill_name"] for r in skills_needed],
            "timeline_months": 6 if "Senior" in next_role else 12 if jump < 2 else 18,
            "difficulty": "Medium" if jump < 2 else "Hard" if jump < 4 else "Very Hard",
        })
    paths.sort(key=lambda x: x["salary_jump"], reverse=True)
    return paths


@router.post("/action-plan")
async def action_plan(
    current_role: str = Form(...), target_role: str = Form(...),
    city: str = Form(...), experience: int = Form(...), skills: str = Form(...),
    missing_skills: str = Form(default=""), salary_gap: str = Form(default="0"),
):
    user_prompt = f"""
Create a personalised 90-day career action plan:
- Current Role: {current_role}
- Target Role: {target_role}
- City: {city}
- Experience: {experience} years
- Current Skills: {skills}
- Missing Skills: {missing_skills}
- Salary Gap: ₹{salary_gap}L

Return ONLY a JSON object:
{{
  "goal": "<one sentence mission>",
  "month_1": {{"theme": "<theme>", "weeks": [{{"week":1,"focus":"<task>","resource":"<platform>","output":"<deliverable>"}},{{"week":2,"focus":"<task>","resource":"<platform>","output":"<deliverable>"}},{{"week":3,"focus":"<task>","resource":"<platform>","output":"<deliverable>"}},{{"week":4,"focus":"<task>","resource":"<platform>","output":"<deliverable>"}}]}},
  "month_2": {{"theme": "<theme>", "weeks": [{{"week":5,"focus":"<task>","resource":"<platform>","output":"<deliverable>"}},{{"week":6,"focus":"<task>","resource":"<platform>","output":"<deliverable>"}},{{"week":7,"focus":"<task>","resource":"<platform>","output":"<deliverable>"}},{{"week":8,"focus":"<task>","resource":"<platform>","output":"<deliverable>"}}]}},
  "month_3": {{"theme": "<theme>", "weeks": [{{"week":9,"focus":"<task>","resource":"<platform>","output":"<deliverable>"}},{{"week":10,"focus":"<task>","resource":"<platform>","output":"<deliverable>"}},{{"week":11,"focus":"<task>","resource":"<platform>","output":"<deliverable>"}},{{"week":12,"focus":"<task>","resource":"<platform>","output":"<deliverable>"}}]}},
  "success_metrics": ["<metric1>","<metric2>","<metric3>"],
  "quick_wins": ["<action1>","<action2>","<action3>"]
}}"""
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a senior career strategist. Return only valid JSON, no markdown."},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.4, max_tokens=2000,
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Groq returned invalid JSON: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Groq error: {str(e)}")
