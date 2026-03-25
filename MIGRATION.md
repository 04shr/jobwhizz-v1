# MySQL → PostgreSQL Migration Guide
## JobWhiz Lab v3 (MySQL) → v4 (PostgreSQL + Firebase)

---

## Part 1 — Set Up PostgreSQL

### Option A: Neon (Recommended — free tier, serverless, SSL built-in)
1. Go to **neon.tech** → Sign up → Create project → Name it `jobwhiz`
2. Copy the **connection string** — looks like:
   ```
   postgresql://user:password@ep-xxx.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
3. In your `.env`:
   ```
   DB_HOST=ep-xxx.us-east-2.aws.neon.tech
   DB_PORT=5432
   DB_USER=your_user
   DB_PASSWORD=your_password
   DB_NAME=neondb
   DB_SSLMODE=require
   ```

### Option B: Supabase (also free)
1. Go to **supabase.com** → New project → Note the DB password
2. Settings → Database → Connection string (use "URI" format)
3. Same `.env` format as above

### Option C: Railway / Render
- Create a PostgreSQL service, get the connection string, fill in `.env`

---

## Part 2 — Create Schema

Run `backend/schema.sql` against your new PostgreSQL database:

```bash
# Using psql CLI
psql "postgresql://user:password@host:5432/dbname?sslmode=require" -f backend/schema.sql

# Using Neon's SQL editor
# Copy-paste the contents of schema.sql into the SQL editor and run it
```

This creates: `jobs`, `skills`, `job_skills`, `experiments`, `experiment_events`

---

## Part 3 — Migrate Data from MySQL

### Step 1: Export from MySQL

```bash
# Export jobs table
mysqldump -u root -p \
  --no-create-info \
  --complete-insert \
  --skip-extended-insert \
  joblens jobs > export_jobs.sql

# Export skills table
mysqldump -u root -p \
  --no-create-info \
  --complete-insert \
  --skip-extended-insert \
  joblens skills > export_skills.sql

# Export job_skills table
mysqldump -u root -p \
  --no-create-info \
  --complete-insert \
  --skip-extended-insert \
  joblens job_skills > export_job_skills.sql
```

### Step 2: Convert MySQL SQL → PostgreSQL SQL

MySQL and PostgreSQL syntax differences to fix manually or with a script:

| MySQL                        | PostgreSQL                    |
|------------------------------|-------------------------------|
| `` `backticks` ``            | `"double quotes"` or none     |
| `AUTO_INCREMENT`             | `SERIAL` or `GENERATED ALWAYS`|
| `TINYINT(1)` (booleans)      | `BOOLEAN`                     |
| `DATETIME`                   | `TIMESTAMPTZ`                 |
| `LIKE '%x%'`                 | `ILIKE '%x%'` (case-insensitive) |
| `DATE_FORMAT(d, '%Y-%m')`    | `TO_CHAR(d, 'YYYY-MM')`       |
| `DATE_SUB(CURDATE(), INTERVAL 30 DAY)` | `CURRENT_DATE - INTERVAL '30 days'` |
| `INSERT IGNORE INTO`         | `INSERT INTO ... ON CONFLICT DO NOTHING` |
| `LIMIT n OFFSET m`           | Same (compatible)             |

**Quick Python conversion script:**
```python
import re

with open("export_jobs.sql") as f:
    sql = f.read()

# Remove backticks
sql = sql.replace("`", "")
# Fix boolean values
sql = sql.replace(" tinyint(1) ", " BOOLEAN ")
# Fix NULL default timestamps
sql = re.sub(r"DEFAULT '0000-00-00 00:00:00'", "DEFAULT NOW()", sql)

with open("export_jobs_pg.sql", "w") as f:
    f.write(sql)
```

### Step 3: Import into PostgreSQL

```bash
psql "postgresql://user:pass@host/dbname?sslmode=require" -f export_jobs_pg.sql
psql "postgresql://user:pass@host/dbname?sslmode=require" -f export_skills_pg.sql
psql "postgresql://user:pass@host/dbname?sslmode=require" -f export_job_skills_pg.sql
```

### Step 4: Reset sequences (important!)
After importing data, PostgreSQL sequences need to sync:

```sql
SELECT setval('jobs_id_seq',   (SELECT MAX(id) FROM jobs));
SELECT setval('skills_id_seq', (SELECT MAX(id) FROM skills));
SELECT setval('experiments_id_seq', (SELECT MAX(id) FROM experiments));
```

---

## Part 4 — Install Backend Dependencies

```bash
cd backend
pip install -r requirements.txt
```

Key change: `pymysql` → `psycopg2-binary`

---

## Part 5 — Run Backend Locally

```bash
cd backend
cp .env.example .env
# Fill in your PostgreSQL credentials in .env

