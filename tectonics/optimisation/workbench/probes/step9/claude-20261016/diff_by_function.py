"""Read-only: which top-level functions of a module differ between two versions, and by how many lines.

Usage: python -B diff_by_function.py OLD.py NEW.py [NAME ...]
Uses difflib on the two sources; each changed line of NEW is attributed to the enclosing
top-level def/class of NEW (lines removed from OLD to the enclosing def of OLD). Prints
one row per function: added and removed line counts. With NAMEs, prints instead the unified
diff of each named top-level function (or '<module level>' for the lines outside any def).
"""
import ast
import difflib
import sys
from collections import Counter


def owners(source):
    tree = ast.parse(source)
    spans = [(node.lineno, node.end_lineno, node.name) for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]

    def owner(line):
        for start, end, name in spans:
            if start <= line <= (end or start):
                return name
        return '<module level>'
    return owner


def lines_of(source, owner, name):
    return [line for number, line in enumerate(source.splitlines(), 1) if owner(number) == name]


def main():
    old, new = (open(path, encoding='utf8').read() for path in sys.argv[1:3])
    old_owner, new_owner = owners(old), owners(new)
    if len(sys.argv) > 3:
        for name in sys.argv[3:]:
            print(f'===== {name}')
            print('\n'.join(difflib.unified_diff(lines_of(old, old_owner, name), lines_of(new, new_owner, name),
                                                 'old', 'new', n=2, lineterm='')))
        return
    added, removed = Counter(), Counter()
    matcher = difflib.SequenceMatcher(a=old.splitlines(), b=new.splitlines(), autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            continue
        for line in range(i1, i2):
            removed[old_owner(line+1)] += 1
        for line in range(j1, j2):
            added[new_owner(line+1)] += 1
    names = sorted(set(added) | set(removed), key=lambda name: -(added[name]+removed[name]))
    for name in names:
        print(f'{added[name]:5d} + {removed[name]:5d} -  {name}')


if __name__ == '__main__':
    main()
