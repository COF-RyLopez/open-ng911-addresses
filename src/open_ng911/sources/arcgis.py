"""Paged reads of an ArcGIS FeatureServer/MapServer layer as GeoJSON, written to a newline-delimited file
that DuckDB reads in one go: one {"p": properties, "g": geometry as GeoJSON text} per line.

Government endpoints flake (AGENTS.md): each page is retried with backoff before the job fails.
"""
import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

USER_AGENT = "open-ng911-addresses"


def _get_json(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.load(r)
            if "error" in d:
                raise OSError(f"ArcGIS error: {d['error']}")
            return d
        except (OSError, json.JSONDecodeError) as e:
            if i == tries - 1:
                raise
            wait = 5 * 2 ** i
            print(f"  [arcgis] {e}; retrying in {wait}s")
            time.sleep(wait)


def layer_info(layer_url):
    return _get_json(f"{layer_url}?f=json")


def fetch(layer_url, out_path, where="1=1", out_fields="*", workers=4, extra=None):
    """Every feature matching `where`, in WGS84, to out_path. Returns the feature count."""
    info = layer_info(layer_url)
    page = min(int(info.get("maxRecordCount") or 1000), 2000)
    base = {"where": where, "outFields": out_fields, "outSR": "4326", "f": "geojson", **(extra or {})}
    q = f"{layer_url}/query?"
    total = _get_json(q + urllib.parse.urlencode({"where": where, "returnCountOnly": "true", "f": "json"}))["count"]
    order = info.get("objectIdField") or next((f["name"] for f in info.get("fields", []) if f.get("type") == "esriFieldTypeOID"), None)
    if order:
        base["orderByFields"] = order  # stable paging

    def one(offset):
        return _get_json(q + urllib.parse.urlencode({**base, "resultOffset": offset, "resultRecordCount": page}))["features"]

    n = 0
    with open(out_path, "w") as out, ThreadPoolExecutor(workers) as pool:
        for feats in pool.map(one, range(0, total, page)):
            for f in feats:
                if f.get("geometry"):
                    out.write(json.dumps({"p": f.get("properties") or {}, "g": json.dumps(f["geometry"])}) + "\n")
                    n += 1
    print(f"  [arcgis] {n:,} of {total:,} features from {layer_url}")
    return n
