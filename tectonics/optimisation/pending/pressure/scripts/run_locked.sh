#!/usr/bin/env bash
# Run one command under the heavy-run lock, declaring its TOTAL expected peak.
# Copied from G/scripts/run_locked.sh for the "Pressure stage speed" chat (T/ps).
# Usage: run_locked.sh <total GiB> "<what>" <command> [args...]
# Waits (30 s polls, up to 8 h) until free memory covers total + 1 GiB floor + 4 GiB headroom
# and the lock is free; releases the lock on exit. PYTHONHASHSEED=0 is exported.
# Lock order (coordinator, 16 Oct): d2 parity, then the geometry chat's D-j proof, then this.
# So this wrapper takes a free lock only after it has seen the D-j proof hold it (or the lock
# has stayed free for 15 min, i.e. nobody is queued), and after a 90 s courtesy pause that lets
# any 30 s poller queued ahead of us take it first.
set -u
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
LOCK="$T/fidelity-integration-20261005/heavy-run.lock.json"
PS="$T/ps"
PY="$T/.r44-env/Scripts/python.exe"
GIB=$1; WHAT=$2; shift 2
export PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
cd "$PS/scripts"
seen_dj=0; free_since=""
for attempt in $(seq 1 960); do
  if [ -f "$LOCK" ]; then
    grep -q 'D-j proof' "$LOCK" 2>/dev/null && seen_dj=1
    free_since=""
  else
    [ -z "$free_since" ] && free_since=$(date +%s)
    waited=$(( $(date +%s) - free_since ))
    if [ $seen_dj = 1 ] || [ $waited -ge 900 ]; then
      sleep 90
      if [ ! -f "$LOCK" ] && "$PY" -B -I -c "import psutil,sys; sys.exit(0 if psutil.virtual_memory().available >= ($GIB+5)*2**30 else 1)"; then
        HEAVY_LOCK_WINPID=$(cat /proc/$$/winpid) "$PY" -B heavy_lock.py acquire $$ "$GIB" "pressure chat: $WHAT (TOTAL)" > /dev/null && break
      fi
    fi
  fi
  [ $attempt = 960 ] && { echo "$(date +%H:%M:%S) gave up waiting for the lock or free memory"; exit 3; }
  sleep 30
done
trap '"$PY" -B heavy_lock.py release $$' EXIT
echo "$(date +%H:%M:%S) lock acquired ($GIB GiB TOTAL) after $attempt attempt(s); seen D-j=$seen_dj"
"$@"
status=$?
echo "$(date +%H:%M:%S) exit $status"
exit $status
