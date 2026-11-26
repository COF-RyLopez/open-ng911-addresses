"""
Address ranges against address points: the NENA / NSGIC check that every addressed site sits on the right side of
the right road, inside that side's range, and ranges derived from the points where a road side has none.

    1. Each Record (an agency address point, ADR 0001) is paired with the nearest road segment on the same street
       (street.py's key on both sides) within MAX_M, and given the side of the road it sits on.
    2. Each pair is checked against that side's range: `in_range`, `wrong_side` (outside its side's range but
       inside the other side's), `outside_range`, `wrong_parity` (inside the range, on the other parity), or `no_range` (the side has none: NENA's 0, roads.without_range). A Record
       with no same-street segment within MAX_M is `no_matching_road`.
    3. A road side with no range and at least one Record gets a range derived from them: the numbers at the
       segment's start and end (by where each point falls along it) and their parity. These go in their own
       columns (derived_fromaddr_l ...), never into FromAddr/ToAddr: the NENA fields stay the agency's (ADR 0004),
       and an opted-in agency can take the derived ones.

Package files: address_range_check.parquet (one row per Record: segment, side, result, distance) and the RCL's
derived_* and range_points_* columns; an `address_ranges` manifest section with the counts. The check is a finding
for the agency report, never a reason to drop or change anything.
"""
from . import db, roads

MAX_M = 150.0  # how far from its street a point may sit and still be checked against it
SIDES = ("l", "r")
RESULTS = ("in_range", "wrong_side", "outside_range", "wrong_parity", "no_range", "no_matching_road")
RCL_COLUMNS = ", ".join(f"derived_fromaddr_{s} INTEGER, derived_toaddr_{s} INTEGER, derived_parity_{s} VARCHAR, "
                        f"range_points_{s} INTEGER" for s in SIDES)


def check(c):
    """address_range_check(uid, rcl_uid, side, add_number, result, distance_m, geoid) and the RCL's derived
    ranges; returns {result: n}."""
    epsg = roads.utm_epsg(c)
    # one row per part of each segment's (merged) line: a point is sided against the nearest part, and only a
    # one-part line has a single "along" to derive a range by
    c.execute(f"""CREATE OR REPLACE TEMP TABLE _seg AS
        WITH merged AS (
            SELECT r.uid, r.geoid, parsed_street_key(parse_street(s.street)) AS skey,
                   r.fromaddr_l, r.toaddr_l, r.parity_l, r.fromaddr_r, r.toaddr_r, r.parity_r,
                   ST_Dump(ST_LineMerge(ST_Transform(r.geom, 'EPSG:4326', '{epsg}'))) AS parts
            FROM rcl r JOIN road_seg s USING (uid))
        SELECT * EXCLUDE (parts, part), part.geom AS m, len(parts) AS n_parts
        FROM (SELECT *, unnest(parts) AS part FROM merged)
        WHERE ST_GeometryType(part.geom) = 'LINESTRING' AND NOT ST_IsEmpty(part.geom)""")
    c.execute(f"""CREATE OR REPLACE TEMP TABLE _pt AS
        SELECT s.uid, s.add_number, s.geoid, a.skey, ST_Transform(s.geom, 'EPSG:4326', '{epsg}') AS m
        FROM ssap s JOIN agency_addr a ON a.address_uid = s.uid
        WHERE s.status = 'record' AND s.add_number IS NOT NULL""")
    c.execute(f"""CREATE OR REPLACE TABLE address_range_check AS
        WITH pairs AS (
            SELECT p.uid, p.add_number, p.geoid, g.uid AS rcl_uid, ST_Distance(p.m, g.m) AS d, p.m AS pm, g.m AS gm, g.*
                   EXCLUDE (uid, geoid, skey, m)
            FROM _pt p JOIN _seg g ON p.skey = g.skey AND ST_DWithin(p.m, g.m, {MAX_M})
            QUALIFY row_number() OVER (PARTITION BY p.uid ORDER BY ST_Distance(p.m, g.m), g.uid) = 1),
        placed AS (
            SELECT *, ST_LineLocatePoint(gm, pm) AS t FROM pairs),
        sided AS (
            -- left or right of the segment's direction at the point: the sign of the cross product
            SELECT *, CASE WHEN (ST_X(b) - ST_X(a)) * (ST_Y(pm) - ST_Y(a)) - (ST_Y(b) - ST_Y(a)) * (ST_X(pm) - ST_X(a)) >= 0
                      THEN 'l' ELSE 'r' END AS side
            FROM (SELECT *, ST_LineInterpolatePoint(gm, greatest(t - 0.001, 0)) AS a,
                            ST_LineInterpolatePoint(gm, least(t + 0.001, 1)) AS b FROM placed)),
        ranged AS (
            SELECT *, CASE side WHEN 'l' THEN fromaddr_l WHEN 'r' THEN fromaddr_r END AS f,
                      CASE side WHEN 'l' THEN toaddr_l WHEN 'r' THEN toaddr_r END AS e,
                      CASE side WHEN 'l' THEN parity_l WHEN 'r' THEN parity_r END AS par,
                      -- the other side's range, for a point that belongs across the road
                      CASE side WHEN 'l' THEN fromaddr_r WHEN 'r' THEN fromaddr_l END AS of,
                      CASE side WHEN 'l' THEN toaddr_r WHEN 'r' THEN toaddr_l END AS oe,
                      CASE side WHEN 'l' THEN parity_r WHEN 'r' THEN parity_l END AS opar
            FROM sided)
        SELECT uid, rcl_uid, side, add_number, CASE WHEN n_parts = 1 THEN t END AS position,
               CASE WHEN side IS NULL OR par IS NULL OR par = 'Z' THEN 'no_range'
                    WHEN add_number NOT BETWEEN least(f, e) AND greatest(f, e) AND opar IS NOT NULL AND opar <> 'Z'
                         AND add_number BETWEEN least(of, oe) AND greatest(of, oe)
                         AND NOT ((opar = 'O' AND add_number % 2 = 0) OR (opar = 'E' AND add_number % 2 = 1))
                         THEN 'wrong_side'
                    WHEN add_number NOT BETWEEN least(f, e) AND greatest(f, e) THEN 'outside_range'
                    WHEN (par = 'O' AND add_number % 2 = 0) OR (par = 'E' AND add_number % 2 = 1) THEN 'wrong_parity'
                    ELSE 'in_range' END AS result,
               round(d, 1) AS distance_m, geoid
        FROM ranged
        UNION ALL
        SELECT p.uid, NULL, NULL, p.add_number, NULL, 'no_matching_road', NULL, p.geoid
        FROM _pt p WHERE NOT EXISTS (
            SELECT 1 FROM _seg g WHERE p.skey = g.skey AND ST_DWithin(p.m, g.m, {MAX_M}))""")
    derive(c)
    c.execute("DROP TABLE _seg")
    c.execute("DROP TABLE _pt")
    return dict(c.execute("SELECT result, count(*) FROM address_range_check GROUP BY 1 ORDER BY 1").fetchall())


