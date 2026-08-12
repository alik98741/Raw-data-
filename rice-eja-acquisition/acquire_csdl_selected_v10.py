from __future__ import annotations
import io, json, os, re, hashlib, urllib.request, urllib.parse, zipfile, shutil
from pathlib import Path
import numpy as np, pandas as pd, geopandas as gpd, rasterio
from rasterio.features import rasterize

DS='cbd2c393a5ad4056a1bd9130ca1340f6'; VER='V2'
PROPS=['clay','sand','silt','BD','OC','CEC','pH','TN','porosity']
DEPTHS=['0-5cm','5-15cm','15-30cm','30-60cm','60-100cm','100-200cm']
THICK={'0-5cm':5,'5-15cm':10,'15-30cm':15,'30-60cm':30,'60-100cm':40,'100-200cm':100}
OUT=Path('rice-eja-acquisition/csdl-selected-v10'); WORK=Path('rice-eja-acquisition/csdl-work-v10')
OUT.mkdir(parents=True,exist_ok=True); WORK.mkdir(parents=True,exist_ok=True)
UA={'User-Agent':'China-Rice-EJA-CSDL/10.0','Referer':'https://www.scidb.cn/en/s/ZZJzAz'}

def get_bytes(url, timeout=240):
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=timeout) as r:return r.read(),r.geturl(),dict(r.headers)

def get_text(url): return get_bytes(url,90)[0].decode('utf-8','replace')

# Official ScienceDB URL export
q=urllib.parse.urlencode({'dataSetId':DS,'version':VER,'global':'Shanghai'})
alltxt=get_text('https://www.scidb.cn/api/sdb-filetree-service/getAllUrl?'+q)
(OUT/'CSDLv2_ALL_URLS_OFFICIAL.txt').write_text(alltxt,encoding='utf-8')
lines=[x.strip() for x in alltxt.splitlines() if x.strip()]
selected=[]
for u in lines:
    dec=urllib.parse.unquote(u)
    m=re.search(r'/V2/1km/GTiff/([^/]+)/([^/?&]+\.zip)',dec)
    if not m: continue
    prop,fn=m.group(1),m.group(2)
    if prop not in PROPS: continue
    if not any(d in fn for d in DEPTHS): continue
    if '_1km_mean.zip' not in fn: continue
    selected.append((prop,fn,u))
# de-dup exact file names
seen=set(); selected=[x for x in selected if not (x[1] in seen or seen.add(x[1]))]
if len(selected)!=len(PROPS)*len(DEPTHS):
    missing=[]
    names={x[1] for x in selected}
    for p in PROPS:
      for d in DEPTHS:
        exp=f'{p}_{d}_1km_mean.zip'
        if exp not in names: missing.append(exp)
    raise RuntimeError(f'Expected 54 selected CSDL files, got {len(selected)}; missing={missing}')

# Boundary
meta=json.loads(get_text('https://www.geoboundaries.org/api/current/gbOpen/CHN/ADM1/'))
boundary_url=meta['gjDownloadURL']
braw,_,_=get_bytes(boundary_url,120)
bpath=WORK/'chn_adm1.geojson'; bpath.write_bytes(braw)
gdf=gpd.read_file(bpath)
namecol='shapeName' if 'shapeName' in gdf.columns else next(c for c in gdf.columns if 'name' in c.lower())
# explicit source -> NBS31 cleanup
rename={'Guangzhou Province':'Guangdong','Inner Mongol':'Inner Mongolia','Nei Mongol':'Inner Mongolia','Xinjiang Uygur':'Xinjiang','Tibet Autonomous Region':'Tibet'}
exclude={'Hong Kong','Macao','Macau','Taiwan'}
gdf['province_raw']=gdf[namecol].astype(str)
gdf['province']=gdf['province_raw'].replace(rename)
gdf=gdf[~gdf['province'].isin(exclude)].copy()
# do not silently force 31 yet: record names and continue
(OUT/'boundary_names_used.csv').write_text(gdf[['province_raw','province']].to_csv(index=False),encoding='utf-8')

