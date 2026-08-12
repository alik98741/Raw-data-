from __future__ import annotations
import json,urllib.request,ftplib,re,csv,hashlib,zipfile,shutil,os
from pathlib import Path
import numpy as np,pandas as pd,geopandas as gpd,rasterio
from rasterio.features import rasterize

UUID='46ddd893-3b2b-4bb3-b9e6-b043f3c5c3a2';BASE='https://data.tpdc.ac.cn'
PROPS=['BD','CEC','OC','TN','clay','pH','porosity','sand','silt']
DEPTHS=['0-5cm','5-15cm','15-30cm','30-60cm','60-100cm','100-200cm']
THICK={'0-5cm':5,'5-15cm':10,'15-30cm':15,'30-60cm':30,'60-100cm':40,'100-200cm':100}
EXPECTED=['Anhui','Beijing','Chongqing','Fujian','Gansu','Guangdong','Guangxi','Guizhou','Hainan','Hebei','Heilongjiang','Henan','Hubei','Hunan','Inner Mongolia','Jiangsu','Jiangxi','Jilin','Liaoning','Ningxia','Qinghai','Shaanxi','Shandong','Shanghai','Shanxi','Sichuan','Tianjin','Tibet','Xinjiang','Yunnan','Zhejiang']
OUT=Path('rice-eja-acquisition/csdl-tpdc-mean-v10');WORK=Path('rice-eja-acquisition/csdl-tpdc-work-v10')
OUT.mkdir(parents=True,exist_ok=True);WORK.mkdir(parents=True,exist_ok=True)
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

def ftp_connect():
 d=post(f'/file/ftp/createNoLoginDownloadFtpUser?metadataId={UUID}',{'noToken':True}).get('data')
 hosts=[h.strip() for h in re.split(r'[,;\s]+',d['ftpUrl']) if '.' in h]; port=int(d['ftpPort'])
 for h in hosts:
  try:
   f=ftplib.FTP();f.connect(h,port,timeout=90);f.login(d['username'],d['password']);f.set_pasv(True);return f,h,port
  except Exception:pass
 raise RuntimeError('TPDC no-login FTP connection failed')

ftp,host,port=ftp_connect()
# boundary
bm=get_json('https://www.geoboundaries.org/api/current/gbOpen/CHN/ADM1/')
braw=get_bytes(bm['gjDownloadURL']); bpath=WORK/'boundary.geojson';bpath.write_bytes(braw)
g=gpd.read_file(bpath); namecol='shapeName' if 'shapeName' in g.columns else next(c for c in g.columns if 'name' in c.lower())
rename={'Guangzhou Province':'Guangdong','Inner Mongol':'Inner Mongolia','Nei Mongol':'Inner Mongolia','Xinjiang Uygur':'Xinjiang','Tibet Autonomous Region':'Tibet','Guangxi Zhuang':'Guangxi','Ningxia Hui':'Ningxia'}
g['province_raw']=g[namecol].astype(str);g['province']=g.province_raw.replace(rename)
g=g[g.province.isin(EXPECTED)].copy()
if set(g.province)!=set(EXPECTED) or len(g)!=31:
 raise RuntimeError(f'Boundary crosswalk not exactly NBS31: n={len(g)} missing={sorted(set(EXPECTED)-set(g.province))} extra={sorted(set(g.province)-set(EXPECTED))}')
g[['province_raw','province']].to_csv(OUT/'ADM1_to_NBS31_crosswalk_used.csv',index=False)

# inventory exact mean files
inventory=[]
for p in PROPS:
 ftp.cwd('/1km/GTiff/'+p)
 ls=[(n,facts) for n,facts in ftp.mlsd() if n not in('.','..') and facts.get('type')=='file']
 for d in DEPTHS:
  target=f'{p}_{d}_1km_mean.zip'; matches=[(n,f) for n,f in ls if n==target]
  if len(matches)!=1:raise RuntimeError(f'Missing/duplicate {target} in TPDC')
  inventory.append({'property':p,'depth':d,'name':target,'ftp_path':f'/1km/GTiff/{p}/{target}','server_size':int(matches[0][1].get('size') or 0)})
if len(inventory)!=54:raise RuntimeError(f'Expected 54 files, got {len(inventory)}')

