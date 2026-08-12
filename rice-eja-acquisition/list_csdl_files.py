import json,urllib.request,re
from pathlib import Path
OUT=Path('rice-eja-acquisition/csdl-files');OUT.mkdir(parents=True,exist_ok=True)
BASE='https://www.scidb.cn'
DS='cbd2c393a5ad4056a1bd9130ca1340f6'; VER='V2'
UA={'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*','Content-Type':'application/json;charset=UTF-8','Referer':'https://www.scidb.cn/en/s/ZZJzAz'}

def post(path,obj):
 data=json.dumps(obj).encode()
 req=urllib.request.Request(BASE+path,data=data,headers=UA,method='POST')
 with urllib.request.urlopen(req,timeout=90) as r: return json.loads(r.read().decode('utf-8','replace'))

def get(path):
 req=urllib.request.Request(BASE+path,headers=UA)
 with urllib.request.urlopen(req,timeout=90) as r: return r.geturl(),dict(r.headers),r.read(2_000_000)

# root and large-page listing
roots=[]
for path in ['/','']:
 try:
  j=post('/gin-sdb-filetree/public/file/childrenFileListByPath',{'dataSetId':DS,'version':VER,'path':path,'lastIndex':0,'pageSize':2000})
  roots.append({'path':path,'response':j})
 except Exception as e: roots.append({'path':path,'error':repr(e)})
(OUT/'root_responses.json').write_text(json.dumps(roots,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(roots,ensure_ascii=False)[:10000])

# Search public tree for high-value terms; this endpoint may recursively search.
terms=['1km','clay','sand','silt','bulk','density','organic','carbon','SOC','CEC','pH','nitrogen','porosity','q0.05','q0.95','mean']
search=[]
for term in terms:
 try:
  j=post('/gin-sdb-filetree/public/file/searchTreeList',{'dataSetId':DS,'version':VER,'search':term})
  search.append({'term':term,'response':j})
 except Exception as e: search.append({'term':term,'error':repr(e)})
(OUT/'search_responses.json').write_text(json.dumps(search,indent=2,ensure_ascii=False),encoding='utf-8')

# Flatten likely file objects from both responses.
flat=[]
def walk(x,ctx=''):
 if isinstance(x,dict):
  # capture dicts that resemble nodes/files
  keys=set(x)
  if keys & {'name','fileName','label','path','id','fileId','size','type'}:
   flat.append({'context':ctx,**{k:x.get(k) for k in ['id','fileId','name','fileName','label','path','type','size','fileSize','parentId'] if k in x}})
  for k,v in x.items(): walk(v,ctx+'/'+str(k))
 elif isinstance(x,list):
  for i,v in enumerate(x): walk(v,ctx+f'[{i}]')
for r in roots: walk(r,'root')
for r in search: walk(r,'search:'+r.get('term',''))
# dedupe serialized
seen=set(); uniq=[]
for r in flat:
 s=json.dumps(r,sort_keys=True,ensure_ascii=False)
 if s not in seen:seen.add(s);uniq.append(r)
(OUT/'flattened_nodes.json').write_text(json.dumps(uniq,indent=2,ensure_ascii=False),encoding='utf-8')
print('flattened nodes',len(uniq))
for r in uniq[:200]: print(r)
