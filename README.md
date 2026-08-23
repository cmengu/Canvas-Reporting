# Canvas Weekly

Every Friday 8:00 am, pulls NUS Canvas and republishes a one-page report to a
fixed Claude artifact URL: what's due in the next 7 days (tickable checklist),
red flags (past due, unsubmitted), what changed since last Friday (new
assignments, due-date changes, new files), a 3-week lookahead, grades released,
and a 7-day announcements digest.

**Report:** https://claude.ai/code/artifact/47e359b4-6ca8-4012-ac27-7b0db065bfac

## Setup

1. Canvas → Account → Settings → **+ New Access Token**, then:
   ```sh
   echo '<token>' > ~/.canvas_token && chmod 600 ~/.canvas_token
   ```
2. Test a live run:
   ```sh
   python3 canvas_report.py && open report.html
   ```
3. The Friday schedule is a launchd job (`com.canvasreporting.weekly.plist`,
   installed in `~/Library/LaunchAgents`). Re-install after edits with:
   ```sh
   cp com.canvasreporting.weekly.plist ~/Library/LaunchAgents/
   launchctl unload ~/Library/LaunchAgents/com.canvasreporting.weekly.plist 2>/dev/null
   launchctl load ~/Library/LaunchAgents/com.canvasreporting.weekly.plist
   ```

## How it works

- `canvas_report.py` — fetches courses, assignments (+ your submissions),
  module files, and announcements via the Canvas REST API (stdlib only, no
  pip installs); diffs against the previous snapshot in `snapshots/`; renders
  `report.html`. `--demo` renders sample data without a token.
- `run_weekly.sh` — runs the fetch, then uses headless Claude (`claude -p`)
  to republish `report.html` to the same artifact URL (from `config.json`).
- Checklist ticks live in your browser's localStorage keyed by assignment id,
  so they survive the weekly republish.
- Without a token the script exits with code 2 and the publish step is
  skipped, so a missing token never clobbers the report.

Notes: the Mac must be awake at 8 am Friday for launchd to fire (it runs at
next wake otherwise on modern macOS via the missed-job catch-up). Token is
never committed — `snapshots/`, logs, and `report.html` are gitignored.
