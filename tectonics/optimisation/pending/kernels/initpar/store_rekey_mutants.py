"""Planted mutants for store_rekey.py compare (fail-closed evidence). Stdlib only.

Usage: python -B -I store_rekey_mutants.py REFERENCE.sqlite OUTDIR
REFERENCE: a closed route (1) measurement store (e.g. T/ck/initpar/t4/serial.sqlite). OUTDIR must not
exist. Builds a pristine candidate (the reference re-keyed under a fake identity), which must PASS,
then one copy per mutant, each of which must FAIL. Writes OUTDIR/mutants.json; exit 1 unless all hold.
"""
import hashlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import store_rekey as S  # noqa: E402

FAKE = hashlib.sha256(b'another native tree').hexdigest()
OTHER = hashlib.sha256(b'a second identity').hexdigest()


def edit(path, action):
    db = sqlite3.connect(str(path), isolation_level=None)
    try:
        db.execute('BEGIN IMMEDIATE')
        action(db)
        db.execute('COMMIT')
    finally:
        db.close()


def snapshot(db, n):
    return db.execute('SELECT rowid, id, body, digest FROM snapshots ORDER BY rowid LIMIT 1 OFFSET ?', (n,)).fetchone()


def missing(db):
    rowid = snapshot(db, 10)[0]
    db.execute('DELETE FROM snapshots WHERE rowid=?', (rowid,))


def extra(db):
    body = S._parse(snapshot(db, 0)[2])
    body['metadata']['cell_id'] = hashlib.sha256(b'another cell').hexdigest()
    key, new, digest = S.rederive(S._canonical(body), FAKE)
    db.execute('INSERT INTO snapshots VALUES(?,?,?)', (key, new, digest))


def reorder_chunks(db):
    rows = db.execute('SELECT rowid, id, descriptor, codec, stored_sha, payload FROM chunks ORDER BY rowid LIMIT 2 OFFSET 4').fetchall()
    for row in rows:
        db.execute('DELETE FROM chunks WHERE rowid=?', (row[0],))
    for row in reversed(rows):
        db.execute('INSERT INTO chunks(id, descriptor, codec, stored_sha, payload) VALUES(?,?,?,?,?)', row[1:])


def reorder_snapshots(db):
    rows = [snapshot(db, 2), snapshot(db, 3)]
    for row in rows:
        db.execute('DELETE FROM snapshots WHERE rowid=?', (row[0],))
    for row in reversed(rows):
        db.execute('INSERT INTO snapshots(id, body, digest) VALUES(?,?,?)', row[1:])


def neighbour_field(db):
    rowid, _, body, _ = snapshot(db, 5)
    manifest = S._parse(body)
    manifest['metadata']['relative_error'] = '1/999'
    key, new, digest = S.rederive(S._canonical(manifest), FAKE)
    db.execute('UPDATE snapshots SET id=?, body=?, digest=? WHERE rowid=?', (key, new, digest, rowid))


def second_identity(db):
    rowid, _, body, _ = snapshot(db, 7)
    key, new, digest = S.rederive(body, OTHER)
    db.execute('UPDATE snapshots SET id=?, body=?, digest=? WHERE rowid=?', (key, new, digest, rowid))


def foreign_key(db):
    rowid = snapshot(db, 3)[0]
    db.execute('UPDATE snapshots SET id=? WHERE rowid=?', (hashlib.sha256(b'foreign key').hexdigest(), rowid))


def payload_byte(db):
    rowid, payload = db.execute('SELECT rowid, payload FROM chunks ORDER BY rowid LIMIT 1 OFFSET 6').fetchone()
    payload = bytearray(payload)
    payload[len(payload)//2] ^= 1
    db.execute('UPDATE chunks SET payload=? WHERE rowid=?', (bytes(payload), rowid))


def settings(db):
    db.execute('UPDATE settings SET body=? WHERE id=1', (b'{"chunk_bytes":65535,"schema":"atlas.array-store.v1"}',))


def stale_digest(db):
    rowid, _, body, _ = snapshot(db, 8)
    db.execute('UPDATE snapshots SET digest=? WHERE rowid=?', (hashlib.sha256(body+b' ').hexdigest(), rowid))


MUTANTS = dict(missing_snapshot=missing, extra_snapshot=extra, reordered_chunks=reorder_chunks,
               reordered_snapshots=reorder_snapshots, changed_field_next_to_identity=neighbour_field,
               second_identity=second_identity, key_differs_for_another_reason=foreign_key,
               chunk_payload_byte=payload_byte, settings_changed=settings, stale_digest=stale_digest)


def main():
    reference, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=False)
    pin = S._sha_file(reference)
    pristine = out/'pristine.sqlite'
    S.rekey(reference, pin, FAKE, pristine)
    results = {'pristine': S.compare(pristine, reference, pin)['passed']}
    results['wrong_pin'] = S.compare(pristine, reference, hashlib.sha256(b'x').hexdigest())['passed']
    for name, action in MUTANTS.items():
        path = out/(name+'.sqlite')
        shutil.copyfile(pristine, path)
        edit(path, action)
        result = S.compare(path, reference, pin)
        results[name] = result['passed']
        results[name+':failed'] = result['failed']
    ok = results['pristine'] is True and all(results[name] is False for name in ['wrong_pin', *MUTANTS])
    (out/'mutants.json').write_text(json.dumps(dict(reference=str(reference), pin=pin, results=results, ok=ok),
                                               indent=1), encoding='utf8')
    print(json.dumps(dict(ok=ok, **{k: v for k, v in results.items() if not k.endswith(':failed')})))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
