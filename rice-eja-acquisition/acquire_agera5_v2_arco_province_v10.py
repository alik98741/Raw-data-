from __future__ import annotations
import os,json,math,urllib.request
from pathlib import Path
import numpy as np,pandas as pd,xarray as xr,geopandas as gpd
from rasterio.features import rasterize
from affine import Affine

TOKEN=os.getenv('CDSAPI_KEY','').strip()
if not TOKEN: raise RuntimeError('CDSAPI_KEY repository secret is missing')
URL='https://arco.datastores.ecmwf.int/cadl-arco-time-001/arco/sis_agrometeorological_indicators/all/timeChunked.zarr'
OUT=Path('rice-eja-acquisition/agera5-v2-province-v10');OUT.mkdir(parents=True,exist_ok=True)
VARS=['2m_temperature_24_hour_maximum','2m_temperature_24_hour_minimum','precipitation_flux','vapour_pressure_deficit_at_maximum_temperature','reference_evapotranspiration','solar_radiation_flux']
EXPECTED=['Anhui','Beijing','Chongqing','Fujian','Gansu','Guangdong','Guangxi','Guizhou','Hainan','Hebei','Heilongjiang','Henan','Hubei','Hunan','Inner Mongolia','Jiangsu','Jiangxi','Jilin','Liaoning','Ningxia','Qinghai','Shaanxi','Shandong','Shanghai','Shanxi','Sichuan','Tianjin','Tibet','Xinjiang','Yunnan','Zhejiang']
CROSSWALK={'Hainan Province':'Hainan','Guangxi Zhuang Autonomous Region':'Guangxi','Fujian Province':'Fujian','Yunnan Province':'Yunnan','Guizhou Province':'Guizhou','Jiangxi Province':'Jiangxi','Hunan Province':'Hunan','Zhejiang Province':'Zhejiang','Shanghai Municipality':'Shanghai','Chongqing Municipality':'Chongqing','Hubei Province':'Hubei','Sichuan Province':'Sichuan','Anhui Province':'Anhui','Jiangsu Province':'Jiangsu','Henan Province':'Henan','Tibet Autonomous Region':'Tibet','Shandong Province':'Shandong','Qinghai Province':'Qinghai','Ningxia Ningxia Hui Autonomous Region':'Ningxia','Shaanxi Province':'Shaanxi','Tianjin Municipality':'Tianjin','Shanxi Province':'Shanxi','Beijing Municipality':'Beijing','Gansu Province':'Gansu','Hebei Province':'Hebei','Liaoning Province':'Liaoning','Jilin Province':'Jilin','Xinjiang Uyghur Autonomous Region':'Xinjiang','Inner Mongolia Autonomous Region':'Inner Mongolia','Heilongjiang Province':'Heilongjiang','Guangzhou Province':'Guangdong'}

def get_json(url):
 req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
 with urllib.request.urlopen(req,timeout=90) as r:return json.loads(r.read().decode())
def get_bytes(url):
 req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
 with urllib.request.urlopen(req,timeout=120) as r:return r.read()

storage={'headers':{'Authorization':f'Bearer {TOKEN}'}}
ds=xr.open_zarr(URL,consolidated=True,storage_options=storage,chunks='auto')
# Find standard coordinate names robustly.
def find_name(cands,names):
 for x in cands:
  if x in names:return x
 for n in names:
  lo=n.lower()
  if any(x in lo for x in cands):return n
 raise RuntimeError(f'Could not resolve coordinate among {cands}; names={list(names)}')
