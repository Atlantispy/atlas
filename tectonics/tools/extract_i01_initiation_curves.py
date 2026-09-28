#!/usr/bin/env python3
"""New extraction, not the lost historical script. Units: page pt and 1e12 N/m.
Map: value=v0+(point-p0)*a; b is the equivalent affine intercept.
Ticks: x first/last labelled; y 0 and 4. Other ticks give residuals, not bounds.
Underlying paths, including overdrawn parts; no smoothing, extrapolation,
work integration, fabricated joins or reconstruction of hidden ink.
"""
import hashlib
import json
import math
import platform
import sys
import unittest
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from pathlib import Path
import pymupdf as pdf
SHA = 'c4f1834908bb1e0a3f520a0b810e8fe967352075e97950504c54cb9ad8e1287d'
CONFIG = [
dict(fig='8b', page=17, xref=84, contents=[86],
   frames=[261,289,291,323],
   xticks=[(292,0),(294,20),(297,40),(300,60),(303,80),(306,100)],
   yticks=[(262,0),(264,1),(270,2),(276,3),(282,4)],
   km_per_x=1, xs=[5,10,20,30,40,50],
   curves=[('figure8b_case1',325,324,4244,(1.,0.,0.)),
       ('figure8b_case5',260,259,1660,(0.,0.,0.))],
   width=0.9240000247955322),
dict(fig='13a', page=22, xref=112, contents=[114],
   frames=[2,44,46,65],
   xticks=[(47,0),(49,2),(51,4),(53,6)],
   yticks=[(3,-1),(10,0),(12,1),(18,2),(24,3),(30,4)],
   km_per_x=20, xs=[10,20,40,60,80,100,109,120],
   curves=[('figure13a_case23_right40Myr',67,66,650,(0.,0.,1.)),
       ('figure13a_case23_left10Myr',1,0,598,
       (1.,0.3919999897480011,0.3919999897480011))],
   width=0.9679999947547913)
]
def need(ok, why):
  if not ok:
    raise ValueError(why)
def digest(value):
  return hashlib.sha256(json.dumps(value, separators=(',', ':'),
                  allow_nan=False).encode()).hexdigest()
class Axis:
  def __init__(self, p0, v0, p1, v1):
    need(p0 != p1 and v0 != v1, 'degenerate axis')
    self.p0, self.v0 = p0, v0
    self.a = (v1-v0)/(p1-p0)
    self.b = v0-self.a*p0
  def value(self, p):
    return self.v0+(p-self.p0)*self.a
  def point(self, v):
    return self.p0+(v-self.v0)/self.a
def clip(a, b, box):
  """Closed Liang-Barsky slab clipping. Retain both endpoints; no epsilon.
  Vertical/horizontal/point segments handled without division by zero.
  Reversed segments retain their original orientation. No new connectors.
  """
  lo, hi = 0., 1.
  for j in (0, 1):
    d = b[j]-a[j]
    if d == 0:
      if not box[j] <= a[j] <= box[j+2]:
        return None
    else:
      s, t = sorted(((box[j]-a[j])/d, (box[j+2]-a[j])/d))
      lo, hi = max(lo, s), min(hi, t)
      if lo > hi:
        return None
  return [[a[j]+r*(b[j]-a[j]) for j in (0,1)] for r in (lo,hi)]
def extrema(segments, box):
  ys, hits = [], 0
  for a,b in segments:
    c = clip(a,b,box)
    if c is not None:
      hits += 1
      ys.extend([c[0][1],c[1][1]])
  need(ys, 'no segment intersects requested closed slab')
  return min(ys), max(ys), hits
def outward(lo, hi):
  need(math.isfinite(lo) and math.isfinite(hi) and lo <= hi, 'invalid band')
  q = Decimal('0.01')
  return [float(Decimal.from_float(lo).quantize(q, rounding=ROUND_FLOOR)),
      float(Decimal.from_float(hi).quantize(q, rounding=ROUND_CEILING))]
