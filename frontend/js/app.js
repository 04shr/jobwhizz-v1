// ════════════════════════════════════════════════
//  app.js — Main app script
//  Handles: routing, shared UI helpers, and all
//           page-specific logic for every HTML page.
//  Imports from api.js only. No inline scripts anywhere.
// ════════════════════════════════════════════════

import {
  API_BASE, apiFetch, apiPost,
  checkHealth, getDashKPIs, getJobsByCity, getJobsByRole,
  getSalaryDist, getTopCompanies,
  getEDASummary, getEDASchema, getDataQuality,
  getSalaryByCity, getSalaryByRole, getExpVsSalary,
  getEDASkills, getSkillsByRole,
  getKeywordFreq,
  getSMLStats, getSMLDist, getRegressionData,
  getFeatureImport, getSMLSalaryByRole, getSMLSalaryByCity,
  getOverallAvg, getModelEval, getHypothesisDE, getHypothesisBLR,
  getSalaryBenchmarks, getMarketPulse, getDSSRoles, getDSSCities,
  getJobs, getTopSkills
} from "./api.js";

// ── Shared colours ────────────────────────────────
const COLORS = ["#00e5a0","#4f8bff","#ffb340","#ff4f6b","#b57bee","#00c9d4","#6ec6ff","#ffd080"];

// ════════════════════════════════════════════════
//  SHARED UTILITIES
// ════════════════════════════════════════════════

// Bar chart renderer
export function renderBar(id, data, labelKey, valueKey, suffix = "") {
  const el = document.getElementById(id);
  if (!el) return;
  if (!data?.length) { el.innerHTML = '<p class="loading" style="color:var(--muted)">No data</p>'; return; }
  const max = Math.max(...data.map(d => +d[valueKey]));
  el.innerHTML = data.map((d, i) => `
    <div class="bar-row">
      <div class="bar-label" title="${d[labelKey]}">${d[labelKey]}</div>
      <div class="bar-track">
        <div class="bar-fill" style="width:0%;background:${COLORS[i % COLORS.length]}"
             data-w="${(+d[valueKey] / max) * 100}"></div>
      </div>
      <div class="bar-val">${typeof d[valueKey] === "number" && d[valueKey] % 1 !== 0
        ? d[valueKey].toFixed(1) : d[valueKey]}${suffix}</div>
    </div>`).join("");
  setTimeout(() => el.querySelectorAll(".bar-fill").forEach(b => b.style.width = b.dataset.w + "%"), 60);
}

// Loading state
function setLoading(id) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = '<div class="loading"><div class="spinner"></div>Loading...</div>';
}

// API status indicator
async function updateAPIStatus() {
  try {
    await checkHealth();
    document.querySelectorAll(".api-dot").forEach(d => d.classList.add("live"));
    document.querySelectorAll("#apiLabel").forEach(el => {
      el.textContent = "API Live"; el.style.color = "var(--accent)";
    });
  } catch {
    document.querySelectorAll("#apiLabel").forEach(el => {
      el.textContent = "API Offline"; el.style.color = "var(--danger)";
    });
  }
}

// Scroll animations
function initScrollAnimations() {
  const obs = new IntersectionObserver(entries =>
    entries.forEach(e => { if (e.isIntersecting) { e.target.style.opacity = "1"; e.target.style.transform = "none"; } }),
    { threshold: 0.06 }
  );
  document.querySelectorAll(".anim").forEach(el => obs.observe(el));
}

// ════════════════════════════════════════════════
//  INDEX.HTML — HOME + DASHBOARD
// ════════════════════════════════════════════════

// Page routing (index.html only — multi-page uses <a href>)
window.showPage = function(name) {
  document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".nav-links a").forEach(a => a.classList.remove("active"));
  document.getElementById("page-" + name)?.classList.add("active");
  document.getElementById("nav-" + name)?.classList.add("active");
  window.scrollTo(0, 0);
};

async function loadHomeStats() {
  try {
    const k = await getDashKPIs();
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    set("hs-jobs",      Number(k.total_jobs).toLocaleString());
    set("hs-companies", k.total_companies);
    set("hs-cities",    k.total_cities);
    set("hs-salary",    k.avg_salary ?? "—");
    set("footer-count", `${k.total_jobs} jobs · ${k.total_companies} companies · live`);
  } catch (e) { console.warn("Home stats:", e); }
}

function renderFeatureGrid() {
  const grid = document.getElementById("feature-grid");
  if (!grid) return;
  const features = [
    { tag: "DESCRIPTIVE", title: "Dashboard", desc: "KPIs, salary distribution, hiring trends and top companies from live job data.", href: "index.html#dashboard" },
    { tag: "EXPLORATORY", title: "EDA", desc: "Data quality audit, correlation analysis, skills by city and role.", href: "eda.html" },
    { tag: "DIAGNOSTIC",  title: "NLP", desc: "Resume parsing, JD matching and AI-powered ATS evaluation.", href: "nlp.html" },
    { tag: "PREDICTIVE",  title: "SML", desc: "Salary prediction, regression, hypothesis testing, model evaluation.", href: "sml.html" },
    { tag: "PRESCRIPTIVE", title: "DSS", desc: "Gap analysis, skill ROI ranking, career paths, 90-day action plan.", href: "dss.html" },
  ];
  grid.innerHTML = features.map(f => `
    <a href="${f.href}" class="feature-card">
      <div class="tag">${f.tag}</div>
      <h3>${f.title}</h3>
      <p>${f.desc}</p>
    </a>`).join("");
}

// ── Dashboard (index.html, page-dashboard) ────────────────────
let salaryChartInst = null;

window.loadDashboard = async function() {
  try {
    const k = await getDashKPIs();
    document.getElementById("dash-kpis").innerHTML = `
      <div class="kpi"><div class="kpi-val">${Number(k.total_jobs).toLocaleString()}</div><div class="kpi-label">TOTAL JOBS</div></div>
      <div class="kpi"><div class="kpi-val">${k.avg_salary ? "₹" + k.avg_salary + "L" : "—"}</div><div class="kpi-label">AVG SALARY</div></div>
      <div class="kpi"><div class="kpi-val">${k.total_companies}</div><div class="kpi-label">COMPANIES</div></div>
      <div class="kpi"><div class="kpi-val">${k.total_cities}</div><div class="kpi-label">CITIES</div></div>`;

    const [skills, cities, sal] = await Promise.all([getTopSkills(10), getJobsByCity(), getSalaryDist()]);
    renderBar("dash-skills", skills, "skill_name", "frequency");
    renderBar("dash-cities", cities, "city", "job_count");

    if (salaryChartInst) salaryChartInst.destroy();
    const ctx = document.getElementById("salaryChart");
    if (ctx) {
      salaryChartInst = new Chart(ctx, {
        type: "bar",
        data: {
          labels: sal.map(d => d.salary_range),
          datasets: [{ data: sal.map(d => d.count), backgroundColor: "rgba(0,229,160,.5)", borderColor: "#00e5a0", borderWidth: 1, borderRadius: 4 }]
        },
        options: {
          plugins: { legend: { display: false } },
          scales: {
            x: { ticks: { color: "#5a6075", font: { family: "DM Mono", size: 11 } }, grid: { color: "#1e2230" } },
            y: { ticks: { color: "#5a6075", font: { family: "DM Mono", size: 11 } }, grid: { color: "#1e2230" } }
          }
        }
      });
    }
  } catch (e) { console.warn("Dashboard:", e); }
};

