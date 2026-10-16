"""S1 revision 2: the refuter's P3 fixes on top of the r1 candidate (393303fb); writes s1/r2/run_fresh_interval.py.

Only the QueryStages class changes:
- finish() observes first, so a stage whose save() was skipped (guard _sync raised) is still closed;
- once a status is set (COMPLETE or INCOMPLETE), observation stops, so a save() after finish() adds nothing;
- every read and sum happens before the row is updated (a failed read leaves the row as it was);
- opened()/finish() observe inside their own step (no nested guard);
- the scope string and docstring say what the rows hold (all owners in the stage), name the guard file, and say
  what a hard kill leaves.
"""
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE, TARGET = HERE/'run_fresh_interval.py', HERE/'r2'/'run_fresh_interval.py'
SOURCE_SHA = '393303fbfba98cba556ce42e520c2db2e0ab49804d5b4624fb47e7312a424232'

START, END = 'class QueryStages:\n', '\n\n@contextmanager\ndef completed_queries('

CLASS = '''class QueryStages:
    """S1 (WP17 instrumentation): completed-query counts per guard stage; observation only.

    ContinuationGuard.phase() (private_heat_continuation_guard_r3.py) sets record['stage'],
    runs _sync() and then calls the runner's save(), so save() normally sees each stage
    change after that stage's last query. If _sync() raises, that save() is skipped; the
    next observation (a save(), an owner open or finish()) closes the stage instead.

    Each row holds, per counter, the sum over every completed-query owner open in the stage
    of that owner's exact counter deltas (record['completed_queries'] holds the last owner's
    totals only), ``unflushed`` as read when the row was last updated, and the owner opens
    (query_checkpoints calls) in the stage. A stage with no live owner has null counts,
    never 0. Nothing wraps the owner, the guard or a query; the guard's phase names and
    order are unchanged.

    An Exception here is recorded (status INCOMPLETE, error) and stops only this
    observation; the rows keep the stages closed before it (recording failures stay
    diagnostic, as in dev_stage_timing). A BaseException (KeyboardInterrupt, SystemExit)
    is never caught. finish() closes the last row and sets status COMPLETE; observation
    stops there. A run killed hard never reaches finish(): its run.json keeps the rows of
    the stages closed by its last save(), with no status and no in-progress row.
    """

    def __init__(self, record):
        self.record, self.owner, self.base, self.stage = record, None, None, record.get('stage')
        self.value = record['completed_queries_by_stage'] = {
            'schema': 'atlas.completed-queries-by-stage.v1', 'fields': list(QUERY_STAGE_FIELDS),
            'scope': ("per stage, the sum over every completed-query owner open in it of that owner's counter "
                      "deltas (completed_queries holds the last owner only); null outside an owner's life"),
            'rows': [], 'opened_with': []}
        self.row = self._new_row()

    def _new_row(self):
        return dict(stage=self.stage, opens=0, unflushed=None, **dict.fromkeys(QUERY_STAGE_FIELDS))

    @staticmethod
    def _counts(owner):
        return {name: getattr(owner, name) for name in QUERY_STAGE_FIELDS}

    def _accumulate(self):
        # Every read and sum first, then one update: a failed read leaves the row as it was.
        if self.owner is not None:
            now, unflushed = self._counts(self.owner), getattr(self.owner, 'unflushed', 0)
            sums = {name: (self.row[name] or 0)+now[name]-self.base[name] for name in QUERY_STAGE_FIELDS}
            self.row.update(sums, unflushed=unflushed)
            self.base = now

    def _observe(self):
        stage = self.record.get('stage')
        if stage != self.stage:
            self._accumulate()
            self.value['rows'].append(self.row)
            self.stage = stage
            self.row = self._new_row()

    def _safely(self, step):
        if 'status' in self.value:  # finished (COMPLETE) or failed (INCOMPLETE): observation has stopped
            return
        try:
            step()
        except Exception as error:  # noqa: BLE001 - instrumentation never fails the run
            self.owner = self.base = None
            self.value.update(status='INCOMPLETE', error=type(error).__name__+': '+str(error)[:256])

    def observe(self):
        self._safely(self._observe)

    def opened(self, owner):
        def step():
            self._observe()
            require(self.owner is None, 'one completed-query owner at a time')
            base = self._counts(owner)
            self.owner, self.base = owner, base
            self.value['opened_with'].append(dict(stage=self.stage, **base))
            self.row.update({name: self.row[name] or 0 for name in QUERY_STAGE_FIELDS}, opens=self.row['opens']+1)
        self._safely(step)

    def closed(self, owner):
        def step():
            require(owner is self.owner, 'a different completed-query owner closed')
            self._accumulate()
            self.owner = self.base = None
        self._safely(step)

    def finish(self):
        def step():
            self._observe()
            self._accumulate()
            self.owner = self.base = None
            self.value['rows'].append(self.row)
            self.row = None
            self.value['status'] = 'COMPLETE'
        self._safely(step)
'''


def main():
    raw = SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise SystemExit('r1 candidate is not 393303fb: refusing')
    s = raw.decode('utf8')
    if s.count(START) != 1 or s.count(END) != 1:
        raise SystemExit('class seams not found exactly once')
    start, end = s.index(START), s.index(END)
    if not start < end:
        raise SystemExit('class seams out of order')
    out = s[:start]+CLASS.rstrip('\n')+s[end:]
    TARGET.parent.mkdir(exist_ok=True)
    if TARGET.exists():
        raise SystemExit('%s exists: a new revision is a new file' % TARGET)
    TARGET.write_bytes(out.encode('utf8'))
    print('wrote', TARGET, hashlib.sha256(out.encode('utf8')).hexdigest())


if __name__ == '__main__':
    sys.exit(main())
