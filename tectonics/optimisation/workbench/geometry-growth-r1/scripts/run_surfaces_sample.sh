#!/usr/bin/env bash
# Bounded 1-in-10 support sample of IV2 fixed-wall + moving-interface queries:
# shards 0,10,...,50 of 60, one process each (6 x ~150 MB, under 2 GiB, no lock).
# Usage: run_surfaces_sample.sh <supports.jsonl.gz> <partition.json.gz> <runtime> <cap> <tag>
set -u
export PYTHONHASHSEED=0   # production pins it; interface work units follow set order
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
SUP="$1"; PART="$2"; RT="$3"; CAP="$4"; TAG="$5"
cd "$G/scripts"
pids=()
for i in 0 10 20 30 40 50; do
  timeout 5400 "$PY" -B replay_surfaces.py --supports "$SUP" --partition "$PART" \
    --interval "$G/work/iv2-interval-only-r1.json.gz" --stream-width 0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000 \
    --runtime "$RT" --output "$G/evidence/surfaces-sample-$TAG-s$i.jsonl" --cap-cpu "$CAP" --shard $i --shards 60 \
    > "$G/work/surfaces-sample-$TAG-s$i.log" 2>&1 &
  pids+=($!)
done
echo "started $TAG $(date +%H:%M:%S)"
for p in "${pids[@]}"; do wait "$p"; done
echo "done $TAG $(date +%H:%M:%S)"
