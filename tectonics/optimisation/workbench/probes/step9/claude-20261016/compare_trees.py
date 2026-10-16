"""Read-only: compare two source trees file by file (.py, by SHA-256), plus geometry's package digest.

Usage: python -B compare_trees.py ROOT_A ROOT_B [--recursive]
package_digest is geometry's rc1_env.package_digest over each root (every .py file below it,
sorted relative paths), so a root can be matched to a report's package_digest. With
--recursive the file comparison covers subfolders too (otherwise the top level only, as for a
flat helpers folder). Prints the files that differ and those present on one side only.
"""
import json
import sys
from hashlib import sha256
from pathlib import Path


def package_digest(root):
    digest = sha256()
    for path in sorted(root.rglob('*.py')):
        digest.update(str(path.relative_to(root)).replace('\\', '/').encode()+b'\0')
        digest.update(sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def files(root, recursive):
    found = root.rglob('*.py') if recursive else root.glob('*.py')
    return {str(path.relative_to(root)).replace('\\', '/'): sha256(path.read_bytes()).hexdigest()[:8]
            for path in found}


def main():
    argv = sys.argv[1:]
    recursive = '--recursive' in argv
    a, b = (Path(path).resolve() for path in argv if path != '--recursive')
    left, right = files(a, recursive), files(b, recursive)
    report = dict(a=str(a), b=str(b), package_digest_a=package_digest(a), package_digest_b=package_digest(b),
                  files_a=len(left), files_b=len(right),
                  differ={name: [left[name], right[name]] for name in sorted(set(left) & set(right))
                          if left[name] != right[name]},
                  only_a=sorted(set(left)-set(right)), only_b=sorted(set(right)-set(left)))
    print(json.dumps(report, indent=1))


if __name__ == '__main__':
    main()