// ════════════════════════════════════════════════
//  EDA.HTML
// ════════════════════════════════════════════════

async function loadEDAKPIs() {
  const s = await getEDASummary();
  const missingPct = ((s.missing_salary / s.total_jobs) * 100).toFixed(1);
  const el = document.getElementById("kpi-grid");
  if (!el) return;
  el.innerHTML = `
    <div class="kpi-cell"><div class="kpi-val">${s.total_jobs}</div><div class="kpi-label">Total Jobs</div></div>
    <div class="kpi-cell"><div class="kpi-val blue">${s.unique_companies}</div><div class="kpi-label">Companies</div></div>
    <div class="kpi-cell"><div class="kpi-val warn">${s.unique_cities}</div><div class="kpi-label">Cities</div></div>
    <div class="kpi-cell"><div class="kpi-val">₹${s.mean_salary || "—"}L</div><div class="kpi-label">Mean Salary</div></div>
    <div class="kpi-cell"><div class="kpi-val">${s.missing_salary}</div><div class="kpi-label">Null Salaries</div><div class="kpi-insight">${missingPct}% missing</div></div>
    <div class="kpi-cell"><div class="kpi-val">${s.date_range_days}</div><div class="kpi-label">Days of Data</div></div>`;
}

async function loadDataQuality() {
  const [schema, quality, summary] = await Promise.all([getEDASchema(), getDataQuality(), getEDASummary()]);
  const total = summary.total_jobs;
  const qMap  = Object.fromEntries(quality.map(q => [q.column, q.nulls]));
  const notes = {
    id: "Auto-increment primary key", title: "All listings contain titles",
    company: "Company names from Adzuna API",
    city: "Some rows contain region names instead of cities",
    salary_avg: "Adzuna role-level estimate — not individual salaries",
    experience_min: "Extracted from job description using regex",
    experience_max: "Extracted from job description using regex",
    date_posted: "Older listings default to fetch date",
    employment_type: "Adzuna does not return this for India",
    description: "Used for skill extraction via regex",
  };
  const visibleCols = ["id","title","company","city","salary_avg","experience_min","experience_max","date_posted","employment_type","description"];
  const tbody = document.getElementById("dq-tbody");
  if (!tbody) return;
  tbody.innerHTML = schema
    .filter(c => visibleCols.includes(c.column_name))
    .map(col => {
      const nulls = qMap[col.column_name] || 0;
      const coverage = ((total - nulls) / total * 100).toFixed(1);
      const status = nulls === 0 ? "ok" : coverage > 90 ? "warn" : "info";
      return `<tr>
        <td style="color:var(--accent2)">${col.column_name}</td>
        <td style="color:var(--muted)">${(col.data_type || "").toUpperCase()}</td>
        <td>${nulls}</td><td>${coverage}%</td>
        <td><span class="badge badge-${status}">${status === "ok" ? "✓ Clean" : status === "warn" ? "⚠ Caveat" : "ℹ Note"}</span></td>
        <td style="color:var(--muted);font-size:.7rem">${notes[col.column_name] || "—"}</td>
      </tr>`;
    }).join("");
}

function pearsonR(x, y) {
  const n = x.length, sx = x.reduce((a,b)=>a+b,0), sy = y.reduce((a,b)=>a+b,0);
  const sxy = x.reduce((s,v,i)=>s+v*y[i],0), sx2 = x.reduce((s,v)=>s+v*v,0), sy2 = y.reduce((s,v)=>s+v*v,0);
  return (n*sxy - sx*sy) / Math.sqrt((n*sx2 - sx*sx) * (n*sy2 - sy*sy));
}

async function loadEDA() {
  await Promise.all([loadEDAKPIs(), loadDataQuality()]);

  const cities = await getJobsByCity();
  renderBar("city-bars", cities, "city", "job_count");
  const top = cities[0], sec = cities[1];
  const cityInsight = document.getElementById("city-insight");
  if (cityInsight && top) cityInsight.innerHTML = `<strong>${top.city}</strong> dominates with <strong>${top.job_count}</strong> listings — ${sec ? (top.job_count/sec.job_count).toFixed(1) + "× more than " + sec.city : "the most of any city"}.`;

  const skills = await getEDASkills();
  renderBar("skills-grouped", skills, "skill_name", "frequency");

  const sal = await getSalaryDist();
  const histCtx = document.getElementById("salaryHistChart");
  if (histCtx) new Chart(histCtx, {
    type: "bar",
    data: { labels: sal.map(d=>d.salary_range), datasets: [{ data: sal.map(d=>d.count), backgroundColor: "#00e5a0" }] },
    options: { plugins: { legend: { display: false } }, scales: { x: { ticks: { color: "#5a6075" } }, y: { ticks: { color: "#5a6075" } } } }
  });

  const [roles, salCities] = await Promise.all([getSalaryByRole(), getSalaryByCity()]);
  renderBar("role-salary-bars",  roles,    "role",  "avg_salary", "L");
  renderBar("city-salary-bars",  salCities,"city",  "avg_salary", "L");

  const expData = await getExpVsSalary();
  const filtered = expData.filter(d => d.experience_years <= 20);
  const expCtx = document.getElementById("expSalaryChart");
  if (expCtx) new Chart(expCtx, {
    type: "line",
    data: { labels: filtered.map(d=>d.experience_years), datasets: [{ label: "Salary", data: filtered.map(d=>d.avg_salary), borderColor: "#4f8bff", tension: .4 }] },
    options: { plugins: { legend: { display: false } }, scales: { x: { title: { display: true, text: "Experience (years)", color: "#5a6075" }, ticks: { color: "#5a6075" } }, y: { title: { display: true, text: "Avg Salary (LPA)", color: "#5a6075" }, ticks: { color: "#5a6075" } } } }
  });
  const r = pearsonR(filtered.map(d=>d.experience_years), filtered.map(d=>d.avg_salary)).toFixed(2);
  const badge = document.getElementById("corr-badge");
  if (badge) badge.textContent = `📊 Correlation r = ${r}`;

  const companies = await getTopCompanies();
  renderBar("company-bars", companies, "company", "job_count");

  const jobs = await getJobs("", "", 50);
  const tbody = document.getElementById("jobs-tbody");
  if (tbody) tbody.innerHTML = jobs.map(j => `
    <tr>
      <td>${j.title}</td><td>${j.company}</td><td>${j.city}</td>
      <td>${j.salary_avg ? "₹" + j.salary_avg + "L" : "—"}</td>
      <td>${(j.experience_min === 0 && j.experience_max === 0) || !j.experience_max
        ? '<span style="color:var(--warn)">Not specified</span>'
        : j.experience_min + "–" + j.experience_max}</td>
      <td>${j.date_posted || "—"}</td>
    </tr>`).join("");
}

