from __future__ import annotations
import os,re,json,requests
from pathlib import Path

raw=os.environ.get('CDSAPI_KEY','').strip()
if not raw:
    raise RuntimeError('CDSAPI_KEY missing')

# Build safe normalization candidates without ever printing secret material.
cands=[]
def add(label,val):
    val=(val or '').strip()
    if val and all(val!=v for _,v in cands): cands.append((label,val))
add('raw',raw)
# If user pasted a .cdsapirc block, extract key line.
for line in raw.splitlines():
    s=line.strip()
    if s.lower().startswith('key:'):
        add('key_line',s.split(':',1)[1].strip())
if raw.lower().startswith('key:'):
    add('key_prefix',raw.split(':',1)[1].strip())
if raw.lower().startswith('bearer '):
    add('bearer_prefix',raw[7:].strip())
# Legacy uid:key forms occasionally survive in copied credentials; ARCO wants PAT itself.
if '\n' not in raw and ':' in raw and not raw.lower().startswith(('http:','https:')):
    add('after_first_colon',raw.split(':',1)[1].strip())

urls={
 'account':'https://cds.climate.copernicus.eu/api/profiles/v1/account/',
 'licences':'https://cds.climate.copernicus.eu/api/profiles/v1/account/licences',
 'agera5_arco':'https://arco.datastores.ecmwf.int/cadl-arco-time-001/arco/sis_agrometeorological_indicators/all/timeChunked.zarr/.zmetadata'
}
rows=[]
for label,tok in cands:
    headers={'Authorization':f'Bearer {tok}','User-Agent':'China-Rice-EJA-safe-probe/1.0'}
    row={'candidate':label}
    for name,url in urls.items():
        try:
            r=requests.get(url,headers=headers,timeout=30,allow_redirects=True)
            row[name+'_http']=int(r.status_code)
            # Keep only tiny, non-sensitive diagnostics.
            row[name+'_content_type']=r.headers.get('content-type','')[:120]
        except Exception as e:
            row[name+'_http']='ERROR'
            row[name+'_error']=type(e).__name__
    rows.append(row)

out=Path('rice-eja-acquisition/cds-auth-diagnostic-v10');out.mkdir(parents=True,exist_ok=True)
(out/'CDS_AUTH_DIAGNOSTIC.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
# Human-safe summary only.
summary=[]
for r in rows:
    summary.append(f"{r['candidate']}: account={r.get('account_http')} licences={r.get('licences_http')} agera5_arco={r.get('agera5_arco_http')}")
(out/'CDS_AUTH_DIAGNOSTIC.txt').write_text('\n'.join(summary)+'\n',encoding='utf-8')
print('\n'.join(summary))
# Do not fail: artifact is the diagnostic result.
