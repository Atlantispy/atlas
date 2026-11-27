"""Independent scalar piecewise W06 paths and FIRST-exit accounting.

No production module, trajectory, intersection or thermal integrator is imported.
Paths integrate each declared velocity interval directly. Each birth interval is
partitioned by scalar boundary preimages at semantic event times; a midpoint
parcel determines its first exit. Thermal fields reuse only the independent
Step-3 scalar adaptive age/depth reference supplied by the caller.

Offsets are forward seconds from the named onset, never geological Ma BP. The
supported fixed-window route permits outward active intervals and ALL-ZERO
inactive intervals; reentry, jumps and cross-side reassignment are refused.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math

import numpy as np


SIDES = ('left', 'right')


def case_events(case, scenario='motion_switch'):
    """Expand the compact frozen case into independent SI event dictionaries."""
    specification = case['scenarios'][scenario]
    if 'events' in specification:
        events = deepcopy(specification['events'])
    else:
        base = specification['base_scenario']
        if 'events' not in case['scenarios'][base]:
            raise ValueError('only a single explicit frozen-case inheritance is supported')
        events = deepcopy(case['scenarios'][base]['events'])
        events[1].update(deepcopy(specification['replace_event_1']))
    for event in events:
        event['offset_s'] = event.pop('offset_years')*case['seconds_per_year']
        for side in (*SIDES, 'ridge'):
            event[side+'_velocity_m_s'] = event.pop(side+'_velocity_m_per_year')/case['seconds_per_year']
        event['reassignments'] = tuple(event['reassignments'])
    return tuple(events)


@dataclass(frozen=True)
class ReferenceParcel:
    side: str
    position_m: float
    birth_offset_s: float
    cooling_start_offset_s: float
    age_s: float
    birth_event_id: str
    birth_source_id: str
    birth_plate_id: str
    plate_id: str
    ridge_id: str
    thermal_model_id: str
    ownership_sources: tuple[str, ...]


@dataclass(frozen=True)
class ReferenceStrip:
    side: str
    left_m: float
    right_m: float
    birth_offset_left_s: float
    birth_offset_right_s: float
    birth_event_id: str
    birth_source_id: str
    birth_plate_id: str
    plate_id: str
    ridge_id: str
    thermal_model_id: str
    ownership_sources: tuple[str, ...]

    @property
    def cooling_offset_left_s(self):
        return self.birth_offset_left_s

    @property
    def cooling_offset_right_s(self):
        return self.birth_offset_right_s


@dataclass(frozen=True)
class ReferenceRegion:
    """One birth-time interval with common resident/first-exit classification.

