import os,runpy,json,math
import numpy as np,pandas as pd
from aquacrop import AquaCropModel,Soil,Crop,InitialWaterContent,IrrigationManagement
from sklearn.metrics import mean_squared_error,r2_score,mean_absolute_error
OUT='maize-aquacrop-eja/results_assimilation';os.makedirs(OUT,exist_ok=True)
C=runpy.run_path('maize-aquacrop-eja/run_aquacrop.py');wd=C['wd'];irr=C['irr'];plant=C['plant'];harvest=C['harvest'];metrics=C['metrics'];WB=C['wb'];missing=C['missing'];date_from_doy=C['date_from_doy']
E=pd.read_csv('maize-aquacrop-eja/results_sensitivity/swd_eval.csv',parse_dates=['Date']);E=E[E.config=='z105_i85'][['Year','Trt_code','Date','SWD_obs','root_raw','stage']].copy();E['root_m']=E.root_raw/1000.
# Phenology is forward-filled on the COMPLETE DAILY USDA trajectory, then sampled at soil-water observation dates.
order={'Plant':0,'VE':1,'V1':2,'V2':3,'V3':4,'V4':5,'V5':6,'V6':7,'V7':8,'V8':9,'V9':10,'V10':11,'V11':12,'V12':13,'V13':14,'V14':15,'VT':16,'R1':17,'R2':18,'R3':19,'R4':20,'R5':21,'R6':22}
def sgroup(s):
 if pd.isna(s):return 'Early vegetative'
 q=order.get(str(s),0)
 if q<=8:return 'Early vegetative'
 if q<=16:return 'Late vegetative'
 if q<=19:return 'Reproductive'
 return 'Grain filling'
stage_lookup={}
for y in [2012,2013]:
 for t in range(1,13):
  rr=sorted([r for r in WB if int(r['Year'])==y and int(r['Trt_code'])==t],key=lambda r:int(r['DOY']));cur='Plant'
  for r in rr:
   if not missing(r.get('Growth_stage')):cur=str(r.get('Growth_stage'))
   stage_lookup[(y,t,pd.Timestamp(date_from_doy(y,int(r['DOY']))))]=cur
E['stage_ff']=[stage_lookup.get((int(r.Year),int(r.Trt_code),pd.Timestamp(r.Date)),'Plant') for _,r in E.iterrows()];E['stage_group']=E.stage_ff.map(sgroup)
E.groupby(['Year','stage_group']).size().rename('n_observations').reset_index().to_csv(OUT+'/stage_observation_counts.csv',index=False)

def deficit(th,profile,z):
 z=max(0.,float(z));s=0.
 for i,p in profile.iterrows():
  overlap=max(0.,min(z,float(p.zBot))-float(p.z_top))
  if overlap>0:s+=(float(p.th_fc)-float(th[i]))*overlap*1000.
 return s

def update_theta(th,profile,z,target):
 th=np.array(th,float).copy();active=[i for i,p in profile.iterrows() if float(p.z_top)<z and min(z,float(p.zBot))-float(p.z_top)>0]
 if not active:return th
 def apply(c):
  x=th.copy()
  for i in active:x[i]=np.clip(th[i]+c,float(profile.iloc[i].th_wp),float(profile.iloc[i].th_s))
  return x
 lo,hi=-.5,.5;dlo=deficit(apply(lo),profile,z);dhi=deficit(apply(hi),profile,z);target=float(np.clip(target,min(dlo,dhi),max(dlo,dhi)))
 for _ in range(60):
  mid=(lo+hi)/2.;dm=deficit(apply(mid),profile,z)
  if dm>target:lo=mid
  else:hi=mid
 return apply((lo+hi)/2.)

def make_model(year,code):
 weather=wd[wd.Year==year][['MinTemp','MaxTemp','Precipitation','ReferenceET','Date']].copy().sort_values('Date');schedule=pd.DataFrame(irr[(year,code)],columns=['Date','Depth']);soil=Soil('SandyLoam');crop=Crop('Maize',planting_date=plant[year].strftime('%m/%d'),harvest_date=harvest[year].strftime('%m/%d'),Zmin=.08,Zmax=1.05);iw=InitialWaterContent(wc_type='Pct',method='Layer',depth_layer=[1],value=[85]);im=IrrigationManagement(irrigation_method=3,Schedule=schedule,MaxIrr=100,MaxIrrSeason=1200,AppEff=100);return AquaCropModel(plant[year].strftime('%Y/%m/%d'),harvest[year].strftime('%Y/%m/%d'),weather,soil,crop,iw,irrigation_management=im)

