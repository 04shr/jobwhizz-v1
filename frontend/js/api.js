// ════════════════════════════════════════════════
//  api.js — All fetch calls in one place
//  Change API_BASE to your deployed backend URL
// ════════════════════════════════════════════════

//export const API_BASE = "https://your-backend.onrender.com";
export const API_BASE = "http://127.0.0.1:8000";

export async function apiFetch(endpoint, retries = 3, delay = 1500) {
  for (let i = 0; i < retries; i++) {
    try {
      const r = await fetch(API_BASE + endpoint);
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${endpoint}`);
      return r.json();
    } catch (err) {
      if (i < retries - 1) await new Promise(res => setTimeout(res, delay * (i + 1)));
      else throw err;
    }
  }
}

export async function apiPost(endpoint, formData) {
  const r = await fetch(API_BASE + endpoint, { method: "POST", body: formData });
  if (!r.ok) { const e = await r.json(); throw new Error(e.detail || "API error"); }
  return r.json();
}

// ── Health ────────────────────────────────────────
export const checkHealth        = ()            => apiFetch("/");

// ── Dashboard ─────────────────────────────────────
export const getDashKPIs        = ()            => apiFetch("/api/dashboard/kpis");
export const getJobsByCity      = ()            => apiFetch("/api/dashboard/jobs-by-city");
export const getJobsByRole      = ()            => apiFetch("/api/dashboard/jobs-by-role");
export const getSalaryDist      = ()            => apiFetch("/api/dashboard/salary-distribution");
export const getHiringTrend     = ()            => apiFetch("/api/dashboard/hiring-trend");
export const getTopCompanies    = ()            => apiFetch("/api/dashboard/top-companies");

// ── EDA ───────────────────────────────────────────
export const getEDASummary      = ()            => apiFetch("/api/eda/summary");
export const getEDASchema       = ()            => apiFetch("/api/eda/schema");
export const getDataQuality     = ()            => apiFetch("/api/eda/data-quality");
export const getSalaryByCity    = ()            => apiFetch("/api/eda/salary-by-city");
export const getSalaryByRole    = ()            => apiFetch("/api/eda/salary-by-role");
export const getExpVsSalary     = ()            => apiFetch("/api/eda/experience-vs-salary");
export const getJobsOverTime    = ()            => apiFetch("/api/eda/jobs-over-time");
export const getEDASkills       = (limit = 15) => apiFetch(`/api/eda/skills?limit=${limit}`);
export const getSkillsByRole    = ()            => apiFetch("/api/eda/skills-by-role");

// ── NLP ───────────────────────────────────────────
export const getKeywordFreq     = ()            => apiFetch("/api/nlp/keyword-frequency");
export const getSkillCooccur    = ()            => apiFetch("/api/nlp/skill-cooccurrence");

// ── SML ───────────────────────────────────────────
export const getSMLStats        = ()            => apiFetch("/api/sml/stats/summary");
export const getSMLDist         = ()            => apiFetch("/api/sml/stats/distribution");
export const getRegressionData  = ()            => apiFetch("/api/sml/regression/exp-vs-salary");
export const getFeatureImport   = ()            => apiFetch("/api/sml/feature-importance");
export const getSMLSalaryByRole = ()            => apiFetch("/api/sml/salary-by-role");
export const getSMLSalaryByCity = (n = 10)     => apiFetch(`/api/sml/salary-by-city?limit=${n}`);
export const getOverallAvg      = ()            => apiFetch("/api/sml/overall-avg");
export const getModelEval       = ()            => apiFetch("/api/sml/model/evaluation");
export const getHypothesisDE    = ()            => apiFetch("/api/sml/hypothesis/data-engineers-vs-rest");
export const getHypothesisBLR   = ()            => apiFetch("/api/sml/hypothesis/bangalore-vs-rest");

// ── DSS ───────────────────────────────────────────
export const getSalaryBenchmarks = ()           => apiFetch("/api/dss/salary-benchmarks");
export const getMarketPulse      = ()           => apiFetch("/api/dss/market-pulse");
export const getDSSRoles         = ()           => apiFetch("/api/dss/config/roles");
export const getDSSCities        = ()           => apiFetch("/api/dss/config/cities");

// ── Jobs ──────────────────────────────────────────
export const getJobs = (city = "", role = "", limit = 50) =>
  apiFetch(`/api/jobs?${new URLSearchParams({ ...(city && {city}), ...(role && {role}), limit })}`);

// ── Skills ────────────────────────────────────────
export const getTopSkills = (limit = 15) => apiFetch(`/api/skills/top?limit=${limit}`);
