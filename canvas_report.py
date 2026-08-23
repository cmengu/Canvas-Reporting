#!/usr/bin/env python3
"""Canvas Weekly — fetch NUS Canvas data, diff against last week, render report.html.

Usage:
  python3 canvas_report.py           # real run (needs ~/.canvas_token)
  python3 canvas_report.py --demo    # sample data, no token needed

Exit codes: 0 ok, 2 no token (so run_weekly.sh skips the republish).
"""

import json
import html
import re
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SNAP_DIR = ROOT / "snapshots"
CONFIG = json.loads((ROOT / "config.json").read_text()) if (ROOT / "config.json").exists() else {}
BASE_URL = CONFIG.get("base_url", "https://canvas.nus.edu.sg")
SGT = timezone(timedelta(hours=8))
LOOKAHEAD_WEEKS = 3


# ---------------------------------------------------------------- Canvas API

def load_token():
    for p in (Path.home() / ".canvas_token",):
        if p.exists():
            return p.read_text().strip()
    return None


def api_get(token, path, params=None):
    """GET a Canvas endpoint, following Link-header pagination. Returns a list."""
    params = dict(params or {})
    params.setdefault("per_page", 100)
    url = f"{BASE_URL}/api/v1/{path}?{urllib.parse.urlencode(params, doseq=True)}"
    out = []
    while url:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
            out.extend(data if isinstance(data, list) else [data])
            url = None
            for part in resp.headers.get("Link", "").split(","):
                if 'rel="next"' in part:
                    url = part[part.find("<") + 1:part.find(">")]
    return out


def gather(token):
    """Pull everything the report needs into one snapshot dict."""
    now = datetime.now(timezone.utc)
    snap = {"generated_at": now.isoformat(), "courses": {}, "assignments": {}, "files": {}, "announcements": []}

    courses = [c for c in api_get(token, "courses", {"enrollment_state": "active", "include[]": "term"})
               if c.get("name")]
    for c in courses:
        cid = str(c["id"])
        snap["courses"][cid] = {"code": c.get("course_code") or c["name"], "name": c["name"]}

        for a in api_get(token, f"courses/{cid}/assignments", {"include[]": "submission"}):
            sub = a.get("submission") or {}
            snap["assignments"][str(a["id"])] = {
                "course": cid,
                "name": a.get("name", "Untitled"),
                "due_at": a.get("due_at"),
                "points": a.get("points_possible"),
                "url": a.get("html_url", ""),
                "submitted": sub.get("workflow_state") not in (None, "unsubmitted"),
                "missing": bool(sub.get("missing")),
                "score": sub.get("score"),
                "graded_at": sub.get("graded_at"),
            }

        for m in api_get(token, f"courses/{cid}/modules", {"include[]": "items"}):
            for item in m.get("items") or []:
                if item.get("type") == "File":
                    snap["files"][str(item["id"])] = {
                        "course": cid, "title": item.get("title", "file"),
                        "module": m.get("name", ""), "url": item.get("html_url", ""),
                    }

    week_ago = (now - timedelta(days=7)).isoformat()
    ctx = [f"course_{cid}" for cid in snap["courses"]]
    if ctx:
        for ann in api_get(token, "announcements", {"context_codes[]": ctx, "start_date": week_ago}):
            cid = str(ann.get("context_code", "")).replace("course_", "")
            snap["announcements"].append({
                "course": cid, "title": ann.get("title", ""),
                "posted_at": ann.get("posted_at"), "url": ann.get("html_url", ""),
                "message": re.sub(r"<[^>]+>", " ", ann.get("message") or "").strip()[:280],
            })
    return snap


# ---------------------------------------------------------------- diff

def load_previous_snapshot():
    snaps = sorted(SNAP_DIR.glob("*.json"))
    return json.loads(snaps[-1].read_text()) if snaps else None


def diff_snapshots(prev, cur):
    d = {"first_run": prev is None, "new_assignments": [], "due_changes": [], "new_files": [], "new_grades": []}
    if prev is None:
        return d
    for aid, a in cur["assignments"].items():
        pa = prev["assignments"].get(aid)
        if pa is None:
            d["new_assignments"].append(aid)
        else:
            if pa.get("due_at") != a.get("due_at") and a.get("due_at"):
                d["due_changes"].append((aid, pa.get("due_at")))
            if a.get("score") is not None and pa.get("score") != a.get("score"):
                d["new_grades"].append(aid)
    d["new_files"] = [fid for fid in cur["files"] if fid not in prev["files"]]
    return d


