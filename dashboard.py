#!/usr/bin/env python3
"""
Build a self-contained dashboard.html from the data.json that scanner.py writes.

    python dashboard.py            # uses ./data.json
    python dashboard.py --demo     # sample data, no network needed
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEMO = {
    "generated": "sample data",
    "filters": {"min_cap": 100e6, "max_cap": 20e9, "cap_filter": True},
    "companies": [
        {"ticker": "EXMP", "name": "Example Therapeutics Inc.", "market_cap": 420_000_000,
         "cap_bucket": "Small", "price": 6.12, "currency": "USD", "sector": "Biotechnology",
         "rating": "buy", "rating_mean": 1.8, "analyst_count": 7,
         "target_price": 14.50, "upside_pct": 136.9, "rating_spread": [4, 2, 1, 0, 0],
         "areas": ["Melanoma", "Oncology"], "trial_count": 2, "sponsor_names": ["Example Therapeutics"],
         "trials": [
             {"nct_id": "NCT00000001", "title": "Study of EXA-101 in advanced melanoma",
              "area": "Melanoma", "status": "RECRUITING", "start_date": "2025-03",
              "primary_completion": "2026-10", "pc_type": "ESTIMATED", "has_results": False, "enrollment": 340,
              "conditions": ["Metastatic Melanoma"], "interventions": ["EXA-101", "Pembrolizumab"],
              "role": "partner",
              "url": "https://clinicaltrials.gov/study/NCT00000001"},
             {"nct_id": "NCT00000002", "title": "EXA-101 plus chemotherapy in solid tumors",
              "area": "Oncology", "status": "ACTIVE_NOT_RECRUITING", "start_date": "2024-01",
              "primary_completion": "2026-07", "pc_type": "ESTIMATED", "has_results": False, "enrollment": 512,
              "conditions": ["Solid Tumor"], "interventions": ["EXA-101"],
              "url": "https://clinicaltrials.gov/study/NCT00000002"}]},
        {"ticker": "SMPL", "name": "Sample Biosciences Ltd.", "market_cap": 3_100_000_000,
         "cap_bucket": "Mid", "price": 41.80, "currency": "USD", "sector": "Biotechnology",
         "rating": "hold", "rating_mean": 2.9, "analyst_count": 12,
         "target_price": 38.00, "upside_pct": -9.1, "rating_spread": [1, 2, 7, 2, 0],
         "areas": ["Allergy"], "trial_count": 1, "sponsor_names": ["Sample Biosciences"],
         "trials": [
             {"nct_id": "NCT00000003", "title": "Oral immunotherapy for peanut allergy in children",
              "area": "Allergy", "status": "RECRUITING", "start_date": "2025-06",
              "primary_completion": "2027-01", "pc_type": "ACTUAL", "has_results": False, "enrollment": 220,
              "conditions": ["Peanut Allergy"], "interventions": ["SMP-2"],
              "url": "https://clinicaltrials.gov/study/NCT00000003"}]},
    ],
    "unmatched_sponsors": ["Some Private Biotech GmbH"],
}

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TrialScan — Phase 3 screen</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@500;600&display=swap" rel="stylesheet">
<style>
  :root{
    --paper:#E9EDF0; --card:#FFFFFF; --ink:#0D1218; --muted:#5E6B78;
    --rule:#D2D9E0; --accent:#135A63; --accent-soft:#DCEAEB;
    --oncology:#6B4BC4; --melanoma:#1E4470; --allergy:#B8801C;
    --r-sb:#1B7A5A; --r-b:#5AA184; --r-h:#9A8B4F; --r-s:#C4703A; --r-ss:#A33B2A;
    --sans:"IBM Plex Sans",system-ui,-apple-system,sans-serif;
    --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,monospace;
    --serif:"IBM Plex Serif",Georgia,serif;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);
       font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}
  .wrap{max-width:1080px;margin:0 auto;padding:0 20px 80px}

  /* masthead */
  header{padding:34px 0 18px;border-bottom:2px solid var(--ink)}
  h1{font-family:var(--serif);font-weight:600;font-size:clamp(28px,5vw,42px);
     letter-spacing:-.02em;margin:0}
  .sub{font-family:var(--mono);font-size:12px;color:var(--muted);
       text-transform:uppercase;letter-spacing:.09em;margin-top:6px}

  /* hero: cap spectrum */
  .spectrum{margin:26px 0 8px;padding:22px 16px 10px;background:var(--card);
            border:1px solid var(--rule)}
  .spectrum h2{font-family:var(--mono);font-size:11px;letter-spacing:.12em;
               text-transform:uppercase;color:var(--muted);margin:0 0 20px;font-weight:500}
  .axis{position:relative;height:66px}
  .axis-line{position:absolute;left:0;right:0;top:33px;height:1px;background:var(--rule)}
  .tick{position:absolute;top:41px;transform:translateX(-50%);font-family:var(--mono);
        font-size:10px;color:var(--muted)}
  .tick::before{content:"";position:absolute;left:50%;top:-9px;width:1px;height:6px;
                background:var(--rule)}
  .dot{position:absolute;top:33px;transform:translate(-50%,-50%);border-radius:50%;
       cursor:pointer;opacity:.82;transition:transform .15s ease,opacity .15s ease;
       border:1.5px solid var(--card)}
  .dot:hover,.dot:focus-visible{transform:translate(-50%,-50%) scale(1.55);opacity:1;z-index:3}
  .readout{font-family:var(--mono);font-size:12px;color:var(--muted);min-height:18px;
           margin-top:2px}
  .legend{display:flex;flex-wrap:wrap;gap:14px 20px;margin-top:14px;padding-top:12px;
          border-top:1px solid var(--rule);font-family:var(--mono);font-size:10px;
          letter-spacing:.05em;text-transform:uppercase;color:var(--muted)}
  .lg{display:flex;align-items:center;gap:6px}
  .lg i{width:10px;height:10px;border-radius:50%;display:inline-block}
  .lg.sq i{border-radius:0;width:14px;height:6px}
  .lgh{color:var(--ink);font-weight:600}
  .readout b{color:var(--ink);font-weight:600}

  /* readout calendar */
  .cal{margin:22px 0 0;background:var(--card);border:1px solid var(--rule)}
  .cal h2{font-family:var(--mono);font-size:11px;letter-spacing:.12em;text-transform:uppercase;
          color:var(--muted);margin:0;font-weight:500;padding:16px 16px 12px;
          display:flex;align-items:center;gap:10px;cursor:pointer;user-select:none}
  .cal h2 b{color:var(--ink)}
  .cal h2 .caret{margin-left:auto;font-size:14px;transition:transform .15s ease}
  .cal.closed h2 .caret{transform:rotate(-90deg)}
  .cal.closed .calbody{display:none}
  .calrow{display:grid;grid-template-columns:52px 62px 1fr auto;gap:12px;align-items:baseline;
          padding:10px 16px;border-top:1px solid var(--rule)}
  .calrow:hover{background:#F5F8F9}
  .calwhen{font-family:var(--mono);font-size:11px;font-weight:600;text-align:right}
  .calwhen.soon{color:var(--r-ss)} .calwhen.near{color:var(--allergy)}
  .calwhen.later{color:var(--muted)}
  .caltkr{font-family:var(--mono);font-size:12px;font-weight:600}
  .caltitle{font-size:13px;line-height:1.4}
  .caltitle a{color:var(--ink);text-decoration:none}
  .caltitle a:hover{color:var(--accent);text-decoration:underline}
  .calmeta{font-family:var(--mono);font-size:10px;color:var(--muted);margin-top:2px}
  .calcap{font-family:var(--mono);font-size:11px;color:var(--muted);white-space:nowrap}
  .calempty{padding:20px 16px;border-top:1px solid var(--rule);color:var(--muted);font-size:13px}
  @media (max-width:620px){
    .calrow{grid-template-columns:52px 1fr;gap:8px}
    .caltitle{grid-column:1/-1}
    .calcap{display:none}
  }

  /* controls */
  .controls{position:sticky;top:0;z-index:5;background:var(--paper);
            padding:14px 0 12px;border-bottom:1px solid var(--rule);
            display:flex;flex-wrap:wrap;gap:8px;align-items:center}
  input[type=search]{flex:1 1 220px;min-width:0;padding:9px 12px;border:1px solid var(--rule);
        background:var(--card);font-family:var(--sans);font-size:14px;color:var(--ink)}
  input[type=search]:focus{outline:2px solid var(--accent);outline-offset:-1px}
  .chip{padding:8px 13px;border:1px solid var(--rule);background:var(--card);
        font-family:var(--mono);font-size:11px;letter-spacing:.06em;text-transform:uppercase;
        cursor:pointer;color:var(--muted);white-space:nowrap}
  .chip[aria-pressed=true]{background:var(--ink);color:var(--card);border-color:var(--ink)}
  .chip:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
  .count{font-family:var(--mono);font-size:12px;color:var(--muted);margin-left:auto}

  /* company rows */
  .row{background:var(--card);border:1px solid var(--rule);border-top:none}
  .row:first-of-type{border-top:1px solid var(--rule)}
  .head{display:grid;grid-template-columns:78px 1fr auto auto;gap:14px;align-items:baseline;
        padding:14px 16px;cursor:pointer;width:100%;background:none;border:0;text-align:left;
        font:inherit;color:inherit}
  .head:hover{background:#F5F8F9}
  .head:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
  .tkr{font-family:var(--mono);font-weight:600;font-size:14px;letter-spacing:.03em}
  .nm{font-weight:500}
  .meta{font-family:var(--mono);font-size:11px;color:var(--muted);margin-top:3px;
        display:flex;flex-wrap:wrap;gap:5px;align-items:center}
  .tag{padding:1px 6px;color:#fff;font-size:10px;letter-spacing:.05em;text-transform:uppercase}
  .tag.Oncology{background:var(--oncology)} .tag.Melanoma{background:var(--melanoma)}
  .tag.Allergy{background:var(--allergy)}
  /* analyst consensus */
  .rating{text-align:right;white-space:nowrap;min-width:104px}
  .rlabel{font-family:var(--mono);font-size:11px;font-weight:600;letter-spacing:.06em;
          text-transform:uppercase}
  .rlabel.strong_buy,.rlabel.buy{color:var(--r-sb)}
  .rlabel.hold{color:var(--r-h)}
  .rlabel.sell,.rlabel.strong_sell,.rlabel.underperform{color:var(--r-ss)}
  .rbar{display:flex;height:5px;width:100px;margin:4px 0 0 auto;background:var(--rule)}
  .rbar span{height:100%}
  .rup{font-family:var(--mono);font-size:11px;color:var(--muted);margin-top:3px}
  .rup.pos{color:var(--r-sb)} .rup.neg{color:var(--r-ss)}
  .rnone{font-family:var(--mono);font-size:11px;color:#A6B0BB}  .cap{font-family:var(--mono);font-size:15px;font-weight:600;text-align:right;white-space:nowrap}
  .cap small{display:block;font-size:10px;font-weight:400;color:var(--muted);
             letter-spacing:.08em;text-transform:uppercase}

  /* trials */
  .trials{display:none;border-top:1px solid var(--rule);background:#FBFCFD}
  .row.open .trials{display:block}
  .trial{padding:12px 16px 12px 28px;border-bottom:1px solid var(--rule);
         border-left:3px solid var(--rule)}
  .trial:last-child{border-bottom:none}
  .trial.Oncology{border-left-color:var(--oncology)}
  .trial.Melanoma{border-left-color:var(--melanoma)}
  .trial.Allergy{border-left-color:var(--allergy)}
  .role{font-family:var(--mono);font-size:9px;letter-spacing:.08em;text-transform:uppercase;
        padding:1px 5px;border:1px solid var(--rule);color:var(--muted);margin-left:6px;
        vertical-align:middle}
  .role.partner{border-color:var(--allergy);color:var(--allergy)}
  .trial a{color:var(--accent);text-decoration:none;font-weight:500}
  .trial a:hover{text-decoration:underline}
  .tmeta{font-family:var(--mono);font-size:11px;color:var(--muted);margin-top:4px}
  .status{font-weight:600;color:var(--ink)}

  .empty{padding:44px 16px;text-align:center;color:var(--muted);background:var(--card);
         border:1px solid var(--rule)}
  footer{margin-top:34px;padding-top:16px;border-top:1px solid var(--rule);
         font-family:var(--mono);font-size:11px;color:var(--muted);line-height:1.8}

  @media (max-width:620px){
    .head{grid-template-columns:1fr auto;gap:8px}
    .tkr{grid-column:1/-1}
    .rating{grid-column:1/-1;text-align:left}
    .rbar{margin-left:0}
    .cap{font-size:13px}
  }
  @media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>TrialScan</h1>
    <div class="sub">Phase 3 &middot; oncology, melanoma, allergy &middot; built __GENERATED__</div>
  </header>

  <section class="spectrum">
    <h2>Market cap spectrum — one dot per company, sized by trial count</h2>
    <div class="axis" id="axis"><div class="axis-line"></div></div>
    <div class="readout" id="readout">Hover a dot to identify a company. Click to filter.</div>
    <div class="legend">
      <span class="lgh">Dot colour = lead therapeutic area</span>
      <span class="lg"><i style="background:var(--oncology)"></i>Oncology</span>
      <span class="lg"><i style="background:var(--melanoma)"></i>Melanoma</span>
      <span class="lg"><i style="background:var(--allergy)"></i>Allergy</span>
      <span class="lg"><i style="background:var(--muted);opacity:.4"></i>Dot size = trial count</span>
    </div>
    <div class="legend">
      <span class="lgh">Analyst bar, left to right</span>
      <span class="lg sq"><i style="background:var(--r-sb)"></i>Strong buy</span>
      <span class="lg sq"><i style="background:var(--r-b)"></i>Buy</span>
      <span class="lg sq"><i style="background:var(--r-h)"></i>Hold</span>
      <span class="lg sq"><i style="background:var(--r-s)"></i>Sell</span>
      <span class="lg sq"><i style="background:var(--r-ss)"></i>Strong sell</span>
    </div>
    <div class="legend">
      <span class="lgh">Cap buckets</span>
      <span class="lg">Micro &lt;$300M · Small $300M–2B · Mid $2–10B · Large &gt;$10B</span>
    </div>
    <div class="legend">
      <span class="lgh">Partner tag</span>
      <span class="lg">Another company is the registered lead sponsor — the asset is co-developed</span>
    </div>
  </section>

  <section class="cal" id="cal">
    <h2 id="calToggle">Readouts expected — <b id="calCount">…</b>
      <span style="font-weight:400;text-transform:none;letter-spacing:0">
        primary completion within
        <select id="calWindow" style="font:inherit;border:1px solid var(--rule);
          background:var(--card);padding:1px 4px">
          <option value="3">3 months</option>
          <option value="6" selected>6 months</option>
          <option value="12">12 months</option>
        </select></span>
      <span class="caret">▾</span></h2>
    <div class="calbody" id="calBody"></div>
  </section>

  <div class="controls">
    <input type="search" id="q" placeholder="Search company, ticker, drug or condition" aria-label="Search">
    <button class="chip" data-area="Oncology" aria-pressed="false">Oncology</button>
    <button class="chip" data-area="Melanoma" aria-pressed="false">Melanoma</button>
    <button class="chip" data-area="Allergy" aria-pressed="false">Allergy</button>
    <button class="chip" data-bucket="Micro" aria-pressed="false">Micro</button>
    <button class="chip" data-bucket="Small" aria-pressed="false">Small</button>
    <button class="chip" data-bucket="Mid" aria-pressed="false">Mid</button>
    <button class="chip" data-bucket="Large" aria-pressed="false">Large</button>
    <button class="chip" id="buyOnly" aria-pressed="false">Rated buy</button>
    <span class="count" id="count"></span>
  </div>

  <main id="list"></main>

  <footer id="foot"></footer>
</div>

<script>
const DATA = __DATA__;
const cos = DATA.companies;

const fmtCap = c => !c ? "—" :
  c >= 1e9 ? "$" + (c/1e9).toFixed(2) + "B" : "$" + Math.round(c/1e6) + "M";
const fmtPrice = p => typeof p === "number"
  ? p.toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2})
  : p;
const esc = s => String(s ?? "").replace(/[&<>"]/g, m =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[m]));
const statusLabel = s => String(s||"").replace(/_/g," ").toLowerCase();

const RATING_COLORS = ["var(--r-sb)","var(--r-b)","var(--r-h)","var(--r-s)","var(--r-ss)"];

function ratingHTML(c){
  if(!c.rating && !c.rating_spread)
    return `<span class="rating rnone">no coverage</span>`;

  const label = String(c.rating||"").replace(/_/g," ");
  const n = c.analyst_count;
  let bar = "";
  if(c.rating_spread){
    const total = c.rating_spread.reduce((a,b)=>a+b,0) || 1;
    const names = ["strong buy","buy","hold","sell","strong sell"];
    bar = `<span class="rbar" title="${c.rating_spread.map((v,i)=>
        v ? `${v} ${names[i]}` : "").filter(Boolean).join(", ")}">` +
      c.rating_spread.map((v,i)=>
        v ? `<span style="width:${v/total*100}%;background:${RATING_COLORS[i]}"></span>` : ""
      ).join("") + `</span>`;
  }
  let up = "";
  if(c.upside_pct != null){
    const sign = c.upside_pct >= 0 ? "+" : "";
    up = `<span class="rup ${c.upside_pct>=0?"pos":"neg"}">${sign}${c.upside_pct}% to target</span>`;
  }
  return `<span class="rating">
    <span class="rlabel ${esc(String(c.rating||"").toLowerCase())}">${esc(label||"—")}${n?` ${n}`:""}</span>
    ${bar}${up ? "<br>"+up : ""}</span>`;
}

const state = {q:"", areas:new Set(), buckets:new Set(), buyOnly:false, pinned:null};

/* ---- hero: log-scale cap spectrum ---- */
function drawAxis(){
  const axis = document.getElementById("axis");
  const caps = cos.map(c=>c.market_cap).filter(Boolean);
  if(!caps.length) return;
  const lo = Math.log10(Math.min(...caps)*0.9), hi = Math.log10(Math.max(...caps)*1.1);
  const pos = v => ((Math.log10(v)-lo)/(hi-lo))*100;

  [1e8,3e8,1e9,3e9,1e10,3e10].forEach(v=>{
    const p = pos(v);
    if(p<1 || p>99) return;
    const t = document.createElement("div");
    t.className = "tick"; t.style.left = p+"%"; t.textContent = fmtCap(v);
    axis.appendChild(t);
  });

  const maxT = Math.max(...cos.map(c=>c.trial_count||1));
  cos.forEach(c=>{
    if(!c.market_cap) return;
    const d = document.createElement("button");
    const size = 8 + 12*Math.sqrt((c.trial_count||1)/maxT);
    d.className = "dot";
    d.style.cssText = `left:${pos(c.market_cap)}%;width:${size}px;height:${size}px;
      background:var(--${(c.areas[0]||"Oncology").toLowerCase()})`;
    d.setAttribute("aria-label", `${c.ticker}, ${fmtCap(c.market_cap)}, ${c.trial_count} trials`);
    const say = () => document.getElementById("readout").innerHTML =
      `<b>${esc(c.ticker)}</b> ${esc(c.name)} — ${fmtCap(c.market_cap)} · ${c.trial_count} Phase 3 · ${c.areas.join(", ")}`;
    d.addEventListener("mouseenter", say);
    d.addEventListener("focus", say);
    d.addEventListener("click", ()=>{
      state.pinned = state.pinned === c.ticker ? null : c.ticker;
      document.getElementById("q").value = state.pinned || "";
      state.q = (state.pinned||"").toLowerCase();
      render();
    });
    axis.appendChild(d);
  });
}

/* ---- readout calendar ---- */
function monthsUntil(d){
  if(!d) return null;
  const p = String(d).split("-");
  if(p.length < 2) return null;
  const dt = new Date(+p[0], +p[1]-1, p.length > 2 ? Math.min(+p[2],28) : 15);
  if(isNaN(dt)) return null;
  return (dt - new Date()) / (1000*60*60*24*30.44);
}

const DEAD = ["TERMINATED","WITHDRAWN","SUSPENDED"];

function calendarRows(months){
  // A melanoma trial also matches the oncology query, so the same NCT can appear
  // under two areas. Collapse per company+trial and merge the area tags.
  const seen = new Map();
  cos.forEach(c => (c.trials||[]).forEach(t => {
    if(t.has_results || DEAD.includes(t.status)) return;
    const m = monthsUntil(t.primary_completion);
    if(m === null || m < -6 || m > months) return;
    const key = c.ticker + "|" + t.nct_id;
    if(seen.has(key)){
      const prev = seen.get(key);
      if(t.area && !prev.areas.includes(t.area)) prev.areas.push(t.area);
      return;
    }
    seen.set(key, {...t, ticker:c.ticker, name:c.name, market_cap:c.market_cap,
                   months:m, areas:[t.area].filter(Boolean)});
  }));
  return [...seen.values()].sort((a,b)=>a.months-b.months);
}

function renderCalendar(){
  const months = +document.getElementById("calWindow").value;
  const rows = calendarRows(months);
  document.getElementById("calCount").textContent =
    `${rows.length} trial${rows.length===1?"":"s"}`;

  const body = document.getElementById("calBody");
  if(!rows.length){
    body.innerHTML = `<div class="calempty">No primary completion dates fall in this
      window. Try widening it — many sponsors list dates a year or more out.</div>`;
    return;
  }
  body.innerHTML = rows.slice(0,40).map(r=>{
    const cls = r.months < 0 ? "soon" : r.months < 3 ? "near" : "later";
    const when = r.months < 0 ? "overdue"
      : r.months < 1 ? `${Math.round(r.months*30)}d` : `${r.months.toFixed(1)}mo`;
    const est = r.pc_type === "ESTIMATED" ? " est." : "";
    return `<div class="calrow">
      <span class="calwhen ${cls}">${when}</span>
      <span class="caltkr">${esc(r.ticker)}</span>
      <span class="caltitle">
        <a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a>
        <span class="calmeta">${esc((r.areas||[]).join(", "))} ·
          ${esc(r.primary_completion)}${est} ·
          ${esc(statusLabel(r.status))}${r.enrollment?` · n=${r.enrollment}`:""}
          ${r.role==="partner"?" · partnered":""}</span>
      </span>
      <span class="calcap">${fmtCap(r.market_cap)}</span>
    </div>`;
  }).join("");
}

document.getElementById("calWindow").addEventListener("change", e=>{
  e.stopPropagation(); renderCalendar();
});
document.getElementById("calToggle").addEventListener("click", e=>{
  if(e.target.tagName === "SELECT") return;
  document.getElementById("cal").classList.toggle("closed");
});

/* ---- filtering ---- */
function matches(c){
  if(state.areas.size && !c.areas.some(a=>state.areas.has(a))) return false;
  if(state.buckets.size && !state.buckets.has(c.cap_bucket)) return false;
  if(state.buyOnly && !/buy/i.test(c.rating||"")) return false;
  if(!state.q) return true;
  const hay = [c.ticker, c.name, ...(c.sponsor_names||[]),
    ...c.trials.flatMap(t=>[t.title, ...(t.conditions||[]), ...(t.interventions||[])])
  ].join(" ").toLowerCase();
  return hay.includes(state.q);
}

function trialHTML(t){
  const role = t.role === "partner"
    ? `<span class="role partner" title="Partnered asset — another company is the registered lead sponsor">partner</span>`
    : "";
  return `<div class="trial ${t.area}">
    <a href="${esc(t.url)}" target="_blank" rel="noopener">${esc(t.title)}</a>${role}
    <div class="tmeta"><span class="status">${esc(statusLabel(t.status))}</span>
      &middot; ${esc(t.nct_id)}
      &middot; start ${esc(t.start_date||"n/a")}
      &middot; primary completion ${esc(t.primary_completion||"n/a")}
      ${t.enrollment ? "&middot; n=" + t.enrollment : ""}
      ${(t.interventions||[]).length ? "<br>" + esc(t.interventions.join(", ")) : ""}
    </div></div>`;
}

function render(){
  const list = document.getElementById("list");
  const shown = cos.filter(matches);
  document.getElementById("count").textContent =
    `${shown.length} of ${cos.length} companies`;

  if(!shown.length){
    list.innerHTML = `<div class="empty">No companies match these filters.
      Widen the cap range or clear the search.</div>`;
    return;
  }

  list.innerHTML = shown.map(c=>`
    <article class="row" data-t="${esc(c.ticker)}">
      <button class="head" aria-expanded="false">
        <span class="tkr">${esc(c.ticker)}</span>
        <span>
          <span class="nm">${esc(c.name)}</span>
          <span class="meta">
            ${c.areas.map(a=>`<span class="tag ${a}">${a}</span>`).join("")}
            <span>${c.trial_count} Phase 3</span>
            ${c.price ? `<span>· ${esc(c.currency||"USD")} ${fmtPrice(c.price)}</span>` : ""}
          </span>
        </span>
        <span class="cap">${fmtCap(c.market_cap)}<small>${esc(c.cap_bucket)} cap</small></span>
        ${ratingHTML(c)}
      </button>
      <div class="trials">${c.trials.map(trialHTML).join("")}</div>
    </article>`).join("");

  list.querySelectorAll(".head").forEach(btn=>{
    btn.addEventListener("click", ()=>{
      const row = btn.closest(".row");
      const open = row.classList.toggle("open");
      btn.setAttribute("aria-expanded", open);
    });
  });
}

/* ---- wiring ---- */
document.getElementById("q").addEventListener("input", e=>{
  state.q = e.target.value.trim().toLowerCase(); state.pinned = null; render();
});
document.querySelectorAll(".chip").forEach(chip=>{
  chip.addEventListener("click", ()=>{
    const on = chip.getAttribute("aria-pressed") === "true";
    chip.setAttribute("aria-pressed", !on);
    if(chip.id === "buyOnly"){ state.buyOnly = !on; render(); return; }
    const set = chip.dataset.area ? state.areas : state.buckets;
    const val = chip.dataset.area || chip.dataset.bucket;
    on ? set.delete(val) : set.add(val);
    render();
  });
});

document.getElementById("foot").innerHTML =
  `Trial data: ClinicalTrials.gov API v2. Company identity: SEC company_tickers.
   Market caps and analyst consensus: Yahoo Finance via yfinance, cached up to 24h.<br>
   ${DATA.unmatched_sponsors?.length || 0} industry sponsors could not be matched to a
   US-listed ticker — most are private, subsidiaries, or listed only outside the US.<br>
   Screening tool, not investment advice. Verify every figure at the source before acting on it.`;

drawAxis();
renderCalendar();
render();
</script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data.json")
    ap.add_argument("--out", default="dashboard.html")
    ap.add_argument("--demo", action="store_true", help="Render sample data instead.")
    args = ap.parse_args()

    if args.demo:
        data = DEMO
    else:
        p = Path(args.data)
        if not p.exists():
            print(f"{p} not found. Run scanner.py first, or try --demo.")
            raise SystemExit(1)
        data = json.loads(p.read_text())

    html = (TEMPLATE
            .replace("__DATA__", json.dumps(data))
            .replace("__GENERATED__", str(data.get("generated", ""))))
    Path(args.out).write_text(html)
    print(f"Wrote {args.out} — {len(data.get('companies', []))} companies. Open it in a browser.")


if __name__ == "__main__":
    main()
