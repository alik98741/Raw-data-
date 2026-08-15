from __future__ import annotations
import io,json,re,time,unicodedata
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import requests,pandas as pd,numpy as np
OUT=Path('sugarcane-industrial-algorithms/observed-public-v2'); OUT.mkdir(parents=True,exist_ok=True)

def norm(s):
 s=unicodedata.normalize('NFKD',str(s)).encode('ascii','ignore').decode('ascii').upper().strip(); return re.sub(r'\s+',' ',s)
def num(x):
 s=str(x or '').strip();
 if s in ('','-','...','..','X'): return np.nan
 if ',' in s and '.' not in s:s=s.replace(',','.')
 elif ',' in s and '.' in s:s=s.replace('.','').replace(',','.')
 try:return float(s)
 except:return np.nan
def get(url,retries=5):
 last=None
 for k in range(retries):
  try:
   r=requests.get(url,timeout=120,headers={'User-Agent':'Sugarcane-Industrial-Algorithms/2.0'}); r.raise_for_status(); return r
  except Exception as e:last=e; time.sleep(2**k)
 raise last

def one_year(y):
 # IDs verified by an independent Table 5457 national probe on 2026-08-15:
 # 216 Area colhida; 214 Quantidade produzida; 112 Rendimento medio da producao.
 u=f'https://apisidra.ibge.gov.br/values/t/5457/n6/all/v/216,214,112/p/{y}/c782/40106'
 d=get(u).json();
 if not isinstance(d,list) or len(d)<2: raise RuntimeError(f'No SIDRA rows {y}: {str(d)[:200]}')
 f=pd.DataFrame(d[1:])
 need=['D1C','D1N','D2C','D2N','D3C','V','MN']; miss=[c for c in need if c not in f]
 if miss: raise RuntimeError(f'SIDRA schema {y} missing {miss}; cols={list(f)}')
 f=f[need].copy(); f.columns=['municipality_code','municipality_name','variable_code','variable_name','year','value_raw','unit']
 f['value']=f.value_raw.map(num); f['year']=y
 ids=dict(zip(f.variable_code.astype(str),f.variable_name))
 exp={'216':'Área colhida','214':'Quantidade produzida','112':'Rendimento médio da produção'}
 for c,n in exp.items():
  got=norm(ids.get(c,'')); want=norm(n)
  if not got.startswith(want): raise RuntimeError(f'Variable identity failure {y}: {c}={ids.get(c)} expected {n}')
 return f

frames=[]
with ThreadPoolExecutor(max_workers=4) as ex:
 fut={ex.submit(one_year,y):y for y in range(1985,2025)}
 for q in as_completed(fut):
  y=fut[q]; f=q.result(); frames.append(f); print('IBGE',y,len(f),flush=True)
long=pd.concat(frames,ignore_index=True).sort_values(['year','municipality_code','variable_code'])
long.to_csv(OUT/'IBGE_PAM_5457_sugarcane_long_1985_2024.csv',index=False)
code={'216':'harvested_area_ha','214':'production_t','112':'yield_reported_kg_ha'}; long['metric']=long.variable_code.astype(str).map(code)
p=long.pivot_table(index=['municipality_code','municipality_name','year'],columns='metric',values='value',aggfunc='first').reset_index()
p['yield_calc_t_ha']=p.production_t/p.harvested_area_ha; p['yield_reported_t_ha']=p.yield_reported_kg_ha/1000; p['yield_abs_diff']=abs(p.yield_calc_t_ha-p.yield_reported_t_ha)
if np.nanmedian(p.yield_abs_diff)>1.0: raise RuntimeError('Yield identity QC failed: '+str(np.nanmedian(p.yield_abs_diff)))
# Parse UF from SIDRA municipality label first; current-locality lookup only as fallback.
def parse_uf(s):
 t=str(s); m=re.search(r'(?:\s-\s|\()([A-Z]{2})\)?$',t); return m.group(1) if m else None
p['state_abbr']=p.municipality_name.map(parse_uf)
if p.state_abbr.isna().any():
 loc=get('https://servicodados.ibge.gov.br/api/v1/localidades/municipios').json(); x=[]
 for m in loc:
  uf=m.get('microrregiao',{}).get('mesorregiao',{}).get('UF',{}) or m.get('regiao-imediata',{}).get('regiao-intermediaria',{}).get('UF',{})
  x.append((str(m['id']),uf.get('sigla',''),uf.get('nome','')))
 lx=pd.DataFrame(x,columns=['municipality_code','uf_fallback','state_name']); p.municipality_code=p.municipality_code.astype(str); p=p.merge(lx,on='municipality_code',how='left'); p['state_abbr']=p.state_abbr.fillna(p.uf_fallback)
