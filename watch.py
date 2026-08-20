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
from datetime import datetime
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
        "trials": {t["nct_id"]: {
            "status": t["status"], "title": t["title"], "area": t["area"],
            "primary_completion": t.get("primary_completion"),
            "pc_type": t.get("pc_type"),
            "has_results": bool(t.get("has_results")),
        } for t in c["trials"]},
    } for c in companies}


def months_until(date_str: str | None) -> float | None:
    """Rough months from today to a YYYY-MM or YYYY-MM-DD registry date."""
    if not date_str:
        return None
    try:
        parts = date_str.split("-")
        y, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 6
        d = int(parts[2]) if len(parts) > 2 else 15
        target = datetime(y, m, min(d, 28))
        return (target - datetime.now()).days / 30.44
    except Exception:
        return None


def diff(old: dict, new: dict) -> dict:
    changes = {"results_posted": [], "new_companies": [], "new_trials": [],
               "status_changes": [], "date_changes": [], "dropped": []}

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
                continue

            # Results appearing on the registry is the readout itself.
            if t.get("has_results") and not was.get("has_results"):
                changes["results_posted"].append({
                    "ticker": tkr, "name": cur["name"], "nct_id": nct,
                    "title": t["title"], "area": t["area"]})

            if was["status"] != t["status"]:
                changes["status_changes"].append({
                    "ticker": tkr, "name": cur["name"], "nct_id": nct,
                    "title": t["title"], "area": t["area"],
                    "from": was["status"], "to": t["status"]})

            # A primary completion date moving is a signal in its own right:
            # pushed out usually means enrolment trouble, pulled in can mean
            # an interim analysis. Either way the sponsor knows before you do.
            old_pc, new_pc = was.get("primary_completion"), t.get("primary_completion")
            if old_pc and new_pc and old_pc != new_pc:
                changes["date_changes"].append({
                    "ticker": tkr, "name": cur["name"], "nct_id": nct,
                    "title": t["title"], "area": t["area"],
                    "from": old_pc, "to": new_pc,
                    "direction": "pushed back" if new_pc > old_pc else "pulled forward",
                    "pc_type": t.get("pc_type")})

    for tkr, prev in old.items():
        if tkr not in new:
            changes["dropped"].append({"ticker": tkr, "name": prev["name"]})

    return changes


def upcoming_catalysts(companies: list[dict], months: float = 4.0) -> list[dict]:
    """Trials whose primary completion falls inside the next `months`.

    This is the forward view: it doesn't need anything to have changed, it just
    tells you which readouts are close. Sorted nearest first.
    """
    rows = []
    for c in companies:
        for t in c["trials"]:
            if t.get("has_results"):
                continue  # already read out
            if t.get("status") in ("TERMINATED", "WITHDRAWN", "SUSPENDED"):
                continue
            m = months_until(t.get("primary_completion"))
            if m is None or m < -1 or m > months:
                continue
            rows.append({
                "ticker": c["ticker"], "name": c["name"],
                "market_cap": c.get("market_cap"),
                "nct_id": t["nct_id"], "title": t["title"], "area": t["area"],
                "status": t.get("status"), "date": t.get("primary_completion"),
                "pc_type": t.get("pc_type"), "months": round(m, 1),
                "enrollment": t.get("enrollment")})
    rows.sort(key=lambda r: r["months"])
    return rows


def sweep_readout_news(companies: list[dict], cal: list[dict], days: int,
                       max_lookups: int, verbose: bool = True) -> tuple[dict, list]:
    """Check the news for every company with a readout window open.

    This is the part that catches the actual event. The registry updates weeks
    after a readout; the press release and the 8-K land the same morning. So for
    any company with a trial completing soon, we look at its feeds every run —
    whether or not anything changed in the registry.
    """
    by_ticker = {c["ticker"]: c for c in companies}
    watch = []
    for r in cal:
        if r["ticker"] not in watch:
            watch.append(r["ticker"])
    watch = watch[:max_lookups]

    if verbose:
        print(f"Sweeping news for {len(watch)} companies with readouts pending...")

    found, hits = {}, []
    for i, tkr in enumerate(watch, 1):
        rows = news.fetch_news(by_ticker[tkr], days=days)
        found[tkr] = rows
        for r in rows:
            if r.get("readout"):
                hits.append({**r, "ticker": tkr, "name": by_ticker[tkr]["name"],
                             "market_cap": by_ticker[tkr].get("market_cap")})
        if verbose:
            print(f"  {i}/{len(watch)} {tkr}", end="\r", flush=True)
    if verbose:
        print(" " * 40, end="\r")
        print(f"  {len(hits)} possible readout headlines found")
    return found, hits


