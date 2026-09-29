"""Recorded SHA-256 values must bind repository bytes, not a Windows CRLF working copy.
SPDX-License-Identifier: AGPL-3.0-only

Git stores the text suffixes named in tectonics/.gitattributes with LF, so a digest
of CRLF bytes matches no checkout. These checks only read files and run on every
platform: the first finds such bindings; the second finds a working copy whose line
endings would make locally computed digests disagree with the repository; the third
keeps the I01 receipt writers from writing platform (CRLF) line endings again.
"""
import ast
import hashlib
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
# reference_data keeps exact upstream bytes (-text) and is deliberately not scanned.
SCANNED=('cases','docs','evidence','src','tests','tools')
# These list superseded CRLF values on purpose: they are the correction audit trails.
CORRECTION_RECORDS=frozenset(('evidence/line-ending-digest-correction-r1.json',
                              'evidence/line-ending-digest-correction-r2.json'))
HEX=re.compile(rb'(?<![0-9a-fA-F])[0-9a-f]{64}(?![0-9a-fA-F])')
LF,CRLF=b'\n',b'\r\n'


def sha(raw):return hashlib.sha256(raw).hexdigest()


def lf_suffixes():
    suffixes=set()
    for line in (ROOT/'.gitattributes').read_text(encoding='utf-8').splitlines():
        parts=line.split()
        if parts and re.fullmatch(r'\*\.[a-z0-9]+',parts[0]) and {'text','eol=lf'}<=set(parts[1:]):
            suffixes.add(parts[0][1:])
    return suffixes


def checkout():
    paths=[p for p in ROOT.iterdir() if p.is_file()]
    for name in SCANNED:
        paths+=[p for p in (ROOT/name).rglob('*') if p.is_file()]
    return {p.relative_to(ROOT).as_posix():p.read_bytes() for p in sorted(paths)
            if not p.is_symlink() and '__pycache__' not in p.parts}


class RecordedDigestLineEndingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        suffixes=lf_suffixes()
        if '.json' not in suffixes:raise AssertionError('tectonics/.gitattributes no longer stores JSON with LF')
        cls.files=checkout()
        cls.lf,cls.crlf,cls.allowed={},{},set()
        for name,raw in cls.files.items():
            lf=raw.replace(CRLF,LF)
            if Path(name).suffix not in suffixes or b'\r' in lf or LF not in lf:
                cls.allowed.add(sha(raw));continue
            cls.lf[sha(lf)]=name;cls.crlf[sha(lf.replace(LF,CRLF))]=name
        cls.allowed|=set(cls.lf)
        cls.recorded=[(name,match.start(),match.group().decode())
                      for name,raw in cls.files.items()
                      if name not in CORRECTION_RECORDS and b'\0' not in raw[:8192]
                      for match in HEX.finditer(raw)]

    def test_no_recorded_digest_matches_only_a_crlf_rendering(self):
        bad=[f'{name}:{self.files[name][:at].count(LF)+1} binds {self.crlf[value]} by the digest of its CRLF rendering'
             for name,at,value in self.recorded if value in self.crlf and value not in self.allowed]
        if bad:self.fail('\n'.join([f'{len(bad)} recorded digests match no checkout. Write text evidence '
                                    "with newline='\\n', hash the LF bytes and record that digest.",*bad]))

    def test_digest_bound_text_has_repository_line_endings_here(self):
        bound={self.lf[value] for _,_,value in self.recorded if value in self.lf}
        stale=sorted(name for name in bound if CRLF in self.files[name])
        if stale:self.fail('\n'.join([f'{len(stale)} files whose LF digests are recorded have CRLF endings '
                                      'in this working copy, so hashes computed here disagree with the '
                                      'repository. Review and convert only the named files to LF after '
                                      'checking their content against the bound repository version; '
                                      'preserve local edits and original execution records. Do not '
                                      'reset or rewrite the whole checkout.',*stale]))


def text_writes(path):
    """Lines of text-mode open(), Path.open() or write_text() writes in one tool that omit newline='\\n'."""
    lines=[]
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if not isinstance(node,ast.Call):continue
        name=node.func.id if isinstance(node.func,ast.Name) else getattr(node.func,'attr',None)
        keywords={keyword.arg:keyword.value for keyword in node.keywords}
        if name=='open':
            at=1 if isinstance(node.func,ast.Name) else 0          # open(path, mode) or path.open(mode)
            mode=keywords.get('mode',node.args[at] if len(node.args)>at else None)
            writes=(isinstance(mode,ast.Constant) and isinstance(mode.value,str)
                    and bool(set(mode.value)&set('wxa+')) and 'b' not in mode.value)
        else:
            writes=name=='write_text'
        newline=keywords.get('newline')
        if writes and not (isinstance(newline,ast.Constant) and newline.value=='\n'):lines.append(node.lineno)
    return lines


class ReceiptWriterTests(unittest.TestCase):
    def test_i01_receipt_writers_emit_explicit_lf_text(self):
        # Their receipts are registered by digest; the platform newline makes Windows runs write CRLF bytes.
        bad=[f'tools/{path.name}:{line}' for path in sorted((ROOT/'tools').glob('check_i01_*.py'))
             for line in text_writes(path)]
        if bad:self.fail('\n'.join([f"{len(bad)} I01 receipt writes use the platform newline. Open text "
                                    "output with encoding='utf-8', newline='\\n'.",*bad]))


if __name__=='__main__':
    unittest.main()
