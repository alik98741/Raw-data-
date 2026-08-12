from __future__ import annotations
import urllib.request,json,re
from pathlib import Path
OUT=Path('rice-eja-acquisition/agera5-timeseries-v2-probe-v10');OUT.mkdir(parents=True,exist_ok=True)
COL='sis-agrometeorological-indicators-timeseries'
H={'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*'}
def get(url,limit=20_000_000):
 req=urllib.request.Request(url,headers=H)
 with urllib.request.urlopen(req,timeout=90) as r:return r.read(limit).decode('utf-8','replace'),r.geturl(),dict(r.headers)
base=f'https://cds.climate.copernicus.eu/api/catalogue/v1/collections/{COL}'
raw,u,h=get(base); coll=json.loads(raw);(OUT/'collection.json').write_text(raw,encoding='utf-8')
res={}
for rel in ['form','constraints','layout']:
 links=[x for x in coll.get('links',[]) if x.get('rel')==rel]
 if links:
  try:
   r,fu,hh=get(links[0]['href']);(OUT/f'{rel}.json').write_text(r,encoding='utf-8');res[rel]={'ok':True,'url':fu,'bytes':len(r)}
  except Exception as e:res[rel]={'error':repr(e),'url':links[0]['href']}
for name,url in [('retrieve_process',f'https://cds.climate.copernicus.eu/api/retrieve/v1/processes/{COL}'),('costing',f'https://cds.climate.copernicus.eu/api/retrieve/v1/processes/{COL}/costing')]:
 try:
  r,fu,hh=get(url);(OUT/f'{name}.json').write_text(r,encoding='utf-8');res[name]={'ok':True,'url':fu,'bytes':len(r),'head':r[:3000]}
 except Exception as e:res[name]={'error':repr(e),'url':url}
# Mine all fetched text for zarr/object-store/s3/arco URLs or paths.
text='\n'.join(p.read_text(errors='ignore') for p in OUT.glob('*.json'))
patterns=['zarr','arco','s3','object-store','bucket','endpoint','url','store','mapper','fsspec']
hits={}
for pat in patterns:
 vals=[]
 for m in re.finditer(pat,text,re.I):vals.append(text[max(0,m.start()-300):m.start()+800])
 hits[pat]=vals[:100]
(OUT/'arco_keyword_contexts.json').write_text(json.dumps(hits,indent=2,ensure_ascii=False),encoding='utf-8')
urls=sorted(set(re.findall(r'https?://[^\s"\'<>]+',text)))
(OUT/'all_urls_found.txt').write_text('\n'.join(urls),encoding='utf-8')
print(json.dumps(res,indent=2,ensure_ascii=False))
print('urls',len(urls),'zarr_hits',len(hits['zarr']),'arco_hits',len(hits['arco']))