latn=find_name(['latitude','lat'],ds.coords);lonn=find_name(['longitude','lon'],ds.coords);timen=find_name(['valid_time','time','date'],ds.coords)
missing=[v for v in VARS if v not in ds.data_vars]
if missing: raise RuntimeError(f'Required AgERA5 v2 variables missing from ARCO store: {missing}; available={list(ds.data_vars)}')
# Subset China bounding box with buffer. Handle coordinate orientation.
lat=np.asarray(ds[latn].values);lon=np.asarray(ds[lonn].values)
lat_slice=slice(55,17) if lat[0]>lat[-1] else slice(17,55);lon_slice=slice(72,136) if lon[0]<lon[-1] else slice(136,72)
sub=ds[VARS].sel({latn:lat_slice,lonn:lon_slice,timen:slice('2015-01-01','2020-12-31')})
lat=np.asarray(sub[latn].values,dtype=float);lon=np.asarray(sub[lonn].values,dtype=float)
if lat.ndim!=1 or lon.ndim!=1: raise RuntimeError('Expected 1D regular AgERA5 lat/lon coordinates')
# Boundary.
bm=get_json('https://www.geoboundaries.org/api/current/gbOpen/CHN/ADM1/');bp=OUT/'boundary.geojson';bp.write_bytes(get_bytes(bm['gjDownloadURL']))
g=gpd.read_file(bp);namecol='shapeName' if 'shapeName' in g.columns else next(c for c in g.columns if 'name' in c.lower());g['province_raw']=g[namecol].astype(str);g['province']=g.province_raw.map(CROSSWALK);g=g[g.province.notna()].copy()
if len(g)!=31 or set(g.province)!=set(EXPECTED):raise RuntimeError('Boundary crosswalk failed exact NBS31 check')
g=g.to_crs('EPSG:4326').reset_index(drop=True);g[['province_raw','province']].to_csv(OUT/'ADM1_to_NBS31_crosswalk_used.csv',index=False)
# Rasterize polygons onto the regular grid using cell-centre coordinates.
dlon=float(np.median(np.diff(lon)));dlat=float(np.median(np.diff(lat)))
# rasterio transform maps row0 upper edge; normalize arrays to north->south, west->east for labels.
lon_order=np.argsort(lon);lat_order=np.argsort(lat)[::-1];lon_sorted=lon[lon_order];lat_sorted=lat[lat_order]
transform=Affine.translation(lon_sorted[0]-abs(dlon)/2,lat_sorted[0]+abs(dlat)/2)*Affine.scale(abs(dlon),-abs(dlat))
labels=rasterize([(geom,i+1) for i,geom in enumerate(g.geometry)],out_shape=(len(lat_sorted),len(lon_sorted)),transform=transform,fill=0,dtype='int16',all_touched=False)
# Cell area relative weights on regular lat-lon grid.
w2=np.repeat(np.cos(np.deg2rad(lat_sorted))[:,None],len(lon_sorted),axis=1)
province_index={i+1:g.loc[i,'province'] for i in range(len(g))}
# Metadata and coordinate audit, no token stored.
meta={'source':'AgERA5 v2.0 ARCO timeChunked Zarr','url':URL,'period':['2015-01-01','2020-12-31'],'variables':{},'coords':{'time':timen,'lat':latn,'lon':lonn,'lat_count':len(lat),'lon_count':len(lon),'lat_range':[float(lat.min()),float(lat.max())],'lon_range':[float(lon.min()),float(lon.max())]},'aggregation':'NBS31 province polygon, cosine(latitude) cell-area weighting; NOT rice-area weighting','credential':'Bearer CDS PAT used in-memory only and not persisted'}
for v in VARS:meta['variables'][v]={'attrs':{k:str(val) for k,val in sub[v].attrs.items()},'dtype':str(sub[v].dtype),'dims':list(sub[v].dims)}
(OUT/'AgERA5_v2_NATIVE_METADATA.json').write_text(json.dumps(meta,indent=2,ensure_ascii=False),encoding='utf-8')

allrows=[]
for year in range(2015,2021):
 print('YEAR',year,flush=True)
 y=sub.sel({timen:slice(f'{year}-01-01',f'{year}-12-31')})
 times=pd.to_datetime(y[timen].values)
 # load one variable at a time to cap memory.
 var_arrays={}
 for v in VARS:
  print('  variable',v,flush=True)
  a=y[v]
  # eliminate singleton non-spatiotemporal dims if any; fail if unresolved >1 dims.
  for d in list(a.dims):
   if d not in (timen,latn,lonn):
    if a.sizes[d]==1:a=a.isel({d:0},drop=True)
    else:raise RuntimeError(f'{v} has unsupported extra dimension {d} size {a.sizes[d]}')
  a=a.transpose(timen,latn,lonn).values
  # reorder spatial axes to match labels.
  a=a[:,lat_order,:][:,:,lon_order]
  var_arrays[v]=np.asarray(a,dtype='float64')
 for ti,dt in enumerate(times):
  for lab,prov in province_index.items():
   mask=(labels==lab);ww=w2[mask]
   row={'province':prov,'date':dt.strftime('%Y-%m-%d'),'year':int(dt.year),'doy':int(dt.dayofyear),'n_grid_cells':int(mask.sum()),'weighting':'coslat_area_NBS31_polygon'}
   for v in VARS:
    vals=var_arrays[v][ti][mask];ok=np.isfinite(vals)
    row[v]=float(np.average(vals[ok],weights=ww[ok])) if ok.any() else np.nan
    row[v+'_valid_cells']=int(ok.sum())
   allrows.append(row)
 pd.DataFrame(allrows).query('year == @year').to_csv(OUT/f'AgERA5_v2_NBS31_daily_{year}.csv',index=False)
 # remove this year's rows from memory after file write
 allrows=[]
# combine yearly tables compactly.
frames=[pd.read_csv(OUT/f'AgERA5_v2_NBS31_daily_{y}.csv') for y in range(2015,2021)];daily=pd.concat(frames,ignore_index=True);daily.to_csv(OUT/'AgERA5_v2_NBS31_daily_2015_2020.csv',index=False)
# completeness QC
expected_dates=sum(366 if pd.Timestamp(f'{y}-12-31').dayofyear==366 else 365 for y in range(2015,2021));qc={'rows':len(daily),'expected_rows':31*expected_dates,'unique_provinces':daily.province.nunique(),'unique_dates':daily.date.nunique(),'date_min':daily.date.min(),'date_max':daily.date.max(),'missing_by_variable':{v:int(daily[v].isna().sum()) for v in VARS},'status':'PASS' if len(daily)==31*expected_dates and daily.province.nunique()==31 else 'FAIL'}
(OUT/'AgERA5_v2_ACQUISITION_QC.json').write_text(json.dumps(qc,indent=2),encoding='utf-8');print(json.dumps(qc,indent=2))
# remove boundary binary from scientific output; crosswalk retained.
bp.unlink(missing_ok=True)
