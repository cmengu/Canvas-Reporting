# Canvas Weekly

Every Friday 8:00 am, pulls NUS Canvas and regenerates `report.html` — a local
webpage (no accounts, no hosting) that opens in your browser:

- **To-do** — every upcoming assignment as a tickable checklist, grouped by
  week and, within each week, by module. Anything that changed since last
  Friday is bracketed inline: `(new this week)`, `(was Thu 21 Aug)`. New
  lecture files land at the bottom of this tab.
- **Red flags** — past due, not submitted.
- **Grades** — scores released this week.
- **Announcements** — last 7 days across all modules.

Where a module uses weighted assignment groups in Canvas, each item also shows
its share of the final grade (e.g. `≈7.5% of grade`), computed as
`group weight × item points ÷ group total points`.

## Setup

1. Canvas → Account → Settings → **+ New Access Token**, then:
   ```sh
   echo '<token>' > ~/.canvas_token && chmod 600 ~/.canvas_token
   ```
2. Test a live run:
   ```sh
   python3 canvas_report.py && open report.html
   ```
   (`--demo` renders sample data without a token.)
3. The Friday schedule is a launchd job (`com.canvasreporting.weekly.plist`,
   installed in `~/Library/LaunchAgents`). Re-install after edits with:
   ```sh
   cp com.canvasreporting.weekly.plist ~/Library/LaunchAgents/
   launchctl unload ~/Library/LaunchAgents/com.canvasreporting.weekly.plist 2>/dev/null
   launchctl load ~/Library/LaunchAgents/com.canvasreporting.weekly.plist
   ```

## How it works

- `canvas_report.py` — fetches courses, assignment groups (for grade
  weights), assignments (+ your submissions), module files, and announcements
  via the Canvas REST API (stdlib only, no pip installs); diffs against the
  previous snapshot in `snapshots/`; renders `report.html`.
- `run_weekly.sh` — runs the fetch, then opens `report.html`. If the fetch
  fails (or there's no token) it keeps the last good report.
- Ticks and the active tab live in your browser's localStorage, so they
  survive the weekly regeneration.

Everything stays on your machine: the token (`~/.canvas_token`, chmod 600,
never committed) is sent only to `canvas.nus.edu.sg` over HTTPS, and the
report and snapshots are gitignored local files. The Mac must be awake at
8 am Friday for launchd to fire (it catches up at next wake otherwise).