def derive(c):
    """The RCL's derived_* columns: on a side with no range (parity 'Z') and at least one Record on it, the numbers
    nearest the segment's start and end, and their parity (none on a line in separate pieces, which has no single
    start and end); range_points_*: the Records checked on each side."""
    for col in RCL_COLUMNS.split(", "):
        c.execute(f"ALTER TABLE rcl ADD COLUMN IF NOT EXISTS {col}")
    for s in SIDES:
        c.execute(f"""UPDATE rcl r SET range_points_{s} = k.n,
                derived_fromaddr_{s} = CASE WHEN r.parity_{s} = 'Z' THEN k.first END,
                derived_toaddr_{s} = CASE WHEN r.parity_{s} = 'Z' THEN k.last END,
                derived_parity_{s} = CASE WHEN r.parity_{s} <> 'Z' OR k.first IS NULL THEN NULL
                    WHEN k.odd = k.n THEN 'O' WHEN k.odd = 0 THEN 'E' ELSE 'B' END
            FROM (SELECT rcl_uid, count(*)::INTEGER AS n, count(*) FILTER (add_number % 2 = 1) AS odd,
                         arg_min(add_number, position) AS first, arg_max(add_number, position) AS last
                  FROM address_range_check WHERE side = '{s}' GROUP BY 1) k
            WHERE r.uid = k.rcl_uid""")


def package_section(c, geoid):
    """The manifest's `address_ranges` section."""
    by = dict(c.execute(f"SELECT result, count(*) FROM address_range_check WHERE geoid = '{geoid}' "
                        "GROUP BY 1").fetchall())
    derived = db.one(c, f"""SELECT count(*) FILTER (derived_fromaddr_l IS NOT NULL) AS l,
                                   count(*) FILTER (derived_fromaddr_r IS NOT NULL) AS r
                            FROM rcl WHERE geoid = '{geoid}'""")
    return {"max_distance_m": MAX_M, "records_checked": sum(by.values()),
            **{r: int(by.get(r, 0)) for r in RESULTS},
            "segment_sides_with_derived_range": {"left": int(derived["l"]), "right": int(derived["r"])},
            "note": "Records against the road ranges on their side of the same street; derived ranges are in the "
                    "derived_* columns, never in the agency's FromAddr/ToAddr"}


def write_package(c, geoid, d):
    c.execute(f"COPY (SELECT * EXCLUDE (geoid) FROM address_range_check WHERE geoid = '{geoid}' ORDER BY uid) "
              f"TO '{d}/address_range_check.parquet' (FORMAT parquet, COMPRESSION zstd)")
