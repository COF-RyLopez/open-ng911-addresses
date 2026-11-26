"""
One build job: a state or province, end to end, on one DuckDB connection.

    python -m open_ng911.build --job us-vt [--out data/output] [--ledger <previous ledger parquet>]

Steps:
  1. Resolve the Overture release (overture_release.py) and read the job's registry.
  2. Load the Package areas and municipalities, the Source agency's address points and Overture's addresses (sources/).
  3. Parse every street the same way (street.py) and match Records to Overture one to one (matcher.py).
  4. Give each Overture address an Address UID through the lineage ledger (lineage.py).
  5. Assemble the SiteStructureAddressPoint layer: every Record, plus Overture addresses no Record matched
     as Gap-fill candidates (ADR 0001), with NGUIDs built from the Address UID (ADR 0002), and give each its
     A3 from the municipality boundaries; build the A2 and A3 boundary layers (boundaries.py).
  6. Build the RoadCenterline layer: government centerlines, TIGER where a Package has none, Overture GERS
     IDs attached (roads.py).
  7. Count where the government roads and Overture / the national road layer disagree (upstream.py), and list
     which government sources could stand in for Overture's ODbL themes in each Package (odbl_inventory.py).
  8. Write one Package per county or census division, the ledger and a job summary; fail the job if a
     NENA mandatory field isn't filled on every row.
"""
import argparse
import json
import os
import sys

from . import (
    boundaries,
    coverage,
    db,
    fieldmap,
    ids,
    layers,
    lineage,
    matcher,
    nena,
    odbl_inventory,
    overture_release,
    package,
    registry,
    roads,
    street,
    upstream,
)
from .sources import centerlines, openaddresses, overture

# Every loader is loader(c, job, jurisdiction, work_dir) and creates or fills one table; tests swap in fixtures.
LIVE_LOADERS = {
    # the country's boundaries (registry.COUNTRIES): TIGER in the US, StatCan in Canada (ADR 0006)
    "package_area": boundaries.load_package_area,
    "municipality": boundaries.load_municipality,
    "agency_addr": openaddresses.load_agency_addr,
    "overture_addr": overture.load_overture_addr,
    # RoadCenterline (roads.py): road_seg from the government sources, then TIGER where a Package has none
    "gov_roads": centerlines.load_government,
    "tiger_roads": centerlines.load_tiger,
    "overture_segment": overture.load_overture_segment,
    # upstream counts (upstream.py): national_seg, the national road layer to compare government roads with
    "national_roads": centerlines.load_national_reference,
    # PSAP, police, fire and EMS boundaries, provisioning, distance and location markers (layers.py)
    "nena_layers": layers.load_sources,
}


def prepare(c):
    """Parsed streets, keys and Package GEOIDs on both address tables."""
    c.execute("""CREATE OR REPLACE TABLE agency_addr AS
        SELECT a.* EXCLUDE (geoid), p.geoid FROM (SELECT *, NULL::VARCHAR AS geoid FROM agency_addr) a
        LEFT JOIN package_area p ON ST_Intersects(p.geom, a.geom)
        QUALIFY row_number() OVER (PARTITION BY a.address_uid ORDER BY p.geoid) = 1""")
    # a point just outside every Package (a shoreline or border address off the generalised TIGER outline) goes
    # to the nearest Package within about 1 km; one farther out (bad coordinates, across the line) is counted
    c.execute("""UPDATE agency_addr a SET geoid = n.geoid FROM (
            SELECT a.address_uid, p.geoid FROM agency_addr a JOIN package_area p
              ON a.geoid IS NULL AND ST_DWithin(p.geom, a.geom, 0.01)
            QUALIFY row_number() OVER (PARTITION BY a.address_uid ORDER BY ST_Distance(p.geom, a.geom), p.geoid) = 1) n
        WHERE a.address_uid = n.address_uid""")
    c.execute("""INSERT INTO agency_dropped SELECT source_key, 'outside_packages', site_type, count(*)
                 FROM agency_addr WHERE geoid IS NULL GROUP BY ALL""")
    c.execute("DELETE FROM agency_addr WHERE geoid IS NULL")
    for t in ("agency_addr", "overture_addr"):
        c.execute(f"""CREATE OR REPLACE TABLE {t} AS
            SELECT *, parsed_street_key(ps) AS skey FROM (SELECT *, parse_street(street) AS ps FROM {t})""")


