"""
Story map data: a small JSON file per build job, read by story/index.html (written to story/pilots/; data/ is gitignored).

    python story/extract.py --out data/output --job ca-pe [--dest story/pilots]

What goes in, and why it is safe to publish:
  - every Package's counts and field fill, copied from its manifest.json (already public in CI summaries)
  - the A2 and A3 outlines, simplified: TIGER (US public domain) or StatCan (Statistics Canada Open Licence)
  - address points ONLY when every address source in the job has license_status = "open" (AGENTS.md,
    Licenses). Records carry the agency's licence; gap-fill candidates go in only with a stated Overture
    source licence. Jobs with an "unknown" source (Vermont today) get counts and outlines, never points.
  - no road geometry: government centerlines in Phase 1 are all licence-unknown, and Overture's are ODbL.
"""
import argparse
import glob
import json
import os
import random
import sys

from open_ng911 import db

SAMPLE_FIELDS = ("uid", "nguid", "gers_id", "status", "source_id", "discrpagid", "dateupdate", "country", "a1",
                 "a2", "a3", "add_number", "addnum_suf", "st_predir", "st_pretyp", "st_name", "st_postyp",
                 "st_posdir", "unit", "post_comm", "post_code", "placement", "source_license")


def _round(c):
    return [round(c[0], 4), round(c[1], 4)] if isinstance(c[0], (int, float)) else [_round(x) for x in c]


def geojson(c, path, props, tolerance):
    """A layer's polygons as GeoJSON features, simplified and rounded to 4 decimals (~10 m)."""
    out = []
    sel = ", ".join(props)
    kind = c.execute(f"DESCRIBE SELECT geom FROM read_parquet('{path}')").fetchall()[0][1]
    geom = "ST_GeomFromWKB(geom)" if kind == "BLOB" else "geom"  # an empty layer has no GEOMETRY type
    for row in c.execute(f"""SELECT {sel}, ST_AsGeoJSON(ST_SimplifyPreserveTopology({geom}, {tolerance}))
            FROM read_parquet('{path}')""").fetchall():
        *vals, g = row
        if g:
            g = json.loads(g)
            g["coordinates"] = _round(g["coordinates"])
            out.append({"type": "Feature", "properties": dict(zip(props, vals)), "geometry": g})
    return out


def manifest_subset(m):
    road = m.get("road_centerline", {})
    up = m.get("upstream", {})
    return {
        "package": m["package"], "name": m["name"], "rows": m["rows"], "records": m["records"],
        "records_with_gers_id": m["records_with_gers_id"], "gap_fill_candidates": m["gap_fill_candidates"],
        "record_gers_coverage": m["record_gers_coverage"], "field_fill": m["field_fill"],
        "nguid_domain": m["nguid_domain"], "opted_in": m["opted_in"], "recipient": m["recipient"],
        "a3_features": m["boundaries"].get("A3Polygon", {}).get("features", 0),
        "roads": {"rows": road.get("rows", 0), "with_gers_id": road.get("with_gers_id", 0),
                  "road_source": road.get("road_source"), "field_fill": road.get("field_fill", {})},
        "upstream": {"overture": up.get("overture", {}), "national": up.get("national", {})},
        "odbl": {k: v.get("status") for k, v in m.get("odbl_replacement", {}).items() if isinstance(v, dict)},
    }


