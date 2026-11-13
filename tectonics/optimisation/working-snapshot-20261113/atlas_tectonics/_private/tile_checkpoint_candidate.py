"""Qualification-only, identity-bound completed-tile storage; not IV1 state."""
import hashlib
import json
import sqlite3
import sys
from contextlib import ExitStack
from fractions import Fraction


class AttemptMeter:
    """One attempt's charged tile-arena work; common setup is excluded."""
    def __init__(self, ceiling, tile_limit):
        if type(ceiling) is not int or type(tile_limit) is not int or not 0 < tile_limit <= ceiling:
            raise ValueError('invalid attempt work policy')
        self.ceiling, self.tile_limit = ceiling, tile_limit
        self.used, self.active = 0, None

    def begin(self, generation_remaining):
        if self.active is not None:
            raise ValueError('tile accounting already active')
        if self.ceiling-self.used < self.tile_limit or generation_remaining < self.tile_limit:
            return False
        self.active = 0
        return True

    def charge(self, count):
        if (self.active is None or type(count) is not int or count < 0 or
                self.active+count > self.tile_limit or self.used+count > self.ceiling):
            raise ValueError('attempt tile-work allowance exceeded')
        self.active += count
        self.used += count

    def finish(self):
        if self.active is None:
            raise ValueError('tile accounting not active')
        used = self.active
        self.active = None
        return used


def summarize_attempt(events, *, ceiling=64000000, tile_limit=2000000):
    """Account logged tile work; an unmatched begin consumes its full reserve."""
    used, active = 0, None
    for row in events:
        stage = row.get('stage')
        if stage == 'TILE_ATTEMPT_BEGIN':
            if (active is not None or row.get('attempt_before') != used or
                    row.get('reserved_work') != tile_limit or used+tile_limit > ceiling):
                raise ValueError('invalid tile attempt begin')
            active = tuple(row['tile'])
        elif stage == 'TILE_ATTEMPT_END':
            charged = row.get('tile_charged')
            if (active is None or tuple(row['tile']) != active or type(charged) is not int or
                    not 0 <= charged <= tile_limit or row.get('attempt_charged') != used+charged):
                raise ValueError('invalid tile attempt end')
            used += charged
            active = None
    return dict(accounted_work=used + (tile_limit if active is not None else 0),
                ended_work=used, unfinished_tile=active, conservative_debit=tile_limit if active is not None else 0)


def reconcile_attempt(output, *, required_terminal=None, ceiling=64000000, tile_limit=2000000):
    """Reconcile existing stdout records; malformed or ambiguous data refuses."""
    events = []
    for line in output.splitlines():
        if not line.lstrip().startswith(b'{'):
            continue
        try:
            row = json.loads(line)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError('torn or malformed attempt record') from exc
        if type(row) is dict:
            events.append(row)
    terminal_stages = {'STREAMED_SOURCE_GRID_PARTIAL', 'STREAMED_SOURCE_GRID_SWEEP'}
    terminals = [(i,row) for i,row in enumerate(events) if row.get('stage') in terminal_stages]
    if len(terminals) > 1:
        raise ValueError('ambiguous attempt terminal')
    starts = [(i,row) for i,row in enumerate(events) if row.get('stage') == 'ATTEMPT_ACCOUNTING_START']
    if (len(starts) != 1 or starts[0][1].get('attempt_ceiling') != ceiling or
            starts[0][1].get('tile_limit') != tile_limit or
            starts[0][1].get('scope') != 'tile-arena-charges-only;pre-arena-setup-io-freshness-fold-excluded' or
            any(row.get('stage') in ('TILE_ATTEMPT_BEGIN','TILE_ATTEMPT_END') for row in events[:starts[0][0]]) or
            terminals and terminals[0][0] < starts[0][0]):
        raise ValueError('attempt accounting start missing or ambiguous')
    summary = summarize_attempt(events, ceiling=ceiling, tile_limit=tile_limit)
    if terminals:
        position, terminal = terminals[0]
        if (required_terminal is not None and terminal['stage'] != required_terminal or
                summary['unfinished_tile'] is not None or
                terminal.get('attempt_tile_work') != summary['ended_work'] or
                terminal.get('attempt_tile_work_limit') != ceiling or
                terminal.get('common_setup_arithmetic_excluded') is not True or
                any(row.get('stage') in ('TILE_ATTEMPT_BEGIN','TILE_ATTEMPT_END') for row in events[position+1:])):
            raise ValueError('attempt terminal/accounting differs')
        return dict(summary, terminal=terminal['stage'])
    if required_terminal is not None:
        raise ValueError('required attempt terminal absent')
    return dict(summary, terminal=None)