// ════════════════════════════════════════════════
//  NLP.HTML
// ════════════════════════════════════════════════

const KNOWN_SKILLS_CLIENT = [
  "python","r","scala","sql","mysql","postgresql","mongodb","snowflake",
  "power bi","tableau","looker","excel","matplotlib","plotly",
  "aws","azure","gcp","databricks","machine learning","deep learning",
  "nlp","tensorflow","pytorch","scikit-learn","spark","kafka",
  "airflow","dbt","pandas","numpy","hadoop","javascript",
  "docker","kubernetes","git","fastapi","flask","statistics",
];
const ROLE_MAP_CLIENT = {
  "Data Scientist":  ["machine learning","deep learning","tensorflow","pytorch","nlp"],
  "Data Analyst":    ["sql","power bi","tableau","excel","looker"],
  "Data Engineer":   ["spark","kafka","airflow","hadoop","dbt","databricks"],
  "ML Engineer":     ["tensorflow","pytorch","deep learning","kubernetes","docker"],
};

window.extractSkills = function() {
  const text = document.getElementById("jdInput")?.value.toLowerCase() || "";
  if (!text.trim()) { alert("Please paste a job description first!"); return; }
  const found = KNOWN_SKILLS_CLIENT.filter(s => new RegExp("\\b" + s.replace(/ /g, "\\s+") + "\\b").test(text));
  let detectedRole = "Data Analyst", maxHits = 0;
  for (const [role, kws] of Object.entries(ROLE_MAP_CLIENT)) {
    const hits = kws.filter(k => text.includes(k)).length;
    if (hits > maxHits) { maxHits = hits; detectedRole = role; }
  }
  const skillOut = document.getElementById("skillOutput");
  if (skillOut) skillOut.innerHTML = found.length
    ? found.map((s,i) => `<span class="skill-chip" style="animation-delay:${i*.05}s">${s.charAt(0).toUpperCase()+s.slice(1)}</span>`).join("")
    : '<p style="font-family:var(--font-mono);font-size:.72rem;color:var(--muted)">No skills found.</p>';
  const roleOut = document.getElementById("roleOutput");
  if (roleOut) roleOut.innerHTML = `<span class="skill-chip" style="background:rgba(79,139,255,.1);border-color:rgba(79,139,255,.3);color:var(--accent2)">🏷 ${detectedRole}</span>`;
};

// Resume analyser state
let resumeText = "", selectedJD = null, selectedTone = "normal", scoreRingInst = null, parsedData = null;

window.handleFileUpload = async function(input) {
  const file = input.files[0]; if (!file) return;
  document.getElementById("fileName").textContent = file.name;
  document.getElementById("fileSize").textContent = (file.size/1024).toFixed(1) + " KB · Extracting...";
  document.getElementById("fileInfo")?.classList.add("show");
  document.getElementById("uploadZone")?.classList.add("has-file");

  if (file.name.toLowerCase().endsWith(".txt")) {
    resumeText = await file.text();
    document.getElementById("fileSize").textContent = (file.size/1024).toFixed(1) + " KB · Ready";
    await parseResumeAndMatch();
    return;
  }
  if (file.name.toLowerCase().endsWith(".pdf")) {
    document.getElementById("parsedCard")?.classList.add("show");
    document.getElementById("parsedContent").innerHTML = '<div class="loading-inline"><div class="spinner-sm"></div>Extracting PDF...</div>';
    try {
      const fd = new FormData(); fd.append("file", file);
      const r = await fetch(API_BASE + "/api/nlp/extract-pdf", { method: "POST", body: fd });
      const data = await r.json();
      if (!r.ok) { document.getElementById("parsedContent").innerHTML = `<p style="color:var(--warn);font-family:var(--font-mono);font-size:.75rem">⚠️ ${data.detail}</p>`; return; }
      resumeText = data.text;
      document.getElementById("fileSize").textContent = `${(file.size/1024).toFixed(1)} KB · ${data.pages} pages · ${data.char_count} chars`;
      await parseResumeAndMatch();
    } catch(e) { document.getElementById("parsedContent").innerHTML = `<p style="color:var(--danger);font-family:var(--font-mono);font-size:.72rem">Failed: ${e.message}</p>`; }
    return;
  }
  alert("Please upload a PDF or TXT file.");
};

window.clearFile = function() {
  resumeText = ""; selectedJD = null; parsedData = null;
  const el = document.getElementById("resumeFile"); if (el) el.value = "";
  document.getElementById("fileInfo")?.classList.remove("show");
  document.getElementById("uploadZone")?.classList.remove("has-file");
  document.getElementById("parsedCard")?.classList.remove("show");
  document.getElementById("analyseBtn") && (document.getElementById("analyseBtn").disabled = true);
  document.getElementById("resultsPanel")?.classList.remove("show");
  document.getElementById("loadingState")?.classList.remove("show");
  document.getElementById("jdMatchesWrap").innerHTML = '<div class="loading-inline"><div class="spinner-sm"></div>Finding matches...</div>';
};

window.parseResumeText = async function() {
  const text = document.getElementById("resumePaste")?.value.trim();
  if (!text) { alert("Please paste resume text first."); return; }
  resumeText = text;
  await parseResumeAndMatch();
};

