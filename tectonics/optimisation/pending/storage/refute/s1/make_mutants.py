"""S1 refuter: plant mutants in copies of the candidate; each seam must occur exactly once."""
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAND = HERE/'cand'
SRC = (CAND/'run_fresh_interval.py').read_text(encoding='utf8')

CLOSED = ("                if query_stages is not None:\n"
          "                    query_stages.closed(owner)\n")

MUTANTS = {
    'm01_drop_closed': [(CLOSED, '')],
    'm02_write_before_observe': [("            query_stages.observe()\n            G._write(output, record)\n",
                                  "            G._write(output, record)\n            query_stages.observe()\n")],
    'm03_base_not_updated': [("            self.row['unflushed'] = getattr(self.owner, 'unflushed', 0)\n"
                              "            self.base = now\n",
                              "            self.row['unflushed'] = getattr(self.owner, 'unflushed', 0)\n")],
    'm04_safely_reraises': [("            self.value.update(status='INCOMPLETE', error=type(error).__name__+': '+str(error)[:256])\n",
                             "            self.value.update(status='INCOMPLETE', error=type(error).__name__+': '+str(error)[:256])\n"
                             "            raise\n")],
    'm05_drop_finish': [("            query_stages.finish()\n", '')],
    'm06_opens_counted_at_close': [("            self.row['opens'] += 1\n", ''),
                                   ("            require(owner is self.owner, 'a different completed-query owner closed')\n",
                                    "            require(owner is self.owner, 'a different completed-query owner closed')\n"
                                    "            self.row['opens'] += 1\n")],
    'm07_closed_before_flush': [(CLOSED, ''),
                                ("            active = sys.exception()\n",
                                 "            active = sys.exception()\n"
                                 "            if query_stages is not None:\n"
                                 "                query_stages.closed(owner)\n")],
    'm08_zero_not_null': [("**dict.fromkeys(QUERY_STAGE_FIELDS))", "**dict.fromkeys(QUERY_STAGE_FIELDS, 0))")],
    'm09_no_accumulate_on_stage_change': [("            if stage != self.stage:\n                self._accumulate()\n",
                                           "            if stage != self.stage:\n")],
    'm10_safely_catches_baseexception': [("        except Exception as error:  # noqa: BLE001 - instrumentation never fails the run\n",
                                          "        except BaseException as error:  # noqa: BLE001 - instrumentation never fails the run\n")],
    'm11_finish_no_accumulate': [("        def step():\n            self._accumulate()\n            self.owner = self.base = None\n"
                                  "            self.value['rows'].append(self.row)\n",
                                  "        def step():\n            self.owner = self.base = None\n"
                                  "            self.value['rows'].append(self.row)\n")],
    'm12_unflushed_default_none': [("getattr(self.owner, 'unflushed', 0)", "getattr(self.owner, 'unflushed', None)")],
    'm13_observe_dropped_in_opened': [("        def step():\n            self.observe()\n", "        def step():\n")],
    'm14_delta_sign': [("(self.row[name] or 0)+now[name]-self.base[name]", "(self.row[name] or 0)+self.base[name]-now[name]")],
    'm15_no_incomplete_shortcircuit': [("        if self.value.get('status') == 'INCOMPLETE':\n            return\n", '')],
    'm16_advance_unwired': [("                                 save=save, query_stages=query_stages)\n",
                             "                                 save=save, query_stages=None)\n")],
    'm17_stage_key_strict': [("            stage = self.record.get('stage')\n", "            stage = self.record['stage']\n")],
    'm18_opened_before_store_check': [("        if query_stages is not None:\n            query_stages.opened(owner)\n", ''),
                                      ("                    **arguments) as owner:\n",
                                       "                    **arguments) as owner:\n"
                                       "        if query_stages is not None:\n            query_stages.opened(owner)\n")],
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
        folder.mkdir(parents=True, exist_ok=True)
        (folder/'run_fresh_interval.py').write_text(text, encoding='utf8', newline='\n')
        for test in ('test_s1_query_stages.py', 'test_run_fresh_interval.py'):
            shutil.copyfile(CAND/test, folder/test)
        print('planted', name)


if __name__ == '__main__':
    main()
