import os, re, math, csv, json, zipfile, datetime
import xml.etree.ElementTree as ET
from collections import defaultdict
import numpy as np
import pandas as pd
from aquacrop import AquaCropModel, Soil, Crop, InitialWaterContent, IrrigationManagement

NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
RNS='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
DATA='maize_2012_2013.xlsx'
SOILS='LIRF_Soils.xlsx'
OUT='maize-aquacrop-eja/results'
os.makedirs(OUT, exist_ok=True)

def cidx(ref):
    n=0
    for c in re.match(r'([A-Z]+)', ref).group(1): n=n*26+ord(c)-64
    return n-1

def xlsx_all(path):
    with zipfile.ZipFile(path) as z:
        ss=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            root=ET.fromstring(z.read('xl/sharedStrings.xml'))
            ss=[''.join((t.text or '') for t in si.iter(f'{{{NS}}}t')) for si in root.findall(f'{{{NS}}}si')]
        wb=ET.fromstring(z.read('xl/workbook.xml'))
        rel=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        rels={e.attrib['Id']:e.attrib['Target'] for e in rel}
        paths={sh.attrib['name']:'xl/'+rels[sh.attrib[f'{{{RNS}}}id']] for sh in wb.find(f'{{{NS}}}sheets')}
        out={}
        for name,path2 in paths.items():
            rows=[]
            with z.open(path2) as fh:
                for _,el in ET.iterparse(fh,events=('end',)):
                    if el.tag==f'{{{NS}}}row':
                        d={}
                        for c in el.findall(f'{{{NS}}}c'):
                            j=cidx(c.attrib['r']); typ=c.attrib.get('t'); v=c.find(f'{{{NS}}}v'); val=None
                            if typ=='s' and v is not None: val=ss[int(v.text)]
                            elif typ=='inlineStr':
                                t=c.find(f'{{{NS}}}is/{{{NS}}}t'); val=t.text if t is not None else ''
                            elif v is not None:
                                try:
                                    q=float(v.text); val=int(q) if q.is_integer() else q
                                except Exception: val=v.text
                            d[j]=val
                        if d:
                            w=max(d)+1; r=[None]*w
                            for j,val in d.items(): r[j]=val
                            rows.append(r)
                        el.clear()
            width=max((len(r) for r in rows),default=0)
            out[name]=[r+[None]*(width-len(r)) for r in rows]
        return out

def missing(x): return x is None or x=='' or x=='.'
def fnum(x):
    if missing(x): return None
    try: return float(x)
    except Exception: return None

def as_records(rows, header_row):
    hdr=rows[header_row]
    idx={str(v):i for i,v in enumerate(hdr) if not missing(v)}
    ans=[]
    for r in rows[header_row+1:]:
        if any(not missing(v) for v in r): ans.append({k:(r[i] if i<len(r) else None) for k,i in idx.items()})
    return ans

def date_from_doy(year,doy): return datetime.date(int(year),1,1)+datetime.timedelta(days=int(doy)-1)

def metrics(obs,pred):
    a=np.asarray(obs,float); b=np.asarray(pred,float); m=np.isfinite(a)&np.isfinite(b); a=a[m];b=b[m]
    if len(a)==0:return {'n':0,'R2':None,'RMSE':None,'MAE':None,'MBE':None}
    ss_res=float(np.sum((a-b)**2)); ss_tot=float(np.sum((a-a.mean())**2))
    return {'n':int(len(a)),'R2':None if ss_tot==0 else 1-ss_res/ss_tot,'RMSE':float(np.sqrt(np.mean((a-b)**2))),'MAE':float(np.mean(np.abs(a-b))),'MBE':float(np.mean(b-a))}

def root_deficit_mm(wsrow, growrow, profile):
    z=max(0.0,float(growrow['z_root']))
    total=0.0
    thcols=[c for c in wsrow.index if str(c).startswith('th')]
    for i,c in enumerate(thcols):
        if i>=len(profile):break
        p=profile.iloc[i]
        top=float(p['z_top']); bot=float(p['zBot']); overlap=max(0.0,min(z,bot)-top)
        if overlap<=0: continue
        th=float(wsrow[c]); fc=float(p['th_fc'])
        total += (fc-th)*overlap*1000.0
    return total

book=xlsx_all(DATA)
weather=as_records(book['Weather data'],0)
wb=as_records(book['Water Balance ET'],1)
annual=as_records(book['Annual data by plot'],1)
canopy=as_records(book['Canopy Cover by Plot'],1)
lai=as_records(book['LAI by Plot'],1)
fc=as_records(book['Soil Field Capacity'],1)
trtmap={int(r['Trt_code']):str(r['Treatment']) for r in annual if not missing(r.get('Trt_code')) and not missing(r.get('Treatment'))}

g=defaultdict(list)
for r in weather:
    if not missing(r.get('Year')) and not missing(r.get('DOY')): g[(int(r['Year']),int(r['DOY']))].append(r)
