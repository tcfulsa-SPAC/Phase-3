#!/usr/bin/env python3
"""
Pull recent news and regulatory filings for a company.

Three free feeds, no API keys:
  SEC EDGAR   - 8-K / 424B5 / S-1 filings. The highest-signal source for biotech:
                material events and financings hit here before the press picks them up.
  Google News - broad press coverage, restricted to the last N days.
  Yahoo       - headline feed keyed to the ticker.

RSS/Atom is parsed with the standard library, so there's no feedparser dependency.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

import requests

ATOM = "{http://www.w3.org/2005/Atom}"

# Filing types worth waking up for. 8-K is the material-event catch-all;
# 424B5 / S-1 usually mean a raise, which matters if you hold the stock.
FILINGS_OF_INTEREST = "8-K,424B5,S-1,S-3,6-K"

HEADERS = {"User-Agent": "TrialScan research script contact@example.com"}


def _get(url: str, headers: dict | None = None) -> str | None:
    try:
        r = requests.get(url, headers=headers or HEADERS, timeout=25)
        r.raise_for_status()
        return r.text
    except Exception:
        return None


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    try:  # RSS: Tue, 12 Aug 2026 14:03:00 GMT
        return parsedate_to_datetime(raw)
    except Exception:
        pass
    try:  # Atom: 2026-08-12T14:03:00-04:00
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def _items(xml: str) -> list[dict]:
    """Flatten either RSS <item> or Atom <entry> into a common shape."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []

    out = []
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        get = lambda n: (it.findtext(n) or it.findtext(ATOM + n) or "").strip()

        link = get("link")
        if not link:
            for ln in it.findall(ATOM + "link"):
                if ln.get("href"):
                    link = ln.get("href")
                    break

        out.append({
            "title": re.sub(r"<[^>]+>", "", get("title")),
            "url": link,
            "date": _parse_date(get("pubDate") or get("updated") or get("published")),
            "source": get("source") or "",
        })
    return out


# ---------------------------------------------------------------------------
# Feeds
# ---------------------------------------------------------------------------

def sec_filings(cik: int | str | None, days: int) -> list[dict]:
    if not cik:
        return []
    url = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
           f"&CIK={str(cik).zfill(10)}&type={FILINGS_OF_INTEREST}"
           "&dateb=&owner=include&count=20&output=atom")
    xml = _get(url)
    if not xml:
        return []
    rows = []
    for it in _items(xml):
        rows.append({**it, "source": "SEC EDGAR", "kind": "filing"})
    return rows


def google_news(company: str, ticker: str, days: int) -> list[dict]:
    q = f'"{company}" OR "{ticker}" when:{days}d'
    url = (f"https://news.google.com/rss/search?q={quote_plus(q)}"
           "&hl=en-US&gl=US&ceid=US:en")
    xml = _get(url)
    if not xml:
        return []
    return [{**it, "source": it["source"] or "Google News", "kind": "news"}
            for it in _items(xml)]


def yahoo_headlines(ticker: str) -> list[dict]:
    url = ("https://feeds.finance.yahoo.com/rss/2.0/headline"
           f"?s={quote_plus(ticker)}&region=US&lang=en-US")
    xml = _get(url)
    if not xml:
        return []
    return [{**it, "source": it["source"] or "Yahoo Finance", "kind": "news"}
            for it in _items(xml)]


# ---------------------------------------------------------------------------

# Phrases that mark a press release or filing as an actual trial readout rather
# than routine corporate news. Deliberately broad — a false positive costs you
# one line in a digest; a false negative costs you the event.
READOUT_PATTERNS = re.compile(
    r"\b(topline|top-line|primary endpoint|primary and (key )?secondary|"
    r"met (its|the|both)|statistically significant|interim analysis|"
    r"phase 3 (data|results|readout)|phase iii (data|results)|"
    r"pivotal (data|results|trial results)|readout|"
    r"positive (data|results)|failed to meet|did not meet|missed (its|the)|"
    r"overall survival|progression-free survival|recurrence-free|"
    r"data monitoring committee|dsmb|stopped early|halt(ed|s)? (the )?trial)\b",
    re.I)


def is_readout(title: str) -> bool:
    """Does this headline look like trial results rather than corporate noise?"""
    return bool(READOUT_PATTERNS.search(title or ""))


def _key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()[:70]


def fetch_news(company: dict, days: int = 7, limit: int = 6,
               polite_delay: float = 0.4) -> list[dict]:
    """Recent filings and headlines for one company, newest first, deduped."""
    ticker, name = company["ticker"], company["name"]
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    rows: list[dict] = []
    for fn in (lambda: sec_filings(company.get("cik"), days),
               lambda: google_news(name, ticker, days),
               lambda: yahoo_headlines(ticker)):
        rows.extend(fn())
        time.sleep(polite_delay)

    seen, keep = set(), []
    for r in rows:
        if not r["title"] or not r["url"]:
            continue
        d = r["date"]
        if d and d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        if d and d < cutoff:
            continue
        k = _key(r["title"])
        if k in seen:
            continue
        seen.add(k)
        keep.append({**r, "date": d, "readout": is_readout(r["title"])})

    # Filings first, then newest news.
    keep.sort(key=lambda r: (not r["readout"], r["kind"] != "filing",
                             -(r["date"].timestamp() if r["date"] else 0)))
    return keep[:limit]


if __name__ == "__main__":
    import json
    import sys
    tkr = sys.argv[1] if len(sys.argv) > 1 else "IOVA"
    for row in fetch_news({"ticker": tkr, "name": tkr, "cik": None}, days=14):
        print(f"[{row['source']}] {row['title']}\n  {row['url']}")