SSAP = "SiteStructureAddressPoint"
# How the pipeline fills a SiteStructureAddressPoint field no Source maps (the coverage report's `derived`)
SSAP_DERIVED = {
    "discrpagid": "the Package's NGUID domain (a placeholder until the authority opts in, ADR 0003)",
    "dateupdate": "build time, where the Source maps no edit date",
    "nguid": "Address UID under the Package's domain (ADR 0002)",
    "country": "the job", "a1": "the job", "a2": "the Package (A2Polygon)",
    "a3": "the municipality the point falls in (A3Polygon)",
    "add_number": "OpenAddresses number", "addnum_suf": "OpenAddresses number",
    **{p: "OpenAddresses street, parsed (street.py)" for p in ("st_predir", "st_pretyp", "st_name", "st_postyp",
                                                               "st_posdir")},
    "unit": "OpenAddresses unit", "unitpretyp": "OpenAddresses unit, split", "unitvalue": "OpenAddresses unit, split",
    "post_comm": "OpenAddresses city", "post_code": "OpenAddresses postcode",
    "placement": "'Unknown' where the Source states no method",
    "longitude": "the point", "latitude": "the point",
}


def assemble_ssap(c, job, jurisdiction, updated, table="ssap", native=True):
    """The SiteStructureAddressPoint layer: every NENA field of the job's country, from the Source's own field
    where its registry `nena` table maps one (fieldmap.py), else from the OpenAddresses fields and the parse.
    native=False builds the same layer from the OpenAddresses fields alone (the coverage report's `before`)."""
    source = jurisdiction.sources_for("addresses")[0]
    country = job.country
    ncols = fieldmap.column_names(SSAP, country)
    rec_n = ", ".join(f"a.{n}" if native else f"NULL::{t} AS {n}" for n, t in
                      zip(ncols, _types(SSAP, country)))
    gap_n = ", ".join(f"NULL::{t} AS {n}" for n, t in zip(ncols, _types(SSAP, country)))
    parsed = {"st_predir": "nena_dir_word(y.ps.predir)", "st_pretyp": "nena_pretype_word(y.pre_raw)",
              "st_name": "nena_st_name(y.ps.name, y.pre_raw)", "st_postyp": "y.postyp",
              "st_posdir": "nena_dir_word(y.ps.posdir)"}
    own_unit = "y.n_unitpretyp IS NOT NULL OR y.n_unitvalue IS NOT NULL"
    value = {
        "discrpagid": "d.domain",
        "dateupdate": f"coalesce(y.n_dateupdate, '{updated}')",
        "nguid": "build_nguid('SSAP', y.uid, d.domain)",
        "country": f"'{job.country}'", "a1": f"'{job.code}'", "a2": "p.name",
        "a3": "NULL::VARCHAR",  # set from the municipality boundaries (boundaries.assign_a3)
        "add_number": "coalesce(y.n_add_number, try_cast(nullif(regexp_extract(y.number, '^[0-9]+'), '') AS INTEGER))",
        # '30B': the Source's number field keeps the suffix, and NENA's AddNum_Suf takes it where none is mapped
        "addnum_suf": "coalesce(y.n_addnum_suf, nullif(trim(regexp_replace(y.number, '^[0-9]+', '')), ''))",
        # CLDXF-CA keeps one Unit; CLDXF-US splits it into UnitPreTyp + UnitValue ('Apartment' + '4B')
        "unit": "coalesce(y.n_unit, y.unit)",
        "unitpretyp": f"CASE WHEN {own_unit} THEN y.n_unitpretyp ELSE nena_unit_type(coalesce(y.n_unit, y.unit)) END",
        "unitvalue": f"CASE WHEN {own_unit} THEN y.n_unitvalue ELSE nena_unit_value(coalesce(y.n_unit, y.unit)) END",
        "post_comm": "coalesce(y.n_post_comm, upper(y.city))",
        "post_code": "coalesce(y.n_post_code, y.postcode)",
        "placement": "coalesce(y.n_placement, 'Unknown')",
        "longitude": "round(ST_X(y.geom), 7)", "latitude": "round(ST_Y(y.geom), 7)",
    }
    street = dict(zip(fieldmap.STREET_PARTS, fieldmap.native_street("y", parsed)))
    out = []
    for f in nena.layer_fields(SSAP, country):
        n = f["name"]
        out.append(street[n] if n in street else f"{value.get(n, 'y.n_' + n)} AS {n}")
    c.execute(f"""CREATE OR REPLACE TABLE {table} AS
        WITH rec AS (
            SELECT a.address_uid AS uid, m.gers_id, 'record' AS status, a.source_key AS source,
                   a.source_id, '{source.license_status}' AS source_license, 'agency_record' AS link_method,
                   m.distance_m AS match_distance_m, m.street_key_match, a.site_type AS source_site_type,
                   a.number, a.ps, a.unit, a.city, a.postcode, a.geom, a.geoid, {rec_n}
            FROM agency_addr a LEFT JOIN address_match m USING (address_uid)),
        gap AS (
            SELECT u.address_uid AS uid, o.gers_id, 'gap_fill_candidate' AS status, 'overture' AS source,
                   o.source_record_id AS source_id, o.source_license, u.link_method,
                   NULL::DOUBLE AS match_distance_m, NULL::BOOLEAN AS street_key_match,
                   NULL::VARCHAR AS source_site_type,
                   o.number, o.ps, o.unit, o.postal_city AS city, o.postcode, o.geom, o.geoid, {gap_n}
            FROM overture_addr o JOIN overture_uid u USING (gers_id)
            WHERE o.gers_id NOT IN (SELECT gers_id FROM address_match)
              -- two Overture IDs linked to one UID: keep one row per UID
            QUALIFY row_number() OVER (PARTITION BY u.address_uid ORDER BY o.gers_id) = 1),
        x AS (
            SELECT *, nena_type_word(ps.type) AS postyp FROM (SELECT * FROM rec UNION ALL SELECT * FROM gap)
            WHERE uid NOT IN (SELECT uid FROM rec) OR status = 'record'),
        y AS (SELECT *, nena_pretype_raw(ps.name, postyp) AS pre_raw, {fieldmap.npre_raw_sql('x')} FROM x)
        SELECT y.uid, y.gers_id, y.status, y.source, y.source_id, y.source_license, y.link_method,
               y.match_distance_m, y.street_key_match, y.source_site_type,
               {", ".join(out)},
               y.geoid, y.geom
        FROM y JOIN package_domain d USING (geoid) JOIN package_area p USING (geoid)""")


