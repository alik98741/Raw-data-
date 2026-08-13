import os, runpy, json
import numpy as np
import pandas as pd
from aquacrop import AquaCropModel, Soil, Crop, InitialWaterContent, IrrigationManagement
C=runpy.run_path('maize-aquacrop-eja/refine_site_soil.py'); B=C['C']; OUT='maize-aquacrop-eja/results_measured_fc';os.makedirs(OUT,exist_ok=True)
fnum=C['fnum'];missing=C['missing'];metrics=C['metrics'];SR=C['SR'];wd=C['wd'];wb=B['wb'];fcrows=B['fc'];irr=C['irr'];plant=C['plant'];harvest=C['harvest'];swdobs=C['swdobs'];canmean=C['canmean'];annmean=C['annmean'];trtmap=C['trtmap'];om_med=C['om_med'];date_from_doy=B['date_from_doy']
def fc_curve(year):
    pts=[]
    for r in fcrows:
        if int(r['Year'])!=year:continue
        dep=r['Depth'];z=.075 if str(dep)=='0-15' else float(dep)/100.;v=fnum(r['Field_Capacity'])
        if v is not None:pts.append((z,v/100.))
    g=pd.DataFrame(pts,columns=['z','fc']).groupby('z',as_index=False).fc.mean();return g.z.values,g.fc.values

def make_soil(year):
    sec=['A','B'] if year==2012 else ['C','D'];zpts,fcpts=fc_curve(year);soil=Soil('custom',dz=[.1]*18);helper=Soil('SandyLoam');audit=[]
    for layer,top in enumerate(np.arange(0,1.8,.3),1):
        bot=top+.3;mid=(top+bot)/2;sub=SR[(SR.section.isin(sec))&(SR.mid_m>=top)&(SR.mid_m<bot)];source='section'
        if len(sub)==0:sub=SR[(SR.mid_m>=top)&(SR.mid_m<bot)];source='all_LIRF'
        if len(sub)==0:sub=SR.loc[(SR.mid_m-mid).abs().nsmallest(3).index];source='nearest_LIRF'
        sand=float(sub.sand.mean());clay=float(sub.clay.mean());om=float(sub.om.fillna(om_med).mean());taw=float((sub.thFC-sub.thWP).mean());fc=float(np.interp(mid,zpts,fcpts));wp=max(.01,fc-taw)
        _,_,sat,ksat=helper.calculate_soil_hydraulic_properties(sand/100,clay/100,om);sat=max(float(sat),fc+.03);ksat=max(float(ksat),1.)
        soil.add_layer(.3,wp,fc,sat,ksat,100);audit.append([year,''.join(sec),layer,top,bot,len(sub),source,sand,clay,om,taw,wp,fc,sat,ksat])
    return soil,audit

def deficit(ws,profile,z):
    if z is None or not np.isfinite(z):return np.nan
    s=0.;th=[c for c in ws.index if str(c).startswith('th')]
    for i,c in enumerate(th):
        if i>=len(profile):break
        p=profile.iloc[i];q=max(0.,min(float(z),float(p.zBot))-float(p.z_top))
        if q:s+=(float(p.th_fc)-float(ws[c]))*q*1000
    return s
ie=__import__('collections').defaultdict(list)
for r in wb:
    q=fnum(r.get('irr_eff (mm)'))
    if q is not None and q>0:ie[(int(r['Year']),int(r['Trt_code']))].append((pd.Timestamp(date_from_doy(int(r['Year']),int(r['DOY']))),q))
