import hashlib, json, math, urllib.request
from pathlib import Path
import numpy as np
import pandas as pd
from aquacrop import AquaCropModel, Soil, Crop, InitialWaterContent, IrrigationManagement

URL='https://ndownloader.figshare.com/files/44526245'
SHA='90cdefe84e4c5092d8dd217f8cf4dc5fabac38731844290fdee9ade523a95e31'
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'smoke_outputs'; OUT.mkdir(exist_ok=True)
DATA=ROOT/'data'; DATA.mkdir(exist_ok=True)
WB=DATA/'usda_2012_2013.xlsx'

if not WB.exists(): urllib.request.urlretrieve(URL,WB)
h=hashlib.sha256(WB.read_bytes()).hexdigest()
if h!=SHA: raise RuntimeError(f'SHA mismatch {h}')

def read(name,header=1):
    return pd.read_excel(WB,sheet_name=name,header=header).replace({'.':np.nan,'NA':np.nan,'N/A':np.nan})
wb=read('Water Balance ET'); fc=read('Soil Field Capacity'); ann=read('Annual data by plot'); weather=read('Weather data',0)
for c in ['Year','DOY','Trt_code']: wb[c]=pd.to_numeric(wb[c],errors='coerce')
wb=wb.dropna(subset=['Year','DOY','Trt_code']); wb[['Year','DOY','Trt_code']]=wb[['Year','DOY','Trt_code']].astype(int)
wb['Date']=pd.to_datetime(wb.Year.astype(str),format='%Y')+pd.to_timedelta(wb.DOY-1,unit='D')
fc['Year']=pd.to_numeric(fc['Year'],errors='coerce'); fc['Trt_code']=pd.to_numeric(fc['Tmt_Code'],errors='coerce')
fc['Depth_cm']=fc['Depth'].map(lambda v: float(str(v).split('-')[-1]) if pd.notna(v) else np.nan)
fc['FC']=pd.to_numeric(fc['Field_Capacity'],errors='coerce')/100.0
weather['Year']=pd.to_numeric(weather['Year'],errors='coerce'); weather['DOY']=pd.to_numeric(weather['DOY'],errors='coerce')
weather['AirTemp_C']=pd.to_numeric(weather['AirTemp_C'],errors='coerce'); weather['ETo-Daily']=pd.to_numeric(weather['ETo-Daily'],errors='coerce'); weather['Rain-Daily']=pd.to_numeric(weather['Rain-Daily'],errors='coerce')

def build_weather(year):
    w=weather[weather.Year==year].copy()
    d=w.groupby(['Year','DOY'],as_index=False).agg(MinTemp=('AirTemp_C','min'),MaxTemp=('AirTemp_C','max'),ReferenceET=('ETo-Daily','max'),Rain=('Rain-Daily','max'))
    p=wb[wb.Year==year].groupby('DOY',as_index=False)['precip_gross (mm)'].median().rename(columns={'precip_gross (mm)':'Precipitation'})
    d=d.merge(p,on='DOY',how='left'); d['Precipitation']=pd.to_numeric(d['Precipitation'],errors='coerce').fillna(d['Rain']).fillna(0)
    d['Date']=pd.to_datetime(d.Year.astype(int).astype(str),format='%Y')+pd.to_timedelta(d.DOY.astype(int)-1,unit='D')
    return d[['MinTemp','MaxTemp','Precipitation','ReferenceET','Date']]

def dates(year):
    s=wb[wb.Year==year]
    p=s.loc[s.Growth_stage.astype(str).eq('Plant'),'Date'].min(); h=s.loc[s.Growth_stage.astype(str).eq('Harvest'),'Date'].max()
    if pd.isna(h): h=s.Date.max()
    return pd.Timestamp(p),pd.Timestamp(h)

def soil_for(year,trt):
    prof=fc[(fc.Year==year)&(fc.Trt_code==trt)].dropna(subset=['Depth_cm','FC']).sort_values('Depth_cm')
    depths=np.array([15,30,60,90,120,150,200],float)
    fcv=np.interp(depths,prof.Depth_cm.to_numpy(float),prof.FC.to_numpy(float))
    dz=[.15,.15,.30,.30,.30,.30,.50]
    ref=Soil('SandyLoam',dz=dz); sat0=float(ref.profile.th_s.dropna().iloc[0]); ks=float(ref.profile.Ksat.dropna().iloc[0])
    s=Soil('custom',dz=dz)
    for thick,f in zip(dz,fcv):
        wp=max(.04,.50*float(f)); sat=max(sat0,float(f)+.08)
        s.add_layer(float(thick),wp,float(f),sat,ks,100)
    s.fill_nan(); return s

def irrigation(year,trt):
    g=wb[(wb.Year==year)&(wb.Trt_code==trt)].copy(); g['Depth']=pd.to_numeric(g['irr_eff (mm)'],errors='coerce').fillna(0)
    x=g.groupby('Date',as_index=False).Depth.sum(); return x[x.Depth>0]

def stage_cd(year,stage,plant):
    g=wb[(wb.Year==year)&(wb.Growth_stage.astype(str).eq(stage))]
    if g.empty:return None
    vals=[(pd.Timestamp(d)-plant).days for d in g.Date.dropna()]
    return int(round(np.median(vals))) if vals else None

def run(year,trt):
    plant,harvest=dates(year)
    a=ann[ann.Year==year]
    pop=float(pd.to_numeric(a['Plant density plants ha-1'],errors='coerce').mean())
    p={'CalendarType':1,'SwitchGDD':0,'PlantPop':pop,'Zmax':1.05}
    for k,st in [('EmergenceCD','Emergence'),('HIstartCD','R1'),('SenescenceCD','R5'),('MaturityCD','R6')]:
        v=stage_cd(year,st,plant)
        if v is not None and v>0:p[k]=v
    if 'MaturityCD' in p and 'HIstartCD' in p:p['YldFormCD']=max(20,p['MaturityCD']-p['HIstartCD'])
    crop=Crop('Maize',planting_date=plant.strftime('%m/%d'),harvest_date=harvest.strftime('%m/%d'),**p)
    irr=IrrigationManagement(irrigation_method=3,Schedule=irrigation(year,trt),AppEff=100,MaxIrr=1000,MaxIrrSeason=5000)
    model=AquaCropModel(plant.strftime('%Y/%m/%d'),harvest.strftime('%Y/%m/%d'),build_weather(year),soil_for(year,trt),crop,InitialWaterContent(value=['FC']),irrigation_management=irr)
    model.run_model(till_termination=True)
    st=model.get_simulation_results(); fl=model.get_water_flux(); ws=model.get_water_storage(); gr=model.get_crop_growth()
    st.to_csv(OUT/f'final_{year}_T{trt}.csv',index=False); fl.to_csv(OUT/f'flux_{year}_T{trt}.csv',index=False); ws.to_csv(OUT/f'water_{year}_T{trt}.csv',index=False); gr.to_csv(OUT/f'growth_{year}_T{trt}.csv',index=False)
    return {'year':year,'trt':trt,'plant':str(plant.date()),'harvest':str(harvest.date()),'params':p,'final_columns':list(st.columns),'flux_columns':list(fl.columns),'water_columns':list(ws.columns),'growth_columns':list(gr.columns),'final':st.iloc[0].replace({np.nan:None}).to_dict()}

summary=[]
for year,trt in [(2012,1),(2012,12),(2013,1),(2013,12)]:
    summary.append(run(year,trt))
with open(OUT/'smoke_summary.json','w') as f: json.dump(summary,f,indent=2,default=str)
print(json.dumps(summary,indent=2,default=str))
