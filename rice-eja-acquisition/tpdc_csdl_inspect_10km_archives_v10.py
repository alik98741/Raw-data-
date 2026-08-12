from __future__ import annotations
import json,urllib.request,ftplib,re,zipfile,hashlib
from pathlib import Path
UUID='46ddd893-3b2b-4bb3-b9e6-b043f3c5c3a2';BASE='https://data.tpdc.ac.cn';OUT=Path('rice-eja-acquisition/csdl-10km-inspect-v10');OUT.mkdir(parents=True,exist_ok=True)
H={'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*','Content-Type':'application/json;charset=UTF-8','Referer':f'{BASE}/en/data/{UUID}'}
def post(p,o):
 req=urllib.request.Request(BASE+p,data=json.dumps(o).encode(),headers=H,method='POST')
 with urllib.request.urlopen(req,timeout=90) as r:return json.loads(r.read().decode())
d=post(f'/file/ftp/createNoLoginDownloadFtpUser?metadataId={UUID}',{'noToken':True}).get('data');hosts=[h.strip() for h in re.split(r'[,;\s]+',d['ftpUrl']) if '.' in h]
ftp=None
for h in hosts:
 try:
  x=ftplib.FTP();x.connect(h,int(d['ftpPort']),timeout=60);x.login(d['username'],d['password']);x.set_pasv(True);ftp=x;break
 except:pass
if not ftp:raise RuntimeError('FTP failed')
files=['/10km/GTiff/BD/BD_0-5cm_10km.zip','/10km/GTiff/clay/clay_0-5cm_10km.zip','/10km/GTiff/OC/OC_0-5cm_10km_mean.zip']
res=[]
for remote in files:
 local=OUT/Path(remote).name;hsh=hashlib.sha256()
 with open(local,'wb') as f:
  ftp.retrbinary('RETR '+remote,lambda b:(hsh.update(b),f.write(b)),blocksize=1024*1024)
 with zipfile.ZipFile(local) as z:
  contents=[{'name':i.filename,'size':i.file_size,'compressed':i.compress_size} for i in z.infolist()]
 res.append({'remote':remote,'bytes':local.stat().st_size,'sha256':hsh.hexdigest(),'contents':contents})
 local.unlink()
ftp.quit()
(OUT/'CSDLv2_10km_archive_contents.json').write_text(json.dumps(res,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(res,indent=2,ensure_ascii=False))
