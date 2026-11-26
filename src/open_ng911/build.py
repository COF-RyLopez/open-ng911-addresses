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
  7. Write one Package per county or census division, the ledger and a job summary; fail the job if a
     NENA mandatory field isn't filled on every row.
"""
import argparse
import datetime
import json
import os
import sys

from . import boundaries, db, ids, lineage, matcher, nena, overture_release, package, registry, roads, street
from .sources import centerlines, openaddresses, overture, statcan, tiger

LIVE_LOADERS = {
    # counties from TIGER in the US, census divisions from StatCan in Canada (ADR 0006)
    "package_area": lambda c, job, jur, work: (statcan if job.country == "CA" else tiger).load_package_area(c, job, work),
    "municipality": lambda c, job, jur, work: boundaries.load_municipality(c, job, work),
    "agency_addr": lambda c, job, jur, work: openaddresses.load_agency_addr(c, jur, work),
    "overture_addr": lambda c, job, jur, work: overture.load_overture_addr(c, jur, work),
    # RoadCenterline (roads.py)
    "gov_roads": centerlines.load_government,
    "tiger_roads": centerlines.load_tiger,
    "overture_segment": lambda c, job, jur, work: overture.load_overture_segment(c, jur, work),
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


def assemble_ssap(c, job, jurisdiction, updated):
    source = next(s for s in jurisdiction.sources if s.layer == "addresses")
    c.execute(f"""CREATE OR REPLACE TABLE ssap AS
        WITH rec AS (
            SELECT a.address_uid AS uid, m.gers_id, 'record' AS status, a.source_key AS source,
                   a.source_id, '{source.license_status}' AS source_license, 'agency_record' AS link_method,
                   m.distance_m AS match_distance_m, m.street_key_match, a.site_type AS source_site_type,
                   a.number, a.ps, a.unit, a.city, a.postcode, a.geom, a.geoid
            FROM agency_addr a LEFT JOIN address_match m USING (address_uid)),
        gap AS (
            SELECT u.address_uid AS uid, o.gers_id, 'gap_fill_candidate' AS status, 'overture' AS source,
                   o.source_record_id AS source_id, o.source_license, u.link_method,
                   NULL::DOUBLE AS match_distance_m, NULL::BOOLEAN AS street_key_match,
                   NULL::VARCHAR AS source_site_type,
                   o.number, o.ps, o.unit, o.postal_city AS city, o.postcode, o.geom, o.geoid
            FROM overture_addr o JOIN overture_uid u USING (gers_id)
            WHERE o.gers_id NOT IN (SELECT gers_id FROM address_match)
              -- two Overture IDs linked to one UID: keep one row per UID
            QUALIFY row_number() OVER (PARTITION BY u.address_uid ORDER BY o.gers_id) = 1),
        x AS (
            SELECT *, nena_type_word(ps.type) AS postyp FROM (SELECT * FROM rec UNION ALL SELECT * FROM gap)
            WHERE uid NOT IN (SELECT uid FROM rec) OR status = 'record'),
        y AS (SELECT *, nena_pretype_raw(ps.name, postyp) AS pre_raw FROM x)
        SELECT y.uid, y.gers_id, y.status, y.source, y.source_id, y.source_license, y.link_method,
               y.match_distance_m, y.street_key_match, y.source_site_type,
               d.domain AS discrpagid,
               '{updated}' AS dateupdate,
               build_nguid('SSAP', y.uid, d.domain) AS nguid,
               '{job.country}' AS country,
               '{job.code}' AS a1,
               p.name AS a2,
               NULL::VARCHAR AS a3,  -- set from the municipality boundaries (boundaries.assign_a3)
               try_cast(nullif(regexp_extract(y.number, '^[0-9]+'), '') AS INTEGER) AS add_number,
               nullif(trim(regexp_replace(y.number, '^[0-9]+', '')), '') AS addnum_suf,
               nena_dir_word(y.ps.predir) AS st_predir,
               nena_pretype_word(y.pre_raw) AS st_pretyp,
               nena_st_name(y.ps.name, y.pre_raw) AS st_name,
               y.postyp AS st_postyp,
               nena_dir_word(y.ps.posdir) AS st_posdir,
               y.unit,
               upper(y.city) AS post_comm,
               y.postcode AS post_code,
               'Unknown' AS placement,  -- no source in the pilot states a placement method yet
               y.geoid, y.geom
        FROM y JOIN package_domain d USING (geoid) JOIN package_area p USING (geoid)""")


def gate(c):
    """NENA mandatory fields filled on every row; returns the failures."""
    fails = []
    for f in nena.SSAP_REQUIRED:
        missing = c.execute(f"SELECT count(*) FROM ssap WHERE {f} IS NULL").fetchall()[0][0]
        if missing:
            fails.append(f"{f}: {missing:,} rows empty")
    dup = c.execute("SELECT count(*) - count(DISTINCT nguid) FROM ssap").fetchall()[0][0]
    if dup:
        fails.append(f"nguid: {dup:,} duplicates")
    return fails


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
    ids.install(c)
    boundaries.install(c)
    updated = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

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
    boundaries.create_layers(c, job, updated)
    roads.build(c, job, jur, work_dir, loaders, updated)

    root, summaries = package.write(c, job, jur, release, out_dir)
    road_stats = roads.write(c, job, root, release)
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
               "agency_points_id_shared": c.execute(
                   "SELECT count(*) FROM agency_addr WHERE id_shared").fetchall()[0][0],
               "overture_link_methods": links, "a3": boundaries.summary(c),
               "road_segments": sum(r["rows"] for r in road_stats.values()),
               "road_segments_with_gers_id": sum(r["with_gers_id"] for r in road_stats.values()),
               "road_sources": dict(c.execute("SELECT road_source, count(*) FROM rcl GROUP BY 1 ORDER BY 1").fetchall()),
               "gate_failures": fails,
               "by_package": {s["package"]: {k: s[k] for k in ("name", "rows", "records", "gap_fill_candidates",
                                                               "record_gers_coverage")}
                              | roads.package_summary(road_stats[s["package"]]) for s in summaries}}
    with open(os.path.join(root, "job.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps({k: v for k, v in summary.items() if k != "by_package"}, indent=2))
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
