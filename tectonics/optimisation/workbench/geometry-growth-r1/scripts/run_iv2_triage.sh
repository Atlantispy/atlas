#!/usr/bin/env bash
# T triage: every saved IV2 endpoint query under RC1's production route, sharded by
# support index, with a per-query CPU cap. Each shard writes its own JSONL.
set -u
export PYTHONHASHSEED=0   # production pins it; interface work units follow set order
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
SHARDS="$1"; CAP="$2"; TAG="$3"
pids=()
for ((i=0; i<SHARDS; i++)); do
  timeout 14400 "$PY" -B "$G/scripts/replay_queries.py" --supports "$G/work/iv2-supports.jsonl.gz" \
    --output "$G/evidence/triage-iv2-rc1-$TAG-s$i.jsonl" --cap-cpu "$CAP" --shard "$i" --shards "$SHARDS" \
    > "$G/work/triage-iv2-rc1-$TAG-s$i.log" 2>&1 &
  pids+=($!)
done
echo "started ${pids[*]} $(date +%H:%M:%S)"
for p in "${pids[@]}"; do wait "$p"; echo "shard pid $p exit $? $(date +%H:%M:%S)"; done
