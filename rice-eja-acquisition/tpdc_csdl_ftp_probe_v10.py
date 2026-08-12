from __future__ import annotations
import json, urllib.request, ftplib, ssl
from pathlib import Path

UUID='46ddd893-3b2b-4bb3-b9e6-b043f3c5c3a2'
BASE='https://data.tpdc.ac.cn'
OUT=Path('rice-eja-acquisition/tpdc-ftp-probe-v10'); OUT.mkdir(parents=True,exist_ok=True)
H={'User-Agent':'Mozilla/5.0','Accept':'application/json,text/plain,*/*','Content-Type':'application/json;charset=UTF-8','Referer':f'{BASE}/en/data/{UUID}'}

def post(path,obj):
    req=urllib.request.Request(BASE+path,data=json.dumps(obj).encode(),headers=H,method='POST')
    with urllib.request.urlopen(req,timeout=90) as r:
        raw=r.read().decode('utf-8','replace')
        return r.status, r.geturl(), json.loads(raw)

status={}
# exact frontend detail call
try:
    code,url,j=post('/view/metadataView/detail/',{'userId':'','metadataId':UUID})
    ctx=j.get('context') or {}; meta=ctx.get('metadataVO') or {}
    status['detail']={'http':code,'app_code':j.get('code'),'metadata_id':meta.get('id'),'title':meta.get('title'),'sharePolicy':meta.get('sharePolicy'),'status':meta.get('status'),'fileSize':meta.get('fileSize'),'source':meta.get('source'),'language':meta.get('language')}
except Exception as e:
    status['detail']={'error':repr(e)}; meta={}

# Exact no-login FTP route used by the frontend. Never persist password/username.
ftp_info=None
for path in [
    f'/file/ftp/createNoLoginDownloadFtpUser?metadataId={UUID}',
    f'/file/ftp/createNoLoginDownloadFtpUser?metadataId={meta.get("id") or UUID}',
]:
    try:
        code,url,j=post(path,{'noToken':True})
        data=j.get('data') or j.get('context') or {}
        status.setdefault('ftp_endpoint_attempts',[]).append({'path':path,'http':code,'app_code':j.get('code'),'keys':sorted(data.keys()) if isinstance(data,dict) else [],'has_host':bool(isinstance(data,dict) and (data.get('ftpUrl') or data.get('host'))),'has_username':bool(isinstance(data,dict) and data.get('username')),'has_password':bool(isinstance(data,dict) and data.get('password'))})
        if str(j.get('code'))=='200' and isinstance(data,dict) and data.get('username') and data.get('password'):
            ftp_info=data; break
    except Exception as e:
        status.setdefault('ftp_endpoint_attempts',[]).append({'path':path,'error':repr(e)})

if ftp_info:
    host=str(ftp_info.get('ftpUrl') or ftp_info.get('host') or '').replace('ftp://','').strip('/ ')
    port=int(ftp_info.get('ftpPort') or ftp_info.get('port') or 21)
    user=ftp_info['username']; pw=ftp_info['password']
    status['ftp_session']={'host':host,'port':port,'credential_received':True}
    try:
        ftp=ftplib.FTP(); ftp.connect(host,port,timeout=60); ftp.login(user,pw); ftp.set_pasv(True)
        pwd=ftp.pwd(); root=[]
        try: root=list(ftp.mlsd())
        except Exception:
            root=[(x,{}) for x in ftp.nlst()]
        status['ftp_session'].update({'login_success':True,'pwd':pwd,'root_entries':[{'name':n,'type':f.get('type')} for n,f in root[:200]]})
        # Search shallowly for V2/1km and property directories without downloading.
        paths=[]
        for cand in ['V2','/V2','1km','/1km','V2/1km','/V2/1km']:
            try:
                ftp.cwd(pwd); ftp.cwd(cand); here=ftp.pwd()
                try: ls=list(ftp.mlsd())
                except Exception: ls=[(x,{}) for x in ftp.nlst()]
                paths.append({'candidate':cand,'pwd':here,'entries':[{'name':n,'type':f.get('type')} for n,f in ls[:300]]})
            except Exception as e:
                paths.append({'candidate':cand,'error':type(e).__name__+': '+str(e)[:200]})
        status['ftp_paths']=paths
        ftp.quit()
    except Exception as e:
        status['ftp_session'].update({'login_success':False,'error':repr(e)})
else:
    status['ftp_session']={'credential_received':False}

(OUT/'TPDC_CSDL_FTP_PROBE_REDACTED.json').write_text(json.dumps(status,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(status,indent=2,ensure_ascii=False))