manifest=[]; rows=[]; labels=None; shapes=None; transform0=None; crs0=None
for j,(prop,fn,url) in enumerate(selected,1):
    print(f'[{j}/{len(selected)}] {fn}',flush=True)
    raw,final_url,hdr=get_bytes(url,600)
    sha=hashlib.sha256(raw).hexdigest()
    zpath=WORK/fn; zpath.write_bytes(raw)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        tifnames=[n for n in z.namelist() if n.lower().endswith(('.tif','.tiff'))]
        if len(tifnames)!=1: raise RuntimeError(f'{fn}: expected one TIFF, found {tifnames}')
        tifname=tifnames[0]; z.extract(tifname,WORK)
    tpath=WORK/tifname
    with rasterio.open(tpath) as src:
        arr=src.read(1,masked=True)
        if labels is None:
            gg=gdf.to_crs(src.crs)
            shapes=[(geom,i+1) for i,geom in enumerate(gg.geometry)]
            labels=rasterize(shapes,out_shape=(src.height,src.width),transform=src.transform,fill=0,dtype='int16',all_touched=False)
            transform0=src.transform; crs0=str(src.crs)
        else:
            if src.transform!=transform0 or str(src.crs)!=crs0 or arr.shape!=labels.shape:
                raise RuntimeError(f'Grid mismatch in {fn}')
        data=np.asarray(arr.filled(np.nan),dtype='float64')
        valid=np.isfinite(data)
        for i,rec in gg.reset_index(drop=True).iterrows():
            vals=data[(labels==(i+1)) & valid]
            if vals.size:
                q05,q50,q95=np.quantile(vals,[.05,.5,.95])
                rows.append({'province':rec['province'],'province_raw':rec['province_raw'],'property':prop,'depth':next(d for d in DEPTHS if d in fn),'n_pixels':int(vals.size),'mean':float(np.mean(vals)),'spatial_q05':float(q05),'spatial_q50':float(q50),'spatial_q95':float(q95),'spatial_sd':float(np.std(vals,ddof=1)) if vals.size>1 else np.nan})
    manifest.append({'property':prop,'file':fn,'bytes':len(raw),'sha256':sha,'source_url':url,'resolved_url':final_url,'internal_tif':tifname})
    try:tpath.unlink()
    except:pass
    try:zpath.unlink()
    except:pass

long=pd.DataFrame(rows)
long.to_csv(OUT/'CSDLv2_1km_ADM1_depth_long.csv',index=False)
pd.DataFrame(manifest).to_csv(OUT/'CSDLv2_SELECTED_DOWNLOAD_MANIFEST.csv',index=False)

# Depth-weighted summaries. Weight layer-level statistics by layer thickness.
def depth_summary(maxcm,label):
    keep=[]; cum=0
    for d in DEPTHS:
        top,bottom=map(int,re.findall(r'\d+',d)[:2])
        if bottom<=maxcm: keep.append(d)
    sub=long[long.depth.isin(keep)].copy(); sub['thickness_cm']=sub.depth.map(THICK)
    outs=[]
    for (prov,prop),z in sub.groupby(['province','property']):
        w=z.thickness_cm.to_numpy(float)
        r={'province':prov,'property':prop,'depth_weighting':label,'layers':'|'.join(keep),'total_thickness_cm':float(w.sum())}
        for col in ['mean','spatial_q05','spatial_q50','spatial_q95','spatial_sd']:
            a=z[col].to_numpy(float); ok=np.isfinite(a)
            r[col]=float(np.average(a[ok],weights=w[ok])) if ok.any() else np.nan
        r['n_pixels_min']=int(z.n_pixels.min())
        outs.append(r)
    return pd.DataFrame(outs)

summ=pd.concat([depth_summary(30,'0-30cm_thickness_weighted'),depth_summary(60,'0-60cm_thickness_weighted')],ignore_index=True)
summ.to_csv(OUT/'CSDLv2_1km_ADM1_depth_weighted_0_30_0_60.csv',index=False)
# wide model-ready means, preserving q05/q95 as spatial quantiles
wide=summ.pivot_table(index=['province','depth_weighting'],columns='property',values=['mean','spatial_q05','spatial_q95']).reset_index()
wide.columns=['_'.join([str(x) for x in c if str(x)!='']).strip('_') if isinstance(c,tuple) else c for c in wide.columns]
wide.to_csv(OUT/'CSDLv2_1km_ADM1_model_ready_wide.csv',index=False)

status={'dataset_id':DS,'version':VER,'source_branch':'1km/GTiff/*/*_1km_mean.zip','selected_files':len(selected),'properties':PROPS,'depths':DEPTHS,'boundary_features_used':int(len(gdf)),'important_note':'spatial_q05/q50/q95 are within-province spatial pixel quantiles of CSDLv2 mean rasters; they are NOT CSDL model prediction uncertainty quantiles. The public 1-km URL export exposed mean products only.','outputs':[p.name for p in OUT.iterdir()]}
(OUT/'CSDLv2_ACQUISITION_STATUS.json').write_text(json.dumps(status,indent=2),encoding='utf-8')
print(json.dumps(status,indent=2))
