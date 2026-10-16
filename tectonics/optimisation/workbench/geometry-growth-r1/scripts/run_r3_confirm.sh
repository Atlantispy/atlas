#!/usr/bin/env bash
# After the queued final parity: the proved complementary-cut queries of the IV2 sample under
# r3 (mandatory reservation, digest over helper + call site) vs r2; numbers must be identical
# (bounds, leaves, work units, rule); only the certificate digest differs. PYTHONHASHSEED=0.
set -u
export PYTHONHASHSEED=0
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
R2="$G/evidence/cpcut-r2"
OUT="$G/evidence/cpcut-r3"
W2="0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000"
while ! grep -q '^end ' "$G/work/after-r2.log"; do sleep 20; done
mkdir -p "$OUT"
cd "$G/scripts"
"$PY" -B -I -c "
import glob, json, sys
rows = [json.loads(l) for p in sorted(glob.glob(sys.argv[1])) for l in open(p, encoding='utf8')]
proved = [dict(support_index=r['support_index'], cell=r['cell'], other=r.get('other'), constraint_name=r['constraint_name'])
          for r in rows if r.get('rule') == 'exact-zero-area-from-complementary-moving-cuts']
for i in range(3):
    with open(sys.argv[2] % i, 'x', encoding='utf8', newline='\n') as f:
        for row in proved[i::3]:
            f.write(json.dumps(row) + '\n')
print('proved', len(proved))
" "$R2/deep-cpcut2-wp23-s*.jsonl" "$OUT/proved-list-%d.jsonl"
pids=()
for i in 0 1 2; do
  timeout 3600 "$PY" -B replay_surfaces.py --supports "$G/work/iv2-supports.jsonl.gz" --partition "$G/work/iv2-partition-r1.json.gz" \
    --interval "$G/work/iv2-interval-only-r1.json.gz" --stream-width $W2 --runtime "test:$T/gg/cpcut-wp23-r3" --cap-cpu 120 \
    --kinds interface --only-list "$OUT/proved-list-$i.jsonl" --output "$OUT/proved-r3-s$i.jsonl" > "$OUT/proved-r3-s$i.log" 2>&1 &
  pids+=($!)
done
for p in "${pids[@]}"; do wait "$p"; done
"$PY" -B -I compare_surfaces.py --numbers --baseline "$R2/deep-cpcut2-wp23-s*.jsonl" --candidate "$OUT/proved-r3-s*.jsonl" > "$OUT/cmp-r2-r3-numbers.json"; echo "numbers exit $?"
echo "end $(date +%H:%M:%S)"
