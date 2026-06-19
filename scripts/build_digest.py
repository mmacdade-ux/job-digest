#!/usr/bin/env python3
"""
Daily job-search digest builder.

Fetches job postings from automated sources, filters to relevant roles,
deduplicates against seen.json, and writes a self-contained dark-mode HTML
digest. Designed to run on a GitHub Actions ubuntu runner (stdlib only — no pip
installs) where outbound network egress is open.

Sources that are JS-rendered or otherwise unscrapable are listed as static
"check manually" links rather than fetched.
"""

import json
import hashlib
import re
import html
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEEN_PATH = ROOT / "seen.json"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# Title keywords (case-insensitive) — include if any appears in the title.
TITLE_KEYWORDS = [
    "web", "design", "officer", "technical", "engineer", "ai", "multimedia",
    "computer", " it ", "system", "developer", "content", "digital",
    "communications", "accessibility", "learning", "ux", "comms", "marketing",
    "advisor",
]
# Location keywords — include if any appears in the location.
LOCATION_KEYWORDS = [
    "brisbane", "logan", "gold coast", "south east queensland", "qld",
    "queensland", "remote", "hybrid",
]

# Static manual-check list: JS-rendered / blocked sites we cannot reliably scrape.
MANUAL_CHECK = [
    ("ACU (PageUp)", "https://careers.acu.edu.au/en/listing/"),
    ("Griffith University", "https://www.griffith.edu.au/careers"),
    ("QUT", "https://www.qut.edu.au/about/careers"),
    ("Cricket Australia", "https://cricket.csod.com/ux/ats/careersite/11/home?c=cricket"),
    ("Cricket (site 12)", "https://cricket.csod.com/ux/ats/careersite/12/home?c=cricket"),
    ("ASD / Defence",
     "https://defencecareers.nga.net.au/cp/index.cfm?event=jobs.home&CurATC=ASDEXT&CurBID=C49A927D-AAE1-A68D-E047-B5FED76E0B7B&persistVariables=CurATC%2CCurBID"),
    ("Council (ccc.qld.gov.au)", "https://www.ccc.qld.gov.au/about/careers/vacancies"),
]


def _http(url, *, data=None, headers=None, timeout=25):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def fetch_uq():
    """UQ Workday CXS JSON API. Returns list of {title, location, url}."""
    base = "https://uq.wd3.myworkdayjobs.com/wday/cxs/uq/uqcareers/jobs"
    apply_base = "https://uq.wd3.myworkdayjobs.com/uqcareers"
    headers = {"Content-Type": "application/json", "Accept": "application/json",
               "User-Agent": UA}
    out, offset, total = [], 0, None
    while True:
        body = json.dumps({"appliedFacets": {}, "limit": 20,
                           "offset": offset, "searchText": ""}).encode()
        raw = _http(base, data=body, headers=headers)
        d = json.loads(raw)
        if total is None:
            total = d.get("total", 0)
        posts = d.get("jobPostings", [])
        if not posts:
            break
        for p in posts:
            ext = p.get("externalPath", "")
            out.append({
                "title": (p.get("title") or "").strip(),
                "location": (p.get("locationsText") or "").strip(),
                "url": apply_base + ext if ext else apply_base,
            })
        offset += 20
        if offset >= (total or 0) or offset >= 200:
            break
    return out


