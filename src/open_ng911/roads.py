"""
The RoadCenterline layer: government road geometry in every Package, with Overture GERS IDs attached.

    1. Read every `centerlines` Source in the job's registry (sources/centerlines.py): the Source agency's own
       segments, the Records of this layer (ADR 0001).
    2. Give each segment the Package its midpoint falls in, keeping a government segment
       only inside the Packages its Source covers.
    3. Packages left with no government segment fall back to Census TIGER ADDRFEAT, county by county.
    4. Crosswalk to Overture: each segment's GERS IDs are the Overture road segments that run along it
       (`crosswalk`). Only the IDs and overlap numbers are kept; Overture's geometry and names are ODbL and
       never go into a Package (AGENTS.md). Overture's counsel confirmed GERS IDs aren't derivative and may be
       attached to our own geometry.
    5. NENA fields (NENA-STA-006.3, lower-cased, registry words) with RCL NGUIDs built from the segment UID under
       the Package's domain, the same way as the address points (ADR 0002, 0003).

Package files, next to the address points:

    road_centerline.parquet       GeoParquet: NENA fields + uid, gers_id, road_source, source, source_license
    road_gers_crosswalk.parquet   every segment x GERS ID link: overlap_m, rcl_share, segment_share, is_primary

and a `road_centerline` section in manifest.json naming every road source with its license and date.
"""
import json
import math
import os

from . import db, nena, package

ROAD_MATCH_M = 20.0  # how far an Overture segment may sit from the government line and still run along it
MAX_ANGLE = 30.0     # degrees between the two shared stretches: more is a road crossing, not running along


def _sources_covering(jurisdiction):
    return {s.key: s for s in jurisdiction.sources_for("centerlines")}


def install(c):
    # halfway along a line; a multi-part line has no single "along", so a point on one of its parts
    c.execute("""CREATE OR REPLACE MACRO road_midpoint(g) AS CASE WHEN ST_GeometryType(g) = 'LINESTRING'
                 THEN ST_LineInterpolatePoint(g, 0.5) ELSE ST_PointOnSurface(g) END""")


def assign_packages(c, jurisdiction):
    """road_seg gains geoid; government segments outside their Source's coverage and anything outside every
    Package is dropped, and road_fallback lists the Packages no government segment reached."""
    c.execute("""CREATE OR REPLACE TABLE road_seg AS
        SELECT s.* EXCLUDE (geoid), p.geoid
        FROM road_seg s
        JOIN package_area p ON ST_Intersects(p.geom, road_midpoint(s.geom))
        QUALIFY row_number() OVER (PARTITION BY s.uid ORDER BY p.geoid) = 1""")
    covered = []
    for key, s in _sources_covering(jurisdiction).items():
        if s.covers != "*":
            covered.append(f"(source_key = '{key}' AND geoid IN ({', '.join(repr(g) for g in s.covers)}))")
        else:
            covered.append(f"source_key = '{key}'")
    keep = " OR ".join(covered) or "false"
    c.execute(f"DELETE FROM road_seg WHERE road_source = 'government' AND NOT ({keep})")
    c.execute("""CREATE OR REPLACE TABLE road_fallback AS
        SELECT geoid FROM package_area
        WHERE geoid NOT IN (SELECT geoid FROM road_seg WHERE road_source = 'government')""")


def utm_epsg(c):
    """A metric CRS for the job: the WGS84 UTM zone at the centre of its Packages."""
    lon, lat = c.execute("SELECT (min(ST_XMin(geom)) + max(ST_XMax(geom))) / 2, "
                         "(min(ST_YMin(geom)) + max(ST_YMax(geom))) / 2 FROM package_area").fetchall()[0]
    zone = min(60, math.floor((lon + 180) / 6) + 1)
    return f"EPSG:{32600 + zone if lat >= 0 else 32700 + zone}"


