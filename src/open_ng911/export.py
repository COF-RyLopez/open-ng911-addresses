"""
A job's Packages as one NENA GeoPackage: every layer written into a copy of NENA's own v3.0 template
(nena/templates), so layer names, field names, types and length checks are NENA's.

    python -m open_ng911.export data/output/release=<r>/us-vt us-vt.gpkg

    1. The Packages' GeoParquet layers are read together. A service polygon or municipality the build clipped at a county
       seam (the same agency feature in two Packages) is merged back into one, with the largest piece's fields.
    2. Each NENA field is checked before anything is written: a value longer than the field, or outside its NENA
       domain, is listed in the report (<out>.report.json) with its count. A value too long for NENA's field stops
       the export, since the template's checks would reject it; nothing is cut or changed to fit.
    3. Agency_ID, ServiceURI and AVcard_URI are the agency's to provide (ADR 0004), and the template makes them NOT
       NULL. In the copy they may be empty; the report lists every layer owing them (decided 2026-11-26).

Only Records (the agencies' own points) go into SiteStructureAddressPoint; Gap-fill candidates stay in the GeoParquet
for review. The GeoParquet stays the full Package (uid, gers_id, derived ranges ...); this is NENA's fields alone.
"""
import argparse
import glob
import json
import os
import re
import shutil
import sqlite3

from . import db, nena

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nena", "templates",
                        "NG911_GISDataModelTemplate_v3.0.gpkg")
# NENA layer -> the Package file it is in
FILES = {
    "SiteStructureAddressPoint": "site_structure_address_point", "RoadCenterLine": "road_centerline",
    "A2Polygon": "a2_polygon", "A3Polygon": "a3_polygon", "PsapPolygon": "psap_polygon",
    "PolicePolygon": "police_polygon", "FirePolygon": "fire_polygon", "EmsPolygon": "ems_polygon",
    "ProvisioningPolygon": "provisioning_polygon", "DistanceMarkerPoint": "distance_marker_point",
    "LocationMarkerPoint": "location_marker_point",
}
# What makes pieces of a polygon clipped at county seams one feature: the agency's feature for service layers, the
# municipality for A3 (A2 is the county itself)
SEAM_KEYS = {**{f"{n}Polygon": ("source", "source_id") for n in ("Psap", "Police", "Fire", "Ems", "Provisioning")},
             "A3Polygon": ("source_code",)}
AGENCY_FIELDS = {f: f for f in ("Agency_ID", "ServiceURI", "AVcard_URI")}


class ExportError(SystemExit):
    pass


def relax(path, owed):
    """Let the agency-owned fields be empty in the copy: their CHECK accepts NULL and NOT NULL comes off."""
    con = sqlite3.connect(path)
    for (table,) in con.execute("SELECT table_name FROM gpkg_contents").fetchall():
        sql = con.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()[0]
        new = sql
        for f in owed:
            new = re.sub(rf"\[{f}\] (\w+(?:\(\d+\))?) check\(typeof\(\[{f}\]\) = 'text' and (.*?)\) not null",
                         rf"[{f}] \1 check((typeof([{f}]) = 'text' or typeof([{f}]) = 'null') and \2)", new)
        if new != sql:
            con.execute("PRAGMA writable_schema = ON")
            con.execute("UPDATE sqlite_master SET sql = ? WHERE type = 'table' AND name = ?", (new, table))
            con.execute("PRAGMA writable_schema = OFF")
    con.commit()
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    con.close()


def _sql_type(dtype):
    """The DuckDB type of a template field's dtype as pyogrio reports it."""
    d = str(dtype)
    return ("TIMESTAMP" if d.startswith("datetime") else "BIGINT" if d.startswith("int")
            else "DOUBLE" if d.startswith("float") else "VARCHAR")


def _select(c, layer, files, fields, country, dtypes):
    """The SQL for one layer across the Packages: NENA's fields under NENA's names, geometry as WKB in the
    template's type, a polygon split at a county seam merged into one."""
    by_name = {f["name"]: f for f in nena.layer_fields(layer, country)}
    have = {r[0] for r in c.execute(
        f"DESCRIBE SELECT * FROM read_parquet({files}, union_by_name = true)").fetchall()}
    cols = []
    for tf, dt in zip(fields, dtypes):
        ours = next((n for n, f in by_name.items() if f["nena"].lower() == tf.lower()), None)
        if ours in have:
            f = by_name[ours]
            v = f"try_cast({ours} AS TIMESTAMP)" if f["type"] == "DATETIME" else ours
            cols.append((tf, v, f))
        else:
            cols.append((tf, f"NULL::{_sql_type(dt)}", by_name.get(ours)))
    where = "WHERE status = 'record'" if layer == "SiteStructureAddressPoint" else ""
    src = f"(SELECT * FROM read_parquet({files}, union_by_name = true) {where})"
    key = SEAM_KEYS.get(layer) if layer.endswith("Polygon") else None
    if key and set(key) <= have:
        # each piece is the same agency feature; the merged one keeps the largest piece's fields (and NGUID)
        k = ", ".join(key)
        src = f"""(SELECT arg_max(COLUMNS(* EXCLUDE (geom, {k})), ST_Area(geom)), {k}, ST_Union_Agg(geom) AS geom
                   FROM {src} GROUP BY {k})"""
    return cols, src


