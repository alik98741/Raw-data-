import re,json,urllib.request,urllib.parse
from pathlib import Path
OUT=Path('rice-eja-acquisition/csdl-probe');OUT.mkdir(parents=True,exist_ok=True)
UA={'User-Agent':'Mozilla/5.0'}
urls={
'sciencedb':'https://www.scidb.cn/en/detail?dataSetId=4c2cc9d9fd1b4f70b30853aef5b57d20',
'tpdc':'https://data.tpdc.ac.cn/en/data/9ca9c82e-8b5f-4ea9-b1ea-ec706061ae70',
'sciencedb_cn':'https://www.scidb.cn/detail?dataSetId=4c2cc9d9fd1b4f70b30853aef5b57d20'
}
summary={}
for key,url in urls.items():
    try:
        req=urllib.request.Request(url,headers=UA)
        with urllib.request.urlopen(req,timeout=90) as r:
            raw=r.read(6_000_000); final=r.geturl();headers=dict(r.headers)
        text=raw.decode('utf-8','replace')
        (OUT/f'{key}.html').write_text(text,encoding='utf-8')
        # pull candidate URLs/endpoints, DOI, dataset IDs, archives and file names
        candidates=set()
        for m in re.findall(r'https?://[^\"\'<>\\\s]+',text):
            if any(x in m.lower() for x in ['api','download','file','dataset','data','scidb','tpdc','.zip','.rar','.tif','.tiff','.nc']): candidates.add(m[:1000])
        for m in re.findall(r'[\"\']([^\"\']*(?:api|download|file|data)[^\"\']*)[\"\']',text,re.I):
            if len(m)<1000: candidates.add(m)
        scripts=re.findall(r'<script[^>]+src=[\"\']([^\"\']+)',text,re.I)
        links=re.findall(r'<a[^>]+href=[\"\']([^\"\']+)',text,re.I)
        summary[key]={'final_url':final,'bytes_read':len(raw),'content_type':headers.get('Content-Type'),'candidate_count':len(candidates),'script_count':len(scripts),'link_count':len(links)}
        (OUT/f'{key}_candidates.txt').write_text('\n'.join(sorted(candidates)),encoding='utf-8')
        (OUT/f'{key}_scripts.txt').write_text('\n'.join(scripts),encoding='utf-8')
        (OUT/f'{key}_links.txt').write_text('\n'.join(links),encoding='utf-8')
        # download JS bundles on same host and grep dataset id / download APIs, capped
        base=urllib.parse.urlsplit(final)
        js_hits=[]
        for s in scripts[:40]:
            su=urllib.parse.urljoin(final,s)
            try:
                rq=urllib.request.Request(su,headers=UA)
                with urllib.request.urlopen(rq,timeout=45) as rr: b=rr.read(8_000_000)
                st=b.decode('utf-8','replace')
                if ('dataSetId' in st or 'download' in st.lower() or '4c2cc9d9' in st):
                    for pat in [r'https?://[^\"\'<>\\\s]{1,600}',r'[\"\']([^\"\']*(?:download|dataset|file)[^\"\']*)[\"\']']:
                        for x in re.findall(pat,st,re.I):
                            if isinstance(x,tuple): x=x[0]
                            if any(q in x.lower() for q in ['download','dataset','file','api','scidb','tpdc']):js_hits.append(x[:1000])
            except Exception: pass
        (OUT/f'{key}_js_hits.txt').write_text('\n'.join(sorted(set(js_hits))),encoding='utf-8')
        summary[key]['js_hits']=len(set(js_hits))
    except Exception as e: summary[key]={'error':repr(e)}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary,indent=2))
