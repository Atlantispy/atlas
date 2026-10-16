"""Growth successor (a) + (b): a reviewed identity successor for NEW intervals only.

Source transform of atlas_tectonics/integration_differential_geometry.py for the
Step 10 (WP9) composition. Approved by the coordinator under Michael's delegated
authority (plan-order review section 7b, items 3a and 3b). Interval-1 records,
receipts and the Step 9 migration are untouched; readers accept both generations
because no reader looks a constraint up except by a component literal's name.

(a) Unreferenced support constraints are not stored. After partition_physical_support
    has decided its components, every constraint that no component literal names is
    dropped from the issued support record (NEW intervals only: the static/initial
    partition, the shared start state, is unchanged). Proof that nothing reads them:
    see the hand-off (consumer census). Effect: smaller supports and no pose/validation
    work for them; identical components, literals and logical cell ids; changed
    support ids.

(b) Charts proved empty are not seeded. In prepare_interval_partition, after the
    carried regions are built and before births are declared, a carried chart whose
    cone is proved to have zero volume at the parent interval's END INSTANT is
    dropped. Every next-interval literal is that instant's plane rigidly rotated by
    one shared R(s) (same plate rate in every snapshot wrapper; checked), and the
    radial shell is rotation invariant, so the chart is empty for the WHOLE next
    interval and every descendant (bounded by its material literals) is empty too.
    Certificates, in order, all exact RC1 functions:
      C1 _consistent_literals is None (opposite duplicate rigid planes; time free);
      C4 _common_ray_cone_zero_volume at [T, T] on the inner constraints (no voxel);
      C5 zero volume at T in EVERY grid voxel (regular, native, excluded alike),
         each by RC1's own root leaf certificate (levels 0/16/32). The grid must
         cover the whole funded radial domain (checked here, as _assemble_partition
         does); otherwise nothing is dropped.
    An unproved chart is kept exactly as before. Births are never touched.
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    'fc9dd85e002fe54db6e409ebe89083996f62611c40d958a5a1e60184f3424253': 'RC1 composed-r1 runtime-src',
}

ANCHOR_A = ("        result = dict(schema='atlas.differential-physical-support.v1', "
            "interval_id=None if static else identity_id,\n")
HOOK_A = ("        if not static:\n"
          "            # Growth successor (a), new intervals only: store only the\n"
          "            # constraints some component literal names (none other is read).\n"
          "            _used = {name for part in components for name, _ in part['constraints']}\n"
          "            constraints = {name: value for name, value in constraints.items() if name in _used}\n"
          "            del _used\n")

ANCHOR_B = '    # Actual finite birth declarations, not a fake old patch/source key. The\n'
HOOK_B = ("    # Growth successor (b), new intervals only: a carried chart proved empty\n"
          "    # at the parent end instant is empty for this whole interval; never seed it.\n"
          "    regions = _growth_drop_empty_charts(regions, step, old_time, old['grid_lines'], collar, budget)\n")

ANCHOR_DEF = 'def prepare_interval_partition(parent_partition, interval, funding, sphere, collar, *,\n'
HELPER = '''
def _growth_chart_empty(region, old_time, grid, arena, budget):
    """Exact proof that a carried chart's cone has zero volume at the parent end instant.

    Returns the certificate name or None. See the growth_successor transform docstring.
    """
    chart = region.get('source_constraint_chart')
    if region.get('kind') != 'inherited' or chart is None:
        return None
    literals = tuple((name, sign) for name, sign in chart['literals'])
    wrapped = chart['constraints']
    rates = {_encoded(wrapped[name].get('angular_velocity_rad_s')) for name, _ in literals}
    if (not literals or len(rates) != 1 or
            any(wrapped[name].get('kind') != 'snapshot-rotated' or
                W._decode(wrapped[name]['snapshot_offset_s']) != old_time for name, _ in literals)):
        return None
    inner = {name: wrapped[name]['constraint'] for name, _ in literals}
    identities = {name: _plane_identity(wrapped[name]) for name, _ in literals}
    if _consistent_literals(literals, identities) is None:
        return 'C1-opposite-duplicate-rigid-plane'
    for level in (0, 24):
        if _common_ray_cone_zero_volume(literals, inner, old_time, old_time, level, arena) is not None:
            return 'C4-instant-common-ray-cone'
    g = region['radial_layer']
    layer = V.RadialLayer(*(W._decode(g[k]) for k in ('radius_m', 'top_depth_m', 'bottom_depth_m')), budget=budget)
    lower2, upper2 = layer.bottom_radius_m**2, layer.top_radius_m**2
    # Voxels holding parent pieces first: a positive chart fails fast there.
    first = set(region.get('parent_cells', {}))
    ordered = sorted(grid, key=lambda item: (','.join(map(str, item[0])) not in first, item[0]))
    for at, box in ordered:
        low, high = box._radial_bounds()
        if low >= upper2 or high <= lower2:
            continue
        zero = False
        for level in (0, 16, 32):
            detail = {}
            bounds, _, _, _ = _component_volume_certificate(layer, box, literals, inner, old_time, level,
                                                            arena, detail=detail)
            if bounds[1] == 0:
                zero = True
                break
            if not detail.get('angular_inner_empty'):
                break
        if not zero:
            return None
    return 'C5-every-voxel-instant-zero'


def _growth_drop_empty_charts(regions, step, old_time, grid_lines, collar, budget):
    """Growth successor (b): the carried regions minus charts proved empty (exact)."""
    if not regions:
        return regions
    base = collar.cell_geometries()[0]
    origin, basis = base.origin_m, base.basis
    lines = tuple(tuple(map(W._decode, axis)) for axis in grid_lines)
    radius = W._decode(step['radius_m'])
    translation = tuple(sum(basis[k][j]*origin[k] for k in range(3)) for j in range(3))
    if any(line[0] > -radius-t or line[-1] < radius-t for line, t in zip(lines, translation)):
        return regions   # coverage not proved here: drop nothing
    grid = [(at, V.CartesianCell(tuple(lines[j][at[j]] for j in range(3)),
                                 tuple(lines[j][at[j]+1] for j in range(3)), origin, basis, budget=budget))
            for at in product(*(range(len(a)-1) for a in lines))]
    kept = {}
    with B._Arena(budget) as arena:
        for key in sorted(regions):
            if _growth_chart_empty(regions[key], old_time, grid, arena, budget) is None:
                kept[key] = regions[key]
    return kept


'''


def _once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('growth-successor anchor must occur exactly once: ' + old[:70])
    return source.replace(old, new)


def transform(source, *, allow_unreviewed_input=False):
    """Transformed geometry source. Only the reviewed RC1 input by default; a composer
    stacking it on another transform passes allow_unreviewed_input and re-runs parity."""
    if '_growth_drop_empty_charts' in source:
        raise ValueError('growth successor already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('growth transform input is not the reviewed geometry; pass allow_unreviewed_input and re-run parity')
    if 'from itertools import' not in source or 'product' not in source:
        raise ValueError('module must already import itertools.product')
    source = _once(source, ANCHOR_A, HOOK_A + ANCHOR_A)
    source = _once(source, ANCHOR_B, HOOK_B + ANCHOR_B)
    source = _once(source, ANCHOR_DEF, HELPER.lstrip('\n') + ANCHOR_DEF)
    return source


def describe(source):
    digest = sha256(source.encode()).hexdigest()
    return dict(input_sha256=digest, known_input=KNOWN_INPUT_SHA256.get(digest),
                output_sha256=sha256(transform(source).encode()).hexdigest())
