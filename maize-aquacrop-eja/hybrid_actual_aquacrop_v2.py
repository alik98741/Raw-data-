import os,json,math,zipfile,re,datetime,xml.etree.ElementTree as ET
import numpy as np,pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import NearestNeighbors
from sklearn.metrics import r2_score,mean_squared_error,mean_absolute_error
OUT='maize-aquacrop-eja/results_hybrid_v2';os.makedirs(OUT,exist_ok=True);DATA='maize_2012_2013.xlsx'
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main';RNS='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
def ci(x):
 n=0
 for c in re.match(r'([A-Z]+)',x).group(1):n=n*26+ord(c)-64
 return n-1
def read_sheets(path,wanted):
 with zipfile.ZipFile(path) as z:
  ss=[]
  if 'xl/sharedStrings.xml' in z.namelist():
   rr=ET.fromstring(z.read('xl/sharedStrings.xml'));ss=[''.join((t.text or '') for t in s.iter(f'{{{NS}}}t')) for s in rr.findall(f'{{{NS}}}si')]
  wb=ET.fromstring(z.read('xl/workbook.xml'));rel=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'));rels={e.attrib['Id']:e.attrib['Target'] for e in rel};paths={s.attrib['name']:'xl/'+rels[s.attrib[f'{{{RNS}}}id']] for s in wb.find(f'{{{NS}}}sheets')}
  out={}
  for name in wanted:
   rows=[]
   with z.open(paths[name]) as fh:
    for _,el in ET.iterparse(fh,events=('end',)):
     if el.tag==f'{{{NS}}}row':
      d={}
      for c in el.findall(f'{{{NS}}}c'):
       j=ci(c.attrib['r']);typ=c.attrib.get('t');v=c.find(f'{{{NS}}}v');val=None
       if typ=='s' and v is not None:val=ss[int(v.text)]
       elif v is not None:
        try:q=float(v.text);val=int(q) if q.is_integer() else q
        except:val=v.text
       d[j]=val
      if d:
       x=[None]*(max(d)+1)
       for j,vv in d.items():x[j]=vv
       rows.append(x)
      el.clear()
   w=max(map(len,rows));out[name]=[r+[None]*(w-len(r)) for r in rows]
  return out
def rec(rows,h):
 hdr=rows[h];idx={str(v):i for i,v in enumerate(hdr) if v is not None};return [{k:(r[i] if i<len(r) else None) for k,i in idx.items()} for r in rows[h+1:] if any(v is not None for v in r)]
def num(x):
 try:return float(x)
 except:return np.nan
def date(y,d):return pd.Timestamp(datetime.date(int(y),1,1)+datetime.timedelta(days=int(d)-1))
S=read_sheets(DATA,['Weather data','Water Balance ET']);W=rec(S['Weather data'],0);WB=rec(S['Water Balance ET'],1)
# true daily weather aggregation
d=[]
for (y,dy),g in pd.DataFrame(W).groupby(['Year','DOY']):
 t=pd.to_numeric(g['AirTemp_C'],errors='coerce');eto=pd.to_numeric(g['ETo'],errors='coerce');rain=pd.to_numeric(g['Rain-Tot'],errors='coerce').fillna(0);d.append([int(y),int(dy),date(y,dy),float(t.mean()),float(t.max()),float(t.min()),float(eto.sum()),float(rain.sum())])
WX=pd.DataFrame(d,columns=['Year','DOY','Date','Tmean','Tmax','Tmin','ETo','Rain'])
# actual daily irrigation by year/treatment from source water-balance schedule
mg=[]
for r in WB:
 if r.get('Year') is None or r.get('Trt_code') is None or r.get('DOY') is None:continue
 mg.append([int(r['Year']),int(r['Trt_code']),date(r['Year'],r['DOY']),0 if not np.isfinite(num(r.get('irr_gross (mm)'))) else num(r.get('irr_gross (mm)'))])
