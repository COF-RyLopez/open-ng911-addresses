"""
The upstream counts (docs/standards/upstream-path.md): where a Package's government roads and the layers above
them disagree, so the case for authoritative local data in Overture and in the national layers builds up job by
job.

Two comparisons, both counts and lengths only:

    overture   every RoadCenterline segment against the Overture segment it links to (its primary GERS ID): does
               the street name agree, and the road class? Overture's names and classes are ODbL: they're compared
               in memory and never written.
    national   the Source agency's own roads against the national road layer for the same Package (US: TIGER
               ADDRFEAT; Canada: not measured until the National Road Network loader exists), with the same
               geometric test as the GERS crosswalk: segments in the agency's network the national layer lacks,
               and national segments the agency's network doesn't have.

Each Package's manifest gets an `upstream` section; job.json gets the totals. Whether any of it could go upstream
is a separate question: only a source whose licence is open (`upstream_eligible`), and only a person proposes it
(ADR 0004).
"""
from . import db, roads

# NENA RoadClass and Overture segment class, each into the same coarse group; a value in neither isn't compared
NENA_GROUP = {"Primary": "highway", "Secondary": "arterial", "Local": "local", "Service Drive": "local",
              "Alley": "local", "Private": "local", "Parking Lot": "local", "Ramp": "ramp",
              "Vehicular Trail": "trail", "Walkway/Pedestrian Trail": "trail", "Stairway": "trail",
              "Bike Path or Trail": "trail", "Bridle Path": "trail"}
OVERTURE_GROUP = {"motorway": "highway", "trunk": "highway", "primary": "arterial", "secondary": "arterial",
                  "tertiary": "local", "residential": "local", "living_street": "local", "unclassified": "local",
                  "service": "local", "track": "trail", "path": "trail", "footway": "trail", "pedestrian": "trail",
                  "steps": "trail", "cycleway": "trail", "bridleway": "trail"}


def _keys(c, table, col, out):
    c.execute(f"""CREATE OR REPLACE TEMP TABLE {out} AS
        WITH p AS (SELECT uid, parse_street({col}) AS ps FROM {table}),
             q AS (SELECT uid, ps, nena_type_word(ps.type) AS postyp FROM p),
             r AS (SELECT *, nena_pretype_raw(ps.name, postyp) AS pre_raw FROM q)
        SELECT uid, CASE WHEN nena_st_name(ps.name, pre_raw) IS NOT NULL THEN street_key(concat_ws(' ',
                   nena_dir_word(ps.predir), nena_pretype_word(pre_raw), nena_st_name(ps.name, pre_raw), postyp,
                   nena_dir_word(ps.posdir))) END AS k
        FROM r""")


def compare_overture(c):
    """upstream_overture(uid, geoid, name_check, class_check), one row per RoadCenterline segment."""
    c.execute("""CREATE OR REPLACE TEMP TABLE _l AS
        SELECT r.uid, r.geoid, r.gers_id, s.street, r.roadclass, o.name AS o_name, o.class AS o_class,
               o.subclass AS o_sub
        FROM rcl r JOIN road_seg s USING (uid) LEFT JOIN overture_segment o ON o.gers_id = r.gers_id""")
    c.execute("CREATE OR REPLACE TEMP TABLE _ln AS SELECT uid, o_name FROM _l")
    _keys(c, "_l", "street", "_k")
    _keys(c, "_ln", "o_name", "_ok")
    c.execute(f"""CREATE OR REPLACE TABLE upstream_overture AS
        WITH keyed AS (
            SELECT l.*, k.k, ok.k AS ok, {db.case('l.roadclass', NENA_GROUP)} AS g,
                   CASE WHEN l.o_sub = 'link' THEN 'ramp' ELSE {db.case('l.o_class', OVERTURE_GROUP)} END AS og
            FROM _l l JOIN _k k USING (uid) JOIN _ok ok USING (uid))
        SELECT uid, geoid,
               CASE WHEN gers_id IS NULL THEN 'no_link'
                    WHEN k IS NULL THEN 'government_unnamed' WHEN ok IS NULL THEN 'overture_unnamed'
                    WHEN k = ok THEN 'agrees' ELSE 'differs' END AS name_check,
               CASE WHEN gers_id IS NULL OR og IS NULL OR g IS NULL THEN NULL
                    WHEN g = og THEN 'agrees' ELSE 'differs' END AS class_check
        FROM keyed""")
    for t in ("_l", "_ln", "_k", "_ok"):
        c.execute(f"DROP TABLE {t}")


