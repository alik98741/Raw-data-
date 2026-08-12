from __future__ import annotations
import json, re, hashlib, urllib.request, zipfile, os, math
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.mask import mask

BASE=Path('rice-eja-acquisition/work')
RAW=BASE/'raw'; OUT=Path('rice-eja-acquisition/results')
RAW.mkdir(parents=True,exist_ok=True); OUT.mkdir(parents=True,exist_ok=True)
UA={'User-Agent':'China-Rice-EJA-acquisition/1.0'}

def get_json(url):
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=120) as r: return json.load(r)

def dl(url,dest):
    req=urllib.request.Request(url,headers=UA)
    h=hashlib.sha256(); n=0
    with urllib.request.urlopen(req,timeout=240) as r, open(dest,'wb') as f:
        while True:
            b=r.read(4*1024*1024)
            if not b: break
            f.write(b); h.update(b); n+=len(b)
    return {'path':str(dest),'bytes':n,'sha256':h.hexdigest(),'url':url}

manifest=[]
# boundary
bm=get_json('https://www.geoboundaries.org/api/current/gbOpen/CHN/ADM1/')
burl=bm['gjDownloadURL']
bfp=RAW/'geoBoundaries-CHN-ADM1.geojson'
manifest.append(dl(burl,bfp))
(OUT/'geoboundaries_metadata.json').write_text(json.dumps(bm,indent=2),encoding='utf-8')
gdf=gpd.read_file(bfp)
(OUT/'boundary_columns.json').write_text(json.dumps(list(gdf.columns),indent=2),encoding='utf-8')
name_col=next((c for c in ['shapeName','shapeNameEn','NAME_1','name','Name'] if c in gdf.columns),None)
if not name_col: raise RuntimeError('No province name column found: '+str(list(gdf.columns)))
gdf[[name_col]].to_csv(OUT/'boundary_adm1_names.csv',index=False)

# CIrrMap250
meta=get_json('https://api.figshare.com/v2/articles/24814293/versions/2')
files=meta.get('files',[]); years=range(2015,2021)
rows=[]
for y in years:
    cand=[]
    for f in files:
        n=f.get('name','')
        if n==f'CIrrMap250_{y}.tif': cand.append(f)
    if len(cand)!=1: raise RuntimeError(f'Expected one CIrrMap250 file for {y}, got {len(cand)}')
    f=cand[0]; fp=RAW/f['name']
    rec=dl(f['download_url'],fp); rec.update({'dataset':'CIrrMap250','year':y,'figshare_id':f.get('id'),'md5':f.get('computed_md5')}); manifest.append(rec)
    with rasterio.open(fp) as src:
        gg=gdf.to_crs(src.crs)
        for _,r in gg.iterrows():
            geom=[r.geometry.__geo_interface__]
            try:
                arr,_=mask(src,geom,crop=True,filled=False)
                a=arr[0]
                vals=a.compressed().astype('float64') if np.ma.isMaskedArray(a) else a.ravel().astype('float64')
                nod=src.nodata
                if nod is not None: vals=vals[vals!=nod]
                vals=vals[np.isfinite(vals)]
                # documented percentage irrigated area; valid range 0..100
                vals=vals[(vals>=0)&(vals<=100)]
                mean=float(np.mean(vals)) if vals.size else np.nan
                med=float(np.median(vals)) if vals.size else np.nan
                q05=float(np.quantile(vals,0.05)) if vals.size else np.nan
                q95=float(np.quantile(vals,0.95)) if vals.size else np.nan
                irrig_equiv=float(np.sum(vals/100.0)) if vals.size else np.nan
                npx=int(vals.size)
            except ValueError:
                mean=med=q05=q95=irrig_equiv=np.nan; npx=0
            rows.append({'province_raw':r[name_col],'year':y,'cirr_mean_pct':mean,'cirr_median_pct':med,'cirr_q05_pct':q05,'cirr_q95_pct':q95,'cirr_valid_pixels':npx,'cirr_irrigated_equiv_pixels':irrig_equiv})
    fp.unlink()  # conserve runner disk after aggregation

pd.DataFrame(rows).to_csv(OUT/'CIrrMap250_ADM1_2015_2020.csv',index=False)

# AquaCrop latest release + Linux binary/source
am=get_json('https://api.github.com/repos/KUL-RSDA/AquaCrop/releases/latest')
(OUT/'AquaCrop_latest_release.json').write_text(json.dumps(am,indent=2),encoding='utf-8')
tag=am.get('tag_name')
if not tag or '7.3' not in tag: raise RuntimeError(f'Unexpected AquaCrop latest release: {tag}')
assets=am.get('assets',[])
for a in assets:
    if a.get('name')=='aquacrop-7.3-x86_64-linux.zip':
        afp=RAW/a['name']; rec=dl(a['browser_download_url'],afp); rec.update({'dataset':'AquaCrop','tag':tag}); manifest.append(rec)
        with zipfile.ZipFile(afp) as z:
            for zi in z.infolist():
                if not zi.is_dir():
                    data=z.read(zi)
                    p=OUT/'aquacrop_linux'/zi.filename
                    p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(data)
        break
else: raise RuntimeError('Linux AquaCrop 7.3 asset not found')

src=RAW/f'AquaCrop_source_{tag}.zip'
manifest.append({**dl(f'https://github.com/KUL-RSDA/AquaCrop/archive/refs/tags/{tag}.zip',src),'dataset':'AquaCrop_source','tag':tag})
# retain source archive in result (small enough) for exact reproducibility
os.replace(src,OUT/src.name)

pd.DataFrame(manifest).to_csv(OUT/'DOWNLOAD_SHA256_MANIFEST.csv',index=False)
print('Completed CIrrMap250 ADM1 aggregation and AquaCrop acquisition.')
