#!/usr/bin/env bash
# Per-process peak memory of each final-parity stage, one process at a time (memory rule, 16 Oct):
#   the IV2 rebuild (rebuild_next.py, growth candidate), one IV2 endpoint shard (replay_queries.py,
#   1 of 6), one IV1 endpoint shard, one IV2 surface shard with the grid file. Under the shared lock,
#   declared as a conservative TOTAL (one process at a time). PYTHONHASHSEED=0.
set -u
export PYTHONHASHSEED=0
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
D="$T/fidelity-integration-20261005"
G="$D/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
A="$D/heat-repair-20261007/heat-original-continued-20261013-r4.artifacts"
PY="$T/.r44-env/Scripts/python.exe"
OUT="$G/evidence/stage-memory-r1"
CAND="$T/gg/final-f2"
W2="0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000"
mkdir -p "$OUT"
cd "$G/scripts"
for attempt in $(seq 1 240); do   # wait for the shared lock, retrying once a minute (at most 4 h)
  HEAVY_LOCK_WINPID=$(cat /proc/$$/winpid) "$PY" -B heavy_lock.py acquire $$ 6.0 "geometry chat: per-stage memory measurement, ONE process at a time (TOTAL <= 6 GiB conservative)" > /dev/null && break
  [ $attempt = 240 ] && { echo "gave up waiting for the lock"; exit 3; }
  sleep 60
done
echo "lock acquired after $attempt attempt(s)"
trap '"$PY" -B heavy_lock.py release $$' EXIT
echo "start $(date +%H:%M:%S)"
"$PY" -B rebuild_next.py --transition iv2 --store "$G/work/r9-native-joined.copy.sqlite" --capture "$A/continuation-trace-inputs-02.json.gz" \
  --iv2-interval "$G/work/iv2-interval-only-r1.json.gz" --proposal "$A/differential-proposal-02.json" \
  --runtime "test:$CAND" --growth --output "$OUT/iv2-partition.json.gz" > "$OUT/iv2-rebuild.json" 2>&1
echo "rebuild exit $? $(date +%H:%M:%S)"
timeout 3600 "$PY" -B replay_queries.py --supports "$G/evidence/final-f2/iv2-supports.jsonl.gz" --runtime "test:$CAND" --cap-cpu 2 \
  --shard 0 --shards 6 --output "$OUT/iv2-endpoints-s0.jsonl" > "$OUT/iv2-endpoints-s0.log" 2>&1
echo "iv2 endpoint shard exit $? $(date +%H:%M:%S)"
timeout 3600 "$PY" -B replay_queries.py --supports "$G/work/iv1-supports.jsonl.gz" --runtime rc1 --cap-cpu 120 \
  --shard 0 --shards 6 --output "$OUT/iv1-endpoints-s0.jsonl" > "$OUT/iv1-endpoints-s0.log" 2>&1
echo "iv1 endpoint shard exit $? $(date +%H:%M:%S)"
timeout 3600 "$PY" -B replay_surfaces.py --supports "$G/work/iv2-supports.jsonl.gz" --partition "$G/work/iv2-partition-r1.grid.json.gz" \
  --interval "$G/work/iv2-interval-only-r1.json.gz" --stream-width $W2 --runtime rc1 --cap-cpu 2 --shard 0 --shards 60 \
  --output "$OUT/iv2-surfaces-s0.jsonl" > "$OUT/iv2-surfaces-s0.log" 2>&1
echo "iv2 surface shard exit $? $(date +%H:%M:%S)"
echo "end $(date +%H:%M:%S)"
