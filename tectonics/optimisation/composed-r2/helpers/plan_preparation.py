"""Prepare the retained control's actual plans WITHOUT funding or initial state.

This is a private adapter for the existing radial verification case, not a
generic planet importer. It preserves the source/constitutive/native/collar
preparation verbatim and stops before the first fresh-funding operation. The
caller must supply the independently authenticated old funding and transferred
state; this helper cannot manufacture them or authorise migration.
"""
from hashlib import sha256
from pathlib import Path
import types


SOURCE_SHA256 = 'a5bdfa249d594a65757ab3b48b93690c648dc2b6125e39752ec4ac090a29b55f'
ANCHOR = '            initial_funding = fund(source, owner, collar, budget)\n'
REPLACEMENT = '''            # Preparation only. No material is booked or state initialised.
            trench = next(b for b in sphere.network.boundaries if b.kind == 'trench')
            sink = Sink(trench.boundary_id, (('test:finite-slab-receiver', 1.),))
            yield dict(source=source, volume_map=volume_map, material=material, law=law,
                native=native, owner=owner, collar=collar, budget=budget,
                registry=registry, supplies=supplies,
                birth_columns={s.source: column for s in supplies}, sinks=(sink,))
'''


def transformed_source(raw):
    if sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError('saved control preparation source changed')
    text = raw.decode('utf8').replace('\r\n', '\n')
    if text.count(ANCHOR) != 1:
        raise ValueError('fresh funding boundary missing or ambiguous')
    prefix, tail = text.split(ANCHOR)
    # This exact source ends at the contextmanager yield. A new trailing
    # function cannot silently disappear from a future, unreviewed source.
    if not tail.rstrip().endswith('birth_columns={s.source: column for s in supplies}, sinks=(sink,), finite_rows=finite_rows)'):
        raise ValueError('prepared case tail differs')
    old = 'def radial_differential_fixture(*, budget=None, reference_pa=0., pressure_space=\'q1\','
    new = 'def prepare_saved_plans(*, budget=None, reference_pa=0., pressure_space=\'q1\','
    if prefix.count(old) != 1:
        raise ValueError('prepared control function signature differs')
    return prefix.replace(old, new, 1)+REPLACEMENT


def load_preparation(source):
    """Compile checked bytes, never patch an imported native/control module."""
    source = Path(source)
    raw = source.read_bytes()
    text = transformed_source(raw)
    module = types.ModuleType('atlas_private_saved_plan_preparation')
    module.__file__ = str(source)+'[plan-only-restart]'
    exec(compile(text, module.__file__, 'exec'), module.__dict__)
    if sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError('saved preparation source changed during import')
    return module.prepare_saved_plans