def crosswalk(c, max_m=ROAD_MATCH_M, left="road_seg", right="overture_segment", right_id="gers_id",
              out="road_gers"):
    """road_gers(uid, gers_id, overlap_m, rcl_share, segment_share, is_primary).

    The same test links any two line tables: `left` (uid, geom) to `right` (`right_id`, geom), into `out` with
    the right-hand ID column named `right_id` (upstream.py uses it for government roads against TIGER).

    An Overture segment runs along a government segment when, within max_m of each other, it covers at least
    half of the government segment or the government segment covers at least half of it (one line is often cut
    into several on the other side), and the two shared stretches point the same way (within MAX_ANGLE), which a
    road crossing or meeting it doesn't. The primary GERS ID is the one along the most of the segment."""
    install(c)
    epsg = utm_epsg(c)
    c.execute(f"""CREATE OR REPLACE TEMP TABLE _g AS
        SELECT uid, m, ST_Buffer(m, {max_m}) AS buf, ST_Length(m) AS len FROM (
            SELECT uid, ST_LineMerge(ST_Transform(geom, 'EPSG:4326', '{epsg}')) AS m FROM {left})""")
    c.execute(f"""CREATE OR REPLACE TEMP TABLE _o AS
        SELECT rid, m, ST_Buffer(m, {max_m}) AS buf, ST_Length(m) AS len FROM (
            SELECT {right_id} AS rid, ST_Transform(geom, 'EPSG:4326', '{epsg}') AS m FROM {right})""")
    c.execute(f"""CREATE OR REPLACE TABLE {out} AS
        WITH pairs AS (
            SELECT g.uid, o.rid, g.len AS glen, o.len AS olen,
                   ST_Intersection(g.m, o.buf) AS gp, ST_Intersection(o.m, g.buf) AS op,
                   ST_Distance(road_midpoint(g.m), o.m) AS mid_m
            FROM _g g JOIN _o o ON ST_Intersects(g.buf, o.m)),
        measured AS (
            SELECT *, ST_Length(gp) AS g_in, ST_Length(op) AS o_in,
                   -- the angle between the two shared stretches, end to end, folded to 0-90 degrees
                   abs(ST_Azimuth(ST_StartPoint(gp), ST_EndPoint(gp)) - ST_Azimuth(ST_StartPoint(op), ST_EndPoint(op))) % pi() AS d
            FROM pairs),
        links AS (
            SELECT * FROM measured
            WHERE glen > 0 AND olen > 0 AND greatest(g_in, o_in) >= least(5, 0.9 * glen)  -- not a junction crumb
              AND (g_in >= 0.5 * glen OR o_in >= 0.5 * olen)
              AND coalesce(degrees(least(d, pi() - d)) <= {MAX_ANGLE}, true))  -- no single stretch: can't tell
        SELECT uid, rid AS {right_id}, round(g_in, 1) AS overlap_m, round(least(g_in / glen, 1), 3) AS rcl_share,
               round(least(o_in / olen, 1), 3) AS segment_share,
               row_number() OVER (PARTITION BY uid ORDER BY g_in DESC, mid_m, rid) = 1 AS is_primary
        FROM links""")
    c.execute("DROP TABLE _g")
    c.execute("DROP TABLE _o")
    return c.execute(f"SELECT count(DISTINCT uid) FROM {out}").fetchall()[0][0]


def _parity(f, t):
    return (f"CASE WHEN coalesce({f}, {t}) IS NULL THEN 'Z' "
            f"WHEN coalesce({f}, {t}) % 2 = 1 AND coalesce({t}, {f}) % 2 = 1 THEN 'O' "
            f"WHEN coalesce({f}, {t}) % 2 = 0 AND coalesce({t}, {f}) % 2 = 0 THEN 'E' ELSE 'B' END")


def assemble_rcl(c, job, updated):
    c.execute(f"""CREATE OR REPLACE TABLE rcl AS
        WITH x AS (SELECT *, nena_type_word(ps.type) AS postyp FROM (SELECT *, parse_street(street) AS ps FROM road_seg)),
        y AS (SELECT *, nena_pretype_raw(ps.name, postyp) AS pre_raw FROM x)
        SELECT y.uid, g.gers_id, g.rcl_share AS gers_rcl_share, y.road_source, y.source_key AS source, y.source_id,
               m.license_status AS source_license,
               d.domain AS discrpagid,
               '{updated}' AS dateupdate,
               build_nguid('RCL', y.uid, d.domain) AS rcl_nguid,
               y.from_l AS fromaddr_l, y.to_l AS toaddr_l, y.from_r AS fromaddr_r, y.to_r AS toaddr_r,
               {_parity('y.from_l', 'y.to_l')} AS parity_l,
               {_parity('y.from_r', 'y.to_r')} AS parity_r,
               nena_dir_word(y.ps.predir) AS st_predir,
               nena_pretype_word(y.pre_raw) AS st_pretyp,
               nena_st_name(y.ps.name, y.pre_raw) AS st_name,
               y.postyp AS st_postyp,
               nena_dir_word(y.ps.posdir) AS st_posdir,
               -- ESN and MSAG community come only from the 911 authority (AGENTS.md): never filled in here
               '{job.country}' AS country_l, '{job.country}' AS country_r,
               '{job.code}' AS a1_l, '{job.code}' AS a1_r,
               p.name AS a2_l, p.name AS a2_r,
               NULL::VARCHAR AS a3_l, NULL::VARCHAR AS a3_r,  -- from the boundary adapters, not built yet
               y.zip_l AS postcode_l, y.zip_r AS postcode_r,
               y.road_class AS roadclass, y.oneway, y.speed_mph AS speedlimit,
               y.geoid, y.geom
        FROM y
        JOIN package_domain d USING (geoid) JOIN package_area p USING (geoid)
        LEFT JOIN road_source_meta m USING (source_key)
        LEFT JOIN (SELECT * FROM road_gers WHERE is_primary) g USING (uid)""")