def compare_national(c):
    """upstream_national(side, uid, geoid, km, linked): each government segment (side 'government') and each
    national segment in a Package with government roads (side 'national'), and whether the other layer has it."""
    c.execute("""CREATE OR REPLACE TABLE _gov AS SELECT uid, geom, geoid FROM road_seg WHERE road_source = 'government'""")
    c.execute("""CREATE OR REPLACE TABLE _nat AS
        SELECT n.uid AS nat_uid, n.geom, p.geoid FROM national_seg n
        JOIN package_area p ON ST_Intersects(p.geom, road_midpoint(n.geom))
        WHERE p.geoid IN (SELECT geoid FROM _gov)
        QUALIFY row_number() OVER (PARTITION BY n.uid ORDER BY p.geoid) = 1""")
    roads.crosswalk(c, left="_gov", right="_nat", right_id="nat_uid", out="_gov_nat")
    epsg = roads.utm_epsg(c)
    km = f"ST_Length(ST_Transform(geom, 'EPSG:4326', '{epsg}')) / 1000"
    c.execute(f"""CREATE OR REPLACE TABLE upstream_national AS
        SELECT 'government' AS side, uid, geoid, {km} AS km, uid IN (SELECT uid FROM _gov_nat) AS linked FROM _gov
        UNION ALL
        SELECT 'national', nat_uid, geoid, {km}, nat_uid IN (SELECT nat_uid FROM _gov_nat) FROM _nat""")
    for t in ("_gov", "_nat", "_gov_nat"):
        c.execute(f"DROP TABLE {t}")


def build(c, job, jurisdiction, work_dir, loaders):
    """The comparison tables; returns the national layer's name and date (None when there's no national layer)."""
    compare_overture(c)
    national = loaders["national_roads"](c, job, jurisdiction, work_dir)
    if national:
        compare_national(c)
    return national


def package_section(c, jurisdiction, geoid, national, release):
    """The `upstream` section of one Package's manifest."""
    licences = {s.key: s.license_status for s in jurisdiction.sources_for("centerlines")}
    keys = [k for k, in c.execute(f"SELECT DISTINCT source_key FROM road_seg WHERE road_source = 'government' "
                                  f"AND geoid = '{geoid}'").fetchall()]
    eligible = bool(keys) and all(licences.get(k) == "open" for k in keys)
    o = db.one(c, f"""SELECT count(*) AS segments,
            count(*) FILTER (name_check = 'no_link') AS not_in_overture,
            count(*) FILTER (name_check = 'agrees') AS name_agrees,
            count(*) FILTER (name_check = 'differs') AS name_differs,
            count(*) FILTER (name_check = 'overture_unnamed') AS overture_unnamed,
            count(*) FILTER (name_check = 'government_unnamed') AS source_unnamed,
            count(*) FILTER (class_check = 'agrees') AS class_agrees,
            count(*) FILTER (class_check = 'differs') AS class_differs
        FROM upstream_overture WHERE geoid = '{geoid}'""")
    section = {"overture": {"release": release, **{k: int(v) for k, v in o.items()}}}
    has_gov = c.execute(f"SELECT count(*) FROM road_seg WHERE road_source = 'government' AND geoid = '{geoid}'"
                        ).fetchall()[0][0]
    if not has_gov:
        section["national"] = {"measured": False, "why": "no government roads in this Package"}
    elif not national:
        section["national"] = {"measured": False, "why": "no national road layer loader for this country yet"}
    else:
        n = db.one(c, f"""SELECT
                count(*) FILTER (side = 'government') AS government_segments,
                count(*) FILTER (side = 'government' AND NOT linked) AS not_in_national,
                round(coalesce(sum(km) FILTER (side = 'government' AND NOT linked), 0), 2) AS not_in_national_km,
                count(*) FILTER (side = 'national') AS national_segments,
                count(*) FILTER (side = 'national' AND NOT linked) AS national_not_in_government,
                round(coalesce(sum(km) FILTER (side = 'national' AND NOT linked), 0), 2) AS national_not_in_government_km
            FROM upstream_national WHERE geoid = '{geoid}'""")
        section["national"] = {"measured": True, **national,
                               **{k: (float(v) if k.endswith("_km") else int(v)) for k, v in n.items()}}
    section["upstream_eligible"] = eligible
    section["note"] = ("Counts only. Overture names and classes (ODbL) are compared in memory and not written. "
                       "Only an open-licensed source can go upstream, and a person proposes it (ADR 0004).")
    return section


def job_totals(sections):
    """The job.json rollup: sums of every count across Packages."""
    tot = {"overture": {}, "national": {}}
    for s in sections:
        for k, v in s["overture"].items():
            if k != "release":
                tot["overture"][k] = tot["overture"].get(k, 0) + v
        if s["national"].get("measured"):
            for k, v in s["national"].items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    tot["national"][k] = round(tot["national"].get(k, 0) + v, 2)
    return tot
