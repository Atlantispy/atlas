"""Field-by-field comparison of two issued records, with identity/provenance fields set aside.

Walks both JSON records in parallel. Paths whose key mentions an identity or provenance
(execution_identity, *_id, *_sha256, digest) are listed separately as 'identity fields that
differ'; every other differing path is a NUMBER/CONTENT difference. Exit 0 only if there are none.
Usage: compare_records_except_identity.py A.json.gz B.json.gz
"""
import gzip
import json
import sys

IDENTITY_MARKS = ('identity', '_id', 'sha256', 'digest', 'provenance')


def walk(a, b, path, content, identity):
    key = path.rsplit('/', 1)[-1].lower()
    is_identity = any(mark in key for mark in IDENTITY_MARKS)
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                (identity if any(m in k.lower() for m in IDENTITY_MARKS) else content).append(path + '/' + k + ' (missing)')
                continue
            walk(a[k], b[k], path + '/' + k, content, identity)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            walk(x, y, '%s[%d]' % (path, i), content, identity)
    elif a != b:
        (identity if is_identity else content).append(path)


def main():
    a = json.loads(gzip.decompress(open(sys.argv[1], 'rb').read()))
    b = json.loads(gzip.decompress(open(sys.argv[2], 'rb').read()))
    content, identity = [], []
    walk(a, b, '', content, identity)
    print(json.dumps(dict(content_differences=len(content), content_examples=content[:10],
                          identity_differences=len(identity), identity_examples=identity[:10]), indent=1))
    sys.exit(0 if not content else 1)


if __name__ == '__main__':
    main()