manifest=[];rows=[]; labels=None; gg=None; grid_sig=None
for k,item in enumerate(inventory,1):
 p,d,fn=item['property'],item['depth'],item['name']; print(f'[{k}/54] {fn}',flush=True)
 zpath=WORK/fn
 h=hashlib.sha256();n=0
 ftp.voidcmd('TYPE I')
 with open(zpath,'wb') as f:
  def cb(b):
   nonlocal_holder[0]+=len(b); h.update(b); f.write(b)
  nonlocal_holder=[0]
  ftp.retrbinary('RETR '+item['ftp_path'],cb,blocksize=1024*1024)
  n=nonlocal_holder[0]
 if item['server_size'] and n!=item['server_size']:raise RuntimeError(f'Size mismatch {fn}: {n} != {item["server_size"]}')
 with zipfile.ZipFile(zpath) as z:
  tifs=[x for x in z.namelist() if x.lower().endswith(('.tif','.tiff'))]
  if len(tifs)!=1:raise RuntimeError(f'{fn} expected 1 TIFF, got {tifs}')
  z.extract(tifs[0],WORK); tpath=WORK/tifs[0]
 with rasterio.open(tpath) as src:
  sig=(src.width,src.height,str(src.crs),tuple(src.transform))
  if labels is None:
   gg=g.to_crs(src.crs).reset_index(drop=True)
   labels=rasterize([(geom,i+1) for i,geom in enumerate(gg.geometry)],out_shape=(src.height,src.width),transform=src.transform,fill=0,dtype='int16',all_touched=False)
   grid_sig=sig
  elif sig!=grid_sig:raise RuntimeError(f'CSDL grid mismatch: {fn}')
  ma=src.read(1,masked=True); raw=np.asarray(ma.filled(np.nan),dtype='float64')
  scale=float(src.scales[0]) if src.scales else 1.0;offset=float(src.offsets[0]) if src.offsets else 0.0
  data=raw*scale+offset
  valid=np.isfinite(data)
  tags=src.tags();bandtags=src.tags(1);units=src.units[0] if src.units else None;desc=src.descriptions[0] if src.descriptions else None
  for i,rec in gg.iterrows():
   vals=data[(labels==(i+1))&valid]
   if vals.size:
    q05,q50,q95=np.quantile(vals,[.05,.5,.95])
    rows.append({'province':rec.province,'property':p,'depth':d,'n_pixels':int(vals.size),'mean':float(vals.mean()),'spatial_q05':float(q05),'spatial_q50':float(q50),'spatial_q95':float(q95),'spatial_sd':float(vals.std(ddof=1)) if vals.size>1 else np.nan,'min':float(vals.min()),'max':float(vals.max()),'unit':units,'scale':scale,'offset':offset})
 manifest.append({**item,'download_bytes':n,'sha256':h.hexdigest(),'internal_tif':tifs[0],'crs':str(src.crs),'width':src.width,'height':src.height,'nodata':src.nodata,'scale':scale,'offset':offset,'unit':units,'description':desc,'tags_json':json.dumps(tags,ensure_ascii=False),'band_tags_json':json.dumps(bandtags,ensure_ascii=False)})
 tpath.unlink(missing_ok=True); zpath.unlink(missing_ok=True)

try:ftp.quit()
except:pass
long=pd.DataFrame(rows);long.to_csv(OUT/'CSDLv2_1km_mean_ADM1_depth_long.csv',index=False)
pd.DataFrame(manifest).to_csv(OUT/'CSDLv2_1km_mean_DOWNLOAD_SHA256_MANIFEST.csv',index=False)

def weighted(maxcm,label):
 keep=[]
 for d in DEPTHS:
  top,bottom=map(int,re.findall(r'\d+',d)[:2])
  if bottom<=maxcm:keep.append(d)
 sub=long[long.depth.isin(keep)].copy();sub['thickness_cm']=sub.depth.map(THICK)
 out=[]
 for (prov,prop),z in sub.groupby(['province','property']):
  w=z.thickness_cm.to_numpy(float);r={'province':prov,'property':prop,'profile':label,'layers':'|'.join(keep),'total_thickness_cm':int(w.sum()),'unit':'|'.join(sorted({str(x) for x in z.unit.dropna()}))}
  for col in ['mean','spatial_q05','spatial_q50','spatial_q95','spatial_sd']:
   a=z[col].to_numpy(float);ok=np.isfinite(a);r[col]=float(np.average(a[ok],weights=w[ok])) if ok.any() else np.nan
  r['n_pixels_min']=int(z.n_pixels.min());out.append(r)
 return pd.DataFrame(out)
prof=pd.concat([weighted(30,'0-30cm'),weighted(60,'0-60cm'),weighted(100,'0-100cm')],ignore_index=True)
prof.to_csv(OUT/'CSDLv2_1km_mean_ADM1_depth_weighted_profiles.csv',index=False)
wide=prof.pivot_table(index=['province','profile'],columns='property',values='mean').reset_index();wide.columns=[str(c) for c in wide.columns]
wide.to_csv(OUT/'CSDLv2_1km_mean_ADM1_model_ready_means.csv',index=False)
status={'source':'TPDC official no-login FTP','dataset_uuid':UUID,'share_policy':'A','ftp_server_used':host,'ftp_port':port,'files_downloaded':len(manifest),'expected_files':54,'properties':PROPS,'depths':DEPTHS,'profiles':['0-30cm','0-60cm','0-100cm'],'boundary':'geoBoundaries CHN ADM1 explicit NBS31 crosswalk','important_notes':['These are CSDLv2 1-km MEAN prediction rasters.','spatial_q05/q50/q95 are within-province spatial pixel distributions, NOT CSDL model prediction quantile layers.','Rice-area-specific weighting is not claimed here; these are province polygon summaries pending a complete validated rice-support mask.'],'outputs':[p.name for p in OUT.iterdir()]}
(OUT/'CSDLv2_TPDC_MEAN_ACQUISITION_STATUS.json').write_text(json.dumps(status,indent=2),encoding='utf-8')
print(json.dumps(status,indent=2))
