#!/usr/bin/env python3
"""Phase 31: build source-compatible ERA5 rice-season climate on the GGCMI 0.5° grid.

Uses ERA5 monthly averaged single-level data for 2001-2015 and integrates
2-m temperature, total precipitation and potential evaporation over the two
GGCMI irrigated-rice seasons. Output is compact CSV, one row per rice grid cell
and rice season. Monthly data are a temporal-aggregation approximation to the
published daily/hourly ERA5 preprocessing and are explicitly labelled as such.
"""
from __future__ import annotations
import calendar, json, math, os, shutil, urllib.request
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr

OUT=Path(os.environ.get('OUT_DIR','phase31_era5_rice_climate')); OUT.mkdir(parents=True,exist_ok=True)
TOKEN=os.environ.get('CDSAPI_KEY','').strip()
if not TOKEN: raise RuntimeError('CDSAPI_KEY repository secret is missing')

ZEN='https://zenodo.org/api/records/5062513'
CAL_FILES=['ri1_ir_ggcmi_crop_calendar_phase3_v1.01.nc4','ri2_ir_ggcmi_crop_calendar_phase3_v1.01.nc4']

# Download exact calendars from official Zenodo record.
import requests
meta=requests.get(ZEN,timeout=60).json()
filemap={f['key']:f for f in meta['files']}
for fn in CAL_FILES:
    f=filemap[fn]; url=f['links']['content']; p=OUT/fn
    if not p.exists():
        with requests.get(url,stream=True,timeout=120) as r:
            r.raise_for_status();
            with open(p,'wb') as w:
                for chunk in r.iter_content(1024*1024): w.write(chunk)

# CDS retrieval. Use current cdsapi package/PAT semantics.
import cdsapi
client=cdsapi.Client(url='https://cds.climate.copernicus.eu/api', key=TOKEN, quiet=False, debug=False)
raw=OUT/'era5_monthly_2001_2015_0p5.nc'
request={
    'product_type':['monthly_averaged_reanalysis'],
    'variable':['2m_temperature','total_precipitation','potential_evaporation'],
    'year':[str(y) for y in range(2001,2016)],
    'month':[f'{m:02d}' for m in range(1,13)],
    'time':['00:00'],
    'data_format':'netcdf',
    'download_format':'unarchived',
    'grid':['0.5','0.5'],
}
if not raw.exists():
    try:
        client.retrieve('reanalysis-era5-single-levels-monthly-means',request,str(raw))
    except Exception as e:
        # Older CDS form fallback.
        legacy={k:v for k,v in request.items() if k not in ('data_format','download_format')}
        legacy['format']='netcdf'
        client.retrieve('reanalysis-era5-single-levels-monthly-means',legacy,str(raw))

# Open ERA5 and robustly resolve names.
ds=xr.open_dataset(raw)
def coord(cands):
    for c in cands:
        if c in ds.coords:return c
    for n in ds.coords:
        if any(c in n.lower() for c in cands):return n
    raise KeyError(cands)
latn=coord(['latitude','lat']); lonn=coord(['longitude','lon']); timen=coord(['valid_time','time','date'])
# Variable short names can vary by engine.
def var(cands):
    for c in cands:
        if c in ds.data_vars:return c
    for n in ds.data_vars:
        std=str(ds[n].attrs.get('standard_name','')).lower(); long=str(ds[n].attrs.get('long_name','')).lower()
        if any(c.lower() in (n.lower()+' '+std+' '+long) for c in cands):return n
    raise KeyError((cands,list(ds.data_vars)))
t2m=var(['t2m','2m_temperature','2 metre temperature'])
tp=var(['tp','total_precipitation','total precipitation'])
pev=var(['pev','potential_evaporation','potential evaporation'])

# Convert lon convention and align exactly to GGCMI 0.5° centers by nearest lookup.
# First build 15-year monthly climatology.
time=pd.to_datetime(ds[timen].values)
months=pd.Series(time.month,index=np.arange(len(time)))
monthly=[]
for m in range(1,13):
    inds=np.where(months.values==m)[0]
    sub=ds.isel({timen:inds})
    monthly.append({
        'month':m,
        'T_K':sub[t2m].mean(timen,skipna=True),
        'P_raw':sub[tp].mean(timen,skipna=True),
        'PEV_raw':sub[pev].mean(timen,skipna=True),
    })

# Calendars.
cals=[xr.open_dataset(OUT/f) for f in CAL_FILES]
cal_lat=np.asarray(cals[0]['lat'].values,dtype=float); cal_lon=np.asarray(cals[0]['lon'].values,dtype=float)
# ERA lat/lon.
elat=np.asarray(ds[latn].values,dtype=float); elon=np.asarray(ds[lonn].values,dtype=float)
elon180=((elon+180)%360)-180
# index nearest; request should already be 0.5 but centres may be .0 rather than .25.
lat_idx=np.array([int(np.nanargmin(abs(elat-v))) for v in cal_lat])
lon_idx=np.array([int(np.nanargmin(abs(elon180-v))) for v in cal_lon])

# Unit interpretation audit.
attrs={v:{k:str(val) for k,val in ds[v].attrs.items()} for v in [t2m,tp,pev]}
(OUT/'ERA5_native_variable_metadata.json').write_text(json.dumps(attrs,indent=2),encoding='utf-8')
# ERA5 monthly-averaged accumulated fields normally represent daily means (m/day).
# We infer by units and use overlap days. Potential evaporation follows ECMWF sign convention
# (evaporation commonly negative); convert to positive demand by negating if climatological median <0.

