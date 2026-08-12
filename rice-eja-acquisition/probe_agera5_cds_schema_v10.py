from __future__ import annotations
import urllib.request,json,re
from pathlib import Path
OUT=Path('rice-eja-acquisition/agera5-schema-v10'); OUT.mkdir(parents=True,exist_ok=True)
BASE='https://cds.climate.copernicus.eu/api/catalogue/v1/collections/sis-agrometeorological-indicators'
H={'User-Agent':'Mozilla/5.0','Accept':'application/json'}
res={}
for name,suffix in [('collection',''),('form','/form.json'),('constraints','/constraints.json')]:
    url=BASE+suffix
    try:
        req=urllib.request.Request(url,headers=H)
        with urllib.request.urlopen(req,timeout=90) as r:
            raw=r.read().decode('utf-8','replace'); res[name]={'status':r.status,'url':r.geturl(),'content_type':r.headers.get('content-type')}
            (OUT/f'{name}.json').write_text(raw,encoding='utf-8')
            try: res[name]['json']=json.loads(raw)
            except: res[name]['head']=raw[:5000]
    except Exception as e: res[name]={'error':repr(e),'url':url}
# Compact extraction of option labels/values from form JSON.
form=res.get('form',{}).get('json')
opts=[]
def walk(x,path=''):
    if isinstance(x,dict):
        if any(k in x for k in ('name','label','id')) and any(k in x for k in ('values','options','choices','details')):
            opts.append({'path':path,**{k:x.get(k) for k in ['name','label','id','type','values','options','choices'] if k in x}})
        for k,v in x.items(): walk(v,path+'/'+str(k))
    elif isinstance(x,list):
        for i,v in enumerate(x): walk(v,path+f'[{i}]')
if form is not None: walk(form)
(OUT/'form_options_compact.json').write_text(json.dumps(opts,indent=2,ensure_ascii=False),encoding='utf-8')
# Extract likely enum values from both artifacts for our variables.
text=json.dumps(res,ensure_ascii=False)
keywords=['2m_temperature','temperature','precipitation','solar','vapour','vapor','reference_evapotranspiration','evapotranspiration','version','statistic','daily','minimum','maximum','mean']
hits={k:sorted(set(re.findall(r'[^"\\]{0,80}'+re.escape(k)+r'[^"\\]{0,160}',text,re.I)))[:200] for k in keywords}
(OUT/'keyword_contexts.json').write_text(json.dumps(hits,indent=2,ensure_ascii=False),encoding='utf-8')
# Do not dump giant JSON into log; only statuses.
print(json.dumps({k:{x:y for x,y in v.items() if x!='json'} for k,v in res.items()},indent=2))
print('compact_option_blocks',len(opts))
