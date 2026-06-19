# Job digest

A daily job-search digest, built and published by GitHub Actions.

- **Schedule:** every day at 21:00 UTC (07:00 Australia/Brisbane) — see
  [`.github/workflows/digest.yml`](.github/workflows/digest.yml).
- **What it does:** [`scripts/build_digest.py`](scripts/build_digest.py) fetches
  postings from automated sources, filters to relevant roles, deduplicates
  against `seen.json`, and writes `latest.html` + a dated `digest-YYYY-MM-DD.html`.
- **Read it:** `latest.html` (bookmark the GitHub Pages URL once Pages is enabled).

## Sources

| Source | Method |
|--------|--------|
| UQ (Workday) | JSON API (`wday/cxs/uq/uqcareers/jobs`) |
| CSIRO (SuccessFactors) | HTML parse of `jobTitle-link` anchors |

JS-rendered / blocked sites (ACU, Griffith, QUT, Cricket, ASD, Council) are listed
as "check manually" links in the digest rather than scraped.

## Dedup

`seen.json` is keyed by a SHA-1 of `site|title|location` (lowercased). Entries are
only ever added, never removed — so a role is "new" exactly once.

## Run it yourself

Locally: `python3 scripts/build_digest.py` (stdlib only — no installs).
On demand in the cloud: Actions tab → **Daily job digest** → **Run workflow**.
