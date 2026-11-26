"""
NENA boundary layers and the A3 of every address point.

NENA-STA-006.3 names the administrative levels A1 (state, province), A2 (county, census division),
A3 (municipality: city, town, village), A4 (unincorporated community) and A5 (neighbourhood). Each Package
gets two boundary layers, from government open data only (never OSM or Overture divisions, which are ODbL):

    A2Polygon   the Package area itself: the TIGER county (US) or StatCan census division (Canada)
    A3Polygon   the municipalities in the Package, clipped to it: TIGER county subdivisions in the strong MCD
                states, else incorporated places (sources/tiger.py); StatCan census subdivisions in Canada
                (sources/statcan.py)

Every SiteStructureAddressPoint gets its A3 from the municipality it falls in. A point in no incorporated
municipality gets 'Unincorporated' (CLDXF). A point within SNAP_DEG of an incorporated municipality's edge
takes that municipality, so a 1 m generalization gap doesn't make a town address 'Unincorporated'.

Boundary NGUIDs come from a UID of the boundary's own government code (boundary_uid), under the Package's
domain, the same as address NGUIDs (ADR 0002, 0003).
"""
import contextlib
import importlib
import uuid

import duckdb

from . import db, ids, registry

UNINCORPORATED = "Unincorporated"
SNAP_DEG = 0.00005  # about 5 m
# A clipped piece of a municipality smaller than this share of it is a sliver from the county edge, unless an
# address in the Package falls in it
SLIVER_SHARE = 0.001

def boundary_uid(source, code):
    """'us-a3', '5000710675' -> uuid5(NS, 'boundary:us-a3:5000710675')"""
    return str(uuid.uuid5(ids.NAMESPACE, f"boundary:{source}:{code}"))


def _source(job):
    return importlib.import_module(f".sources.{registry.country(job).boundaries}", __package__)


def load_package_area(c, job, jurisdiction, work_dir):
    """package_area: TIGER counties in the US, StatCan census divisions in Canada (registry.COUNTRIES)."""
    _source(job).load_package_area(c, job, work_dir)


def load_municipality(c, job, jurisdiction, work_dir):
    """municipality, the A3 units: TIGER county subdivisions or places, StatCan census subdivisions."""
    _source(job).load_municipality(c, job, work_dir)


def _has_municipalities(c):
    return c.execute("SELECT count(*) FROM municipality").fetchall()[0][0] > 0


def assign_a3(c):
    """Set ssap.a3 from the municipality each point falls in (or is within SNAP_DEG of)."""
    if not _has_municipalities(c):
        return
    c.execute(f"""CREATE OR REPLACE TEMP TABLE ssap_a3 AS
        WITH hit AS (
            SELECT s.uid, m.name, m.geoid AS mgeoid,
                   ST_Distance(m.geom, s.geom) AS d,
                   -- a county subdivision nests in its county: prefer the one whose code starts with the Package's
                   starts_with(m.geoid, s.geoid) AS nests
            FROM ssap s JOIN municipality m
              ON m.incorporated AND ST_DWithin(m.geom, s.geom, {SNAP_DEG}))
        SELECT uid, name AS a3, mgeoid FROM hit
        QUALIFY row_number() OVER (PARTITION BY uid ORDER BY d, nests DESC, mgeoid) = 1""")
    c.execute(f"""UPDATE ssap SET a3 = coalesce((SELECT x.a3 FROM ssap_a3 x WHERE x.uid = ssap.uid),
                                                '{UNINCORPORATED}')""")
    # QA in the build log: the communities the Records name where we found no municipality
    top = c.execute(f"""SELECT post_comm, count(*) FROM ssap WHERE a3 = '{UNINCORPORATED}' AND status = 'record'
                        GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 10""").fetchall()
    if top:
        print("  [boundaries] Unincorporated Records by their own community: "
              + ", ".join(f"{name} {n:,}" for name, n in top))


