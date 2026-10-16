"""Build-only compact restored consumer; original r9 validation stays explicit.

The frozen RAM context's indexed mesh checks and recovery's collar-index rule
are carried into this additive successor. Legacy helpers remain unchanged.
"""
import ast
from hashlib import sha256

import ram_context_indexed_patch as RAM
import spatial_validation_patch as V

BASE_SHA256 = '68e593c48b9c136e601e961a78f35dc544cc17083f1c67c5ebbed4f3ebdf2d3f'


_COLLAR = '''

def _collar_flat_index(index, shape):
    """Match regional_collar3d's actual full-grid index normalisation exactly."""
    if (type(shape) is not tuple or len(shape) != 3
            or any(type(n) is not int or n <= 0 for n in shape)):
        raise ValueError('Actual three-dimensional collar grid shape required')
    count = shape[0]*shape[1]*shape[2]
    if type(index) is int and 0 <= index < count:
        return index
    if (type(index) is not list or len(index) != 3
            or any(type(i) is not int or not 0 <= i < n
                   for i, n in zip(index, shape, strict=True))):
        raise ValueError('thermal collar index is not an actual full-grid coordinate')
    return int(np.ravel_multi_index(tuple(index), shape))


def _collar_value(array, index):
    if type(array) is not np.ndarray or array.dtype != np.dtype('float64'):
        raise ValueError('Actual native binary64 collar field required')
    return float(array.flat[_collar_flat_index(index, array.shape)])
'''


def transform(source):
    if type(source) is not str or sha256(source.encode()).hexdigest() != BASE_SHA256:
        raise V.ContractError('exact original r9 restored binding required')
    original = ast.parse(source)
    equations = {n.name: ast.dump(n) for n in original.body if isinstance(n, ast.FunctionDef)
                 and n.name in ('_inputs', '_equations', '_equations_body', '_expected_bindings')}
    if len(equations) != 4:
        raise V.ContractError('original r9 restored binding required')
    source = V.context_source(source)
    source = V._function(source, '_context', (
        ('        _snapshot(snapshot, budget, cancel)',
         '        if _indexed_spatial(snapshot, (parent_spatial_state, state)):\n'
         '            _indexed_snapshot(snapshot, budget, cancel)\n'
         '        else:\n            _snapshot(snapshot, budget, cancel)'),
        ('R.decoded(parent_spatial_state._snapshot._metadata, budget=budget, cancel=cancel)',
         '_HC.state_view(parent_spatial_state._snapshot, budget, cancel, R)'),
        ('R.decoded(state._snapshot._metadata, budget=budget, cancel=cancel)',
         '_HC.state_view(state._snapshot, budget, cancel, R)'),
        ('    thermal = work.stack.enter_context(R.decoded(mesh._json, budget=budget, cancel=cancel)).value',
         '    if mesh.is_compact:\n        thermal = _IndexedThermal(mesh, budget)\n'
         '    else:\n        thermal = work.stack.enter_context(R.decoded(mesh._json, budget=budget, cancel=cancel)).value'),
        ("    graph, plan, ref = exchange['spatial_graph'], exchange['joined_heat_plan'], exchange['joined_heat']",
         "    graph, plan, ref = exchange['spatial_graph'], exchange['joined_heat_plan'], exchange['joined_heat']\n"
         '    plan = _HC.native_plan(plan, work.stack)'),
        (RAM._ENDPOINT, '    if mesh.is_compact:\n'
         '        if _indexed_endpoint_differs(mesh, thermal, current, owner, graph, exchange):\n'
         "            raise ValueError('Restored physical mesh is not the actual transported endpoint')\n"
         '    else:\n'+RAM._indent(RAM._ENDPOINT)),
        (RAM._GEOMETRY.rstrip('\n'), '    if mesh.is_compact:\n'
         '        geometry = _indexed_geometry(mesh, geometry, budget, cancel)\n'
         '    else:\n'+RAM._indent(RAM._GEOMETRY).rstrip('\n')),
    ))
    source = V._function(source, '_snapshot', (
        ('    if type(snapshot) is not RegionalMechanicalSnapshot:',
         '    from heat_ledger_tables import CompactHeatSnapshot\n'
         '    if type(snapshot) is CompactHeatSnapshot:\n'
         '        if snapshot.scope.run_budget is not budget:\n'
         "            raise ValueError('Restored heat snapshot has another budget')\n"
         '        snapshot.verify_identity(check=lambda: R.check(cancel))\n'
         '        return\n'
         '    if type(snapshot) is not RegionalMechanicalSnapshot:'),
    ))
    source = V._function(source, 'validate_for', (
        ('R.codec_for_value(exchange, budget=budget, cancel=cancel)',
         '_SV.codec_scope(exchange, budget, cancel, R.codec_for_value)'),
        ('R.stream_hash(exchange, cancel)',
         '_SV.identity(exchange, lambda value: R.stream_hash(value, cancel))'),
    ))
    source = V._function(source, 'restore', (
        ('bindings=bindings, budget=budget, cancel=cancel)',
         "bindings=bindings, scope=store.scope, mesh=getattr(geometry, '_indexed', None), budget=budget, cancel=cancel)"),
        ('R.decoded(saved.value._metadata, budget=budget, cancel=cancel)',
         '_HC.ledger_access(saved.value, budget, cancel, R)'),
        ('with R.codec(view, budget=budget, cancel=cancel):',
         'with _HC.ledger_codec(view, budget, cancel, R):'),
        ("R.stream_hash(dict(metadata=origin, arrays={k: dict(shape=list(v.shape),\n"
         "                        sha256=sha256(memoryview(v).cast('B')).hexdigest()) for k,v in call_arrays.items()}), cancel)",
         '_HC.call_identity(origin, call_arrays, R, cancel)'),
        ("exterior = {row['cell_id']: row for row in current['cells']}",
         "exterior = _HC.endpoint_cells(current['cells'])"),
        ("float(collar_state.fields.array('enthalpy_j').flat[row['index']])",
         "_collar_value(collar_state.fields.array('enthalpy_j'), row['index'])"),
        ('exchange_identity = R.stream_hash(exchange, cancel)',
         'exchange_identity = _SV.identity(exchange, lambda value: R.stream_hash(value, cancel))'),
        ('        views.__exit__(None, None, None)',
         '        encoded_plan = _HC.owned_plan_bytes(plan, work, budget, cancel, R, I._json)\n'
         '        views.__exit__(None, None, None)'),
        ('_plan=I._json(plan)', '_plan=encoded_plan'),
    ), scope='with _SV.access(exchange) as exchange:')
    # Only the decoder dispatch changes. The inherited scalar operations and
    # order within the original equations body are untouched.
    source = V._replace(source, 'ar = R._ProjectionArithmetic(', 'ar = _HC.ledger_arithmetic(R)(', 2)
    source += ('\nimport heat_cold_patch as _HC\nimport spatial_indexed_patch as _INDEXED_SPATIAL\n'
               'import private_heat_indexed_runtime as _INDEXED_HEAT\n'+RAM._ROUTE+_COLLAR)
    after = {n.name: n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}
    for name, original_ast in equations.items():
        node = after[name]
        if name == '_equations_body':
            # Ignore exactly the wrapper constructor substitution, not any
            # arithmetic or validation statement.
            part = ast.unparse(node).replace('_HC.ledger_arithmetic(R)', 'R._ProjectionArithmetic')
            actual = ast.dump(ast.parse(part).body[0])
        else:
            actual = ast.dump(node)
        if actual != original_ast:
            raise V.ContractError('compact restored binding changed '+name)
    compile(source, '<private-heat-restored-r10>', 'exec')
    return source
