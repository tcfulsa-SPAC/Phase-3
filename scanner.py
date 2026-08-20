#!/usr/bin/env python3
"""
TrialScan - find small- and mid-cap public companies running Phase 3 trials
in oncology, melanoma, and allergy.

Pipeline:
  1. Pull Phase 3 studies from ClinicalTrials.gov API v2 (free, no key).
  2. Keep industry-sponsored trials only.
  3. Resolve sponsor company name -> stock ticker via the SEC company_tickers file.
  4. Enrich with market cap via yfinance.
  5. Filter to the small/mid-cap band and write data.json + CSVs.

Usage:
    python scanner.py
    python scanner.py --min-cap 300e6 --max-cap 10e9 --status RECRUITING
    python scanner.py --no-cap-filter          # keep every matched company
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

import requests

CTG_API = "https://clinicaltrials.gov/api/v2/studies"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"

# The SEC asks for a descriptive User-Agent with a contact address.
# Put your own email here before running.
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "TrialScan research script you@example.com")

CACHE = Path(".cache")
CACHE.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Therapeutic areas. Each is an Essie query sent to ClinicalTrials.gov's
# condition field. Add or edit freely - this is the main knob you'll turn.
# ---------------------------------------------------------------------------
AREAS: dict[str, str] = {
    "Oncology": (
        "cancer OR neoplasm OR carcinoma OR tumor OR lymphoma OR leukemia "
        "OR myeloma OR sarcoma OR glioma OR glioblastoma"
    ),
    "Melanoma": "melanoma OR \"uveal melanoma\" OR \"cutaneous melanoma\"",
    "Allergy": (
        "allergy OR allergic OR anaphylaxis OR \"atopic dermatitis\" "
        "OR \"allergic rhinitis\" OR \"food allergy\" OR urticaria "
        "OR \"eosinophilic esophagitis\" OR \"chronic rhinosinusitis\""
    ),
}

DEFAULT_STATUSES = [
    "NOT_YET_RECRUITING",
    "RECRUITING",
    "ENROLLING_BY_INVITATION",
    "ACTIVE_NOT_RECRUITING",
]

# Sponsor names that don't fuzzy-match cleanly to their SEC filing name.
# Grow this map as you spot misses - it's the highest-leverage fix.
MANUAL_TICKERS: dict[str, str] = {
    "iovance biotherapeutics": "IOVA",
    "replimune": "REPL",
    "immunocore": "IMCR",
    "arcus biosciences": "RCUS",
    "revolution medicines": "RVMD",
    "nuvation bio": "NUVB",
    "day one biopharmaceuticals": "DAWN",
    "aravive": "ARAV",
    "aldeyra therapeutics": "ALDX",
    "arcutis biotherapeutics": "ARQT",
    "connect biopharma": "CNTB",
    "aimmune therapeutics": "",           # acquired by Nestle - not independently listed
    "kyowa kirin": "",                    # Tokyo-listed, not in SEC file
    # Subsidiaries file trials under their own name, not the parent's:
    "merck sharp dohme": "MRK",
    "merck sharp dohme corp": "MRK",
    "genentech": "RHHBY",
    "janssen research development": "JNJ",
    "janssen": "JNJ",
    "bristol myers squibb": "BMY",
    "astrazeneca": "AZN",
    "hoffmann la roche": "RHHBY",
}

# Corporate-form and industry words stripped before matching.
NOISE = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|llc|lp|plc|"
    r"sa|nv|ag|as|ab|oy|aps|gmbh|bv|kk|spa|srl|pty|holdings?|group|the|"
    r"pharmaceuticals?|pharma|pharmaceutica|therapeutics?|biosciences?|bioscience|"
    r"biotherapeutics?|biopharmaceuticals?|biopharma|biotech(nology)?|medicines?|"
    r"laboratories|labs?|sciences?|health(care)?|oncology|immunotherapeutics?)\b",
    re.I,
)


def normalize(name: str) -> str:
    """Reduce a company name to a comparable key."""
    s = name.lower()
    s = re.sub(r"[.,()\-/&']", " ", s)
    s = NOISE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ---------------------------------------------------------------------------
# 1. ClinicalTrials.gov
# ---------------------------------------------------------------------------

FIELD_PATHS = ",".join([
    "protocolSection.identificationModule",
    "protocolSection.statusModule",
    "protocolSection.sponsorCollaboratorsModule",
    "protocolSection.conditionsModule",
    "protocolSection.designModule",
    "protocolSection.armsInterventionsModule",
])


def fetch_area(area: str, condition_query: str, statuses: list[str],
               page_size: int = 200, verbose: bool = True) -> list[dict]:
    """Page through every Phase 3 study matching one therapeutic area."""
    studies: list[dict] = []
    token: str | None = None
    use_fields = True

    while True:
        params = {
            "format": "json",
            "query.cond": condition_query,
            # `filter.phase` does NOT exist in API v2 - it returns
            # "unknown parameter". Phase filtering goes through filter.advanced.
            "filter.advanced": "AREA[Phase]PHASE3",
            # Comma-separated. A pipe here returns HTTP 400.
            "filter.overallStatus": ",".join(statuses),
            "pageSize": page_size,
        }
        if use_fields:
            params["fields"] = FIELD_PATHS
        if token:
            params["pageToken"] = token

        r = requests.get(CTG_API, params=params,
                         headers={"User-Agent": SEC_USER_AGENT}, timeout=60)

        # If the server rejects the field projection, fall back to full records.
        if r.status_code == 400 and use_fields:
            print(f"\n  field projection rejected, retrying without it")
            use_fields = False
            continue

        # Surface the server's own explanation instead of a bare HTTPError.
        if r.status_code >= 400:
            raise RuntimeError(
                f"ClinicalTrials.gov returned {r.status_code} for area '{area}'.\n"
                f"  URL:  {r.url}\n"
                f"  Body: {r.text[:400]}")

        r.raise_for_status()

        payload = r.json()
        batch = payload.get("studies", [])
        studies.extend(batch)
        token = payload.get("nextPageToken")
        if verbose:
            print(f"  {area}: {len(studies)} studies", end="\r", flush=True)
        if not token or not batch:
            break
        time.sleep(0.2)

    if verbose:
        print(f"  {area}: {len(studies)} studies      ")
    return studies


def parse_study(study: dict, area: str) -> dict | None:
    """Flatten one API record. Returns None if it isn't an industry Phase 3."""
    p = study.get("protocolSection", {})
    design = p.get("designModule", {})

    # Belt-and-braces: confirm phase client-side even though we filtered server-side.
    if "PHASE3" not in (design.get("phases") or []):
        return None

    sponsor = (p.get("sponsorCollaboratorsModule", {}) or {}).get("leadSponsor", {}) or {}
    if sponsor.get("class") != "INDUSTRY":
        return None

    ident = p.get("identificationModule", {})
    status = p.get("statusModule", {})
    arms = p.get("armsInterventionsModule", {}) or {}

    enrollment = (design.get("enrollmentInfo") or {}).get("count")
    interventions = [
        i.get("name") for i in (arms.get("interventions") or []) if i.get("name")
    ]

    return {
        "nct_id": ident.get("nctId"),
        "title": ident.get("briefTitle"),
        "area": area,
        "sponsor": sponsor.get("name", "").strip(),
        "status": status.get("overallStatus"),
        "start_date": (status.get("startDateStruct") or {}).get("date"),
        "primary_completion": (status.get("primaryCompletionDateStruct") or {}).get("date"),
        "conditions": (p.get("conditionsModule", {}) or {}).get("conditions", []),
        "enrollment": enrollment,
        "interventions": interventions[:6],
        "url": f"https://clinicaltrials.gov/study/{ident.get('nctId')}",
    }


