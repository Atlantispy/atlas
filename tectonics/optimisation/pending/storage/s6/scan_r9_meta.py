"""S6 (H5): read-only scan of the r9 IV1 heat result metadata (opened sqlite immutable, no writes).

Stage 1: assemble metadata_utf8 bytes, report offsets of interesting keys; then decode
selective_refinements and summarise each refinement pass (faces, rungs, seconds, routes).
"""
import json, sqlite3, sys, re, struct
import numpy as np
P = sys.argv[1]
c = sqlite3.connect('file:' + P + '?mode=ro&immutable=1', uri=True)
body = json.loads(bytes(c.execute("select body from snapshots where id like '24c6cc10%'").fetchone()[0]))
m = body['arrays']['metadata_utf8']
buf = bytearray()
for cid in m['chunks']:
    codec, desc, payload = c.execute('select codec, descriptor, payload from chunks where id=?', (cid,)).fetchone()
    payload = bytes(payload)
    count = json.loads(bytes(desc))['count']
    if codec == 'raw':
        buf += payload
    elif codec == 'palette-packed-v1':
        # same decode as atlas_tectonics/storage.py _decode (dtype |u1)
        n, bits = struct.unpack('<HB', payload[:3])
        cut = 3 + n
        palette = np.frombuffer(payload, dtype='u1', offset=3, count=n)
        packed = np.frombuffer(payload, dtype='u1', offset=cut)
        idx = np.empty(count, dtype='u1')
        per = 8 // bits
        for lane in range(per):
            size = idx[lane::per].size
            idx[lane::per] = (packed[:size] >> (lane * bits)) & ((1 << bits) - 1)
        buf += palette[idx].tobytes()
    else:
        raise SystemExit('unexpected codec ' + codec)
buf = bytes(buf[:m['shape'][0]])
print('bytes', len(buf))
for key in (b'"selective_refinements"', b'"reconstruction"', b'"connected_seconds"', b'"reconstruction_scope"',
            b'"partial_reconstruction"', b'"polygon_moments_computed"'):
    offs = [mm.start() for mm in re.finditer(re.escape(key), buf)]
    print(key.decode(), len(offs), offs[:8])
dec = json.JSONDecoder()
def value_at(key):
    i = buf.find(key)
    j = buf.index(b':', i + len(key)) + 1
    while buf[j:j+1] in (b' ',):
        j += 1
    s = buf[j:j + 400_000_000].decode('utf-8', 'replace') if False else None
    return j
if len(sys.argv) > 2 and sys.argv[2] == "offsets":
    sys.exit(0)
# connected_seconds
j = value_at(b'"connected_seconds"')
print('connected_seconds', buf[j:j+30])
# selective refinements: decode from its start (bounded slice)
j = value_at(b'"selective_refinements"')
end_guess = buf.find(b'"selective_refinements"')
txt = buf[j:].decode('utf-8')
val, used = dec.raw_decode(txt)
print('selective_refinements bytes', used, 'count', len(val))
def summarise(proof):
    census = proof.get('census', [])
    routes, att_s, samples, exp, nattempt = {}, 0.0, [], 0, 0
    prec_hist = {}
    for e in census:
        if e.get('prescribed_power_exact'):
            routes['prescribed'] = routes.get('prescribed', 0) + 1
            continue
        a = e['functional_attempts']
        r = a[-1].get('route')
        routes[r] = routes.get(r, 0) + 1
        samples.append(e['samples'])
        exp += e['expanded_shells']
        for item in a:
            for name in ('interval', 'zero_column_interval', 'reduced_interval'):
                if isinstance(item.get(name), dict):
                    for t in item[name].get('attempts', []):
                        nattempt += 1
                        att_s += t.get('seconds', 0.0)
                        prec_hist[t.get('precision_bits'), t.get('status')] = prec_hist.get((t.get('precision_bits'), t.get('status')), 0) + 1
        pb = a[-1].get('precision_bits')
    return dict(seconds=proof.get('seconds'), census=len(census), selected=len(proof.get('selected_face_ids', [])),
                total_physical_faces=proof.get('total_physical_faces'), polygon_moments_computed=proof.get('polygon_moments_computed'),
                scope=proof.get('reconstruction_scope'), routes=routes, interval_attempt_seconds=round(att_s, 3),
                interval_attempts=nattempt, precision_status=sorted(((str(k), v) for k, v in prec_hist.items())),
                samples_mean=(sum(samples) / len(samples) if samples else None), samples_max=max(samples) if samples else None,
                expanded_shells=exp, exact_fallback_faces=proof.get('exact_fallback_faces'),
                interval_certified_faces=proof.get('interval_certified_faces'))
for i, ref in enumerate(val):
    print('refinement', i, 'precision_bits', ref.get('precision_bits'), 'offered', ref.get('offered_precision_bits'))
    print('  ', json.dumps(summarise(ref['proof'])))
    mg = ref.get('merge')
    if isinstance(mg, dict):
        print('   merge keys', sorted(mg)[:20])
del txt, val
# main reconstruction proof: decode (may be large)
j = value_at(b'"reconstruction"')
txt = buf[j:].decode('utf-8')
del buf
val, used = dec.raw_decode(txt)
del txt
print('reconstruction bytes', used)
print('  ', json.dumps(summarise(val)))
