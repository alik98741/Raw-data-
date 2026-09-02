#!/usr/bin/env python3
from __future__ import annotations
import csv,json,os,re,urllib.parse,urllib.request
from pathlib import Path
OUT=Path(os.environ.get('OUT_DIR','phase30e_tpdc_file_inventory'));OUT.mkdir(parents=True,exist_ok=True)
BASE='https://data.tpdc.ac.cn'; MID='2e46eb77-3ca2-4b90-9a42-fd49f10630d4';UA='Mozilla/5.0 rice-awd-eja/1.0'

def request(url,method='GET',data=None,timeout=90):
    b=None;headers={'User-Agent':UA,'Accept':'application/json,text/plain,*/*'}
    if data is not None:
        b=json.dumps(data).encode();headers['Content-Type']='application/json'
    req=urllib.request.Request(url,data=b,headers=headers,method=method)
    with urllib.request.urlopen(req,timeout=timeout) as r:
        raw=r.read();ct=r.headers.get('content-type','');
    txt=raw.decode('utf-8',errors='ignore')
    return ct,txt

# Exact API shape recovered from deployed JavaScript.
audit=[]
try:
    ct,txt=request(BASE+'/view/metadataView/detail/','POST',{'userId':'','metadataId':MID})
    (OUT/'metadata_detail.json').write_text(txt,encoding='utf-8')
    detail=json.loads(txt);audit.append({'step':'metadata_detail','status':'PASS','code':detail.get('code'),'bytes':len(txt)})
except Exception as e:
    detail={};audit.append({'step':'metadata_detail','status':'ERROR','error':repr(e)})

# Try exact enclosure paths implied by baseURL=/file + relative /file/...
roots=[]
for ep in [
    BASE+f'/file/file/getRootFileDataList?metadataId={MID}',
    BASE+f'/file/getRootFileDataList?metadataId={MID}',
]:
    try:
        ct,txt=request(ep)
        name='root_'+str(len(roots))+'.txt';(OUT/name).write_text(txt,encoding='utf-8')
        obj=json.loads(txt); audit.append({'step':'root','endpoint':ep,'status':'PASS','code':obj.get('code'),'bytes':len(txt)})
        if str(obj.get('code'))=='200':roots=obj.get('data') or obj.get('context') or [];break
    except Exception as e:audit.append({'step':'root','endpoint':ep,'status':'ERROR','error':repr(e)})

# Normalize arbitrary file node structures and recursively traverse folders.
def flatten_nodes(x):
    if isinstance(x,list):return x
    if isinstance(x,dict):
        for k in ['records','list','rows','data','children','fileList']:
            if isinstance(x.get(k),list):return x[k]
    return []

def node_name(n):
    for k in ['name','fileName','filename','orginName','originalName','title','label']:
        if n.get(k):return str(n[k])
    return ''
def node_id(n):
    for k in ['id','fileId','fileID']:
        if n.get(k) is not None:return str(n[k])
    return ''
def is_folder(n):
    vals=' '.join(str(n.get(k,'')) for k in ['type','fileType','isDir','directory','folder','nodeType']).lower()
    return any(v in vals for v in ['folder','dir','true']) or bool(n.get('children'))

queue=list(flatten_nodes(roots));seen=set();inventory=[]
max_nodes=2000
while queue and len(inventory)<max_nodes:
    n=queue.pop(0)
    if not isinstance(n,dict):continue
    nid=node_id(n);name=node_name(n)
    key=(nid,name)
    if key in seen:continue
    seen.add(key)
    inventory.append({'id':nid,'name':name,'is_folder_guess':is_folder(n),'raw_json':json.dumps(n,ensure_ascii=False)[:5000]})
    # embedded children
    for ch in flatten_nodes(n.get('children',[])):queue.append(ch)
    # explicitly traverse every node id; endpoint harmlessly returns [] for files.
    if nid:
        for ep in [BASE+f'/file/file/getFileDataList?parentId={urllib.parse.quote(nid)}',BASE+f'/file/getFileDataList?parentId={urllib.parse.quote(nid)}']:
            try:
                ct,txt=request(ep,timeout=30);obj=json.loads(txt)
                if str(obj.get('code'))=='200':
                    kids=flatten_nodes(obj.get('data') or obj.get('context') or [])
                    if kids:
                        queue.extend(kids);break
            except Exception:pass

with open(OUT/'file_inventory.csv','w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=['id','name','is_folder_guess','raw_json']);w.writeheader();w.writerows(inventory)
targets=[r for r in inventory if any(s in r['name'].lower() for s in ['1-9.zip','19-26.zip','phh2o5min','sand5min','phh2o','sand'])]
with open(OUT/'target_files.csv','w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=['id','name','is_folder_guess','raw_json']);w.writeheader();w.writerows(targets)
with open(OUT/'audit.csv','w',newline='',encoding='utf-8') as f:
    fields=sorted({k for r in audit for k in r});w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(audit)
summary={'detail_code':detail.get('code'),'inventory_nodes':len(inventory),'targets':len(targets),'target_names':[r['name'] for r in targets]}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(summary,indent=2,ensure_ascii=False))
