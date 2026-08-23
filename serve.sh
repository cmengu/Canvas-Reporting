#!/bin/zsh
# Serve the report at http://localhost:8787 (localhost only).
cd "$(dirname "$0")"
exec /usr/bin/env python3 -m http.server 8787 --bind 127.0.0.1
