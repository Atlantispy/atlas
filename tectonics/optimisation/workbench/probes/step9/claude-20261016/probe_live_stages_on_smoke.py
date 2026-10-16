"""Read-only: do the 11 Step 8 live stages apply over the s1 smoke composition's native tree?

The s1 tree (R/s1/src, test_step8_runtime.compose_live_fixture) carries the established
Step 6/7 owner stages and none of the Step 8 live stages. This applies
live_memory_composition.apply_native to its native sources in memory and prints each
stage's module, label and full input/output SHA-256 (each stage also compiles), or the
first refusal. Nothing is written.
"""
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'
TREE = R/'s1'/'src'/'atlas_tectonics'
sys.path[:0] = [str(C), str(R/'composed-r1'/'helpers'), str(R/'composed-r1'/'runtime-src')]


def main():
    import live_memory_composition as LIVE
    raw = {path.name: path.read_bytes().decode('utf8') for path in sorted(TREE.glob('*.py'))}
    # compose_live_fixture writes its transformed files with write_text (CRLF on Windows);
    # every stage anchors on LF text, as a Step 10 composer writes it.
    crlf = sorted(name for name, text in raw.items() if '\r\n' in text)
    sources = {name: text.replace('\r\n', '\n') for name, text in raw.items()}
    print('s1 native files', len(sources), '| CRLF (normalised to LF here):', crlf)
    print('live_memory_composition', sha256((C/'live_memory_composition.py').read_bytes()).hexdigest()[:16])
    # test_live_composition's base applies differential_mesh_patch before the live stages;
    # the s1 tree leaves that file native (I's text).
    import differential_mesh_patch as DP
    name = 'integration_differential_mesh.py'
    before = sources[name]
    sources[name] = DP.transform(before)
    print(f"{name:40s} {'(established) differential_mesh_patch':36s} {sha256(before.encode()).hexdigest()} -> "
          f"{sha256(sources[name].encode()).hexdigest()}")
    # apply_native's own loop, one stage at a time, so a refusal names its stage.
    for name, label, transform in LIVE.STAGES:
        before = sources[name]
        try:
            after = transform(before)
            compile(after, name, 'exec')
        except Exception as error:  # noqa: BLE001 - the first refusal is the finding
            print(f'{name:40s} {label:36s} REFUSED: {type(error).__name__}: {str(error)[:200]}')
            return 1
        sources[name] = after
        print(f"{name:40s} {label:36s} {sha256(before.encode()).hexdigest()} -> {sha256(after.encode()).hexdigest()}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
