"""What a run may use, decided from a reading of the machine handed to it (machine_resources_monitor makes one): the
cores counted and each pool's width, the memory a start needs, and a run's memory limits; adaptive by default, or
manual from the one setting ATLAS_RESOURCES.

  unset or empty                     adaptive: the measured cores (or the ticket's booking), stepped down at launch
  adaptive,cores=6,memory_gib=12     adaptive under ceilings (either alone); a ceiling only lowers
  manual,cores=8,memory_gib=12       the set values, both needed; a stage may be named: manual,...,heat=8,ale=4

A bad value stops the run at launch and never falls back. Standard library only, and nothing of the package, so the
chain driver and the run queue can load this file by its path. Execution only: nothing here enters a result.
SPDX-License-Identifier: AGPL-3.0-only
"""
import os

GIB = 1 << 30
FLOOR_BYTES = GIB                            # the owner's free-memory floor
ALLOWANCE_BYTES = GIB                        # the owner's allowance beside it
RESERVE_BYTES = FLOOR_BYTES+ALLOWANCE_BYTES  # held back from every cap and every start
EARLIER_LIMITS = {'rss_bytes': 12 << 30, 'free_floor_bytes': GIB, 'logical_budget_bytes': 16 << 30}  # what a receipt
#                                            made before this gate says; no run is limited by them
SETTING = 'ATLAS_RESOURCES'
REMOVED = 'ATLAS_POOL_WIDTHS'
STAGES = ('admission', 'heat', 'ale', 'pressure')
BOOKED = 'RUNQ_TICKET_CORES'


class ResourcesRefused(ValueError):
    pass


def _count(text):
    return int(text) if text.isascii() and text.isdigit() and int(text) >= 1 else None


def setting(machine, environ=None):
    """The setting as given, checked against this reading: {given, mode, cores, memory_bytes, widths}. Refuses a
    malformed, repeated, unknown or below-one value; cores above the physical cores; memory above the machine's less
    the floor; a stage above the set cores; a stage named in adaptive mode; manual without both values; and the
    removed ATLAS_POOL_WIDTHS."""
    environ = os.environ if environ is None else environ
    if environ.get(REMOVED, '').strip():
        raise ResourcesRefused(f'{REMOVED} is removed: set {SETTING} (manual,cores=<n>,memory_gib=<n>,<stage>=<n>)')
    given = environ.get(SETTING, '')
    items = [item.strip() for item in given.split(',')] if given.strip() else ['adaptive']
    mode, values = items[0], {}
    if mode not in ('adaptive', 'manual'):
        raise ResourcesRefused(f'{SETTING}={given!r}: the first item is adaptive or manual')
    for item in items[1:]:
        name, sep, value = (part.strip() for part in item.partition('='))
        if not sep or name not in ('cores', 'memory_gib', *STAGES) or name in values or _count(value) is None:
            raise ResourcesRefused(f'{SETTING}: {item!r} is not <name>=<count of one or more>, once each, for a name '
                                   f'in cores, memory_gib, {", ".join(STAGES)}')
        values[name] = _count(value)
    cores, memory = values.pop('cores', None), values.pop('memory_gib', None)
    if cores is not None and cores > machine['physical_cores']:
        raise ResourcesRefused(f'{SETTING}: cores={cores} is above the {machine["physical_cores"]} physical cores')
    if memory is not None and memory*GIB > machine['total_bytes']-FLOOR_BYTES:
        raise ResourcesRefused(f'{SETTING}: memory_gib={memory} is above the machine\'s memory less the floor')
    if mode == 'manual' and (cores is None or memory is None):
        raise ResourcesRefused(f'{SETTING}: manual needs both cores and memory_gib')
    if mode == 'adaptive' and values:
        raise ResourcesRefused(f'{SETTING}: a stage is named only in manual mode')
    for name, width in values.items():
        if width > cores:
            raise ResourcesRefused(f'{SETTING}: {name}={width} is above the set cores {cores}')
    return {'given': given, 'mode': mode, 'cores': cores, 'memory_bytes': None if memory is None else memory*GIB,
            'widths': values}


def run_cores(machine, chosen, environ=None):
    """(cores, source): the count a run may use. Manual: the set cores. Adaptive: the ticket's booking where the
    queue gives one, else the measured physical cores, lowered by a ceiling."""
    if chosen['mode'] == 'manual':
        return chosen['cores'], 'set'
    booked = _count((os.environ if environ is None else environ).get(BOOKED, '').strip())
    cores, source = (booked, 'ticket booking') if booked else (machine['physical_cores'], 'measured')
    if chosen['cores'] is not None and chosen['cores'] < cores:
        return chosen['cores'], 'ceiling'
    return cores, source


