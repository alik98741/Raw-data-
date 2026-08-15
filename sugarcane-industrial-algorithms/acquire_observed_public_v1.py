from __future__ import annotations
import io, json, re, time, unicodedata
from pathlib import Path
import requests
import pandas as pd
import numpy as np

OUT=Path('sugarcane-industrial-algorithms/observed-public-v1')
OUT.mkdir(parents=True, exist_ok=True)
S=requests.Session(); S.headers.update({'User-Agent':'Sugarcane-Industrial-Algorithms/1.0 (research data acquisition)'})

def get(url, timeout=120, retries=5):
    last=None
    for k in range(retries):
        try:
            r=S.get(url, timeout=timeout, allow_redirects=True)
            r.raise_for_status(); return r
        except Exception as e:
            last=e; time.sleep(2**k)
    raise last

def clean_num(x):
    if x is None: return np.nan
    s=str(x).strip().replace('\xa0','')
    if s in ('','-','...','..','X'): return np.nan
    if ',' in s and '.' not in s: s=s.replace(',','.')
    elif ',' in s and '.' in s: s=s.replace('.','').replace(',','.')
    try: return float(s)
    except: return np.nan

def norm(s):
    s=unicodedata.normalize('NFKD',str(s)).encode('ascii','ignore').decode('ascii').upper().strip()
    return re.sub(r'\s+',' ',s)

# ---------------- IBGE PAM / SIDRA Table 5457 ----------------
# c782/40106 = Cana-de-acucar. Variable identity is decoded from the official
# D2N names returned by SIDRA, never from remembered numeric variable IDs.
frames=[]; diagnostics=[]
for year in range(1985,2025):
    url=f'https://apisidra.ibge.gov.br/values/t/5457/n6/all/v/allxp/p/{year}/c782/40106'
    r=get(url)
    data=r.json()
    if not isinstance(data,list) or len(data)<2:
        raise RuntimeError(f'IBGE returned no data for {year}: {str(data)[:300]}')
    hdr=data[0]; rows=data[1:]
    df=pd.DataFrame(rows)
    required=['D1C','D1N','D2C','D2N','D3C','V']
    miss=[c for c in required if c not in df]
    if miss:
        raise RuntimeError(f'Unexpected SIDRA schema for {year}; missing={miss}; columns={df.columns.tolist()}; header={hdr}')
    df=df[['D1C','D1N','D2C','D2N','D3C','V']].copy()
    df.columns=['municipality_code','municipality_name','variable_code','variable_name','year','value_raw']
    df['year']=pd.to_numeric(df['year'],errors='coerce').astype('Int64')
    df['value']=df.value_raw.map(clean_num)
    frames.append(df)
    diagnostics.append({'year':year,'rows':len(df),'municipalities':df.municipality_code.nunique(),
                        'variables':df[['variable_code','variable_name']].drop_duplicates().to_dict('records')})
    print('IBGE',year,len(df),flush=True)
long=pd.concat(frames,ignore_index=True)
long.to_csv(OUT/'IBGE_PAM_5457_sugarcane_long_1985_2024.csv',index=False)

# Decode variables using official names, robust to SIDRA numeric-code revisions/assumptions.
def metric_from_name(x):
    n=norm(x)
    if 'PERCENTUAL' in n: return None
    if n.startswith('QUANTIDADE PRODUZIDA'): return 'production_t'
    if n.startswith('AREA COLHIDA'): return 'harvested_area_ha'
    if n.startswith('RENDIMENTO MEDIO DA PRODUCAO'): return 'yield_reported'
    return None
long['metric']=long.variable_name.map(metric_from_name)
selected=long[long.metric.notna()].copy()
found=set(selected.metric.unique())
expected={'production_t','harvested_area_ha','yield_reported'}
if found!=expected:
    raise RuntimeError('Could not identify required SIDRA variables from official names. Found='+str(found)+'; names='+str(long[['variable_code','variable_name']].drop_duplicates().to_dict('records')))
panel=selected.pivot_table(index=['municipality_code','municipality_name','year'],columns='metric',values='value',aggfunc='first').reset_index()
panel['yield_calc_t_ha']=panel['production_t']/panel['harvested_area_ha']
# SIDRA reports average yield for sugarcane in kg/ha; infer/check scale against physical production/area relation.
ratio=panel['yield_reported']/panel['yield_calc_t_ha']
med_ratio=np.nanmedian(ratio.replace([np.inf,-np.inf],np.nan))
yield_scale=1000.0 if 500 < med_ratio < 1500 else 1.0
panel['yield_reported_t_ha']=panel['yield_reported']/yield_scale
panel['yield_abs_diff']=abs(panel['yield_calc_t_ha']-panel['yield_reported_t_ha'])
if np.nanmedian(panel['yield_abs_diff'])>1.0:
    raise RuntimeError(f'IBGE yield identity QC failed: median absolute production/area vs reported-yield difference={np.nanmedian(panel.yield_abs_diff):.3f} t/ha')

# Official municipality -> state crosswalk.
loc=get('https://servicodados.ibge.gov.br/api/v1/localidades/municipios').json()
locrows=[]
for m in loc:
    uf=m.get('microrregiao',{}).get('mesorregiao',{}).get('UF',{})
    if not uf:
        uf=m.get('regiao-imediata',{}).get('regiao-intermediaria',{}).get('UF',{})
    locrows.append({'municipality_code':str(m['id']),'state_code':str(uf.get('id','')),'state_abbr':uf.get('sigla',''),'state_name':uf.get('nome','')})
