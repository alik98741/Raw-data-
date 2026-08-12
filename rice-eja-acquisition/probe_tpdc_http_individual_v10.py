from __future__ import annotations
import json,urllib.request,urllib.parse,os,re
from pathlib import Path
UUID='46ddd893-3b2b-4bb3-b9e6-b043f3c5c3a2';BASE='https://data.tpdc.ac.cn';OUT=Path('rice-eja-acquisition/tpdc-http-individual-v10');OUT.mkdir(parents=True,exist_ok=True)
H={'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*','Referer':f'{BASE}/en/data/{UUID}'}
def req_json(url,method='GET',obj=None):
 data=json.dumps(obj).encode() if obj is not None else None;hdr={**H}
 if obj is not None:hdr['Content-Type']='application/json;charset=UTF-8'
 r=urllib.request.Request(url,data=data,headers=hdr,method=method)
 with urllib.request.urlopen(r,timeout=60) as x:return json.loads(x.read().decode('utf-8','replace'))
# Try root endpoint variants.
variants=[f'{BASE}/file/getRootFileDataList?metadataId={UUID}',f'{BASE}/file/file/getRootFileDataList?metadataId={UUID}']
root=None;used=None;tests=[]
for u in variants:
 try:
  j=req_json(u);tests.append({'url':u,'ok':True,'head':str(j)[:1000]})
  if str(j.get('code'))=='200':root=j;used=u;break
 except Exception as e:tests.append({'url':u,'error':repr(e)})
(OUT/'root_endpoint_tests.json').write_text(json.dumps(tests,indent=2,ensure_ascii=False),encoding='utf-8')
if root is None:raise RuntimeError('No root file endpoint worked')
# Walk directory names 1km -> GTiff -> BD using parent IDs.
def entries(j):return j.get('data') or j.get('context') or []
def child(parent_id):
 for u in [f'{BASE}/file/getFileDataList?parentId={parent_id}',f'{BASE}/file/file/getFileDataList?parentId={parent_id}']:
  try:
   j=req_json(u)
   if str(j.get('code'))=='200':return j,u
  except:pass
 raise RuntimeError(f'No child endpoint for {parent_id}')
cur=entries(root);trace=[{'level':'root','entries':cur}]
for wanted in ['1km','GTiff','BD']:
 matches=[x for x in cur if str(x.get('name'))==wanted and str(x.get('type')).lower()!='file']
 if not matches:raise RuntimeError(f'Could not find folder {wanted}; entries={[x.get("name") for x in cur]}')
 j,u=child(matches[0].get('id'));cur=entries(j);trace.append({'level':wanted,'endpoint':u,'entries':cur})
files=[x for x in cur if x.get('name')=='BD_0-5cm_1km_mean.zip']
if len(files)!=1:raise RuntimeError(f'Target not found; {[x.get("name") for x in cur]}')
fid=files[0].get('id');(OUT/'file_tree_trace_redacted.json').write_text(json.dumps(trace,indent=2,ensure_ascii=False),encoding='utf-8')
# Test HTTP individual binary endpoint with and without noToken body, only first 1MiB if server honours Range.
results=[]
for suffix in [f'/file/batchDownloadByFileId?fileId={fid}',f'/file/file/batchDownloadByFileId?fileId={fid}']:
 for body in [None,{'noToken':True}]:
  url=BASE+suffix;data=json.dumps(body).encode() if body else b'';headers={**H,'Range':'bytes=0-1048575'}
  if body:headers['Content-Type']='application/json;charset=UTF-8'
  try:
   q=urllib.request.Request(url,data=data,headers=headers,method='POST')
   with urllib.request.urlopen(q,timeout=120) as r:
    b=r.read(2_000_000);results.append({'url':url,'body':body,'status':r.status,'final_url':r.geturl(),'content_type':r.headers.get('content-type'),'content_length':r.headers.get('content-length'),'content_disposition':r.headers.get('content-disposition'),'bytes_read':len(b),'magic':b[:16].hex()})
  except Exception as e:results.append({'url':url,'body':body,'error':repr(e)})
(OUT/'http_individual_download_tests.json').write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps({'root':used,'file_id_present':bool(fid),'tests':results},indent=2,ensure_ascii=False))
