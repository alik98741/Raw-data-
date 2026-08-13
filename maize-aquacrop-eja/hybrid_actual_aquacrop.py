import os,json,math
import numpy as np,pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import NearestNeighbors
from sklearn.metrics import r2_score,mean_squared_error,mean_absolute_error
OUT='maize-aquacrop-eja/results_hybrid';os.makedirs(OUT,exist_ok=True)
E=pd.read_csv('maize-aquacrop-eja/results_sensitivity/swd_eval.csv',parse_dates=['Date']);E=E[E.config=='z105_i85'].copy()
B=pd.read_csv('maize-aquacrop-eja/results/aquacrop_daily_baseline.csv',parse_dates=['Date']);B=B[B.variant=='root_anchored'][['Year','Trt_code','Date','gdd_cum','z_root_m','IrrDay_mm']]
E=E.merge(B,on=['Year','Trt_code','Date'],how='left'); targets={1:(100,100),2:(100,50),3:(80,80),4:(80,65),5:(80,50),6:(80,40),7:(65,80),8:(65,65),9:(65,50),10:(65,40),11:(50,50),12:(40,40)}
# causal management-state features; no observed SWD lag or test-year target is used.
parts=[]
for (y,t),g in E.sort_values('Date').groupby(['Year','Trt_code']):
 g=g.copy();g['DAS']=(g.Date-g.Date.min()).dt.days;lv,gf=targets[int(t)];g['LV']=lv;g['GF']=gf;g['irr7']=g.IrrDay_mm.fillna(0).rolling(3,min_periods=1).sum();g['irr14']=g.IrrDay_mm.fillna(0).rolling(5,min_periods=1).sum();last=None;ds=[]
 for d,q in zip(g.Date,g.IrrDay_mm.fillna(0)):
  if q>0:last=d
  ds.append((d-last).days if last is not None else int((d-g.Date.min()).days+1))
 g['days_since_irr']=ds;parts.append(g)
E=pd.concat(parts,ignore_index=True)
# Because evaluation rows are periodic soil-water measurement dates, rolling windows above are observation-index summaries; daily irrigation timing remains represented by days_since_irr and current IrrDay.
emp=['DAS','LV','GF','irr7','irr14','days_since_irr']
hyb=emp+['SWD_AC','Canopy_AC','gdd_cum','z_root_m']

def met(y,p):
 y=np.asarray(y,float);p=np.asarray(p,float);return {'n':len(y),'R2':float(r2_score(y,p)),'RMSE':float(np.sqrt(mean_squared_error(y,p))),'MAE':float(mean_absolute_error(y,p)),'MBE':float(np.mean(p-y))}
def M(df,cols):return df[cols].astype(float).values

def residual_fit(train,test,shrink=.5,q=.5):
 X=M(train,hyb);Xt=M(test,hyb);res=train.SWD_obs.values-train.SWD_AC.values;target=res-res.mean();m=GradientBoostingRegressor(n_estimators=120,learning_rate=.035,max_depth=2,min_samples_leaf=8,loss='huber',random_state=20260813);m.fit(X,target);raw=m.predict(Xt);sc=StandardScaler().fit(X);z=sc.transform(X);zt=sc.transform(Xt);nn=NearestNeighbors(n_neighbors=min(6,len(train))).fit(z);d=nn.kneighbors(z,return_distance=True)[0][:,-1];dt=nn.kneighbors(zt,return_distance=True)[0][:,-1];ref=np.quantile(d,q);gate=np.minimum(1.,ref/np.maximum(dt,1e-9));return test.SWD_AC.values+shrink*gate*raw,gate,m

def tune(train):
 best=None
 for shrink in [.25,.5,.75,1.0]:
  for q in [.25,.5,.75]:
   yy=[];pp=[]
   for hold in sorted(train.Trt_code.unique()):
    tr=train[train.Trt_code!=hold];te=train[train.Trt_code==hold];p,_,_=residual_fit(tr,te,shrink,q);yy.extend(te.SWD_obs);pp.extend(p)
   mm=met(yy,pp);score=mm['RMSE']+.15*abs(mm['MBE'])
   if best is None or score<best[0]:best=(score,shrink,q,mm)
 return best

def ai_only(train,test):
 m=GradientBoostingRegressor(n_estimators=120,learning_rate=.035,max_depth=2,min_samples_leaf=8,loss='huber',random_state=20260813);m.fit(M(train,emp),train.SWD_obs);return m.predict(M(test,emp))
results={};predrows=[];rng=np.random.default_rng(20260813)
for tr_y,te_y in [(2012,2013),(2013,2012)]:
 tr=E[E.Year==tr_y].copy();te=E[E.Year==te_y].copy();best=tune(tr);ph,gate,model=residual_fit(tr,te,best[1],best[2]);pa=ai_only(tr,te);pp=te.SWD_AC.values;y=te.SWD_obs.values
 key=f'{tr_y}->{te_y}';results[key]={'selected_shrink':best[1],'selected_OOD_quantile':best[2],'inner_LOTO':best[3],'AquaCrop':met(y,pp),'AI_only':met(y,pa),'AquaCrop_AI_gated':met(y,ph),'median_gate':float(np.median(gate)),'fraction_gate_below_0.5':float(np.mean(gate<.5))}
 imp=100*(results[key]['AquaCrop']['RMSE']-results[key]['AquaCrop_AI_gated']['RMSE'])/results[key]['AquaCrop']['RMSE'];results[key]['RMSE_reduction_pct']=float(imp)
 boots=[];trts=sorted(te.Trt_code.unique())
 for _ in range(1500):
  sel=rng.choice(trts,len(trts),replace=True);ix=np.concatenate([np.where(te.Trt_code.values==t)[0] for t in sel]);rp=np.sqrt(mean_squared_error(y[ix],pp[ix]));rh=np.sqrt(mean_squared_error(y[ix],ph[ix]));boots.append(100*(rp-rh)/rp)
 results[key]['RMSE_reduction_bootstrap95']=[float(np.quantile(boots,.025)),float(np.quantile(boots,.975))]
 for i,r in te.reset_index(drop=True).iterrows():predrows.append([key,int(r.Year),int(r.Trt_code),r.Date.date().isoformat(),r.SWD_obs,pp[i],pa[i],ph[i],gate[i]])
# pooled leave-one-treatment-out management generalization, fixed conservative settings chosen a priori
Y=[];P=[];H=[];T=[]
for hold in sorted(E.Trt_code.unique()):
 tr=E[E.Trt_code!=hold];te=E[E.Trt_code==hold];p,_,_=residual_fit(tr,te,.5,.5);Y.extend(te.SWD_obs);P.extend(te.SWD_AC);H.extend(p);T.extend([hold]*len(te))
results['pooled_unseen_treatment']={'AquaCrop':met(Y,P),'AquaCrop_AI_gated':met(Y,H),'RMSE_reduction_pct':float(100*(met(Y,P)['RMSE']-met(Y,H)['RMSE'])/met(Y,P)['RMSE'])}
pd.DataFrame(predrows,columns=['fold','Year','Trt_code','Date','SWD_obs','AquaCrop','AI_only','AquaCrop_AI_gated','OOD_gate']).to_csv(OUT+'/blind_year_predictions.csv',index=False)
with open(OUT+'/metrics.json','w') as f:json.dump(results,f,indent=2)
print(json.dumps(results,indent=2));print('ACTUAL_AQUACROP_HYBRID_COMPLETE')
