#!/usr/bin/env bash
# Run one command under the heavy-run lock, declaring its TOTAL expected peak.
# Usage: run_locked.sh <total GiB> "<what>" <command> [args...]
# Waits (30 s polls, up to 4 h) until free memory covers total + 1 GiB floor + 4 GiB headroom
# and the lock is free; releases the lock on exit. PYTHONHASHSEED=0 is exported.
set -u
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
HS="$T/hs"
PY="$T/.r44-env/Scripts/python.exe"
GIB=$1; WHAT=$2; shift 2
export PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
cd "$HS/scripts"
for attempt in $(seq 1 480); do
  if "$PY" -B -I -c "import psutil,sys; sys.exit(0 if psutil.virtual_memory().available >= ($GIB+5)*2**30 else 1)"; then
    HEAVY_LOCK_WINPID=$(cat /proc/$$/winpid) "$PY" -B heavy_lock.py acquire $$ "$GIB" "heat reconstruction speed: $WHAT (TOTAL)" > /dev/null && break
  fi
  [ $attempt = 480 ] && { echo "gave up waiting for the lock or free memory"; exit 3; }
  sleep 30
done
trap '"$PY" -B heavy_lock.py release $$' EXIT
echo "$(date +%H:%M:%S) lock acquired ($GIB GiB TOTAL) after $attempt attempt(s)"
"$@"
status=$?
echo "$(date +%H:%M:%S) exit $status"
exit $status
