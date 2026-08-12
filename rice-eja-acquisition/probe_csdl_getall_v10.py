from __future__ import annotations
import urllib.parse, urllib.request, json, os, re
from pathlib import Path

DS='cbd2c393a5ad4056a1bd9130ca1340f6'; VER='V2'
OUT=Path('rice-eja-acquisition/csdl-getall-v10'); OUT.mkdir(parents=True,exist_ok=True)
UA={'User-Agent':'Mozilla/5.0','Referer':'https://www.scidb.cn/en/s/ZZJzAz','Accept':'*/*'}

def get(url, limit=5_000_000):
    req=urllib.request.Request(url,headers=UA)
    try:
        with urllib.request.urlopen(req,timeout=90) as r:
            body=r.read(limit)
            return {'ok':True,'status':r.status,'final_url':r.geturl(),'headers':dict(r.headers),'body':body.decode('utf-8','replace')}
    except Exception as e:
        return {'ok':False,'error':repr(e),'url':url}

variants=[]
for typ in [None,'dataset','dataSet','DataSet','1','0']:
    q={'dataSetId':DS,'version':VER,'global':'Shanghai'}
    if typ is not None:q['type']=typ
    url='https://www.scidb.cn/api/sdb-filetree-service/getAllUrl?'+urllib.parse.urlencode(q)
    x=get(url)
    x['type_variant']=typ
    variants.append(x)
    if x.get('ok'):
        fn='getall_'+('none' if typ is None else re.sub(r'[^A-Za-z0-9]+','_',typ))+'.txt'
        (OUT/fn).write_text(x.get('body',''),encoding='utf-8')

zipurl=f'https://china.scidb.cn/getZipFile?dataSetId={DS}&version={VER}'
z=get(zipurl,limit=200_000)
if z.get('ok'):(OUT/'getzip_probe_body.txt').write_text(z.get('body',''),encoding='utf-8')

summary={'getAllUrl_variants':[{k:v for k,v in x.items() if k!='body'}|{'body_head':x.get('body','')[:1000]} for x in variants], 'getZipFile':{k:v for k,v in z.items() if k!='body'}|{'body_head':z.get('body','')[:1000]}}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')

# Mine any returned URLs and filenames relevant to the target 1-km properties.
text='\n'.join(x.get('body','') for x in variants if x.get('ok'))
urls=re.findall(r'https?://[^\s"\'<>]+',text)
keywords=('1km','clay','sand','silt','bd_','bulk','soc','cec','ph_','por','tn_','nitrogen')
sel=[u for u in urls if any(k.lower() in u.lower() for k in keywords)]
(OUT/'selected_urls.txt').write_text('\n'.join(dict.fromkeys(sel)),encoding='utf-8')
print(json.dumps(summary,indent=2,ensure_ascii=False))
print('selected_urls',len(sel))
