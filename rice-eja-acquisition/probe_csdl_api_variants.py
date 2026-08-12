import json,urllib.request,urllib.error
from pathlib import Path
OUT=Path('rice-eja-acquisition/csdl-api-variants');OUT.mkdir(parents=True,exist_ok=True)
DS='cbd2c393a5ad4056a1bd9130ca1340f6'; V='V2'
paths=['/gin-sdb-filetree/public/file/childrenFileListByPath','/api/gin-sdb-filetree/public/file/childrenFileListByPath','/api/sdb-filetree/public/file/childrenFileListByPath','/gin-sdb-filetree/file/childrenFileListByPath']
hosts=['https://www.scidb.cn','https://scidb.cn']
bodies=[{'dataSetId':DS,'version':V,'path':'/'+V,'lastIndex':0,'pageSize':200},{'dataSetId':DS,'version':V,'path':'/','lastIndex':0,'pageSize':200}]
res=[]
for host in hosts:
 for path in paths:
  for body in bodies:
   data=json.dumps(body).encode()
   req=urllib.request.Request(host+path,data=data,method='POST',headers={'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*','Content-Type':'application/json;charset=UTF-8','Referer':'https://www.scidb.cn/en/s/ZZJzAz','Origin':'https://www.scidb.cn'})
   try:
    with urllib.request.urlopen(req,timeout=60) as r:
     b=r.read(1000000); res.append({'url':host+path,'body':body,'status':r.status,'headers':dict(r.headers),'response':b.decode('utf-8','replace')[:100000]})
   except urllib.error.HTTPError as e:
    try: eb=e.read(10000).decode('utf-8','replace')
    except: eb=''
    res.append({'url':host+path,'body':body,'status':e.code,'error':repr(e),'response':eb})
   except Exception as e: res.append({'url':host+path,'body':body,'error':repr(e)})
(OUT/'variants.json').write_text(json.dumps(res,indent=2,ensure_ascii=False),encoding='utf-8')
for x in res: print(x['url'],x.get('status'),x.get('response','')[:300].replace('\n',' '))
