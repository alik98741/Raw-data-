from __future__ import annotations
import os,json,urllib.request,ftplib,re,hashlib,zipfile,time
from pathlib import Path
import numpy as np,pandas as pd,geopandas as gpd,rasterio
from rasterio.features import rasterize

UUID='46ddd893-3b2b-4bb3-b9e6-b043f3c5c3a2';BASE='https://data.tpdc.ac.cn'
PROP=os.environ.get('CSDL_PROPERTY','').strip(); ALLOWED=['BD','CEC','OC','TN','clay','pH','porosity','sand','silt']
if PROP not in ALLOWED: raise RuntimeError(f'Invalid CSDL_PROPERTY={PROP!r}')
DEPTHS=['0-5cm','5-15cm','15-30cm','30-60cm','60-100cm','100-200cm']
THICK={'0-5cm':5,'5-15cm':10,'15-30cm':15,'30-60cm':30,'60-100cm':40,'100-200cm':100}
EXPECTED=['Anhui','Beijing','Chongqing','Fujian','Gansu','Guangdong','Guangxi','Guizhou','Hainan','Hebei','Heilongjiang','Henan','Hubei','Hunan','Inner Mongolia','Jiangsu','Jiangxi','Jilin','Liaoning','Ningxia','Qinghai','Shaanxi','Shandong','Shanghai','Shanxi','Sichuan','Tianjin','Tibet','Xinjiang','Yunnan','Zhejiang']
CROSSWALK={'Hainan Province':'Hainan','Guangxi Zhuang Autonomous Region':'Guangxi','Fujian Province':'Fujian','Yunnan Province':'Yunnan','Guizhou Province':'Guizhou','Jiangxi Province':'Jiangxi','Hunan Province':'Hunan','Zhejiang Province':'Zhejiang','Shanghai Municipality':'Shanghai','Chongqing Municipality':'Chongqing','Hubei Province':'Hubei','Sichuan Province':'Sichuan','Anhui Province':'Anhui','Jiangsu Province':'Jiangsu','Henan Province':'Henan','Tibet Autonomous Region':'Tibet','Shandong Province':'Shandong','Qinghai Province':'Qinghai','Ningxia Ningxia Hui Autonomous Region':'Ningxia','Shaanxi Province':'Shaanxi','Tianjin Municipality':'Tianjin','Shanxi Province':'Shanxi','Beijing Municipality':'Beijing','Gansu Province':'Gansu','Hebei Province':'Hebei','Liaoning Province':'Liaoning','Jilin Province':'Jilin','Xinjiang Uyghur Autonomous Region':'Xinjiang','Inner Mongolia Autonomous Region':'Inner Mongolia','Heilongjiang Province':'Heilongjiang','Guangzhou Province':'Guangdong'}
ROOT=Path('rice-eja-acquisition');OUT=ROOT/f'csdl-tpdc-v10-{PROP}';WORK=ROOT/f'csdl-work-v10-{PROP}';OUT.mkdir(parents=True,exist_ok=True);WORK.mkdir(parents=True,exist_ok=True)
H={'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*','Content-Type':'application/json;charset=UTF-8','Referer':f'{BASE}/en/data/{UUID}'}
def post(p,o):
 req=urllib.request.Request(BASE+p,data=json.dumps(o).encode(),headers=H,method='POST')
 with urllib.request.urlopen(req,timeout=90) as r:return json.loads(r.read().decode())
def get_json(url):
 req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
 with urllib.request.urlopen(req,timeout=90) as r:return json.loads(r.read().decode())
def get_bytes(url):
 req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
 with urllib.request.urlopen(req,timeout=120) as r:return r.read()
