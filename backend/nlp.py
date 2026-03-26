"""
JobWhiz Lab — NLP Routes

Changes vs previous version:
  - analyse_resume: auto-stores result in resume_job_matches after Groq returns
  - parse_resume:   auto-stores session in resume_sessions, returns session_token
  - New GET /api/nlp/match-insights   — aggregate stats across all stored analyses
  - New GET /api/nlp/trending-gaps    — most common missing skills system-wide
  - New GET /api/nlp/score-distribution — match score histogram
  - Groq unavailable: returns 503 with clear message instead of crashing
"""

import os
import io
import json
import re
import uuid
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
import pdfplumber
from db import query, execute, get_db

router = APIRouter(prefix="/api/nlp", tags=["NLP"])

# ── Groq client — graceful degradation if key absent ─────────────
_groq_client = None

def _get_groq():
    global _groq_client
    if _groq_client is not None:
        return _groq_client
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None
    try:
        from groq import Groq
        _groq_client = Groq(api_key=api_key)
        return _groq_client
    except Exception as e:
        print(f"Groq init failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# EXISTING READ ENDPOINTS (unchanged)
# ─────────────────────────────────────────────────────────────────

@router.get("/keyword-frequency")
def keyword_frequency():
    return query("""
        SELECT s.skill_name, COUNT(js.job_id) AS frequency
        FROM skills s
        JOIN job_skills js ON s.id = js.skill_id
        GROUP BY s.skill_name
        ORDER BY frequency DESC
        LIMIT 25
    """)


@router.get("/skill-cooccurrence")
def skill_cooccurrence():
    return query("""
        SELECT s1.skill_name AS skill_a, s2.skill_name AS skill_b,
               COUNT(*) AS co_count
        FROM job_skills js1
        JOIN job_skills js2
          ON js1.job_id = js2.job_id AND js1.skill_id < js2.skill_id
        JOIN skills s1 ON s1.id = js1.skill_id
        JOIN skills s2 ON s2.id = js2.skill_id
        GROUP BY skill_a, skill_b
        ORDER BY co_count DESC
        LIMIT 20
    """)


# ─────────────────────────────────────────────────────────────────
# PDF EXTRACTION (unchanged)
# ─────────────────────────────────────────────────────────────────

@router.post("/extract-pdf")
async def extract_pdf(file: UploadFile = File(...)):
    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Max 10MB.")
    try:
        text_parts = []
        with pdfplumber.open(io.BytesIO(contents)) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text_parts.append(t.strip())
        full_text = "\n\n".join(text_parts).strip()
        if not full_text or len(full_text) < 50:
            raise HTTPException(
                status_code=422,
                detail="Could not extract text. PDF may be image-based. Please paste resume text instead."
            )
        return {"text": full_text, "pages": len(text_parts), "char_count": len(full_text)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF extraction failed: {str(e)}")


# ─────────────────────────────────────────────────────────────────
# JD MATCHING (unchanged logic, uses salary_avg which may now be NULL)
# ─────────────────────────────────────────────────────────────────

@router.post("/match-jds")
async def match_jds(role: str = Form(...), skills: str = Form(...)):
    skill_list = [s.strip() for s in skills.split(",") if s.strip()]

    if skill_list:
        like_clauses = " OR ".join(["description ILIKE %s" for _ in skill_list[:6]])
        params = [f"%{s}%" for s in skill_list[:6]]
    else:
        like_clauses = "1=1"
        params = []

    role_map = {
        "data analyst":    "Data Analyst",
        "data scientist":  "Data Scientist",
        "data engineer":   "Data Engineer",
        "ml engineer":     "ML Engineer",
        "business analyst":"Business Analyst",
    }
    matched_role = next((v for k, v in role_map.items() if k in role.lower()), None)
    if matched_role:
        role_clause = "AND title ILIKE %s"
        params.append(f"%{matched_role}%")
    else:
        role_clause = ""

    rows = query(f"""
        SELECT id, title, company, city, salary_avg, salary_max,
               salary_is_predicted, experience_min, experience_max,
               description, redirect_url
        FROM jobs
        WHERE ({like_clauses}) {role_clause}
        ORDER BY salary_avg DESC NULLS LAST
        LIMIT 5
    """, params)

    if not rows:
        rows = query("""
            SELECT id, title, company, city, salary_avg, salary_max,
                   salary_is_predicted, experience_min, experience_max,
                   description, redirect_url
            FROM jobs
            ORDER BY salary_avg DESC NULLS LAST
            LIMIT 5
        """)
    return rows


# ─────────────────────────────────────────────────────────────────
# PARSE RESUME
# Now stores a session record and returns session_token.
# Frontend sends session_token back when calling analyse-resume
# so we can link the analysis to this session.
# ─────────────────────────────────────────────────────────────────

@router.post("/parse-resume")
async def parse_resume(resume_text: str = Form(...)):
    client = _get_groq()
    if not client:
        raise HTTPException(
            status_code=503,
            detail="AI analysis unavailable — GROQ_API_KEY not configured."
        )

    user_prompt = f"""
Parse this resume and return ONLY a JSON object:
{{
  "detected_role": "<most likely target job title>",
  "years_experience": <integer or 0 if fresher>,
  "top_skills": ["<skill1>", "<skill2>", "<skill3>", "<skill4>", "<skill5>"],
  "education": "<highest degree and field>",
  "summary": "<one sentence about this candidate>"
}}

RESUME:
{resume_text[:2500]}"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system",
                 "content": "You are a resume parser. Return only valid JSON, no markdown."},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=400,
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"AI returned invalid JSON: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Parse error: {str(e)}")

    # ── Store session ─────────────────────────────────────────────
    token = str(uuid.uuid4()).replace("-", "")
    try:
        session_id = execute("""
            INSERT INTO resume_sessions
                (session_token, detected_role, years_experience,
                 education, top_skills, summary)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            token,
            parsed.get("detected_role"),
            parsed.get("years_experience", 0),
            parsed.get("education"),
            parsed.get("top_skills", []),
            parsed.get("summary"),
        ))
        parsed["session_id"]    = session_id
        parsed["session_token"] = token
    except Exception as e:
        # Don't fail the parse if storage fails — just warn
        parsed["session_token"] = None
        print(f"Warning: could not store resume session: {e}")

    return parsed