# ---------------------------------------------------------------------------
# 2. Sponsor name -> ticker
# ---------------------------------------------------------------------------

def load_sec_index() -> dict[str, dict]:
    """Download (and cache) the SEC's ticker file, keyed by normalized name."""
    cached = CACHE / "sec_tickers.json"
    if cached.exists() and time.time() - cached.stat().st_mtime < 7 * 86400:
        raw = json.loads(cached.read_text())
    else:
        r = requests.get(SEC_TICKERS, headers={"User-Agent": SEC_USER_AGENT}, timeout=60)
        r.raise_for_status()
        raw = r.json()
        cached.write_text(json.dumps(raw))

    index: dict[str, dict] = {}
    for row in raw.values():
        key = normalize(row["title"])
        if key and key not in index:
            index[key] = {"ticker": row["ticker"], "name": row["title"], "cik": row["cik_str"]}
    return index


def match_ticker(sponsor: str, index: dict[str, dict]) -> dict | None:
    """Exact-then-fuzzy match a sponsor name against the SEC index."""
    key = normalize(sponsor)
    if not key:
        return None

    if key in MANUAL_TICKERS:
        t = MANUAL_TICKERS[key]
        return {"ticker": t, "name": sponsor, "cik": None, "match": "manual"} if t else None

    if key in index:
        return {**index[key], "match": "exact"}

    # Fuzzy: require a high ratio so "Bayer" doesn't grab "Baye Corp".
    close = difflib.get_close_matches(key, index.keys(), n=1, cutoff=0.90)
    if close:
        return {**index[close[0]], "match": "fuzzy"}

    # Last resort: sponsor key is a full prefix of exactly one indexed name.
    prefix = [k for k in index if k.startswith(key + " ") or k == key]
    if len(prefix) == 1:
        return {**index[prefix[0]], "match": "prefix"}

    return None


