"""
Packages: one per county (in Canada, census division), each the NG9-1-1 dataset for that area (GLOSSARY.md).

Phase 1 writes the SiteStructureAddressPoint layer. Road centerlines (government centerlines through the
OpenAddresses registry, TIGER as the fallback) and boundaries follow; Overture's ODbL themes never go into
a core layer, and the OSM-derived Review layer is built only for opted-in Packages (ADR 0007).

    <out>/release=<release>/<job>/<geoid>/
        site_structure_address_point.parquet   GeoParquet, NENA-STA-006.3 fields + uid, gers_id, status
        manifest.json                          counts, field fill, sources and their licenses, opt-in state
"""
import json
import os

from . import ids
from .nena import SSAP_REQUIRED

SSAP_FIELDS = ("discrpagid", "dateupdate", "nguid", "country", "a1", "a2", "a3", "add_number", "addnum_suf",
               "st_predir", "st_pretyp", "st_name", "st_postyp", "st_posdir", "unit", "post_comm", "post_code",
               "placement")


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


def write(c, job, jurisdiction, release, out_dir):
    root = os.path.join(out_dir, f"release={release}", job.id)
    summaries = []
    sources = [{"key": s.key, "agency": s.agency, "layer": s.layer, "openaddresses": s.openaddresses,
                "license_status": s.license_status, "license_url": s.license_url, "attribution": s.attribution}
               for s in jurisdiction.sources]
    fill_sql = ", ".join(f"count({f}) AS {f}" for f in SSAP_FIELDS)
    for geoid, name, domain, opted, authority in c.execute(
            "SELECT geoid, name, domain, opted_in, authority FROM package_area JOIN package_domain USING (geoid) ORDER BY 1").fetchall():
        d = os.path.join(root, geoid)
        os.makedirs(d, exist_ok=True)
        c.execute(f"COPY (SELECT * EXCLUDE (geoid) FROM ssap WHERE geoid = '{geoid}' ORDER BY uid) "
                  f"TO '{os.path.join(d, 'site_structure_address_point.parquet')}' (FORMAT parquet, COMPRESSION zstd)")
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
            "nena": {"standard": "NENA-STA-006.3-2026", "layers": ["SiteStructureAddressPoint"],
                     "mandatory_fields": list(SSAP_REQUIRED)},
            "recipient": authority, "opted_in": opted, "nguid_domain": domain,
            "distribution": ("handed to the opted-in 911 authority" if opted else
                             "built for the public scorecard only; not handed out until the 911 authority opts in (ADR 0003)"),
            "rows": rows, **counts,
            "record_gers_coverage": round(counts["records_with_gers_id"] / counts["records"], 4) if counts["records"] else None,
            "field_fill": {k: round(int(v) / rows, 4) if rows else None for k, v in stats.items()},
            "sources": sources,
            "gap_fill_licenses": dict(c.execute(f"""SELECT coalesce(source_license, 'unstated'), count(*) FROM ssap
                WHERE geoid = '{geoid}' AND status = 'gap_fill_candidate' GROUP BY 1 ORDER BY 2 DESC""").fetchall()),
        }
        with open(os.path.join(d, "manifest.json"), "w") as f:
            json.dump(manifest, f, indent=2)
        summaries.append(manifest)
    return root, summaries
