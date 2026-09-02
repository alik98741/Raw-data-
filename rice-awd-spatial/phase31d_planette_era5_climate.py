#!/usr/bin/env python3
"""Build 2001-2015 ERA5-derived rice-season climate for the global AWD atlas.

Sources
-------
* ERA5 monthly 0.25-degree public Planette archive: t2m, t2m_min, t2m_max, pr.
* GGCMI Phase 3 irrigated-rice calendars from Zenodo record 5062513.

CWA is P - PET_HG. PET_HG is Hargreaves-Samani reference ET because the
credential-free Planette mirror does not expose ERA5 potential evaporation.
This transfer approximation is explicitly retained in the output metadata and
is stress-tested downstream by scaling PET by +/-20%.
"""
from __future__ import annotations
import calendar, json, math, os
from pathlib import Path
import requests
import numpy as np
import pandas as pd
import xarray as xr
import icechunk as ic

OUT=Path(os.environ.get('OUT_DIR','phase31d_planette_era5_climate')); OUT.mkdir(parents=True,exist_ok=True)
ZEN='https://zenodo.org/api/records/5062513'
CAL_FILES=['ri1_ir_ggcmi_crop_calendar_phase3_v1.01.nc4','ri2_ir_ggcmi_crop_calendar_phase3_v1.01.nc4']
VARS=['t2m','t2m_min','t2m_max','pr']

# ---- exact official crop calendars ----
meta=requests.get(ZEN,timeout=60); meta.raise_for_status(); meta=meta.json()
fmap={f['key']:f for f in meta['files']}
calendar_audit=[]
for fn in CAL_FILES:
    f=fmap[fn]; url=f.get('links',{}).get('content') or f.get('links',{}).get('self')
    if not url: raise RuntimeError(f'No downloadable link for {fn}: {f.get("links")}')
    p=OUT/fn
    if not p.exists():
        with requests.get(url,stream=True,timeout=180) as r:
            r.raise_for_status()
            with open(p,'wb') as w:
                for ch in r.iter_content(1024*1024):
                    if ch: w.write(ch)
    calendar_audit.append({'file':fn,'bytes':p.stat().st_size,'checksum':f.get('checksum'),'url':url})

# ---- calendar rows and unique climate points ----
season_frames=[]
for season,fn in enumerate(CAL_FILES,1):
    ds=xr.open_dataset(OUT/fn)
    for need in ['planting_day','maturity_day','fraction_of_harvested_area']:
        if need not in ds: raise KeyError(f'{need} absent from {fn}; vars={list(ds.data_vars)}')
    pl=ds['planting_day'].transpose('lat','lon')
    ma=ds['maturity_day'].transpose('lat','lon')
    fr=ds['fraction_of_harvested_area'].transpose('lat','lon')
    lat=np.asarray(ds['lat'].values,dtype=float); lon=np.asarray(ds['lon'].values,dtype=float)
    A=np.asarray(pl.values,dtype=float); B=np.asarray(ma.values,dtype=float); F=np.asarray(fr.values,dtype=float)
    valid=np.isfinite(A)&np.isfinite(B)&np.isfinite(F)&(F>0)&(A>=1)&(A<=366)&(B>=1)&(B<=366)
    ii,jj=np.where(valid)
    frame=pd.DataFrame({'lat':lat[ii],'lon':lon[jj],'season':season,'planting_day':A[ii,jj],'maturity_day':B[ii,jj],'season_fraction':F[ii,jj]})
    season_frames.append(frame)
cal=pd.concat(season_frames,ignore_index=True)
pts=cal[['lat','lon']].drop_duplicates().sort_values(['lat','lon']).reset_index(drop=True)
pts['point_id']=np.arange(len(pts),dtype=int)
cal=cal.merge(pts,on=['lat','lon'],how='left',validate='many_to_one')

