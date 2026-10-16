"""Print string leaves of a JSON file that look like paths (compact summary)."""
import json, sys
d = json.load(open(sys.argv[1], encoding='utf8'))
pat = sys.argv[2].lower() if len(sys.argv) > 2 else ''
seen = set()
def walk(x, p=''):
    if isinstance(x, dict):
        for k, v in x.items(): walk(v, p + '.' + str(k))
    elif isinstance(x, list):
        for i, v in enumerate(x): walk(v, p + '[]')
    elif isinstance(x, str) and (chr(92) in x or '/' in x) and pat in (p + x).lower():
        if (p, x) not in seen:
            seen.add((p, x)); print(p, x)
walk(d)
