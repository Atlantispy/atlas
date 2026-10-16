#!/usr/bin/env bash
# D-j proof (replaces run_workers_parity_r3.sh, whose copied r2 stores were bound to the old package
# digest and would have stopped every arm at 'no compatible observations'; refuter 16 Oct).
# Runtime gg/workers6-r6 = chain + workers_six + workers_six_rolling_interfaces (with the
# minimum_job_seconds guard) + endpoint clamp. Each set: a serial pass on THIS runtime writes the
# timing store; each arm starts from its own copy. IV2 (1-in-20 sample): serial, w2 control, w4, w6.
# IV1: serial, w4, w6. summarise_dj.py applies the checks. Lock 4 GiB TOTAL after a free-memory
# check. PYTHONHASHSEED=0.
set -u
export PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
OUT="$G/evidence/workers-dj"
RT="test:$T/gg/workers6-r6"
W1="0x2f00cbfcd7c08aad8918ab19af 0x4e3bbe22f900000000000000000000000000000000000"
W2="0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000"
mkdir -p "$OUT"
cd "$G/scripts"
for attempt in $(seq 1 480); do
  if "$PY" -B -I -c "import psutil,sys; sys.exit(0 if psutil.virtual_memory().available >= 9*2**30 else 1)"; then
    HEAVY_LOCK_WINPID=$(cat /proc/$$/winpid) "$PY" -B heavy_lock.py acquire $$ 4.0 "geometry chat: D-j proof, ONE arm at a time, parent + up to 6 workers (TOTAL)" > /dev/null && break
  fi
  [ $attempt = 480 ] && { echo "gave up waiting for the lock or free memory"; exit 3; }
  sleep 30
done
trap '"$PY" -B heavy_lock.py release $$' EXIT
echo "lock acquired after $attempt attempt(s) $(date +%H:%M:%S)"
iv2=(--supports "$G/evidence/final-f2/iv2-supports.jsonl.gz" --partition "$G/evidence/final-f1/iv2-partition.grid.json.gz" --interval "$G/work/iv2-interval-only-r1.json.gz" --stream-width $W2 --shard 0 --shards 20)
iv1=(--supports "$G/work/iv1-supports.jsonl.gz" --partition "$G/work/next-iv1-rc1-r1.grid.json.gz" --interval "$G/work/iv1-interval-r1.json.gz" --stream-width $W1 --minimum-seconds 1)
for set in iv2 iv1; do
  if [ $set = iv2 ]; then args=("${iv2[@]}"); arms="2 4 6"; else args=("${iv1[@]}"); arms="4 6"; fi
  "$PY" -B parallel_parity.py --runtime "$RT" "${args[@]}" --mode serial --workers 1 --profile-store "$OUT/$set-store" --output "$OUT/$set-serial.json" > "$OUT/$set-serial.log" 2>&1
  echo "done $set serial $(date +%H:%M:%S)"
  for n in $arms; do
    cp -r "$OUT/$set-store" "$OUT/$set-store-w$n"
    "$PY" -B parallel_parity.py --runtime "$RT" "${args[@]}" --mode auto --workers $n --profile-store "$OUT/$set-store-w$n" --output "$OUT/$set-w$n.json" > "$OUT/$set-w$n.log" 2>&1
    echo "done $set w$n $(date +%H:%M:%S)"
  done
done
"$PY" -B -I summarise_dj.py "$OUT" "$G/evidence/workers-six-r2" > "$OUT/summary.txt"; echo "summary exit $?"
cat "$OUT/summary.txt"
echo "end $(date +%H:%M:%S)"
