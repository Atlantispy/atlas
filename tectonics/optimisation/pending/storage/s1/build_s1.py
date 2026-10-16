"""Build T/so/s1/run_fresh_interval.py from T/so/s1/base/run_fresh_interval.py (exact replacements)."""
import sys
from pathlib import Path

S1 = Path(sys.argv[1])
s = (S1/'base'/'run_fresh_interval.py').read_bytes().decode('utf8')
CLASS = '''QUERY_STAGE_FIELDS = ('hits', 'misses', 'written', 'incomplete')


class QueryStages:
    """S1 (WP17 instrumentation): completed-query counts per guard stage; observation only.

    Every guard.phase() sets record['stage'] and then calls the runner's save(), so save()
    sees each stage change after that stage's last query. Each row holds the live owner's own
    exact counters as deltas over the stage, ``unflushed`` as read when the row was last
    updated, and the owner opens (query_checkpoints calls) in the stage. A stage with no live
    owner has null counts, never 0. Nothing wraps the owner, the guard or a query; the guard's
    phase names and order are unchanged. A failure here is recorded and stops only this
    observation (recording failures stay diagnostic, as in dev_stage_timing).
    """

    def __init__(self, record):
        self.record, self.owner, self.base, self.stage = record, None, None, record.get('stage')
        self.value = record['completed_queries_by_stage'] = {
            'schema': 'atlas.completed-queries-by-stage.v1', 'fields': list(QUERY_STAGE_FIELDS),
            'scope': "live completed-query owner counters; null outside an owner's life", 'rows': [],
            'opened_with': []}
        self.row = self._new_row()

    def _new_row(self):
        return dict(stage=self.stage, opens=0, unflushed=None, **dict.fromkeys(QUERY_STAGE_FIELDS))

    def _counts(self):
        return {name: getattr(self.owner, name) for name in QUERY_STAGE_FIELDS}

    def _accumulate(self):
        if self.owner is not None:
            now = self._counts()
            for name in QUERY_STAGE_FIELDS:
                self.row[name] = (self.row[name] or 0)+now[name]-self.base[name]
            self.row['unflushed'] = getattr(self.owner, 'unflushed', 0)
            self.base = now

    def _safely(self, step):
        if self.value.get('status') == 'INCOMPLETE':
            return
        try:
            step()
        except Exception as error:  # noqa: BLE001 - instrumentation never fails the run
            self.owner = self.base = None
            self.value.update(status='INCOMPLETE', error=type(error).__name__+': '+str(error)[:256])

    def observe(self):
        def step():
            stage = self.record.get('stage')
            if stage != self.stage:
                self._accumulate()
                self.value['rows'].append(self.row)
                self.stage = stage
                self.row = self._new_row()
        self._safely(step)

    def opened(self, owner):
        def step():
            self.observe()
            require(self.owner is None, 'one completed-query owner at a time')
            self.owner = owner
            self.base = self._counts()
            self.value['opened_with'].append(dict(stage=self.stage, **self.base))
            self.row['opens'] += 1
            for name in QUERY_STAGE_FIELDS:
                self.row[name] = self.row[name] or 0
        self._safely(step)

    def closed(self, owner):
        def step():
            require(owner is self.owner, 'a different completed-query owner closed')
            self._accumulate()
            self.owner = self.base = None
        self._safely(step)

    def finish(self):
        def step():
            self._accumulate()
            self.owner = self.base = None
            self.value['rows'].append(self.row)
            self.row = None
            self.value.setdefault('status', 'COMPLETE')
        self._safely(step)


@contextmanager
def completed_queries('''
edits = [
    ('@contextmanager\ndef completed_queries(', CLASS),
    ('''def completed_queries(owner_type, directory, *, declared, arguments, execution, budget, cancel, limits, record,
                      save):''', '''def completed_queries(owner_type, directory, *, declared, arguments, execution, budget, cancel, limits, record,
                      save, query_stages=None):'''),
    ('''        require(declared == 'files' or callable(flush), 'a batched completed-query store must flush')
        try:''', '''        require(declared == 'files' or callable(flush), 'a batched completed-query store must flush')
        if query_stages is not None:
            query_stages.opened(owner)
        try:'''),
    ('''            finally:
                record['completed_queries'] = {''', '''            finally:
                if query_stages is not None:
                    query_stages.closed(owner)
                record['completed_queries'] = {'''),
    ('def run_fresh_interval(profile, *, sources, guard, record, save, mode, stop_before_advance=False, seed=None):',
     '''def run_fresh_interval(profile, *, sources, guard, record, save, mode, stop_before_advance=False, seed=None,
                       query_stages=None):'''),
    ('''                        store_directory=store_directory, check=check, query_store=(EndpointCheckpoints, declared,''',
     '''                        store_directory=store_directory, check=check, query_stages=query_stages,
                        query_store=(EndpointCheckpoints, declared,'''),
    ('''             catalog, query_directory, store_directory, check, query_store, measurements=None):''',
     '''             catalog, query_directory, store_directory, check, query_store, measurements=None, query_stages=None):'''),
    ('''                                 execution=execution, budget=budget, cancel=check, limits=limits, record=record,
                                 save=save)''', '''                                 execution=execution, budget=budget, cancel=check, limits=limits, record=record,
                                 save=save, query_stages=query_stages)'''),
    ('''        save = lambda: G._write(output, record)
''', '''        query_stages = QueryStages(record)

        def save():
            query_stages.observe()
            G._write(output, record)
'''),
    ('''                budget = run_fresh_interval(profile, sources=sources, guard=guard, record=record, save=save, mode=mode,
                                            stop_before_advance=stop_before_advance, seed=seed)''',
     '''                budget = run_fresh_interval(profile, sources=sources, guard=guard, record=record, save=save, mode=mode,
                                            stop_before_advance=stop_before_advance, seed=seed,
                                            query_stages=query_stages)'''),
    ('''            record['status'] = final_status(record['errors'], mode, record)
            save()
    return 0''', '''            query_stages.finish()
            record['status'] = final_status(record['errors'], mode, record)
            save()
    return 0'''),
]
for old, new in edits:
    if s.count(old) != 1:
        raise SystemExit('seam count %d: %r' % (s.count(old), old[:70]))
    s = s.replace(old, new)
(S1/'run_fresh_interval.py').write_bytes(s.encode('utf8'))
print('ok')
