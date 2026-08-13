import os,json
import numpy as np,pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import NearestNeighbors
from sklearn.metrics import r2_score,mean_squared_error,mean_absolute_error
OUT='maize-aquacrop-eja/results_final_aligned';os.makedirs(OUT,exist_ok=True)
X=pd.read_csv('maize-aquacrop-eja/results_hybrid_v2/analysis_rows.csv',parse_dates=['Date']);BASE=pd.read_csv('maize-aquacrop-eja/results_assimilation/baseline_observation_root.csv',parse_dates=['Date']);ASS=pd.read_csv('maize-aquacrop-eja/results_assimilation/blind_all_observation_assimilation.csv',parse_dates=['Date'])
A=ASS.sort_values('fold').drop_duplicates(['Year','Trt_code','Date'])[['Year','Trt_code','Date','prior','stage_group']].rename(columns={'prior':'SWD_state_updated'})
B=X.merge(BASE[['Year','Trt_code','Date','baseline','stage_group']],on=['Year','Trt_code','Date'],how='inner').merge(A,on=['Year','Trt_code','Date'],how='left',suffixes=('','_assim'));B['SWD_process_aligned']=B.baseline;B['stage_group']=B.stage_group.fillna(B.stage_group_assim)
# Causal exogenous variables come from the raw USDA record. The only auxiliary process state retained is canopy from the selected z=1.05 m/85% TAW AquaCrop run. z_root, Es, Tr and DeepPerc from an earlier sensitivity run are intentionally excluded to avoid mixing process configurations.
emp=['dap','gdd_cum','LV','GF','Tmean','ETo','Rain','Irr','irr7','irr14','rain7','rain14','eto7','eto14','days_since_irr','cum_irr','cum_rain','cum_eto'];proc_extra=['Canopy_AC']
def M(d,c):return d[c].astype(float).replace([np.inf,-np.inf],np.nan).fillna(0).values
def met(y,p):
 y=np.asarray(y,float);p=np.asarray(p,float);return {'n':len(y),'R2':float(r2_score(y,p)),'RMSE':float(np.sqrt(mean_squared_error(y,p))),'MAE':float(mean_absolute_error(y,p)),'MBE':float(np.mean(p-y))}
def fit_res(train,test,basecol,gate=True,shrink=1.,q=.75):
 cols=emp+[basecol]+proc_extra;Xt=M(train,cols);Xv=M(test,cols);res=train.SWD_obs.values-train[basecol].values;target=res-res.mean();m=GradientBoostingRegressor(n_estimators=120,learning_rate=.035,max_depth=2,min_samples_leaf=8,loss='huber',random_state=20260813);m.fit(Xt,target);raw=m.predict(Xv)
 if gate:
  sc=StandardScaler().fit(Xt);z=sc.transform(Xt);zv=sc.transform(Xv);nn=NearestNeighbors(n_neighbors=min(6,len(train))).fit(z);d=nn.kneighbors(z,return_distance=True)[0][:,-1];dv=nn.kneighbors(zv,return_distance=True)[0][:,-1];ref=np.quantile(d,q);w=np.minimum(1.,ref/np.maximum(dv,1e-9))
 else:w=np.ones(len(test))
 return test[basecol].values+shrink*w*raw,w,m
def tune(train,basecol,gate):
 best=None
 for s in [.25,.5,.75,1.]:
  qs=[.25,.5,.75] if gate else [.5]
  for q in qs:
   yy=[];pp=[]
   for hold in sorted(train.Trt_code.unique()):
    tr=train[train.Trt_code!=hold];te=train[train.Trt_code==hold];p,_,_=fit_res(tr,te,basecol,gate,s,q);yy+=list(te.SWD_obs);pp+=list(p)
   mm=met(yy,pp);score=mm['RMSE']+.15*abs(mm['MBE'])
   if best is None or score<best[0]:best=(score,s,q,mm)
 return best
def ai(train,test):
 m=GradientBoostingRegressor(n_estimators=120,learning_rate=.035,max_depth=2,min_samples_leaf=8,loss='huber',random_state=20260813);m.fit(M(train,emp),train.SWD_obs);return m.predict(M(test,emp))
