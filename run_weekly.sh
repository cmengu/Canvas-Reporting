#!/bin/zsh
# Friday-morning job: regenerate the report, then republish the artifact.
cd "$(dirname "$0")"
echo "--- run $(date) ---" >> weekly.log

/usr/bin/env python3 canvas_report.py >> weekly.log 2>&1 || { echo "fetch failed or no token; skipping publish" >> weekly.log; exit 0; }

URL=$(/usr/bin/env python3 -c "import json; print(json.load(open('config.json')).get('artifact_url',''))")
if [ -n "$URL" ]; then
  "$HOME/.local/bin/claude" -p "Publish $HOME/Canvas-Reporting/report.html with the Artifact tool, updating the existing artifact by passing url: $URL. Favicon 📚. Do nothing else." \
    --allowedTools "Read,Artifact" >> weekly.log 2>&1
fi