# Extract monthly arrays reordered to calendar grid once.
mon_arrays={}
for obj in monthly:
    m=obj['month']; mon_arrays[m]={}
    for key in ['T_K','P_raw','PEV_raw']:
        a=np.asarray(obj[key].values)
        # dimensions expected lat,lon after time mean; transpose if needed via DataArray first.
        da=obj[key].transpose(latn,lonn)
        a=np.asarray(da.values,dtype=float)
        a=a[lat_idx,:][:,lon_idx]
        mon_arrays[m][key]=a
pev_med=float(np.nanmedian(np.stack([mon_arrays[m]['PEV_raw'] for m in range(1,13)])))
pev_sign=-1.0 if pev_med<0 else 1.0

# Day-of-year calendar overlap with month. Use non-leap 365-day climatological year.
month_starts={}; d=1
for m in range(1,13):
    month_starts[m]=(d,d+calendar.monthrange(2001,m)[1]-1); d=month_starts[m][1]+1

def overlap_days(start:int,end:int,m:int)->int:
    if not (np.isfinite(start) and np.isfinite(end)): return 0
    start=int(round(start));end=int(round(end))
    ms,me=month_starts[m]
    if end>=start:
        return max(0,min(end,me)-max(start,ms)+1)
    # season crosses Dec/Jan
    return max(0,min(365,me)-max(start,ms)+1)+max(0,min(end,me)-max(1,ms)+1)

def season_length(start,end):
    if not (np.isfinite(start) and np.isfinite(end)):return np.nan
    start=int(round(start));end=int(round(end));return end-start+1 if end>=start else (365-start+1)+end

rows=[]
for season,calds in enumerate(cals,1):
    plant=np.asarray(calds['planting_day'].values,dtype=float)
    mat=np.asarray(calds['maturity_day'].values,dtype=float)
    frac=np.asarray(calds['fraction_of_harvested_area'].values,dtype=float)
    # Some files may be lon,lat; force to lat,lon based dims.
    for name,arr in [('plant',plant),('mat',mat),('frac',frac)]: pass
    if calds['planting_day'].dims != ('lat','lon'):
        plant=np.asarray(calds['planting_day'].transpose('lat','lon').values,dtype=float)
        mat=np.asarray(calds['maturity_day'].transpose('lat','lon').values,dtype=float)
        frac=np.asarray(calds['fraction_of_harvested_area'].transpose('lat','lon').values,dtype=float)
    valid=np.isfinite(plant)&np.isfinite(mat)&np.isfinite(frac)&(frac>0)
    ij=np.argwhere(valid)
    for ii,jj in ij:
        st=float(plant[ii,jj]); en=float(mat[ii,jj]); sl=season_length(st,en)
        if not np.isfinite(sl) or sl<30 or sl>365: continue
        t_sum=0.0;p_mm=0.0;pet_mm=0.0;days=0
        for m in range(1,13):
            od=overlap_days(st,en,m)
            if od<=0:continue
            days+=od
            tk=mon_arrays[m]['T_K'][ii,jj]
            pr=mon_arrays[m]['P_raw'][ii,jj]
            pe=mon_arrays[m]['PEV_raw'][ii,jj]
            if np.isfinite(tk):t_sum+=(tk-273.15)*od
            # Monthly mean accumulated fields interpreted as m/day; convert by overlap days.
            if np.isfinite(pr):p_mm+=pr*1000.0*od
            if np.isfinite(pe):pet_mm+=pev_sign*pe*1000.0*od
        if days<30:continue
        rows.append({'lat':cal_lat[ii],'lon':cal_lon[jj],'season':season,'planting_day':st,'maturity_day':en,'growing_days':days,'season_fraction':float(frac[ii,jj]),'T_C':t_sum/days,'P_mm':p_mm,'PET_mm':pet_mm,'CWA_mm':p_mm-pet_mm})
out=pd.DataFrame(rows)
out.to_csv(OUT/'ERA5_2001_2015_GGCMI_rice_season_climate_0p5.csv',index=False)
qc={'rows':len(out),'season1_rows':int((out.season==1).sum()),'season2_rows':int((out.season==2).sum()),'T_range':[float(out.T_C.min()),float(out.T_C.max())],'P_range':[float(out.P_mm.min()),float(out.P_mm.max())],'PET_range':[float(out.PET_mm.min()),float(out.PET_mm.max())],'CWA_range':[float(out.CWA_mm.min()),float(out.CWA_mm.max())],'pev_native_median':pev_med,'pev_sign_multiplier':pev_sign,'method':'ERA5 monthly 2001-2015 climatology integrated over GGCMI rice-season overlap; temporal-aggregation approximation to published ERA5 growing-season preprocessing','status':'PASS' if len(out)>5000 and out.T_C.between(-10,45).mean()>0.99 and (out.P_mm>=0).mean()>0.99 and (out.PET_mm>=0).mean()>0.99 else 'FAIL'}
(OUT/'ERA5_rice_climate_QC.json').write_text(json.dumps(qc,indent=2),encoding='utf-8');print(json.dumps(qc,indent=2))
# Remove bulky raw climate after compact output/QC.
try: raw.unlink()
except Exception: pass
if qc['status']!='PASS': raise RuntimeError('Climate QC failed: '+json.dumps(qc))
