"""
JobWhiz Lab — NLP Routes
Resume parsing, JD matching, ATS evaluation via Groq.
"""

import os
import io
import json
import re
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
import pdfplumber
from db import query

router = APIRouter(prefix="/api/nlp", tags=["NLP"])
import os

api_key = os.getenv("GROQ_API_KEY")

client = None

if api_key:
    try:
        from groq import Groq
        client = Groq(api_key=api_key)
    except Exception as e:
        print("Groq init failed:", e)
        client = None

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
        SELECT s1.skill_name AS skill_a, s2.skill_name AS skill_b, COUNT(*) AS co_count
        FROM job_skills js1
        JOIN job_skills js2 ON js1.job_id = js2.job_id AND js1.skill_id < js2.skill_id
        JOIN skills s1 ON s1.id = js1.skill_id
        JOIN skills s2 ON s2.id = js2.skill_id
        GROUP BY skill_a, skill_b
        ORDER BY co_count DESC
        LIMIT 20
    """)


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
            raise HTTPException(status_code=422, detail="Could not extract text. PDF may be image-based. Please paste resume text instead.")
        return {"text": full_text, "pages": len(text_parts), "char_count": len(full_text)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF extraction failed: {str(e)}")


@router.post("/match-jds")
async def match_jds(role: str = Form(...), skills: str = Form(...)):
    skill_list = [s.strip() for s in skills.split(",") if s.strip()]
    if skill_list:
        like_clauses = " OR ".join([f"description ILIKE %s" for _ in skill_list[:6]])
        params = [f"%{s}%" for s in skill_list[:6]]
    else:
        like_clauses = "1=1"
        params = []

    role_map = {
        "data analyst": "Data Analyst", "data scientist": "Data Scientist",
        "data engineer": "Data Engineer", "ml engineer": "ML Engineer",
        "business analyst": "Business Analyst",
    }
    matched_role = next((v for k, v in role_map.items() if k in role.lower()), None)
    if matched_role:
        role_clause = "AND title ILIKE %s"
        params.append(f"%{matched_role}%")
    else:
        role_clause = ""

    rows = query(f"""
        SELECT id, title, company, city, salary_avg, salary_max,
               experience_min, experience_max, description, redirect_url
        FROM jobs WHERE ({like_clauses}) {role_clause}
        ORDER BY salary_avg DESC LIMIT 5
    """, params)

    if not rows:
        rows = query("""
            SELECT id, title, company, city, salary_avg, salary_max,
                   experience_min, experience_max, description, redirect_url
            FROM jobs ORDER BY salary_avg DESC LIMIT 5
        """)
    return rows


@router.post("/analyse-resume")
async def analyse_resume(
    resume_text: str = Form(...),
    jd_text:     str = Form(...),
    tone:        str = Form(default="normal")
):
    tone_system = {
        "normal": "You are a senior HR consultant and ATS specialist. Give a professional, balanced, objective evaluation. Be factual and constructive. No fluff.",
        "roast":  "You are a savage, brutally honest career coach who ROASTS resumes like a stand-up comedian. You are FUNNY, HARSH, and SARCASTIC. Think Gordon Ramsay reviewing a resume. EVERY field must drip with sarcasm and dark humour. Still be secretly helpful — the advice must be real — but BRUTAL in delivery.",
        "hype":   "You are the world's most enthusiastic hype coach. You are LOUD, POSITIVE, and FULL OF ENERGY. Use emojis everywhere. Celebrate EVERY tiny thing like it is a Nobel Prize. EVERY field must be electric with positivity.",
        "interviewer": "You are a stone-cold senior staff engineer at Google conducting a resume review. You are DEMANDING, TECHNICAL, and SKEPTICAL. Every field must read like a tough interview question or brutal rejection reason.",
    }
    user_prompt = f"""
Analyse this resume against the job description. Write in the assigned tone for EVERY single field.

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
                {"role": "system", "content": tone_system.get(tone, tone_system["normal"])},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.85 if tone in ["roast", "hype"] else 0.4 if tone == "interviewer" else 0.3,
            max_tokens=1200,
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()
        result = json.loads(raw)
        result["tone"] = tone
        return result
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Groq returned invalid JSON: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Groq error: {str(e)}")


@router.post("/parse-resume")
async def parse_resume(resume_text: str = Form(...)):
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
                {"role": "system", "content": "You are a resume parser. Return only valid JSON, no markdown."},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.2, max_tokens=400,
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()
        return json.loads(raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Parse error: {str(e)}")