def fetch_csiro():
    """CSIRO SuccessFactors HTML. Returns list of {title, location, url}."""
    raw = _http("https://jobs.csiro.au/search/?createNewAlert=false&q=",
                headers={"User-Agent": UA})
    rows = re.findall(
        r'<a[^>]*class="[^"]*jobTitle-link[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        raw, re.S)
    out = []
    for href, txt in rows:
        title = html.unescape(re.sub(r"<[^>]+>", "", txt)).strip()
        if not title:
            continue
        url = href if href.startswith("http") else "https://jobs.csiro.au" + href
        out.append({"title": title, "location": "Various (CSIRO)", "url": url})
    return out


SOURCES = [
    ("UQ", "https://uq.wd3.myworkdayjobs.com/uqcareers", fetch_uq),
    ("CSIRO", "https://jobs.csiro.au/search/?createNewAlert=false&q=", fetch_csiro),
]


def keep(listing):
    title = listing["title"].lower()
    loc = listing["location"].lower()
    if any(k.strip() in title for k in TITLE_KEYWORDS):
        return True
    if any(k in loc for k in LOCATION_KEYWORDS):
        return True
    return False


def key_for(site, listing):
    raw = f"{site}|{listing['title']}|{listing['location']}".lower().strip()
    return hashlib.sha1(raw.encode()).hexdigest()


def esc(s):
    return html.escape(s or "", quote=True)


def build_html(date, time, new_by_source, manual_items, total_seen, sources_ok):
    n = sum(len(v) for v in new_by_source.values())
    s = len(SOURCES)
    w = len(manual_items)

    if n == 0:
        site_sections = '<p style="color:var(--muted)">No new postings today.</p>'
    else:
        parts = []
        for site, src_url, _ in SOURCES:
            items = new_by_source.get(site, [])
            if not items:
                continue
            lis = "\n".join(
                f'<li><b>{esc(i["title"])}</b> '
                f'<span class="loc">- {esc(i["location"])}</span> '
                f'<a href="{esc(i["url"])}">Apply</a></li>'
                for i in items)
            parts.append(
                f'<h2>{esc(site)} <span class="count">{len(items)} new</span> '
                f'<a class="source-link" href="{esc(src_url)}">(source)</a></h2>\n'
                f'<ul>\n{lis}\n</ul>')
        site_sections = "\n".join(parts)

    manual_lis = "\n".join(
        f'<li><a href="{esc(u)}">{esc(name)}</a>{note}</li>'
        for name, u, note in manual_items)
    manual_section = (
        '<div class="warning"><h2>Check these manually</h2><ul>\n'
        f'{manual_lis}\n</ul></div>')

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job digest - {date} - {n} new</title>
<script>(function(){{var s=localStorage.getItem("theme");var t=s||(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light");document.documentElement.dataset.theme=t;}})();</script>
<style>
:root{{color-scheme:light dark;--bg:#f4f4f6;--surface:#fff;--text:#1a1a1f;--muted:#5a5a66;--border:#d9d9e0;--accent:#2f7fc1;--new-badge:#1f6feb;--warn:#d4a017;}}
[data-theme="dark"]{{--bg:#0d1117;--surface:#161b22;--text:#e6edf3;--muted:#7d8590;--border:#30363d;--accent:#58a6ff;--new-badge:#1f6feb;--warn:#d4a017;}}
@media (prefers-color-scheme:dark){{:root:not([data-theme]){{--bg:#0d1117;--surface:#161b22;--text:#e6edf3;--muted:#7d8590;--border:#30363d;--accent:#58a6ff;--new-badge:#1f6feb;--warn:#d4a017;}}}}
*{{box-sizing:border-box;}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:760px;margin:0 auto;padding:32px 20px;background:var(--bg);color:var(--text);line-height:1.6;}}
header{{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:8px;}}
h1{{font-size:1.4rem;margin:0 auto 0 0;}}
.meta{{color:var(--muted);font-size:.85rem;margin-bottom:28px;}}
#theme-toggle{{cursor:pointer;background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:999px;padding:.3rem .75rem;font-size:.82rem;font-weight:600;}}
#theme-toggle:focus-visible{{outline:3px solid var(--accent);outline-offset:2px;}}
h2{{font-size:1.05rem;margin:28px 0 10px;display:flex;align-items:baseline;gap:8px;}}
.count{{background:var(--new-badge);color:#fff;font-size:.72rem;font-weight:600;padding:2px 7px;border-radius:10px;}}
.source-link{{font-size:.78rem;font-weight:400;color:var(--accent);}}
ul{{margin:0;padding-left:20px;}}
li{{margin-bottom:8px;}}
.loc{{color:var(--muted);font-size:.9rem;}}
a{{color:var(--accent);text-decoration:none;}}
.warning{{background:var(--surface);border-left:4px solid var(--warn);padding:12px 16px;margin:28px 0 10px;border-radius:0 6px 6px 0;}}
.warning h2{{margin:0 0 8px;font-size:.95rem;color:var(--warn);}}
.warning ul{{color:var(--muted);}}
footer{{margin-top:40px;padding-top:16px;border-top:1px solid var(--border);font-size:.85rem;color:var(--muted);}}
footer p{{margin:2px 0;}}
</style>
</head>
<body>
<header>
<h1>Job digest - {date} - {n} new</h1>
<button id="theme-toggle" aria-label="Toggle dark mode">Dark mode</button>
</header>
<p class="meta">Generated {date} at {time} UTC &middot; {n} new postings &middot; {sources_ok}/{s} sources auto-checked</p>
{site_sections}
{manual_section}
<footer>
<p>{n} new listings today &middot; {w} sites need a manual check</p>
<p>Total tracked in seen.json: {total_seen}</p>
</footer>
<script>
var b=document.getElementById("theme-toggle");function s(){{b.textContent=document.documentElement.dataset.theme==="dark"?"Light mode":"Dark mode";}}s();b.addEventListener("click",function(){{var n=document.documentElement.dataset.theme==="dark"?"light":"dark";document.documentElement.dataset.theme=n;localStorage.setItem("theme",n);s();}});
</script>
</body>
</html>
"""


def main():
    now = datetime.now(timezone.utc)
    date = now.strftime("%Y-%m-%d")
    time = now.strftime("%H:%M")

    seen = {}
    if SEEN_PATH.exists():
        try:
            seen = json.loads(SEEN_PATH.read_text() or "{}")
        except json.JSONDecodeError:
            seen = {}

    new_by_source = {}
    manual_items = list((n, u, "") for n, u in MANUAL_CHECK)
    sources_ok = 0

    for site, _src_url, fetch in SOURCES:
        try:
            listings = fetch()
            sources_ok += 1
        except Exception as e:  # noqa: BLE001 — best-effort per source
            print(f"WARN: {site} fetch failed: {e}", file=sys.stderr)
            manual_items.append((f"{site} (auto-source errored today)", _src_url, ""))
            continue

        new_here = []
        for listing in listings:
            if not keep(listing):
                continue
            k = key_for(site, listing)
            if k in seen:
                continue
            seen[k] = {
                "title": listing["title"], "url": listing["url"],
                "location": listing["location"], "source": site,
                "first_seen_date": date,
            }
            new_here.append(listing)
        if new_here:
            new_by_source[site] = new_here
        print(f"INFO: {site}: {len(listings)} fetched, {len(new_here)} new")

    page = build_html(date, time, new_by_source, manual_items, len(seen), sources_ok)
    (ROOT / "latest.html").write_text(page)
    (ROOT / f"digest-{date}.html").write_text(page)
    SEEN_PATH.write_text(json.dumps(seen, indent=2, sort_keys=True))

    n = sum(len(v) for v in new_by_source.values())
    print(f"OK: {date} - {n} new, {sources_ok}/{len(SOURCES)} sources, "
          f"{len(seen)} tracked")


if __name__ == "__main__":
    main()
