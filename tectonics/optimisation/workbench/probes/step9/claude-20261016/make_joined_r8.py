"""Write R/private_heat_original_joined_r8.py = original_joined_r8_transform.r8_source(r7).

Usage: python -B make_joined_r8.py
Replaces this chat's own generated r8 atomically, never r7. Also checks, without executing
the joined control, that r8's derived text is r7's with exactly the r8 mesh edits applied.
"""
import os
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]


def derived(path):
    text = path.read_text(encoding='utf8')
    namespace = {'__file__': str(path), '__name__': path.stem+'_constants'}
    exec(compile(text[:text.index('\nsource_bindings()\n')], path.name+'[constants]', 'exec'), namespace)
    from continuation_transfer import joined_control_source
    original = namespace['_read_bound'](namespace['_SOURCE'], namespace['_SOURCE_SHA'])
    return namespace['_replace_exact'](joined_control_source(original), namespace['_EDITS'])


def main():
    sys.path.insert(0, str(R))
    import original_joined_r8_transform as T
    r7 = R/'private_heat_original_joined_r7.py'
    r8 = R/'private_heat_original_joined_r8.py'
    text = T.r8_source(r7.read_bytes().decode('utf8'))
    temporary = r8.with_suffix('.py.tmp')
    with temporary.open('x', encoding='utf8', newline='') as stream:
        stream.write(text)
    os.replace(temporary, r8)
    old, new = derived(r7), derived(r8)
    expected = old
    for _label, before, after in T.MESH_EDITS:
        assert expected.count(before) == 1 and new.count(after) == 1
        expected = expected.replace(before, after, 1)
    assert new == expected
    print({'r8': str(r8), 'sha256': sha256(r8.read_bytes()).hexdigest(),
           'derived_r7_sha256': sha256(old.encode()).hexdigest(), 'derived_r8_sha256': sha256(new.encode()).hexdigest()})


if __name__ == '__main__':
    main()