# ---- open public ERA5 stores and compute 2001-2015 monthly point climatology ----
def open_var(var:str):
    prefix=f'era5/{var}/month/0p25latx0p25lon/era5_{var}_month_0p25latx0p25lon.zarr'
    storage=ic.s3_storage(bucket='planette-era5',prefix=prefix,region='us-east-2',anonymous=True)
    repo=ic.Repository.open(storage=storage)
    sess=repo.readonly_session('main')
    ds=xr.open_dataset(sess.store,engine='zarr',consolidated=False,chunks={})
    return ds, prefix

lat_da=xr.DataArray(pts['lat'].to_numpy(),dims='point')
lon360=np.mod(pts['lon'].to_numpy(),360.0)
lon_da=xr.DataArray(lon360,dims='point')
clim={}; source_meta={}
for var in VARS:
    print('Opening',var,flush=True)
    ds,prefix=open_var(var)
    if var not in ds.data_vars: raise KeyError((var,list(ds.data_vars)))
    da=ds[var].sel(time=slice('2001-01-01','2015-12-31'))
    if da.sizes.get('time',0)<170: raise RuntimeError(f'{var}: insufficient 2001-2015 months: {da.sizes}')
    # Time is sliced first, then nearest point selection; xarray cannot combine a slice
    # with method='nearest' in a single .sel call.
    pv=da.sel(lat=lat_da,lon=lon_da,method='nearest')
    mon=pv.groupby('time.month').mean('time',skipna=True).transpose('month','point').compute()
    if mon.sizes.get('month')!=12: raise RuntimeError(f'{var}: expected 12 climatological months, got {mon.sizes}')
    clim[var]=np.asarray(mon.values,dtype='float64')
    source_meta[var]={'prefix':prefix,'dims':{k:int(v) for k,v in ds.sizes.items()},'attrs':{k:str(v) for k,v in ds[var].attrs.items()},'selected_months':int(da.sizes['time']),'native_lat_range':[float(ds.lat.min()),float(ds.lat.max())],'native_lon_range':[float(ds.lon.min()),float(ds.lon.max())]}
    print(var,'done',clim[var].shape,flush=True)

# ---- Hargreaves extraterrestrial radiation and monthly ET0 ----
# FAO-56 Eq. 52 uses Ra in equivalent evaporation mm/day. Compute astronomical
# Ra in MJ m-2 d-1 then multiply by 0.408 mm per MJ m-2.
GSC=0.0820 # MJ m-2 min-1
month_days=np.array([calendar.monthrange(2001,m)[1] for m in range(1,13)],dtype=int)
month_start=np.r_[1,1+np.cumsum(month_days[:-1])]
month_end=month_start+month_days-1
month_mid=(month_start+month_end)/2.0
phi=np.deg2rad(pts['lat'].to_numpy(dtype=float))[:,None]
J=month_mid[None,:]
dr=1+0.033*np.cos(2*np.pi*J/365.0)
delta=0.409*np.sin(2*np.pi*J/365.0-1.39)
arg=-np.tan(phi)*np.tan(delta); arg=np.clip(arg,-1,1)
ws=np.arccos(arg)
ra_mj=(24*60/np.pi)*GSC*dr*(ws*np.sin(phi)*np.sin(delta)+np.cos(phi)*np.cos(delta)*np.sin(ws))
ra_mm=0.408*ra_mj

T=(clim['t2m'].T-273.15)        # point x month
Tmin=(clim['t2m_min'].T-273.15)
Tmax=(clim['t2m_max'].T-273.15)
Trange=np.maximum(Tmax-Tmin,0.0)
ET0=0.0023*(T+17.8)*np.sqrt(Trange)*ra_mm
ET0=np.where(np.isfinite(ET0),np.maximum(ET0,0),np.nan) # mm/day
Pday=clim['pr'].T*86400.0       # kg m-2 s-1 -> mm/day
Pday=np.where(np.isfinite(Pday),np.maximum(Pday,0),np.nan)

# ---- overlap seasons with monthly climatology ----
def olap(a,b,c,d):
    return max(0,min(b,d)-max(a,c)+1)