locdf=pd.DataFrame(locrows).drop_duplicates('municipality_code')
panel['municipality_code']=panel.municipality_code.astype(str)
panel=panel.merge(locdf,on='municipality_code',how='left',validate='many_to_one')
if panel.state_abbr.isna().mean()>0.001:
    raise RuntimeError(f'IBGE locality crosswalk missing rate too high: {panel.state_abbr.isna().mean()}')
panel.to_csv(OUT/'IBGE_sugarcane_municipality_year_1985_2024.csv',index=False)

state=(panel.groupby(['state_code','state_abbr','state_name','year'],as_index=False)
       .agg(harvested_area_ha=('harvested_area_ha','sum'),production_t=('production_t','sum')))
state['yield_t_ha']=state.production_t/state.harvested_area_ha
state.to_csv(OUT/'IBGE_sugarcane_state_year_1985_2024.csv',index=False)
national=state.groupby('year',as_index=False).agg(harvested_area_ha=('harvested_area_ha','sum'),production_t=('production_t','sum'))
national['yield_t_ha']=national.production_t/national.harvested_area_ha
national.to_csv(OUT/'IBGE_sugarcane_national_year_1985_2024.csv',index=False)

# ---------------- ANP observed ethanol ----------------
base='https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/arquivos-producao-de-biocombustiveis/producao-etanol-anidro-hidratado-m3-2012-2026.csv'
candidates=[base+'/@@download/file',base,base+'/view']
raw=None; used=None
for u in candidates:
    try:
        rr=get(u); b=rr.content
        if b'ANO' in b[:1000] and b';' in b[:1000]: raw=b; used=rr.url; break
    except Exception: pass
if raw is None: raise RuntimeError('Could not retrieve ANP ethanol CSV from official source')
(OUT/'ANP_ethanol_2012_2026_raw.csv').write_bytes(raw)
anp=pd.read_csv(io.BytesIO(raw),sep=';',encoding='utf-8-sig',decimal=',')
anp.columns=[norm(c).replace(' ','_') for c in anp.columns]
req=['ANO','UNIDADE_DA_FEDERACAO','PRODUTO','PRODUCAO']
if any(c not in anp for c in req): raise RuntimeError('Unexpected ANP columns: '+str(anp.columns.tolist()))
anp['ANO']=pd.to_numeric(anp.ANO,errors='coerce')
anp['PRODUCAO']=pd.to_numeric(anp.PRODUCAO,errors='coerce')
anp=anp[(anp.ANO>=2012)&(anp.ANO<=2024)].copy()
anp['state_norm']=anp.UNIDADE_DA_FEDERACAO.map(norm)
anp_state=anp.groupby(['ANO','state_norm'],as_index=False).agg(ethanol_m3=('PRODUCAO','sum'))
anp_state.columns=['year','state_norm','ethanol_m3']
states=state[['state_abbr','state_name']].drop_duplicates().copy(); states['state_norm']=states.state_name.map(norm)
anp_state=anp_state.merge(states,on='state_norm',how='left')
anp_state.to_csv(OUT/'ANP_ethanol_state_year_2012_2024.csv',index=False)
anp_nat=anp_state.groupby('year',as_index=False).agg(ethanol_m3=('ethanol_m3','sum'))
anp_nat.to_csv(OUT/'ANP_ethanol_national_year_2012_2024.csv',index=False)

# ---------------- Industrial merged evidence ----------------
merged=state.merge(anp_state[['year','state_abbr','ethanol_m3']],on=['year','state_abbr'],how='inner')
merged=merged[(merged.production_t>0)&(merged.ethanol_m3>=0)].copy()
# Observed allocation intensity: NOT a biochemical conversion coefficient because cane is split among sugar/ethanol uses.
merged['ethanol_allocation_L_per_t_total_cane']=1000*merged.ethanol_m3/merged.production_t
merged.to_csv(OUT/'IBGE_ANP_state_year_2012_2024.csv',index=False)

qc={
 'ibge_years':[int(panel.year.min()),int(panel.year.max())],
 'ibge_rows':int(len(panel)),
 'ibge_municipalities':int(panel.municipality_code.nunique()),
 'ibge_states':int(panel.state_abbr.nunique()),
 'sidra_variable_identity':selected[['variable_code','variable_name','metric']].drop_duplicates().to_dict('records'),
 'ibge_missing_production':int(panel.production_t.isna().sum()),
 'ibge_missing_area':int(panel.harvested_area_ha.isna().sum()),
 'ibge_yield_report_scale_divisor':yield_scale,
 'ibge_median_abs_yield_qc_diff_t_ha':float(np.nanmedian(panel.yield_abs_diff)),
 'anp_source_url_resolved':used,
 'anp_years':[int(anp_state.year.min()),int(anp_state.year.max())],
 'anp_state_year_rows':int(len(anp_state)),
 'merged_state_year_rows':int(len(merged)),
 'status':'PASS'
}
(OUT/'OBSERVED_ACQUISITION_QC.json').write_text(json.dumps(qc,indent=2,ensure_ascii=False),encoding='utf-8')
(OUT/'IBGE_YEAR_DIAGNOSTICS.json').write_text(json.dumps(diagnostics,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(qc,indent=2,ensure_ascii=False))
