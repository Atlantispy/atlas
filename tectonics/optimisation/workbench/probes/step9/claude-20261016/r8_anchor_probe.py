"""Count the (b') JC 408 anchor in r7's derived joined-control text, without executing it.

Usage: python -B r8_anchor_probe.py
Runs only the constant/function part of R/private_heat_original_joined_r7.py (everything
before its first source_bindings() call), applies continuation_transfer.joined_control_source
and r7's edits to the pinned JC source, and prints how often each anchor occurs. Read-only.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
ANCHOR = ("            mesh = H.build_differential_mesh(funding, bounds, partition.supports, endpoint='end',\n"
          "                max_geometry_volume_error_m3=32*radius**3, max_leaves=thermal_max_leaves,\n"
          "                max_witness_refinements=thermal_witness_refinements,\n"
          "                closed_graph=solution.graph, budget=budget)\n")


def main():
    sys.path.insert(0, str(R))
    text = (R/'private_heat_original_joined_r7.py').read_text(encoding='utf8')
    head = text[:text.index('\nsource_bindings()\n')]
    namespace = {'__file__': str(R/'private_heat_original_joined_r7.py'), '__name__': 'r7_constants'}
    exec(compile(head, 'r7-constants', 'exec'), namespace)
    from continuation_transfer import joined_control_source
    original = namespace['_read_bound'](namespace['_SOURCE'], namespace['_SOURCE_SHA'])
    transferred = joined_control_source(original)
    derived = namespace['_replace_exact'](transferred, namespace['_EDITS'])
    for label, value in (('original', original), ('transferred', transferred), ('derived', derived)):
        print(label, 'anchor count', value.count(ANCHOR))


if __name__ == '__main__':
    main()
