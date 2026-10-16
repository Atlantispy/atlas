"""Append text to T/WORKFLOW_DECISIONS.md without touching earlier bytes.

Usage: python -B append_decision.py TEXT_FILE EXPECTED_PREVIOUS_SHA256|-

Writes a before/after hash line to stdout so each append is auditable. The
earlier file content is re-read and verified unchanged after the append.
"""
import hashlib
import os
import sys

T = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), *(['..'] * 7)))
TARGET = os.path.join(T, 'WORKFLOW_DECISIONS.md')


def main():
    text_path, expected = sys.argv[1], sys.argv[2]
    with open(TARGET, 'rb') as f:
        before = f.read()
    before_sha = hashlib.sha256(before).hexdigest()
    if expected != '-' and expected != before_sha:
        raise SystemExit('WORKFLOW_DECISIONS.md changed since last append: ' + before_sha)
    with open(text_path, 'rb') as f:
        addition = f.read()
    addition = addition.replace(b'\r\n', b'\n')
    prefix = b'' if before.endswith(b'\n\n') else (b'\n' if before.endswith(b'\n') else b'\n\n')
    with open(TARGET, 'ab') as f:
        f.write(prefix + addition)
    with open(TARGET, 'rb') as f:
        after = f.read()
    if not after.startswith(before):
        raise SystemExit('earlier content changed during append')
    print('target', TARGET)
    print('before', before_sha, len(before))
    print('after ', hashlib.sha256(after).hexdigest(), len(after))


if __name__ == '__main__':
    main()
