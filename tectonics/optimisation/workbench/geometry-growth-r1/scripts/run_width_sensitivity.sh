#!/usr/bin/env bash
# Interval-3 forecast input: the cost of an 8x tighter stream width (IV1 -> IV2 was 8x), geometry
# held fixed. Candidate + jets runtime on the IV2 candidate partition:
#   hard set   every candidate-capped sample interface (216), at W2 (have: jets-r1) and at W2/8;
#   easy set   every 15th settled sample interface (about 280), at W2 and at W2/8.
# 3 processes (< 2 GiB, no lock), cap 300 s. PYTHONHASHSEED=0.
set -u
export PYTHONHASHSEED=0
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
F="$G/evidence/final-f1"
OUT="$G/evidence/width-sensitivity-r1"
RT="test:$T/gg/cand-jets-r1"
W2N=0xef6aca6e197d9db2f69d62da0b
W2D=0xc6ae51dc48000000000000000000000000000000000000
W3D=$("$PY" -I -c "print(hex(int('$W2D',16)*8))")
mkdir -p "$OUT"
cd "$G/scripts"
"$PY" -B -I -c "
import glob, json, sys
rows = [json.loads(l) for p in sorted(glob.glob(sys.argv[1])) for l in open(p, encoding='utf8')]
hard = [r for r in rows if r.get('kind') == 'interface' and r['status'] == 'capped']
easy = [r for r in rows if r.get('kind') == 'interface' and r['status'] == 'met'][::15]
sel = [dict(support_index=r['support_index'], cell=r['cell'], other=r.get('other'), constraint_name=r['constraint_name'])
       for r in hard + easy]
for i in range(3):
    with open(sys.argv[2] % i, 'x', encoding='utf8', newline='\n') as f:
        for row in sel[i::3]:
            f.write(json.dumps(row) + '\n')
print('hard', len(hard), 'easy', len(easy))
" "$F/cand-iv2-surfaces-s*.jsonl" "$OUT/list-%d.jsonl"
for width in w2 w3; do
  den=$W2D; [ $width = w3 ] && den=$W3D
  pids=()
  for i in 0 1 2; do
    timeout 7200 "$PY" -B replay_surfaces.py --supports "$F/iv2-supports.jsonl.gz" --partition "$F/iv2-partition.json.gz" \
      --interval "$G/work/iv2-interval-only-r1.json.gz" --stream-width $W2N $den --runtime "$RT" --cap-cpu 300 \
      --kinds interface --only-list "$OUT/list-$i.jsonl" --output "$OUT/$width-s$i.jsonl" > "$OUT/$width-s$i.log" 2>&1 &
    pids+=($!)
  done
  for p in "${pids[@]}"; do wait "$p"; done
  echo "done $width $(date +%H:%M:%S)"
done
echo "end $(date +%H:%M:%S)"