def check(c, layer, cols, src):
    """{field: {"too_long": n, "outside_domain": n, "examples": [...]}} for one layer, before it is written."""
    doms = nena.domains()
    out = {}
    for tf, v, f in cols:
        if f is None or v.startswith("NULL"):
            continue
        problems = {}
        if f.get("length") and f["type"] not in ("INTEGER", "REAL", "DATETIME"):
            n = c.execute(f"SELECT count(*) FROM {src} WHERE length({v}::VARCHAR) > {int(f['length'])}").fetchall()[0][0]
            if n:
                problems["too_long"] = n
        dom = doms.get(f.get("domain") or "")
        if isinstance(dom, list) and dom and f["type"] not in ("INTEGER", "REAL", "DATETIME"):
            values = ", ".join(db.quote(str(x)) for x in dom)
            rows = c.execute(f"SELECT {v}::VARCHAR, count(*) FROM {src} WHERE {v} IS NOT NULL "
                             f"AND {v}::VARCHAR NOT IN ({values}) GROUP BY 1 ORDER BY 2 DESC").fetchall()
            if rows:
                problems["outside_domain"] = sum(n for _, n in rows)
                problems["examples"] = [x for x, _ in rows[:5]]
        if problems:
            out[tf] = problems
    return out


def export(job_dir, out_path, country="US"):
    """Every Package under job_dir (release=<r>/<job>) into one GeoPackage at out_path; returns the report."""
    import pyogrio  # the export's only extra dependency (pip install open-ng911-addresses[export])

    packages = sorted(d for d in glob.glob(os.path.join(job_dir, "*")) if os.path.isfile(os.path.join(d, "manifest.json")))
    if not packages:
        raise ExportError(f"No Packages under {job_dir}")
    shutil.copyfile(TEMPLATE, out_path)
    relax(out_path, AGENCY_FIELDS)
    c = db.connect(s3=False)
    report = {"template": os.path.basename(TEMPLATE), "packages": [os.path.basename(p) for p in packages],
              "layers": {}, "agency_owed": {}, "problems": {}}
    for layer, stem in FILES.items():
        paths = [os.path.join(p, f"{stem}.parquet") for p in packages if os.path.exists(os.path.join(p, f"{stem}.parquet"))]
        if not paths:
            continue
        info = pyogrio.read_info(out_path, layer=layer)
        files = "[" + ", ".join(db.quote(p) for p in paths) + "]"
        cols, src = _select(c, layer, files, list(info["fields"]), country, list(info["dtypes"]))
        problems = check(c, layer, cols, src)
        if problems:
            report["problems"][layer] = problems
        geom = info["geometry_type"]
        g = "geom"
        if geom.startswith("Multi"):
            g = f"ST_Multi({g})"
        if geom.endswith(" Z"):
            g = f"ST_Force3DZ({g}, 0)"
        sel = ", ".join(f'{v} AS "{tf}"' for tf, v, _ in cols)
        t = c.sql(f"SELECT {sel}, ST_AsWKB({g}) AS wkb FROM {src}").to_arrow_table()
        n = t.num_rows
        report["layers"][layer] = n
        owed = [tf for tf in AGENCY_FIELDS if tf in info["fields"]]
        if owed and n:
            report["agency_owed"][layer] = {tf: n for tf in owed}
        if any(p.get("too_long") for p in problems.values()):
            continue
        if n:
            pyogrio.write_arrow(t, out_path, layer=layer, driver="GPKG", append=True, geometry_name="wkb",
                                geometry_type=geom, crs="EPSG:4326")
    with open(out_path + ".report.json", "w") as f:
        json.dump(report, f, indent=2)
    long = {lyr: [f for f, p in ps.items() if p.get("too_long")] for lyr, ps in report["problems"].items()}
    long = {k: v for k, v in long.items() if v}
    if long:
        raise ExportError(f"values too long for NENA's fields, not written: {long} (see {out_path}.report.json)")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("job_dir", help="data/output/release=<r>/<job>: the job's Packages")
    ap.add_argument("out", help="the GeoPackage to write")
    ap.add_argument("--country", default="US")
    a = ap.parse_args()
    r = export(a.job_dir, a.out, a.country)
    print(json.dumps({"layers": r["layers"], "problems": r["problems"], "agency_owed": r["agency_owed"]}, indent=2))


if __name__ == "__main__":
    main()
