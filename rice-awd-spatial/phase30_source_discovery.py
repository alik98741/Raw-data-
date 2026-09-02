#!/usr/bin/env python3
"""Phase 30: discover and verify official spatial inputs for the rice AWD project.

This script is intentionally conservative: it queries official APIs, downloads only
small/explicitly matched files, verifies checksums where supplied, and inventories
larger datasets before any bulk acquisition.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

OUT = Path(os.environ.get("OUT_DIR", "phase30_discovery"))
OUT.mkdir(parents=True, exist_ok=True)

UA = "rice-awd-eja-source-discovery/1.0"


def get_json(url: str, timeout: int = 90):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def download(url: str, path: Path, timeout: int = 180):
    path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(path, "wb") as f:
        shutil.copyfileobj(r, f)
    return path


def md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_csv(path: Path, rows: list[dict]):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = sorted({k for row in rows for k in row})
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def flatten_text_files(root: Path):
    allowed = {".r", ".rmd", ".m", ".py", ".txt", ".md", ".csv", ".json", ".yml", ".yaml"}
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in allowed and p.stat().st_size <= 10_000_000:
            try:
                yield p, p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass


def main():
    audit = []

    # 1) GGCMI Phase 3 rice calendars (official Zenodo API)
    zen = get_json("https://zenodo.org/api/records/5062513")
    (OUT / "zenodo_5062513_metadata.json").write_text(json.dumps(zen, indent=2), encoding="utf-8")
    zrows = []
    targets = {
        "ri1_ir_ggcmi_crop_calendar_phase3_v1.01.nc4",
        "ri2_ir_ggcmi_crop_calendar_phase3_v1.01.nc4",
    }
    for f in zen.get("files", []):
        key = f.get("key") or f.get("filename") or ""
        checksum = f.get("checksum", "")
        links = f.get("links", {}) or {}
        url = links.get("content") or links.get("self")
        row = {"name": key, "size": f.get("size"), "checksum": checksum, "download_url": url}
        zrows.append(row)
        if key in targets and url:
            dest = OUT / "ggcmi" / key
            download(url, dest)
            actual = md5(dest)
            expected = checksum.split(":", 1)[-1].lower() if checksum else ""
            ok = (not expected) or actual == expected
            audit.append({"source": "GGCMI", "file": key, "status": "PASS" if ok else "FAIL", "expected_md5": expected, "actual_md5": actual, "size": dest.stat().st_size})
            if not ok:
                raise RuntimeError(f"Checksum mismatch for {key}: {actual} != {expected}")
    write_csv(OUT / "ggcmi_inventory.csv", zrows)
    missing = targets - {r["name"] for r in zrows}
    if missing:
        raise RuntimeError(f"Missing GGCMI target files in official record: {sorted(missing)}")

    # 2) Harvard Dataverse GAEZ+ 2015 harvested area inventory.
    doi = "doi:10.7910/DVN/KAGRFI"
    dv_url = "https://dataverse.harvard.edu/api/datasets/:persistentId/?persistentId=" + urllib.parse.quote(doi, safe=":/")
    dv = get_json(dv_url)
    (OUT / "dataverse_KAGRFI_metadata.json").write_text(json.dumps(dv, indent=2), encoding="utf-8")
    files = (((dv.get("data") or {}).get("latestVersion") or {}).get("files") or [])
    drows = []
    rice_candidates = []
    for item in files:
        df = item.get("dataFile") or {}
        fn = df.get("filename", "")
        row = {
            "id": df.get("id"), "filename": fn, "filesize": df.get("filesize"),
            "contentType": df.get("contentType"), "md5": ((df.get("checksum") or {}).get("value")),
            "directoryLabel": item.get("directoryLabel", ""), "restricted": item.get("restricted", False),
        }
        drows.append(row)
        low = (fn + " " + str(item.get("directoryLabel", ""))).lower()
        if "rice" in low and ("irrig" in low or "irrigated" in low):
            rice_candidates.append(row)
    write_csv(OUT / "gaez_harvest_area_inventory.csv", drows)
    write_csv(OUT / "gaez_rice_irrigated_candidates.csv", rice_candidates)
    audit.append({"source": "GAEZ+", "file": "Dataverse inventory", "status": "PASS", "n_files": len(drows), "n_rice_irrigated_candidates": len(rice_candidates)})

    # Download only clearly matching rice-irrigated candidates <= 150 MB.
    for row in rice_candidates:
        if row.get("restricted") or not row.get("id"):
            continue
        size = int(row.get("filesize") or 0)
        if 0 < size <= 150_000_000:
            fn = row["filename"]
            dest = OUT / "gaez" / fn
            url = f"https://dataverse.harvard.edu/api/access/datafile/{row['id']}"
            download(url, dest, timeout=300)
            actual = md5(dest)
            expected = str(row.get("md5") or "").lower()
            ok = (not expected) or actual == expected
            audit.append({"source": "GAEZ+", "file": fn, "status": "PASS" if ok else "FAIL", "expected_md5": expected, "actual_md5": actual, "size": dest.stat().st_size})
            if not ok:
                raise RuntimeError(f"GAEZ checksum mismatch for {fn}")

    # 3) Official Figshare source-code record for the Nature Food AWD study.
    fig = get_json("https://api.figshare.com/v2/articles/27249210")
    (OUT / "figshare_27249210_metadata.json").write_text(json.dumps(fig, indent=2), encoding="utf-8")
    frows = []
    code_root = OUT / "nature_food_code"
    code_root.mkdir(exist_ok=True)
    for f in fig.get("files", []):
        row = {"id": f.get("id"), "name": f.get("name"), "size": f.get("size"), "computed_md5": f.get("computed_md5"), "download_url": f.get("download_url")}
        frows.append(row)
        name = str(f.get("name") or "")
        size = int(f.get("size") or 0)
        url = f.get("download_url")
        # Source-code record is expected to be small. Cap protects Actions storage.
        if url and 0 < size <= 150_000_000:
            dest = code_root / name
            download(url, dest, timeout=300)
            actual = md5(dest)
            expected = str(f.get("computed_md5") or "").lower()
            ok = (not expected) or actual == expected
            audit.append({"source": "NatureFood-Figshare", "file": name, "status": "PASS" if ok else "FAIL", "expected_md5": expected, "actual_md5": actual, "size": dest.stat().st_size})
            if not ok:
                raise RuntimeError(f"Figshare checksum mismatch for {name}")
            if zipfile.is_zipfile(dest):
                ex = code_root / (dest.stem + "_extracted")
                ex.mkdir(exist_ok=True)
                with zipfile.ZipFile(dest) as z:
                    z.extractall(ex)
    write_csv(OUT / "figshare_code_inventory.csv", frows)

    # 4) Search downloaded code for exact spatial-source definitions / formulas.
    pattern = re.compile(r"(?i)(ERA5|CWA|climatological|precip|evapo|PET|temperature|soil|sand|pH|HWSD|Shangguan|UAWD|upper\s+AWD|GAEZ|harvest|calendar|SWP|water\s+potential)")
    hits = []
    for p, text in flatten_text_files(code_root):
        for i, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                hits.append({"file": str(p.relative_to(code_root)), "line": i, "text": line[:2000]})
    write_csv(OUT / "nature_food_spatial_source_hits.csv", hits)

    # 5) Check official SoilGrids endpoints only as modern sensitivity, not source-compatible primary soil.
    soil_urls = [
        "https://files.isric.org/soilgrids/latest/data/phh2o/",
        "https://files.isric.org/soilgrids/latest/data/sand/",
    ]
    soil_rows = []
    for url in soil_urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                body = r.read(200000).decode("utf-8", errors="ignore")
                soil_rows.append({"url": url, "status": r.status, "preview": re.sub(r"\s+", " ", body)[:5000]})
        except Exception as e:
            soil_rows.append({"url": url, "status": "ERROR", "preview": repr(e)})
    write_csv(OUT / "soilgrids_endpoint_audit.csv", soil_rows)

    write_csv(OUT / "acquisition_audit.csv", audit)
    summary = {
        "ggcmi_targets_downloaded": sum(1 for a in audit if a.get("source") == "GGCMI" and a.get("status") == "PASS"),
        "gaez_inventory_files": len(drows),
        "gaez_rice_irrigated_candidates": len(rice_candidates),
        "figshare_files": len(frows),
        "source_code_hits": len(hits),
        "audit_failures": sum(1 for a in audit if a.get("status") == "FAIL"),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if summary["audit_failures"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