def fresh_ftp(prefer=0):
 d=post(f'/file/ftp/createNoLoginDownloadFtpUser?metadataId={UUID}',{'noToken':True}).get('data');hosts=[h.strip() for h in re.split(r'[,;\s]+',d['ftpUrl']) if '.' in h];port=int(d['ftpPort']);hosts=hosts[prefer%len(hosts):]+hosts[:prefer%len(hosts)]
 last=None
 for h in hosts:
  try:
   f=ftplib.FTP();f.connect(h,port,timeout=90);f.login(d['username'],d['password']);f.set_pasv(True);return f,h,port
  except Exception as e:last=e
 raise RuntimeError(f'No FTP host succeeded: {last!r}')
def remote_inventory():
 f,h,p=fresh_ftp(ALLOWED.index(PROP));f.cwd('/1km/GTiff/'+PROP);ls={n:facts for n,facts in f.mlsd() if n not in('.','..') and facts.get('type')=='file'};f.quit();out=[]
 for d in DEPTHS:
  n=f'{PROP}_{d}_1km_mean.zip'
  if n not in ls:raise RuntimeError(f'Missing {n}')
  out.append({'property':PROP,'depth':d,'name':n,'remote':f'/1km/GTiff/{PROP}/{n}','server_size':int(ls[n].get('size') or 0)})
 return out
def download_resume(item,path,max_attempts=8):
 size=item['server_size'];attempts=[]
 for a in range(max_attempts):
  existing=path.stat().st_size if path.exists() else 0
  if size and existing==size:return attempts
  if size and existing>size:path.unlink();existing=0
  ftp=None
  try:
   ftp,host,port=fresh_ftp(ALLOWED.index(PROP)+a);mode='ab' if existing else 'wb';counter=[existing]
   with open(path,mode) as out:
    def cb(b):out.write(b);counter[0]+=len(b)
    try:ftp.retrbinary('RETR '+item['remote'],cb,blocksize=256*1024,rest=existing if existing else None)
    except Exception as e:
     # TPDC sometimes resets the control connection after the full data socket has completed.
     attempts.append({'attempt':a+1,'host':host,'start':existing,'end':counter[0],'exception':repr(e)})
    else:attempts.append({'attempt':a+1,'host':host,'start':existing,'end':counter[0],'exception':None})
  finally:
   if ftp:
    try:ftp.close()
    except:pass
  now=path.stat().st_size if path.exists() else 0
  if size and now==size:return attempts
  time.sleep(min(5*(a+1),30))
 raise RuntimeError(f'Could not complete {item["name"]}; have {path.stat().st_size if path.exists() else 0}, expected {size}; attempts={attempts}')

# exact boundary once per property
bm=get_json('https://www.geoboundaries.org/api/current/gbOpen/CHN/ADM1/');bp=WORK/'boundary.geojson';bp.write_bytes(get_bytes(bm['gjDownloadURL']));g=gpd.read_file(bp);namecol='shapeName' if 'shapeName' in g.columns else next(c for c in g.columns if 'name' in c.lower());g['province_raw']=g[namecol].astype(str);g['province']=g.province_raw.map(CROSSWALK);g=g[g.province.notna()].copy()
if len(g)!=31 or set(g.province)!=set(EXPECTED):raise RuntimeError('NBS31 boundary crosswalk failed')
g[['province_raw','province']].sort_values('province').to_csv(OUT/'ADM1_to_NBS31_crosswalk_used.csv',index=False)