def build(c, job, jurisdiction, work_dir, loaders, updated):
    """road_seg, road_gers and rcl on the connection. loaders: gov_roads, tiger_roads, overture_segment."""
    from .sources import centerlines
    install(c)
    centerlines.create_tables(c)
    loaders["gov_roads"](c, job, jurisdiction, work_dir)
    assign_packages(c, jurisdiction)
    loaders["tiger_roads"](c, job, jurisdiction, work_dir)
    assign_packages(c, jurisdiction)
    # a TIGER edge can fall in a county that has government roads (ADDRFEAT lists boundary edges in both)
    c.execute("DELETE FROM road_seg WHERE road_source = 'tiger' AND geoid NOT IN (SELECT geoid FROM road_fallback)")
    loaders["overture_segment"](c, job, jurisdiction, work_dir)
    linked = crosswalk(c)
    assemble_rcl(c, job, updated)
    by = dict(c.execute("SELECT road_source, count(*) FROM rcl GROUP BY 1 ORDER BY 1").fetchall())
    print(f"[{job.id}] road centerlines by source: {by}; {linked:,} with a GERS ID")


def gate(c):
    return db.gate(c, "rcl", nena.RCL_REQUIRED, "rcl_nguid", "rcl ", nguid_label="")


def write(c, job, root, release):
    """road_centerline.parquet and road_gers_crosswalk.parquet in every Package, and the manifest's road section.
    Returns the road section of each Package's manifest, by Package key."""
    fill_sql = ", ".join(f"count({f}) AS {f}" for f in nena.RCL_FIELDS)
    meta = db.rows(c, "SELECT * FROM road_source_meta ORDER BY source_key")
    out = {}
    for geoid, in c.execute("SELECT geoid FROM package_area ORDER BY 1").fetchall():
        d = os.path.join(root, geoid)
        os.makedirs(d, exist_ok=True)
        c.execute(f"COPY (SELECT * EXCLUDE (geoid) FROM rcl WHERE geoid = '{geoid}' ORDER BY uid) TO "
                  f"'{os.path.join(d, 'road_centerline.parquet')}' (FORMAT parquet, COMPRESSION zstd)")
        c.execute(f"""COPY (SELECT g.uid, r.rcl_nguid, g.gers_id, g.overlap_m, g.rcl_share, g.segment_share,
                                   g.is_primary, '{release}' AS overture_release
                            FROM road_gers g JOIN rcl r USING (uid) WHERE r.geoid = '{geoid}'
                            ORDER BY g.uid, g.is_primary DESC, g.gers_id)
                      TO '{os.path.join(d, 'road_gers_crosswalk.parquet')}' (FORMAT parquet)""")
        stats = db.rows(c, f"SELECT count(*) AS rows, count(gers_id) AS with_gers_id, {fill_sql} FROM rcl "
                         f"WHERE geoid = '{geoid}'")[0]
        rows, with_gers = int(stats.pop("rows")), int(stats.pop("with_gers_id"))
        per_source = dict(c.execute(f"SELECT source, count(*) FROM rcl WHERE geoid = '{geoid}' GROUP BY 1").fetchall())
        section = {
            "rows": rows, "with_gers_id": with_gers,
            "gers_coverage": round(with_gers / rows, 4) if rows else None,
            "road_source": "government" if any(m["road_source"] == "government" and m["source_key"] in per_source
                                               for m in meta) else ("tiger" if rows else None),
            "field_fill": {k: round(int(v) / rows, 4) if rows else None for k, v in stats.items()},
            # every source of this Package's roads, with its license and its date (when the publisher last
            # edited it, or the TIGER vintage) and when we read it
            "sources": [{**m, "segments": per_source[m["source_key"]]} for m in meta if m["source_key"] in per_source],
            "gers_ids": {"overture_release": release, "theme": "transportation/segment",
                         "note": "GERS IDs only; no Overture geometry or names (ODbL) are in this Package"},
        }
        mpath = os.path.join(d, "manifest.json")
        manifest = {}
        if os.path.exists(mpath):
            with open(mpath) as f:
                manifest = json.load(f)
        nena_section = manifest.setdefault("nena", {})
        layers = nena_section.setdefault("layers", [])
        if "RoadCenterline" not in layers:
            layers.append("RoadCenterline")
        nena_section["rcl_mandatory_fields"] = list(nena.RCL_REQUIRED)
        manifest["road_centerline"] = section
        with open(mpath, "w") as f:
            json.dump(manifest, f, indent=2)
        out[package.package_key(job, geoid)] = section
    return out


def package_summary(section):
    """The road numbers job.json shows for one Package."""
    return {"road_segments": section["rows"], "road_source": section["road_source"],
            "road_gers_coverage": section["gers_coverage"]}
