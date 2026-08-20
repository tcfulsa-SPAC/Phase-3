#!/usr/bin/env python3
"""
Run the screen, compare it to last time, and alert on what changed.

    python watch.py --seed      # first run: record the baseline, alert on nothing
    python watch.py             # every run after that

What counts as a change:
  NEW COMPANY   a ticker that wasn't in the screen before
  NEW TRIAL     an existing company registering another Phase 3
  STATUS CHANGE a trial moving between states - completion is the one to watch
  DROPPED       a company that fell out (usually acquired, delisted, or cap moved)

Every changed company gets recent SEC filings and press attached, so the digest
tells you what happened and why in the same place.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import news
import notify
import scanner

STATE = Path("state.json")

STATUS_NOTE = {
    "COMPLETED": "trial completed — readout window",
    "TERMINATED": "trial terminated",
    "SUSPENDED": "trial suspended",
    "WITHDRAWN": "trial withdrawn",
    "ACTIVE_NOT_RECRUITING": "finished enrolling",
    "RECRUITING": "now enrolling",
}


def fmt_cap(c):
    if not c:
        return "n/a"
    return f"${c/1e9:.2f}B" if c >= 1e9 else f"${round(c/1e6)}M"


def label(s):
    return str(s or "").replace("_", " ").lower()


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

def snapshot(companies: list[dict]) -> dict:
    return {c["ticker"]: {
        "name": c["name"],
        "market_cap": c["market_cap"],
        "areas": c["areas"],
        "trials": {t["nct_id"]: {"status": t["status"], "title": t["title"],
                                 "area": t["area"]} for t in c["trials"]},
    } for c in companies}


def diff(old: dict, new: dict) -> dict:
    changes = {"new_companies": [], "new_trials": [], "status_changes": [], "dropped": []}

    for tkr, cur in new.items():
        prev = old.get(tkr)
        if not prev:
            changes["new_companies"].append({"ticker": tkr, **cur})
            continue
        for nct, t in cur["trials"].items():
            was = prev["trials"].get(nct)
            if not was:
                changes["new_trials"].append({"ticker": tkr, "name": cur["name"],
                                              "nct_id": nct, **t})
            elif was["status"] != t["status"]:
                changes["status_changes"].append({
                    "ticker": tkr, "name": cur["name"], "nct_id": nct,
                    "title": t["title"], "area": t["area"],
                    "from": was["status"], "to": t["status"]})

    for tkr, prev in old.items():
        if tkr not in new:
            changes["dropped"].append({"ticker": tkr, "name": prev["name"]})

    return changes


def has_changes(ch: dict) -> bool:
    return any(ch[k] for k in ch)


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------

def build_digest(changes: dict, news_by_ticker: dict, generated: str) -> tuple[str, str]:
    """Return (html, plaintext)."""
    h: list[str] = []
    t: list[str] = []

    def section(title, rows, render_html, render_text):
        if not rows:
            return
        h.append(f'<h2 style="font:600 12px/1.4 ui-monospace,monospace;letter-spacing:.12em;'
                 f'text-transform:uppercase;color:#5E6B78;margin:26px 0 10px;'
                 f'padding-bottom:6px;border-bottom:1px solid #D2D9E0">'
                 f'{title} — {len(rows)}</h2>')
        t.append(f"\n{title.upper()} ({len(rows)})\n" + "-" * 40)
        for r in rows:
            h.append(render_html(r))
            t.append(render_text(r))

    def news_html(tkr):
        rows = news_by_ticker.get(tkr) or []
        if not rows:
            return ""
        li = "".join(
            f'<li style="margin:3px 0"><a href="{r["url"]}" '
            f'style="color:#135A63;text-decoration:none">{r["title"]}</a> '
            f'<span style="color:#8A96A3">· {r["source"]}</span></li>'
            for r in rows)
        return (f'<ul style="margin:8px 0 0;padding-left:18px;font-size:13px;'
                f'line-height:1.5">{li}</ul>')

    def news_text(tkr):
        rows = news_by_ticker.get(tkr) or []
        return "".join(f"\n    - [{r['source']}] {r['title']}\n      {r['url']}" for r in rows)

    card = ('style="background:#fff;border:1px solid #D2D9E0;border-left:3px solid %s;'
            'padding:13px 15px;margin-bottom:9px"')

    section(
        "New companies in Phase 3", changes["new_companies"],
        lambda r: (f'<div {card % "#135A63"}>'
                   f'<b style="font-family:ui-monospace,monospace">{r["ticker"]}</b> '
                   f'{r["name"]}<br>'
                   f'<span style="font-size:12px;color:#5E6B78">'
                   f'{fmt_cap(r["market_cap"])} · {", ".join(r["areas"])} · '
                   f'{len(r["trials"])} Phase 3</span>'
                   f'{news_html(r["ticker"])}</div>'),
        lambda r: (f'\n  {r["ticker"]} {r["name"]} — {fmt_cap(r["market_cap"])}, '
                   f'{", ".join(r["areas"])}, {len(r["trials"])} Phase 3'
                   + news_text(r["ticker"])))

    section(
        "New Phase 3 trials", changes["new_trials"],
        lambda r: (f'<div {card % "#6B4BC4"}>'
                   f'<b style="font-family:ui-monospace,monospace">{r["ticker"]}</b> '
                   f'{r["name"]}<br>'
                   f'<a href="https://clinicaltrials.gov/study/{r["nct_id"]}" '
                   f'style="color:#135A63;text-decoration:none">{r["title"]}</a><br>'
                   f'<span style="font-size:12px;color:#5E6B78">{r["area"]} · '
                   f'{label(r["status"])} · {r["nct_id"]}</span>'
                   f'{news_html(r["ticker"])}</div>'),
        lambda r: (f'\n  {r["ticker"]} — {r["title"]}\n    {r["area"]}, '
                   f'{label(r["status"])}, https://clinicaltrials.gov/study/{r["nct_id"]}'
                   + news_text(r["ticker"])))

    section(
        "Trial status changes", changes["status_changes"],
        lambda r: (f'<div {card % "#B8801C"}>'
                   f'<b style="font-family:ui-monospace,monospace">{r["ticker"]}</b> '
                   f'{r["name"]}<br>'
                   f'<a href="https://clinicaltrials.gov/study/{r["nct_id"]}" '
                   f'style="color:#135A63;text-decoration:none">{r["title"]}</a><br>'
                   f'<span style="font-size:12px;color:#5E6B78">'
                   f'{label(r["from"])} → <b style="color:#0D1218">{label(r["to"])}</b>'
                   f'{" · " + STATUS_NOTE[r["to"]] if r["to"] in STATUS_NOTE else ""}</span>'
                   f'{news_html(r["ticker"])}</div>'),
        lambda r: (f'\n  {r["ticker"]} — {r["title"]}\n    {label(r["from"])} -> '
                   f'{label(r["to"])}' + news_text(r["ticker"])))

    section(
        "Dropped out of the screen", changes["dropped"],
        lambda r: (f'<div {card % "#8A96A3"}>'
                   f'<b style="font-family:ui-monospace,monospace">{r["ticker"]}</b> '
                   f'{r["name"]}<br><span style="font-size:12px;color:#5E6B78">'
                   f'No longer matching — check for an acquisition, delisting, '
                   f'or a move outside your cap band.</span></div>'),
        lambda r: f'\n  {r["ticker"]} {r["name"]} — no longer matching')

    html = (f'<div style="font:15px/1.5 -apple-system,BlinkMacSystemFont,'
            f'\'Segoe UI\',sans-serif;background:#E9EDF0;padding:24px;color:#0D1218">'
            f'<div style="max-width:660px;margin:0 auto">'
            f'<h1 style="font:600 26px Georgia,serif;margin:0 0 4px">TrialScan</h1>'
            f'<div style="font:12px ui-monospace,monospace;color:#5E6B78;'
            f'letter-spacing:.08em;text-transform:uppercase">{generated}</div>'
            + "".join(h) +
            f'<p style="font-size:11px;color:#8A96A3;margin-top:28px;'
            f'border-top:1px solid #D2D9E0;padding-top:12px">'
            f'ClinicalTrials.gov · SEC EDGAR · Google News · Yahoo Finance. '
            f'Screening tool, not investment advice.</p></div></div>')

    text = f"TrialScan — {generated}\n" + "".join(t)
    return html, text


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Watch for new Phase 3 entrants and alert.")
    ap.add_argument("--seed", action="store_true",
                    help="Record the baseline without sending anything. Use on first run.")
    ap.add_argument("--min-cap", type=float, default=100e6)
    ap.add_argument("--max-cap", type=float, default=20e9)
    ap.add_argument("--news-days", type=int, default=7)
    ap.add_argument("--max-news-lookups", type=int, default=25,
                    help="Cap on companies to fetch news for, so one noisy run stays polite.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Write digest.html but send nothing.")
    args = ap.parse_args()

    try:
        payload = scanner.build_dataset(args.min_cap, args.max_cap)
    except RuntimeError as e:
        print(e)
        return 1

    Path("data.json").write_text(json.dumps(payload, indent=1))
    scanner.write_csvs(payload["companies"])

    new_state = snapshot(payload["companies"])
    old_state = json.loads(STATE.read_text()) if STATE.exists() else {}

    if args.seed or not old_state:
        STATE.write_text(json.dumps(new_state, indent=1))
        print(f"\nBaseline recorded: {len(new_state)} companies. "
              f"Future runs will report changes against it.")
        return 0

    changes = diff(old_state, new_state)
    counts = {k: len(v) for k, v in changes.items()}
    print(f"\nChanges: {counts}")

    if not has_changes(changes):
        STATE.write_text(json.dumps(new_state, indent=1))
        print("Nothing new. No alert sent.")
        return 0

    # News only for companies that actually changed.
    tickers = []
    for k in ("new_companies", "new_trials", "status_changes"):
        for r in changes[k]:
            if r["ticker"] not in tickers:
                tickers.append(r["ticker"])
    tickers = tickers[:args.max_news_lookups]

    by_ticker = {c["ticker"]: c for c in payload["companies"]}
    news_by_ticker = {}
    print(f"Fetching news for {len(tickers)} companies...")
    for i, tkr in enumerate(tickers, 1):
        news_by_ticker[tkr] = news.fetch_news(by_ticker[tkr], days=args.news_days)
        print(f"  {i}/{len(tickers)} {tkr}", end="\r", flush=True)
    print(" " * 40, end="\r")

    html, text = build_digest(changes, news_by_ticker, payload["generated"])
    Path("digest.html").write_text(html)

    n_new = counts["new_companies"]
    subject = (f"TrialScan: {n_new} new Phase 3 "
               f"{'company' if n_new == 1 else 'companies'}"
               if n_new else
               f"TrialScan: {counts['new_trials']} new trials, "
               f"{counts['status_changes']} status changes")

    if args.dry_run:
        print("Dry run — wrote digest.html, sent nothing.")
    else:
        cfg = notify.load_config()
        ok = notify.send_email(subject, html, text, cfg)
        ok |= notify.send_webhook(f"*{subject}*\n{text[:1400]}", cfg)
        if not ok:
            print("No delivery configured. digest.html has the full report — "
                  "see README for email and webhook setup.")

    STATE.write_text(json.dumps(new_state, indent=1))
    print("State updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
