"""Item 19: initial-measurement stores across native trees (stdlib only; never imports atlas_tectonics).

A route (1) measurement store (atlas.array-store.v1, written by integration_dual_geometry.
cached_initial_component) differs between native trees only through the execution identity:
  snapshot key = invocation = sha256(canonical JSON of the metadata, which holds execution_identity);
  snapshot body = canonical JSON of {schema, invocation, arrays, metadata[, execution_mode]};
  snapshot digest = sha256(body); chunk rows are content-addressed and identity-free.

compare CANDIDATE REFERENCE@SHA256 [--report OUT.json]
    FAIL CLOSED: exit 1 unless every check is True. Checks:
    - the reference file's SHA-256 equals the pin; neither store has -wal/-journal/-shm sidecars;
    - settings rows byte-equal; chunk rows (id, descriptor, codec, stored_sha, payload) byte-equal
      in rowid (put) order, same count;
    - each store holds exactly one execution identity;
    - every candidate snapshot is self-consistent (id == invocation == sha256(canonical metadata),
      body == canonical JSON of itself, digest == sha256(body));
    - snapshot i of the candidate, re-derived under the reference's identity (identity put back,
      key/invocation/body/digest recomputed, nothing masked), is byte-equal to the reference's
      snapshot i (id, body, digest), in rowid order, same count.
rekey REFERENCE@SHA256 IDENTITY OUT
    Writes OUT: a copy of the reference with every snapshot re-derived under IDENTITY (rowids,
    chunks and settings unchanged). Used to seed a warm store for another native tree. Prints
    OUT's SHA-256. OUT must not exist.
"""
import hashlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path

SIDECARS = ('-wal', '-journal', '-shm')


def _sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('duplicate key')
        out[key] = value
    return out


def _parse(raw):
    return json.loads(bytes(raw), object_pairs_hook=_pairs)


def _open(path):
    return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro&immutable=1', uri=True)


def _pinned(argument):
    path, _, pin = argument.rpartition('@')
    if not path or len(pin) != 64:
        raise SystemExit('REFERENCE@SHA256 required')
    return Path(path), pin


def rederive(body, identity):
    """(key, body, digest) of a snapshot body re-derived under `identity`."""
    manifest = _parse(body)
    metadata = dict(manifest['metadata'], execution_identity=identity)
    key = hashlib.sha256(_canonical(metadata)).hexdigest()
    manifest = dict(manifest, metadata=metadata, invocation=key)
    new = _canonical(manifest)
    return key, new, hashlib.sha256(new).hexdigest()


def _snapshots(db):
    return [(row[0], bytes(row[1]), row[2]) for row in db.execute('SELECT id, body, digest FROM snapshots ORDER BY rowid')]


def _identities(snapshots):
    return {_parse(body)['metadata'].get('execution_identity') for _, body, _ in snapshots}


