"""Step 10 composition check A9-A13: the post-publication full refresh is avoided.

Usage: python -B check_a9_a13.py COMPOSED_ROOT [--mutant-strip-both]

The post-publication _refresh is a per-node unsealed pass (about 40 min at IV1). It is
avoided only if CollarWorkflow._publish carries R2's in-transaction token adoption
(publication_token_transform) or compact_restart_patch's postpublication. This check reads
COMPOSED_ROOT/src/atlas_tectonics/integration_regional_workflow.py (LF-normalised, as Python
reads it), finds CollarWorkflow._publish by AST and FAILS unless at least one is present.
It also reports which are present, whether R2's adoption precedes the postpublication (the
Step 10 order), and whether R3's heat-checkpoint seam is in advance_spatial.
--mutant-strip-both removes both from the text first and must FAIL (detection self-check).
Exit 0 with 'a9-a13-check-pass' (or 'a9-a13-mutant-detected').
"""
from __future__ import annotations

import ast
from hashlib import sha256
import json
from pathlib import Path
import sys

R2_ADOPT = 'token_adopted'
R2_CAPTURE = '_r2_tokens.append(self._store.change_token())'
POSTPUBLICATION = '_RESTART.postpublication(self, parent, row, cancel=cancel)'
R3_SEAM = 'self._r3_after_heat_checkpoint(heat, _r3_mark)'


def method(text, name):
    tree = ast.parse(text)
    collar = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'CollarWorkflow')
    node = next(f for f in collar.body if isinstance(f, ast.FunctionDef) and f.name == name)
    return ast.get_source_segment(text, node) or ''


def main():
    root = Path(sys.argv[1]).resolve()
    mutant = '--mutant-strip-both' in sys.argv[2:]
    path = root / 'src' / 'atlas_tectonics' / 'integration_regional_workflow.py'
    text = path.read_text(encoding='utf8')
    if mutant:
        text = text.replace(POSTPUBLICATION, 'pass').replace(R2_ADOPT, '_r2_disabled').replace(R2_CAPTURE, 'pass')
    publish = method(text, '_publish')
    advance = method(text, 'advance_spatial')
    has_r2 = R2_ADOPT in publish and R2_CAPTURE in publish
    has_post = POSTPUBLICATION in publish
    result = dict(path=str(path), text_sha256=sha256(text.encode('utf8')).hexdigest(), mutant=mutant,
                  r2_adoption=has_r2, compact_restart_postpublication=has_post,
                  r2_before_postpublication=(has_r2 and has_post and
                                             publish.find(R2_ADOPT) < publish.find(POSTPUBLICATION)),
                  r3_heat_seam=R3_SEAM in advance)
    print(json.dumps(result, indent=1))
    passed = has_r2 or has_post
    if mutant:
        if passed:
            raise SystemExit('MUTANT NOT DETECTED: stripped text still passes')
        print('a9-a13-mutant-detected')
        return
    if not passed:
        raise SystemExit('A9-A13: neither R2 token adoption nor compact_restart postpublication is composed; '
                         'every interval would pay the post-publication full refresh')
    print('a9-a13-check-pass')


if __name__ == '__main__':
    main()
