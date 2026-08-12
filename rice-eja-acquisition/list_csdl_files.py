import json, urllib.request
from pathlib import Path

OUT=Path('rice-eja-acquisition/csdl-files'); OUT.mkdir(parents=True,exist_ok=True)
BASE='https://www.scidb.cn'
DS='cbd2c393a5ad4056a1bd9130ca1340f6'; VER='V2'
END='/api/gin-sdb-filetree/public/file/childrenFileListByPath'
SEARCH='/api/gin-sdb-filetree/public/file/searchTreeList'
UA={'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*','Content-Type':'application/json;charset=UTF-8','Referer':'https://www.scidb.cn/en/s/ZZJzAz','Origin':'https://www.scidb.cn'}

def post(path,obj):
    data=json.dumps(obj).encode()
    req=urllib.request.Request(BASE+path,data=data,headers=UA,method='POST')
    with urllib.request.urlopen(req,timeout=90) as r:
        j=json.loads(r.read().decode('utf-8','replace'))
    if j.get('code') not in (20000,200,'20000','200'):
        raise RuntimeError(f"ScienceDB API error: {j}")
    return j

def children(path,page_size=1000):
    allrows=[]; last=0
    for _ in range(1000):
        j=post(END,{'dataSetId':DS,'version':VER,'path':path,'lastIndex':last,'pageSize':page_size})
        rows=j.get('data') or []
        if not rows: break
        allrows.extend(rows)
        # API uses index as paging position. Stop when fewer than requested.
        if len(rows)<page_size: break
        last=max(int(r.get('index',last)) for r in rows)+1
    return allrows

root=children('/'+VER)
(OUT/'root_V2.json').write_text(json.dumps(root,indent=2,ensure_ascii=False),encoding='utf-8')
print('root:',[(x.get('fileName'),x.get('path'),x.get('dir')) for x in root])
if not any(x.get('path')=='/V2/1km' for x in root):
    raise RuntimeError('CSDLv2 /V2/1km directory not found')

# Recursively enumerate only the 1-km branch.
allnodes=[]; queue=['/V2/1km']; seen=set()
while queue:
    p=queue.pop(0)
    if p in seen: continue
    seen.add(p)
    rows=children(p)
    print(p, len(rows))
    for r in rows:
        allnodes.append(r)
        if r.get('dir'):
            queue.append(r.get('path'))

(OUT/'CSDLv2_1km_all_nodes.json').write_text(json.dumps(allnodes,indent=2,ensure_ascii=False),encoding='utf-8')
files=[r for r in allnodes if not r.get('dir')]
(OUT/'CSDLv2_1km_files.json').write_text(json.dumps(files,indent=2,ensure_ascii=False),encoding='utf-8')

# Search endpoint is retained only as an independent cross-check.
terms=['clay','sand','silt','bulk','organic','carbon','cec','ph','nitrogen','porosity','mean','q0.05','q0.95']
search=[]
for term in terms:
    try:
        j=post(SEARCH,{'dataSetId':DS,'version':VER,'search':term})
        search.append({'term':term,'data':j.get('data')})
    except Exception as e:
        search.append({'term':term,'error':repr(e)})
(OUT/'search_crosscheck.json').write_text(json.dumps(search,indent=2,ensure_ascii=False),encoding='utf-8')

# Make a human-readable inventory of relevant candidate files.
keywords=['clay','sand','silt','bulk','bd','organic','soc','carbon','cec','ph','nitrogen','tn','porosity']
candidates=[]
for f in files:
    text=(f.get('fileName','')+' '+f.get('path','')).lower()
    if any(k in text for k in keywords):
        candidates.append({k:f.get(k) for k in ['id','fileName','path','size','md5','suffix','url','canPreview','index']})
(OUT/'CSDLv2_1km_study_candidates.json').write_text(json.dumps(candidates,indent=2,ensure_ascii=False),encoding='utf-8')
print('1km nodes',len(allnodes),'files',len(files),'study candidates',len(candidates))
for x in candidates[:250]: print(x)