def callback_accounting(output):
    """Conservatively resolve a terminated attempt's existing stdout."""
    try:
        return dict(reconcile_attempt(output), unresolved=False)
    except (ValueError, TypeError, KeyError):
        return dict(accounted_work=64000000, ended_work=None, unfinished_tile=None,
                    conservative_debit=64000000, terminal=None, unresolved=True)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def tile_digest(generation, key, raw):
    return hashlib.sha256(canonical([generation, *key]) + b'\0' + raw).hexdigest()


def encode(value):
    if not isinstance(value, Fraction) or value < 0:
        raise ValueError('invalid exact tile volume')
    return [format(value.numerator, 'x'), format(value.denominator, 'x')]


def decode(value):
    if (type(value) is not list or len(value) != 2 or
            any(type(x) is not str or not x or any(c not in '0123456789abcdef' for c in x)
                or (len(x) > 1 and x[0] == '0') for x in value)):
        raise ValueError('invalid canonical fraction')
    n, d = (int(x, 16) for x in value)
    if d <= 0 or encode(Fraction(n, d)) != value:
        raise ValueError('noncanonical fraction')
    return Fraction(n, d)


def expected_by_tile(rows, coarse, fine, band):
    """Derive each tile's exterior IDs from the graph, including zero bookings."""
    if len(coarse) != 3 or len(fine) != 3:
        raise ValueError('invalid grid dimensions')
    mapping = []
    for axis in range(3):
        a, b = coarse[axis], fine[axis]
        if any(x >= y for x, y in zip(a, a[1:])) or any(x >= y for x, y in zip(b, b[1:])):
            raise ValueError('unordered grid')
        axis_map = []
        for lo, hi in zip(b, b[1:]):
            choices = [i for i, (x, y) in enumerate(zip(a, a[1:])) if x <= lo and hi <= y]
            if len(choices) != 1:
                raise ValueError('fine tile crosses or escapes coarse grid')
            axis_map.append(choices[0])
        mapping.append(axis_map)
    voxel_ids = {}
    identities = set()
    for row in rows:
        if row.get('kind') != 'exterior' or row.get('radial_band') != band:
            continue
        ident = row['cell_id']
        voxel = tuple(row['voxel_index'])
        if (ident in identities or len(voxel) != 3 or
                any(type(i) is not int or i < 0 or i >= len(coarse[j])-1 for j, i in enumerate(voxel))):
            raise ValueError('invalid graph exterior inventory')
        identities.add(ident)
        voxel_ids.setdefault(voxel, set()).add(ident)
    from itertools import product
    return {tuple(index): voxel_ids.get(tuple(mapping[j][index[j]] for j in range(3)), set())
            for index in product(*(range(len(axis)) for axis in mapping))}


