from __future__ import annotations
import json,urllib.request,ftplib,re
from pathlib import Path
UUID='46ddd893-3b2b-4bb3-b9e6-b043f3c5c3a2'; BASE='https://data.tpdc.ac.cn'
PROPS=['BD','CEC','OC','TN','clay','pH','porosity','sand','silt']
OUT=Path('rice-eja-acquisition/tpdc-csdl-selected-list-v10');OUT.mkdir(parents=True,exist_ok=True)
H={'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*','Content-Type':'application/json;charset=UTF-8','Referer':f'{BASE}/en/data/{UUID}'}
def post(path,obj):
 req=urllib.request.Request(BASE+path,data=json.dumps(obj).encode(),headers=H,method='POST')
 with urllib.request.urlopen(req,timeout=90) as r:return json.loads(r.read().decode())
j=post(f'/file/ftp/createNoLoginDownloadFtpUser?metadataId={UUID}',{'noToken':True}); d=j.get('data') or j.get('context') or {}
hosts=[h.strip() for h in re.split(r'[,;\s]+',str(d.get('ftpUrl','')).replace('ftp://','')) if '.' in h]
port=int(d.get('ftpPort') or 21); user=d['username']; pw=d['password']
ftp=None; used=None
for h in hosts:
 try:
  f=ftplib.FTP();f.connect(h,port,timeout=60);f.login(user,pw);f.set_pasv(True);ftp=f;used=h;break
 except Exception: pass
if ftp is None: raise RuntimeError('No FTP host login succeeded')
listing={'host':used,'port':port,'properties':{}}
for p in PROPS:
 ftp.cwd('/1km/GTiff/'+p)
 try: ls=[{'name':n,'type':facts.get('type'),'size':int(facts['size']) if facts.get('size') else None} for n,facts in ftp.mlsd() if n not in ('.','..')]
 except Exception: ls=[{'name':n,'type':None,'size':None} for n in ftp.nlst()]
 listing['properties'][p]=ls
ftp.quit()
(OUT/'CSDLv2_1km_GTiff_selected_property_listing.json').write_text(json.dumps(listing,indent=2,ensure_ascii=False),encoding='utf-8')
rows=[]
for p,ls in listing['properties'].items():
 for x in ls: rows.append({'property':p,**x})
import csv
with open(OUT/'CSDLv2_1km_GTiff_selected_property_listing.csv','w',newline='',encoding='utf-8') as f:
 w=csv.DictWriter(f,fieldnames=['property','name','type','size']);w.writeheader();w.writerows(rows)
print('host',used,'files',len(rows))
for p,ls in listing['properties'].items(): print(p,len(ls),[x['name'] for x in ls[:30]])