class Tests(unittest.TestCase):
  def test_axes(self):
    x,y=Axis(10,0,30,100),Axis(30,0,10,4)
    self.assertEqual((x.value(20),x.point(25),y.value(15)),(50,15,3))
  def test_clipping(self):
    box=(1,1,2,3)
    self.assertEqual(clip((0,0),(4,4),box),[[1,1],[2,2]])
    self.assertEqual(clip((4,4),(0,0),box),[[2,2],[1,1]])
    self.assertEqual(clip((1,0),(1,4),box),[[1,1],[1,3]])
    self.assertIsNone(clip((0,0),(0,4),box))
  def test_endpoints(self):
    self.assertEqual(clip((0,2),(1,2),(1,1,2,3)),[[1,2],[1,2]])
    self.assertEqual(clip((1,2),(1,2),(1,1,2,3)),[[1,2],[1,2]])
  def test_multiple(self):
    self.assertEqual(extrema([((0,1),(2,1)),((1,0),(1,3)),
                 ((0,4),(2,4))],(.5,-1,1.5,5)),(0,4,3))
    with self.assertRaises(ValueError):
      extrema([((0,0),(0,1))],(2,2,3,3))
  def test_rounding(self):
    self.assertEqual(outward(-1.125,1.125),[-1.13,1.13])
    self.assertEqual(outward(.5,.5),[.5,.5])
    self.assertEqual(outward(math.nextafter(.5,-math.inf),
                 math.nextafter(.5,math.inf)),[.49,.51])
def extract(path):
  need(pdf.VersionBind=='1.26.7' and pdf.VersionFitz=='1.26.12',
    'parser version differs: review required, no automatic fallback')
  raw=Path(path).read_bytes()
  need(hashlib.sha256(raw).hexdigest()==SHA, 'source PDF SHA256 mismatch')
  out=dict(task='MC02-CURVE-REPRO-20260928',status='UNACCEPTED_NEW_EXTRACTION',
   source_sha256=SHA,source_bytes=len(raw),
   versions=[platform.python_version(),pdf.VersionBind,pdf.VersionFitz],
   coordinates='Unrotated PyMuPDF points, top-left origin; x right, y down; 72 pt/inch',
   raw_pdf_to_page=[1,0,0,-1,0,789],
   force_unit='1e12 N/m',rounding_quantum=0.01,
   uncertainty={'line_width':'assumed half-width rectangular reading band, not exact ink geometry',
         'axis_systematic':'unquantified; tick residuals are diagnostics only',
         'physical_model':'not provided'},
   tick_schema=['seqno','page_coordinate_pt','label','affine_residual'],
   map_schema=['p0','v0','a','b'],
   row_schema=['km','x_pt','ymin_pt','ymax_pt','raw_Flo','raw_Fhi','rounded_lo','rounded_hi','hits'],
   panels=[])
  with pdf.open(stream=raw,filetype='pdf') as doc:
    need(len(doc)==31,'unexpected page count')
    for c in CONFIG:
      p=doc[c['page']-1]
      need(p.rotation==0 and list(p.rect)==[0,0,610,789] and
        list(p.cropbox)==[0,0,610,789] and list(p.mediabox)==[0,0,610,789],
        'unexpected page geometry')
      need(list(p.transformation_matrix)==out['raw_pdf_to_page'], 'page transform')
      need(p.xref==c['xref'] and p.get_contents()==c['contents'], 'PDF object IDs')
      ds=p.get_drawings(extended=True)
      def one(seq):
        found=[d for d in ds if d.get('seqno')==seq]
        need(len(found)==1, f'ambiguous seqno {seq}')
        return found[0]
      def line(seq):
        d=one(seq)
        need(d['type']=='s' and d['color']==(0.,0.,0.) and
          len(d['items'])==1 and d['items'][0][0]=='l','axis path changed')
        return d['items'][0][1:]
      left,right,bottom,top=[line(s) for s in c['frames']]
      box=[left[0].x,top[0].y,right[0].x,bottom[0].y]
      l,t,r,b=box
      need(list(left[0])==[l,b] and list(left[1])==[l,t] and
        list(right[0])==[r,b] and list(right[1])==[r,t] and
        list(bottom[0])==[l,b] and list(bottom[1])==[r,b] and
        list(top[0])==[l,t] and list(top[1])==[r,t], 'panel not rectangle')
      def ticks(spec,j):
        ans=[]
        for seq,v in spec:
          a,z=line(seq)
          need((a.x==z.x and a.y==b and z.y>b) if j==0 else
            (a.y==z.y and a.x==l and z.x<l), 'tick orientation')
          ans.append([seq,a[j],v])
        return ans
      xt,yt=ticks(c['xticks'],0),ticks(c['yticks'],1)
      x=Axis(xt[0][1],xt[0][2],xt[-1][1],xt[-1][2])
      zero=next(v for v in yt if v[2]==0)
      y=Axis(zero[1],0,yt[-1][1],yt[-1][2])
      panel=dict(figure=c['fig'],page=c['page'],page_xref=p.xref,
       contents=p.get_contents(), panel_pt=box, frame_seqnos=c['frames'],
       xticks=[z+[x.value(z[1])-z[2]] for z in xt],
       yticks=[z+[y.value(z[1])-z[2]] for z in yt],
       x_axis_unit='km' if c['km_per_x']==1 else 'Myr',
       km_per_x=c['km_per_x'],
       x_map=[x.p0,x.v0,x.a,x.b],y_map=[y.p0,y.v0,y.a,y.b],
       width_pt=c['width'],halfwidth_pt=c['width']/2,
       halfwidth_km=c['width']/2*x.a*c['km_per_x'],
       halfwidth_force=c['width']/2*abs(y.a),
       stroke={'opacity':1,'fill':None,'dash':'[] 0','caps':[0,0,0],'join':0},
       clip_guard='level 0, no preceding clip/group; expanded samples inside panel',
       curves={})
      for name,seq,index,count,rgb in c['curves']:
        matches=[]
        for i,d in enumerate(ds):
          if (d['type']=='s' and d['color']==rgb and
            len(d['items'])>100 and all(z[0]=='l' for z in d['items']) and
            l<=d['rect'].x0<=d['rect'].x1<=r and
            t<=d['rect'].y0<=d['rect'].y1<=b):
            matches.append((i,d))
        need(len(matches)==1, f'curve selection ambiguous/missing: {name}')
        i,d=matches[0]
        need((i,d['seqno'],len(d['items']),d['width'])==
          (index,seq,count,c['width']), 'selected path identity changed')
        need(d['level']==0 and not any(z['type'] in ('clip','group') for z in ds[:i]),
          'unsupported clipping/group before selected path')
        need(d['fill'] is None and d['stroke_opacity']==1 and
          d['dashes']=='[] 0' and not d['closePath'] and
          d['lineCap']==(0,0,0) and d['lineJoin']==0, 'unsupported stroke style')
        seg=[(list(z[1]),list(z[2])) for z in d['items']]
        h=d['width']/2
        rows=[]
        for km in c['xs']:
          xp=x.point(km/c['km_per_x'])
          need(l<xp-h<xp+h<r, 'horizontal reading slab reaches panel border')
          ymin,ymax,hits=extrema(seg,(xp-h,t,xp+h,b))
          need(t<ymin-h and ymax+h<b, 'expanded band clipped at panel border')
          flo,fhi=y.value(ymax+h),y.value(ymin-h)
          rows.append([km,xp,ymin,ymax,flo,fhi,*outward(flo,fhi),hits])
        panel['curves'][name]=dict(draw_index=i,seqno=seq,segments=count,
         segment_sha256=digest(seg),rgb=list(rgb),bbox_pt=list(d['rect']),
         subpath_break_indices=[j for j in range(1,len(seg)) if seg[j-1][1]!=seg[j][0]],
         samples=rows)
      out['panels'].append(panel)
  return out
