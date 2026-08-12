from __future__ import annotations
import json, re, hashlib, os, sys, urllib.request
from pathlib import Path

OUT=Path('rice-eja-acquisition/output')
OUT.mkdir(parents=True, exist_ok=True)

def get_json(url):
    req=urllib.request.Request(url, headers={'User-Agent':'China-Rice-EJA-acquisition/1.0'})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)

def dump(name,obj):
    (OUT/name).write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding='utf-8')

def download(url,dest,max_bytes=500_000_000):
    req=urllib.request.Request(url, headers={'User-Agent':'China-Rice-EJA-acquisition/1.0'})
    with urllib.request.urlopen(req, timeout=180) as r:
        size=int(r.headers.get('Content-Length','0') or 0)
        if size and size>max_bytes:
            return {'status':'SKIPPED_TOO_LARGE','bytes':size,'url':url}
        h=hashlib.sha256(); n=0
        with open(dest,'wb') as f:
            while True:
                b=r.read(1024*1024)
                if not b: break
                n+=len(b)
                if n>max_bytes:
                    f.close(); Path(dest).unlink(missing_ok=True)
                    return {'status':'SKIPPED_STREAM_EXCEEDED_LIMIT','bytes':n,'url':url}
                f.write(b); h.update(b)
        return {'status':'DOWNLOADED','bytes':n,'sha256':h.hexdigest(),'path':str(dest),'url':url}

status={}

# geoBoundaries
try:
    m=get_json('https://www.geoboundaries.org/api/current/gbOpen/CHN/ADM1/')
    dump('geoboundaries_metadata.json',m)
    status['boundary']={'status':'REACHABLE','gjDownloadURL':m.get('gjDownloadURL'),'boundaryID':m.get('boundaryID')}
except Exception as e: status['boundary']={'status':'ERROR','error':repr(e)}

# ChinaRiceCalendar
try:
    u='https://dataverse.harvard.edu/api/datasets/:persistentId?persistentId=doi:10.7910/DVN/EUP8EY'
    m=get_json(u); dump('ChinaRiceCalendar_metadata.json',m)
    files=m.get('data',{}).get('latestVersion',{}).get('files',[])
    periods=('2013_2017','2018_2022'); systems=('early','middle','late'); events=('transplant','heading','matur')
    sel=[]
    for it in files:
        d=it.get('dataFile',{}); n=d.get('filename',''); lo=n.lower()
        if lo.endswith('_rice_pixels.tif') and any(p in lo for p in periods) and any(s in lo for s in systems) and any(e in lo for e in events):
            sel.append({'id':d.get('id'),'name':n,'size':d.get('filesize'),'checksum':d.get('checksum'),'url':f"https://dataverse.harvard.edu/api/access/datafile/{d.get('id')}"})
    dump('ChinaRiceCalendar_selected.json',sel)
    status['ChinaRiceCalendar']={'status':'REACHABLE','selected_count':len(sel),'total_bytes':sum(int(x.get('size') or 0) for x in sel),'files':sel}
except Exception as e: status['ChinaRiceCalendar']={'status':'ERROR','error':repr(e)}

# CIrrMap250 v2
try:
    m=get_json('https://api.figshare.com/v2/articles/24814293/versions/2'); dump('CIrrMap250_v2_metadata.json',m)
    yrs={str(y) for y in range(2015,2021)}; sel=[]
    for f in m.get('files',[]):
        n=f.get('name',''); mm=re.search(r'(20\d{2})',n)
        if n.startswith('CIrrMap250_') and n.lower().endswith(('.tif','.tiff')) and mm and mm.group(1) in yrs:
            sel.append({k:f.get(k) for k in ('id','name','size','download_url','computed_md5','supplied_md5')})
    dump('CIrrMap250_selected.json',sel)
    status['CIrrMap250']={'status':'REACHABLE','selected_count':len(sel),'total_bytes':sum(int(x.get('size') or 0) for x in sel),'files':sel}
except Exception as e: status['CIrrMap250']={'status':'ERROR','error':repr(e)}

# CIWW1km current and versions
try:
    latest=get_json('https://api.figshare.com/v2/articles/27715404'); dump('CIWW1km_latest.json',latest)
    v=int(latest.get('version') or 0)
    m=get_json(f'https://api.figshare.com/v2/articles/27715404/versions/{v}'); dump(f'CIWW1km_v{v}_metadata.json',m)
    target={str(y) for y in range(2015,2021)}; sel=[]
    for f in m.get('files',[]):
        n=f.get('name',''); yrs=set(re.findall(r'20(?:1[5-9]|20)',n)); lo=n.lower()
        typ='volume' if ('km3' in lo or 'volume' in lo) else ('depth' if ('_mm' in lo or 'depth' in lo) else None)
        if typ and yrs & target:
            sel.append({'name':n,'size':f.get('size'),'download_url':f.get('download_url'),'type':typ})
    dump('CIWW1km_selected.json',sel)
    status['CIWW1km']={'status':'REACHABLE','version':v,'selected_count':len(sel),'selected_bytes':sum(int(x.get('size') or 0) for x in sel),'all_files':[{'name':f.get('name'),'size':f.get('size'),'download_url':f.get('download_url')} for f in m.get('files',[])]}
except Exception as e: status['CIWW1km']={'status':'ERROR','error':repr(e)}

# AquaCrop latest
try:
    m=get_json('https://api.github.com/repos/KUL-RSDA/AquaCrop/releases/latest'); dump('AquaCrop_latest_release.json',m)
    assets=[{'name':a.get('name'),'size':a.get('size'),'url':a.get('browser_download_url')} for a in m.get('assets',[])]
    status['AquaCrop']={'status':'REACHABLE','tag':m.get('tag_name'),'assets':assets,'source_zip':f"https://github.com/KUL-RSDA/AquaCrop/archive/refs/tags/{m.get('tag_name')}.zip"}
except Exception as e: status['AquaCrop']={'status':'ERROR','error':repr(e)}

# ScienceDB / CSDLv2 page reachability
for key,url in {
  'CSDLv2_ScienceDB':'https://www.scidb.cn/en/detail?dataSetId=4c2cc9d9fd1b4f70b30853aef5b57d20',
  'CSDLv2_TPDC':'https://data.tpdc.ac.cn/en/data/9ca9c82e-8b5f-4ea9-b1ea-ec706061ae70'
}.items():
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req,timeout=60) as r:
            status[key]={'status':'REACHABLE','http_status':r.status,'final_url':r.geturl(),'content_type':r.headers.get('content-type')}
    except Exception as e: status[key]={'status':'ERROR','error':repr(e),'url':url}

# CDS landing page (anonymous; token still required for data)
try:
    req=urllib.request.Request('https://cds.climate.copernicus.eu/datasets/sis-agrometeorological-indicators?tab=overview',headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(req,timeout=60) as r:
        status['AgERA5_CDS']={'status':'REACHABLE','http_status':r.status,'final_url':r.geturl()}
except Exception as e: status['AgERA5_CDS']={'status':'ERROR','error':repr(e)}

dump('SOURCE_PROBE_STATUS.json',status)
print(json.dumps(status,indent=2))