# ---------------------------------------------------------------- rendering

def parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(SGT) if s else None


def fmt_due(s):
    dt = parse_iso(s)
    return dt.strftime("%a %d %b, %I:%M %p").replace(" 0", " ") if dt else "no due date"


def esc(s):
    return html.escape(str(s or ""))


def chip(snap, cid):
    return f'<span class="chip">{esc(snap["courses"].get(cid, {}).get("code", "?"))}</span>'


def assignment_row(snap, aid, ticked=True, note=""):
    a = snap["assignments"][aid]
    pts = f'<span class="mono dim">{a["points"]:g} pts</span>' if a.get("points") else ""
    box = f'<input type="checkbox" data-tick="{esc(aid)}" aria-label="done">' if ticked else ""
    note_html = f'<span class="note">{note}</span>' if note else ""
    return (f'<li class="row">{box}<div class="rowbody">'
            f'<div class="rowtop">{chip(snap, a["course"])}<a href="{esc(a["url"])}">{esc(a["name"])}</a>{note_html}</div>'
            f'<div class="rowsub mono">{esc(fmt_due(a["due_at"]))} &nbsp;{pts}</div></div></li>')


def section(title, count, body, tone=""):
    if not body:
        return ""
    return (f'<section class="{tone}"><h2><span class="eyebrow">{esc(title)}</span>'
            f'<span class="count mono">{count}</span></h2>{body}</section>')


