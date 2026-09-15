"""Private retained numerical callables with fresh, deduplicated source gates.

Only the internals of one verification pass share reads. A later identity,
verify or backend gate creates a new Reader; calculations never share a gate.
No retained module globals or sealed graph are mutated.
"""
from types import SimpleNamespace
from work.generator_upgrade_r14 import provenance as ground
from work.generator_upgrade_r14 import erosion as old_erosion, terrain as old_terrain
from work.generator_upgrade_r16 import regional as original, columns
from work.generator_upgrade_r24.verification import Reader, _Clones
from work.generator_upgrade_r28.preflight import clone


def guarded(source, method, *args, **kwargs):
    # The retained backend performs its initial full seal and establishes its
    # captured identity before a private namespace copies those bindings.
    ground.backend()
    reader, primary = Reader(), None
    try:
        view = _Clones(reader).module(source)
        if method == 'verify_backend':
            target = clone(source.verify_backend, **vars(view))
        else:
            target = getattr(view, method)
        return target(*args, **kwargs)
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            reader.finish()
        except BaseException as error:
            if primary is not None:
                primary.geology_source_cleanup_errors = [str(error)]
            else:
                raise


def gate(source):
    view = SimpleNamespace(**vars(source))
    for name in ('identity', 'verify', 'verify_backend'):
        if hasattr(source, name):
            def invoke(*args, _name=name, **kwargs):
                return guarded(source, _name, *args, **kwargs)
            setattr(view, name, invoke)
    return view


ground_gate = gate(ground)
regional_gate = gate(original.p)
build_columns = clone(columns.build_columns, provenance=ground_gate)
erosion = SimpleNamespace(**vars(old_erosion))
erosion._advance = clone(old_erosion._advance, provenance=ground_gate)
erosion.advance = clone(old_erosion.advance, provenance=ground_gate, _advance=erosion._advance)
terrain = SimpleNamespace(**vars(old_terrain))
terrain.trial = clone(old_terrain.trial, p=ground_gate, erosion=erosion)
regional = SimpleNamespace(**vars(original))
regional.p = regional_gate
regional.build = clone(original.build, p=regional_gate, build_columns=build_columns)
regional.terrain_step = clone(original.terrain_step, p=regional_gate, terrain=terrain)
