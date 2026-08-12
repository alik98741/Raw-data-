from __future__ import annotations
import json,urllib.request,ftplib,re,zipfile,tempfile,os
from pathlib import Path
import rasterio
UUID='46ddd893-3b2b-4bb3-b9e6-b043f3c5c3a2';BASE='https://data.tpdc.ac.cn';OUT=Path('rice-eja-acquisition/csdl-10km-band-inspect-v10');OUT.mkdir(parents=True,exist_ok=True)
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
with tempfile.TemporaryDirectory() as td:
 for remote in files:
  zp=Path(td)/Path(remote).name
  with open(zp,'wb') as f:ftp.retrbinary('RETR '+remote,f.write,blocksize=1024*1024)
  with zipfile.ZipFile(zp) as z:
   tif=[n for n in z.namelist() if n.lower().endswith('.tif')][0];z.extract(tif,td);tp=Path(td)/tif
  with rasterio.open(tp) as src:
   res.append({'remote':remote,'tif':tif,'count':src.count,'dtypes':src.dtypes,'descriptions':src.descriptions,'units':src.units,'scales':src.scales,'offsets':src.offsets,'tags':src.tags(),'band_tags':[src.tags(i) for i in range(1,src.count+1)],'shape':[src.height,src.width],'crs':str(src.crs)})
  tp.unlink(missing_ok=True)
ftp.quit();(OUT/'CSDLv2_10km_raster_band_metadata.json').write_text(json.dumps(res,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(res,indent=2,ensure_ascii=False))