inventory=remote_inventory();manifest=[];rows=[];labels=None;gg=None;grid_sig=None
for k,item in enumerate(inventory,1):
 print(f'{PROP} [{k}/6] {item["name"]}',flush=True);zp=WORK/item['name'];attempts=download_resume(item,zp);sha=hashlib.sha256(zp.read_bytes()).hexdigest()
 with zipfile.ZipFile(zp) as z:
  tifs=[x for x in z.namelist() if x.lower().endswith(('.tif','.tiff'))]
  if len(tifs)!=1:raise RuntimeError(f'{item["name"]}: {tifs}')
  z.extract(tifs[0],WORK);tp=WORK/tifs[0]
 with rasterio.open(tp) as src:
  sig=(src.width,src.height,str(src.crs),tuple(src.transform))
  if labels is None:
   gg=g.to_crs(src.crs).reset_index(drop=True);labels=rasterize([(geom,i+1) for i,geom in enumerate(gg.geometry)],out_shape=(src.height,src.width),transform=src.transform,fill=0,dtype='int16',all_touched=False);grid_sig=sig
  elif sig!=grid_sig:raise RuntimeError('CSDL grid mismatch')
  ma=src.read(1,masked=True);raw=np.asarray(ma.filled(np.nan),dtype='float64');scale=float(src.scales[0]) if src.scales else 1.;offset=float(src.offsets[0]) if src.offsets else 0.;data=raw*scale+offset;valid=np.isfinite(data);tags=src.tags();unit=tags.get('units') or tags.get('Units') or (src.units[0] if src.units else None);long_name=tags.get('long_name')
  srcmeta={'crs':str(src.crs),'width':src.width,'height':src.height,'nodata':src.nodata,'scale':scale,'offset':offset,'unit_tag':unit,'long_name':long_name,'tags_json':json.dumps(tags,ensure_ascii=False)}
  for i,r in gg.iterrows():
   vals=data[(labels==(i+1))&valid]
   if vals.size:
    q05,q50,q95=np.quantile(vals,[.05,.5,.95]);rows.append({'province':r.province,'property':PROP,'depth':item['depth'],'n_pixels':int(vals.size),'mean':float(vals.mean()),'spatial_q05':float(q05),'spatial_q50':float(q50),'spatial_q95':float(q95),'spatial_sd':float(vals.std(ddof=1)) if vals.size>1 else np.nan,'min':float(vals.min()),'max':float(vals.max()),'unit_tag':unit})
 manifest.append({**item,'download_bytes':zp.stat().st_size,'sha256':sha,'attempts_json':json.dumps(attempts),'internal_tif':tifs[0],**srcmeta});tp.unlink(missing_ok=True);zp.unlink(missing_ok=True)
long=pd.DataFrame(rows);long.to_csv(OUT/f'CSDLv2_1km_mean_{PROP}_ADM1_depth_long.csv',index=False);pd.DataFrame(manifest).to_csv(OUT/f'CSDLv2_1km_mean_{PROP}_DOWNLOAD_SHA256_MANIFEST.csv',index=False)
def weighted(maxcm,label):
 keep=[d for d in DEPTHS if int(re.findall(r'\d+',d)[1])<=maxcm];sub=long[long.depth.isin(keep)].copy();sub['thickness_cm']=sub.depth.map(THICK);out=[]
 for prov,z in sub.groupby('province'):
  w=z.thickness_cm.to_numpy(float);r={'province':prov,'property':PROP,'profile':label,'layers':'|'.join(keep),'total_thickness_cm':int(w.sum()),'unit_tag':'|'.join(sorted({str(x) for x in z.unit_tag.dropna()}))}
  for col in ['mean','spatial_q05','spatial_q50','spatial_q95','spatial_sd']:
   a=z[col].to_numpy(float);ok=np.isfinite(a);r[col]=float(np.average(a[ok],weights=w[ok])) if ok.any() else np.nan
  r['n_pixels_min']=int(z.n_pixels.min());out.append(r)
 return pd.DataFrame(out)
prof=pd.concat([weighted(30,'0-30cm'),weighted(60,'0-60cm'),weighted(100,'0-100cm')],ignore_index=True);prof.to_csv(OUT/f'CSDLv2_1km_mean_{PROP}_ADM1_depth_weighted_profiles.csv',index=False)
status={'property':PROP,'files':len(manifest),'expected':6,'source':'TPDC no-login FTP','dataset_uuid':UUID,'status':'PASS' if len(manifest)==6 and long.province.nunique()==31 else 'FAIL','notes':['Mean prediction rasters only.','spatial quantiles are within-province heterogeneity, not prediction uncertainty.','Province polygon aggregation, not rice-area weighting.']};(OUT/f'CSDLv2_{PROP}_STATUS.json').write_text(json.dumps(status,indent=2),encoding='utf-8');print(json.dumps(status,indent=2))