# ─────────────────────────────────────────────────────────────────
# ANALYSE RESUME
# Now stores the result in resume_job_matches linked to session_id.
# ─────────────────────────────────────────────────────────────────

@router.post("/analyse-resume")
async def analyse_resume(
    resume_text:  str = Form(...),
    jd_text:      str = Form(...),
    tone:         str = Form(default="normal"),
    job_id:       str = Form(default=""),         # job.id from DB (optional)
    session_token:str = Form(default=""),         # from parse-resume response
):
    client = _get_groq()
    if not client:
        raise HTTPException(
            status_code=503,
            detail="AI analysis unavailable — GROQ_API_KEY not configured."
        )

    tone_system = {
        "normal": (
            "You are a senior HR consultant and ATS specialist. "
            "Give a professional, balanced, objective evaluation. "
            "Be factual and constructive. No fluff."
        ),
        "roast": (
            "You are a savage, brutally honest career coach who ROASTS resumes "
            "like a stand-up comedian. FUNNY, HARSH, SARCASTIC. Think Gordon Ramsay "
            "reviewing a resume. Still be secretly helpful — advice must be real — "
            "but BRUTAL in delivery."
        ),
        "hype": (
            "You are the world's most enthusiastic hype coach. LOUD, POSITIVE, "
            "FULL OF ENERGY. Use emojis everywhere. Celebrate EVERY tiny thing "
            "like it is a Nobel Prize."
        ),
        "interviewer": (
            "You are a stone-cold senior staff engineer at Google. DEMANDING, "
            "TECHNICAL, SKEPTICAL. Every field reads like a tough interview "
            "question or brutal rejection reason."
        ),
    }

    user_prompt = f"""
Analyse this resume against the job description. Write in the assigned tone for EVERY field.

--- RESUME ---
{resume_text[:3000]}

--- JOB DESCRIPTION ---
{jd_text[:2000]}

Return ONLY a valid JSON object (no markdown, no backticks):
{{
  "match_score": <integer 0-100>,
  "detected_role": "<job title>",
  "summary": "<2-3 sentence verdict in the assigned tone>",
  "pros": ["<strength 1>", "<strength 2>", "<strength 3>", "<strength 4>"],
  "cons": ["<weakness 1>", "<weakness 2>", "<weakness 3>", "<weakness 4>"],
  "missing_skills": ["<skill gap 1>", "<skill gap 2>", "<skill gap 3>"],
  "matched_skills": ["<matched 1>", "<matched 2>", "<matched 3>", "<matched 4>"],
  "ats_flags": ["<ATS issue 1>", "<ATS issue 2>"],
  "one_liner": "<single punchy sentence in the assigned tone>",
  "action_items": ["<action 1>", "<action 2>", "<action 3>"]
}}"""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system",
                 "content": tone_system.get(tone, tone_system["normal"])},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.85 if tone in ["roast", "hype"] else
                        0.40 if tone == "interviewer" else 0.30,
            max_tokens=1200,
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()
        result = json.loads(raw)
        result["tone"] = tone
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"AI returned invalid JSON: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Groq error: {str(e)}")

    # ── Store match result ────────────────────────────────────────
    try:
        # Resolve session_id from token
        session_id = None
        if session_token:
            rows = query(
                "SELECT id FROM resume_sessions WHERE session_token = %s",
                [session_token]
            )
            if rows:
                session_id = rows[0]["id"]

        db_job_id = int(job_id) if job_id and job_id.isdigit() else None

        match_id = execute("""
            INSERT INTO resume_job_matches
                (session_id, job_id, tone, match_score,
                 matched_skills, missing_skills, ats_flags,
                 pros, cons, action_items, summary, one_liner)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            session_id,
            db_job_id,
            tone,
            result.get("match_score"),
            result.get("matched_skills", []),
            result.get("missing_skills", []),
            result.get("ats_flags", []),
            result.get("pros", []),
            result.get("cons", []),
            result.get("action_items", []),
            result.get("summary"),
            result.get("one_liner"),
        ))
        result["match_id"] = match_id
    except Exception as e:
        result["match_id"] = None
        print(f"Warning: could not store match result: {e}")

    return result


# ─────────────────────────────────────────────────────────────────
# NEW: AGGREGATE ANALYTICS FROM STORED MATCHES
# These endpoints give the project actual depth — every resume
# analysis now contributes to aggregate insight.
# ─────────────────────────────────────────────────────────────────

@router.get("/match-insights")
def match_insights():
    """
    Aggregate stats across all stored resume analyses.
    Useful for dashboard: how well do candidates match the market?
    """
    summary = query("""
        SELECT
            COUNT(*)                                    AS total_analyses,
            ROUND(AVG(match_score)::numeric, 1)        AS avg_match_score,
            ROUND(MIN(match_score)::numeric, 1)        AS min_score,
            ROUND(MAX(match_score)::numeric, 1)        AS max_score,
            COUNT(DISTINCT session_id)                  AS unique_candidates,
            COUNT(DISTINCT job_id)                      AS unique_jobs_matched
        FROM resume_job_matches
        WHERE match_score IS NOT NULL
    """)

    score_dist = query("""
        SELECT
            CASE
                WHEN match_score >= 80 THEN '80–100 (Strong)'
                WHEN match_score >= 60 THEN '60–79 (Good)'
                WHEN match_score >= 40 THEN '40–59 (Average)'
                ELSE '0–39 (Weak)'
            END AS band,
            COUNT(*) AS count
        FROM resume_job_matches
        WHERE match_score IS NOT NULL
        GROUP BY band
        ORDER BY MIN(match_score) DESC
    """)

    tone_dist = query("""
        SELECT tone, COUNT(*) AS count
        FROM resume_job_matches
        GROUP BY tone
        ORDER BY count DESC
    """)

    top_matched_jobs = query("""
        SELECT j.title, j.company, j.city,
               COUNT(*) AS times_matched,
               ROUND(AVG(m.match_score)::numeric, 1) AS avg_score
        FROM resume_job_matches m
        JOIN jobs j ON j.id = m.job_id
        WHERE m.job_id IS NOT NULL
        GROUP BY j.id, j.title, j.company, j.city
        ORDER BY times_matched DESC
        LIMIT 10
    """)

    return {
        "summary":          summary[0] if summary else {},
        "score_distribution": score_dist,
        "tone_distribution":  tone_dist,
        "most_matched_jobs":  top_matched_jobs,
    }


@router.get("/trending-gaps")
def trending_gaps(limit: int = 15):
    """
    Most frequently cited missing skills across all stored analyses.
    This tells us: what skills are candidates lacking that the market wants?
    Different from job-skill frequency — this is the gap, not just demand.
    """
    rows = query("""
        SELECT
            UNNEST(missing_skills) AS skill,
            COUNT(*) AS frequency
        FROM resume_job_matches
        WHERE missing_skills IS NOT NULL
          AND array_length(missing_skills, 1) > 0
        GROUP BY skill
        ORDER BY frequency DESC
        LIMIT %s
    """, [limit])
    return rows


@router.get("/score-distribution")
def score_distribution():
    """
    Match score histogram in 10-point buckets.
    Shows how competitive the candidate pool is against current job listings.
    """
    return query("""
        SELECT
            (FLOOR(match_score / 10) * 10)::int AS bucket_start,
            COUNT(*) AS count,
            ROUND(AVG(match_score)::numeric, 1) AS avg_in_bucket
        FROM resume_job_matches
        WHERE match_score IS NOT NULL
        GROUP BY bucket_start
        ORDER BY bucket_start
    """)


@router.get("/candidate-roles")
def candidate_roles():
    """
    Distribution of detected roles from resume parse sessions.
    Tells us who is using the tool and targeting which roles.
    """
    return query("""
        SELECT
            detected_role,
            COUNT(*) AS candidate_count,
            ROUND(AVG(years_experience)::numeric, 1) AS avg_years_exp
        FROM resume_sessions
        WHERE detected_role IS NOT NULL
        GROUP BY detected_role
        ORDER BY candidate_count DESC
        LIMIT 15
    """)


@router.get("/common-ats-flags")
def common_ats_flags(limit: int = 10):
    """
    Most common ATS formatting issues found across all resume analyses.
    Systemic issues that candidates keep making.
    """
    return query("""
        SELECT
            UNNEST(ats_flags) AS flag,
            COUNT(*) AS frequency
        FROM resume_job_matches
        WHERE ats_flags IS NOT NULL
          AND array_length(ats_flags, 1) > 0
        GROUP BY flag
        ORDER BY frequency DESC
        LIMIT %s
    """, [limit])