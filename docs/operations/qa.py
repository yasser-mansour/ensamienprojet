"""Structural, extraction, font and geometry QA for documentation outputs."""
from pathlib import Path
import json,hashlib
from pypdf import PdfReader
import pymupdf as fitz
H=Path(__file__).resolve().parent;O=H/'deliverables';m=json.loads((O/'manifest.json').read_text());r=PdfReader(O/'ENERGY_LAB_NINE_PRESENTER_OPERATIONS_MANUAL.pdf');checks=[]
def check(name,cond):
 checks.append({'check':name,'pass':bool(cond)})
 assert cond,name
check('master page count',len(r.pages)==m['master_pages'])
check('88 slide owners',set(map(int,m['owners']))==set(range(1,89)) and set(m['owners'].values())==set(range(1,10)))
s=m['segments'];check('contiguous 105 minute timeline',s[0][0]==0 and s[-1][1]==105 and all(a[1]==b[0] for a,b in zip(s,s[1:])))
check('five mission counts',m['mission_question_counts']==[5,8,7,5,1])
for i,(a,b) in m['presenter_ranges'].items():
 q=PdfReader(O/f'ENERGY_LAB_PRESENTER_{int(i):02d}.pdf');check(f'P{i} exact text extraction',len(q.pages)==b-a+1 and all(x.extract_text()==y.extract_text() for x,y in zip(q.pages,r.pages[a-1:b])))
 qdoc=fitz.open(O/f'ENERGY_LAB_PRESENTER_{int(i):02d}.pdf');master=fitz.open(O/'ENERGY_LAB_NINE_PRESENTER_OPERATIONS_MANUAL.pdf')
 check(f'P{i} identical rendered page pixels',all(qdoc[j].get_pixmap().samples==master[a-1+j].get_pixmap().samples for j in range(len(qdoc))))
c=PdfReader(O/'ENERGY_LAB_QUICK_REFERENCE_CARDS.pdf');check('nine one-page quick cards',len(c.pages)==9)
for j,p in enumerate(c.pages):
 # Footer page differs; body should match card in master.
 a=r.pages[m['quick_card_master_pages'][j]-1].extract_text().split('one-page quick reference',1)[1]
 b=p.extract_text().split('one-page quick reference',1)[1]
 check(f'P{j+1} quick card matches master',a==b)
font_problems=[]
for page in r.pages:
 for name,f in page['/Resources']['/Font'].items():
  f=f.get_object(); desc=f.get('/FontDescriptor')
  # ReportLab includes unused standard Helvetica resource; check actual fonts through fitz below.
  if desc and not any(k in desc.get_object() for k in ('/FontFile','/FontFile2','/FontFile3')):font_problems.append(str(name))
check('font descriptors embedded',not font_problems)
doc=fitz.open(O/'ENERGY_LAB_NINE_PRESENTER_OPERATIONS_MANUAL.pdf');bad=[];fonts=set()
for n,p in enumerate(doc):
 for block in p.get_text('dict')['blocks']:
  for line in block.get('lines',[]):
   for span in line['spans']:
    fonts.add(span['font']);x0,y0,x1,y1=span['bbox']
    if x0<40 or x1>555 or y0<10 or y1>827:bad.append((n+1,span['text'],span['bbox']))
check('text stays inside page margins',not bad)
check('rendered text uses embedded Arial fonts',all('Arial' in f for f in fonts))
check('no replacement or DEL glyphs',all('\ufffd' not in p.extract_text() and '\x7f' not in p.extract_text() for p in r.pages))
for p,h in m['sources'].items():check('source checksum '+p,hashlib.sha256((H.parents[1]/p).read_bytes()).hexdigest()==h)
check('fixture unchanged',hashlib.sha256((H.parents[1]/'fixtures/energy_lab.json').read_bytes()).hexdigest()==m['fixture_sha256'])
report={'status':'PASS','checks':checks,'master_pages':len(r.pages),'fonts':sorted(fonts),'limitations':['No original manual QA script recovered; this script is newly added.','Geometry cannot alone certify layout; representative render review required.','No live deployed application or classroom acceptance test performed.','Original textbook and official audio unavailable.']}
(O/'QA_REPORT.json').write_text(json.dumps(report,indent=2));print(f'PASS: {len(checks)} checks; {len(r.pages)} master pages; fonts {sorted(fonts)}')
# Contact sheets of representative pages from every section and dossier, plus all cards.
from PIL import Image,ImageDraw
selected=sorted(set([1,2,3,4,5,6,11,12,13,14,15,17,22,23,24,28,29,32,33,34,35,36]+[v for a,b in m['presenter_ranges'].values() for v in [a,a+1,b-1,b]]))
tmp=H/'preview';tmp.mkdir(exist_ok=True)
for offset in range(0,len(selected),12):
 batch=selected[offset:offset+12];sheet=Image.new('RGB',(1200,((len(batch)+3)//4)*440),'#ccd1d5');draw=ImageDraw.Draw(sheet)
 for j,n in enumerate(batch):
  pix=doc[n-1].get_pixmap(matrix=fitz.Matrix(.48,.48),alpha=False);im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples);x=(j%4)*300;y=(j//4)*440;sheet.paste(im,(x,y+20));draw.text((x+5,y+3),f'Page {n}',fill='black')
 sheet.save(tmp/f'contact_{offset//12+1}.png')