def render(snap, d):
    now = datetime.now(SGT)
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=7)

    def due_between(a, lo, hi):
        dt = parse_iso(a.get("due_at"))
        return dt is not None and lo <= dt < hi

    assignments = snap["assignments"]

    due_this_week = sorted((aid for aid, a in assignments.items() if due_between(a, now, now + timedelta(days=7))),
                           key=lambda i: assignments[i]["due_at"])
    red_flags = sorted((aid for aid, a in assignments.items()
                        if a.get("due_at") and parse_iso(a["due_at"]) < now
                        and not a.get("submitted") and a.get("score") is None
                        and parse_iso(a["due_at"]) > now - timedelta(days=45)),
                       key=lambda i: assignments[i]["due_at"], reverse=True)

    lookahead = []
    for w in range(1, LOOKAHEAD_WEEKS + 1):
        lo, hi = now + timedelta(days=7 * w), now + timedelta(days=7 * (w + 1))
        ids = sorted((aid for aid, a in assignments.items() if due_between(a, lo, hi)),
                     key=lambda i: assignments[i]["due_at"])
        if ids:
            lookahead.append((lo, ids))

    # -- section bodies
    flags_html = "<ul>" + "".join(assignment_row(snap, i, ticked=False) for i in red_flags) + "</ul>" if red_flags else ""
    due_html = ("<ul>" + "".join(assignment_row(snap, i) for i in due_this_week) + "</ul>"
                if due_this_week else '<p class="empty">Nothing due this week.</p>')

    ch = []
    if d["first_run"]:
        ch.append('<p class="empty">First run — baseline captured. Changes appear from next Friday.</p>')
    else:
        if d["new_assignments"]:
            ch.append('<h3>New assignments</h3><ul>' + "".join(assignment_row(snap, i, ticked=False) for i in d["new_assignments"]) + "</ul>")
        for aid, old in d["due_changes"]:
            ch.append('<h3>Due date changed</h3>' if "Due date changed" not in "".join(ch) else "")
            ch.append("<ul>" + assignment_row(snap, aid, ticked=False, note=f"was {esc(fmt_due(old))}") + "</ul>")
        if d["new_files"]:
            items = "".join(f'<li class="row"><div class="rowbody"><div class="rowtop">{chip(snap, snap["files"][f]["course"])}'
                            f'<a href="{esc(snap["files"][f]["url"])}">{esc(snap["files"][f]["title"])}</a></div>'
                            f'<div class="rowsub mono dim">{esc(snap["files"][f]["module"])}</div></div></li>'
                            for f in d["new_files"])
            ch.append(f"<h3>New files</h3><ul>{items}</ul>")
        if not any((d["new_assignments"], d["due_changes"], d["new_files"])):
            ch.append('<p class="empty">No changes since last Friday.</p>')
    changes_html = "".join(ch)
    changes_count = "—" if d["first_run"] else len(d["new_assignments"]) + len(d["due_changes"]) + len(d["new_files"])

    look_html = "".join(f'<h3>{lo.strftime("%d %b")} – {(lo + timedelta(days=6)).strftime("%d %b")}</h3><ul>'
                        + "".join(assignment_row(snap, i, ticked=False) for i in ids) + "</ul>"
                        for lo, ids in lookahead) or '<p class="empty">Nothing on the horizon yet.</p>'

    grades_html = ""
    if d["new_grades"]:
        rows = []
        for aid in d["new_grades"]:
            a = assignments[aid]
            score = f'{a["score"]:g}' + (f' / {a["points"]:g}' if a.get("points") else "")
            rows.append(f'<li class="row"><div class="rowbody"><div class="rowtop">{chip(snap, a["course"])}'
                        f'<a href="{esc(a["url"])}">{esc(a["name"])}</a><span class="score mono">{score}</span></div></div></li>')
        grades_html = "<ul>" + "".join(rows) + "</ul>"

    anns = sorted(snap["announcements"], key=lambda x: x.get("posted_at") or "", reverse=True)
    ann_html = "".join(f'<li class="row"><div class="rowbody"><div class="rowtop">{chip(snap, an["course"])}'
                       f'<a href="{esc(an["url"])}">{esc(an["title"])}</a></div>'
                       f'<div class="rowsub mono dim">{esc(fmt_due(an["posted_at"]))}</div>'
                       f'<p class="annbody">{esc(an["message"])}</p></div></li>'
                       for an in anns)
    ann_html = f"<ul>{ann_html}</ul>" if ann_html else ""

    stats = [("due in 7 days", len(due_this_week)), ("red flags", len(red_flags)),
             ("changes", changes_count), ("grades in", len(d["new_grades"]))]
    stats_html = "".join(f'<div class="stat"><span class="statnum mono">{n}</span><span class="statlbl">{esc(l)}</span></div>'
                         for l, n in stats)

    demo_banner = '<p class="demo">Sample data — connect your Canvas token for the real thing.</p>' if snap.get("demo") else ""

    body = f"""<title>Canvas Weekly</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sora:wght@600;700&family=Public+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>{CSS}</style>
<div class="page">
<header>
  <p class="kicker mono">week of {week_start.strftime("%d %b %Y")} · generated {now.strftime("%a %d %b, %I:%M %p").replace(" 0", " ")} SGT</p>
  <h1>Canvas Weekly</h1>
  {demo_banner}
  <div class="stats">{stats_html}</div>
</header>
{section("Red flags — past due, not submitted", len(red_flags), flags_html, tone="danger")}
{section("Due in the next 7 days", len(due_this_week), due_html)}
{section("Changed since last Friday", changes_count, changes_html)}
{section("Next 3 weeks", sum(len(i) for _, i in lookahead), look_html)}
{section("Grades released", len(d["new_grades"]), grades_html, tone="good")}
{section("Announcements, last 7 days", len(anns), ann_html)}
<footer class="mono dim">Canvas Weekly · updates every Friday morning</footer>
</div>
<script>{JS}</script>"""
    return body