class Tiles:
    def __init__(self, path, generation):
        self.generation = digest(generation)
        self.tile_work_limit = generation.get('tile_ceiling', 1000000)
        if type(self.tile_work_limit) is not int or self.tile_work_limit not in (1000000,2000000):
            raise ValueError('invalid checkpoint tile limit')
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS generation (id TEXT PRIMARY KEY, payload BLOB NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS tile (generation TEXT NOT NULL, band INTEGER NOT NULL, i INTEGER NOT NULL, j INTEGER NOT NULL, k INTEGER NOT NULL, payload BLOB NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(generation,band,i,j,k))')
        raw = canonical(generation)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            rows = self.db.execute('SELECT id,payload FROM generation').fetchall()
            if rows and rows != [(self.generation, raw)]:
                raise ValueError('checkpoint generation differs')
            if not rows:
                self.db.execute('INSERT INTO generation VALUES (?,?)', (self.generation, raw))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def read(self, key, expected_ids):
        band, i, j, k = key
        length = self.db.execute('SELECT length(payload) FROM tile WHERE generation=? AND band=? AND i=? AND j=? AND k=?',
                                 (self.generation, band, i, j, k)).fetchone()
        if length is None:
            return None
        if type(length[0]) is not int or not 0 < length[0] <= 8 << 20:
            raise ValueError('checkpoint tile payload exceeds limit')
        row = self.db.execute('SELECT payload,digest FROM tile WHERE generation=? AND band=? AND i=? AND j=? AND k=?',
                              (self.generation, band, i, j, k)).fetchone()
        if row is None:
            raise ValueError('checkpoint tile disappeared')
        raw, pin = row
        if len(raw) > 8 << 20:
            raise ValueError('checkpoint tile payload exceeds limit')
        if tile_digest(self.generation, key, raw) != pin:
            raise ValueError('checkpoint payload digest differs')
        payload = json.loads(raw)
        if canonical(payload) != raw or payload.get('key') != list(key):
            raise ValueError('checkpoint payload identity differs')
        pairs = payload.get('volumes')
        if type(pairs) is not list or any(type(p) is not list or len(p) != 2 or type(p[0]) is not str for p in pairs):
            raise ValueError('checkpoint volume inventory malformed')
        ids = [p[0] for p in pairs]
        if ids != sorted(expected_ids) or len(ids) != len(set(ids)):
            raise ValueError('checkpoint tile component inventory differs')
        volumes = [decode(value) for _, value in pairs]
        if type(payload.get('work')) is not int or not 0 <= payload['work'] <= self.tile_work_limit:
            raise ValueError('checkpoint work differs')
        result = payload.get('tile_result')
        if (payload.get('coverage') != 'PASS' or type(result) is not dict or
                result.get('tile') != [i, j, k] or result.get('band') != band or
                result.get('tile_components') != len(ids) or result.get('tile_work') != payload['work'] or
                any(type(result.get(field)) is not int or result[field] < 0
                    for field in ('zero_tested', 'targets', 'pieces', 'labels')) or
                result['zero_tested'] > len(ids) or 'peak_reserved_bytes' in result):
            raise ValueError('checkpoint tile result differs')
        shell = decode(payload['shell'])
        try:
            result_shell = Fraction(result['shell_volume'])
            eligible = Fraction(result['exact_volume'])
            native = Fraction(result['fixed_native'])
            excluded = Fraction(result['fixed_excluded'])
        except (ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
            raise ValueError('checkpoint tile measures malformed') from exc
        if (min(eligible, native, excluded) < 0 or shell != result_shell or
                shell != eligible + native + excluded or sum(volumes, Fraction(0)) != eligible):
            raise ValueError('checkpoint tile conservation differs')
        return payload

    def insert(self, key, expected_ids, payload):
        raw = canonical(payload)
        pin = tile_digest(self.generation, key, raw)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            old = self.read(key, expected_ids)
            if old is not None:
                if canonical(old) != raw:
                    raise ValueError('conflicting tile replay')
            else:
                self.db.execute('INSERT INTO tile VALUES (?,?,?,?,?,?,?)',
                                (self.generation, *key, raw, pin))
                self.read(key, expected_ids)
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def keys(self):
        return {tuple(row) for row in self.db.execute('SELECT band,i,j,k FROM tile WHERE generation=?', (self.generation,))}


def fold_completed(store, expected, bookings, budget, *, work, shell_count, total_work_limit, require_positive=True):
    """Fold unique complete rows with bounded live exact-number reservations."""
    wanted = {(0, *index) for index in expected}
    if store.keys() != wanted:
        raise ValueError('checkpoint tile set differs')
    ids = set().union(*expected.values())
    if ids != set(bookings):
        raise ValueError('checkpoint exterior inventory differs')
    sums, reservations = {}, {}
    total_work = shells = 0
    with ExitStack() as stack:
        # Fixed charges include dictionary/index and serialisation overhead;
        # exact values are charged separately, including their replacement.
        stack.enter_context(budget.reserve(8 << 20, category='qualification-fold'))
        def release_values():
            for lease in reservations.values():
                lease.__exit__(None, None, None)
        stack.callback(release_values)
        for index in sorted(expected):
            key = (0, *index)
            row = store.read(key, expected[index])
            if row is None or row.get('coverage') != 'PASS':
                raise ValueError('checkpoint tile is incomplete')
            total_work += row['work']
            if total_work > total_work_limit:
                raise ValueError('checkpoint total work exceeds limit')
            shell = decode(row['shell'])
            shells += shell > 0
            for ident, encoded in row['volumes']:
                value = decode(encoded)
                if bookings[ident] == 0 and value:
                    raise ValueError('zero booking has nominal volume')
                prior = sums.get(ident, Fraction(0))
                with work((prior, value), budget):
                    total = prior + value
                size = 1024 + 4 * (sys.getsizeof(total.numerator) + sys.getsizeof(total.denominator))
                lease = budget.reserve(size, category='qualification-fold')
                lease.__enter__()
                old = reservations.get(ident)
                reservations[ident] = lease
                sums[ident] = total
                if old is not None:
                    old.__exit__(None, None, None)
        if shells != shell_count or set(sums) != ids:
            raise ValueError('checkpoint fold census differs')
        positive = {ident for ident in ids if bookings[ident] > 0}
        if (require_positive and any(sums[ident] <= 0 for ident in positive)) or any(sums[ident] for ident in ids-positive):
            raise ValueError('checkpoint fold component totals differ')
        positive = {ident for ident in positive if sums[ident] > 0}
        encoded_bound = sum(len(ident) + 128 + (sums[ident].numerator.bit_length() + sums[ident].denominator.bit_length() + 3)//4
                            for ident in positive)
        if encoded_bound > 8 << 20:
            raise ValueError('checkpoint folded output exceeds limit')
        result = dict(generation=store.generation, tiles=len(wanted), positive_shell=shells,
                      total_work=total_work, positive_component_sums=[[i, encode(sums[i])] for i in sorted(positive)])
        # The caller must bind this result to final imports and the successful
        # tracked process; a folded value alone is not a terminal result.
        result['payload_digest'] = digest(result)
        return result
