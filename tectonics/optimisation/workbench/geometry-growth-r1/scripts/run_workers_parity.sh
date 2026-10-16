#!/usr/bin/env bash
# Worker-cap lift parity: RC1's router with automatic workers at 1, 2, 4 and 6 (candidate runtime +
# workers_six). Each set: a serial pass writes the timing store; each worker arm starts from its own
# copy. Records and streams must be byte-identical across serial, 1, 2, 4 and 6.
#   IV1: all supports, minimum_seconds 1 (IV1 surfaces are cheap; this makes the batches engage).
#   IV2: candidate partition, supports with index % 20 == 0, default policy thresholds.
# One arm at a time. Memory (measured): parent < 0.5 GB, a batch child about 0.2 GB, so 6 workers
# about 2 GB; the lock declares 4 GiB TOTAL. PYTHONHASHSEED=0.
set -u
export PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
OUT="$G/evidence/workers-six-r1"
RT="test:$T/gg/workers6-r1"
W1="0x2f00cbfcd7c08aad8918ab19af 0x4e3bbe22f900000000000000000000000000000000000"
W2="0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000"
mkdir -p "$OUT"
cd "$G/scripts"
for attempt in $(seq 1 240); do
  HEAVY_LOCK_WINPID=$(cat /proc/$$/winpid) "$PY" -B heavy_lock.py acquire $$ 4.0 "geometry chat: worker-count parity, ONE arm at a time, parent + up to 6 workers (TOTAL)" > /dev/null && break
  [ $attempt = 240 ] && { echo "gave up waiting for the lock"; exit 3; }
  sleep 60
done
trap '"$PY" -B heavy_lock.py release $$' EXIT
echo "lock acquired after $attempt attempt(s) $(date +%H:%M:%S)"
run_set () {  # name supports grid interval width extra...
  local name=$1 sup=$2 grid=$3 iv=$4 w=$5; shift 5
  local common=(--runtime "$RT" --supports "$sup" --partition "$grid" --interval "$iv" --stream-width $w "$@")
  "$PY" -B parallel_parity.py "${common[@]}" --mode serial --workers 1 --profile-store "$OUT/$name-store" --output "$OUT/$name-serial.json" > "$OUT/$name-serial.log" 2>&1
  echo "done $name serial $(date +%H:%M:%S)"
  for n in 1 2 4 6; do
    cp -r "$OUT/$name-store" "$OUT/$name-store-w$n"
    "$PY" -B parallel_parity.py "${common[@]}" --mode auto --workers $n --profile-store "$OUT/$name-store-w$n" --output "$OUT/$name-w$n.json" > "$OUT/$name-w$n.log" 2>&1
    echo "done $name w$n $(date +%H:%M:%S)"
  done
}
run_set iv1 "$G/work/iv1-supports.jsonl.gz" "$G/work/next-iv1-rc1-r1.grid.json.gz" "$G/work/iv1-interval-r1.json.gz" "$W1" --minimum-seconds 1
run_set iv2 "$G/evidence/final-f2/iv2-supports.jsonl.gz" "$G/evidence/final-f1/iv2-partition.grid.json.gz" "$G/work/iv2-interval-only-r1.json.gz" "$W2" --shard 0 --shards 20
"$PY" -B -I -c "
import json, sys, glob
ok = True
for name in ('iv1', 'iv2'):
    rows = {}
    for arm in ('serial', 'w1', 'w2', 'w4', 'w6'):
        d = json.load(open(sys.argv[1] + '/%s-%s.json' % (name, arm)))
        bw = d['decision'].get('batch_workers') or {}
        rows[arm] = (d['records_sha256'], d['streams_sha256'], d['records'], d['error'], d['wall_s'], d['parent_cpu_s'],
                     bw.get('started'), bw.get('jobs'), bw.get('adopted'), bw.get('peak_child_rss'))
    base = rows['serial'][:2]
    for arm, r in rows.items():
        same = r[:2] == base and r[3] is None
        ok &= same
        print(name, arm.ljust(6), 'IDENTICAL' if same else 'DIFFERS', 'records', r[2], 'error', r[3], 'wall_s', r[4],
              'parent_cpu_s', r[5], 'workers started', r[6], 'jobs', r[7], 'adopted', r[8], 'peak child rss', r[9])
print('ALL IDENTICAL' if ok else 'PARITY FAILED')
sys.exit(0 if ok else 1)
" "$OUT" > "$OUT/summary.txt"; echo "summary exit $?"
cat "$OUT/summary.txt"
echo "end $(date +%H:%M:%S)"