async function parseResumeAndMatch() {
  if (!resumeText || resumeText.length < 50) { alert("Not enough text extracted."); return; }
  document.getElementById("parsedCard")?.classList.add("show");
  document.getElementById("parsedContent").innerHTML = '<div class="loading-inline"><div class="spinner-sm"></div>Parsing with AI...</div>';
  try {
    const fd = new FormData(); fd.append("resume_text", resumeText);
    parsedData = await apiPost("/api/nlp/parse-resume", fd);
    document.getElementById("parsedContent").innerHTML = `
      <div class="parsed-row"><span class="parsed-key">Detected Role</span><span class="parsed-val" style="color:var(--purple)">${parsedData.detected_role}</span></div>
      <div class="parsed-row"><span class="parsed-key">Experience</span><span class="parsed-val">${parsedData.years_experience} yr${parsedData.years_experience !== 1?"s":""}</span></div>
      <div class="parsed-row"><span class="parsed-key">Education</span><span class="parsed-val">${parsedData.education}</span></div>
      <div class="parsed-row"><span class="parsed-key">Top Skills</span><span class="parsed-val">${parsedData.top_skills?.join(", ") || "—"}</span></div>
      <div class="parsed-row" style="border:none"><span class="parsed-key">Summary</span><span class="parsed-val" style="font-size:.7rem;color:var(--muted);max-width:260px;text-align:right">${parsedData.summary}</span></div>`;

    document.getElementById("jdMatchesWrap").innerHTML = '<div class="loading-inline"><div class="spinner-sm"></div>Querying database...</div>';
    const fd2 = new FormData();
    fd2.append("role", parsedData.detected_role || "");
    fd2.append("skills", parsedData.top_skills?.join(", ") || "");
    const jds = await apiPost("/api/nlp/match-jds", fd2);
    renderJDMatches(jds);
  } catch(e) {
    document.getElementById("parsedContent").innerHTML = `<p style="color:var(--danger);font-family:var(--font-mono);font-size:.72rem">Error: ${e.message}</p>`;
  }
}

function renderJDMatches(jds) {
  const wrap = document.getElementById("jdMatchesWrap"); if (!wrap) return;
  if (!jds?.length) { wrap.innerHTML = '<p style="color:var(--muted);font-family:var(--font-mono);font-size:.72rem">No matching jobs found.</p>'; return; }
  wrap.innerHTML = `<div class="jd-grid">${jds.map((jd,i) => `
    <div class="jd-card" onclick="window.selectJD(this,${i})" data-idx="${i}" data-jd='${JSON.stringify(jd).replace(/'/g,"&#39;")}'>
      <div class="jd-title">${jd.title}</div>
      <div class="jd-company">${jd.company} · ${jd.city || "India"}</div>
      <div class="jd-meta">
        <span class="jd-tag green">₹${jd.salary_avg || "—"}L</span>
        <span class="jd-tag">${jd.experience_min??0}–${jd.experience_max??"?"}yr</span>
      </div>
    </div>`).join("")}</div>`;
  const first = document.querySelector(".jd-card");
  if (first) { first.classList.add("selected"); selectedJD = jds[0]; }
  document.getElementById("analyseBtn") && (document.getElementById("analyseBtn").disabled = false);
}

window.selectJD = function(el, idx) {
  document.querySelectorAll(".jd-card").forEach(c => c.classList.remove("selected"));
  el.classList.add("selected");
  selectedJD = JSON.parse(el.dataset.jd);
};

window.selectTone = function(tone, btn) {
  document.querySelectorAll(".tone-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active"); selectedTone = tone;
  const analyseBtn = document.getElementById("analyseBtn");
  if (!analyseBtn) return;
  analyseBtn.className = `analyse-btn ${tone}-btn`;
  const labels = { normal:"🎯 Analyse Resume", roast:"🔥 Roast My Resume", hype:"🚀 Hype Me Up", interviewer:"😤 Interview Me" };
  analyseBtn.textContent = labels[tone];
};

window.analyseResume = async function() {
  if (!resumeText || !selectedJD) return;
  document.getElementById("resultsPanel")?.classList.remove("show");
  document.getElementById("loadingState")?.classList.add("show");
  const ringColors = { normal:"#4f8bff", roast:"#ff4f6b", hype:"#ffb340", interviewer:"#b57bee" };
  const ring = document.getElementById("loadingRing");
  if (ring) ring.style.borderTopColor = ringColors[selectedTone];
  try {
    const fd = new FormData();
    fd.append("resume_text", resumeText);
    fd.append("jd_text", selectedJD.description || JSON.stringify(selectedJD));
    fd.append("tone", selectedTone);
    const result = await apiPost("/api/nlp/analyse-resume", fd);
    renderResults(result);
  } catch(e) {
    document.getElementById("loadingState")?.classList.remove("show");
    alert("Analysis failed: " + e.message);
  }
};

