"""WP18 part 1, (a)+(b) (coordinator-approved 16 Oct 2026 at two endpoint workers): endpoint
batches that can pay.

Source transform of atlas_tectonics/integration_component_volume_auto.py, stacked on
workers_six_endpoint_clamp.py (input fa0cbcaf...). Measured reason (WP18-PART1-DESIGN-NOTE.md,
16 Oct re-assessment): IV2 endpoint queries average 15 ms, and every batch is a one-shot child
that must save 3.4 s (start-up + transfer). Under RC1's endpoint clamp (32 jobs, 64-request
horizon, current support only) no batch can ever pay, so every endpoint query runs in the parent.

(a) Batch bounds: the endpoint schedule keeps the policy's general bounds (batch_jobs and
    horizon, 512 and 4096 by default), already reviewed for walls and interfaces. The schedule
    was built with them and self.cached = 2*horizon+64 follows. One batch's shipped supports stay
    within D.MAX_BATCH_INPUT through the schedule's existing capacity check (_weigh/_fits).
    ComponentParallelSession keeps its 1..2 workers; EndpointBatchPass (the opt-in prototype,
    1..32 requests) is untouched.
(b) Cross-support lookahead: when the support being offered runs out while the schedule is
    still hungry, the next support of the pass is read AHEAD of the router:
    - only its component list (logical ids and the label inputs) is kept, as small tuples;
    - non-compact: one support.record() decode within the existing prepaid routing decode
      envelope, sequential with its other users (the precedent is RC1's EndpointBatchPass:
      "fits the existing prepaid transport/decode envelope and dies with the iterator");
    - compact: the support is materialised once by its partition (charged by _issue), held as
      Step 8's retained handle (retain_support) and its components read through Step 8's
      support_fields (charged owner); the temporary native support dies at once;
    - the routing-row projector is NEVER called ahead of its serial position: the router still
      projects each support once, in order, and binds it; a read-ahead support must then be
      the same support (index and support id), or the schedule stops and the pass runs serial.
    - _beyond() = jobs left in the support being read + (supports not read yet) x (jobs per
      support read so far): the wall pass's own estimator.
r2 (16 Oct, after the refuter: no record fault; memory and efficiency fixes):
    - read ahead only while a worker session is open, or while the schedule's plan asks the
      router for more to cut its first batch (offered < wanted, set only by its 'lookahead still
      growing' branch). r1 read the whole pass ahead before any estimate existed (IV2 smoke: all
      351 supports, then the open was refused); gating on an open session alone would never cut a
      first batch (one IV2 support offers ~8 requests of ~15 ms). A pass below its threshold or
      without estimates reads nothing ahead. With no session open (none chosen yet, or a first
      open deferred), reading ahead also ends for the pass once the lookahead first reaches its
      horizon (delta review P2: a pass whose windows are never rated would otherwise renew the
      request all pass and read every compact support twice), so at most one horizon of supports
      is read twice without a session; it resumes if a session opens;
    - compact: every handle this pass retains with requests to offer is held as (index, handle)
      until the router binds a later support, then leaves the rolling identities memo (2*horizon
      +64 = 8,256 entries), so the pass keeps only the handles in sight, not one per support.
      Holding the handle (not its id) keeps a later handle from reusing that id meanwhile
      (delta review P3); a support without requests is not tracked;
    - a lookahead stop drops the support being read at once; offered jobs go at close();
    - report: lookahead_peak_supports (read ahead, not yet bound) and lookahead_peak_handles.
Adoption order is unchanged: workers only compute ahead and the parent adopts in router order.
claim() and checkpoint_consumed() still match the next offered (logical id, endpoint).
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    'fa0cbcaf55eb0845e824fa8a2a8417dd1c0b1936c899a8b049d0ba88a1a1cdfe':
        'gg/workers6-r6 (composed-r1 runtime-src + workers_six_endpoint_clamp)',
}

EDITS = (
    # (a) policy bounds; lookahead state.
    ("        self.prepared = False\n"
     "        self.checkpoint_hits = 0\n"
     "        super().__init__(parent)\n"
     "        if self.schedule is not None:\n"
     "            # Preserve the reviewed endpoint transport bounds and keep the\n"
     "            # current support's metadata lookahead small.\n"
     "            self.schedule.limit = min(self.policy.batch_jobs, 32)\n"
     "            self.schedule.horizon = min(self.policy.horizon, 64)\n"
     "            self.cached = 2*self.schedule.horizon + 64\n",
     "        self.prepared = False\n"
     "        self.checkpoint_hits = 0\n"
     "        # WP18 part 1: the pass's supports; the next one not read yet; supports bound by the\n"
     "        # router; read ones it has still to bind, as (index, support id); and the supports\n"
     "        # and endpoint jobs read so far.\n"
     "        self.supports, self.cursor, self.bound = None, 0, 0\n"
     "        self.unbound, self.read = deque(), [0, 0]\n"
     "        # r2: compact handles this pass retained, as (index, handle), so the identities memo drops\n"
     "        # them once the router has passed their support; peak supports read ahead, peak handles;\n"
     "        # set once a lookahead reaches its horizon with no session open (no more reading ahead\n"
     "        # until one opens).\n"
     "        self.handles, self.peak, self.sated = deque(), [0, 0], False\n"
     "        super().__init__(parent)\n"
     "        # WP18 part 1: the policy's general batch bounds (batch_jobs, horizon), as for walls\n"
     "        # and interfaces. The schedule was built with them and self.cached = 2*horizon+64\n"
     "        # already; one batch's shipped supports stay within D.MAX_BATCH_INPUT through the\n"
     "        # schedule's capacity check.\n"),
    # (b) prepare keeps the pass's support sequence.
    ("        if self.prepared or self.closed:\n"
     "            raise RuntimeError('one prepare per automatic endpoint pass')\n"
     "        self.prepared = True\n",
     "        if self.prepared or self.closed:\n"
     "            raise RuntimeError('one prepare per automatic endpoint pass')\n"
     "        self.prepared = True\n"
     "        # Read ahead by index, one support at a time, never all at once.\n"
     "        self.supports = supports\n"),
    # (b) bind_support: a read-ahead support is checked, others are read from the router's row.
    ("        if self.schedule is None or self.closed or self.schedule.stopped is not None:\n"
     "            return\n"
     "        try:\n"
     "            if self.order or self.left:\n"
     "                raise ValueError('previous endpoint support was not consumed in serial order')\n"
     "            if getattr(support, '_compact_ref', None) is not None:\n"
     "                # Offer the small retained handle, not the temporary native support.\n"
     "                from partition_routing_patch import retain_support\n"
     "                support = retain_support(support)\n"
     "            parts = row['components']\n"
     "            self.left = sum(1 + (part['parent_cell_id'] is not None) for part in parts)\n"
     "            self.jobs = ((support, part['logical_cell_id'], endpoint, {},\n"
     "                          (endpoint, len(part['constraints']), len(part['partition_path'])))\n"
     "                         for part in parts for endpoint in ('start', 'end')\n"
     "                         if endpoint != 'start' or part['parent_cell_id'] is not None)\n"
     "            self._fill()\n"
     "        except Exception as error:\n"
     "            self.schedule._stop('endpoint lookahead error', S._text(error))\n",
     "        if self.schedule is None or self.closed or self.schedule.stopped is not None:\n"
     "            if self.schedule is not None and not self.closed:\n"
     "                # Stopped by the schedule: nothing more binds, so the reading and the held\n"
     "                # handles (with their memo entries) go now, not at close.\n"
     "                self._drop_reading()\n"
     "            return\n"
     "        try:\n"
     "            index, self.bound = self.bound, self.bound+1\n"
     "            # Supports the router has passed: their retained handles leave the identities memo\n"
     "            # (only a memo: a later lookup recomputes it), so the pass holds the handles in sight.\n"
     "            while self.handles and self.handles[0][0] < index:\n"
     "                self.identities.pop(id(self.handles.popleft()[1]), None)\n"
     "            if self.order and self.order[0][0] < index:\n"
     "                raise ValueError('previous endpoint support was not consumed in serial order')\n"
     "            if index < self.cursor:\n"
     "                # Read ahead already and its requests offered: the router must bind that same support.\n"
     "                held = self.unbound.popleft() if self.unbound else None\n"
     "                if held is None or held != (index, support.support_id):\n"
     "                    raise ValueError('endpoint lookahead support differs from the router order')\n"
     "            else:\n"
     "                if index != self.cursor or self.jobs is not None or self.left or self.unbound:\n"
     "                    raise ValueError('previous endpoint support was not consumed in serial order')\n"
     "                compact = getattr(support, '_compact_ref', None) is not None\n"
     "                if compact:\n"
     "                    # Offer the small retained handle, not the temporary native support.\n"
     "                    from partition_routing_patch import retain_support\n"
     "                    support = retain_support(support)\n"
     "                self._begin_support(index, support, _summary(row['components']))\n"
     "                if compact:\n"
     "                    self._retained(index, support)\n"
     "            self._fill()\n"
     "        except Exception as error:\n"
     "            self.schedule._stop('endpoint lookahead error', S._text(error))\n"
     "            self._drop_reading()\n"),
    # (b) _beyond, _fill and the read-ahead.
    ("    def _beyond(self):\n"
     "        # No whole-mesh decode or estimate of unseen supports.\n"
     "        return self.left\n"
     "\n"
     "    def _fill(self):\n"
     "        if self.jobs is None or self.schedule is None or self.closed:\n"
     "            return\n"
     "        try:\n"
     "            while self.schedule.hungry():\n"
     "                item = next(self.jobs, None)\n"
     "                if item is None:\n"
     "                    self.jobs, self.left = None, 0\n"
     "                    return\n"
     "                support, key, endpoint, pair, label = item\n"
     "                self.left -= 1\n"
     "                self.total += 1\n"
     "                self.order.append((key, endpoint, label))\n"
     "                self.schedule.offer((support, key, endpoint, pair), 0.0, label)\n"
     "                if not self.left:\n"
     "                    self.jobs.close()\n"
     "                    self.jobs = None\n"
     "                    return\n"
     "        except Exception as error:\n"
     "            self.schedule._stop('endpoint lookahead error', S._text(error))\n",
     "    def _beyond(self):\n"
     "        # Jobs left in the support being read; for supports not read yet, the mean number\n"
     "        # of jobs per support read so far (the wall pass's estimator). No whole-mesh decode.\n"
     "        supports, jobs = self.read\n"
     "        if self.supports is None or not supports:\n"
     "            return self.left\n"
     "        return self.left + max(0, len(self.supports)-self.cursor)*jobs/supports\n"
     "\n"
     "    def _begin_support(self, index, support, summary):\n"
     "        \"\"\"The endpoint requests of support ``index`` in router order, from its (id, has parent,\n"
     "        constraint count, partition path length) summary.\"\"\"\n"
     "        self.cursor = index+1\n"
     "        self.left = sum(1 + has_parent for _, has_parent, _, _ in summary)\n"
     "        self.read[0] += 1\n"
     "        self.read[1] += self.left\n"
     "        self.jobs = ((index, support, key, endpoint, {}, (endpoint, constraints, path))\n"
     "                     for key, has_parent, constraints, path in summary for endpoint in ('start', 'end')\n"
     "                     if endpoint != 'start' or has_parent) if self.left else None\n"
     "\n"
     "    def _retained(self, index, handle):\n"
     "        # Only a handle with requests to offer can enter the memo. Holding it until the router\n"
     "        # passes its support keeps its id from being reused by a later handle meanwhile.\n"
     "        if self.left:\n"
     "            self.handles.append((index, handle))\n"
     "            self.peak[1] = max(self.peak[1], len(self.handles))\n"
     "\n"
     "    def _drop_reading(self):\n"
     "        # A stopped lookahead drops the support it was reading at once; jobs already offered\n"
     "        # go with the schedule at close(), which the ALE runs before the partition closes.\n"
     "        if self.jobs is not None:\n"
     "            self.jobs.close()\n"
     "            self.jobs = None\n"
     "        self.left = 0\n"
     "        self.unbound.clear()\n"
     "        # No support is bound after a stop, so held handles leave the memo now, not at close.\n"
     "        while self.handles:\n"
     "            self.identities.pop(id(self.handles.popleft()[1]), None)\n"
     "\n"
     "    def _read_ahead(self):\n"
     "        \"\"\"Offer the next support's requests before the router reaches it.\n"
     "\n"
     "        Only its component summary and the support (a retained handle if compact) are kept.\n"
     "        The routing-row projector is not called ahead of its serial position.\n"
     "        \"\"\"\n"
     "        index = self.cursor\n"
     "        support = self.supports[index]\n"
     "        compact = getattr(support, '_compact_ref', None) is not None\n"
     "        if compact:\n"
     "            # Step 8's retained handle and charged field read; the temporary native support\n"
     "            # and its retained bytes die here.\n"
     "            from partition_routing_patch import retain_support, support_fields\n"
     "            held = retain_support(support)\n"
     "            del support\n"
     "            owned = support_fields(held, ('components',))\n"
     "            try:\n"
     "                summary = _summary(owned.value['components'])\n"
     "            finally:\n"
     "                del owned\n"
     "            ident = held.support_id\n"
     "        else:\n"
     "            # One decode within the existing prepaid routing decode envelope, sequential\n"
     "            # with its other users; the graph dies before this returns.\n"
     "            held, ident = support, support.support_id\n"
     "            summary = _summary(support.record()['components'])\n"
     "        self.unbound.append((index, ident))\n"
     "        self.peak[0] = max(self.peak[0], len(self.unbound))\n"
     "        self._begin_support(index, held, summary)\n"
     "        if compact:\n"
     "            self._retained(index, held)\n"
     "\n"
     "    def _fill(self):\n"
     "        if self.schedule is None or self.closed:\n"
     "            return\n"
     "        schedule = self.schedule\n"
     "        try:\n"
     "            while schedule.hungry():\n"
     "                if self.jobs is None:\n"
     "                    # Read ahead only while a worker session is open, or while the schedule's plan\n"
     "                    # asks the router for more to cut its first batch (offered < wanted; one\n"
     "                    # support's requests never fill a batch) and no lookahead of this pass has\n"
     "                    # reached its horizon without a session. A pass below its threshold or still\n"
     "                    # without estimates reads nothing ahead.\n"
     "                    if (self.supports is None or self.cursor >= len(self.supports) or not self.bound\n"
     "                            or (schedule.session is None\n"
     "                                and (self.sated or schedule.offered >= schedule._wanted))):\n"
     "                        return\n"
     "                    self._read_ahead()\n"
     "                    continue\n"
     "                item = next(self.jobs, None)\n"
     "                if item is None:\n"
     "                    self.jobs, self.left = None, 0\n"
     "                    continue\n"
     "                index, support, key, endpoint, pair, label = item\n"
     "                self.left -= 1\n"
     "                self.total += 1\n"
     "                self.order.append((index, key, endpoint, label))\n"
     "                self.schedule.offer((support, key, endpoint, pair), 0.0, label)\n"
     "                if not self.left:\n"
     "                    self.jobs.close()\n"
     "                    self.jobs = None\n"
     "            if schedule.session is None and len(schedule.ahead) >= schedule.horizon:\n"
     "                # A whole horizon in sight and still no session: read no further ahead until one\n"
     "                # opens, so at most one horizon of supports is read twice without a session.\n"
     "                self.sated = True\n"
     "        except Exception as error:\n"
     "            self.schedule._stop('endpoint lookahead error', S._text(error))\n"
     "            self._drop_reading()\n"),
    # claim / checkpoint: order entries now carry the support index first.
    ("            if self.order and self.order[0][:2] == (request['logical_cell_id'], request['endpoint']):\n"
     "                _, _, self.label = self.order.popleft()\n",
     "            if self.order and self.order[0][1:3] == (request['logical_cell_id'], request['endpoint']):\n"
     "                _, _, _, self.label = self.order.popleft()\n"),
    ("        if self.order and self.order[0][:2] == (logical_cell_id, endpoint):\n"
     "            self.order.popleft()\n",
     "        if self.order and self.order[0][1:3] == (logical_cell_id, endpoint):\n"
     "            self.order.popleft()\n"),
    # close: drop the support sequence and read-ahead identities too.
    ("        if self.jobs is not None:\n"
     "            self.jobs.close()\n"
     "            self.jobs = None\n"
     "        self.order.clear()\n"
     "        super().close()\n",
     "        if self.jobs is not None:\n"
     "            self.jobs.close()\n"
     "            self.jobs = None\n"
     "        self.order.clear()\n"
     "        self.unbound.clear()\n"
     "        self.handles.clear()\n"
     "        self.supports = None\n"
     "        super().close()\n"),
    ("            report['lookahead_scope'] = 'current funded support only'\n",
     "            report['lookahead_scope'] = ('supports ahead of the router while a session is open, or while its '\n"
     "                                         'first batch is being cut up to one horizon; rows projected in router order')\n"
     "            report['lookahead_supports'] = self.read[0]\n"
     "            report['lookahead_peak_supports'], report['lookahead_peak_handles'] = self.peak\n"
     "            report['lookahead_sated'] = self.sated\n"),
    # module docstring.
    ("Only the current, already funded routing row is offered. Endpoint observations\n",
     "Requests are offered in router order. While a worker session is open, or the schedule\n"
     "asks for more to cut its first batch (up to one horizon), supports ahead of the router\n"
     "are read for their component lists (WP18 part 1). Endpoint observations\n"),
    # module-level summary helper, before open_automatic_endpoints.
    ("\n\ndef open_automatic_endpoints(parent, width):\n",
     "\n\ndef _summary(parts):\n"
     "    \"\"\"(logical id, has parent, constraint count, partition path length) per component, in order.\"\"\"\n"
     "    return tuple((part['logical_cell_id'], part['parent_cell_id'] is not None,\n"
     "                  len(part['constraints']), len(part['partition_path'])) for part in parts)\n"
     "\n\ndef open_automatic_endpoints(parent, width):\n"),
)


def transform(source, *, allow_unreviewed_input=False):
    if 'def _read_ahead(self):' in source:
        raise ValueError('WP18 endpoint lookahead already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('endpoint auto input is not the reviewed module; pass allow_unreviewed_input and re-run parity')
    for old, new in EDITS:
        if source.count(old) != 1:
            raise ValueError('WP18 endpoint anchor must occur exactly once: %r' % old[:60])
        source = source.replace(old, new)
    return source
