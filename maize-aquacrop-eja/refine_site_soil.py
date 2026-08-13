import os, runpy, json
import numpy as np
import pandas as pd
from aquacrop import AquaCropModel, Soil, Crop, InitialWaterContent, IrrigationManagement

C=runpy.run_path('maize-aquacrop-eja/run_aquacrop.py')
OUT='maize-aquacrop-eja/results_refined'; os.makedirs(OUT,exist_ok=True)
fnum=C['fnum']; missing=C['missing']; metrics=C['metrics']; sbook=C['sbook']; wd=C['wd']; irr=C['irr']; plant=C['plant']; harvest=C['harvest']; trtmap=C['trtmap']; swdobs=C['swdobs']; canmean=C['canmean']; annmean=C['annmean']

# Independent 2007 LIRF moisture-release characterization.
rows=sbook['Moisture Release']; hi=next(i for i,r in enumerate(rows) if len(r)>1 and str(r[0]).strip()=='SiteID' and str(r[1]).strip()=='Plot ID')
a=[]
for r in rows[hi+1:]:
    if len(r)<13: continue
    site=fnum(r[0]); plot='' if missing(r[1]) else str(r[1]).strip(); up=fnum(r[2]); lo=fnum(r[3]); sand=fnum(r[5]); clay=fnum(r[6]); om=fnum(r[8]); fc=fnum(r[10]); wp=fnum(r[11])
    if None not in (site,up,lo,sand,clay,fc,wp) and plot:
        a.append([int(site),plot,plot[0].upper(),up,lo,(up+lo)/200,sand,clay,om,fc,wp])
SR=pd.DataFrame(a,columns=['site','plot','section','upper_cm','lower_cm','mid_m','sand','clay','om','thFC','thWP'])
om_med=float(SR.om.dropna().median())

def make_soil(year):
    sections=['A','B'] if year==2012 else ['C','D']; soil=Soil('custom',dz=[.1]*18); helper=Soil('SandyLoam'); audit=[]
    for layer,top in enumerate(np.arange(0,1.8,.3),1):
        bot=top+.3; sub=SR[(SR.section.isin(sections))&(SR.mid_m>=top)&(SR.mid_m<bot)]; source='section'
        if len(sub)==0: sub=SR[(SR.mid_m>=top)&(SR.mid_m<bot)]; source='all_LIRF'
        if len(sub)==0:
            ix=(SR.mid_m-(top+bot)/2).abs().nsmallest(3).index; sub=SR.loc[ix]; source='nearest_LIRF'
        sand=float(sub.sand.mean()); clay=float(sub.clay.mean()); om=float(sub.om.fillna(om_med).mean()); fc=float(sub.thFC.mean()); wp=float(sub.thWP.mean())
        _,_,sat,ksat=helper.calculate_soil_hydraulic_properties(sand/100,clay/100,om); sat=max(float(sat),fc+.02); ksat=max(float(ksat),1)
        soil.add_layer(.3,wp,fc,sat,ksat,100)
        audit.append([year,''.join(sections),layer,top,bot,len(sub),source,sand,clay,om,wp,fc,sat,ksat])
    return soil,audit

def deficit(ws,profile,z):
    if z is None or not np.isfinite(z): return np.nan
    total=0.; th=[c for c in ws.index if str(c).startswith('th')]
    for i,c in enumerate(th):
        if i>=len(profile): break
        p=profile.iloc[i]; overlap=max(0.,min(float(z),float(p.zBot))-float(p.z_top))
        if overlap: total+=(float(p.th_fc)-float(ws[c]))*overlap*1000
    return total

