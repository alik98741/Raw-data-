from __future__ import annotations
import ftplib,json,re,ssl
from pathlib import Path
OUT=Path('rice-eja-acquisition/chinaricecalendar-ncdc-probe-v10');OUT.mkdir(parents=True,exist_ok=True)
results=[]
for mode in ['FTP_TLS','FTP']:
  for user,pw,label in [('anonymous','anonymous@','anonymous'),('','', 'blank')]:
    rec={'mode':mode,'credential':label}
    f=None
    try:
      if mode=='FTP_TLS':
        f=ftplib.FTP_TLS(context=ssl.create_default_context());f.connect('ftp.ncdc.ac.cn',2121,timeout=30);f.auth();f.login(user,pw);f.prot_p()
      else:
        f=ftplib.FTP();f.connect('ftp.ncdc.ac.cn',2121,timeout=30);f.login(user,pw)
      rec['pwd']=f.pwd(); names=f.nlst();rec['root_count']=len(names);rec['root_head']=names[:100]
      # Search a few likely dirs without recursive explosion.
      hits=[]
      for n in names[:300]:
        if any(k in n.lower() for k in ['rice','calendar','dv','db6449','eup8ey']): hits.append(n)
      rec['name_hits']=hits
    except Exception as e: rec['error']=type(e).__name__+': '+str(e)[:300]
    finally:
      if f:
        try:f.close()
        except:pass
    results.append(rec)
(OUT/'NCDC_FTP_PROBE.json').write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
for r in results: print(r)
