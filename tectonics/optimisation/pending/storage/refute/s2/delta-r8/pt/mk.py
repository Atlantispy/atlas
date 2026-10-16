import re,sys
from pathlib import Path
d = Path(sys.argv[1]); text = Path(sys.argv[2]).read_text(encoding='utf8')
parts = re.split(r'(?m)^--- (?=R/)', text)[1:]
for part in parts:
    name = part.split(' ',1)[0].split('/')[-1]
    body = part.split('\n',2)[2]
    out = d/(name+'.patch')
    out.write_text('--- a/%s\n+++ b/%s\n%s' % (name, name, body), encoding='utf8', newline='\n')
    print(out)
