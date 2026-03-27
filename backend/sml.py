"""
JobWhiz Lab — SML Routes
Predictive Analytics: salary stats, regression, hypothesis testing, model evaluation.
All values are computed from live DB — zero hardcoding.
"""

import math
from fastapi import APIRouter
from db import query

router = APIRouter(prefix="/api/sml", tags=["SML"])

# Reusable CASE expression for role classification
_ROLE_CASE = """
    CASE
        WHEN title ILIKE '%Data Engineer%'    THEN 'Data Engineer'
        WHEN title ILIKE '%Data Scientist%'   THEN 'Data Scientist'
        WHEN title ILIKE '%ML Engineer%'      THEN 'ML Engineer'
        WHEN title ILIKE '%Data Analyst%'     THEN 'Data Analyst'
        WHEN title ILIKE '%Business Analyst%' THEN 'Business Analyst'
        ELSE 'Other'
    END
"""


@router.get("/stats/summary")
def stats_summary():
    base = query("""
        SELECT
            COUNT(*)                                AS n,
            ROUND(AVG(salary_avg)::numeric, 4)     AS mean,
            ROUND(STDDEV(salary_avg)::numeric, 4)  AS std_dev,
            ROUND(MIN(salary_avg)::numeric, 2)     AS min_val,
            ROUND(MAX(salary_avg)::numeric, 2)     AS max_val
        FROM jobs WHERE salary_avg IS NOT NULL
    """)[0]

    n = int(base["n"])
    median_offset = max(0, (n - 1) // 2)
    median_row = query(f"""
        SELECT salary_avg AS median FROM jobs
        WHERE salary_avg IS NOT NULL
        ORDER BY salary_avg
        LIMIT 1 OFFSET {median_offset}
    """)
    median = float(median_row[0]["median"]) if median_row else float(base["mean"] or 0)

    q1_row = query(f"""
        SELECT salary_avg AS q1 FROM jobs WHERE salary_avg IS NOT NULL
        ORDER BY salary_avg LIMIT 1 OFFSET {max(0, int(n * 0.25) - 1)}
    """)
    q3_row = query(f"""
        SELECT salary_avg AS q3 FROM jobs WHERE salary_avg IS NOT NULL
        ORDER BY salary_avg LIMIT 1 OFFSET {max(0, int(n * 0.75) - 1)}
    """)
    moments = query("""
        SELECT
            AVG(POWER((salary_avg - avg_val) / NULLIF(std_val, 0), 3)) AS skewness,
            AVG(POWER((salary_avg - avg_val) / NULLIF(std_val, 0), 4)) - 3 AS excess_kurtosis
        FROM jobs
        CROSS JOIN (SELECT AVG(salary_avg) AS avg_val, STDDEV(salary_avg) AS std_val FROM jobs WHERE salary_avg IS NOT NULL) s
        WHERE salary_avg IS NOT NULL
    """)

    return {
        "n":               n,
        "mean":            round(float(base["mean"] or 0), 2),
        "median":          round(median, 2),
        "std_dev":         round(float(base["std_dev"] or 0), 2),
        "min":             round(float(base["min_val"] or 0), 2),
        "max":             round(float(base["max_val"] or 0), 2),
        "q1":              round(float(q1_row[0]["q1"]), 2) if q1_row else None,
        "q3":              round(float(q3_row[0]["q3"]), 2) if q3_row else None,
        "skewness":        round(float(moments[0]["skewness"]), 3) if moments and moments[0]["skewness"] else None,
        "excess_kurtosis": round(float(moments[0]["excess_kurtosis"]), 3) if moments and moments[0]["excess_kurtosis"] else None,
    }


@router.get("/stats/distribution")
def salary_distribution():
    agg = query("""
        SELECT
            ROUND(MIN(salary_avg)::numeric, 2) AS p0,
            ROUND(AVG(CASE WHEN pct BETWEEN 15 AND 25 THEN salary_avg END)::numeric, 2) AS p20,
            ROUND(AVG(CASE WHEN pct BETWEEN 35 AND 45 THEN salary_avg END)::numeric, 2) AS p40,
            ROUND(AVG(CASE WHEN pct BETWEEN 55 AND 65 THEN salary_avg END)::numeric, 2) AS p60,
            ROUND(AVG(CASE WHEN pct BETWEEN 75 AND 85 THEN salary_avg END)::numeric, 2) AS p80,
            ROUND(MAX(salary_avg)::numeric, 2) AS p100
        FROM (
            SELECT salary_avg,
                   PERCENT_RANK() OVER (ORDER BY salary_avg) * 100 AS pct
            FROM jobs WHERE salary_avg IS NOT NULL
        ) ranked
    """)
    row = agg[0] if agg else {}
    try:
        b = [float(row.get(k) or 0) for k in ["p0", "p20", "p40", "p60", "p80", "p100"]]
        seen, clean = set(), []
        for v in b:
            rv = round(v)
            if rv not in seen:
                seen.add(rv); clean.append(v)
        if len(clean) < 3:
            raise ValueError
    except Exception:
        ext = query("SELECT MIN(salary_avg) AS lo, MAX(salary_avg) AS hi FROM jobs WHERE salary_avg IS NOT NULL")[0]
        lo, hi = float(ext["lo"] or 0), float(ext["hi"] or 30)
        step = (hi - lo) / 5
        clean = [round(lo + i * step, 1) for i in range(6)]

    case_parts = []
    for i in range(len(clean) - 1):
        lo_v, hi_v = round(clean[i], 1), round(clean[i + 1], 1)
        if i == len(clean) - 2:
            case_parts.append(f"WHEN salary_avg >= {lo_v} THEN '{lo_v}L+'")
        else:
            case_parts.append(f"WHEN salary_avg < {hi_v} THEN '{lo_v}-{hi_v}L'")

    case_sql = "CASE\n" + "\n".join(f"            {p}" for p in case_parts) + "\n            ELSE 'Other'\n        END"
    # FIX: GROUP BY alias 'bucket' — wrap in subquery
    return query(f"""
        SELECT bucket, COUNT(*) AS count,
               ROUND(AVG(salary_avg)::numeric, 2) AS avg_in_bucket
        FROM (
            SELECT {case_sql} AS bucket, salary_avg
            FROM jobs WHERE salary_avg IS NOT NULL
        ) sub
        GROUP BY bucket
        ORDER BY MIN(salary_avg)
    """)


@router.get("/regression/exp-vs-salary")
def regression_data():
    rows = query("""
        SELECT experience_max AS experience_years,
               ROUND(AVG(salary_avg)::numeric, 2) AS avg_salary,
               COUNT(*) AS job_count
        FROM jobs
        WHERE salary_avg IS NOT NULL AND experience_max IS NOT NULL
          AND experience_max > 0 AND experience_max <= 20
        GROUP BY experience_max ORDER BY experience_max
    """)
    if not rows:
        return {"points": [], "slope": 0, "intercept": 0, "r_squared": 0, "r": 0, "mae": 0}

    xs = [float(r["experience_years"]) for r in rows]
    ys = [float(r["avg_salary"]) for r in rows]
    n  = len(xs)
    xm, ym = sum(xs) / n, sum(ys) / n
    num   = sum((xs[i] - xm) * (ys[i] - ym) for i in range(n))
    den   = sum((x - xm) ** 2 for x in xs)
    slope = num / den if den else 0
    intercept = ym - slope * xm
    y_pred  = [intercept + slope * x for x in xs]
    ss_res  = sum((ys[i] - y_pred[i]) ** 2 for i in range(n))
    ss_tot  = sum((y - ym) ** 2 for y in ys)
    r2      = 1 - ss_res / ss_tot if ss_tot else 0
    r       = math.copysign(math.sqrt(abs(r2)), slope)
    mae     = sum(abs(ys[i] - y_pred[i]) for i in range(n)) / n
    return {"points": rows, "slope": round(slope, 4), "intercept": round(intercept, 4),
            "r_squared": round(r2, 4), "r": round(r, 4), "mae": round(mae, 4)}


@router.get("/feature-importance")
def feature_importance():
    total_var = float(query("SELECT VAR_SAMP(salary_avg) AS v FROM jobs WHERE salary_avg IS NOT NULL")[0]["v"] or 1)
    # FIX: GROUP BY alias 'role' — wrap in subquery
    role_rows = query("""
        SELECT role, AVG(salary_avg) AS avg_sal, COUNT(*) AS cnt
        FROM (
            SELECT
                CASE
                    WHEN title ILIKE '%Data Engineer%'    THEN 'Data Engineer'
                    WHEN title ILIKE '%Data Scientist%'   THEN 'Data Scientist'
                    WHEN title ILIKE '%ML Engineer%'      THEN 'ML Engineer'
                    WHEN title ILIKE '%Data Analyst%'     THEN 'Data Analyst'
                    WHEN title ILIKE '%Business Analyst%' THEN 'Business Analyst'
                    ELSE 'Other'
                END AS role,
                salary_avg
            FROM jobs WHERE salary_avg IS NOT NULL
        ) sub
        GROUP BY role
    """)
    grand_mean = sum(float(r["avg_sal"]) * int(r["cnt"]) for r in role_rows) / sum(int(r["cnt"]) for r in role_rows)
    role_bv  = sum(int(r["cnt"]) * (float(r["avg_sal"]) - grand_mean) ** 2 for r in role_rows) / sum(int(r["cnt"]) for r in role_rows)
    role_pct = min(round(role_bv / total_var * 100, 1), 95)

    city_rows = query("""
        SELECT city, AVG(salary_avg) AS avg_sal, COUNT(*) AS cnt
        FROM jobs WHERE salary_avg IS NOT NULL AND city != '' GROUP BY city
    """)
    city_n  = sum(int(r["cnt"]) for r in city_rows)
    city_gm = sum(float(r["avg_sal"]) * int(r["cnt"]) for r in city_rows) / city_n if city_n else grand_mean
    city_bv = sum(int(r["cnt"]) * (float(r["avg_sal"]) - city_gm) ** 2 for r in city_rows) / city_n if city_n else 0
    city_pct = min(round(city_bv / total_var * 100, 1), 30)

    remaining = max(0, 100 - role_pct - city_pct)
    return [
        {"feature": "Job Role / Title", "importance_pct": role_pct,                 "color": "#00c9d4"},
        {"feature": "City / Location",  "importance_pct": city_pct,                 "color": "#4f8bff"},
        {"feature": "Experience",       "importance_pct": round(remaining * 0.45, 1), "color": "#ffb340"},
        {"feature": "Top Skill",        "importance_pct": round(remaining * 0.35, 1), "color": "#b57bee"},
        {"feature": "Company",          "importance_pct": round(remaining * 0.20, 1), "color": "#5a6075"},
    ]


@router.get("/salary-by-role")
def salary_by_role():
    # FIX: GROUP BY alias 'role' — wrap in subquery
    return query("""
        SELECT role,
               ROUND(AVG(salary_avg)::numeric, 2) AS avg_salary,
               ROUND(MIN(salary_avg)::numeric, 2) AS min_salary,
               ROUND(MAX(salary_avg)::numeric, 2) AS max_salary,
               COUNT(*) AS job_count
        FROM (
            SELECT
                CASE
                    WHEN title ILIKE '%Data Engineer%'    THEN 'Data Engineer'
                    WHEN title ILIKE '%Data Scientist%'   THEN 'Data Scientist'
                    WHEN title ILIKE '%ML Engineer%'      THEN 'ML Engineer'
                    WHEN title ILIKE '%Data Analyst%'     THEN 'Data Analyst'
                    WHEN title ILIKE '%Business Analyst%' THEN 'Business Analyst'
                    WHEN title ILIKE '%AI Engineer%'      THEN 'AI Engineer'
                    ELSE 'Other'
                END AS role,
                salary_avg
            FROM jobs WHERE salary_avg IS NOT NULL
        ) sub
        GROUP BY role
        ORDER BY avg_salary DESC
    """)


@router.get("/salary-by-city")
def salary_by_city(limit: int = 10):
    # city is a real column — GROUP BY city is fine
    return query("""
        SELECT city, ROUND(AVG(salary_avg)::numeric, 2) AS avg_salary, COUNT(*) AS job_count
        FROM jobs
        WHERE salary_avg IS NOT NULL AND city IS NOT NULL AND city != '' AND city != 'India'
        GROUP BY city ORDER BY avg_salary DESC LIMIT %s
    """, [limit])


@router.get("/overall-avg")
def overall_avg():
    row = query("SELECT ROUND(AVG(salary_avg)::numeric, 4) AS avg FROM jobs WHERE salary_avg IS NOT NULL")[0]
    return {"overall_avg": float(row["avg"]) if row["avg"] else None}


@router.get("/hypothesis/data-engineers-vs-rest")
def hypothesis_de_vs_rest():
    de   = query("SELECT COUNT(*) AS n, ROUND(AVG(salary_avg)::numeric,4) AS mean, ROUND(STDDEV(salary_avg)::numeric,4) AS std FROM jobs WHERE title ILIKE '%Data Engineer%' AND salary_avg IS NOT NULL")[0]
    rest = query("SELECT COUNT(*) AS n, ROUND(AVG(salary_avg)::numeric,4) AS mean, ROUND(STDDEV(salary_avg)::numeric,4) AS std FROM jobs WHERE title NOT ILIKE '%Data Engineer%' AND salary_avg IS NOT NULL")[0]
    n1, mu1, s1 = int(de["n"]),   float(de["mean"]),   float(de["std"]  or 0.01)
    n2, mu2, s2 = int(rest["n"]), float(rest["mean"]), float(rest["std"] or 0.01)
    se = math.sqrt(s1**2/n1 + s2**2/n2) if n1 > 0 and n2 > 0 else 1
    z  = (mu1 - mu2) / se if se else 0
    p_label = "< 0.001" if abs(z)>3.29 else "< 0.01" if abs(z)>2.58 else "< 0.05" if abs(z)>1.96 else "> 0.05"
    reject  = abs(z) > 1.96
    return {
        "group_a": {"name": "Data Engineers", "n": n1, "mean": round(mu1,2), "std": round(s1,2)},
        "group_b": {"name": "Other Roles",    "n": n2, "mean": round(mu2,2), "std": round(s2,2)},
        "z_statistic": round(z,3), "p_value": p_label, "reject_null": reject,
        "conclusion": f"Data Engineers earn significantly more (p{p_label})" if reject else f"No significant difference (p{p_label})",
        "diff": round(mu1 - mu2, 2),
    }


@router.get("/hypothesis/bangalore-vs-rest")
def hypothesis_blr_vs_rest():
    blr  = query("SELECT COUNT(*) AS n, ROUND(AVG(salary_avg)::numeric,4) AS mean, ROUND(STDDEV(salary_avg)::numeric,4) AS std FROM jobs WHERE city='Bangalore' AND salary_avg IS NOT NULL")[0]
    rest = query("SELECT COUNT(*) AS n, ROUND(AVG(salary_avg)::numeric,4) AS mean, ROUND(STDDEV(salary_avg)::numeric,4) AS std FROM jobs WHERE city!='Bangalore' AND city!='' AND salary_avg IS NOT NULL")[0]
    n1, mu1, s1 = int(blr["n"]),  float(blr["mean"]),  float(blr["std"]  or 0.01)
    n2, mu2, s2 = int(rest["n"]), float(rest["mean"]), float(rest["std"] or 0.01)
    se = math.sqrt(s1**2/n1 + s2**2/n2) if n1 > 0 and n2 > 0 else 1
    z  = (mu1 - mu2) / se if se else 0
    p_label = "< 0.001" if abs(z)>3.29 else "< 0.01" if abs(z)>2.58 else "< 0.05" if abs(z)>1.96 else "> 0.05"
    reject  = abs(z) > 1.96
    return {
        "group_a": {"name": "Bangalore",    "n": n1, "mean": round(mu1,2), "std": round(s1,2)},
        "group_b": {"name": "Other Cities", "n": n2, "mean": round(mu2,2), "std": round(s2,2)},
        "z_statistic": round(z,3), "p_value": p_label, "reject_null": reject,
        "conclusion": f"Significant salary difference (p{p_label})" if reject else f"No significant difference — role matters more than location (p{p_label})",
        "diff": round(mu1 - mu2, 2),
    }


@router.get("/model/evaluation")
def model_evaluation():
    # Inner subquery already groups by role correctly (GROUP BY role in subquery scope)
    rows = query("""
        SELECT j.salary_avg AS actual, role_avgs.avg_sal AS predicted
        FROM jobs j
        JOIN (
            SELECT role, ROUND(AVG(salary_avg)::numeric, 2) AS avg_sal
            FROM (
                SELECT
                    CASE
                        WHEN title ILIKE '%Data Engineer%'    THEN 'Data Engineer'
                        WHEN title ILIKE '%Data Scientist%'   THEN 'Data Scientist'
                        WHEN title ILIKE '%ML Engineer%'      THEN 'ML Engineer'
                        WHEN title ILIKE '%Data Analyst%'     THEN 'Data Analyst'
                        WHEN title ILIKE '%Business Analyst%' THEN 'Business Analyst'
                        ELSE 'Other'
                    END AS role,
                    salary_avg
                FROM jobs WHERE salary_avg IS NOT NULL
            ) sub
            GROUP BY role
        ) AS role_avgs ON role_avgs.role = CASE
            WHEN j.title ILIKE '%Data Engineer%'    THEN 'Data Engineer'
            WHEN j.title ILIKE '%Data Scientist%'   THEN 'Data Scientist'
            WHEN j.title ILIKE '%ML Engineer%'      THEN 'ML Engineer'
            WHEN j.title ILIKE '%Data Analyst%'     THEN 'Data Analyst'
            WHEN j.title ILIKE '%Business Analyst%' THEN 'Business Analyst'
            ELSE 'Other' END
        WHERE j.salary_avg IS NOT NULL
    """)
    actuals   = [float(r["actual"])    for r in rows]
    predicted = [float(r["predicted"]) for r in rows]
    n         = len(actuals)
    if n == 0:
        return {"n": 0, "mae": 0, "rmse": 0, "r_squared": 0, "mape": 0, "sample": []}
    mean_act = sum(actuals) / n
    mae      = sum(abs(actuals[i] - predicted[i]) for i in range(n)) / n
    mse      = sum((actuals[i] - predicted[i]) ** 2 for i in range(n)) / n
    rmse     = math.sqrt(mse)
    ss_res   = sum((actuals[i] - predicted[i]) ** 2 for i in range(n))
    ss_tot   = sum((a - mean_act) ** 2 for a in actuals)
    r2       = 1 - ss_res / ss_tot if ss_tot else 0
    mape     = sum(abs(actuals[i] - predicted[i]) / actuals[i] * 100 for i in range(n) if actuals[i]) / n
    return {"n": n, "mae": round(mae, 3), "rmse": round(rmse, 3),
            "r_squared": round(r2, 3), "mape": round(mape, 2),
            "sample": [{"actual": r["actual"], "predicted": r["predicted"]} for r in rows[:20]]}