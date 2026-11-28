"""Prepare the retained control's actual plans WITHOUT funding or initial state.

This is a private adapter for the existing radial verification case, not a
generic planet importer. It preserves the source/constitutive/native/collar
preparation verbatim and stops before the first fresh-funding operation. The
caller must supply the independently authenticated old funding and transferred
state; this helper cannot manufacture them or authorise migration.
"""
from pathlib import Path
import types


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
    text = raw.decode('utf8').replace('\r\n', '\n')
    prefix, tail = text.split(ANCHOR)
    old = 'def radial_differential_fixture(*, budget=None, reference_pa=0., pressure_space=\'q1\','
    new = 'def prepare_saved_plans(*, budget=None, reference_pa=0., pressure_space=\'q1\','
    if prefix.count(old) != 1:
        raise ValueError('source-text anchor missing or ambiguous: '+old[:100])
    return prefix.replace(old, new, 1)+REPLACEMENT


def load_preparation(source):
    """Compile the derived text, never patch an imported native/control module."""
    source = Path(source)
    raw = source.read_bytes()
    text = transformed_source(raw)
    module = types.ModuleType('atlas_private_saved_plan_preparation')
    module.__file__ = str(source)+'[plan-only-restart]'
    exec(compile(text, module.__file__, 'exec'), module.__dict__)
    return module.prepare_saved_plans
