import json,urllib.request
from pathlib import Path
OUT=Path('rice-eja-acquisition/csdl-1km-level');OUT.mkdir(parents=True,exist_ok=True)
url='https://www.scidb.cn/api/gin-sdb-filetree/public/file/childrenFileListByPath'
body={'dataSetId':'cbd2c393a5ad4056a1bd9130ca1340f6','version':'V2','path':'/V2/1km','lastIndex':0,'pageSize':1000}
req=urllib.request.Request(url,data=json.dumps(body).encode(),method='POST',headers={'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*','Content-Type':'application/json;charset=UTF-8','Referer':'https://www.scidb.cn/en/s/ZZJzAz','Origin':'https://www.scidb.cn'})
with urllib.request.urlopen(req,timeout=90) as r:j=json.loads(r.read().decode())
OUT.joinpath('level.json').write_text(json.dumps(j,indent=2,ensure_ascii=False),encoding='utf-8')
print('code',j.get('code'),'n',len(j.get('data') or []))
for x in j.get('data') or []:print(x.get('id'),x.get('fileName'),x.get('path'),x.get('dir'),x.get('size'))
