"""Move a pre-landing-1 run profile to landing 1's field set.

    python -I -B tools/runs/migrate_run_profile.py OLD_PROFILE OLD_SHA256 NEW_PROFILE

Serves atlas.fresh-interval-profile.v2 and atlas.prepared-restart-launch.v3 alike: `source_manifest` is
replaced by the two values the readers used to take from that manifest, `completed_query_store` and
`installed_binding.qualification_status`; every other field is carried. The old file is never changed.
Standard library only; stays outside the source-bound packages.
"""
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath

NEW_FIELDS = ('completed_query_store', 'qualification_status')


def _forms():
    # The JSON forms a profile is written in; the new file is written in the old file's form.
    for sort_keys in (True, False):
        yield lambda value, s=sort_keys: json.dumps(value, sort_keys=s, separators=(',', ':'), allow_nan=False).encode()
        for indent in (2, 4):
            for end in ('', '\n'):
                yield lambda value, s=sort_keys, i=indent, e=end: (
                    json.dumps(value, sort_keys=s, indent=i, allow_nan=False) + e).encode()


def _pinned(path, sha256, label):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise SystemExit('%s bytes differ from their SHA-256: %s' % (label, path))
    return raw


def migrate(old_profile, old_sha256, new_profile):
    raw = _pinned(old_profile, old_sha256, 'profile')
    old = json.loads(raw)
    if type(old) is not dict or 'source_manifest' not in old or set(NEW_FIELDS) & set(old):
        raise SystemExit('not a pre-landing-1 profile (no source_manifest, or already moved): %s' % old_profile)
    form = next((f for f in _forms() if f(old) == raw), None)
    if form is None:
        raise SystemExit('profile is in no known JSON form: %s' % old_profile)
    binding = old['source_manifest']
    name = binding.get('path') if type(binding) is dict else None
    if (type(name) is not str or not name or '\\' in name or ':' in name or PurePosixPath(name).is_absolute()
            or '..' in PurePosixPath(name).parts):
        raise SystemExit('source_manifest.path must be workspace-relative and contained')
    manifest = json.loads(_pinned(Path(old['workspace']) / name, binding.get('sha256'), 'source manifest'))
    try:
        values = (manifest['completed_query_store'], manifest['installed_binding']['qualification_status'])
    except (KeyError, TypeError):
        raise SystemExit('source manifest lacks completed_query_store or installed_binding.qualification_status')
    new = {}
    for key, value in old.items():
        if key == 'source_manifest':
            new['completed_query_store'], new['qualification_status'] = values
        else:
            new[key] = value
    out = form(new)
    with open(new_profile, 'xb') as handle:  # refuses an existing file
        handle.write(out)
    return hashlib.sha256(out).hexdigest()


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    try:
        print(migrate(*sys.argv[1:]))
    except FileExistsError:
        raise SystemExit('output exists: %s' % sys.argv[3])