def compare(candidate, reference, pin):
    checks = {}
    checks['reference_sha256_pinned'] = _sha_file(reference) == pin
    for name, path in (('candidate', candidate), ('reference', reference)):
        checks[f'{name}_no_sidecars'] = not any(Path(str(path)+s).exists() for s in SIDECARS)
    with _open(candidate) as c, _open(reference) as r:
        settings = [bytes(b) for (b,) in c.execute('SELECT body FROM settings ORDER BY id')]
        checks['settings_equal'] = settings == [bytes(b) for (b,) in r.execute('SELECT body FROM settings ORDER BY id')] \
            and len(settings) == 1
        query = 'SELECT id, descriptor, codec, stored_sha, payload FROM chunks ORDER BY rowid'
        chunks_c = [tuple(bytes(v) if isinstance(v, (bytes, memoryview)) else v for v in row) for row in c.execute(query)]
        chunks_r = [tuple(bytes(v) if isinstance(v, (bytes, memoryview)) else v for v in row) for row in r.execute(query)]
        checks['chunk_count_equal'] = len(chunks_c) == len(chunks_r) and len(chunks_r) > 0
        checks['chunks_equal_in_order'] = chunks_c == chunks_r
        snaps_c, snaps_r = _snapshots(c), _snapshots(r)
    checks['snapshot_count_equal'] = len(snaps_c) == len(snaps_r) and len(snaps_r) > 0
    ids_c, ids_r = _identities(snaps_c), _identities(snaps_r)
    checks['candidate_one_identity'] = len(ids_c) == 1 and None not in ids_c
    checks['reference_one_identity'] = len(ids_r) == 1 and None not in ids_r
    consistent = matched = 0
    first_mismatch = None
    reference_identity = next(iter(ids_r)) if checks['reference_one_identity'] else None
    for index, (key, body, digest) in enumerate(snaps_c):
        try:
            manifest = _parse(body)
            ok = (key == manifest['invocation'] == hashlib.sha256(_canonical(manifest['metadata'])).hexdigest()
                  and body == _canonical(manifest) and digest == hashlib.sha256(body).hexdigest())
            consistent += ok
            if reference_identity is not None and index < len(snaps_r) and \
                    rederive(body, reference_identity) == snaps_r[index]:
                matched += 1
            elif first_mismatch is None:
                first_mismatch = index
        except (ValueError, KeyError, TypeError) as error:
            first_mismatch = index if first_mismatch is None else first_mismatch
            checks.setdefault('parse_error', str(error)[:200])
    checks['candidate_snapshots_self_consistent'] = consistent == len(snaps_c)
    checks['snapshots_rederived_equal_in_order'] = matched == len(snaps_c) == len(snaps_r)
    failed = sorted(name for name, value in checks.items() if value is not True)
    return dict(candidate=str(candidate), reference=str(reference), pin=pin,
                candidate_identity=sorted(i for i in ids_c if i is not None),
                reference_identity=sorted(i for i in ids_r if i is not None),
                chunks=len(chunks_c), snapshots=len(snaps_c), first_mismatch=first_mismatch,
                checks=checks, failed=failed, passed=not failed)


def rekey(reference, pin, identity, out):
    if _sha_file(reference) != pin:
        raise SystemExit('reference SHA-256 differs from the pin')
    if any(Path(str(reference)+s).exists() for s in SIDECARS):
        raise SystemExit('reference store has a sidecar')
    if out.exists() or any(Path(str(out)+s).exists() for s in SIDECARS):
        raise SystemExit(f'{out} exists')
    if len(identity) != 64 or any(ch not in '0123456789abcdef' for ch in identity):
        raise SystemExit('identity must be a lowercase SHA-256')
    shutil.copyfile(reference, out)
    with _open(reference) as r:
        rows = [(rowid, key, bytes(body)) for rowid, key, body in
                r.execute('SELECT rowid, id, body FROM snapshots ORDER BY rowid')]
    db = sqlite3.connect(str(out), isolation_level=None)
    try:
        db.execute('BEGIN IMMEDIATE')
        for rowid, _, body in rows:
            key, new, digest = rederive(body, identity)
            db.execute('UPDATE snapshots SET id=?, body=?, digest=? WHERE rowid=?', (key, new, digest, rowid))
        db.execute('COMMIT')
    finally:
        db.close()
    if any(Path(str(out)+s).exists() for s in SIDECARS):
        raise SystemExit('rekeyed store left a sidecar')
    return _sha_file(out)


def main():
    argv = sys.argv[1:]
    if argv[:1] == ['compare'] and len(argv) in (3, 5):
        reference, pin = _pinned(argv[2])
        result = compare(Path(argv[1]), reference, pin)
        if len(argv) == 5 and argv[3] == '--report':
            Path(argv[4]).write_text(json.dumps(result, indent=1), encoding='utf8')
        print(json.dumps(dict(passed=result['passed'], failed=result['failed'], chunks=result['chunks'],
                              snapshots=result['snapshots'], first_mismatch=result['first_mismatch'])))
        sys.exit(0 if result['passed'] else 1)
    if argv[:1] == ['rekey'] and len(argv) == 4:
        reference, pin = _pinned(argv[1])
        print(rekey(reference, pin, argv[2], Path(argv[3])))
        return
    raise SystemExit(__doc__)


if __name__ == '__main__':
    main()