MG=pd.DataFrame(mg,columns=['Year','Trt_code','Date','Irr']).groupby(['Year','Trt_code','Date'],as_index=False).Irr.max()
B=pd.read_csv('maize-aquacrop-eja/results_sensitivity/swd_eval.csv',parse_dates=['Date']);B=B[B.config=='z105_i85'].copy();P=pd.read_csv('maize-aquacrop-eja/results/aquacrop_daily_baseline.csv',parse_dates=['Date']);P=P[P.variant=='root_anchored'][['Year','Trt_code','Date','dap','gdd_cum','z_root_m','canopy_cover_frac','Es_mm','Tr_mm','DeepPerc_mm']]
# build daily causal covariates, then join at observed SWD dates
targets={1:(100,100),2:(100,50),3:(80,80),4:(80,65),5:(80,50),6:(80,40),7:(65,80),8:(65,65),9:(65,50),10:(65,40),11:(50,50),12:(40,40)};daily=[]
for (y,t),g in MG.groupby(['Year','Trt_code']):
 x=WX[WX.Year==y].merge(g,on=['Year','Date'],how='left');x['Trt_code']=t;x.Irr=x.Irr.fillna(0);x=x.sort_values('Date');x['irr7']=x.Irr.rolling(7,min_periods=1).sum();x['irr14']=x.Irr.rolling(14,min_periods=1).sum();x['rain7']=x.Rain.rolling(7,min_periods=1).sum();x['rain14']=x.Rain.rolling(14,min_periods=1).sum();x['eto7']=x.ETo.rolling(7,min_periods=1).sum();x['eto14']=x.ETo.rolling(14,min_periods=1).sum();last=None;ds=[]
 for dt,q in zip(x.Date,x.Irr):
  if q>0:last=dt
  ds.append((dt-last).days if last is not None else 999)
 x['days_since_irr']=ds;x['cum_irr']=x.Irr.cumsum();x['cum_rain']=x.Rain.cumsum();x['cum_eto']=x.ETo.cumsum();daily.append(x)
D=pd.concat(daily,ignore_index=True);B=B.merge(P,on=['Year','Trt_code','Date'],how='left').merge(D[['Year','Trt_code','Date','Tmean','Tmax','Tmin','ETo','Rain','Irr','irr7','irr14','rain7','rain14','eto7','eto14','days_since_irr','cum_irr','cum_rain','cum_eto']],on=['Year','Trt_code','Date'],how='left');B['LV']=B.Trt_code.map(lambda x:targets[int(x)][0]);B['GF']=B.Trt_code.map(lambda x:targets[int(x)][1]);B.to_csv(OUT+'/analysis_rows.csv',index=False)
emp=['dap','gdd_cum','LV','GF','Tmean','ETo','Rain','Irr','irr7','irr14','rain7','rain14','eto7','eto14','days_since_irr','cum_irr','cum_rain','cum_eto'];hyb=emp+['SWD_AC','Canopy_AC','z_root_m','Es_mm','Tr_mm','DeepPerc_mm']
def M(x,c):return x[c].astype(float).replace([np.inf,-np.inf],np.nan).fillna(0).values
def met(y,p):
 y=np.asarray(y,float);p=np.asarray(p,float);return {'n':len(y),'R2':float(r2_score(y,p)),'RMSE':float(np.sqrt(mean_squared_error(y,p))),'MAE':float(mean_absolute_error(y,p)),'MBE':float(np.mean(p-y))}
def resfit(tr,te,shrink,q):
 X=M(tr,hyb);Xt=M(te,hyb);r=tr.SWD_obs.values-tr.SWD_AC.values;target=r-r.mean();m=GradientBoostingRegressor(n_estimators=120,learning_rate=.035,max_depth=2,min_samples_leaf=8,loss='huber',random_state=20260813);m.fit(X,target);raw=m.predict(Xt);sc=StandardScaler().fit(X);z=sc.transform(X);zt=sc.transform(Xt);nn=NearestNeighbors(n_neighbors=min(6,len(tr))).fit(z);d=nn.kneighbors(z,return_distance=True)[0][:,-1];dt=nn.kneighbors(zt,return_distance=True)[0][:,-1];ref=np.quantile(d,q);gate=np.minimum(1.,ref/np.maximum(dt,1e-9));return te.SWD_AC.values+shrink*gate*raw,gate,m
