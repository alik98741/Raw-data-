from __future__ import annotations
import io,json,re,unicodedata
from pathlib import Path
import requests,pandas as pd,numpy as np
OUT=Path('sugarcane-industrial-algorithms/state-industrial-fast-v1');OUT.mkdir(parents=True,exist_ok=True)
H={'User-Agent':'Sugarcane-Industrial-Algorithms/fast-state-v1'}
def get(u):
 r=requests.get(u,timeout=180,headers=H);r.raise_for_status();return r
def norm(s):
 s=unicodedata.normalize('NFKD',str(s)).encode('ascii','ignore').decode('ascii').upper().strip();return re.sub(r'\s+',' ',s)
def num(x):
 s=str(x or '').strip()
 if s in ('','-','...','..','X'):return np.nan
 if ',' in s and '.' not in s:s=s.replace(',','.')
 elif ',' in s and '.' in s:s=s.replace('.','').replace(',','.')
 try:return float(s)
 except:return np.nan
# All available state-years in one compact official SIDRA request.
u='https://apisidra.ibge.gov.br/values/t/5457/n3/all/v/216,214,112/p/all/c782/40106'
d=get(u).json();f=pd.DataFrame(d[1:]);f=f[['D1C','D1N','D2C','D2N','D3C','V','MN']];f.columns=['state_code','state_name','variable_code','variable_name','year','value_raw','unit'];f['year']=pd.to_numeric(f.year,errors='coerce');f=f[f.year.between(1985,2024)].copy();f['value']=f.value_raw.map(num)
# hard identity checks
ids=f[['variable_code','variable_name','unit']].drop_duplicates(); exp={'216':'AREA COLHIDA','214':'QUANTIDADE PRODUZIDA','112':'RENDIMENTO MEDIO DA PRODUCAO'}
for c,w in exp.items():
 vals=ids.loc[ids.variable_code.astype(str)==c,'variable_name'].map(norm).unique().tolist()
 if not vals or not vals[0].startswith(w):raise RuntimeError(f'SIDRA variable identity fail {c}: {vals}')
code={'216':'harvested_area_ha','214':'production_t','112':'yield_reported_kg_ha'};f['metric']=f.variable_code.astype(str).map(code);p=f.pivot_table(index=['state_code','state_name','year'],columns='metric',values='value',aggfunc='first').reset_index();p['yield_calc_t_ha']=p.production_t/p.harvested_area_ha;p['yield_reported_t_ha']=p.yield_reported_kg_ha/1000;p['yield_abs_diff']=abs(p.yield_calc_t_ha-p.yield_reported_t_ha)
if np.nanmedian(p.yield_abs_diff)>1:raise RuntimeError('Yield identity QC fail '+str(np.nanmedian(p.yield_abs_diff)))
# UF acronym official lookup
ufs=get('https://servicodados.ibge.gov.br/api/v1/localidades/estados').json();um={str(x['id']):(x['sigla'],x['nome']) for x in ufs};p['state_abbr']=p.state_code.astype(str).map(lambda x:um.get(x,('',''))[0]);p.to_csv(OUT/'IBGE_sugarcane_state_year_1985_2024.csv',index=False)
n=p.groupby('year',as_index=False).agg(harvested_area_ha=('harvested_area_ha','sum'),production_t=('production_t','sum'));n['yield_t_ha']=n.production_t/n.harvested_area_ha;n.to_csv(OUT/'IBGE_sugarcane_national_year_1985_2024.csv',index=False)
# ANP observed ethanol
base='https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/arquivos-producao-de-biocombustiveis/producao-etanol-anidro-hidratado-m3-2012-2026.csv';raw=None;used=None
for x in [base+'/@@download/file',base,base+'/view']:
 try:
  r=get(x);b=r.content
  if b'ANO' in b[:1500] and b';' in b[:1500]:raw=b;used=r.url;break
 except Exception:pass
if raw is None:raise RuntimeError('ANP CSV retrieval failed')
a=pd.read_csv(io.BytesIO(raw),sep=';',encoding='utf-8-sig',decimal=',');a.columns=[norm(c).replace(' ','_') for c in a.columns]
for c in ['ANO','UNIDADE_DA_FEDERACAO','PRODUTO','PRODUCAO']:
 if c not in a:raise RuntimeError('ANP missing '+c+' cols='+str(list(a)))
a['ANO']=pd.to_numeric(a.ANO,errors='coerce');a['PRODUCAO']=pd.to_numeric(a.PRODUCAO,errors='coerce');a=a[a.ANO.between(2012,2024)].copy();a['state_norm']=a.UNIDADE_DA_FEDERACAO.map(norm);aa=a.groupby(['ANO','state_norm'],as_index=False).agg(ethanol_m3=('PRODUCAO','sum'));aa.columns=['year','state_norm','ethanol_m3'];names=p[['state_abbr','state_name']].drop_duplicates();names['state_norm']=names.state_name.map(norm);aa=aa.merge(names,on='state_norm',how='left');aa.to_csv(OUT/'ANP_ethanol_state_year_2012_2024.csv',index=False);aa.groupby('year',as_index=False).ethanol_m3.sum().to_csv(OUT/'ANP_ethanol_national_year_2012_2024.csv',index=False)
m=p.merge(aa[['year','state_abbr','ethanol_m3']],on=['year','state_abbr'],how='inner');m=m[(m.production_t>0)&(m.ethanol_m3>=0)].copy();m['ethanol_allocation_L_per_t_total_cane']=1000*m.ethanol_m3/m.production_t;m.to_csv(OUT/'IBGE_ANP_state_year_2012_2024.csv',index=False)
qc={'status':'PASS','sidra_source':u,'sidra_variable_identity':ids.to_dict('records'),'state_year_rows':len(p),'states':p.state_abbr.nunique(),'years':[int(p.year.min()),int(p.year.max())],'median_yield_identity_diff_t_ha':float(np.nanmedian(p.yield_abs_diff)),'anp_source':used,'anp_state_year_rows':len(aa),'merged_rows':len(m)};(OUT/'STATE_INDUSTRIAL_QC.json').write_text(json.dumps(qc,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(qc,indent=2,ensure_ascii=False))