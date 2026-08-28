#!/usr/bin/env python3
"""
ASD/Defence careers check — standalone, self-hosted-runner-only companion to
build_digest.py.

ASD's careers site (NGA/ColdFusion, plain server-rendered HTML) sits behind an
AWS WAF that blocks GitHub's cloud runner IPs with HTTP 405, while working
fine from a residential IP. This script exists to run on a self-hosted runner
(a home machine) instead, on its own schedule and its own dedup file
(seen-asd.json), so it never touches the main digest's pipeline or state.

  python3 scripts/build_asd_digest.py            # check + send if new
  python3 scripts/build_asd_digest.py --dry-run  # check only, no send
"""

import json
import hashlib
import re
import html
import os
import sys
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEEN_PATH = ROOT / "seen-asd.json"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

RECIPIENT = "m.macdade@griffith.edu.au"
FROM_ADDR = "onboarding@resend.dev"

# Same relevance filter as build_digest.py, kept in sync deliberately.
TITLE_KEYWORDS = [
    "web", "design", "officer", "technical", "engineer", "ai", "multimedia",
    "computer", " it ", "system", "developer", "content", "digital",
    "communications", "accessibility", "learning", "ux", "comms", "marketing",
    "advisor",
]
LOCATION_KEYWORDS = [
    "brisbane", "logan", "gold coast", "south east queensland", "qld",
    "queensland", "remote", "hybrid",
]

ASD_URL = ("https://defencecareers.nga.net.au/cp/index.cfm?event=jobs.home"
           "&CurATC=ASDEXT&CurBID=C49A927D-AAE1-A68D-E047-B5FED76E0B7B"
           "&persistVariables=CurATC%2CCurBID")

_ASD_JOB_RE = re.compile(
    r'<a\s+([^>]*class="cp_jobListJobTitle"[^>]*)>(.*?)</a>\s*<ul>(.*?)</ul>', re.S)
_HREF_RE = re.compile(r'href="([^"]+)"')
_LI_RE = re.compile(r'<li>(.*?)</li>', re.S)


def _strip_tags(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


def _http(url, *, headers=None, timeout=25):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def fetch_asd():
    """ASD/Defence careers (NGA, server-rendered HTML). Returns {title, location, url}.

    Lists all currently open roles on one page (no pagination handled — the
    "records" count was 12 of 12 when this was written).
    """
    raw = _http(ASD_URL, headers={"User-Agent": UA})
    out = []
    for attrs, title_html, ul_html in _ASD_JOB_RE.findall(raw):
        href_m = _HREF_RE.search(attrs)
        title = _strip_tags(title_html)
        if not href_m or not title:
            continue
        lis = _LI_RE.findall(ul_html)
        location = _strip_tags(lis[-1]) if lis else ""
        url = urllib.parse.urljoin(ASD_URL, html.unescape(href_m.group(1)))
        out.append({"title": title, "location": location, "url": url})
    return out


def keep(listing):
    title = listing["title"].lower()
    loc = listing["location"].lower()
    if any(k.strip() in title for k in TITLE_KEYWORDS):
        return True
    if any(k in loc for k in LOCATION_KEYWORDS):
        return True
    return False


def key_for(listing):
    raw = f"ASD|{listing['title']}|{listing['location']}".lower().strip()
    return hashlib.sha1(raw.encode()).hexdigest()


def esc(s):
    return html.escape(s or "", quote=True)


def render_email(date, items):
    rows = "".join(
        f'<div style="margin:0 0 14px">'
        f'<a href="{esc(i["url"])}" style="font-size:15px;font-weight:600;'
        f'color:#1a1a1f;text-decoration:none">{esc(i["title"])}</a>'
        f'<div style="font-size:13px;color:#5a5a66;margin-top:2px">{esc(i["location"])}</div>'
        f'</div>' for i in items)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>ASD digest — {date}</title>
<style>
  body {{ margin:0; background:#f4f4f6; }}
  @media (prefers-color-scheme: dark) {{
    body, .wrap {{ background:#0d1117 !important; }}
    .card {{ background:#161b22 !important; border-color:#30363d !important; }}
    h1 {{ color:#e6edf3 !important; }}
    .muted {{ color:#9aa4b2 !important; }}
  }}
</style>
</head>
<body style="margin:0;background:#f4f4f6;">
<div class="wrap" style="background:#f4f4f6;padding:24px 12px;">
  <div class="card" style="max-width:640px;margin:0 auto;background:#ffffff;border:1px solid #d9d9e0;border-radius:12px;padding:28px 26px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.55;">
    <h1 style="font-size:22px;margin:0 0 4px;color:#1a1a1f;">ASD digest</h1>
    <div class="muted" style="font-size:13px;color:#8a8a96;margin-bottom:8px;">{date} · {len(items)} new</div>
    <hr style="border:none;border-top:1px solid #e3e3e8;margin:8px 0 4px;">
    {rows}
    <hr style="border:none;border-top:1px solid #e3e3e8;margin:24px 0 10px;">
    <div class="muted" style="font-size:12px;color:#8a8a96;">
      Checked from a self-hosted runner — ASD's site blocks GitHub's cloud
      runners, so this runs separately from the main job digest.
    </div>
  </div>
</div>
</body>
</html>"""


def send_resend(subject, html_body):
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        raise SystemExit("RESEND_API_KEY not set — cannot send.")
    payload = json.dumps({
        "from": FROM_ADDR, "to": [RECIPIENT],
        "subject": subject, "html": html_body,
    }).encode()
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "Accept": "application/json", "User-Agent": UA})  # default urllib UA is
        # Cloudflare-banned (error 1010) in front of api.resend.com; send a browser UA
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"Resend: HTTP {r.status} {r.read().decode()[:200]}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print(f"Resend send FAILED — HTTP {e.code}. Response:\n{body}", file=sys.stderr)
        raise SystemExit(1)


def main():
    dry_run = "--dry-run" in sys.argv
    now = datetime.now(timezone.utc)
    date = now.strftime("%Y-%m-%d")

    seen = {}
    if SEEN_PATH.exists():
        try:
            seen = json.loads(SEEN_PATH.read_text() or "{}")
        except json.JSONDecodeError:
            seen = {}

    try:
        listings = fetch_asd()
    except Exception as e:  # noqa: BLE001 — best-effort, this is a convenience check
        print(f"WARN: ASD fetch failed: {e}", file=sys.stderr)
        return

    new_items = []
    for listing in listings:
        if not keep(listing):
            continue
        k = key_for(listing)
        if k in seen:
            continue
        seen[k] = {"title": listing["title"], "url": listing["url"],
                    "location": listing["location"], "first_seen_date": date}
        new_items.append(listing)

    print(f"INFO: ASD: {len(listings)} fetched, {len(new_items)} new")

    if dry_run:
        (ROOT / "asd-email-preview.html").write_text(render_email(date, new_items))
        print("DRY RUN — asd-email-preview.html written, seen-asd.json NOT updated, email NOT sent.")
        return

    SEEN_PATH.write_text(json.dumps(seen, indent=2, sort_keys=True))

    if not new_items:
        print("0 new ASD postings — skipping email.")
        return
    send_resend(f"ASD digest — {date} — {len(new_items)} new", render_email(date, new_items))
    print("Email sent.")


if __name__ == "__main__":
    main()
