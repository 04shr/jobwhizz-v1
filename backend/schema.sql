-- JobWhiz Lab — PostgreSQL Schema
-- Run once to set up the database

CREATE TABLE IF NOT EXISTS jobs (
    id            SERIAL PRIMARY KEY,
    external_id   VARCHAR(255) UNIQUE,
    title         VARCHAR(255) NOT NULL,
    company       VARCHAR(255) NOT NULL,
    location      VARCHAR(255),
    city          VARCHAR(100),
    country       VARCHAR(100) DEFAULT 'India',
    salary_max    NUMERIC(10,2),
    salary_avg    NUMERIC(10,2),
    employment_type VARCHAR(50),
    experience_min  INT,
    experience_max  INT,
    description   TEXT,
    source        VARCHAR(100) DEFAULT 'adzuna',
    redirect_url  VARCHAR(1000),
    date_posted   DATE,
    date_fetched  TIMESTAMPTZ DEFAULT NOW(),
    is_active     BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS skills (
    id          SERIAL PRIMARY KEY,
    skill_name  VARCHAR(100) UNIQUE NOT NULL,
    category    VARCHAR(50) DEFAULT 'other',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS job_skills (
    job_id   INT REFERENCES jobs(id) ON DELETE CASCADE,
    skill_id INT REFERENCES skills(id) ON DELETE CASCADE,
    PRIMARY KEY (job_id, skill_id)
);

CREATE TABLE IF NOT EXISTS experiments (
    id             SERIAL PRIMARY KEY,
    name           VARCHAR(255) NOT NULL,
    description    TEXT,
    variant_a_name VARCHAR(100),
    variant_b_name VARCHAR(100),
    metric         VARCHAR(100),
    start_date     DATE,
    end_date       DATE,
    status         VARCHAR(20) DEFAULT 'draft',
    winner         VARCHAR(20),
    p_value        NUMERIC(6,4),
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS experiment_events (
    id            SERIAL PRIMARY KEY,
    experiment_id INT REFERENCES experiments(id) ON DELETE CASCADE,
    variant       CHAR(1) CHECK (variant IN ('A','B')),
    event_type    VARCHAR(100),
    user_session  VARCHAR(255),
    occurred_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_jobs_city    ON jobs(city);
CREATE INDEX IF NOT EXISTS idx_jobs_salary  ON jobs(salary_avg);
CREATE INDEX IF NOT EXISTS idx_js_skill     ON job_skills(skill_id);


SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public';

SELECT table_schema, table_name 
FROM information_schema.tables 
WHERE table_name = 'job_skills';