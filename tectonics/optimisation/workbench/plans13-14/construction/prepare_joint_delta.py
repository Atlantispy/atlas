"""Source-only, exact adaptation of the approved Plan14 handoffs for C14.

No Atlas imports, source generation, execution permission or enablement.
"""
from hashlib import sha256
import json
from pathlib import Path

W = Path('C:/Users/LOCAL_USER/Documents/Codex/agentchattr/workspace')
T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
BASE = T / 'ac/p1012-r1'
BASE_SHA = 'cb71df92d0ab2f3ab175c43a669d5b8ffc1d4d350cbdc49b68fd6f2cabfb74d5'
S1 = W / 'work/plan14/s1-r1/integration-map.json'
S1_SHA = '9f344a367196c2d37bea29974a6248c8c17d015de4cff32449c166a269fede7e'
MARKER = W / 'work/plan14/r1/marker-delta.json'
OUT = W / 'work/plan13/joint-r1/additional-delta.json'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def raw(path, expected):
    value = path.read_bytes()
    require(sha256(value).hexdigest() == expected, 'Input pin differs: ' + str(path))
    return value


def prepare(marker_sha):
    require(len(marker_sha) == 64 and all(c in '0123456789abcdef' for c in marker_sha),
            'Explicit reviewed marker-map SHA256 required')
    require(not OUT.exists(), 'Preserve previous source adapter')
    composition = json.loads(raw(BASE / 'composition.json', BASE_SHA))
    s1 = json.loads(raw(S1, S1_SHA))
    marker = json.loads(raw(MARKER, marker_sha))
    require(s1['base']['path'] == str(BASE / 'composition.json') and
            s1['base']['sha256'] == BASE_SHA and s1['base']['h5a_enabled'] is False,
            'Exact accepted lf3 predecessor required')
    require(marker['baseline'] == str(BASE), 'Marker predecessor differs')
    files = {}
    for name, row in s1['production_files'].items():
        area, member = name.split('/', 1)
        expected = composition['helpers' if area == 'helpers' else 'outputs'].get(member)
        require(row['base_sha256'] == expected, 'S1 predecessor differs: ' + name)
        candidate = S1.parent / 'production-delta' / name
        value = raw(candidate, row['output_sha256'])
        if expected is None:
            require(value == raw(Path(row['source']), row['source_sha256']),
                    'Accepted new S1 source differs')
        else:
            before = raw(BASE / name, expected)
            if row['operation'] == 'one-FINISH-import-only':
                old = b'import private_heat_finish_kernel_r10 as FINISH'
                new = b'import private_heat_finish_kernel_r11 as FINISH'
                require(before.count(old) == 1 and value == before.replace(old, new),
                        'S1 forward change exceeds one FINISH import')
            else:
                require(row['operation'] == 'enumerated-current-dependency-pins-only',
                        'Unexpected S1 source operation')
                for change in row['changes']:
                    old, new = change['before'].encode('ascii'), change['after'].encode('ascii')
                    require(before.count(old) == 1, 'Dependency pin not unique')
                    before = before.replace(old, new)
                require(before == value, 'S1 consumer change exceeds declared dependency pins')
        files[name] = dict(base_sha256=expected, candidate=str(candidate), output_sha256=row['output_sha256'])
    require(len(files) == 9, 'Exact nine-file S1 production delta required')
    fresh = marker['files']['fresh_interval_driver.py']
    prepared = marker['files']['prepared_interval_driver.py']
    require(fresh['changed'] is True and prepared['changed'] is False and
            prepared['before'] == prepared['after'] == composition['helpers']['prepared_interval_driver.py'],
            'Only approved fresh marker source may change')
    require(fresh['before'] == composition['helpers']['fresh_interval_driver.py'] and
            fresh['after'] == '709f65d3d44662f04a8283ccd0265a9f0575f688ec6e96f3019fcd80328f9943',
            'Approved marker source differs')
    raw(Path(fresh['candidate']), fresh['after'])
    files['helpers/fresh_interval_driver.py'] = dict(base_sha256=fresh['before'],
        candidate=fresh['candidate'], output_sha256=fresh['after'])
    result = dict(schema='atlas.private.plan13-plan14.ordered-additional-source-delta.r1',
        base=dict(path=str(BASE / 'composition.json'), sha256=BASE_SHA), files=files,
        upstream=dict(s1=dict(path=str(S1), sha256=S1_SHA), marker=dict(path=str(MARKER), sha256=marker_sha)),
        scope='Approved Plan14 delta; source rows disjoint from C14 kernel/resources/helper',
        H5a_enabled=False, scientific_acceptance=False, holds_released=False)
    value = (json.dumps(result, sort_keys=True, indent=2) + '\n').encode('utf8')
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open('xb') as stream:
        stream.write(value)
    print(json.dumps(dict(path=str(OUT), sha256=sha256(value).hexdigest(), files=len(files),
                         status='SOURCE_ADAPTER_PREPARED_NO_GENERATION_BUILT')))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--marker-map-sha256', required=True)
    prepare(parser.parse_args().marker_map_sha256)
