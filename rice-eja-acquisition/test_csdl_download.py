import urllib.request,zipfile,hashlib,os,json
from pathlib import Path
OUT=Path('rice-eja-acquisition/csdl-download-test');OUT.mkdir(parents=True,exist_ok=True)
file_id='7599a04028025a6f67af8d0ad24332d1' # BD_0-5cm_1km_mean.zip
urls=[
 f'https://www.scidb.cn/api/sdb-download-service/downloadFileMole?fileId={file_id}',
 f'https://www.scidb.cn/api/sdb-download-service/downloadFile?fileId={file_id}',
 f'https://www.scidb.cn/api/gin-sdb-filetree/public/file/download?fileId={file_id}'
]
res=[]
for i,u in enumerate(urls):
 try:
  req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.scidb.cn/en/s/ZZJzAz','Accept':'*/*'})
  with urllib.request.urlopen(req,timeout=120) as r:
   b=r.read(40_000_000); h=dict(r.headers); final=r.geturl()
  rec={'url':u,'final':final,'status':200,'bytes':len(b),'headers':h,'magic':b[:20].hex()}
  fp=OUT/f'candidate_{i}.bin';fp.write_bytes(b)
  if b.startswith(b'PK'):
   z=zipfile.ZipFile(fp); rec['zip_names']=z.namelist(); rec['zip_info']=[{'name':x.filename,'size':x.file_size,'compressed':x.compress_size} for x in z.infolist()]
  res.append(rec)
 except Exception as e:res.append({'url':u,'error':repr(e)})
(OUT/'results.json').write_text(json.dumps(res,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
print(json.dumps(res,indent=2,ensure_ascii=False,default=str))
