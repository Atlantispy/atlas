"""Build-only r9 -> r10 checkpoint transform; equation body stays identical."""
import ast
from hashlib import sha256

import spatial_validation_patch as V

BASE_SHA256 = '95d0840eeedbef6b3b6cea53d737cdda32fb67330ab0016a356990c2d0dea2c9'


def transform(source):
    if type(source) is not str or sha256(source.encode()).hexdigest() != BASE_SHA256:
        raise V.ContractError('exact original r9 checkpoint consumer required')
    before = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_equations')
    source = V._replace(source, "SCHEMA = 'atlas.private.i12-detached-checkpoint-consumer.r9'",
                        "SCHEMA = 'atlas.private.i12-detached-checkpoint-consumer.r10'")
    source = V._replace(source, 'R.decoded(snapshot._metadata, budget=call._budget, cancel=cancel)',
                        '_HC.ledger_access(snapshot, call._budget, cancel, R)')
    source = V._replace(source, 'ar = R._ProjectionArithmetic(', 'ar = _HC.ledger_arithmetic(R)(')
    source = V._replace(source, 'bindings=bindings, budget=call._budget, cancel=cancel)',
                        "bindings=bindings, scope=store.scope, mesh=getattr(call._geometry, '_indexed', None), budget=call._budget, cancel=cancel)")
    source += '\nimport heat_cold_patch as _HC\n'
    after = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_equations')
    if ast.dump(before) != ast.dump(after):
        raise V.ContractError('r10 changed exact checkpoint equations')
    compile(source, '<private-heat-checkpoint-r10>', 'exec')
    return source