soila=[]
for y in [2012,2013]: soila += make_soil(y)[1]
pd.DataFrame(soila,columns=['Year','sections','layer','top_m','bottom_m','n_samples','source','sand_pct','clay_pct','OM_pct','thWP','thFC','thS','Ksat_mm_d']).to_csv(OUT+'/LIRF_soil_profile.csv',index=False)
lookup={(int(r.Year),int(r.Trt_code),pd.Timestamp(r.Date)):r for _,r in swdobs.iterrows()}
D=[]; F=[]
for year in [2012,2013]:
    weather=wd[wd.Year==year][['MinTemp','MaxTemp','Precipitation','ReferenceET','Date']].copy().sort_values('Date')
    for code in range(1,13):
        soil,_=make_soil(year); schedule=pd.DataFrame(irr[(year,code)],columns=['Date','Depth']); crop=Crop('Maize',planting_date=plant[year].strftime('%m/%d'),harvest_date=harvest[year].strftime('%m/%d'),Zmin=.08,Zmax=1.05)
        im=IrrigationManagement(irrigation_method=3,Schedule=schedule,MaxIrr=100,MaxIrrSeason=1200,AppEff=100)
        m=AquaCropModel(plant[year].strftime('%Y/%m/%d'),harvest[year].strftime('%Y/%m/%d'),weather,soil,crop,InitialWaterContent(value=['FC']),irrigation_management=im); m.run_model(till_termination=True)
        fs=m.get_simulation_results().iloc[0]; flux=m.get_water_flux(); store=m.get_water_storage(); grow=m.get_crop_growth(); n=min(int(fs['Harvest Date (Step)'])+1,len(flux),len(store),len(grow)); profile=soil.profile.reset_index(drop=True)
        for i in range(n):
            date=pd.Timestamp(plant[year])+pd.Timedelta(days=int(grow.iloc[i].time_step_counter)); zmodel=float(grow.iloc[i].z_root); key=(year,code,date); raw=lookup[key].root_raw if key in lookup else np.nan; zaudit=float(raw)/1000 if pd.notna(raw) else np.nan
            D.append([year,code,date,float(grow.iloc[i].dap),zmodel,zaudit,deficit(store.iloc[i],profile,zmodel),deficit(store.iloc[i],profile,zaudit),100*float(grow.iloc[i].canopy_cover),float(grow.iloc[i].biomass),float(flux.iloc[i].Es),float(flux.iloc[i].Tr)])
        F.append([year,code,float(fs['Dry yield (tonne/ha)']),float((flux.iloc[:n].Es+flux.iloc[:n].Tr).sum()),str(fs['Harvest Date (YYYY/MM/DD)'])])
D=pd.DataFrame(D,columns=['Year','Trt_code','Date','dap','z_root_model_m','z_root_USDA_audit_m','SWD_modelroot','SWD_USDAroot_audit','Canopy_AC_pct','Biomass_AC','Es','Tr']); F=pd.DataFrame(F,columns=['Year','Trt_code','DryYield_AC','SeasonalET_AC','HarvestDate'])
D.to_csv(OUT+'/aquacrop_daily_site_soil.csv',index=False); F.to_csv(OUT+'/aquacrop_final_site_soil.csv',index=False)
SE=D.merge(swdobs,on=['Year','Trt_code','Date']); CE=D.merge(canmean,on=['Year','Trt_code','Date']); AE=F.merge(annmean,on=['Year','Trt_code']); SE.to_csv(OUT+'/swd_eval.csv',index=False); CE.to_csv(OUT+'/canopy_eval.csv',index=False); AE.to_csv(OUT+'/annual_eval.csv',index=False)
summary={'software':'AquaCrop-OSPy 3.1.0','soil':'independent LIRF 2007 moisture-release, AB sections for 2012 and CD for 2013','root_parameters':'Zmin=0.08 m, Zmax=1.05 m','initial_water':'FC','metrics':{}}
for y in [2012,2013]:
    s=SE[SE.Year==y]; c=CE[CE.Year==y]; aa=AE[AE.Year==y]
    summary['metrics'][str(y)]={'SWD_modelroot':metrics(s.SWD_obs,s.SWD_modelroot),'SWD_USDAroot_audit':metrics(s.SWD_obs,s.SWD_USDAroot_audit),'USDA_process_same_dates':metrics(s.SWD_obs,s.SWD_USDA),'canopy':metrics(c.Canopy_obs,c.Canopy_AC_pct),'yield_dry':metrics(aa.Yield_dry_t_ha,aa.DryYield_AC),'seasonal_ET':metrics(aa.Annual_ETc_mm,aa.SeasonalET_AC)}
with open(OUT+'/site_soil_metrics.json','w') as f: json.dump(summary,f,indent=2)
print(json.dumps(summary,indent=2)); print('SITE_SOIL_AQUACROP_COMPLETE')
