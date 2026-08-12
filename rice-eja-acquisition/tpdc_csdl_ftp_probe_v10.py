from __future__ import annotations
import json, urllib.request, ftplib, re
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

def safe_list(ftp):
    try:
        return [{'name':n,'type':f.get('type'),'size':f.get('size')} for n,f in ftp.mlsd()]
    except Exception:
        return [{'name':x,'type':None,'size':None} for x in ftp.nlst()]

status={}
try:
    code,url,j=post('/view/metadataView/detail/',{'userId':'','metadataId':UUID})
    ctx=j.get('context') or {}; meta=ctx.get('metadataVO') or {}
    status['detail']={'http':code,'app_code':j.get('code'),'metadata_id':meta.get('id'),'title':meta.get('title'),'sharePolicy':meta.get('sharePolicy'),'status':meta.get('status'),'fileSize':meta.get('fileSize'),'source':meta.get('source'),'language':meta.get('language')}
except Exception as e:
    status['detail']={'error':repr(e)}; meta={}

ftp_info=None
path=f'/file/ftp/createNoLoginDownloadFtpUser?metadataId={UUID}'
try:
    code,url,j=post(path,{'noToken':True})
    data=j.get('data') or j.get('context') or {}
    status['ftp_endpoint']={'path':path,'http':code,'app_code':j.get('code'),'keys':sorted(data.keys()) if isinstance(data,dict) else [],'has_host':bool(isinstance(data,dict) and (data.get('ftpUrl') or data.get('host'))),'has_username':bool(isinstance(data,dict) and data.get('username')),'has_password':bool(isinstance(data,dict) and data.get('password'))}
    if str(j.get('code'))=='200' and isinstance(data,dict) and data.get('username') and data.get('password'):
        ftp_info=data
except Exception as e:
    status['ftp_endpoint']={'path':path,'error':repr(e)}

if ftp_info:
    rawhost=str(ftp_info.get('ftpUrl') or ftp_info.get('host') or '').replace('ftp://','').strip('/ ')
    hosts=[h.strip() for h in re.split(r'[,;\s]+',rawhost) if h.strip() and '.' in h]
    port=int(ftp_info.get('ftpPort') or ftp_info.get('port') or 21)
    user=ftp_info['username']; pw=ftp_info['password']
    status['ftp_session']={'hosts':hosts,'port':port,'credential_received':True,'attempts':[]}
    connected=False
    for host in hosts:
        att={'host':host}
        try:
            ftp=ftplib.FTP(); ftp.connect(host,port,timeout=60); ftp.login(user,pw); ftp.set_pasv(True)
            pwd=ftp.pwd(); root=safe_list(ftp)
            att.update({'login_success':True,'pwd':pwd,'root_entries':root[:300]})
            paths=[]
            # infer likely child directories from root plus conventional paths
            candidates=['V2','/V2','1km','/1km','V2/1km','/V2/1km']+[x['name'] for x in root if x.get('type')=='dir']
            seen=set()
            for cand in candidates:
                if cand in seen: continue
                seen.add(cand)
                try:
                    ftp.cwd(pwd); ftp.cwd(cand); here=ftp.pwd(); ls=safe_list(ftp)
                    paths.append({'candidate':cand,'pwd':here,'entries':ls[:500]})
                    # one extra level for entries that look like V2, 1km, GTiff
                    for child in [z['name'] for z in ls if z.get('type')=='dir' and z['name'].lower() in {'v2','1km','gtiff','netcdf','data'}]:
                        try:
                            ftp.cwd(here); ftp.cwd(child); paths.append({'candidate':cand+'/'+child,'pwd':ftp.pwd(),'entries':safe_list(ftp)[:500]})
                        except Exception as e: paths.append({'candidate':cand+'/'+child,'error':type(e).__name__+': '+str(e)[:200]})
                except Exception as e:
                    paths.append({'candidate':cand,'error':type(e).__name__+': '+str(e)[:200]})
            att['paths']=paths
            ftp.quit(); connected=True; status['ftp_session']['attempts'].append(att); break
        except Exception as e:
            att.update({'login_success':False,'error':repr(e)}); status['ftp_session']['attempts'].append(att)
    status['ftp_session']['login_success']=connected
else:
    status['ftp_session']={'credential_received':False}

(OUT/'TPDC_CSDL_FTP_PROBE_REDACTED.json').write_text(json.dumps(status,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(status,indent=2,ensure_ascii=False))