def simulate(year,code,gain=0.,stage_select='ALL'):
 obs=E[(E.Year==year)&(E.Trt_code==code)].sort_values('Date').copy();od={pd.Timestamp(r.Date):r for _,r in obs.iterrows()};model=make_model(year,code);rows=[];first=True
 while True:
  model.run_model(num_steps=1,initialize_model=first);first=False;idx=int(model._clock_struct.time_step_counter)-1;cur=pd.Timestamp(model._clock_struct.simulation_start_date)+pd.Timedelta(days=idx);profile=model._param_struct.Soil.profile.reset_index(drop=True)
  if cur in od:
   r=od[cur];z=float(r.root_m);prior=deficit(model._init_cond.th,profile,z);rows.append([year,code,cur,float(r.SWD_obs),z,r.stage_group,prior])
   if gain>0 and (stage_select=='ALL' or r.stage_group==stage_select):
    target=prior+gain*(float(r.SWD_obs)-prior);model._init_cond.th=update_theta(model._init_cond.th,profile,z,target)
  if model._clock_struct.model_is_finished:break
 return pd.DataFrame(rows,columns=['Year','Trt_code','Date','SWD_obs','root_m','stage_group','prior'])

def met(df,col):return metrics(df.SWD_obs,df[col])
baselines=[]
for y in [2012,2013]:
 for t in range(1,13):baselines.append(simulate(y,t,0,'ALL').rename(columns={'prior':'baseline'}))
BASE=pd.concat(baselines,ignore_index=True);BASE.to_csv(OUT+'/baseline_observation_root.csv',index=False)
sel={};testall=[];gains=[.25,.5,.75,1.0]
for train,test in [(2012,2013),(2013,2012)]:
 scores={}
 for k in gains:
  rr=[]
  for t in range(1,13):rr.append(simulate(train,t,k,'ALL'))
  q=pd.concat(rr,ignore_index=True);scores[str(k)]=met(q,'prior')['RMSE']
 best=float(min(scores,key=scores.get));sel[f'{train}->{test}']={'training_RMSE_by_gain':scores,'selected_gain':best}
 rr=[]
 for t in range(1,13):rr.append(simulate(test,t,best,'ALL'))
 q=pd.concat(rr,ignore_index=True).merge(BASE[BASE.Year==test][['Year','Trt_code','Date','baseline']],on=['Year','Trt_code','Date']);sel[f'{train}->{test}']['test_baseline']=met(q,'baseline');sel[f'{train}->{test}']['test_assimilated']=met(q,'prior');sel[f'{train}->{test}']['RMSE_reduction_pct']=100*(sel[f'{train}->{test}']['test_baseline']['RMSE']-sel[f'{train}->{test}']['test_assimilated']['RMSE'])/sel[f'{train}->{test}']['test_baseline']['RMSE'];q['fold']=f'{train}->{test}';testall.append(q)
 stage_res={}
 for stage in ['Early vegetative','Late vegetative','Reproductive','Grain filling']:
  rs=[]
  for t in range(1,13):rs.append(simulate(test,t,best,stage))
  a=pd.concat(rs,ignore_index=True).merge(BASE[BASE.Year==test][['Year','Trt_code','Date','baseline']],on=['Year','Trt_code','Date']);updates=E[(E.Year==test)&(E.stage_group==stage)][['Trt_code','Date']];stage_res[stage]={}
  for h in [7,14,28]:
   keep=[]
   for i,r in a.iterrows():
    ud=updates[updates.Trt_code==r.Trt_code].Date;ok=any((r.Date>d) and ((r.Date-d).days<=h) for d in ud)
    if ok:keep.append(i)
   z=a.loc[keep]
   if len(z):
    mb=met(z,'baseline');ma=met(z,'prior');stage_res[stage][str(h)]={'n':len(z),'baseline_RMSE':mb['RMSE'],'assimilated_RMSE':ma['RMSE'],'VOI_pct':100*(mb['RMSE']-ma['RMSE'])/mb['RMSE']}
   else:stage_res[stage][str(h)]={'n':0,'VOI_pct':None}
 sel[f'{train}->{test}']['stage_horizon']=stage_res
pd.concat(testall,ignore_index=True).to_csv(OUT+'/blind_all_observation_assimilation.csv',index=False)
with open(OUT+'/metrics.json','w') as f:json.dump(sel,f,indent=2)
print(json.dumps(sel,indent=2));print('TRUE_AQUACROP_STATE_ASSIMILATION_COMPLETE')
