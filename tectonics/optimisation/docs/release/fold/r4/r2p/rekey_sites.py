"""Carry the R1 fold's site decisions onto p20c-r2, making only the declared changes.

    python -B rekey_sites.py --roots OLD_DIR NEW_DIR [--declared DECLARED_JSON] SITES_IN CANDIDATES_JSON
                             COMPOSITION_NAME COMPOSITION_SHA256 SITES_OUT MODULE [MODULE ...]

CANDIDATES_JSON is `fold_r5.py candidates` run on p20c-r2 with SITES_IN and the r2 trace. Site ids are
module:line:col:kind, so a decision whose expression moved in an edited file no longer names its site. Only in the
named MODULEs (the files that changed) is a decision moved, and only along the edit's own line map: OLD_DIR and
NEW_DIR are the two compositions (helpers/M.py, src/atlas_tectonics/M.py), difflib maps each unchanged line of the
old file to its new line, and an orphaned or stale decision goes to the site at the mapped line, same column, kind
and expression, which must be undecided. A decision on a line the edit removed or changed has no move: it must be
declared retired, and a site the edit added must be declared added (refuter r3: an undeclared delete plus an add of
the same expression is not a move). DECLARED_JSON names the changes the edit itself makes, each
with a reason: `retire` {site: why}, decisions whose sites the edit removed, and `add` {site: decision}, decisions for
sites the edit introduced (the decision carries its `expr`, which must match). Everything else fails closed:
- a decision outside MODULEs that no longer matches;
- a decision with no unique new site that is not declared retired;
- an undecided site left over that is not declared added;
- a declaration that is unused, outside MODULEs, without a reason, or whose expression or kind does not match;
- a wrap that no longer matches.
Decisions are copied verbatim. Only `target` changes, to the new composition. Exit 0 iff SITES_OUT is written.
"""
import difflib
import json
import sys
from pathlib import Path


def _file(root, module):
    if module.startswith('atlas_tectonics.'):
        return Path(root)/'src'/'atlas_tectonics'/(module.split('.', 1)[1] + '.py')
    return Path(root)/'helpers'/(module + '.py')


def line_map(old_root, new_root, module):
    """{old line: new line} for every line difflib keeps unchanged (1-based)."""
    old, new = (_file(r, module).read_text(encoding='utf8').splitlines() for r in (old_root, new_root))
    out = {}
    for tag, i1, i2, j1, _ in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == 'equal':
            out.update({i + 1: j1 + (i - i1) + 1 for i in range(i1, i2)})
    return out


def main(argv):
    declared, roots = dict(retire={}, add={}), None
    while argv[:1] in (['--declared'], ['--roots']):
        if argv[0] == '--declared' and len(argv) > 1:
            declared = dict(declared, **json.loads(Path(argv[1]).read_bytes()))
            argv = argv[2:]
        elif argv[0] == '--roots' and len(argv) > 2:
            roots = (argv[1], argv[2])
            argv = argv[3:]
        else:
            break
    if len(argv) < 6 or roots is None:
        print(__doc__)
        return 2
    sites = json.loads(Path(argv[0]).read_bytes())
    cand = json.loads(Path(argv[1]).read_bytes())
    name, sha, out, modules = argv[2], argv[3], Path(argv[4]), set(argv[5:])
    decisions = dict(sites['sites'])
    unplaced = sorted(set(cand['orphan_decisions']) | set(cand['stale']))
    outside = [s for s in unplaced if s.split(':', 1)[0] not in modules]
    problems = []
    if outside:
        problems.append(['decisions outside the changed modules no longer match', outside[:20]])
    if cand['bad_wraps']:
        problems.append(['wraps no longer match', cand['bad_wraps'][:20]])
    for site, why in sorted(declared['retire'].items()):
        if site not in unplaced or site in outside or not (isinstance(why, str) and why.strip()):
            problems.append(['a retire declaration is not an orphaned decision in MODULEs with a reason', site])
    retired = {s: decisions.pop(s) for s in unplaced if s in declared['retire'] and s not in outside}
    moved = {s: decisions.pop(s) for s in unplaced if s not in outside and s not in retired}
    rows = {r['site']: r for r in cand['sites']}
    open_rows = [r for r in cand['sites'] if r['site'] not in decisions]
    moves, maps = [], {}
    open_ids = {r['site'] for r in open_rows}
    for old, decision in sorted(moved.items()):
        module, line, col, kind = old.split(':')
        if module not in maps:
            maps[module] = line_map(roots[0], roots[1], module)
        new_line = maps[module].get(int(line))
        new = None if new_line is None else '%s:%d:%s:%s' % (module, new_line, col, kind)
        row = rows.get(new) if new else None
        if row is None or new not in open_ids or new in decisions or row['expr'] != decision['expr']:
            problems.append(['no site at the mapped line for a decision (an edited or removed line: declare it)',
                             old, new])
            continue
        decisions[new] = decision
        moves.append([old, new])
    added = []
    for site, decision in sorted(declared['add'].items()):
        row = rows.get(site)
        if row is None or site in decisions or site.split(':', 1)[0] not in modules or row['kind'] != site.rsplit(':', 1)[1] \
                or not isinstance(decision, dict) or decision.get('expr') != row['expr'] \
                or not (isinstance(decision.get('why'), str) and decision['why'].strip()):
            problems.append(['an add declaration is not an undecided site in MODULEs with its expression and a reason',
                             site])
            continue
        decisions[site] = decision
        added.append(site)
    left = sorted(s for s in rows if s not in decisions)
    if left:
        problems.append(['undecided sites (each needs a declared decision)', left[:20]])
    if problems:
        print(json.dumps(dict(status='FAIL', problems=problems, moves=moves)))
        return 1
    new = dict(sites, sites=dict(sorted(decisions.items())),
               target=dict(sites.get('target', {}), composition=name, composition_json_sha256=sha))
    out.write_text(json.dumps(new, indent=1, sort_keys=True) + '\n', encoding='utf8', newline='\n')
    print(json.dumps(dict(status='OK', moves=moves, retired=sorted(retired), added=added, decisions=len(decisions),
                          out=out.name)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
