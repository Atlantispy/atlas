"""S1 r4: the r3 mutants (make_mutants_r3.py) on r4, plus two for r4's status-first stores (m23, m24).

Each seam must occur exactly once; every mutant must compile. Writes r4/mutants/<name>/ with the r4 tests.
"""
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = (HERE/'run_fresh_interval.py').read_text(encoding='utf8')

CLOSED = ("                if query_stages is not None:\n"
          "                    query_stages.closed(owner)\n")
OPENS = "            self.row.update({name: self.row[name] or 0 for name in QUERY_STAGE_FIELDS}, opens=self.row['opens']+1)\n"
CLOSE_REQUIRE = "            require(owner is self.owner, 'a different completed-query owner closed')\n"

MUTANTS = {
    'm01_drop_closed': [(CLOSED, '')],
    'm02_write_before_observe': [("            query_stages.observe()\n            G._write(output, record)\n",
                                  "            G._write(output, record)\n            query_stages.observe()\n")],
    'm03_base_not_updated': [("            self.row.update(sums, unflushed=unflushed)\n            self.base = now\n",
                              "            self.row.update(sums, unflushed=unflushed)\n")],
    'm04_safely_reraises': [("            self._stop(error)\n        except BaseException",
                             "            self._stop(error)\n            raise\n        except BaseException")],
    'm05_drop_finish': [("            query_stages.finish()\n", '')],
    'm06_opens_counted_at_close': [(OPENS, OPENS.replace(", opens=self.row['opens']+1)", ")")),
                                   (CLOSE_REQUIRE, CLOSE_REQUIRE+"            self.row['opens'] += 1\n")],
    'm07_closed_before_flush': [(CLOSED, ''),
                                ("            active = sys.exception()\n",
                                 "            active = sys.exception()\n"
                                 "            if query_stages is not None:\n"
                                 "                query_stages.closed(owner)\n")],
    'm08_zero_not_null': [("**dict.fromkeys(QUERY_STAGE_FIELDS))", "**dict.fromkeys(QUERY_STAGE_FIELDS, 0))")],
    'm09_no_accumulate_on_stage_change': [("        if stage != self.stage:\n            self._accumulate()\n",
                                           "        if stage != self.stage:\n")],
    'm10_safely_catches_baseexception': [("        except Exception as error:  # noqa: BLE001 - instrumentation never fails the run\n",
                                          "        except BaseException as error:  # noqa: BLE001 - instrumentation never fails the run\n")],
    'm11_finish_no_accumulate': [("            self._observe()\n            self._accumulate()\n",
                                  "            self._observe()\n")],
    'm12_unflushed_default_none': [("getattr(self.owner, 'unflushed', 0)", "getattr(self.owner, 'unflushed', None)")],
    'm13_observe_dropped_in_opened': [("        def step():\n            self._observe()\n            require(self.owner is None",
                                       "        def step():\n            require(self.owner is None")],
    'm14_delta_sign': [("(self.row[name] or 0)+now[name]-self.base[name]", "(self.row[name] or 0)+self.base[name]-now[name]")],
    'm15_no_status_shortcircuit': [("        if 'status' in self.value:  # finished (COMPLETE) or failed (INCOMPLETE): "
                                    "observation has stopped\n            return\n", '')],
    'm16_advance_unwired': [("                                 save=save, query_stages=query_stages)\n",
                             "                                 save=save, query_stages=None)\n")],
    'm17_stage_key_strict': [("        stage = self.record.get('stage')\n", "        stage = self.record['stage']\n")],
    'm18_opened_before_store_check': [("        if query_stages is not None:\n            query_stages.opened(owner)\n", ''),
                                      ("                    **arguments) as owner:\n",
                                       "                    **arguments) as owner:\n"
                                       "        if query_stages is not None:\n            query_stages.opened(owner)\n")],
    # r2's own changes
    'm19_finish_no_observe': [("            self._observe()\n            self._accumulate()\n",
                               "            self._accumulate()\n")],
    'm20_observes_after_finish': [("        if 'status' in self.value:  # finished",
                                   "        if self.value.get('status') == 'INCOMPLETE':  # finished")],
    # r3's own changes
    'm21_interrupt_not_recorded': [("            self._stop(error)\n            raise\n", "            raise\n")],
    'm22_interrupt_swallowed': [("            self._stop(error)\n            raise\n", "            self._stop(error)\n")],
    # r4's own changes
    'm23_interrupt_status_not_first': [
        ("            # An interrupt may have landed between two updates of a row: mark the rows, stop, re-raise.\n"
         "            self.value['status'] = 'INCOMPLETE'  # first, with no call before it: see the class docstring\n",
         "            # An interrupt may have landed between two updates of a row: mark the rows, stop, re-raise.\n")],
    'm24_failure_status_not_first': [
        ("  # noqa: BLE001 - instrumentation never fails the run\n"
         "            self.value['status'] = 'INCOMPLETE'  # first, with no call before it: see the class docstring\n",
         "  # noqa: BLE001 - instrumentation never fails the run\n")],
}


def main():
    root = HERE/'mutants'
    for name, edits in MUTANTS.items():
        text = SRC
        for old, new in edits:
            if text.count(old) != 1:
                sys.exit('%s: seam count %d: %r' % (name, text.count(old), old[:70]))
            text = text.replace(old, new)
        compile(text, name, 'exec')
        folder = root/name
        folder.mkdir(parents=True, exist_ok=False)
        (folder/'run_fresh_interval.py').write_text(text, encoding='utf8', newline='\n')
        for test in ('test_s1_query_stages.py', 'test_run_fresh_interval.py'):
            shutil.copyfile(HERE/test, folder/test)
        print('planted', name)


if __name__ == '__main__':
    main()