def month_overlap(start:int,end:int,m:int)->int:
    ms=int(month_start[m-1]); me=int(month_end[m-1])
    if end>=start: return olap(start,end,ms,me)
    return olap(start,365,ms,me)+olap(1,end,ms,me)
def slen(start:int,end:int)->int:
    return end-start+1 if end>=start else (365-start+1)+end

rows=[]
for r in cal.itertuples(index=False):
    st=int(round(r.planting_day)); en=int(round(r.maturity_day)); pid=int(r.point_id)
    # Map possible DOY 366 to climatological 365 for a non-leap transfer year.
    st=min(st,365); en=min(en,365)
    overlaps=np.array([month_overlap(st,en,m) for m in range(1,13)],dtype=float)
    days=int(overlaps.sum()); expected=slen(st,en)
    if days!=expected or days<30: continue
    tv=T[pid]; pp=Pday[pid]; ee=ET0[pid]
    if not (np.isfinite(tv[overlaps>0]).all() and np.isfinite(pp[overlaps>0]).all() and np.isfinite(ee[overlaps>0]).all()):
        tc=pmm=pet=np.nan
    else:
        tc=float(np.sum(tv*overlaps)/days)
        pmm=float(np.sum(pp*overlaps))
        pet=float(np.sum(ee*overlaps))
    rows.append({'lat':r.lat,'lon':r.lon,'season':int(r.season),'planting_day':float(r.planting_day),'maturity_day':float(r.maturity_day),'growing_days':days,'season_fraction':float(r.season_fraction),'T_C':tc,'P_mm':pmm,'PET_HG_mm':pet,'CWA_mm':pmm-pet if np.isfinite(pmm) and np.isfinite(pet) else np.nan})

out=pd.DataFrame(rows)
out.to_csv(OUT/'ERA5_2001_2015_GGCMI_rice_season_climate_HG_0p5.csv',index=False)
source_meta['calendar_files']=calendar_audit
source_meta['climate_period']='2001-2015 monthly climatology'
source_meta['PET_method']='FAO-56 Hargreaves-Samani reference ET using ERA5 t2m/t2m_min/t2m_max and astronomical Ra; Ra MJ m-2 d-1 converted to mm d-1 with 0.408'
source_meta['CWA_definition']='P_mm - PET_HG_mm'
source_meta['caution']='PET_HG is a transfer approximation because the public mirror lacks the original PETc layer; downstream +/-20% PET sensitivity is mandatory.'
(OUT/'ERA5_HG_SOURCE_METADATA.json').write_text(json.dumps(source_meta,indent=2),encoding='utf-8')

valid=out[['T_C','P_mm','PET_HG_mm','CWA_mm']].notna().all(axis=1)
qc={'calendar_rows':int(len(cal)),'unique_points':int(len(pts)),'output_rows':int(len(out)),'complete_rows':int(valid.sum()),'complete_fraction':float(valid.mean()),'season1_rows':int((out.season==1).sum()),'season2_rows':int((out.season==2).sum())}
for c in ['T_C','P_mm','PET_HG_mm','CWA_mm']:
    s=out[c].dropna(); qc[c+'_range']=[float(s.min()),float(s.max())] if len(s) else [None,None]
qc['status']='PASS' if len(out)>10000 and valid.mean()>0.99 and out.loc[valid,'T_C'].between(-10,45).mean()>0.99 and (out.loc[valid,'P_mm']>=0).all() and (out.loc[valid,'PET_HG_mm']>=0).all() else 'FAIL'
(OUT/'ERA5_HG_CLIMATE_QC.json').write_text(json.dumps(qc,indent=2),encoding='utf-8')
print(json.dumps(qc,indent=2),flush=True)
if qc['status']!='PASS': raise RuntimeError('Climate QC failed: '+json.dumps(qc))
# calendars are source inputs, not needed in compact artifact
for fn in CAL_FILES:
    try:(OUT/fn).unlink()
    except Exception:pass