def points(c, files, rng):
    """Columnar, delta-encoded points (lon/lat x 1e5) plus a street dictionary and a few full-record samples."""
    src = "read_parquet([" + ", ".join(db.quote(f) for f in files) + "])"
    rows = c.execute(f"""SELECT round(ST_X(geom) * 1e5)::BIGINT, round(ST_Y(geom) * 1e5)::BIGINT,
            CASE WHEN status = 'record' AND gers_id IS NOT NULL THEN 0 WHEN status = 'record' THEN 1 ELSE 2 END,
            add_number, concat_ws(' ', st_predir, st_pretyp, st_name, st_postyp, st_posdir), a3, a2
        FROM {src}
        WHERE geom IS NOT NULL AND (status = 'record' OR (source_license IS NOT NULL AND source_license <> 'unknown'))
        ORDER BY a2, ST_Hilbert(geom)""").fetchall()
    streets, a3s, a2s = {}, {}, {}
    x, y, k, n, s, a, p = [], [], [], [], [], [], []
    px = py = 0
    for lon, lat, kind, num, st, a3, a2 in rows:
        x.append(lon - px)
        y.append(lat - py)
        px, py = lon, lat
        k.append(kind)
        n.append(num or 0)
        s.append(streets.setdefault(st, len(streets)))
        a.append(a3s.setdefault(a3 or "", len(a3s)))
        p.append(a2s.setdefault(a2 or "", len(a2s)))
    fields = ", ".join(SAMPLE_FIELDS)
    samples = []
    for status, want in (("record", 240), ("gap_fill_candidate", 60)):
        got = db.rows(c, f"""SELECT {fields}, round(ST_X(geom), 6) AS lon, round(ST_Y(geom), 6) AS lat FROM {src}
            WHERE status = '{status}' AND (status = 'record' OR (source_license IS NOT NULL AND source_license <> 'unknown'))
            USING SAMPLE reservoir({want} ROWS) REPEATABLE (7)""")
        samples += got
    rng.shuffle(samples)
    return {"dx": x, "dy": y, "kind": k, "num": n, "street": s, "a3": a, "a2": p,
            "streets": list(streets), "a3s": list(a3s), "a2s": list(a2s), "samples": samples}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/output")
    ap.add_argument("--job", required=True)
    ap.add_argument("--dest", default=os.path.join(os.path.dirname(__file__), "pilots"))
    a = ap.parse_args()
    roots = sorted(glob.glob(os.path.join(a.out, "release=*", a.job)))
    if not roots:
        sys.exit(f"no build output for {a.job} under {a.out}")
    root = roots[-1]
    with open(os.path.join(root, "job.json")) as f:
        job = json.load(f)
    c = db.connect(s3=False)
    packages, a2, a3, open_sources = [], [], [], None
    for d in sorted(glob.glob(os.path.join(root, "*", "manifest.json"))):
        d = os.path.dirname(d)
        with open(os.path.join(d, "manifest.json")) as f:
            m = json.load(f)
        addr = [s for s in m["sources"] if s["layer"] == "addresses"]
        ok = bool(addr) and all(s["license_status"] == "open" for s in addr)
        open_sources = ok if open_sources is None else (open_sources and ok)
        packages.append(manifest_subset(m))
        geoid = os.path.basename(d)
        if os.path.exists(os.path.join(d, "a2_polygon.parquet")):
            for ft in geojson(c, os.path.join(d, "a2_polygon.parquet"), ("a2", "source_code"), 0.003):
                ft["properties"]["geoid"] = geoid
                a2.append(ft)
        if os.path.exists(os.path.join(d, "a3_polygon.parquet")):
            for ft in geojson(c, os.path.join(d, "a3_polygon.parquet"), ("a3", "source_code"), 0.0015):
                ft["properties"]["geoid"] = geoid
                a3.append(ft)
        sources = m["sources"]
        boundary_src = m["boundaries"]
    out = {"job": job, "packages": packages, "sources": sources, "boundaries": boundary_src,
           "a2": {"type": "FeatureCollection", "features": a2},
           "a3": {"type": "FeatureCollection", "features": a3},
           "points": None,
           "points_note": "Address points are shown only for open-licensed sources." if not open_sources else None}
    if open_sources:
        files = sorted(glob.glob(os.path.join(root, "*", "site_structure_address_point.parquet")))
        out["points"] = points(c, files, random.Random(7))
    os.makedirs(a.dest, exist_ok=True)
    path = os.path.join(a.dest, f"{a.job}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False, default=str)
    print(f"{path}: {os.path.getsize(path):,} bytes, {len(packages)} packages, "
          f"points={'yes' if open_sources else 'no (licence not open)'}")


if __name__ == "__main__":
    main()