Birth and exit endpoints are PAIRED in increasing birth order, not sorted by
exit age. Width is the birth Jacobian times that birth-time interval. For a
resident interval the exit fields are None and its age endpoints refer to now.
    """
    birth_side: str
    birth_first_s: float
    birth_last_s: float
    width_m: float
    side: str | None
    exit_first_s: float | None
    exit_last_s: float | None
    age_first_s: float
    age_last_s: float
    birth_event_id: str
    birth_source_id: str
    birth_plate_id: str
    plate_id: str
    ridge_id: str
    exit_event_id: str | None
    exit_source_id: str | None
    thermal_model_id: str
    ownership_sources: tuple[str, ...]


class PiecewiseHistoryReference:
    """Finite independent kinematic reference, with no numerical time stepping."""
    def __init__(self, events, *, end_s, bounds_m, thermal_model_id):
        self.events = tuple(deepcopy(dict(event)) for event in events)
        self.end_s = float(end_s)
        self.bounds_m = tuple(float(value) for value in bounds_m)
        self.thermal_model_id = thermal_model_id
        if (not self.events or not math.isfinite(self.end_s) or self.end_s <= 0.
                or len(self.bounds_m) != 2 or not all(map(math.isfinite, self.bounds_m))
                or self.bounds_m[0] >= self.bounds_m[1]
                or not isinstance(thermal_model_id, str) or not thermal_model_id):
            raise ValueError('explicit finite history, window and thermal provenance required')
        for index, event in enumerate(self.events):
            for key in ('offset_s', 'ridge_position_m', 'left_velocity_m_s',
                        'right_velocity_m_s', 'ridge_velocity_m_s'):
                if not math.isfinite(event[key]):
                    raise ValueError('non-finite declared history')
            if type(event['active']) is not bool:
                raise ValueError('explicit active/inactive state required')
            for key in ('left_plate_id', 'right_plate_id', 'ridge_id', 'event_id', 'source_id'):
                if not isinstance(event[key], str) or not event[key]:
                    raise ValueError('explicit history/ownership provenance required')
            if event['left_plate_id'] == event['right_plate_id']:
                raise ValueError('distinct physical sides required')
            u, v, r = (event[key] for key in ('left_velocity_m_s', 'right_velocity_m_s', 'ridge_velocity_m_s'))
            if event['active']:
                if not (u <= 0. <= v and u < r < v):
                    raise ValueError('outward, strictly opening active motion required; reentry unsupported')
            elif u != 0. or v != 0. or r != 0.:
                raise ValueError('only explicit all-zero welded intervals are supported')
            if index == 0:
                if event['offset_s'] != 0. or event['reassignments']:
                    raise ValueError('history must begin at onset without a reassignment')
            else:
                previous = self.events[index-1]
                duration = event['offset_s']-previous['offset_s']
                if duration <= 0.:
                    raise ValueError('strictly ordered semantic event times required')
                continuous = math.fsum((previous['ridge_position_m'], previous['ridge_velocity_m_s']*duration))
                if event['ridge_position_m'] != continuous or event['ridge_id'] != previous['ridge_id']:
                    raise ValueError('arbitrary ridge jump/reclassification is unsupported')
                transfers = event['reassignments']
                if len({transfer['side'] for transfer in transfers}) != len(transfers):
                    raise ValueError('duplicate side ownership transfer')
                for transfer in transfers:
                    side = transfer['side']
                    if (side not in SIDES or not transfer['source_id']
                            or transfer['from_plate_id'] != previous[side+'_plate_id']
                            or transfer['to_plate_id'] != event[side+'_plate_id']
                            or transfer['from_plate_id'] == transfer['to_plate_id']):
                        raise ValueError('complete explicit same-side reassignment required')
                for side in SIDES:
                    changed = previous[side+'_plate_id'] != event[side+'_plate_id']
                    if changed != any(transfer['side'] == side for transfer in transfers):
                        raise ValueError('owner changed without exactly one explicit source transfer')
            if event['offset_s'] >= self.end_s:
                raise ValueError('event outside finite declared history')
            stop = self.events[index+1]['offset_s'] if index+1 < len(self.events) else self.end_s
            end_ridge = math.fsum((event['ridge_position_m'], event['ridge_velocity_m_s']*(stop-event['offset_s'])))
            if not (self.bounds_m[0] < event['ridge_position_m'] < self.bounds_m[1]
                    and self.bounds_m[0] < end_ridge < self.bounds_m[1]):
                raise ValueError('ridge must remain strictly within the source window')

    def _time(self, time_s):
        time_s = float(time_s)
        if not math.isfinite(time_s) or not 0. <= time_s <= self.end_s:
            raise ValueError('time outside finite forward history')
        return time_s

    def _event_index(self, time_s):
        return max(i for i, event in enumerate(self.events) if event['offset_s'] <= time_s)

    def _event_end(self, index):
        return self.events[index+1]['offset_s'] if index+1 < len(self.events) else self.end_s

    def ridge_position(self, time_s):
        time_s = self._time(time_s)
        event = self.events[self._event_index(time_s)]
        return math.fsum((event['ridge_position_m'], event['ridge_velocity_m_s']*(time_s-event['offset_s'])))

    def _path(self, side, birth, time_s, birth_index):
        """Scalar integral of the parcel's trajectory, not a strip propagator."""
        event = self.events[birth_index]
        terms = [event['ridge_position_m'], event['ridge_velocity_m_s']*(birth-event['offset_s'])]
        for index in range(birth_index, len(self.events)):
            row = self.events[index]
            begin, end = max(birth, row['offset_s']), min(time_s, self._event_end(index))
            if end > begin:
                terms.append(row[side+'_velocity_m_s']*(end-begin))
        return math.fsum(terms)

    def _lineage(self, side, birth_index, until_index):
        return tuple(transfer['source_id'] for event in self.events[birth_index+1:until_index+1]
                     for transfer in event['reassignments'] if transfer['side'] == side)

    def parcel(self, side, birth_offset_s, time_s):
        """A named point born on an active half-open event interval."""
        time_s = self._time(time_s)
        birth = float(birth_offset_s)
        if side not in SIDES or not 0. <= birth <= time_s:
            raise ValueError('invalid parcel side or birth time')
        index = self._event_index(birth)
        row = self.events[index]
        if not row['active']:
            raise ValueError('inactive interval creates no parcel')
        current = self._event_index(time_s)
        return ReferenceParcel(side, self._path(side, birth, time_s, index), birth, birth,
            time_s-birth, row['event_id'], row['source_id'], row[side+'_plate_id'],
            self.events[current][side+'_plate_id'], row['ridge_id'], self.thermal_model_id,
            self._lineage(side, index, current))

    def _births(self, time_s):
        for index, event in enumerate(self.events):
            begin, end = event['offset_s'], min(time_s, self._event_end(index))
            if event['active'] and end > begin:
                for side in SIDES:
                    rate = abs(event['ridge_velocity_m_s']-event[side+'_velocity_m_s'])
                    yield index, side, begin, end, rate

    def strips(self, time_s):
        time_s = self._time(time_s)
        result = []
        current = self._event_index(time_s)
        for index, side, begin, end, rate in self._births(time_s):
            row = self.events[index]
            xa, xb = self._path(side, begin, time_s, index), self._path(side, end, time_s, index)
            left, right = sorted(((xa, begin), (xb, end)))
            if right[0] <= left[0]:
                raise ArithmeticError('positive birth interval lost its spatial measure')
            result.append(ReferenceStrip(side, left[0], right[0], left[1], right[1],
                row['event_id'], row['source_id'], row[side+'_plate_id'],
                self.events[current][side+'_plate_id'], row['ridge_id'], self.thermal_model_id,
                self._lineage(side, index, current)))
        result.sort(key=lambda strip: strip.left_m)
        for previous, following in zip(result[:-1], result[1:]):
            # Roundoff allowed only to diagnose exact independently computed
            # shared endpoints; no physical overlap is repaired or clamped.
            tolerance = 64*np.finfo(float).eps*max(1., abs(previous.right_m), abs(following.left_m))
            if abs(previous.right_m-following.left_m) > tolerance:
                raise ValueError('unsupported gap or overlapping material strips')
        return tuple(result)

    def _first_exit(self, side, birth, time_s, birth_index):
        """Walk scalar path segments chronologically and solve the first crossing."""
        boundary = self.bounds_m[0 if side == 'left' else 1]
        for index in range(birth_index, len(self.events)):
            row = self.events[index]
            begin, end = max(birth, row['offset_s']), min(time_s, self._event_end(index))
            velocity = row[side+'_velocity_m_s']
            if end <= begin or velocity == 0.:
                continue
            first = self._path(side, birth, begin, birth_index)
            last = self._path(side, birth, end, birth_index)
            crossed = last < boundary if side == 'left' else last > boundary
            if crossed:
                exit_s = begin+(boundary-first)/velocity
                if not begin <= exit_s <= end:
                    raise ArithmeticError('first-exit root outside its semantic interval')
                return index, exit_s
        return None

    def regions(self, time_s):
        """Full resident/first-exit birth intervals, independent of sampling cells."""
        time_s = self._time(time_s)
        result = []
        current = self._event_index(time_s)
        for index, side, begin, end, rate in self._births(time_s):
            row = self.events[index]
            # Boundary membership can change only where a scalar endpoint path
            # meets a boundary. These preimages split all first-exit intervals.
            cuts = {begin, end}
            checks = {time_s, *(min(time_s, self._event_end(j)) for j in range(index, len(self.events)))}
            for check in checks:
                if check < end:
                    continue
                xa, xb = self._path(side, begin, check, index), self._path(side, end, check, index)
                for boundary in self.bounds_m:
                    fraction = (boundary-xa)/(xb-xa)
                    if 0. < fraction < 1.:
                        cuts.add(begin+fraction*(end-begin))
            ordered = sorted(cuts)
            for first_birth, last_birth in zip(ordered[:-1], ordered[1:]):
                middle = first_birth+.5*(last_birth-first_birth)
                crossing = self._first_exit(side, middle, time_s, index)
                if crossing is None:
                    exit_side = exit_first = exit_last = exit_event = exit_source = None
                    age_first, age_last = time_s-first_birth, time_s-last_birth
                    owner_index = current
                else:
                    owner_index, _ = crossing
                    outgoing = self.events[owner_index]
                    boundary = self.bounds_m[0 if side == 'left' else 1]
                    velocity = outgoing[side+'_velocity_m_s']

                    def exit_at(birth):
                        start = max(birth, outgoing['offset_s'])
                        return start+(boundary-self._path(side, birth, start, index))/velocity

                    exit_first, exit_last = exit_at(first_birth), exit_at(last_birth)
                    age_first, age_last = exit_first-first_birth, exit_last-last_birth
                    exit_side, exit_event, exit_source = side, outgoing['event_id'], outgoing['source_id']
                result.append(ReferenceRegion(side, first_birth, last_birth, rate*(last_birth-first_birth),
                    exit_side, exit_first, exit_last, age_first, age_last, row['event_id'], row['source_id'],
                    row[side+'_plate_id'], self.events[owner_index][side+'_plate_id'], row['ridge_id'],
                    exit_event, exit_source, self.thermal_model_id, self._lineage(side, index, owner_index)))
        return tuple(result)

    def first_exits(self, time_s):
        return tuple(region for region in self.regions(time_s) if region.side is not None)

    def project(self, edges_m, time_s):
        """Scalar strip/cell intersections retaining EACH birth-age interval."""
        time_s = self._time(time_s)
        edges = np.asarray(edges_m, dtype=float)
        if (edges.ndim != 1 or edges.size < 2 or not np.isfinite(edges).all()
                or np.any(np.diff(edges) <= 0.) or edges[0] < self.bounds_m[0] or edges[-1] > self.bounds_m[1]):
            raise ValueError('ordered sampling edges within source window required')
        strips = self.strips(time_s)
        intersections = []
        ages = np.zeros(edges.size-1)
        valid = np.zeros(edges.size-1, dtype=bool)
        centre_strip = np.full(edges.size-1, -1, dtype=np.int64)
        width = np.zeros(edges.size-1)
        for cell, (left, right) in enumerate(zip(edges[:-1], edges[1:])):
            centre = left+(right-left)/2.
            centre_rank = None
            for index, strip in enumerate(strips):
                lo, hi = max(left, strip.left_m), min(right, strip.right_m)

                def birth_at(x):
                    fraction = (x-strip.left_m)/(strip.right_m-strip.left_m)
                    return strip.birth_offset_left_s+fraction*(strip.birth_offset_right_s-strip.birth_offset_left_s)

                if hi > lo:
                    youngest, oldest = sorted((time_s-birth_at(lo), time_s-birth_at(hi)))
                    intersections.append((cell, index, hi-lo, youngest, oldest))
                    width[cell] += hi-lo
                if strip.left_m <= centre <= strip.right_m:
                    # Semantic birth intervals are half-open: the newer birth
                    # stage owns a shared face. The active/fossil ridge itself
                    # remains valid, with a deterministic left-side tie break.
                    rank = (min(strip.birth_offset_left_s, strip.birth_offset_right_s), strip.side == 'left')
                    if centre_rank is None or rank > centre_rank:
                        centre_rank = rank
                        valid[cell] = True
                        ages[cell] = time_s-birth_at(centre)
                        centre_strip[cell] = index
        return dict(strips=strips, intersections=np.asarray(intersections, dtype=float).reshape(-1, 5),
            ocean_fraction=width/np.diff(edges), centre_age_s=ages, centre_valid=valid,
            centre_strip_index=centre_strip, created_width_m=math.fsum(
                rate*(end-begin) for _, _, begin, end, rate in self._births(time_s)),
            ridge_position_m=self.ridge_position(time_s))

    def material_accounts(self, time_s, phases, *, width_m):
        regions = self.regions(time_s)
        created = math.fsum(rate*(end-begin) for _, _, begin, end, rate in self._births(time_s))
        resident = math.fsum(region.width_m for region in regions if region.side is None)
        exports = [math.fsum(region.width_m for region in regions if region.side == side) for side in SIDES]
        result = []
        for phase in phases:
            scale = phase['density_kg_m3']*phase['thickness_m']*width_m
            born, here, left, right = (length*scale for length in (created, resident, *exports))
            result.append((born, phase['stock_kg']-born, here, left, right, math.fsum((born, -here, -left, -right))))
        return np.asarray(result)

    def thermal_fields(self, edges_m, time_s, cooling_reference):
        projection = self.project(edges_m, time_s)
        n, p = len(edges_m)-1, len(cooling_reference.phases)
        cell, centre = np.zeros((n, p+5)), np.zeros((n, p+5))
        occupied_width = projection['ocean_fraction']*np.diff(edges_m)
        for cell_index, strip_index, width, young, old in projection['intersections']:
            i = int(cell_index)
            cell[i] += (width/occupied_width[i])*cooling_reference.mean(young, old)
        for i in np.flatnonzero(projection['centre_valid']):
            centre[i] = cooling_reference.point(projection['centre_age_s'][i])
        return dict(projection, cell_values=cell, centre_values=centre)

    def thermal_accounts(self, time_s, cooling_reference, *, width_m):
        """Independent age/depth means over chronological first-exit regions."""
        reference = cooling_reference
        p = len(reference.phases)
        birth = math.fsum(rate*(end-begin)*width_m*reference.energy
                         for _, _, begin, end, rate in self._births(time_s))
        resident, exports, water_here, water_exports = [], [[], []], [], [[], []]
        surfaces, bases = [], []
        for region in self.regions(time_s):
            young, old = sorted((region.age_first_s, region.age_last_s))
            values = reference.mean(young, old)
            area = region.width_m*width_m
            enthalpy = area*reference.capacity*math.fsum(
                (values[j]-reference.ts)*phase['thickness_m'] for j, phase in enumerate(reference.phases))
            water = area*values[p+2]
            surfaces.append(area*values[p+3]); bases.append(-area*values[p+4])
            if region.side is None:
                resident.append(enthalpy); water_here.append(water)
            else:
                index = SIDES.index(region.side)
                exports[index].append(enthalpy); water_exports[index].append(water)
        represented, left, right = math.fsum(resident), math.fsum(exports[0]), math.fsum(exports[1])
        top, basal = math.fsum(surfaces), math.fsum(bases)
        residual = math.fsum((represented, left, right, top, -basal, -birth))
        scale = max(birth, math.fsum(map(abs, (left, right, top, basal))), 1.)
        resident_water, water_left, water_right = map(math.fsum, (water_here, *water_exports))
        drawn = math.fsum((resident_water, water_left, water_right))
        return (np.asarray((birth, reference.cooling['birth_enthalpy_stock_j']-birth,
            basal, reference.cooling['basal_heat_stock_j']-basal, top, represented, left, right, residual, residual/scale)),
            np.asarray((drawn, reference.cooling['water_stock_m3']-drawn, resident_water, water_left, water_right,
                        math.fsum((drawn, -resident_water, -water_left, -water_right)))))
