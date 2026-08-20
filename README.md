# Phase-3
In this Repository we can view the Phase 3 Trials in the USA per Company
# TrialScan

Finds small- and mid-cap listed companies running **Phase 3** trials in oncology,
melanoma, and allergy — then tells you when that list changes and what the news says.

## Quick start

```bash
pip install -r requirements.txt
export SEC_USER_AGENT="TrialScan yourname you@example.com"   # SEC asks for this

python watch.py --seed     # first run: records the baseline, alerts on nothing
python dashboard.py        # builds dashboard.html
open dashboard.html
```

From then on, `python watch.py` reports only what moved since last time.
Want to see the interface first? `python dashboard.py --demo`.

## What you get alerted about

| Change | Why it matters |
|---|---|
| **New company** | A ticker entering the Phase 3 screen for the first time |
| **New trial** | An existing company registering another Phase 3 |
| **Status change** | Especially `-> COMPLETED` — that's the readout window opening |
| **Dropped** | Fell out of the screen: acquired, delisted, or cap moved out of band |

Each changed company arrives with its recent filings and press attached, so the
digest tells you what happened and what's being said about it in one place.

## News sources

Three free feeds, no API keys:

- **SEC EDGAR** — 8-K, 424B5, S-1, S-3, 6-K. Highest signal for biotech: material
  events and financings land here before the press picks them up.
- **Google News** — broad coverage, restricted to the last 7 days (`--news-days`).
- **Yahoo Finance** — headline feed keyed to the ticker.

Results are deduplicated by headline, filings sorted first.

## Getting the alerts

Set up either or both. Environment variables win over `config.json`.

**Email** — copy `config.example.json` to `config.json` and fill it in. For Gmail,
enable 2FA and create an App Password at myaccount.google.com/apppasswords; your
normal password won't work. Port 465 uses SSL, 587 uses STARTTLS — both handled.

**Slack or Discord** — create an incoming webhook and set `SLACK_WEBHOOK` or
`DISCORD_WEBHOOK`. Nothing else to configure.

With neither set, `watch.py` still writes `digest.html` locally. `--dry-run` builds
the digest and sends nothing, which is the right way to test.

## Running it on a schedule

**GitHub Actions (free, nothing to keep running).** `.github/workflows/watch.yml` is
ready to go: push the repo, add your secrets under Settings -> Secrets -> Actions
(`SEC_USER_AGENT`, `SMTP_*`, `ALERT_TO`, or the webhook), and it runs weekday
mornings. It commits `state.json` back to the repo so each run can diff against the
last. Run it by hand from the Actions tab first to confirm delivery works.

**Cron on your own machine:**

```
0 8 * * 1-5 cd /path/to/trialscan && /usr/bin/python3 watch.py >> watch.log 2>&1
```

Daily is the right cadence. ClinicalTrials.gov records update roughly daily, and a
sponsor registering a Phase 3 isn't an intraday event.

## How the screen works

| Step | Source | Cost |
|---|---|---|
| Phase 3 trials + sponsor | ClinicalTrials.gov API v2 | free, no key |
| Sponsor name -> ticker | SEC `company_tickers.json` | free, no key |
| Market cap, price | Yahoo Finance via `yfinance` | free, unofficial |

`scanner.py` builds the dataset · `news.py` fetches coverage · `notify.py` delivers ·
`watch.py` orchestrates and diffs · `dashboard.py` renders the browsable page.

Everything is cached in `.cache/`, so re-runs are fast. Run `scanner.py` on its own
if you just want a fresh snapshot without any alerting.

## Useful flags

```bash
python scanner.py --min-cap 300e6 --max-cap 10e9   # classic small+mid band
python scanner.py --status RECRUITING              # only actively enrolling
python scanner.py --no-cap-filter                  # keep every matched company
python watch.py --dry-run --news-days 14           # test without sending
python news.py IOVA                                # sanity-check the feeds alone
```

## Tuning it

**Therapeutic areas** live in the `AREAS` dict at the top of `scanner.py`. Each value
is a ClinicalTrials.gov condition query — add rare disease, cardiology, whatever.

**Missed companies** are the main thing to fix as you go. After each run, check
`data.json` -> `unmatched_sponsors`. Most are genuinely private or listed only outside
the US, but some are subsidiaries filing under a name the SEC file doesn't carry
("Janssen Research & Development" -> JNJ). Add those to `MANUAL_TICKERS` in
`scanner.py`. That map is where the accuracy comes from.

**Alert volume.** If the digest is noisy, narrow the cap band, cut `AREAS` down to the
indications you actually follow, or drop `NOT_YET_RECRUITING` from `--status`.

## Known limits

- **US-listed only.** The SEC file misses companies listed solely in Tokyo,
  Copenhagen, Shanghai, etc. Covering those means a paid reference source
  (Financial Modeling Prep, Polygon, OpenFIGI) that maps names to global identifiers.
- **yfinance is unofficial** and occasionally returns nothing for a ticker. Those
  companies fall out of the cap filter silently — run `--no-cap-filter` to see them.
- **Registry lag.** Sponsors update ClinicalTrials.gov on their own schedule, so a
  status change can appear days or weeks after the fact. This is not a news wire, and
  anything genuinely market-moving will reach a press release before it reaches here.
- **Sponsor is not always the owner.** The trial sponsor is often the licensee, not the
  company that owns the asset economically. Read the trial before drawing conclusions.
- **`primary_completion` is a plan**, and plans slip. It is not a catalyst date.

This is a screening tool, not investment advice. Verify anything you act on at the
source before acting on it.