def pool_ceiling(machine, chosen):
    """The widest pool allowed: the run's cores less one for the parent, at least one; a stage's set width above
    that raises it to that width."""
    return max(1, run_cores(machine, chosen)[0]-1, *chosen['widths'].values())


def step_down(ceiling, fits, floor=1):
    """The largest count from ceiling down to floor that fits, one at a time; floor - 1 if none."""
    while ceiling >= floor and not fits(ceiling):
        ceiling -= 1
    return max(ceiling, floor-1)


def free_cores(machine, cores):
    """The cores counted less those the reading keeps busy (the monitor's rule), never below none."""
    return max(0.0, cores-machine['busy_cores'])


def launch_width(machine, chosen, booking_bytes, reserve_bytes=0, stage=None):
    """A pool's width where it is launched. Manual: the stage's set width, else the set cores less one, not stepped
    down. Adaptive: the run's cores less one, stepped down until the free cores hold the workers and the parent and
    free memory (at most a memory ceiling and the reserve) holds each worker's booking beside the reserve; at least
    one. A pool's own dispatch gate steps it down again in either mode."""
    cores, _ = run_cores(machine, chosen)
    if chosen['mode'] == 'manual':
        return chosen['widths'].get(stage) or max(1, cores-1)
    free, memory = free_cores(machine, cores), machine['available_bytes']
    if chosen['memory_bytes'] is not None:
        memory = min(memory, chosen['memory_bytes']+RESERVE_BYTES)
    return max(1, step_down(cores-1, lambda n: free >= n+1 and memory >= n*booking_bytes+reserve_bytes))


def start_need(peak):
    """The free memory a start waits for, in exact bytes: its predicted peak, a fifth of it again (rounded up), the
    floor and the allowance."""
    return peak + -(-peak//5) + RESERVE_BYTES


def memory_limits(mode, available_bytes, total_bytes, memory_bytes=None):
    """(cap, ledger) of a run's memory. The cap: in adaptive mode the free memory less the reserve, no more than a
    ceiling; in manual mode the set memory. The ledger: the machine's memory, in either mode."""
    if mode == 'manual':
        cap = memory_bytes
    else:
        cap = available_bytes-RESERVE_BYTES
        cap = cap if memory_bytes is None else min(cap, memory_bytes)
    return cap, total_bytes


def limits(machine, chosen, predicted_peak):
    """A start's memory side, for its decision: the entries the cap is computed from and the cap, floor and ledger.
    Refuses a cap below the predicted peak and its fifth: the run would stop mid-way instead of at the start."""
    cap, ledger = memory_limits(chosen['mode'], machine['available_bytes'], machine['total_bytes'],
                                chosen['memory_bytes'])
    if cap < predicted_peak + -(-predicted_peak//5):
        raise ResourcesRefused(f'the memory cap {cap} bytes is below the predicted peak {predicted_peak} bytes and '
                               'its fifth: refused at the start')
    return {'mode': chosen['mode'], 'setting': chosen['given'], 'memory_bytes': chosen['memory_bytes'],
            'available_bytes': machine['available_bytes'], 'total_bytes': machine['total_bytes'],
            'rss_bytes': cap, 'free_floor_bytes': FLOOR_BYTES, 'logical_budget_bytes': ledger}


def check_limits(entries):
    """True where a decision's cap, floor and ledger are this gate's arithmetic on its own entries."""
    try:
        cap, ledger = memory_limits(entries['mode'], entries['available_bytes'], entries['total_bytes'],
                                    entries['memory_bytes'])
        return (entries['rss_bytes'], entries['free_floor_bytes'], entries['logical_budget_bytes']) == (
            cap, FLOOR_BYTES, ledger) and type(cap) is int and cap > 0
    except (KeyError, TypeError):
        return False


def cap_bound(total_bytes):
    """The most any run's cap may be: the machine's memory less the floor, the most a tree could hold."""
    return total_bytes-FLOOR_BYTES


def widths_record(machine, chosen, widths):
    """The launch's record of widths: the setting as given, the mode, the cores counted and where they came from,
    and each stage's width."""
    cores, source = run_cores(machine, chosen)
    return {'setting': chosen['given'], 'mode': chosen['mode'], 'cores': cores, 'cores_source': source,
            'widths': dict(widths)}