HISTORY=[
[[2.94,3.02],[3.,3.07],[1.96,2.14],[1.03,1.15],[.83,.92],[.74,.87]],
[[3.03,3.12],[3.09,3.16],[2.27,2.43],[1.07,1.19],[.9,1.02],[.81,.91]],
[[2.09,2.27],[1.6,1.7],[1.05,1.16],[.83,.95],[.64,.77],[.17,.33],[.07,.23],[.23,.37]],
[[1.22,1.4],[.63,.69],[-.07,0.],[-.33,-.27],[-.59,-.53],[-.99,-.93],[-1.16,-1.08],[-.98,-.88]]]
def main():
  need(len(sys.argv)==3,'usage: extract_mc02.py INPUT.pdf NEW_OUTPUT.json')
  dest=Path(sys.argv[2])
  need(not dest.exists(),'refuse overwrite of existing evidence')
  tests=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
  need(tests.wasSuccessful(),'synthetic tests failed')
  result=extract(sys.argv[1])
  changes=[]; same=0
  for c,old in zip([c for p in result['panels'] for c in p['curves'].values()],HISTORY,strict=True):
    for row,prev in zip(c['samples'],old,strict=True):
      if row[6:8]==prev: same+=1
      else: changes.append(dict(seqno=c['seqno'],distance_km=row[0],old=prev,new=row[6:8]))
  result['history_comparison']=dict(identical_rounded_bands=same,changed_bands=changes,
   raw_force_differences='unavailable: historical unrounded extrema were not retained',
   horizontal_halfwidth_delta_km=[p['halfwidth_km']-old
                  for p,old in zip(result['panels'],[.1774548014942117,.46882568520171836])])
  result['tests']=dict(run=tests.testsRun,failures=len(tests.failures),errors=len(tests.errors))
  text=json.dumps(result,separators=(',', ':'),allow_nan=False)+'\n'
  with dest.open('x',encoding='utf-8') as f: f.write(text)
  print(text,end='')
if __name__=='__main__':
  main()
