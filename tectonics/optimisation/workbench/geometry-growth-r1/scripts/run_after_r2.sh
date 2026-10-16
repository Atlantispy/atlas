#!/usr/bin/env bash
# Queued after the cpcut r2 chain: (1) the one-command final parity for the whole candidate
# (growth -> WP20 -> items_off -> WP23 rotation -> complementary cut + adoption) under the
# shared heavy-run lock; (2) the all-query IV2 interface projection for that candidate:
# every candidate sample interface capped at 2 s rerun at 120 s, and the exact interval-2
# interface job count of the candidate partition. PYTHONHASHSEED=0.
set -u
export PYTHONHASHSEED=0
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
TAG=f1
F="$G/evidence/final-$TAG"
W2="0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000"
while ! grep -q '^end ' "$G/work/cpcut2-parity.log"; do sleep 20; done
cd "$G/scripts"
HEAVY_LOCK_WINPID=$(cat /proc/$$/winpid) "$PY" -B heavy_lock.py acquire $$ 4.0 "geometry chat: final parity (IV1/IV2 rebuilds with growth; 6-shard replays) + candidate projection" || { echo "lock busy; not started"; exit 3; }
trap '"$PY" -B heavy_lock.py release $$' EXIT
echo "final parity start $(date +%H:%M:%S)"
bash run_final_parity.sh $TAG > "$G/work/final-$TAG.log" 2>&1
echo "final parity exit $? $(date +%H:%M:%S)"
# Candidate projection.
"$PY" -B -I -c "
import glob, json, sys
rows = [json.loads(l) for p in sorted(glob.glob(sys.argv[1])) for l in open(p, encoding='utf8')]
capped = [dict(support_index=r['support_index'], cell=r['cell'], other=r.get('other'), constraint_name=r['constraint_name'])
          for r in rows if r.get('kind') == 'interface' and r['status'] == 'capped']
for i in range(6):
    with open(sys.argv[2] % i, 'x', encoding='utf8', newline='\n') as f:
        for row in capped[i::6]:
            f.write(json.dumps(row) + '\n')
print('candidate capped interfaces', len(capped))
" "$F/cand-iv2-surfaces-s*.jsonl" "$F/capped-list-%d.jsonl"
pids=()
for i in 0 1 2 3 4 5; do
  timeout 5400 "$PY" -B replay_surfaces.py --supports "$F/iv2-supports.jsonl.gz" --partition "$F/iv2-partition.json.gz" \
    --interval "$G/work/iv2-interval-only-r1.json.gz" --stream-width $W2 --runtime "test:$T/gg/final-$TAG" --cap-cpu 120 \
    --kinds interface --only-list "$F/capped-list-$i.jsonl" --output "$F/deep-cand-s$i.jsonl" > "$F/deep-cand-s$i.log" 2>&1 &
  pids+=($!)
done
for p in "${pids[@]}"; do wait "$p"; done
echo "deep candidate done $(date +%H:%M:%S)"
pids=()
for i in 0 1 2 3 4 5; do
  "$PY" -B replay_surfaces.py --supports "$F/iv2-supports.jsonl.gz" --partition "$F/iv2-partition.json.gz" \
    --interval "$G/work/iv2-interval-only-r1.json.gz" --stream-width $W2 --runtime "test:$T/gg/final-$TAG" --count-only \
    --shard $i --shards 6 --output "$F/count-cand-s$i.jsonl" > "$F/count-cand-s$i.log" 2>&1 &
  pids+=($!)
done
for p in "${pids[@]}"; do wait "$p"; done
TOTAL=$("$PY" -B -I -c "
import glob, json, sys
n = 0
for p in glob.glob(sys.argv[1]):
    for l in open(p, encoding='utf8'):
        r = json.loads(l)
        n += sum(v for k, v in r.get('job_counts', {}).items() if k.startswith('interface/'))
print(n)
" "$F/count-cand-s*.jsonl")
echo "candidate interval-2 interface jobs $TOTAL"
"$PY" -B -I project_interfaces.py --total-jobs "$TOTAL" --arm candidate "$F/cand-iv2-surfaces-s*.jsonl" "$F/deep-cand-s*.jsonl" > "$F/projection-candidate.json"
echo "end $(date +%H:%M:%S)"