# ---------------------------------------------------------------------------
# 3. Market cap
# ---------------------------------------------------------------------------

def load_cap_cache() -> dict:
    f = CACHE / "market_caps.json"
    return json.loads(f.read_text()) if f.exists() else {}


def save_cap_cache(cache: dict) -> None:
    (CACHE / "market_caps.json").write_text(json.dumps(cache, indent=1))


def fetch_market_cap(ticker: str, cache: dict) -> dict:
    """Look up market cap, price and sector. Cached for 24h."""
    hit = cache.get(ticker)
    if hit and time.time() - hit.get("_ts", 0) < 86400:
        return hit

    result = {"ticker": ticker, "market_cap": None, "price": None,
              "currency": None, "sector": None, "_ts": time.time()}
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        try:
            fi = tk.fast_info
            result["market_cap"] = fi.get("market_cap") or fi.get("marketCap")
            result["price"] = fi.get("last_price") or fi.get("lastPrice")
            result["currency"] = fi.get("currency")
        except Exception:
            pass
        if not result["market_cap"]:
            info = tk.info or {}
            result["market_cap"] = info.get("marketCap")
            result["price"] = info.get("currentPrice")
            result["currency"] = info.get("currency")
            result["sector"] = info.get("industry") or info.get("sector")
    except Exception as e:
        result["error"] = str(e)[:120]

    cache[ticker] = result
    return result


