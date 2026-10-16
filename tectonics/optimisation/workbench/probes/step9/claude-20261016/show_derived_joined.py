"""Print numbered lines of a joined helper's derived text, without executing it (read-only).

Usage: python -B show_derived_joined.py HELPER.py FIRST LAST
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]


def main():
    sys.path.insert(0, str(R))
    path, first, last = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
    text = path.read_text(encoding='utf8')
    namespace = {'__file__': str(path), '__name__': path.stem+'_constants'}
    exec(compile(text[:text.index('\nsource_bindings()\n')], path.name+'[constants]', 'exec'), namespace)
    from continuation_transfer import joined_control_source
    original = namespace['_read_bound'](namespace['_SOURCE'], namespace['_SOURCE_SHA'])
    derived = namespace['_replace_exact'](joined_control_source(original), namespace['_EDITS'])
    for number, line in enumerate(derived.splitlines()[first-1:last], start=first):
        print(f'{number:5d} {line}')


if __name__ == '__main__':
    main()
