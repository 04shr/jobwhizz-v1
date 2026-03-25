"""
JobWhiz Lab — FastAPI Entry Point
Run with: uvicorn main:app --reload
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from db import query
from etl import run_etl

import dashboard
import eda
import nlp
import sml
import dss

scheduler = BackgroundScheduler()
scheduler.add_job(run_etl, trigger="interval", hours=24, id="etl_daily", replace_existing=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="JobWhiz Lab API", version="4.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router)
app.include_router(eda.router)
app.include_router(nlp.router)
app.include_router(sml.router)
app.include_router(dss.router)


@app.get("/")
def root():
    return {"status": "JobWhiz Lab API is running!", "version": "4.0", "db": "PostgreSQL"}


@app.post("/api/admin/run-etl")
def trigger_etl():
    try:
        run_etl()
        return {"status": "ETL completed successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ETL failed: {str(e)}")


@app.get("/api/admin/scheduler-status")
def scheduler_status():
    job = scheduler.get_job("etl_daily")
    if not job:
        return {"status": "not scheduled"}
    return {"status": "scheduled", "next_run": str(job.next_run_time)}


@app.get("/api/jobs")
def get_jobs(city: str = None, role: str = None, limit: int = 50):
    conditions, params = ["1=1"], []
    if city:
        conditions.append("city = %s")
        params.append(city)
    if role:
        conditions.append("title ILIKE %s")
        params.append(f"%{role}%")
    params.append(limit)
    where = " AND ".join(conditions)
    return query(f"""
        SELECT id, title, company, city, salary_avg, salary_max,
               employment_type, experience_min, experience_max, date_posted, redirect_url
        FROM jobs WHERE {where}
        ORDER BY date_posted DESC NULLS LAST
        LIMIT %s
    """, params)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int):
    rows = query("SELECT * FROM jobs WHERE id = %s", [job_id])
    if not rows:
        raise HTTPException(status_code=404, detail="Job not found")
    job = rows[0]
    job["skills"] = query("""
        SELECT s.skill_name, s.category
        FROM skills s JOIN job_skills js ON s.id = js.skill_id
        WHERE js.job_id = %s
    """, [job_id])
    return job


@app.get("/api/skills/top")
def top_skills(limit: int = 15):
    return query("""
        SELECT s.skill_name, COUNT(js.job_id) AS frequency
        FROM skills s JOIN job_skills js ON s.id = js.skill_id
        GROUP BY s.skill_name ORDER BY frequency DESC LIMIT %s
    """, [limit])


@app.get("/api/skills/by-role")
def skills_by_role():
    return query("""
        SELECT CASE
            WHEN j.title ILIKE '%Data Scientist%' THEN 'Data Scientist'
            WHEN j.title ILIKE '%Data Engineer%'  THEN 'Data Engineer'
            WHEN j.title ILIKE '%ML Engineer%'    THEN 'ML Engineer'
            WHEN j.title ILIKE '%Data Analyst%'   THEN 'Data Analyst'
            ELSE 'Other' END AS role,
            s.skill_name, COUNT(*) AS frequency
        FROM jobs j
        JOIN job_skills js ON j.id = js.job_id
        JOIN skills s ON s.id = js.skill_id
        GROUP BY role, s.skill_name
        ORDER BY role, frequency DESC
    """)
