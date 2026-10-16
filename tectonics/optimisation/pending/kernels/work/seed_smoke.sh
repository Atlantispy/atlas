#!/usr/bin/env bash
# Seed-0 smoke for the q06 route check (job_h3r3.sh's inline snippet, extracted byte-equal) on l3r3.
CK="$(cygpath -m "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)")"; PY="$(dirname "$CK")/.r44-env/Scripts/python.exe"
cd "$CK/work" || exit 2
PYTHONHASHSEED=0 "$PY" -B -s -P route_snippet.py seed0-route.json "$CK/l3r3"; echo "seed0 exit $?: $(tr -d '\n ' < seed0-route.json | cut -c1-200)"
env -u PYTHONHASHSEED "$PY" -B -s -P route_snippet.py random-route.json "$CK/l3r3"; echo "random-seed exit $? (expect 1, refused)"; [ -e random-route.json ] && echo "UNEXPECTED: random-route.json written"
exit 0
