#!/usr/bin/env bash
# Sharded replay of every query in a supports file under a chosen runtime.
# Usage: run_replay_set.sh <supports.jsonl.gz> <runtime> <shards> <cap> <tag>
set -u
export PYTHONHASHSEED=0   # production pins it; interface work units follow set order
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
IN="$1"; RT="$2"; SHARDS="$3"; CAP="$4"; TAG="$5"
"$PY" -B -c "import psutil,sys; a=psutil.virtual_memory().available; print('available GiB %.2f' % (a/2**30)); sys.exit(0 if a >= (1+0.3*$SHARDS+1)*2**30 else 3)" || { echo 'not enough free memory; not started'; exit 3; }
pids=()
for ((i=0; i<SHARDS; i++)); do
  timeout 7200 "$PY" -B "$G/scripts/replay_queries.py" --supports "$IN" --runtime "$RT" \
    --output "$G/evidence/replay-$TAG-s$i.jsonl" --cap-cpu "$CAP" --shard "$i" --shards "$SHARDS" \
    > "$G/work/replay-$TAG-s$i.log" 2>&1 &
  pids+=($!)
done
echo "started ${pids[*]} $(date +%H:%M:%S)"
for p in "${pids[@]}"; do wait "$p"; echo "shard pid $p exit $? $(date +%H:%M:%S)"; done