daily=[]
for (yr,doy),rr in sorted(g.items()):
    temp=[fnum(r.get('AirTemp_C')) for r in rr]; temp=[x for x in temp if x is not None]
    eto=[fnum(r.get('ETo')) for r in rr]; eto=[x for x in eto if x is not None]
    rain=[fnum(r.get('Rain-Tot')) for r in rr]; rain=[x for x in rain if x is not None]
    if temp and eto:
        daily.append({'Year':yr,'DOY':doy,'Date':pd.Timestamp(date_from_doy(yr,doy)),'MinTemp':min(temp),'MaxTemp':max(temp),'Precipitation':sum(rain),'ReferenceET':sum(eto)})
wd=pd.DataFrame(daily)

irr=defaultdict(list)
for r in wb:
    d=fnum(r.get('irr_gross (mm)'))
    if d is not None and d>0:
        yr=int(r['Year']); code=int(r['Trt_code'])
        irr[(yr,code)].append((pd.Timestamp(date_from_doy(yr,int(r['DOY']))),d))

plant={}; harvest={}
for r in wb:
    if r.get('Growth_stage') in ('Plant','Harvest'):
        yr=int(r['Year']); d=date_from_doy(yr,int(r['DOY']))
        if r['Growth_stage']=='Plant': plant.setdefault(yr,d)
        else: harvest.setdefault(yr,d)

swdobs=[]
for r in wb:
    o=fnum(r.get('SWD_RZ'))
    if o is not None:
        yr=int(r['Year']); code=int(r['Trt_code']); raw=fnum(r.get('root_depth (cm)'))
        swdobs.append({'Year':yr,'Trt_code':code,'Date':pd.Timestamp(date_from_doy(yr,int(r['DOY']))),'SWD_obs':o,'SWD_USDA':fnum(r.get('SWD_Pred_RZ')),'root_raw':raw,'stage':r.get('Growth_stage')})
swdobs=pd.DataFrame(swdobs)

crows=[]
for r in canopy:
    v=fnum(r.get('Canopy_Cover'))
    if v is not None:crows.append({'Year':int(r['Year']),'Trt_code':int(r['Trt_code']),'Date':pd.Timestamp(date_from_doy(int(r['Year']),int(r['DOY']))),'Canopy_obs':v})
canmean=pd.DataFrame(crows).groupby(['Year','Trt_code','Date'],as_index=False)['Canopy_obs'].mean()

arows=[]
for r in annual:
    y=fnum(r.get('Grain Yield_15.5%mc_Kg ha-1')); et=fnum(r.get('Annual_ETc mm'))
    arows.append({'Year':int(r['Year']),'Trt_code':int(r['Trt_code']),'Yield_kg_ha':y,'Annual_ETc_mm':et})
annmean=pd.DataFrame(arows).groupby(['Year','Trt_code'],as_index=False).mean(numeric_only=True)
annmean['Yield_dry_t_ha']=annmean['Yield_kg_ha']*(1-0.155)/1000.0

try:
    sbook=xlsx_all(SOILS)
    with open(os.path.join(OUT,'soil_workbook_preview.txt'),'w') as f:
        for name,rows in sbook.items():
            f.write('\n### '+name+'\n')
            for r in rows[:30]: f.write(' | '.join('' if x is None else str(x) for x in r[:18])+'\n')
except Exception as e:
    with open(os.path.join(OUT,'soil_workbook_preview.txt'),'w') as f:f.write('SOIL_PARSE_ERROR '+repr(e))

