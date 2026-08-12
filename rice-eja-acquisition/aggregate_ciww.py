from __future__ import annotations
import argparse, re, json, hashlib, urllib.request
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.features import rasterize

ap=argparse.ArgumentParser(); ap.add_argument('--kind',choices=['depth','volume'],required=True); ap.add_argument('--input-dir',required=True); args=ap.parse_args()
KIND=args.kind; IN=Path(args.input_dir); OUT=Path('rice-eja-acquisition/ciww-results'); OUT.mkdir(parents=True,exist_ok=True)
UA={'User-Agent':'China-Rice-EJA-acquisition/1.0'}

def get_json(url):
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=120) as r:return json.load(r)

def download(url,dest):
    req=urllib.request.Request(url,headers=UA)
    h=hashlib.sha256();n=0
    with urllib.request.urlopen(req,timeout=180) as r,open(dest,'wb') as f:
        while True:
            b=r.read(4*1024*1024)
            if not b:break
            f.write(b);h.update(b);n+=len(b)
    return n,h.hexdigest()

# canonical boundary used by study
bmeta=get_json('https://www.geoboundaries.org/api/current/gbOpen/CHN/ADM1/')
bfp=OUT/'geoBoundaries-CHN-ADM1.geojson'
if not bfp.exists(): download(bmeta['gjDownloadURL'],bfp)
gdf=gpd.read_file(bfp)
name_col='shapeName'
# explicit crosswalk to NBS 31 names; Taiwan/HK/Macau excluded
aliases={
'Hainan Province':'Hainan','Taiwan Province':None,'Guangxi Zhuang Autonomous Region':'Guangxi','Fujian Province':'Fujian','Yunnan Province':'Yunnan','Guizhou Province':'Guizhou','Jiangxi Province':'Jiangxi','Hunan Province':'Hunan','Zhejiang Province':'Zhejiang','Shanghai Municipality':'Shanghai','Chongqing Municipality':'Chongqing','Hubei Province':'Hubei','Sichuan Province':'Sichuan','Anhui Province':'Anhui','Jiangsu Province':'Jiangsu','Henan Province':'Henan','Tibet Autonomous Region':'Tibet','Shandong Province':'Shandong','Qinghai Province':'Qinghai','Ningxia Ningxia Hui Autonomous Region':'Ningxia','Shaanxi Province':'Shaanxi','Tianjin Municipality':'Tianjin','Shanxi Province':'Shanxi','Beijing Municipality':'Beijing','Gansu Province':'Gansu','Hebei Province':'Hebei','Liaoning Province':'Liaoning','Jilin Province':'Jilin','Xinjiang Uyghur Autonomous Region':'Xinjiang','Inner Mongolia Autonomous Region':'Inner Mongolia','Heilongjiang Province':'Heilongjiang','Macau Special Administrative Region':None,'Hong Kong Special Administrative Region':None,'Guangzhou Province':'Guangdong'}
gdf['province']=gdf[name_col].map(aliases)
if gdf['province'].notna().sum()!=31: raise RuntimeError('Expected 31 mainland ADM1 after crosswalk')
gdf=gdf[gdf.province.notna()].copy()

# accept TIF/TIFF beneath extracted directory, only study years
fps=[p for p in IN.rglob('*') if p.is_file() and p.suffix.lower() in ('.tif','.tiff') and re.search(r'20(?:1[5-9]|20)',p.name)]
if not fps: raise RuntimeError(f'No 2015-2020 TIFFs found in {IN}')
rows=[]; file_manifest=[]
for idx,fp in enumerate(sorted(fps),1):
    nm=fp.name
    ym=re.search(r'(20(?:1[5-9]|20))(?:[_-](0[1-9]|1[0-2]))?',nm)
    if not ym: continue
    year=int(ym.group(1)); month=int(ym.group(2)) if ym.group(2) else 0
    with rasterio.open(fp) as src:
        gg=gdf.to_crs(src.crs)
        shapes=[(geom,i+1) for i,geom in enumerate(gg.geometry)]
        labels=rasterize(shapes,out_shape=(src.height,src.width),transform=src.transform,fill=0,dtype='int16')
        arr=src.read(1,masked=True).astype('float64')
        valid=~np.ma.getmaskarray(arr); vals=np.asarray(arr.filled(np.nan))
        valid &= np.isfinite(vals)
        if src.nodata is not None: valid &= vals!=src.nodata
        for i,prov in enumerate(gg.province,1):
            m=valid & (labels==i)
            v=vals[m]
            if v.size:
                mean=float(v.mean()); med=float(np.median(v)); q05=float(np.quantile(v,.05)); q95=float(np.quantile(v,.95)); total=float(v.sum()); n=int(v.size)
            else: mean=med=q05=q95=total=np.nan;n=0
            rows.append({'province':prov,'year':year,'month':month,'ciww_kind':KIND,'source_file':nm,'mean':mean,'median':med,'q05':q05,'q95':q95,'sum':total,'valid_pixels':n})
        h=hashlib.sha256()
        with open(fp,'rb') as f:
            for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
        file_manifest.append({'file':str(fp),'bytes':fp.stat().st_size,'sha256':h.hexdigest(),'year':year,'month':month,'kind':KIND,'crs':str(src.crs),'width':src.width,'height':src.height,'nodata':src.nodata})
    print(f'[{idx}/{len(fps)}] {nm}')

pd.DataFrame(rows).to_csv(OUT/f'CIWW1km_{KIND}_ADM1_2015_2020.csv',index=False)
pd.DataFrame(file_manifest).to_csv(OUT/f'CIWW1km_{KIND}_FILE_MANIFEST.csv',index=False)
print('Aggregated',KIND,'files:',len(file_manifest))
