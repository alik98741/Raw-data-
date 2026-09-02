#!/usr/bin/env python3
from __future__ import annotations
import csv,hashlib,json,os,shutil,zipfile,requests
from pathlib import Path
OUT=Path(os.environ.get('OUT_DIR','phase30f_gsde_targets'));OUT.mkdir(parents=True,exist_ok=True)
BASE='https://data.tpdc.ac.cn';MID='2e46eb77-3ca2-4b90-9a42-fd49f10630d4';FID='050eaff4-6059-4565-958f-959bbdff3a82'
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0 rice-awd-eja/1.0','Accept':'*/*'})
raw=OUT/'gsde_download.bin'; audit=[]

def stream_post(url,data):
    with S.post(url,json=data,stream=True,timeout=(30,1800)) as r:
        audit.append({'url':url,'status_code':r.status_code,'content_type':r.headers.get('content-type',''),'content_disposition':r.headers.get('content-disposition',''),'content_length':r.headers.get('content-length','')})
        r.raise_for_status()
        with open(raw,'wb') as f:
            for ch in r.iter_content(1024*1024):
                if ch:f.write(ch)
        return r.headers
errors=[]
for url,data in [
    (BASE+f'/file/file/batchDownloadByFileId?fileId={FID}',{'noToken':True}),
    (BASE+f'/file/file/batchDownloadFile?metadataId={MID}',{'noToken':True}),
]:
    try:
        stream_post(url,data)
        if raw.stat().st_size>10_000_000 and zipfile.is_zipfile(raw):break
        errors.append(f'{url}: downloaded {raw.stat().st_size} bytes, zip={zipfile.is_zipfile(raw)}')
    except Exception as e:errors.append(f'{url}: {e!r}')
else:
    raise RuntimeError('GSDE no-login download failed: '+repr(errors))
work=OUT/'work';work.mkdir(exist_ok=True)
level0=work/'level0';level0.mkdir(exist_ok=True)
with zipfile.ZipFile(raw) as z:z.extractall(level0)
found={}; queue=list(level0.rglob('*'));seen_zip=set()
while queue:
    p=queue.pop(0)
    if not p.is_file():continue
    lo=p.name.lower()
    for target in ['phh2o5min.nc','sand5min.nc']:
        if lo==target:
            dest=OUT/target
            shutil.copy2(p,dest);found[target]=dest
    if len(found)==2:break
    if p.suffix.lower()=='.zip' and p not in seen_zip:
        seen_zip.add(p);ex=work/('nested_'+str(len(seen_zip)));ex.mkdir(exist_ok=True)
        try:
            with zipfile.ZipFile(p) as z:z.extractall(ex)
            queue.extend(ex.rglob('*'))
        except Exception:pass
if len(found)<2:
    inv=[]
    for p in work.rglob('*'):
        if p.is_file():inv.append({'path':str(p.relative_to(work)),'size':p.stat().st_size})
    with open(OUT/'extracted_inventory.csv','w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=['path','size']);w.writeheader();w.writerows(inv)
    raise RuntimeError('Missing GSDE targets; found '+repr(found))
def sha256(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
manifest=[]
for name,p in sorted(found.items()):manifest.append({'file':p.name,'bytes':p.stat().st_size,'sha256':sha256(p)})
with open(OUT/'GSDE_target_manifest.csv','w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=['file','bytes','sha256']);w.writeheader();w.writerows(manifest)
with open(OUT/'download_audit.csv','w',newline='',encoding='utf-8') as f:
    fields=sorted({k for r in audit for k in r});w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(audit)
summary={'download_bytes':raw.stat().st_size,'download_is_zip':zipfile.is_zipfile(raw),'targets':manifest,'errors_before_success':errors}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(summary,indent=2,ensure_ascii=False))
shutil.rmtree(work,ignore_errors=True)
try:raw.unlink()
except Exception:pass
