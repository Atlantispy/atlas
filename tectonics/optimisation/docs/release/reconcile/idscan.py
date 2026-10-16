"""Identity-mechanism scan of the helper closure (read-only). Usage: idscan.py closure.json helpers_dir out.json"""
import json, re, sys, pathlib
closure = json.load(open(sys.argv[1]))['closure']; hd = pathlib.Path(sys.argv[2])
P = {
 'file_ref': re.compile(r'__file__'),
 'resolve': re.compile(r'\.resolve\(\)'),
 'sources_reg': re.compile(r'_SOURCES\s*\['),
 'user_path': re.compile(r'[A-Za-z]:(?:\\|\|/)+Users(?:\\|\|/)'),
 'const_pin': re.compile(r'^\s*[A-Z][A-Z0-9_]*(?:SHA|SHA256|DIGEST|HASH)[A-Z0-9_]*\s*=\s*[\'"][0-9a-f]{16,}', re.M),
 'name_pin': re.compile(r'[\'"][\w./-]+\.py[\'"]\s*:\s*[\'"][0-9a-f]{64}[\'"]'),
 'dyn_load': re.compile(r'spec_from_file_location|sys\.path\.(?:insert|append)|SourceFileLoader|exec\(compile'),
 'src_rewrite': re.compile(r'source\s*=\s*source|\.replace\(\s*[\'"](?:def |class |    )|def transform\b|write_text\('),
 'parents_nav': re.compile(r'parents\[\d\]|\.parent\.parent'),
}
out = {}
for m in closure:
    f = hd / (m + '.py')
    s = f.read_text(encoding='utf-8')
    out[m] = {k: len(p.findall(s)) for k, p in P.items()}
    out[m]['lines'] = s.count('\n')
    out[m]['user_path_lines'] = [i + 1 for i, l in enumerate(s.splitlines()) if P['user_path'].search(l)]
json.dump(out, open(sys.argv[3], 'w'), indent=1)
tot = {k: sum(1 for v in out.values() if v[k]) for k in P}
print('modules with each mechanism (of %d):' % len(out), tot)
print('user-path modules:', {m: v['user_path_lines'] for m, v in out.items() if v['user_path_lines']})
print('dyn_load modules:', [m for m, v in out.items() if v['dyn_load']])
print('src_rewrite modules (%d):' % sum(1 for v in out.values() if v['src_rewrite']), [m for m, v in out.items() if v['src_rewrite']][:60])