else:p['state_name']=''
# official state-name lookup from locality API for all UFs
ufs=get('https://servicodados.ibge.gov.br/api/v1/localidades/estados').json(); um={x['sigla']:x['nome'] for x in ufs}; p['state_name']=p.state_abbr.map(um)
miss=float(p.state_abbr.isna().mean());
if miss>0.002: raise RuntimeError(f'State resolution missing rate {miss}')
p.to_csv(OUT/'IBGE_sugarcane_municipality_year_1985_2024.csv',index=False)
s=(p.groupby(['state_abbr','state_name','year'],as_index=False).agg(harvested_area_ha=('harvested_area_ha','sum'),production_t=('production_t','sum'))); s['yield_t_ha']=s.production_t/s.harvested_area_ha; s.to_csv(OUT/'IBGE_sugarcane_state_year_1985_2024.csv',index=False)
n=s.groupby('year',as_index=False).agg(harvested_area_ha=('harvested_area_ha','sum'),production_t=('production_t','sum')); n['yield_t_ha']=n.production_t/n.harvested_area_ha; n.to_csv(OUT/'IBGE_sugarcane_national_year_1985_2024.csv',index=False)
# ANP official ethanol file
base='https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/arquivos-producao-de-biocombustiveis/producao-etanol-anidro-hidratado-m3-2012-2026.csv'; raw=None; used=None
for u in [base+'/@@download/file',base,base+'/view']:
 try:
  r=get(u); b=r.content
  if b'ANO' in b[:1000] and b';' in b[:1000]:raw=b;used=r.url;break
 except:pass
if raw is None:raise RuntimeError('ANP official CSV retrieval failed')
(OUT/'ANP_ethanol_2012_2026_raw.csv').write_bytes(raw)
a=pd.read_csv(io.BytesIO(raw),sep=';',encoding='utf-8-sig',decimal=','); a.columns=[norm(c).replace(' ','_') for c in a.columns]; a['ANO']=pd.to_numeric(a.ANO,errors='coerce'); a['PRODUCAO']=pd.to_numeric(a.PRODUCAO,errors='coerce'); a=a[a.ANO.between(2012,2024)].copy(); a['state_norm']=a.UNIDADE_DA_FEDERACAO.map(norm)
as_=a.groupby(['ANO','state_norm'],as_index=False).agg(ethanol_m3=('PRODUCAO','sum')); as_.columns=['year','state_norm','ethanol_m3']; st=s[['state_abbr','state_name']].drop_duplicates(); st['state_norm']=st.state_name.map(norm); as_=as_.merge(st,on='state_norm',how='left'); as_.to_csv(OUT/'ANP_ethanol_state_year_2012_2024.csv',index=False); as_.groupby('year',as_index=False).ethanol_m3.sum().to_csv(OUT/'ANP_ethanol_national_year_2012_2024.csv',index=False)
m=s.merge(as_[['year','state_abbr','ethanol_m3']],on=['year','state_abbr'],how='inner'); m=m[(m.production_t>0)&(m.ethanol_m3>=0)].copy(); m['ethanol_allocation_L_per_t_total_cane']=1000*m.ethanol_m3/m.production_t; m.to_csv(OUT/'IBGE_ANP_state_year_2012_2024.csv',index=False)
qc={'status':'PASS','ibge_years':[int(p.year.min()),int(p.year.max())],'ibge_rows':int(len(p)),'ibge_municipalities':int(p.municipality_code.nunique()),'ibge_states':int(p.state_abbr.nunique()),'sidra_variable_identity':long[['variable_code','variable_name','unit']].drop_duplicates().to_dict('records'),'median_yield_identity_diff_t_ha':float(np.nanmedian(p.yield_abs_diff)),'anp_source_url':used,'anp_years':[int(as_.year.min()),int(as_.year.max())],'merged_state_year_rows':int(len(m))}
(OUT/'OBSERVED_ACQUISITION_QC.json').write_text(json.dumps(qc,indent=2,ensure_ascii=False),encoding='utf-8'); print(json.dumps(qc,indent=2,ensure_ascii=False),flush=True)
