#!/usr/bin/env python3
"""Extract factual S14-S23 cells from the identified Tosi supplement, not OCR.
SPDX-License-Identifier: AGPL-3.0-only

Authoring-only dependencies: pdfplumber and pypdf. Runtime comparison needs only JSON.
Italic digit fonts encode periodic regimes; unequal endpoints do not imply one.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re

TABLES=(('YACC',('25x25','50x50','100x100','150x150')),
        ('Plaatjes',('32x32r','64x64r','128x128r')),
        ('CHIC',('20x20','40x40','80x80','120x120')),
        ('GAIA',('25x25','50x50','100x100','100rx100r')),
        ('StreamV',('20x20','40x40','80x80','160x160')),
        ('StagYY',('32x32','64x64','128x128')),
        ('FEniCS',('20x20','40x40','80x80','120x120')),
        ('Fluidity',('32x32','64x64','128x128')),
        ('ASPECT',('32x32','64x64','128x128')),
        ('MC3D',('40x40','80x80','100x100','200x200')))


def extract(path):
    import pdfplumber
    from pypdf import PdfReader
    data=path.read_bytes();reader=PdfReader(path);tables=[]
    with pdfplumber.open(path) as pdf:
        if len(pdf.pages)!=30:raise ValueError('Expected the 30-page supplement')
        for index,(code,meshes) in enumerate(TABLES,20):
            page=pdf.pages[index];words=page.extract_words(extra_attrs=['fontname'])
            # The first data column contains isolated decimal yields, never pairs.
            yields=[w for w in words if re.fullmatch(r'[2-5]\.\d',w['text'])]
            if not yields:raise ValueError('Missing yield column')
            x=min(w['x0'] for w in yields);yields=[w for w in yields if abs(w['x0']-x)<1]
            rows={}
            # Independently extracted logical lines cross-check the numeric pairs.
            logical={}
            for line in reader.pages[index].extract_text(extraction_mode='layout').splitlines():
                m=re.match(r'\s*([2-5]\.\d)\s+(.*)',line)
                if m:logical[m[1]]=re.findall(r'\(\s*([0-9.]+)(?:,\s*|\s+)([0-9.]+)\s*\)|([–−-])',m[2])
            for y in yields:
                line=sorted((w for w in words if abs(w['top']-y['top'])<2 and w['x0']>y['x1']+1),key=lambda w:w['x0'])
                cells=[];i=0
                while i<len(line):
                    word=line[i]
                    if word['text'] in ('–','−','-'):cells.append(None);i+=1;continue
                    parts=[]
                    while i<len(line):
                        parts.append(line[i]);i+=1
                        if parts[-1]['text'].endswith(')'):break
                    match=re.fullmatch(r'\(\s*([0-9.]+)(?:,\s*|\s+)([0-9.]+)\s*\)', ' '.join(w['text'] for w in parts))
                    if match is None:raise ValueError(('Unrecognised cell',code,y['text'],parts))
                    fonts={w['fontname'].split('+')[-1] for w in parts if any(c.isdigit() for c in w['text'])}
                    if len(fonts)!=1:raise ValueError(('Mixed cell font',fonts))
                    font=fonts.pop()
                    if font not in ('CMR12','CMTI12'):raise ValueError(('Unknown regime font',font))
                    cells.append([match[1],match[2],'periodic' if font=='CMTI12' else 'steady'])
                if len(cells)!=len(meshes):raise ValueError(('Column count',code,y['text'],len(cells)))
                cross=[None if dash else [lo,hi] for lo,hi,dash in logical[y['text']]]
                if [None if c is None else c[:2] for c in cells]!=cross:raise ValueError('Independent extraction disagrees')
                if y['text'] in rows:raise ValueError('Duplicate yield row')
                rows[y['text']]=cells
            tables.append(dict(code=code,table=f'S{index-6}',page=index+1,meshes=list(meshes),rows=rows))
    return dict(schema='atlas.tosi-case5b-reference.v1',source=dict(
        doi='10.1002/2015GC005807',filename='ggge20762-sup-0001-2015GC005807-SupInfo.pdf',
        sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),pages=30,
        locator='Introduction page 4; Tables S14-S23 pages 21-30',
        rights='Factual numerical transcription only; original article/supplement rights remain separate.'),
        columns=['Nu_top_min_as_printed','Nu_top_max_as_printed','regime_from_digit_font'],
        missing='null is an explicit printed dash; absent row means the yield was not tabulated',
        excluded_codes={'MC3D':'Laterally averaged viscosity; different constitutive approximation'},tables=tables)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('pdf',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=extract(args.pdf)
    # Compact one row per line retains printed decimal strings and source structure.
    text=json.dumps({k:v for k,v in result.items() if k!='tables'},indent=2)[:-2]+',\n  "tables": [\n'
    pieces=[]
    for table in result['tables']:
        prefix=json.dumps({k:v for k,v in table.items() if k!='rows'},ensure_ascii=True)
        rows=',\n'.join('      '+json.dumps(k)+': '+json.dumps(v) for k,v in table['rows'].items())
        pieces.append('    '+prefix[:-1]+', "rows": {\n'+rows+'\n    }}')
    text+=',\n'.join(pieces)+'\n  ]\n}\n'
    if json.loads(text)!=result:raise ValueError('Serialisation mismatch')
    with args.output.open('x',encoding='utf-8',newline='\n') as stream:stream.write(text)
    print(json.dumps(dict(tables=len(result['tables']),source_sha256=result['source']['sha256'],
        cells=sum(c is not None for t in result['tables'] for row in t['rows'].values() for c in row))))


if __name__=='__main__':main()