uvicorn main:app --reload
# API running at http://127.0.0.1:8000
```

Test it:
```bash
curl http://127.0.0.1:8000/
# → {"status": "JobWhiz Lab API is running!", "version": "4.0", "db": "PostgreSQL"}

curl http://127.0.0.1:8000/api/dashboard/kpis
# → {"total_jobs": ..., "avg_salary": ..., ...}
```

---

## Part 6 — Run ETL (Populate Data)

```bash
cd backend
python etl.py
```

This will:
1. Delete jobs older than 30 days
2. Fetch salary benchmarks from Adzuna
3. Pull 5 job types × 2 pages = ~500 jobs
4. Load into PostgreSQL

If no Adzuna keys in `.env`, it falls back to 10 mock jobs so you can test the app.

---

## Part 7 — Deploy Backend to Render

1. Push `backend/` to GitHub
2. Go to **render.com** → New → Web Service
3. Connect your repo
4. Settings:
   - **Build command**: `pip install -r requirements.txt`
   - **Start command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Environment variables: copy from your `.env` file
6. Deploy → Copy the URL (e.g. `https://jobwhiz-api.onrender.com`)
7. Update `frontend/js/api.js`:
   ```js
   export const API_BASE = "https://jobwhiz-api.onrender.com";
   ```
8. Update `firebase.json` rewrite destination to match

---

## Part 8 — Deploy Frontend to Firebase

### Install Firebase CLI (once)
```bash
npm install -g firebase-tools
firebase login
```

### Deploy
```bash
# In the project root (where firebase.json lives)
firebase init hosting
# Select your project
# Public directory: frontend
# Single-page app: No
# Overwrite index.html: No

firebase deploy --only hosting
```

Your site will be live at:
```
https://your-project-id.web.app
```

### Redeploy after changes
```bash
firebase deploy --only hosting
```

---

## Part 9 — SQL Syntax Changes Summary

All queries in the Python backend have been updated. Here's what changed:

### MySQL → PostgreSQL syntax in queries

```sql
-- MySQL (old)
DATE_FORMAT(date_posted, '%Y-%m')
-- PostgreSQL (new)
TO_CHAR(date_posted, 'YYYY-MM')

-- MySQL
LIKE '%Data Analyst%'
-- PostgreSQL (case-insensitive)
ILIKE '%Data Analyst%'

-- MySQL
ROUND(AVG(salary_avg), 2)
-- PostgreSQL (explicit cast needed)
ROUND(AVG(salary_avg)::numeric, 2)

-- MySQL
DELETE js FROM job_skills js JOIN jobs j ON js.job_id = j.id WHERE ...
-- PostgreSQL
DELETE FROM job_skills WHERE job_id IN (SELECT id FROM jobs WHERE ...)

-- MySQL
INSERT IGNORE INTO skills (skill_name) VALUES (?)
-- PostgreSQL
INSERT INTO skills (skill_name) VALUES ($1) ON CONFLICT (skill_name) DO NOTHING RETURNING id

-- MySQL
PERCENT_RANK() OVER (ORDER BY salary_avg) * 100  ← works in both
VAR_SAMP()  ← MySQL uses VARIANCE(), PostgreSQL uses VAR_SAMP()
STDDEV()    ← works in both (alias)

-- MySQL
CURDATE()
-- PostgreSQL
CURRENT_DATE

-- MySQL
DATE_SUB(CURDATE(), INTERVAL 30 DAY)
-- PostgreSQL
CURRENT_DATE - INTERVAL '30 days'
```

---

## Final File Structure

```
jobwhiz/
├── firebase.json          ← Firebase hosting config
├── .firebaserc            ← Firebase project ID
├── backend/
│   ├── .env.example       ← Copy to .env, fill credentials
│   ├── requirements.txt   ← psycopg2-binary (not pymysql)
│   ├── schema.sql         ← PostgreSQL schema (run once)
│   ├── db.py              ← PostgreSQL connection helper
│   ├── etl.py             ← ETL pipeline (Adzuna → PostgreSQL)
│   ├── main.py            ← FastAPI entry point
│   ├── dashboard.py       ← Dashboard routes
│   ├── eda.py             ← EDA routes
│   ├── nlp.py             ← NLP + Groq routes
│   ├── sml.py             ← SML routes
│   └── dss.py             ← DSS + Groq routes
└── frontend/
    ├── index.html         ← Home + Dashboard
    ├── eda.html           ← EDA page
    ├── nlp.html           ← NLP page
    ├── sml.html           ← SML page
    ├── dss.html           ← DSS page
    ├── css/
    │   └── style.css      ← Single isolated stylesheet
    └── js/
        ├── api.js         ← All API fetch calls
        └── app.js         ← All page logic (linked from every HTML)
```

No inline `<style>` or `<script>` blocks anywhere.
Every HTML page imports only `css/style.css` and `js/app.js`.
