#!/usr/bin/env bash
# run_final_parity.sh under the heavy-run lock, with every output line time-stamped (per-stage
# times = gaps between lines; each shard log also carries its own seconds and process memory).
# Usage: run_final_parity_locked.sh <tag> <candidate src> [<candidate helpers>]
# With a helpers folder, only the candidate composition loads it (rc1_env RC1_ENV_TEST_HELPERS);
# the RC1+items_off reference keeps composed-r1/helpers.
# Memory (measured, HANDOFF section 4): six shards of about 0.27 GB each, total about 1.6 GB; the
# lock declares 2 GiB TOTAL after a free-memory check (total + 1 GiB floor + 4 GiB headroom).
set -u
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
TAG=$1; CAND=$2; HELP=${3:-}
[ -n "$HELP" ] && export RC1_ENV_TEST_HELPERS="$CAND|$HELP"
cd "$G/scripts"
for attempt in $(seq 1 480); do
  if "$PY" -B -I -c "import psutil,sys; sys.exit(0 if psutil.virtual_memory().available >= 7*2**30 else 1)"; then
    HEAVY_LOCK_WINPID=$(cat /proc/$$/winpid) "$PY" -B heavy_lock.py acquire $$ 2.0 "geometry chat: final parity $TAG (6 shards TOTAL; Step 10 dry run)" > /dev/null && break
  fi
  [ $attempt = 480 ] && { echo "gave up waiting for the lock or free memory"; exit 3; }
  sleep 30
done
trap '"$PY" -B heavy_lock.py release $$' EXIT
echo "$(date +%H:%M:%S) lock acquired after $attempt attempt(s); available $("$PY" -B -I -c "import psutil; print(round(psutil.virtual_memory().available/2**30,1))") GiB"
bash run_final_parity.sh "$TAG" "$CAND" 2>&1 | while IFS= read -r line; do echo "$(date +%H:%M:%S) $line"; done
status=${PIPESTATUS[0]}
echo "$(date +%H:%M:%S) final parity exit $status"
exit $status
