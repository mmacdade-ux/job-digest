# Job digest

A daily job-search digest, emailed via [Resend](https://resend.com) and built by
GitHub Actions.

- **Schedule:** every day at 21:00 UTC (07:00 Australia/Brisbane) — see
  [`.github/workflows/digest.yml`](.github/workflows/digest.yml).
- **What it does:** [`scripts/build_digest.py`](scripts/build_digest.py) fetches
  postings from automated sources, filters to relevant roles, deduplicates
  against `seen.json`, emails an HTML digest, and commits `latest.html` + a dated
  `digest-YYYY-MM-DD.html` as a web archive.
- **Read it:** `latest.html` (bookmark the GitHub Pages URL once Pages is enabled).

## Sources

| Source | Method |
|--------|--------|
| UQ (Workday) | JSON API (`wday/cxs/uq/uqcareers/jobs`) |
| CSIRO (SuccessFactors) | HTML parse of `jobTitle-link` anchors |

JS-rendered / blocked sites (ACU, Griffith, QUT, Cricket, Council) are listed
as "check manually" links in the digest rather than scraped. ASD is also on
that list, but is additionally covered by a separate pipeline — see below.

## ASD digest (separate pipeline)

ASD's careers page is plain scrapable HTML, but it sits behind an AWS WAF that
returns HTTP 405 to GitHub Actions' cloud runner IPs specifically (confirmed
working from a residential IP, blocked only from Actions) — a permanent
cloud-ASN block, not something a retry or header change fixes. So it runs as
its own small pipeline on a **self-hosted runner** (a home machine) instead:

- [`scripts/build_asd_digest.py`](scripts/build_asd_digest.py) — its own fetch,
  its own dedup file (`seen-asd.json`), its own Resend email. Never touches
  the main digest's data.
- [`.github/workflows/asd-digest.yml`](.github/workflows/asd-digest.yml) —
  `runs-on: self-hosted`, scheduled Tue/Fri 09:15 Brisbane (queues and waits
  for the runner if it's offline at that exact moment).
- Uses the same `RESEND_API_KEY` secret as the main digest.

## Setup (one-time)

1. **Resend:** uses the same Resend account as
   [tech-digest](https://github.com/mmacdade-ux/tech-digest) — no new signup
   needed, but the free tier only delivers to the account's own address
   (`m.macdade@griffith.edu.au`), so that's the fixed recipient here too.
2. **Secret:** repo → Settings → Secrets and variables → Actions → New repository
   secret → `RESEND_API_KEY` (its own key, created separately in Resend —
   API key values are shown once and can't be copied from tech-digest's).
3. **Actions write:** Settings → Actions → General → Workflow permissions →
   Read and write.
4. *(optional)* **Pages:** Settings → Pages → Deploy from branch `main` / root →
   archive at `https://mmacdade-ux.github.io/job-digest/latest.html`.

## Dedup

`seen.json` is keyed by a SHA-1 of `site|title|location` (lowercased). Entries are
only ever added, never removed — so a role is "new" exactly once.

## Run it yourself

```sh
python3 scripts/build_digest.py --dry-run   # build archive + email-preview.html, no send
python3 scripts/build_digest.py             # build + send (needs RESEND_API_KEY)
```

On demand in the cloud: Actions tab → **Daily job digest** → **Run workflow**.
