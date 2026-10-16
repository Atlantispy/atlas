"""Append one new top-level field to a JSON receipt without touching old bytes.

Usage: python -B add_receipt_field.py RECEIPT.json KEY VALUE.json EXPECTED_SHA256
Refuses unless the receipt's current SHA-256 equals EXPECTED_SHA256 (so a
change by any other writer is noticed, not overwritten) and KEY is absent.
The new field is inserted textually before the final closing brace, so every
earlier byte of the receipt stays identical; the result must parse to exactly
the old object plus the new key, with the old keys in their old order. A copy
of the previous receipt is kept beside VALUE.json as <name>.before-<KEY>.json.
"""
import json
import sys
from hashlib import sha256
from pathlib import Path


def main():
    receipt, key, value_path, expected = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), sys.argv[4]
    raw = receipt.read_bytes()
    actual = sha256(raw).hexdigest()
    if actual != expected:
        raise SystemExit(f'receipt changed: {actual} != {expected}; stop and report')
    text = raw.decode('utf8')
    old = json.loads(text)
    if type(old) is not dict or key in old:
        raise SystemExit('receipt must be an object without '+key)
    value = json.loads(value_path.read_text(encoding='utf8'))
    end = text.rstrip().rfind('}')
    head, tail = text[:end].rstrip(), text[end:]
    body = json.dumps(value, indent=2, ensure_ascii=False).replace('\n', '\n  ')
    new_text = head+',\n  '+json.dumps(key)+': '+body+'\n'+tail
    new = json.loads(new_text)
    if list(new) != [*old, key] or any(new[k] != old[k] for k in old) or new[key] != value:
        raise SystemExit('insertion would change an existing field')
    if not new_text.startswith(head):
        raise SystemExit('existing bytes would change')
    backup = value_path.parent/f'{receipt.stem}.before-{key}.json'
    backup.write_bytes(raw)
    receipt.write_bytes(new_text.encode('utf8'))
    print(json.dumps(dict(receipt=str(receipt), key=key, before_sha256=actual,
                          after_sha256=sha256(new_text.encode('utf8')).hexdigest(),
                          backup=str(backup)), indent=1))


if __name__ == '__main__':
    main()
