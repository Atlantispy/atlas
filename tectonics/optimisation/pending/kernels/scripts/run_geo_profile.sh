#!/usr/bin/env bash
# cProfile of the composed candidate (test:gg/final-f2) on 16 stratified hard IV2 interfaces
# (every 13th of the 216-query deep set, 141.9 CPU-s unprofiled in jets-r1). One process.
# Usage: run_geo_profile.sh <tag>
set -u
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
F2="$G/evidence/final-f2"
W2="0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000"
TAG=$1
export PYTHONHASHSEED=0
cd "$G/scripts"
"$PY" -B replay_surfaces.py --supports "$F2/iv2-supports.jsonl.gz" --partition "$F2/iv2-partition.json.gz" \
  --interval "$G/work/iv2-interval-only-r1.json.gz" --stream-width $W2 --runtime "test:$T/gg/final-f2" \
  --cap-cpu 120 --kinds interface --only-list "$T/ck/geo/deep16.jsonl" \
  --output "$T/ck/geo/$TAG.jsonl" --profile "$T/ck/geo/$TAG.prof" > "$T/ck/geo/$TAG.log" 2>&1
status=$?
echo "profile exit $status"
exit $status