def create_layers(c, job, updated):
    """Tables a2_polygon and a3_polygon, one row per boundary per Package, in NENA fields + geoid."""
    src = job.country.lower()
    c.execute(f"""CREATE OR REPLACE TABLE a2_polygon AS
        SELECT d.domain AS discrpagid, '{updated}' AS dateupdate, NULL::VARCHAR AS effective,
               NULL::VARCHAR AS expire,
               build_nguid('A2', boundary_uid('{src}-a2', p.geoid), d.domain) AS nguid,
               '{job.country}' AS country, '{job.code}' AS a1, p.name AS a2,
               p.geoid AS source_code, p.geoid, p.geom
        FROM package_area p JOIN package_domain d USING (geoid)""")
    c.execute(f"""CREATE OR REPLACE TABLE a3_polygon AS
        WITH piece AS (
            SELECT p.geoid, p.name AS a2, m.geoid AS mgeoid, m.name AS a3, m.geom AS whole,
                   ST_CollectionExtract(ST_Intersection(m.geom, p.geom), 3) AS geom
            FROM municipality m JOIN package_area p ON m.incorporated AND ST_Intersects(m.geom, p.geom)),
        used AS (SELECT DISTINCT geoid, a3 FROM ssap WHERE a3 <> '{UNINCORPORATED}')
        SELECT d.domain AS discrpagid, '{updated}' AS dateupdate, NULL::VARCHAR AS effective,
               NULL::VARCHAR AS expire,
               build_nguid('A3', boundary_uid('{src}-a3', x.mgeoid), d.domain) AS nguid,
               '{job.country}' AS country, '{job.code}' AS a1, x.a2, x.a3,
               x.mgeoid AS source_code, x.geoid, x.geom
        FROM piece x JOIN package_domain d USING (geoid)
        WHERE NOT ST_IsEmpty(x.geom)
          AND (ST_Area(x.geom) >= {SLIVER_SHARE} * ST_Area(x.whole)
               OR EXISTS (SELECT 1 FROM used u WHERE u.geoid = x.geoid AND u.a3 = x.a3))""")


def install(c):
    with contextlib.suppress(duckdb.Error):
        c.remove_function("boundary_uid")
    c.create_function("boundary_uid", boundary_uid, ["VARCHAR", "VARCHAR"], "VARCHAR", side_effects=False)


def write_package(c, job, geoid, out):
    """Write the Package's boundary layers into its folder; returns the manifest's 'boundaries' entry."""
    for table in ("a2_polygon", "a3_polygon"):
        db.write_geoparquet(c, f"SELECT * EXCLUDE (geoid) FROM {table} WHERE geoid = '{geoid}'",
                            f"{out}/{table}.parquet", "source_code")
    k = registry.country(job)
    n_a3 = c.execute(f"SELECT count(*) FROM a3_polygon WHERE geoid = '{geoid}'").fetchall()[0][0]
    res = c.execute(f"""SELECT
            count(*) FILTER (a3 IS NOT NULL AND a3 <> '{UNINCORPORATED}'),
            count(*) FILTER (a3 = '{UNINCORPORATED}'),
            count(*) FILTER (a3 IS NULL),
            count(*) FILTER (status = 'record' AND post_comm IS NOT NULL AND a3 <> '{UNINCORPORATED}'),
            count(*) FILTER (status = 'record' AND post_comm IS NOT NULL AND upper(a3) = post_comm)
        FROM ssap WHERE geoid = '{geoid}'""").fetchall()[0]
    in_muni, unincorporated, no_a3, compared, agreed = (int(v) for v in res)
    a3 = {"addresses_in_municipality": in_muni, "addresses_unincorporated": unincorporated,
          "addresses_without_a3": no_a3,
          # QA: of the Records in a municipality that name their own community (VT's TOWNNAME), the share
          # whose community is the A3 the boundary gave them
          "record_community_agrees_with_a3": round(agreed / compared, 4) if compared else None}
    lic = {"source_key": k.boundary_key, "license_status": "open", "license": k.boundary_license,
           "license_url": k.boundary_license_url}
    return {"A2Polygon": {"agency": k.a2_source, **lic, "features": 1},
            "A3Polygon": {"agency": k.a3_source, **lic, "features": int(n_a3),
                          **a3}}


def summary(c):
    """Job-wide A3 counts for job.json."""
    res = c.execute(f"""SELECT count(*) FILTER (a3 IS NOT NULL AND a3 <> '{UNINCORPORATED}'),
                               count(*) FILTER (a3 = '{UNINCORPORATED}'), count(*) FILTER (a3 IS NULL),
                               (SELECT count(*) FROM a3_polygon)
                        FROM ssap""").fetchall()[0]
    return dict(zip(("addresses_in_municipality", "addresses_unincorporated", "addresses_without_a3",
                     "a3_polygons"), (int(v) for v in res)))
