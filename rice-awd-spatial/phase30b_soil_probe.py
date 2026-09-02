#!/usr/bin/env python3
import csv, html as htmllib, os, re, urllib.parse, urllib.request
from pathlib import Path
OUT=Path(os.environ.get('OUT_DIR','phase30b_soil_probe'));OUT.mkdir(parents=True,exist_ok=True)
urls=['https://globalchange.bnu.edu.cn/research/soilw','http://globalchange.bnu.edu.cn/research/soilw']
page=None;base=None;err=[]
for u in urls:
    try:
        req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req,timeout=60) as r:
            page=r.read().decode('utf-8',errors='ignore');base=r.geturl();break
    except Exception as e:err.append((u,repr(e)))
if page is None:
    raise RuntimeError('Could not fetch GSDE page: '+repr(err))
(OUT/'gsde_page.html').write_text(page,encoding='utf-8')
rows=[]
for m in re.finditer(r'href\s*=\s*["\']([^"\']+)["\']',page,re.I):
    href=htmllib.unescape(m.group(1));full=urllib.parse.urljoin(base,href)
    around=re.sub(r'<[^>]+>',' ',page[max(0,m.start()-220):min(len(page),m.end()+220)])
    around=re.sub(r'\s+',' ',htmllib.unescape(around)).strip()
    rows.append({'href':href,'url':full,'context':around})
with open(OUT/'all_links.csv','w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=['href','url','context']);w.writeheader();w.writerows(rows)
sel=[]
for r in rows:
    s=(r['href']+' '+r['context']).lower()
    if any(k in s for k in ['phh2o','sand5min','sand','5min','netcdf','.nc','soil basic','soil property']):sel.append(r)
with open(OUT/'candidate_links.csv','w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=['href','url','context']);w.writeheader();w.writerows(sel)
print('BASE',base,'links',len(rows),'candidates',len(sel))
for r in sel[:100]:print(r['url'],r['context'][:300])