CSS = """
:root{
  --bg:#F4F5F8; --surface:#FFFFFF; --ink:#1C2433; --muted:#5B6473; --line:#E2E5EC;
  --accent:#3450B2; --accent-soft:#E8ECF8; --danger:#B93A3A; --danger-soft:#F9ECEC;
  --good:#2E7D4F; --good-soft:#EAF4EE; --shadow:0 1px 2px rgba(28,36,51,.06);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#12151C; --surface:#1A1F2A; --ink:#E8EAF0; --muted:#98A0AF; --line:#2A3140;
    --accent:#8EA2E8; --accent-soft:#242C44; --danger:#E5786F; --danger-soft:#392323;
    --good:#6FBF8E; --good-soft:#1F3328; --shadow:none;
  }
}
:root[data-theme="dark"]{
  --bg:#12151C; --surface:#1A1F2A; --ink:#E8EAF0; --muted:#98A0AF; --line:#2A3140;
  --accent:#8EA2E8; --accent-soft:#242C44; --danger:#E5786F; --danger-soft:#392323;
  --good:#6FBF8E; --good-soft:#1F3328; --shadow:none;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:16px/1.55 "Public Sans",-apple-system,"Segoe UI",sans-serif}
.page{max-width:860px;margin:0 auto;padding:40px 20px 64px}
.mono{font-family:"IBM Plex Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}
.dim{color:var(--muted)}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
a:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
header{margin-bottom:28px}
.kicker{font-size:12px;color:var(--muted);letter-spacing:.04em;text-transform:uppercase;margin:0 0 6px}
h1{font-family:Sora,"Public Sans",sans-serif;font-size:32px;font-weight:700;margin:0 0 16px;text-wrap:balance}
.demo{background:var(--accent-soft);color:var(--accent);border-radius:6px;padding:8px 12px;
  font-size:13.5px;font-weight:500;display:inline-block;margin:0 0 16px}
.stats{display:flex;gap:10px;flex-wrap:wrap}
.stat{background:var(--surface);border:1px solid var(--line);border-radius:8px;
  padding:10px 16px;display:flex;flex-direction:column;min-width:104px;box-shadow:var(--shadow)}
.statnum{font-size:22px;font-weight:500}
.statlbl{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
section{background:var(--surface);border:1px solid var(--line);border-radius:10px;
  padding:18px 20px;margin-bottom:16px;box-shadow:var(--shadow)}
section.danger{border-left:3px solid var(--danger)}
section.good{border-left:3px solid var(--good)}
h2{display:flex;align-items:baseline;gap:10px;margin:0 0 8px}
.eyebrow{font-family:Sora,sans-serif;font-size:14px;font-weight:600;letter-spacing:.02em}
section.danger .eyebrow{color:var(--danger)}
section.good .eyebrow{color:var(--good)}
.count{font-size:12.5px;color:var(--muted)}
h3{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
  margin:16px 0 4px;font-weight:600}
ul{list-style:none;margin:0;padding:0}
.row{display:flex;gap:12px;padding:10px 0;border-top:1px solid var(--line);align-items:flex-start}
ul li:first-child.row{border-top:none}
.row input[type=checkbox]{margin-top:4px;width:16px;height:16px;accent-color:var(--accent);flex:none}
.rowbody{min-width:0;flex:1}
.rowtop{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.rowtop a{font-weight:500;color:var(--ink)}
.row.done .rowtop a{text-decoration:line-through;color:var(--muted)}
.rowsub{font-size:12.5px;color:var(--muted);margin-top:2px}
.chip{background:var(--accent-soft);color:var(--accent);border-radius:4px;
  font:500 11.5px/1.6 "IBM Plex Mono",monospace;padding:1px 7px;flex:none}
.note{font-size:12px;color:var(--danger);font-style:italic}
.score{margin-left:auto;color:var(--good);font-weight:500}
.annbody{font-size:13.5px;color:var(--muted);margin:4px 0 0;max-width:65ch}
.empty{color:var(--muted);font-size:14px;margin:6px 0}
footer{margin-top:32px;font-size:12px;text-align:center}
@media (prefers-reduced-motion: no-preference){
  section{transition:border-color .15s}
}
"""

JS = """
document.querySelectorAll('input[data-tick]').forEach(function(box){
  var key = 'tick-' + box.dataset.tick;
  try { if (localStorage.getItem(key) === '1') { box.checked = true; box.closest('.row').classList.add('done'); } } catch(e){}
  box.addEventListener('change', function(){
    box.closest('.row').classList.toggle('done', box.checked);
    try { box.checked ? localStorage.setItem(key,'1') : localStorage.removeItem(key); } catch(e){}
  });
});
"""


# ---------------------------------------------------------------- demo data