variants={'default_maize':{'Zmin':0.30,'Zmax':1.70},'root_anchored':{'Zmin':0.08,'Zmax':1.05}}
all_daily=[]; all_final=[]
for variant,pars in variants.items():
    for yr in [2012,2013]:
        weather_year=wd[wd.Year==yr][['MinTemp','MaxTemp','Precipitation','ReferenceET','Date']].copy().sort_values('Date')
        pdate=plant[yr]; hdate=harvest[yr]
        for code in range(1,13):
            sched=pd.DataFrame(irr[(yr,code)],columns=['Date','Depth']) if irr[(yr,code)] else pd.DataFrame(columns=['Date','Depth'])
            soil=Soil('SandyLoam')
            crop=Crop('Maize',planting_date=pdate.strftime('%m/%d'),harvest_date=hdate.strftime('%m/%d'),Zmin=pars['Zmin'],Zmax=pars['Zmax'])
            im=IrrigationManagement(irrigation_method=3,Schedule=sched,MaxIrr=100.0,MaxIrrSeason=1200.0,AppEff=100.0)
            iwc=InitialWaterContent(value=['FC'])
            model=AquaCropModel(pdate.strftime('%Y/%m/%d'),hdate.strftime('%Y/%m/%d'),weather_year,soil,crop,iwc,irrigation_management=im)
            model.run_model(till_termination=True)
            fs=model.get_simulation_results().iloc[0]
            flux=model.get_water_flux().copy(); store=model.get_water_storage().copy(); grow=model.get_crop_growth().copy()
            step=int(fs['Harvest Date (Step)'])
            n=min(step+1,len(flux),len(store),len(grow))
            flux=flux.iloc[:n].reset_index(drop=True);store=store.iloc[:n].reset_index(drop=True);grow=grow.iloc[:n].reset_index(drop=True)
            profile=soil.profile.reset_index(drop=True)
            dates=[pd.Timestamp(pdate)+pd.Timedelta(days=int(x)) for x in grow['time_step_counter'].values]
            swdac=[root_deficit_mm(store.iloc[i],grow.iloc[i],profile) for i in range(n)]
            for i in range(n):
                all_daily.append({'variant':variant,'Year':yr,'Trt_code':code,'Treatment':trtmap[code],'Date':dates[i].date().isoformat(),'dap':float(grow.iloc[i]['dap']),'gdd_cum':float(grow.iloc[i]['gdd_cum']),'z_root_m':float(grow.iloc[i]['z_root']),'canopy_cover_frac':float(grow.iloc[i]['canopy_cover']),'biomass_t_ha':float(grow.iloc[i]['biomass']),'dry_yield_t_ha':float(grow.iloc[i]['DryYield']),'Es_mm':float(flux.iloc[i]['Es']),'Tr_mm':float(flux.iloc[i]['Tr']),'DeepPerc_mm':float(flux.iloc[i]['DeepPerc']),'IrrDay_mm':float(flux.iloc[i]['IrrDay']),'SWD_AquaCrop_mm':swdac[i]})
            all_final.append({'variant':variant,'Year':yr,'Trt_code':code,'Treatment':trtmap[code],'HarvestDate':str(fs['Harvest Date (YYYY/MM/DD)']),'DryYield_AquaCrop_t_ha':float(fs['Dry yield (tonne/ha)']),'FreshYield_AquaCrop_t_ha':float(fs['Fresh yield (tonne/ha)']),'SeasonalIrr_AquaCrop_mm':float(fs['Seasonal irrigation (mm)']),'SeasonalET_AquaCrop_mm':float((flux['Es']+flux['Tr']).sum())})

D=pd.DataFrame(all_daily); F=pd.DataFrame(all_final)
D.to_csv(os.path.join(OUT,'aquacrop_daily_baseline.csv'),index=False)
F.to_csv(os.path.join(OUT,'aquacrop_final_baseline.csv'),index=False)
D['Date']=pd.to_datetime(D['Date'])
swd_eval=D.merge(swdobs,on=['Year','Trt_code','Date'],how='inner')
can_eval=D.merge(canmean,on=['Year','Trt_code','Date'],how='inner')
fin_eval=F.merge(annmean,on=['Year','Trt_code'],how='left')
swd_eval.to_csv(os.path.join(OUT,'aquacrop_swd_evaluation_rows.csv'),index=False)
can_eval.to_csv(os.path.join(OUT,'aquacrop_canopy_evaluation_rows.csv'),index=False)
fin_eval.to_csv(os.path.join(OUT,'aquacrop_annual_evaluation_rows.csv'),index=False)

summary={'software':'AquaCrop-OSPy 3.1.0','source_dataset':'USDA-ARS Colorado Maize Water Productivity Dataset 2012-2013','soil_baseline':'AquaCrop-OSPy SandyLoam built-in','initial_water':'field capacity (FC)','irrigation_input':'observed gross irrigation schedule','root_depth_unit_audit':'USDA column labeled cm spans 80-1050; root_anchored sensitivity interprets trajectory as 0.08-1.05 m because literal 0.8-10.5 m is physiologically impossible','metrics':{}}
for v in variants:
    summary['metrics'][v]={}
    for yr in [2012,2013]:
        s=swd_eval[(swd_eval.variant==v)&(swd_eval.Year==yr)]
        c=can_eval[(can_eval.variant==v)&(can_eval.Year==yr)]
        a=fin_eval[(fin_eval.variant==v)&(fin_eval.Year==yr)]
        summary['metrics'][v][str(yr)]={'root_zone_deficit':metrics(s['SWD_obs'],s['SWD_AquaCrop_mm']),'canopy_cover':metrics(c['Canopy_obs'],100*c['canopy_cover_frac']),'yield_dry':metrics(a['Yield_dry_t_ha'],a['DryYield_AquaCrop_t_ha']),'seasonal_ET':metrics(a['Annual_ETc_mm'],a['SeasonalET_AquaCrop_mm']),'n_irrigation_events':int(sum(len(irr[(yr,k)]) for k in range(1,13)))}
with open(os.path.join(OUT,'baseline_metrics.json'),'w') as f:json.dump(summary,f,indent=2)
with open(os.path.join(OUT,'baseline_metrics.txt'),'w') as f:f.write(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
print('AQUACROP_BASELINE_COMPLETE')