R={};rows=[];rng=np.random.default_rng(20260813)
for ty,vy in [(2012,2013),(2013,2012)]:
 tr=B[B.Year==ty].copy();te=B[B.Year==vy].copy();y=te.SWD_obs.values;p0=te.SWD_process_aligned.values;p1=ai(tr,te)
 t2=tune(tr,'SWD_process_aligned',False);p2,_,_=fit_res(tr,te,'SWD_process_aligned',False,t2[1],t2[2]);t3=tune(tr,'SWD_process_aligned',True);p3,w3,m3=fit_res(tr,te,'SWD_process_aligned',True,t3[1],t3[2]);p4a=te.SWD_state_updated.values
 t4=tune(tr,'SWD_state_updated',True);p4,w4,m4=fit_res(tr,te,'SWD_state_updated',True,t4[1],t4[2]);key=f'{ty}->{vy}'
 R[key]={'M0_AquaCrop_aligned':met(y,p0),'M1_AI_only':met(y,p1),'M2_AquaCrop_residual':met(y,p2),'M3_AquaCrop_OOD_AI':met(y,p3),'state_assimilation_ablation':met(y,p4a),'M4_state_updated_AquaCrop_OOD_AI':met(y,p4),'M2_tuning':{'shrink':t2[1],'inner':t2[3]},'M3_tuning':{'shrink':t3[1],'q':t3[2],'inner':t3[3]},'M4_tuning':{'shrink':t4[1],'q':t4[2],'inner':t4[3]},'M3_median_gate':float(np.median(w3)),'M4_median_gate':float(np.median(w4)),'M3_feature_importance':dict(sorted(zip(emp+['SWD_process_aligned']+proc_extra,m3.feature_importances_),key=lambda x:x[1],reverse=True)),'M4_feature_importance':dict(sorted(zip(emp+['SWD_state_updated']+proc_extra,m4.feature_importances_),key=lambda x:x[1],reverse=True))}
 for name,p in [('M1',p1),('M2',p2),('M3',p3),('Assim',p4a),('M4',p4)]:R[key][name+'_RMSE_reduction_vs_M0_pct']=100*(R[key]['M0_AquaCrop_aligned']['RMSE']-met(y,p)['RMSE'])/R[key]['M0_AquaCrop_aligned']['RMSE']
 boots=[];trts=sorted(te.Trt_code.unique())
 for _ in range(1500):
  ss=rng.choice(trts,len(trts),replace=True);ix=np.concatenate([np.where(te.Trt_code.values==t)[0] for t in ss]);r0=np.sqrt(mean_squared_error(y[ix],p0[ix]));r4=np.sqrt(mean_squared_error(y[ix],p4[ix]));boots.append(100*(r0-r4)/r0)
 R[key]['M4_RMSE_reduction_bootstrap95']=[float(np.quantile(boots,.025)),float(np.quantile(boots,.975))];per={}
 for t in trts:
  ix=np.where(te.Trt_code.values==t)[0];per[str(int(t))]=100*(met(y[ix],p0[ix])['RMSE']-met(y[ix],p4[ix])['RMSE'])/met(y[ix],p0[ix])['RMSE']
 R[key]['M4_per_treatment_reduction_pct']=per;R[key]['M4_treatments_improved']=sum(v>0 for v in per.values())
 for i,r in te.reset_index(drop=True).iterrows():rows.append([key,int(r.Year),int(r.Trt_code),r.Date.date().isoformat(),r.stage_group,r.SWD_obs,p0[i],p1[i],p2[i],p3[i],p4a[i],p4[i],w3[i],w4[i]])
pd.DataFrame(rows,columns=['fold','Year','Trt_code','Date','stage_group','SWD_obs','M0_AquaCrop','M1_AI','M2_residual','M3_OOD_AI','Assim_only','M4_full','M3_gate','M4_gate']).to_csv(OUT+'/blind_predictions.csv',index=False)
with open(OUT+'/metrics.json','w') as f:json.dump(R,f,indent=2)
print(json.dumps(R,indent=2));print('FINAL_ALIGNED_MODEL_COMPARISON_COMPLETE')