def demo_snapshots():
    now = datetime.now(SGT)

    def iso(days, hour=23, minute=59):
        return (now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                + timedelta(days=days)).astimezone(timezone.utc).isoformat()

    courses = {"1": {"code": "CS2030", "name": "Programming Methodology II"},
               "2": {"code": "CS2105", "name": "Computer Networks"},
               "3": {"code": "BT4301", "name": "Business Analytics Solutions"},
               "4": {"code": "IS3109", "name": "AI for Business"}}
    A = lambda c, n, due, pts, sub=False, sc=None, ga=None, miss=False: {
        "course": c, "name": n, "due_at": due, "points": pts, "url": "https://canvas.nus.edu.sg/",
        "submitted": sub, "missing": miss, "score": sc, "graded_at": ga}
    cur = {"generated_at": now.isoformat(), "demo": True, "courses": courses, "assignments": {
        "101": A("1", "Lab 3 — Streams and Optionals", iso(2), 10),
        "102": A("2", "Assignment 1 — Socket Programming", iso(4, 16, 0), 15),
        "103": A("4", "Case Brief: Agentic AI in Retail Banking", iso(5), 8),
        "104": A("3", "Tutorial 2 Quiz", iso(-3), 5, miss=True),
        "105": A("1", "Lab 4 — Generics", iso(9), 10),
        "106": A("2", "Quiz 2 — Transport Layer", iso(11, 20, 0), 6),
        "107": A("3", "Group Project Milestone 1", iso(16, 18, 0), 20),
        "108": A("4", "Midterm — in lecture", iso(19, 12, 0), 30),
        "109": A("1", "Lab 2 — Immutability", iso(-6), 10, sub=True, sc=9, ga=iso(-1)),
        "110": A("2", "Quiz 1 — Intro and HTTP", iso(-9), 6, sub=True, sc=5.5, ga=iso(-2)),
    }, "files": {
        "f1": {"course": "1", "title": "Lec 4 — Streams.pdf", "module": "Week 4", "url": "https://canvas.nus.edu.sg/"},
        "f2": {"course": "2", "title": "Tut 3 worksheet.pdf", "module": "Week 4", "url": "https://canvas.nus.edu.sg/"},
        "f3": {"course": "3", "title": "SGD dataset v2.csv", "module": "Project", "url": "https://canvas.nus.edu.sg/"},
    }, "announcements": [
        {"course": "2", "title": "Assignment 1 released — start early", "posted_at": iso(-2, 10, 0),
         "url": "https://canvas.nus.edu.sg/", "message": "Socket programming assignment is out. Autograder opens Monday; the last-day queue is always long, so submit a dry run early."},
        {"course": "4", "title": "Guest lecture Friday: LLM agents in DBS", "posted_at": iso(-4, 9, 0),
         "url": "https://canvas.nus.edu.sg/", "message": "We have a guest speaker from DBS AI Industrialisation this Friday. Attendance counts toward participation."},
    ]}
    prev = json.loads(json.dumps({k: v for k, v in cur.items() if k != "demo"}))
    del prev["assignments"]["102"]          # -> new assignment
    del prev["files"]["f1"]; del prev["files"]["f3"]   # -> new files
    prev["assignments"]["103"]["due_at"] = iso(3)      # -> due date change
    prev["assignments"]["109"]["score"] = None         # -> grade released
    prev["assignments"]["110"]["score"] = None
    return prev, cur


# ---------------------------------------------------------------- main

def main():
    demo = "--demo" in sys.argv
    if demo:
        prev, snap = demo_snapshots()
    else:
        token = load_token()
        if not token:
            print("No token at ~/.canvas_token — Canvas → Account → Settings → New Access Token, "
                  "then: echo '<token>' > ~/.canvas_token && chmod 600 ~/.canvas_token")
            sys.exit(2)
        snap = gather(token)
        prev = load_previous_snapshot()

    d = diff_snapshots(prev, snap)
    (ROOT / "report.html").write_text(render(snap, d))
    if not demo:
        SNAP_DIR.mkdir(exist_ok=True)
        (SNAP_DIR / f"{datetime.now(SGT):%Y-%m-%d}.json").write_text(json.dumps(snap))
    print(f"report.html written ({'demo' if demo else 'live'} mode)")


if __name__ == "__main__":
    main()
