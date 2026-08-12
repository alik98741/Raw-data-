from __future__ import annotations
import urllib.request,re,json
from pathlib import Path
BASE='https://data.tpdc.ac.cn'
UUID='46ddd893-3b2b-4bb3-b9e6-b043f3c5c3a2'
OUT=Path('rice-eja-acquisition/tpdc-csdl-v10');OUT.mkdir(parents=True,exist_ok=True)
H={'User-Agent':'Mozilla/5.0','Accept':'*/*'}
def fetch(path,limit=20_000_000):
 req=urllib.request.Request(BASE+path,headers=H)
 with urllib.request.urlopen(req,timeout=120) as r:return r.read(limit).decode('utf-8','replace'),r.geturl(),dict(r.headers)
files={}
for name,path in [('config','/config.js'),('proxy','/proxy.min.js'),('app','/static/js/app.d0a2e637.js')]:
 try:
  t,u,h=fetch(path); files[name]=t; (OUT/(name+'.js')).write_text(t,encoding='utf-8'); print(name,len(t),u)
 except Exception as e: print(name,'ERROR',repr(e)); files[name]=''
text='\n'.join(files.values())
# Extract URL-like/API/file/download/ftp strings and contexts.
strs=set(re.findall(r'["\']([^"\']{4,300})["\']',text))
keep=[]
keys=['api','download','file','ftp','resource','dataset','dataSet','data/','login','token','uuid','detail']
for s in strs:
 if any(k.lower() in s.lower() for k in keys): keep.append(s)
keep=sorted(keep,key=lambda x:(len(x),x))
(OUT/'candidate_strings.txt').write_text('\n'.join(keep),encoding='utf-8')
# Contexts around target UUID and useful keywords.
contexts=[]
for pat in [UUID,'download','ftp','fileList','dataList','dataset','resource','api/']:
 for m in list(re.finditer(re.escape(pat),text,re.I))[:100]:
  contexts.append({'pattern':pat,'context':text[max(0,m.start()-400):m.start()+800]})
(OUT/'contexts.json').write_text(json.dumps(contexts,indent=2,ensure_ascii=False),encoding='utf-8')
# Probe common JSON API patterns inferred from other TPDC frontends.
paths=[
 f'/api/data/{UUID}', f'/api/data/detail/{UUID}', f'/api/dataset/{UUID}', f'/api/dataset/detail/{UUID}',
 f'/api/v1/data/{UUID}', f'/api/v1/dataset/{UUID}', f'/api/data/get/{UUID}',
 f'/view/data/getDataInfo?dataId={UUID}', f'/view/data/getDataDetail?dataId={UUID}',
 f'/data-service/api/data/{UUID}'
]
probes=[]
for p in paths:
 try:
  req=urllib.request.Request(BASE+p,headers={'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*'})
  with urllib.request.urlopen(req,timeout=30) as r:
   b=r.read(1_000_000).decode('utf-8','replace'); probes.append({'path':p,'status':r.status,'ct':r.headers.get('content-type'),'head':b[:3000]})
 except Exception as e: probes.append({'path':p,'error':repr(e)})
(OUT/'api_probes.json').write_text(json.dumps(probes,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(probes,indent=2,ensure_ascii=False))
