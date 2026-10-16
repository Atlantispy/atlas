#!/usr/bin/env bash
# IV2 fixed-wall + moving-interface bounded replay under the chosen runtime, 6 shards,
# under the cooperative heavy-run lock (combined with this chat's concurrent work).
set -u
export PYTHONHASHSEED=0   # production pins it; interface work units follow set order
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
RT="$1"; TAG="$2"; CAP="$3"
cd "$G/scripts"
HEAVY_LOCK_WINPID=$(cat /proc/$$/winpid) "$PY" -B heavy_lock.py acquire $$ 3.0 "geometry chat: IV2 wall/interface replay (6 shards) + IV2 rebuild" || { echo "lock busy; not started"; exit 3; }
trap '"$PY" -B heavy_lock.py release $$' EXIT
pids=()
for i in 0 1 2 3 4 5; do
  timeout 10800 "$PY" -B replay_surfaces.py --supports "$G/work/iv2-supports.jsonl.gz" --partition "$G/work/iv2-partition-r1.json.gz" \
    --interval "$G/work/iv2-interval-only-r1.json.gz" --stream-width 0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000 \
    --runtime "$RT" --output "$G/evidence/surfaces-iv2-$TAG-s$i.jsonl" --cap-cpu "$CAP" --shard $i --shards 6 \
    > "$G/work/surfaces-iv2-$TAG-s$i.log" 2>&1 &
  pids+=($!)
done
echo "started ${pids[*]} $(date +%H:%M:%S)"
for p in "${pids[@]}"; do wait "$p"; echo "shard $p exit $? $(date +%H:%M:%S)"; done
