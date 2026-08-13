import os,runpy,json
import numpy as np,pandas as pd
from aquacrop import AquaCropModel,Soil,Crop,InitialWaterContent,IrrigationManagement
C=runpy.run_path('maize-aquacrop-eja/run_aquacrop.py');OUT='maize-aquacrop-eja/results_sensitivity';os.makedirs(OUT,exist_ok=True)
wd=C['wd'];irr=C['irr'];plant=C['plant'];harvest=C['harvest'];swd=C['swdobs'];can=C['canmean'];ann=C['annmean'];metrics=C['metrics'];trtmap=C['trtmap'];root_deficit=C['root_deficit_mm']
configs=[('z060_i85',.60,85),('z060_i100',.60,100),('z105_i85',1.05,85),('z105_i100',1.05,100)]
D=[];F=[]
for name,zmax,iw in configs:
 for y in [2012,2013]:
  w=wd[wd.Year==y][['MinTemp','MaxTemp','Precipitation','ReferenceET','Date']].copy().sort_values('Date')
  for code in range(1,13):
   soil=Soil('SandyLoam');crop=Crop('Maize',planting_date=plant[y].strftime('%m/%d'),harvest_date=harvest[y].strftime('%m/%d'),Zmin=.08,Zmax=zmax);schedule=pd.DataFrame(irr[(y,code)],columns=['Date','Depth']);im=IrrigationManagement(irrigation_method=3,Schedule=schedule,MaxIrr=100,MaxIrrSeason=1200,AppEff=100);iwc=InitialWaterContent(wc_type='Pct',method='Layer',depth_layer=[1],value=[iw]);m=AquaCropModel(plant[y].strftime('%Y/%m/%d'),harvest[y].strftime('%Y/%m/%d'),w,soil,crop,iwc,irrigation_management=im);m.run_model(till_termination=True);fs=m.get_simulation_results().iloc[0];fl=m.get_water_flux();st=m.get_water_storage();gr=m.get_crop_growth();n=min(int(fs['Harvest Date (Step)'])+1,len(fl),len(st),len(gr));profile=soil.profile.reset_index(drop=True)
   for i in range(n):
    date=pd.Timestamp(plant[y])+pd.Timedelta(days=int(gr.iloc[i].time_step_counter));D.append([name,y,code,date,root_deficit(st.iloc[i],gr.iloc[i],profile),100*float(gr.iloc[i].canopy_cover)])
   F.append([name,y,code,float(fs['Dry yield (tonne/ha)']),float((fl.iloc[:n].Es+fl.iloc[:n].Tr).sum())])
D=pd.DataFrame(D,columns=['config','Year','Trt_code','Date','SWD_AC','Canopy_AC']);F=pd.DataFrame(F,columns=['config','Year','Trt_code','Yield_AC','ET_AC']);SE=D.merge(swd,on=['Year','Trt_code','Date']);CE=D.merge(can,on=['Year','Trt_code','Date']);AE=F.merge(ann,on=['Year','Trt_code']);D.to_csv(OUT+'/daily.csv',index=False);F.to_csv(OUT+'/final.csv',index=False);SE.to_csv(OUT+'/swd_eval.csv',index=False);CE.to_csv(OUT+'/canopy_eval.csv',index=False);AE.to_csv(OUT+'/annual_eval.csv',index=False)
summary={}
for name,_,_ in configs:
 summary[name]={}
 for y in [2012,2013]:
  s=SE[(SE.config==name)&(SE.Year==y)];c=CE[(CE.config==name)&(CE.Year==y)];a=AE[(AE.config==name)&(AE.Year==y)];summary[name][str(y)]={'SWD':metrics(s.SWD_obs,s.SWD_AC),'canopy':metrics(c.Canopy_obs,c.Canopy_AC),'yield':metrics(a.Yield_dry_t_ha,a.Yield_AC),'ET':metrics(a.Annual_ETc_mm,a.ET_AC)}
# selection score is defined only from training-year observations; lower is better. SWD dominates because it is the primary endpoint.
selection={}
for train,test in [(2012,2013),(2013,2012)]:
 scores={}
 for name,_,_ in configs:
  ms=summary[name][str(train)]['SWD'];mc=summary[name][str(train)]['canopy'];my=summary[name][str(train)]['yield'];scores[name]=ms['RMSE']/10+mc['RMSE']/20+my['RMSE']/2
 best=min(scores,key=scores.get);selection[f'{train}->{test}']={'scores':scores,'selected':best,'test_metrics':summary[best][str(test)]}
with open(OUT+'/metrics.json','w') as f:json.dump({'all':summary,'blind_selection':selection},f,indent=2)
print(json.dumps({'all':summary,'blind_selection':selection},indent=2));print('ROOT_INITIAL_SENSITIVITY_COMPLETE')