def _types(layer, country):
    return [fieldmap.SQL_TYPE.get(f["type"], "VARCHAR") for f in fieldmap.fields(layer, country).values()]


def coverage_spec(c, job, jurisdiction):
    """{NENA layer: section() arguments}: every layer of the standard, with the table it was built into (None:
    not built), the Source fields mapped to it and how the pipeline fills the rest."""
    k = registry.country(job)
    boundary = {f: k.a2_source for f in ("discrpagid", "dateupdate", "nguid", "country", "a1", "a2")}
    built = {SSAP: ("ssap", SSAP_DERIVED), roads.RCL: ("rcl", roads.RCL_DERIVED),
             "A2Polygon": ("a2_polygon", boundary), "A3Polygon": ("a3_polygon", {**boundary, "a3": k.a3_source})}
    for key, table in layers.TABLE.items():
        d = layers.derived(key)
        if key == "provisioning":
            d = {**d, "geometry": "the Package area where no provisioning Source covers it"}
        built[layers.nena_layer(key)] = (table, d)
    out = {}
    for layer in nena.schema()["layers"]:
        table, derived = built.get(layer, (None, {}))
        out[layer] = {"table": table, "sources": coverage.layer_sources(jurisdiction, layer), "derived": derived,
                      "rejected": fieldmap.rejected(c, layer)}
    return out


def ssap_before(c, job, jurisdiction, updated):
    """{field: fill} of the layer built from the OpenAddresses fields alone (A3 is the same either way)."""
    assemble_ssap(c, job, jurisdiction, updated, "ssap_oa_only", native=False)
    c.execute("UPDATE ssap_oa_only o SET a3 = s.a3 FROM ssap s WHERE o.uid = s.uid")
    names = [f["name"] for f in nena.layer_fields(SSAP, job.country)]
    _, fill = coverage.fills(c, "ssap_oa_only", names)
    c.execute("DROP TABLE ssap_oa_only")
    return fill


def gate(c):
    """NENA mandatory fields filled on every row; returns the failures."""
    return db.gate(c, "ssap", nena.SSAP_REQUIRED, "nguid")