function renderResults(r) {
  document.getElementById("loadingState")?.classList.remove("show");
  const panel = document.getElementById("resultsPanel");
  panel?.classList.add("show");
  const score = r.match_score ?? 0;
  const toneColors = { normal:"#4f8bff", roast:"#ff4f6b", hype:"#ffb340", interviewer:"#b57bee" };
  const col = toneColors[r.tone] || "#4f8bff";
  const setTxt = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  setTxt("scoreNum", score);
  const sn = document.getElementById("scoreNum");
  if (sn) sn.style.color = score >= 70 ? "var(--accent)" : score >= 45 ? "var(--warn)" : "var(--danger)";
  setTxt("scoreRole", r.detected_role || "—");
  setTxt("scoreOneliner", r.one_liner || "—");
  setTxt("scoreSummary", r.summary || "—");

  const canvas = document.getElementById("scoreRing");
  if (canvas) {
    if (scoreRingInst) scoreRingInst.destroy();
    scoreRingInst = new Chart(canvas, {
      type: "doughnut",
      data: { datasets: [{ data: [score, 100 - score], backgroundColor: [col, "rgba(30,34,48,1)"], borderWidth: 0, borderRadius: 4 }] },
      options: { cutout: "72%", plugins: { legend: { display: false }, tooltip: { enabled: false } }, animation: { duration: 800 } }
    });
  }
  document.getElementById("prosList").innerHTML = (r.pros||[]).map(p => `<div class="pc-item"><div class="pc-dot"></div><span>${p}</span></div>`).join("");
  document.getElementById("consList").innerHTML = (r.cons||[]).map(c => `<div class="pc-item"><div class="pc-dot"></div><span>${c}</span></div>`).join("");
  document.getElementById("matchedChips").innerHTML = (r.matched_skills||[]).map(s => `<span class="chip chip-match">✓ ${s}</span>`).join("");
  document.getElementById("missingChips").innerHTML = (r.missing_skills||[]).map(s => `<span class="chip chip-miss">+ ${s}</span>`).join("");
  document.getElementById("atsFlags").innerHTML    = (r.ats_flags||[]).length
    ? (r.ats_flags||[]).map(f => `<span class="chip chip-flag">⚑ ${f}</span>`).join("")
    : '<p style="font-family:var(--font-mono);font-size:.72rem;color:var(--accent)">No major ATS flags ✓</p>';
  document.getElementById("actionItems").innerHTML = (r.action_items||[]).map((a,i) => `<div class="action-item"><div class="action-num">${i+1}</div><span>${a}</span></div>`).join("");
  panel?.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadNLPSkills() {
  try {
    const skills = await getKeywordFreq();
    renderBar("skillFreqBars", skills.slice(0,12), "skill_name", "frequency");
  } catch(e) { console.warn("NLP skills:", e); }
}

// ════════════════════════════════════════════════
//  SML.HTML
// ════════════════════════════════════════════════

let SML_STATS = {}, SML_ROLE_MAP = {}, SML_CITY_MAP = {}, SML_OVERALL = null, SML_SLOPE = 0, SML_R2 = 0;

async function loadSML() {
  await renderStatStrip();
  await initPredictor();
  await Promise.all([renderRegression(), renderFeatureImportance(), renderSMLDistribution(), renderHypothesis(), renderModelEval()]);
  const footerNote = document.getElementById("footer-note");
  if (footerNote) {
    const s = await getEDASummary().catch(() => ({}));
    footerNote.textContent = `${s.total_jobs||"?"} jobs · ${s.unique_cities||"?"} cities · Adzuna API · PostgreSQL`;
  }
}

async function renderStatStrip() {
  const el = document.getElementById("stat-strip"); if (!el) return;
  try {
    const s = await getSMLStats(); SML_STATS = s;
    const skewLabel = s.skewness > 1 ? "Strongly right-skewed" : s.skewness > 0 ? "Slightly right-skewed" : "Left-skewed";
    const kurtLabel = s.excess_kurtosis > 0 ? "Leptokurtic — heavier tails" : "Platykurtic — lighter tails";
    el.innerHTML = [
      { cls:"teal",   val: s.mean?.toFixed(2)||"—",            name:"Mean (LPA)",   def:"Sum ÷ count. Pulled up by high earners." },
      { cls:"blue",   val: s.median?.toFixed(2)||"—",          name:"Median (LPA)", def:"Middle value. More honest for skewed data." },
      { cls:"warn",   val: s.std_dev?.toFixed(2)||"—",         name:"Std Dev",      def:`Average spread from mean across ${s.n} jobs.` },
      { cls:"danger", val: s.skewness?.toFixed(2)||"—",        name:"Skewness",     def:skewLabel },
      { cls:"purple", val: s.excess_kurtosis?.toFixed(2)||"—", name:"Kurtosis",     def:kurtLabel },
      { cls:"blue",   val: s.n,                                 name:"Sample Size",  def:`n=${s.n}. Above 30-sample threshold for CLT.` },
    ].map(c => `<div class="stat-cell ${c.cls}"><div class="stat-val">${c.val}</div><div class="stat-name">${c.name}</div><div class="stat-def">${c.def}</div></div>`).join("");
  } catch {
    el.innerHTML = '<div style="grid-column:1/-1;padding:1rem;font-family:var(--font-mono);font-size:.72rem;color:var(--danger)">Could not load stats — is the API running?</div>';
  }
}

async function initPredictor() {
  try {
    const [roles, cities, bench, skillRows, reg] = await Promise.all([
      getSMLSalaryByRole(), getSMLSalaryByCity(), getSalaryBenchmarks(), getKeywordFreq(), getRegressionData()
    ]);
    SML_OVERALL = bench.overall_avg ?? null;
    SML_ROLE_MAP = {}; roles.filter(r => r.role !== "Other").forEach(r => SML_ROLE_MAP[r.role] = r.avg_salary);
    if (SML_OVERALL === null) { const v = Object.values(SML_ROLE_MAP); SML_OVERALL = v.length ? v.reduce((a,b)=>a+b,0)/v.length : 0; }
    SML_CITY_MAP = {}; cities.forEach(c => SML_CITY_MAP[c.city] = c.avg_salary);
    SML_SLOPE = reg.slope ?? 0; SML_R2 = reg.r_squared ?? 0;

    const roleEl = document.getElementById("p-role");
    if (roleEl) roleEl.innerHTML = Object.keys(SML_ROLE_MAP).map(r => `<option value="${r}">${r}</option>`).join("");
    const cityEl = document.getElementById("p-city");
    if (cityEl) cityEl.innerHTML = Object.keys(SML_CITY_MAP).map(c => `<option value="${c}">${c}</option>`).join("");
    const skillEl = document.getElementById("p-skill");
    if (skillEl) skillEl.innerHTML = skillRows.slice(0,10).map(s => `<option value="${s.skill_name}">${s.skill_name}</option>`).join("");
    window.updatePrediction();
  } catch(e) { console.warn("Predictor:", e); }
}

window.updatePrediction = function() {
  const role = document.getElementById("p-role")?.value;
  const city = document.getElementById("p-city")?.value;
  const exp  = +(document.getElementById("p-exp")?.value ?? 2);
  if (!role || !SML_ROLE_MAP[role]) return;
  const base    = SML_ROLE_MAP[role] ?? SML_OVERALL ?? 0;
  const cityAdj = (SML_CITY_MAP[city] ?? SML_OVERALL ?? base) - (SML_OVERALL ?? base);
  const expFactor = Math.max(1 + (exp * SML_SLOPE / (base || 1)), 0.85);
  const predicted = (base + cityAdj) * expFactor;
  const halfBand  = SML_STATS.std_dev ? Math.min(SML_STATS.std_dev / (predicted || 1), 0.20) : 0.12;
  const lo = (predicted * (1 - halfBand)).toFixed(1), hi = (predicted * (1 + halfBand)).toFixed(1);
  const el = document.getElementById("pred-result"); if (!el) return;
  el.classList.add("show");
  el.innerHTML = `
    <div style="font-family:var(--font-mono);font-size:.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:.5rem">Predicted Salary</div>
    <div class="pred-val">₹${predicted.toFixed(1)} <span style="font-size:1.5rem;color:var(--muted)">LPA</span></div>
    <div style="font-family:var(--font-mono);font-size:.72rem;color:var(--muted);margin-top:.5rem">Range: ₹${lo}L – ₹${hi}L</div>
    <div style="margin-top:1rem;font-family:var(--font-mono);font-size:.7rem;line-height:1.8;">
      <div style="display:flex;justify-content:space-between"><span style="color:var(--muted)">Role baseline (${role})</span><span>₹${base.toFixed(1)}L</span></div>
      <div style="display:flex;justify-content:space-between"><span style="color:var(--muted)">City adj (${city})</span><span>${cityAdj>=0?"+":""}₹${cityAdj.toFixed(2)}L</span></div>
      <div style="display:flex;justify-content:space-between"><span style="color:var(--muted)">Exp multiplier (${exp}yr)</span><span>×${expFactor.toFixed(3)}</span></div>
      <div style="display:flex;justify-content:space-between;border-top:1px solid var(--border);padding-top:.4rem;margin-top:.25rem"><span>Final</span><span style="color:var(--teal);font-weight:700">₹${predicted.toFixed(1)}L</span></div>
    </div>`;
  const fb = document.getElementById("formula-box");
  if (fb) fb.textContent = `₹${predicted.toFixed(1)}L = (${base.toFixed(1)} ${cityAdj>=0?"+":""}${cityAdj.toFixed(2)}) × ${expFactor.toFixed(3)}`;
};

async function renderRegression() {
  try {
    const reg = await getRegressionData();
    const { slope, intercept, r_squared: r2, r, mae, points } = reg;
    const setTxt = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    setTxt("slope-display", slope.toFixed(3));
    setTxt("r2-display",    r2.toFixed(3));
    const regStats = document.getElementById("reg-stats");
    if (regStats) regStats.innerHTML = [
      `slope = ${slope.toFixed(3)}`, `intercept = ${intercept.toFixed(2)}`,
      `<span class="${r2<0.1?"warn":"ok"}">R² = ${r2.toFixed(3)}</span>`,
      `r = ${r.toFixed(3)}`, `MAE = ${mae.toFixed(2)} LPA`
    ].map(s => `<span class="reg-badge">${s}</span>`).join("");

    const rawData = await getJobs("", "", 500);
    const scatter = rawData.filter(j => j.experience_max > 0 && j.salary_avg)
      .map(j => ({ x: j.experience_max + (Math.random()-.5)*.3, y: +j.salary_avg + (Math.random()-.5)*.1 }));
    const xs = points.map(d => d.experience_years);
    const lineX = xs.length ? [Math.min(...xs), Math.max(...xs)] : [0, 15];
    const lineY = lineX.map(x => intercept + slope * x);
    const ctx = document.getElementById("regressionChart"); if (!ctx) return;
    new Chart(ctx, {
      type: "scatter",
      data: { datasets: [
        { label:"Job listings", data:scatter, backgroundColor:"rgba(79,139,255,.25)", pointRadius:3 },
        { label:"Regression line", data:lineX.map((x,i)=>({x,y:lineY[i]})), type:"line", borderColor:"#00c9d4", borderWidth:2, pointRadius:0, fill:false }
      ]},
      options: { plugins: { legend: { labels: { color:"#5a6075" } } }, scales: {
        x: { title: { display:true, text:"Experience (years)", color:"#5a6075" }, ticks: { color:"#5a6075" }, grid: { color:"#1a1f2e" } },
        y: { title: { display:true, text:"Salary Avg (LPA)", color:"#5a6075" }, ticks: { color:"#5a6075", callback: v=>"₹"+v+"L" }, grid: { color:"#1a1f2e" } }
      }}
    });
  } catch(e) { console.warn("Regression:", e); }
}

async function renderFeatureImportance() {
  try {
    const fi = await getFeatureImport();
    const fiBars = document.getElementById("fi-bars");
    if (fiBars) {
      fiBars.innerHTML = fi.map(f => `
        <div class="fi-bar-row">
          <div class="fi-label">${f.feature}</div>
          <div class="fi-track"><div class="fi-fill" style="width:0%;background:${f.color}" data-w="${f.importance_pct}"></div></div>
          <div class="fi-pct">${f.importance_pct}%</div>
        </div>`).join("");
      setTimeout(() => fiBars.querySelectorAll(".fi-fill").forEach(b => b.style.width = b.dataset.w + "%"), 100);
    }
    const roles = await getSMLSalaryByRole();
    const filtered = roles.filter(r => r.role !== "Other");
    const maxR = Math.max(...filtered.map(r => r.avg_salary));
    const roleBars = document.getElementById("role-range-bars");
    if (roleBars) roleBars.innerHTML = filtered.map((r,i) => `
      <div class="fi-bar-row">
        <div class="fi-label" style="font-size:.65rem">${r.role}</div>
        <div class="fi-track"><div class="fi-fill" style="width:${(r.avg_salary/maxR)*100}%;background:${COLORS[i%COLORS.length]}"></div></div>
        <div class="fi-pct">₹${r.avg_salary}L</div>
      </div>`).join("");
  } catch(e) { console.warn("Feature importance:", e); }
}

async function renderSMLDistribution() {
  try {
    const sal = await getSMLDist();
    const distCtx = document.getElementById("distChart");
    if (distCtx) new Chart(distCtx, {
      type: "bar",
      data: { labels: sal.map(d=>d.bucket), datasets: [{ data:sal.map(d=>d.count), backgroundColor:sal.map((_,i)=>COLORS[i%COLORS.length].replace(")", ",.4)").replace("rgb","rgba")||"rgba(79,139,255,.4)"), borderRadius:5 }] },
      options: { plugins: { legend: { display:false } }, scales: { x: { ticks:{color:"#5a6075"}, grid:{color:"#1a1f2e"} }, y: { ticks:{color:"#5a6075"}, grid:{color:"#1a1f2e"} } } }
    });

    const s = SML_STATS;
    if (!s.min) return;
    const range = (s.max - s.min) || 1, pct = v => ((v - s.min) / range * 90 + 5);
    const bp = document.getElementById("boxplot");
    if (bp) bp.innerHTML = `
      <div class="bp-line"></div>
      <div class="bp-box" style="left:${pct(s.q1)}%;width:${pct(s.q3)-pct(s.q1)}%"></div>
      <div class="bp-median" style="left:${pct(s.median)}%"></div>
      <div class="bp-whisker" style="left:${pct(s.min)}%"></div>
      <div class="bp-whisker" style="left:${pct(s.max)}%"></div>`;
    const bpl = document.getElementById("bp-labels");
    if (bpl) bpl.innerHTML = `<span>Min ${s.min}</span><span>Q1 ${s.q1}</span><span>Median ${s.median}</span><span>Q3 ${s.q3}</span><span>Max ${s.max}</span>`;
    const five = document.getElementById("five-num");
    if (five) {
      const labs = ["Min","Q1","Median","Q3","Max"], vals = [s.min, s.q1, s.median, s.q3, s.max];
      const cols = ["var(--muted)","var(--teal)","var(--warn)","var(--teal)","var(--muted)"];
      five.innerHTML = vals.map((v,i) => `<div style="text-align:center"><div style="font-family:var(--font-head);font-size:1.1rem;font-weight:700;color:${cols[i]}">₹${v}L</div><div style="font-family:var(--font-mono);font-size:.58rem;color:var(--muted);margin-top:.2rem">${labs[i]}</div></div>`).join("");
    }
  } catch(e) { console.warn("Distribution:", e); }
}

async function renderHypothesis() {
  const renderTest = (data, elId) => {
    const el = document.getElementById(elId); if (!el) return;
    el.innerHTML = `
      <div style="font-family:var(--font-mono);font-size:.72rem;color:var(--muted);margin-bottom:.75rem;line-height:1.8">
        ${data.group_a.name}: x̄ = ₹${data.group_a.mean}L, n = ${data.group_a.n}<br/>
        ${data.group_b.name}: x̄ = ₹${data.group_b.mean}L, n = ${data.group_b.n}<br/>
        Z = <strong style="color:var(--text)">${data.z_statistic}</strong> &nbsp;|&nbsp;
        p = <strong style="color:${data.reject_null?"var(--accent)":"var(--warn)"}">p ${data.p_value}</strong>
      </div>
      <div class="p-meter"><div class="p-fill" style="width:${Math.min(Math.abs(data.z_statistic)/5*100,100)}%"></div></div>
      <div class="hyp-result ${data.reject_null?"reject":"fail"}">
        <div class="hyp-icon">${data.reject_null?"✅":"⚠️"}</div>
        <div class="hyp-text"><strong>${data.reject_null?"Reject H₀":"Fail to Reject H₀"}</strong><br/>${data.conclusion}</div>
      </div>`;
  };
  try {
    const [h1, h2] = await Promise.all([getHypothesisDE(), getHypothesisBLR()]);
    renderTest(h1, "hyp1-result");
    renderTest(h2, "hyp2-result");
  } catch(e) { console.warn("Hypothesis:", e); }
}

async function renderModelEval() {
  try {
    const data = await getModelEval();
    const meanSal = SML_STATS.mean ?? 10;
    const metrics = [
      { name:"MAE",  val:`₹${data.mae}L`,     fill:Math.min(data.mae/(meanSal*.3)*100,100),  color:"var(--accent)", verdict: data.mae<meanSal*.15?"good":data.mae<meanSal*.3?"ok":"poor", def:`Off by ₹${data.mae}L on average across ${data.n} jobs.` },
      { name:"RMSE", val:`₹${data.rmse}L`,    fill:Math.min(data.rmse/(meanSal*.4)*100,100), color:"var(--warn)",   verdict: data.rmse<meanSal*.2?"good":data.rmse<meanSal*.4?"ok":"poor", def:"Penalises large errors more than MAE." },
      { name:"R²",   val:`${data.r_squared}`, fill:Math.max(data.r_squared*100,.5),          color:"var(--danger)", verdict: data.r_squared>=.7?"good":data.r_squared>=.4?"ok":"poor", def:`Explains ${(data.r_squared*100).toFixed(1)}% of variance.` },
    ];
    const evalGrid = document.getElementById("eval-grid");
    if (evalGrid) evalGrid.innerHTML = metrics.map(m => `
      <div class="eval-gauge">
        <div class="gauge-val" style="color:${m.color}">${m.val}</div>
        <div class="gauge-name">${m.name}</div>
        <div class="gauge-bar"><div class="gauge-fill" style="width:${m.fill}%;background:${m.color}"></div></div>
        <div class="gauge-scale"><span>Best</span><span>Worst</span></div>
        <div class="verdict ${m.verdict}">${m.verdict === "good" ? "Good" : m.verdict === "ok" ? "Acceptable" : "High Error"}</div>
        <div style="font-size:.72rem;color:var(--muted);margin-top:.75rem;line-height:1.5">${m.def}</div>
      </div>`).join("");
    if (data.sample?.length) {
      const actuals = data.sample.map(d => +d.actual), predicted = data.sample.map(d => +d.predicted);
      const minV = Math.min(...actuals,...predicted)-.5, maxV = Math.max(...actuals,...predicted)+.5;
      const avpCtx = document.getElementById("actualVsPred");
      if (avpCtx) new Chart(avpCtx, {
        type: "scatter",
        data: { datasets: [
          { label:"Predictions", data:actuals.map((a,i)=>({x:a,y:predicted[i]})), backgroundColor:"rgba(0,201,212,.35)", pointRadius:5 },
          { label:"Perfect fit", data:[{x:minV,y:minV},{x:maxV,y:maxV}], type:"line", borderColor:"rgba(255,179,64,.4)", borderWidth:1, pointRadius:0, fill:false }
        ]},
        options: { plugins: { legend: { labels: { color:"#5a6075" } } }, scales: {
          x: { title:{display:true,text:"Actual (LPA)",color:"#5a6075"}, ticks:{color:"#5a6075",callback:v=>"₹"+v+"L"}, grid:{color:"#1a1f2e"} },
          y: { title:{display:true,text:"Predicted (LPA)",color:"#5a6075"}, ticks:{color:"#5a6075",callback:v=>"₹"+v+"L"}, grid:{color:"#1a1f2e"} }
        }}
      });
    }
  } catch(e) { console.warn("Model eval:", e); }
}

// ════════════════════════════════════════════════
//  DSS.HTML
// ════════════════════════════════════════════════

async function loadDSS() {
  const [roles, cities, pulse] = await Promise.all([getDSSRoles(), getDSSCities(), getMarketPulse()]);
  ["currentRole","targetRole"].forEach(id => {
    const el = document.getElementById(id); if (!el) return;
    el.innerHTML = roles.map(r => `<option value="${r}">${r}</option>`).join("");
  });
  const cityEl = document.getElementById("dssCity");
  if (cityEl) cityEl.innerHTML = cities.map(c => `<option value="${c}">${c}</option>`).join("");

  const pulseEl = document.getElementById("market-pulse");
  if (pulseEl && pulse) pulseEl.innerHTML = `
    <div class="kpi-row">
      <div class="kpi"><div class="kpi-val">${Number(pulse.total_jobs).toLocaleString()}</div><div class="kpi-label">JOBS INDEXED</div></div>
      <div class="kpi"><div class="kpi-val">₹${pulse.avg_salary}L</div><div class="kpi-label">AVG SALARY</div></div>
      <div class="kpi"><div class="kpi-val">${pulse.companies}</div><div class="kpi-label">COMPANIES</div></div>
      <div class="kpi"><div class="kpi-val" style="color:var(--warn)">${pulse.hottest_role}</div><div class="kpi-label">HOTTEST ROLE</div></div>
    </div>`;
}

window.runDSSAnalysis = async function() {
  const fields = ["currentRole","targetRole","dssCity","dssExperience","dssSkills"];
  const [currentRole, targetRole, city, experience, skills] = fields.map(id => document.getElementById(id)?.value || "");
  if (!skills.trim()) { alert("Please enter your skills."); return; }

  const btn = document.getElementById("dssRunBtn"); if (btn) btn.disabled = true;
  const results = document.getElementById("dss-results");
  if (results) { results.classList.remove("show"); }

  const fd = new FormData();
  fd.append("current_role", currentRole); fd.append("target_role", targetRole);
  fd.append("city", city); fd.append("experience", experience || "2");
  fd.append("skills", skills);

  try {
    const [gap, roi, paths] = await Promise.all([
      apiPost("/api/dss/gap-analysis", (() => { const f2 = new FormData(); ["current_role","target_role","city","experience","skills"].forEach((k,i)=>f2.append(k,[currentRole,targetRole,city,experience||"2",skills][i])); return f2; })()),
      apiPost("/api/dss/skill-roi",     (() => { const f2 = new FormData(); f2.append("current_role",currentRole); f2.append("skills",skills); return f2; })()),
      apiPost("/api/dss/career-paths",  (() => { const f2 = new FormData(); f2.append("current_role",currentRole); f2.append("experience",experience||"2"); f2.append("city",city); return f2; })()),
    ]);

    // Gap analysis
    const gapEl = document.getElementById("gap-result");
    if (gapEl) gapEl.innerHTML = `
      <div class="gap-card">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem">
          <div class="kpi"><div class="kpi-val">₹${gap.market_salary}L</div><div class="kpi-label">Target Salary</div></div>
          <div class="kpi"><div class="kpi-val" style="color:${gap.salary_gap>0?"var(--accent)":"var(--danger)"}">
            ${gap.salary_gap>0?"+":""}₹${gap.salary_gap}L</div><div class="kpi-label">Salary Gap</div></div>
          <div class="kpi"><div class="kpi-val">${gap.skill_match_pct}%</div><div class="kpi-label">Skill Match</div></div>
          <div class="kpi"><div class="kpi-val" style="color:${gap.exp_fit==="Match"?"var(--accent)":gap.exp_fit==="Under"?"var(--danger)":"var(--warn)"}">
            ${gap.exp_fit}</div><div class="kpi-label">Exp Fit (${gap.avg_exp_required})</div></div>
        </div>
        <div style="font-family:var(--font-mono);font-size:.72rem;margin-bottom:.5rem;color:var(--muted)">Missing Skills</div>
        <div>${(gap.missing_skills||[]).map(s=>`<span class="chip chip-miss">+ ${s}</span>`).join("")||"None identified"}</div>
        <div style="font-family:var(--font-mono);font-size:.72rem;margin:.75rem 0 .5rem;color:var(--muted)">Matched Skills</div>
        <div>${(gap.matched_skills||[]).map(s=>`<span class="chip chip-match">✓ ${s}</span>`).join("")||"None matched"}</div>
      </div>`;

    // Skill ROI
    const roiEl = document.getElementById("roi-result");
    if (roiEl) roiEl.innerHTML = `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:.75rem">
      ${roi.map(r => `
        <div class="roi-card">
          <div class="roi-skill">${r.skill}</div>
          <div class="roi-meta">+₹${r.salary_premium}L premium · ${r.weeks_to_learn}wk to learn</div>
          <div style="margin-top:.5rem;font-family:var(--font-head);font-size:1.1rem;font-weight:700;color:var(--accent)">ROI ${r.roi_score.toFixed(0)}</div>
        </div>`).join("")}
    </div>`;

    // Career paths
    const pathsEl = document.getElementById("paths-result");
    if (pathsEl) pathsEl.innerHTML = paths.map(p => `
      <div class="path-card">
        <div class="path-role">${p.role}</div>
        <div class="path-meta">${p.difficulty} · ${p.timeline_months}mo · ${p.jobs_available} jobs in ${city}</div>
        <div class="path-jump">+₹${p.salary_jump}L <span style="font-family:var(--font-mono);font-size:.72rem;color:var(--muted)">(${p.jump_pct}% increase)</span></div>
        ${p.skills_needed.length ? `<div style="margin-top:.75rem;font-family:var(--font-mono);font-size:.68rem;color:var(--muted)">Skills needed:</div><div style="margin-top:.3rem">${p.skills_needed.map(s=>`<span class="chip chip-miss">${s}</span>`).join("")}</div>` : ""}
      </div>`).join("");

    // Action plan button
    const planBtn = document.getElementById("get-plan-btn");
    if (planBtn) { planBtn.style.display = "block"; planBtn.dataset.gap = JSON.stringify(gap); }

    if (results) results.classList.add("show");
  } catch(e) { alert("Analysis failed: " + e.message); }
  finally { if (btn) btn.disabled = false; }
};

window.getActionPlan = async function() {
  const gap = JSON.parse(document.getElementById("get-plan-btn")?.dataset.gap || "{}");
  const planEl = document.getElementById("plan-result"); if (!planEl) return;
  planEl.innerHTML = '<div class="loading"><div class="spinner"></div>Generating 90-day plan with AI...</div>';

  const fd = new FormData();
  fd.append("current_role",   document.getElementById("currentRole")?.value || "");
  fd.append("target_role",    document.getElementById("targetRole")?.value || "");
  fd.append("city",           document.getElementById("dssCity")?.value || "");
  fd.append("experience",     document.getElementById("dssExperience")?.value || "2");
  fd.append("skills",         document.getElementById("dssSkills")?.value || "");
  fd.append("missing_skills", (gap.missing_skills || []).join(", "));
  fd.append("salary_gap",     String(gap.salary_gap || 0));

  try {
    const plan = await apiPost("/api/dss/action-plan", fd);
    planEl.innerHTML = `
      <div style="font-family:var(--font-head);font-size:1rem;font-weight:700;color:var(--accent);margin-bottom:1.5rem">🎯 ${plan.goal}</div>
      ${["month_1","month_2","month_3"].map((m, mi) => {
        const month = plan[m]; if (!month) return "";
        return `<div class="plan-month">
          <div class="plan-month-header" style="color:${COLORS[mi]}">Month ${mi+1}: ${month.theme}</div>
          ${(month.weeks||[]).map(w => `
            <div class="plan-week">
              <div class="week-num">WEEK ${w.week}</div>
              <div class="week-focus">${w.focus}</div>
              <div class="week-meta">${w.resource} → ${w.output}</div>
            </div>`).join("")}
        </div>`;
      }).join("")}
      <div class="chart-card" style="margin-top:1rem">
        <h3>Quick Wins</h3>
        ${(plan.quick_wins||[]).map((w,i) => `<div class="action-item"><div class="action-num">${i+1}</div><span>${w}</span></div>`).join("")}
      </div>`;
  } catch(e) { planEl.innerHTML = `<p style="color:var(--danger);font-family:var(--font-mono)">Failed: ${e.message}</p>`; }
};

// ════════════════════════════════════════════════
//  BOOT — detect which page we're on and init
// ════════════════════════════════════════════════

document.addEventListener("DOMContentLoaded", async () => {
  updateAPIStatus();
  initScrollAnimations();

  const page = document.body.dataset.page;

  if (page === "home") {
    renderFeatureGrid();
    loadHomeStats();
    window.loadDashboard(); // pre-load dashboard panel
  }
  if (page === "eda") {
    await loadEDA();
    setInterval(() => { loadEDAKPIs(); }, 30000);
  }
  if (page === "nlp") {
    loadNLPSkills();
  }
  if (page === "sml") {
    await loadSML();
  }
  if (page === "dss") {
    await loadDSS();
  }
});
