import hashlib, json, urllib.request
from pathlib import Path
import numpy as np
import pandas as pd
from aquacrop import AquaCropModel, Soil, Crop, InitialWaterContent, IrrigationManagement

URL='https://ndownloader.figshare.com/files/44526245'
SHA='90cdefe84e4c5092d8dd217f8cf4dc5fabac38731844290fdee9ade523a95e31'
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'prior_outputs'; OUT.mkdir(exist_ok=True)
DATA=ROOT/'data'; DATA.mkdir(exist_ok=True)
WB=DATA/'usda_2012_2013.xlsx'
if not WB.exists(): urllib.request.urlretrieve(URL,WB)
if hashlib.sha256(WB.read_bytes()).hexdigest()!=SHA: raise RuntimeError('USDA workbook checksum mismatch')

def read(name,header=1):
    return pd.read_excel(WB,sheet_name=name,header=header).replace({'.':np.nan,'NA':np.nan,'N/A':np.nan})
wb=read('Water Balance ET'); weather=read('Weather data',0)
for c in ['Year','DOY','Trt_code']: wb[c]=pd.to_numeric(wb[c],errors='coerce')
wb=wb.dropna(subset=['Year','DOY','Trt_code']); wb[['Year','DOY','Trt_code']]=wb[['Year','DOY','Trt_code']].astype(int)
wb['Date']=pd.to_datetime(wb.Year.astype(str),format='%Y')+pd.to_timedelta(wb.DOY-1,unit='D')
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
    plant=s.loc[s.Growth_stage.astype(str).eq('Plant'),'Date'].min(); harvest=s.loc[s.Growth_stage.astype(str).eq('Harvest'),'Date'].max()
    if pd.isna(harvest): harvest=s.Date.max()
    return pd.Timestamp(plant),pd.Timestamp(harvest)

def irrigation(year,trt):
    g=wb[(wb.Year==year)&(wb.Trt_code==trt)].copy(); g['Depth']=pd.to_numeric(g['irr_eff (mm)'],errors='coerce').fillna(0)
    x=g.groupby('Date',as_index=False).Depth.sum(); return x[x.Depth>0]

def run(year,trt):
    plant,harvest=dates(year)
    soil=Soil('SandyLoam')
    crop=Crop('Maize',planting_date=plant.strftime('%m/%d'),harvest_date=harvest.strftime('%m/%d'),Zmax=0.60)
    initial=InitialWaterContent(wc_type='Pct',method='Layer',depth_layer=[1],value=[85])
    irr=IrrigationManagement(irrigation_method=3,Schedule=irrigation(year,trt),AppEff=100,MaxIrr=1000,MaxIrrSeason=5000)
    model=AquaCropModel(plant.strftime('%Y/%m/%d'),harvest.strftime('%Y/%m/%d'),build_weather(year),soil,crop,initial,irrigation_management=irr)
    model.run_model(till_termination=True)
    st=model.get_simulation_results(); fl=model.get_water_flux(); ws=model.get_water_storage(); gr=model.get_crop_growth()
    st.to_csv(OUT/f'final_{year}_T{trt}.csv',index=False); fl.to_csv(OUT/f'flux_{year}_T{trt}.csv',index=False); ws.to_csv(OUT/f'water_{year}_T{trt}.csv',index=False); gr.to_csv(OUT/f'growth_{year}_T{trt}.csv',index=False)
    return {'year':year,'trt':trt,'plant':str(plant.date()),'harvest':str(harvest.date()),'configuration':{'Soil':'SandyLoam','Zmax_m':0.60,'Initial_TAW_pct':85,'Crop':'Maize'},'final':st.iloc[0].replace({np.nan:None}).to_dict()}

summary=[]
for year in (2012,2013):
    for trt in range(1,13):
        print(f'Running transferred AquaCrop prior {year} treatment {trt}')
        summary.append(run(year,trt))
with open(OUT/'all_24_prior_summary.json','w') as f: json.dump(summary,f,indent=2,default=str)
print(json.dumps(summary,indent=2,default=str))
