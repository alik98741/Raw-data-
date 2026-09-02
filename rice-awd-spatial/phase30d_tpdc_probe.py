#!/usr/bin/env python3
from __future__ import annotations
import csv, json, os, re, urllib.parse, urllib.request
from pathlib import Path

OUT=Path(os.environ.get('OUT_DIR','phase30d_tpdc_probe')); OUT.mkdir(parents=True,exist_ok=True)
UA='Mozilla/5.0 rice-awd-eja/1.0'
PAGES=[
 'https://data.tpdc.ac.cn/zh-hans/data/2e46eb77-3ca2-4b90-9a42-fd49f10630d4',
 'https://data.tpdc.ac.cn/en/data/2e46eb77-3ca2-4b90-9a42-fd49f10630d4',
]

def fetch(url, timeout=60):
 req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'text/html,application/json,*/*'})
 with urllib.request.urlopen(req,timeout=timeout) as r:
  return r.geturl(), r.headers.get('content-type',''), r.read()

rows=[]; texts=[]
for idx,url in enumerate(PAGES):
 try:
  final,ct,b=fetch(url); txt=b.decode('utf-8',errors='ignore')
  (OUT/f'page_{idx}.html').write_text(txt,encoding='utf-8')
  rows.append({'kind':'page','source':url,'resolved':final,'status':'PASS','content_type':ct,'bytes':len(b)})
  texts.append((final,txt))
 except Exception as e:
  rows.append({'kind':'page','source':url,'status':'ERROR','error':repr(e)})

# Collect URLs, API-looking strings, data id references, bundle/file names, and script srcs.
patterns=[
 r'https?://[^\"\'<>\\\s]+',
 r'[\"\']([^\"\']*(?:api|download|file|resource|dataset|data)[^\"\']*)[\"\']',
 r'[\"\']([^\"\']*(?:1-9\.zip|19-26\.zip|PHH2O5min\.nc|SAND5min\.nc)[^\"\']*)[\"\']',
]
hits=[]
script_urls=[]
for source,txt in texts:
 for m in re.finditer(r'<script[^>]+src=[\"\']([^\"\']+)[\"\']',txt,re.I):
  u=urllib.parse.urljoin(source,m.group(1)); script_urls.append(u); hits.append({'source':source,'kind':'script_src','value':u})
 for pat in patterns:
  for m in re.finditer(pat,txt,re.I):
   val=m.group(1) if m.lastindex else m.group(0)
   if '2e46eb77' in val or any(k in val.lower() for k in ['api','download','file','resource','1-9.zip','19-26.zip','phh2o','sand5min']):
    hits.append({'source':source,'kind':'page_hit','value':val[:3000]})

# Fetch a bounded number of JS assets and search them for API routes / data UUID / file names.
seen=set(); js_hits=[]
for j,u in enumerate(script_urls[:40]):
 if u in seen: continue
 seen.add(u)
 try:
  final,ct,b=fetch(u,timeout=60)
  if len(b)>8_000_000: continue
  txt=b.decode('utf-8',errors='ignore')
  (OUT/f'js_{j}.txt').write_text(txt,encoding='utf-8')
  needles=['2e46eb77','download','api/','file','resource','1-9.zip','19-26.zip','phh2o','sand5min']
  for needle in needles:
   for m in re.finditer(re.escape(needle),txt,re.I):
    s=max(0,m.start()-350); e=min(len(txt),m.end()+700)
    js_hits.append({'script':final,'needle':needle,'context':txt[s:e].replace('\n',' ')[:2500]})
    if sum(1 for x in js_hits if x['script']==final and x['needle']==needle)>=8: break
 except Exception as e:
  rows.append({'kind':'script','source':u,'status':'ERROR','error':repr(e)})

# Probe plausible API patterns (non-destructive GET only).
uuid='2e46eb77-3ca2-4b90-9a42-fd49f10630d4'
probe_urls=[]
for base in ['https://data.tpdc.ac.cn','https://data.tpdc.ac.cn/api','https://data.tpdc.ac.cn/api/v1','https://data.tpdc.ac.cn/api/v2']:
 for path in [f'/data/{uuid}',f'/dataset/{uuid}',f'/resource/{uuid}',f'/datasets/{uuid}',f'/data/detail/{uuid}',f'/data/file/{uuid}',f'/data/files/{uuid}',f'/files/{uuid}']:
  probe_urls.append(base+path if not base.endswith('/api') and not base.endswith('/v1') and not base.endswith('/v2') else base+path)
for i,u in enumerate(dict.fromkeys(probe_urls)):
 try:
  final,ct,b=fetch(u,timeout=30); txt=b.decode('utf-8',errors='ignore')
  status='PASS'
  rows.append({'kind':'api_probe','source':u,'resolved':final,'status':status,'content_type':ct,'bytes':len(b),'preview':re.sub(r'\s+',' ',txt)[:1000]})
  if 'json' in ct.lower() or txt.lstrip().startswith(('{','[')):
   (OUT/f'api_probe_{i}.txt').write_text(txt,encoding='utf-8')
 except Exception as e:
  rows.append({'kind':'api_probe','source':u,'status':'ERROR','error':repr(e)})

def write_csv(path, data):
 fields=sorted({k for r in data for k in r}) if data else ['empty']
 with open(path,'w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=fields); w.writeheader();
  if data:w.writerows(data)
write_csv(OUT/'probe_audit.csv',rows)
write_csv(OUT/'page_hits.csv',hits)
write_csv(OUT/'js_hits.csv',js_hits)
summary={'pages_ok':sum(r.get('kind')=='page' and r.get('status')=='PASS' for r in rows),'script_urls':len(set(script_urls)),'page_hits':len(hits),'js_hits':len(js_hits),'api_probe_pass':sum(r.get('kind')=='api_probe' and r.get('status')=='PASS' for r in rows)}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary,indent=2))