profiles=[]
for y in [2012,2013]:profiles+=make_soil(y)[1]
pd.DataFrame(profiles,columns=['Year','sections','layer','top_m','bottom_m','n','source','sand','clay','OM','TAW','thWP','thFC','thS','Ksat']).to_csv(OUT+'/soil_profile.csv',index=False)
lookup={(int(r.Year),int(r.Trt_code),pd.Timestamp(r.Date)):r for _,r in swdobs.iterrows()};D=[];F=[]
for variant,schedule_source,appeff in [('gross95','gross',95.),('effective100','effective',100.)]:
 for year in [2012,2013]:
  weather=wd[wd.Year==year][['MinTemp','MaxTemp','Precipitation','ReferenceET','Date']].copy().sort_values('Date')
  for code in range(1,13):
   soil,_=make_soil(year);q=irr[(year,code)] if schedule_source=='gross' else ie[(year,code)];schedule=pd.DataFrame(q,columns=['Date','Depth']);crop=Crop('Maize',planting_date=plant[year].strftime('%m/%d'),harvest_date=harvest[year].strftime('%m/%d'),Zmin=.08,Zmax=1.05);im=IrrigationManagement(irrigation_method=3,Schedule=schedule,MaxIrr=100,MaxIrrSeason=1200,AppEff=appeff);m=AquaCropModel(plant[year].strftime('%Y/%m/%d'),harvest[year].strftime('%Y/%m/%d'),weather,soil,crop,InitialWaterContent(value=['FC']),irrigation_management=im);m.run_model(till_termination=True);fs=m.get_simulation_results().iloc[0];fl=m.get_water_flux();st=m.get_water_storage();gr=m.get_crop_growth();n=min(int(fs['Harvest Date (Step)'])+1,len(fl),len(st),len(gr));profile=soil.profile.reset_index(drop=True)
   for i in range(n):
    date=pd.Timestamp(plant[year])+pd.Timedelta(days=int(gr.iloc[i].time_step_counter));key=(year,code,date);raw=lookup[key].root_raw if key in lookup else np.nan;zu=float(raw)/1000 if pd.notna(raw) else np.nan;zm=float(gr.iloc[i].z_root);D.append([variant,year,code,date,zm,zu,deficit(st.iloc[i],profile,zm),deficit(st.iloc[i],profile,zu),100*float(gr.iloc[i].canopy_cover),float(fl.iloc[i].Es),float(fl.iloc[i].Tr)])
   F.append([variant,year,code,float(fs['Dry yield (tonne/ha)']),float((fl.iloc[:n].Es+fl.iloc[:n].Tr).sum())])
D=pd.DataFrame(D,columns=['variant','Year','Trt_code','Date','z_model','z_USDA','SWD_modelroot','SWD_USDAroot','Canopy_AC','Es','Tr']);F=pd.DataFrame(F,columns=['variant','Year','Trt_code','DryYield_AC','SeasonalET_AC']);D.to_csv(OUT+'/daily.csv',index=False);F.to_csv(OUT+'/final.csv',index=False);SE=D.merge(swdobs,on=['Year','Trt_code','Date']);CE=D.merge(canmean,on=['Year','Trt_code','Date']);AE=F.merge(annmean,on=['Year','Trt_code']);SE.to_csv(OUT+'/swd_eval.csv',index=False);CE.to_csv(OUT+'/canopy_eval.csv',index=False);AE.to_csv(OUT+'/annual_eval.csv',index=False)
summary={'software':'AquaCrop-OSPy 3.1.0','soil':'2012/2013 measured FC + independent 2007 LIRF depth-specific TAW/texture','metrics':{}}
for v in D.variant.unique():
 summary['metrics'][v]={}
 for y in [2012,2013]:
  s=SE[(SE.variant==v)&(SE.Year==y)];c=CE[(CE.variant==v)&(CE.Year==y)];a=AE[(AE.variant==v)&(AE.Year==y)];summary['metrics'][v][str(y)]={'SWD_modelroot':metrics(s.SWD_obs,s.SWD_modelroot),'SWD_USDAroot':metrics(s.SWD_obs,s.SWD_USDAroot),'USDA_same_dates':metrics(s.SWD_obs,s.SWD_USDA),'canopy':metrics(c.Canopy_obs,c.Canopy_AC),'yield_dry':metrics(a.Yield_dry_t_ha,a.DryYield_AC),'seasonal_ET':metrics(a.Annual_ETc_mm,a.SeasonalET_AC)}
with open(OUT+'/metrics.json','w') as f:json.dump(summary,f,indent=2)
print(json.dumps(summary,indent=2));print('MEASURED_FC_AQUACROP_COMPLETE')
