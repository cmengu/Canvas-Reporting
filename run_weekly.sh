#!/bin/zsh
# Friday-morning job: regenerate the report webpage and open it.
cd "$(dirname "$0")"
echo "--- run $(date) ---" >> weekly.log

/usr/bin/env python3 canvas_report.py >> weekly.log 2>&1 || { echo "fetch failed or no token; keeping last report" >> weekly.log; exit 0; }

if curl -s -o /dev/null --max-time 1 http://localhost:8787; then
  /usr/bin/open http://localhost:8787
else
  /usr/bin/open index.html
fi
