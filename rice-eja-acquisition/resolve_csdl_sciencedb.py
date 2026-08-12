import re,json,urllib.request,urllib.parse
from pathlib import Path
OUT=Path('rice-eja-acquisition/csdl-resolve');OUT.mkdir(parents=True,exist_ok=True)
UA={'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*'}

def fetch(url,headers=None):
    req=urllib.request.Request(url,headers={**UA,**(headers or {})})
    with urllib.request.urlopen(req,timeout=90) as r:
        return r.geturl(),dict(r.headers),r.read(10_000_000)

short='https://www.scidb.cn/s/ZZJzAz'
final,headers,raw=fetch(short)
text=raw.decode('utf-8','replace')
(OUT/'short_page.html').write_text(text,encoding='utf-8')
print('short final',final,'bytes',len(raw))
# Save dataset-like IDs/tokens from SSR HTML
ids=sorted(set(re.findall(r'\b[0-9a-fA-F]{24,40}\b',text)))
tokens=sorted(set(re.findall(r'ZZJzAz|dataSetId.{0,120}|surl.{0,120}',text,re.I)))
(OUT/'short_page_ids.txt').write_text('\n'.join(ids),encoding='utf-8')
(OUT/'short_page_tokens.txt').write_text('\n'.join(tokens[:1000]),encoding='utf-8')
print('ids',ids[:30])
# JS bundles: retain contexts around detail resolver + file tree + ftp + download endpoints
scripts=re.findall(r'<script[^>]+src=[\"\']([^\"\']+)',text,re.I)
allctx=[]; allurls=[]
for s in scripts:
    su=urllib.parse.urljoin(final,s)
    try:
        _,_,b=fetch(su); st=b.decode('utf-8','replace')
    except Exception as e:
        continue
    for needle in ['childrenFileListByPath','searchTreeList','downloadFileMole','ftpAccount','surl','visitMode','getTrueVersions','zipDownload','showZipDownload','downloadSelected']:
        pos=0
        while True:
            i=st.find(needle,pos)
            if i<0: break
            allctx.append(f'\n### {s} :: {needle} @ {i}\n'+st[max(0,i-1800):i+2600])
            pos=i+len(needle)
    for u in re.findall(r'(?:url\s*:\s*)?[\"\']([^\"\']{2,400})[\"\']',st):
        if any(k in u.lower() for k in ['filetree','download-service','dataset-service','sharelink','ftp']): allurls.append(u)
(OUT/'endpoint_contexts.txt').write_text('\n'.join(allctx),encoding='utf-8')
(OUT/'endpoint_strings.txt').write_text('\n'.join(sorted(set(allurls))),encoding='utf-8')
print('contexts',len(allctx),'endpoints',len(set(allurls)))
# Try generic open-API endpoint patterns against short token / discovered IDs.
tests=[]
base='https://www.scidb.cn'
cands=['ZZJzAz']+ids
patterns=[
 '/gin-sdb-package/public/searchDataDetail?dataSetId={x}',
 '/sdb-dataset-service/public/findByTxId?dataSetId={x}',
 '/sdb-dataset-service/public/checkNum?dataSetId={x}',
 '/gin-sdb-filetree/public/file/searchTreeList?dataSetId={x}',
 '/gin-sdb-filetree/public/file/childrenFileListByPath?dataSetId={x}&path=/'
]
for x in cands[:20]:
  for p in patterns:
    url=base+p.format(x=urllib.parse.quote(x))
    try:
      fu,h,b=fetch(url)
      body=b.decode('utf-8','replace')[:4000]
      tests.append({'url':url,'status':'OK','content_type':h.get('Content-Type'),'body':body})
    except Exception as e: tests.append({'url':url,'status':'ERR','error':repr(e)})
(OUT/'api_tests.json').write_text(json.dumps(tests,indent=2,ensure_ascii=False),encoding='utf-8')
print('tests',len(tests))