def has_changes(ch: dict) -> bool:
    return any(ch[k] for k in ch)


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------

def build_digest(changes: dict, news_by_ticker: dict, generated: str,
                 calendar: list[dict] | None = None,
                 cal_months: float = 4.0,
                 readout_news: list[dict] | None = None) -> tuple[str, str]:
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

    if readout_news:
        h.append('<h2 style="font:600 12px/1.4 ui-monospace,monospace;letter-spacing:.12em;'
                 'text-transform:uppercase;color:#A33B2A;margin:20px 0 10px;'
                 'padding-bottom:6px;border-bottom:2px solid #A33B2A">'
                 f'Possible readouts in the news — {len(readout_news)}</h2>')
        t.append(f"\nPOSSIBLE READOUTS IN THE NEWS ({len(readout_news)})\n" + "=" * 44)
        for r in readout_news:
            h.append(f'<div style="background:#fff;border:1px solid #D2D9E0;'
                     f'border-left:3px solid #A33B2A;padding:13px 15px;margin-bottom:9px">'
                     f'<b style="font-family:ui-monospace,monospace">{r["ticker"]}</b> '
                     f'<span style="color:#5E6B78">{fmt_cap(r["market_cap"])}</span><br>'
                     f'<a href="{r["url"]}" style="color:#135A63;text-decoration:none;'
                     f'font-weight:500">{r["title"]}</a><br>'
                     f'<span style="font-size:12px;color:#5E6B78">{r["source"]}</span></div>')
            t.append(f'\n  {r["ticker"]} — {r["title"]}\n    [{r["source"]}] {r["url"]}')

    section(
        "READOUT — results posted to the registry", changes["results_posted"],
        lambda r: (f'<div {card % "#A33B2A"}>'
                   f'<b style="font-family:ui-monospace,monospace">{r["ticker"]}</b> '
                   f'{r["name"]}<br>'
                   f'<a href="https://clinicaltrials.gov/study/{r["nct_id"]}?tab=results" '
                   f'style="color:#135A63;text-decoration:none">{r["title"]}</a><br>'
                   f'<span style="font-size:12px;color:#5E6B78">{r["area"]} · '
                   f'results now available · {r["nct_id"]}</span>'
                   f'{news_html(r["ticker"])}</div>'),
        lambda r: (f'\n  {r["ticker"]} — RESULTS POSTED — {r["title"]}\n    '
                   f'https://clinicaltrials.gov/study/{r["nct_id"]}?tab=results'
                   + news_text(r["ticker"])))

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
        "Completion date moved", changes["date_changes"],
        lambda r: (f'<div {card % "#1E4470"}>'
                   f'<b style="font-family:ui-monospace,monospace">{r["ticker"]}</b> '
                   f'{r["name"]}<br>'
                   f'<a href="https://clinicaltrials.gov/study/{r["nct_id"]}" '
                   f'style="color:#135A63;text-decoration:none">{r["title"]}</a><br>'
                   f'<span style="font-size:12px;color:#5E6B78">primary completion '
                   f'<b style="color:#0D1218">{r["direction"]}</b>: '
                   f'{r["from"]} → {r["to"]}</span>'
                   f'{news_html(r["ticker"])}</div>'),
        lambda r: (f'\n  {r["ticker"]} — {r["title"]}\n    primary completion '
                   f'{r["direction"]}: {r["from"]} -> {r["to"]}' + news_text(r["ticker"])))

    section(
        "Dropped out of the screen", changes["dropped"],
        lambda r: (f'<div {card % "#8A96A3"}>'
                   f'<b style="font-family:ui-monospace,monospace">{r["ticker"]}</b> '
                   f'{r["name"]}<br><span style="font-size:12px;color:#5E6B78">'
                   f'No longer matching — check for an acquisition, delisting, '
                   f'or a move outside your cap band.</span></div>'),
        lambda r: f'\n  {r["ticker"]} {r["name"]} — no longer matching')

    if calendar:
        h.append('<h2 style="font:600 12px/1.4 ui-monospace,monospace;letter-spacing:.12em;'
                 'text-transform:uppercase;color:#5E6B78;margin:26px 0 10px;'
                 'padding-bottom:6px;border-bottom:1px solid #D2D9E0">'
                 f'Readouts expected in the next {cal_months:.0f} months — {len(calendar)}</h2>')
        t.append(f"\nREADOUTS EXPECTED ({len(calendar)})\n" + "-" * 40)
        for r in calendar[:25]:
            when = "overdue" if r["months"] < 0 else f'{r["months"]:.1f} mo'
            est = " (estimated)" if r.get("pc_type") == "ESTIMATED" else ""
            h.append(f'<div style="background:#fff;border:1px solid #D2D9E0;'
                     f'border-left:3px solid #B8801C;padding:10px 14px;margin-bottom:6px">'
                     f'<b style="font-family:ui-monospace,monospace">{r["ticker"]}</b> '
                     f'<span style="color:#5E6B78">{fmt_cap(r["market_cap"])}</span> · '
                     f'<b>{when}</b><br>'
                     f'<a href="https://clinicaltrials.gov/study/{r["nct_id"]}" '
                     f'style="color:#135A63;text-decoration:none;font-size:14px">'
                     f'{r["title"]}</a><br>'
                     f'<span style="font-size:12px;color:#5E6B78">{r["area"]} · '
                     f'{r["date"]}{est} · {label(r["status"])}</span></div>')
            t.append(f'\n  {r["ticker"]} ({when}) {r["date"]}{est} — {r["title"]}')

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
    ap.add_argument("--min-cap", type=float, default=50e6)
    ap.add_argument("--max-cap", type=float, default=5e12)
    ap.add_argument("--news-days", type=int, default=7)
    ap.add_argument("--max-news-lookups", type=int, default=40,
                    help="Cap on companies to fetch news for, so one noisy run stays polite.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Write digest.html but send nothing.")
    ap.add_argument("--calendar-months", type=float, default=4.0,
                    help="Include readouts expected within this many months.")
    ap.add_argument("--no-sweep", action="store_true",
                    help="Skip the daily readout news sweep.")
    ap.add_argument("--calendar", action="store_true",
                    help="Just print the upcoming readout calendar and exit.")
    args = ap.parse_args()

    try:
        payload = scanner.build_dataset(args.min_cap, args.max_cap)
    except RuntimeError as e:
        print(e)
        return 1

    Path("data.json").write_text(json.dumps(payload, indent=1))
    scanner.write_csvs(payload["companies"])

    cal = upcoming_catalysts(payload["companies"], args.calendar_months)

    if args.calendar:
        print(f"\nReadouts expected within {args.calendar_months:.0f} months "
              f"({len(cal)} trials)\n" + "=" * 66)
        for r in cal:
            when = "overdue" if r["months"] < 0 else f'{r["months"]:>4.1f} mo'
            print(f'{r["ticker"]:6s} {when}  {r["date"]:10s} {fmt_cap(r["market_cap"]):>8s}  '
                  f'{r["title"][:58]}')
        return 0

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

    # The sweep runs every time, regardless of registry changes. A readout hits
    # the wire the same morning; the registry catches up weeks later.
    sweep_news, readout_hits = ({}, [])
    if not args.no_sweep:
        sweep_news, readout_hits = sweep_readout_news(
            payload["companies"], cal, args.news_days, args.max_news_lookups)

    if not has_changes(changes) and not readout_hits:
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
    news_by_ticker = dict(sweep_news)
    todo = [t for t in tickers if t not in news_by_ticker]
    if todo:
        print(f"Fetching news for {len(todo)} changed companies...")
        for i, tkr in enumerate(todo, 1):
            news_by_ticker[tkr] = news.fetch_news(by_ticker[tkr], days=args.news_days)
            print(f"  {i}/{len(todo)} {tkr}", end="\r", flush=True)
        print(" " * 40, end="\r")

    html, text = build_digest(changes, news_by_ticker, payload["generated"],
                              calendar=cal, cal_months=args.calendar_months,
                              readout_news=readout_hits)
    Path("digest.html").write_text(html)

    n_res, n_new = counts["results_posted"], counts["new_companies"]
    if readout_hits:
        lead = readout_hits[0]
        subject = (f"TrialScan: possible readout — {lead['ticker']}"
                   + (f" +{len(readout_hits)-1} more" if len(readout_hits) > 1 else ""))
    elif n_res:
        subject = (f"TrialScan: {n_res} Phase 3 readout"
                   f"{'' if n_res == 1 else 's'} posted")
    elif n_new:
        subject = (f"TrialScan: {n_new} new Phase 3 "
                   f"{'company' if n_new == 1 else 'companies'}")
    else:
        subject = (f"TrialScan: {counts['new_trials']} new trials, "
                   f"{counts['status_changes']} status changes, "
                   f"{counts['date_changes']} date moves")

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
