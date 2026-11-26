"""
Packages: one per county (in Canada, census division), each the NG9-1-1 dataset for that area (GLOSSARY.md).

This module writes every Package: the SiteStructureAddressPoint layer, then each layer module's files and
manifest section (boundaries.py A2/A3, roads.py RoadCenterline, upstream.py counts, odbl_inventory.py), and the
manifest once. Overture's ODbL themes never go into a core layer, and the OSM-derived Review layer is built only
for opted-in Packages (ADR 0007).

    <out>/release=<release>/<job>/<geoid>/
        site_structure_address_point.parquet   GeoParquet, NENA-STA-006.3 fields + uid, gers_id, status
        a2_polygon.parquet                     A2Polygon: the county / census division, NENA fields + source_code
        a3_polygon.parquet                     A3Polygon: its municipalities clipped to it, NENA fields + source_code
        road_centerline.parquet                RoadCenterline: NENA RCL fields + uid, gers_id, road_source
        road_gers_crosswalk.parquet            segment UID x GERS ID, overlap, primary flag
        manifest.json                          counts, field fill, sources and their licenses, opt-in state
        domains.json                           the value domains the layers use: NENA's, and CLDXF-CA's in Canada
"""
import json
import os

from . import boundaries, coverage, db, ids, layers, nena, odbl_inventory, registry, roads, upstream
from .nena import SSAP_REQUIRED


def package_key(job, geoid):
    return f"{job.id}-{geoid}"


def create_domains(c, job, jurisdiction):
    """package_domain(geoid, domain, opted_in): the NGUID domain each Package is built under."""
    rows = []
    for geoid, in c.execute("SELECT geoid FROM package_area ORDER BY 1").fetchall():
        a = jurisdiction.authority_for(geoid)
        opted = bool(a and a.opted_in)
        rows.append((geoid, a.domain if opted else ids.placeholder_domain(package_key(job, geoid)), opted,
                     a.name if a else None))
    c.execute("CREATE OR REPLACE TABLE package_domain (geoid VARCHAR, domain VARCHAR, opted_in BOOLEAN, authority VARCHAR)")
    c.executemany("INSERT INTO package_domain VALUES (?, ?, ?, ?)", rows)


def write(c, job, jurisdiction, release, out_dir, national, spec=None):
    """Every Package's layer files and its manifest.json, written once with every layer's section; returns the
    job folder and the manifests. national: the national road layer upstream.build compared with, or None.
    spec: build.coverage_spec, for each Package's `nena_coverage`."""
    root = os.path.join(out_dir, f"release={release}", job.id)
    summaries = []
    sources = [{"key": s.key, "agency": s.agency, "layer": s.layer, "openaddresses": s.openaddresses,
                "license_status": s.license_status, "license_url": s.license_url, "attribution": s.attribution}
               for s in jurisdiction.sources]
    ssap_fields = [f["name"] for f in nena.layer_fields("SiteStructureAddressPoint", job.country)]
    fill_sql = ", ".join(f"count({f}) AS {f}" for f in ssap_fields)
    # NENA-STA-006.3's domains, with Canada's beside them in a Canadian Package (ADR 0006)
    road_meta = db.rows(c, "SELECT * FROM road_source_meta ORDER BY source_key")
    catalogue = odbl_inventory.catalogue()
    values = registry.country(job).values
    domains = {"NENA-STA-006.3": nena.domains()}
    if values == "CLDXF-CA":
        domains["CLDXF-CA"] = nena.cldxf_ca()["domains"]
    for geoid, name, domain, opted, authority in c.execute(
            "SELECT geoid, name, domain, opted_in, authority FROM package_area JOIN package_domain USING (geoid) ORDER BY 1").fetchall():
        d = os.path.join(root, geoid)
        os.makedirs(d, exist_ok=True)
        c.execute(f"COPY (SELECT * EXCLUDE (geoid) FROM ssap WHERE geoid = '{geoid}' ORDER BY uid) "
                  f"TO '{os.path.join(d, 'site_structure_address_point.parquet')}' (FORMAT parquet, COMPRESSION zstd)")
        bounds = boundaries.write_package(c, job, geoid, d)
        road = roads.write_package(c, geoid, d, release, road_meta)
        other = layers.write_package(c, jurisdiction, geoid, d)
        res = c.execute(f"""SELECT count(*) AS rows,
                count(*) FILTER (status = 'record') AS records,
                count(*) FILTER (status = 'record' AND gers_id IS NOT NULL) AS records_with_gers_id,
                count(*) FILTER (status = 'gap_fill_candidate') AS gap_fill_candidates, {fill_sql}
            FROM ssap WHERE geoid = '{geoid}'""")
        stats = dict(zip([col[0] for col in res.description], res.fetchall()[0]))
        rows = int(stats.pop("rows"))
        counts = {k: int(stats.pop(k)) for k in ("records", "records_with_gers_id", "gap_fill_candidates")}
        manifest = {
            "package": package_key(job, geoid), "name": name, "job": job.id, "overture_release": release,
            "nena": {"standard": "NENA-STA-006.3-2026", "values": values,
                     "layers": ["SiteStructureAddressPoint", *bounds, "RoadCenterline",
                                *(k for k, v in other.items() if v["features"])],
                     "mandatory_fields": list(SSAP_REQUIRED), "rcl_mandatory_fields": list(nena.RCL_REQUIRED)},
            "recipient": authority, "opted_in": opted, "nguid_domain": domain,
            "distribution": ("handed to the opted-in 911 authority" if opted else
                             "built for the public scorecard only; not handed out until the 911 authority opts in (ADR 0003)"),
            "rows": rows, **counts,
            "record_gers_coverage": round(counts["records_with_gers_id"] / counts["records"], 4) if counts["records"] else None,
            "field_fill": {k: round(int(v) / rows, 4) if rows else None for k, v in stats.items()},
            "sources": sources,
            "boundaries": bounds,
            "gap_fill_licenses": dict(c.execute(f"""SELECT coalesce(source_license, 'unstated'), count(*) FROM ssap
                WHERE geoid = '{geoid}' AND status = 'gap_fill_candidate' GROUP BY 1 ORDER BY 2 DESC""").fetchall()),
            "road_centerline": road,
            "nena_layers": other,
            "nena_coverage": {layer: coverage.section(c, layer, job.country, where=f"geoid = '{geoid}'", **kw)
                              for layer, kw in (spec or {}).items()},
            "upstream": upstream.package_section(c, jurisdiction, geoid, national, release),
            "odbl_replacement": odbl_inventory.manifest_section(c, job, geoid, catalogue),
        }
        with open(os.path.join(d, "manifest.json"), "w") as f:
            json.dump(manifest, f, indent=2)
        with open(os.path.join(d, "domains.json"), "w", encoding="utf-8") as f:
            json.dump(domains, f, indent=1, ensure_ascii=False)
        summaries.append(manifest)
    return root, summaries