def run(job_id, out_dir, work_dir=None, ledger_path=None, loaders=None, registry_dir=registry.REGISTRY_DIR,
        release=None, c=None):
    job = registry.job(job_id, registry_dir)
    jur = registry.jurisdiction(job, registry_dir)
    release = release or overture_release.release_id()
    loaders = {**LIVE_LOADERS, **(loaders or {})}
    work_dir = work_dir or os.path.join(out_dir, "_work", job.id)
    os.makedirs(work_dir, exist_ok=True)
    c = c or db.connect()
    street.install(c)
    nena.install(c, job.country)
    fieldmap.install(c, job.country)
    ids.install(c)
    boundaries.install(c)
    db.create_dropped(c)
    updated = db.now()

    print(f"[{job.id}] {job.name}, Overture {release}")
    for table in ("package_area", "municipality", "agency_addr", "overture_addr"):  # overture_addr reads package_area's extent
        loaders[table](c, job, jur, work_dir)
    prepare(c)
    package.create_domains(c, job, jur)
    matched = matcher.match(c)
    print(f"[{job.id}] {matched:,} Records matched to an Overture address")
    lineage.load_previous(c, ledger_path)
    links = lineage.link(c, release)
    print(f"[{job.id}] Overture address UIDs by link method: {links}")
    assemble_ssap(c, job, jur, updated)
    boundaries.assign_a3(c)
    before = {SSAP: ssap_before(c, job, jur, updated)}
    boundaries.create_layers(c, job, updated)
    roads.build(c, job, jur, work_dir, loaders, updated)
    before[roads.RCL] = roads.rcl_before(c, job, updated)
    loaders["nena_layers"](c, job, jur, work_dir)
    layers.build(c, job, jur, updated)
    national = upstream.build(c, job, jur, work_dir, loaders)

    spec = coverage_spec(c, job, jur)
    root, summaries = package.write(c, job, jur, release, out_dir, national, spec)
    c.execute(f"COPY (SELECT * FROM ledger ORDER BY address_uid, first_release) TO "
              f"'{os.path.join(root, 'address_lineage.parquet')}' (FORMAT parquet)")
    fails = gate(c) + boundaries.gate(c) + roads.gate(c)
    summary = {"job": job.id, "overture_release": release, "built": updated, "packages": len(summaries),
               "rows": sum(s["rows"] for s in summaries), "records": sum(s["records"] for s in summaries),
               "records_with_gers_id": sum(s["records_with_gers_id"] for s in summaries),
               "gap_fill_candidates": sum(s["gap_fill_candidates"] for s in summaries),
               "agency_points_excluded": {t: n for _, t, n in c.execute(
                   "SELECT * FROM agency_excluded ORDER BY n DESC").fetchall()},
               "agency_points_dropped": dict(c.execute(
                   "SELECT reason, sum(n)::BIGINT FROM agency_dropped GROUP BY 1 ORDER BY 2 DESC").fetchall()),
               "agency_points_dropped_by_site_type": {f"{r}: {t}": n for r, t, n in c.execute(
                   "SELECT reason, site_type, n FROM agency_dropped WHERE site_type IS NOT NULL "
                   "ORDER BY n DESC LIMIT 25").fetchall()},
               # every other layer's left-out features: {layer: {reason: n}} (db.drop)
               "features_dropped": db.dropped(c),
               "agency_points_id_shared": c.execute(
                   "SELECT count(*) FROM agency_addr WHERE id_shared").fetchall()[0][0],
               "overture_link_methods": links, "a3": boundaries.summary(c),
               "road_segments": sum(s["road_centerline"]["rows"] for s in summaries),
               "road_segments_with_gers_id": sum(s["road_centerline"]["with_gers_id"] for s in summaries),
               "road_sources": dict(c.execute("SELECT road_source, count(*) FROM rcl GROUP BY 1 ORDER BY 1").fetchall()),
               "upstream": upstream.job_totals(s["upstream"] for s in summaries),
               "odbl_replacement": odbl_inventory.job_totals(s["odbl_replacement"] for s in summaries),
               "nena_coverage": {layer: coverage.section(c, layer, job.country, before=before.get(layer), **kw)
                                 for layer, kw in spec.items()},
               "native_fields": db.rows(c, "SELECT * FROM native_fields ORDER BY layer, source_key, field"),
               "gate_failures": fails,
               "by_package": {s["package"]: {k: s[k] for k in ("name", "rows", "records", "gap_fill_candidates",
                                                               "record_gers_coverage")}
                              | roads.package_summary(s["road_centerline"]) for s in summaries}}
    with open(os.path.join(root, "job.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps({k: v for k, v in summary.items() if k not in ("by_package", "nena_coverage")}, indent=2))
    # one line per layer and field, so a build log shows the coverage without the artifact
    print(f"[{job.id}] NENA coverage (filled/partial/no_source, before -> after): {coverage.brief(summary['nena_coverage'])}")
    # the built layers' statuses, field by field, for reading coverage out of a CI log (job.json has it all)
    compact = {layer: {n: f["status"][0] + ("!" if f.get("required") else "")
                          + ("<" + coverage.status(f["before"])[0] if "before" in f else "")
                       for n, f in s["fields"].items()} for layer, s in summary["nena_coverage"].items() if s["built"]}
    print(f"[{job.id}] NENA coverage by field (f filled, p partial, n no_source; ! Required; <before): "
          + json.dumps(compact, separators=(",", ":")))
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--job", required=True, help="a job id from registry/jobs.toml, e.g. us-vt")
    p.add_argument("--out", default="data/output")
    p.add_argument("--ledger", help="the previous release's address_lineage.parquet, to carry Address UIDs forward")
    a = p.parse_args(argv)
    summary = run(a.job, a.out, ledger_path=a.ledger)
    if summary["gate_failures"]:
        sys.exit("Gate failed: " + "; ".join(summary["gate_failures"]))


if __name__ == "__main__":
    main()