def tune(tr):
 best=None
 for shrink in [.25,.5,.75,1.0]:
  for q in [.25,.5,.75]:
   yy=[];pp=[]
   for hold in sorted(tr.Trt_code.unique()):
    a=tr[tr.Trt_code!=hold];b=tr[tr.Trt_code==hold];p,_,_=resfit(a,b,shrink,q);yy+=list(b.SWD_obs);pp+=list(p)
   mm=met(yy,pp);score=mm['RMSE']+.15*abs(mm['MBE'])
   if best is None or score<best[0]:best=(score,shrink,q,mm)
 return best
def aifit(tr,te):
 m=GradientBoostingRegressor(n_estimators=120,learning_rate=.035,max_depth=2,min_samples_leaf=8,loss='huber',random_state=20260813);m.fit(M(tr,emp),tr.SWD_obs);return m.predict(M(te,emp)),m
rng=np.random.default_rng(20260813);R={};rows=[]
for ty,vy in [(2012,2013),(2013,2012)]:
 tr=B[B.Year==ty].copy();te=B[B.Year==vy].copy();best=tune(tr);ph,gate,hm=resfit(tr,te,best[1],best[2]);pa,am=aifit(tr,te);y=te.SWD_obs.values;pp=te.SWD_AC.values;key=f'{ty}->{vy}';R[key]={'selected_shrink':best[1],'selected_OOD_quantile':best[2],'inner_LOTO':best[3],'AquaCrop':met(y,pp),'AI_only':met(y,pa),'AquaCrop_AI_gated':met(y,ph),'median_gate':float(np.median(gate)),'gate_below_0.5':float(np.mean(gate<.5)),'hybrid_feature_importance':dict(sorted(zip(hyb,hm.feature_importances_),key=lambda q:q[1],reverse=True))}
 R[key]['RMSE_reduction_pct']=100*(R[key]['AquaCrop']['RMSE']-R[key]['AquaCrop_AI_gated']['RMSE'])/R[key]['AquaCrop']['RMSE'];boots=[];trts=sorted(te.Trt_code.unique())
 for _ in range(1500):
  ss=rng.choice(trts,len(trts),replace=True);ix=np.concatenate([np.where(te.Trt_code.values==t)[0] for t in ss]);rp=np.sqrt(mean_squared_error(y[ix],pp[ix]));rh=np.sqrt(mean_squared_error(y[ix],ph[ix]));boots.append(100*(rp-rh)/rp)
 R[key]['RMSE_reduction_bootstrap95']=[float(np.quantile(boots,.025)),float(np.quantile(boots,.975))];per={}
 for t in trts:
  ix=np.where(te.Trt_code.values==t)[0];mp=met(y[ix],pp[ix]);mh=met(y[ix],ph[ix]);per[str(int(t))]=100*(mp['RMSE']-mh['RMSE'])/mp['RMSE']
 R[key]['per_treatment_RMSE_reduction_pct']=per;R[key]['treatments_improved']=int(sum(v>0 for v in per.values()))
 for i,r in te.reset_index(drop=True).iterrows():rows.append([key,int(r.Year),int(r.Trt_code),r.Date.date().isoformat(),r.SWD_obs,pp[i],pa[i],ph[i],gate[i]])
# management transfer with fixed settings (not tuned on pooled test treatments)
y=[];p=[];h=[]
for hold in sorted(B.Trt_code.unique()):
 tr=B[B.Trt_code!=hold];te=B[B.Trt_code==hold];ph,_,_=resfit(tr,te,.5,.5);y+=list(te.SWD_obs);p+=list(te.SWD_AC);h+=list(ph)
R['pooled_unseen_treatment']={'AquaCrop':met(y,p),'AquaCrop_AI_gated':met(y,h)};R['pooled_unseen_treatment']['RMSE_reduction_pct']=100*(R['pooled_unseen_treatment']['AquaCrop']['RMSE']-R['pooled_unseen_treatment']['AquaCrop_AI_gated']['RMSE'])/R['pooled_unseen_treatment']['AquaCrop']['RMSE']
pd.DataFrame(rows,columns=['fold','Year','Trt_code','Date','SWD_obs','AquaCrop','AI_only','AquaCrop_AI_gated','OOD_gate']).to_csv(OUT+'/blind_predictions.csv',index=False)
with open(OUT+'/metrics.json','w') as f:json.dump(R,f,indent=2)
print(json.dumps(R,indent=2));print('HYBRID_V2_COMPLETE')
