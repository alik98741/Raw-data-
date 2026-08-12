from __future__ import annotations
import json,urllib.request,ftplib,re,csv
from pathlib import Path
UUID='46ddd893-3b2b-4bb3-b9e6-b043f3c5c3a2';BASE='https://data.tpdc.ac.cn'
OUT=Path('rice-eja-acquisition/tpdc-csdl-quantile-check-v10');OUT.mkdir(parents=True,exist_ok=True)
H={'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*','Content-Type':'application/json;charset=UTF-8','Referer':f'{BASE}/en/data/{UUID}'}
def post(p,o):
 req=urllib.request.Request(BASE+p,data=json.dumps(o).encode(),headers=H,method='POST')
 with urllib.request.urlopen(req,timeout=90) as r:return json.loads(r.read().decode())
d=post(f'/file/ftp/createNoLoginDownloadFtpUser?metadataId={UUID}',{'noToken':True}).get('data')
hosts=[h.strip() for h in re.split(r'[,;\s]+',d['ftpUrl']) if '.' in h];port=int(d['ftpPort'])
ftp=None
for h in hosts:
 try:
  x=ftplib.FTP();x.connect(h,port,timeout=60);x.login(d['username'],d['password']);x.set_pasv(True);ftp=x;break
 except: pass
if not ftp:raise RuntimeError('FTP login failed')
paths=[]
for res in ['1km','10km']:
 for fmt in ['GTiff','netCDF']:
  for prop in ['BD','clay','OC']:
   p=f'/{res}/{fmt}/{prop}'
   try:
    ftp.cwd(p);ls=[{'name':n,'type':facts.get('type'),'size':int(facts['size']) if facts.get('size') else None} for n,facts in ftp.mlsd() if n not in('.','..')]
    paths.append({'path':p,'files':ls})
   except Exception as e:paths.append({'path':p,'error':repr(e)})
ftp.quit()
(OUT/'CSDLv2_quantile_location_check.json').write_text(json.dumps(paths,indent=2,ensure_ascii=False),encoding='utf-8')
rows=[]
for z in paths:
 for f in z.get('files',[]):rows.append({'path':z['path'],**f})
with open(OUT/'CSDLv2_quantile_location_check.csv','w',newline='',encoding='utf-8') as f:
 w=csv.DictWriter(f,fieldnames=['path','name','type','size']);w.writeheader();w.writerows(rows)
for z in paths: print(z['path'],[f['name'] for f in z.get('files',[])])
