#!/usr/bin/env bash
# Wait (cooperatively) for the shared heavy-run lock, then run final parity f2 under it.
# Retries once a minute; gives up after 6 hours. Never touches another owner's lock or process.
set -u
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
cd "$G/scripts"
for attempt in $(seq 1 360); do
  if HEAVY_LOCK_WINPID=$(cat /proc/$$/winpid) "$PY" -B heavy_lock.py acquire $$ 4.0 "geometry chat: final parity f2 (IV1/IV2 rebuilds with growth; 6-shard replays)" > /dev/null; then
    trap '"$PY" -B heavy_lock.py release $$' EXIT
    echo "lock acquired $(date +%H:%M:%S) after $attempt attempts"
    bash run_final_parity.sh f2 > "$G/work/final-f2.log" 2>&1
    echo "final parity f2 exit $? $(date +%H:%M:%S)"
    exit 0
  fi
  sleep 60
done
echo "gave up waiting for the lock $(date +%H:%M:%S)"
exit 3