def cap_bucket(cap: float | None) -> str:
    if not cap:
        return "Unknown"
    if cap < 300e6:
        return "Micro"
    if cap < 2e9:
        return "Small"
    if cap < 10e9:
        return "Mid"
    return "Large"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_dataset(min_cap: float = 100e6, max_cap: float = 20e9,
                  statuses: list[str] | None = None, cap_filter: bool = True,
                  verbose: bool = True) -> dict:
    """Run the whole pipeline and return the payload. Reused by watch.py."""
    statuses = statuses or DEFAULT_STATUSES
    say = print if verbose else (lambda *a, **k: None)

    say("Fetching Phase 3 trials from ClinicalTrials.gov...")
    trials: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for area, query in AREAS.items():
        for study in fetch_area(area, query, statuses, verbose=verbose):
            row = parse_study(study, area)
            if not row or not row["sponsor"]:
                continue
            # A melanoma trial also matches the oncology query - keep both tags,
            # but never the same (trial, area) pair twice.
            if (row["nct_id"], area) in seen:
                continue
            seen.add((row["nct_id"], area))
            trials.append(row)

    if not trials:
        raise RuntimeError("No trials returned. Check your network or the AREAS queries.")
    say(f"{len(trials)} industry-sponsored Phase 3 trial records.\n")

    say("Resolving sponsors to tickers (SEC company_tickers)...")
    index = load_sec_index()
    say(f"  SEC index: {len(index)} filers")

    sponsors: dict[str, dict] = {}
    for t in trials:
        sponsors.setdefault(t["sponsor"], {"trials": []})["trials"].append(t)

    matched, unmatched = {}, []
    for name, blob in sponsors.items():
        m = match_ticker(name, index)
        if m:
            matched.setdefault(m["ticker"], {"ticker": m["ticker"], "legal_name": m["name"],
                                             "cik": m.get("cik"), "sponsors": [], "trials": []})
            matched[m["ticker"]]["sponsors"].append(name)
            matched[m["ticker"]]["trials"].extend(blob["trials"])
        else:
            unmatched.append(name)
    say(f"  matched {len(matched)} listed companies, {len(unmatched)} sponsors unresolved\n")

    say("Fetching market caps...")
    cache = load_cap_cache()
    companies = []
    for i, (ticker, c) in enumerate(sorted(matched.items()), 1):
        fin = fetch_market_cap(ticker, cache)
        cap = fin.get("market_cap")
        companies.append({
            "ticker": ticker,
            "name": c["legal_name"],
            "cik": c.get("cik"),
            "sponsor_names": sorted(set(c["sponsors"])),
            "market_cap": cap,
            "cap_bucket": cap_bucket(cap),
            "price": fin.get("price"),
            "currency": fin.get("currency"),
            "sector": fin.get("sector"),
            "areas": sorted({t["area"] for t in c["trials"]}),
            "trial_count": len(c["trials"]),
            "trials": sorted(c["trials"], key=lambda t: t.get("start_date") or "", reverse=True),
        })
        if verbose:
            print(f"  {i}/{len(matched)} {ticker}", end="\r", flush=True)
    save_cap_cache(cache)
    if verbose:
        print(" " * 40, end="\r")

    if cap_filter:
        before = len(companies)
        companies = [c for c in companies
                     if c["market_cap"] and min_cap <= c["market_cap"] <= max_cap]
        say(f"Cap filter {min_cap/1e6:.0f}M-{max_cap/1e9:.0f}B: "
            f"{len(companies)} of {before} companies kept.")

    companies.sort(key=lambda c: c["market_cap"] or 0)

    return {
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "filters": {"min_cap": min_cap, "max_cap": max_cap,
                    "statuses": statuses, "cap_filter": cap_filter},
        "companies": companies,
        "unmatched_sponsors": sorted(unmatched),
    }


def write_csvs(companies: list[dict]) -> None:
    with open("companies.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "name", "market_cap_usd", "cap_bucket", "areas", "phase3_trials"])
        for c in companies:
            w.writerow([c["ticker"], c["name"], c["market_cap"], c["cap_bucket"],
                        "; ".join(c["areas"]), c["trial_count"]])

    with open("trials.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "company", "market_cap_usd", "area", "nct_id", "title",
                    "status", "start_date", "primary_completion", "enrollment",
                    "conditions", "interventions", "url"])
        for c in companies:
            for t in c["trials"]:
                w.writerow([c["ticker"], c["name"], c["market_cap"], t["area"], t["nct_id"],
                            t["title"], t["status"], t["start_date"], t["primary_completion"],
                            t["enrollment"], "; ".join(t["conditions"]),
                            "; ".join(t["interventions"]), t["url"]])


def main() -> int:
    ap = argparse.ArgumentParser(description="Find small/mid-cap companies with Phase 3 trials.")
    ap.add_argument("--min-cap", type=float, default=100e6, help="Minimum market cap (USD).")
    ap.add_argument("--max-cap", type=float, default=20e9, help="Maximum market cap (USD).")
    ap.add_argument("--no-cap-filter", action="store_true", help="Keep every matched company.")
    ap.add_argument("--status", nargs="*", default=DEFAULT_STATUSES,
                    help=f"Trial statuses. Default: {' '.join(DEFAULT_STATUSES)}")
    ap.add_argument("--out", default="data.json")
    args = ap.parse_args()

    try:
        payload = build_dataset(args.min_cap, args.max_cap, args.status,
                                cap_filter=not args.no_cap_filter)
    except RuntimeError as e:
        print(e)
        return 1

    Path(args.out).write_text(json.dumps(payload, indent=1))
    write_csvs(payload["companies"])
    print(f"\nWrote {args.out}, companies.csv, trials.csv")
    print("Next: python dashboard.py   ->  builds dashboard.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
