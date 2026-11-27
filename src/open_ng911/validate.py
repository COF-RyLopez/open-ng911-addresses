"""
The validation score: NSGIC's NG9-1-1 GIS data checks that need no agency data, run on every built layer and
scored per Package as passed / applicable checks.

    gate        <layer>.required_fields, <layer>.nguid_unique: what build.gate fails a job on, per Package
    geometry    <layer>.valid_geometry, single_part (SSAP, RCL), RoadCenterLine.self_intersection, short_segment
    domains     <layer>.domains: every value of a coded field inside NENA's domain (CLDXF-CA's street types in Canada)
    A-levels    SiteStructureAddressPoint.inside_package (its A2Polygon), a3_matches_polygon (the A3Polygon it is in;
                'Unincorporated' in none)
    duplicates  SiteStructureAddressPoint.duplicate_address: one full address on two points of a Package
    SSAP-RCL    SiteStructureAddressPoint.rcl_agreement (in its side's range, ranges.py), on_named_road (a segment of
                its street within ranges.MAX_M)
    ranges      RoadCenterLine.range_parity (Parity agrees with the numbers), range_direction (both sides run the same
                way), range_overlap (two segments of one street and community claim the same number)
    network     RoadCenterLine.connectivity: segment ends within SNAP_M of another end but not on it
    polygons    <polygon layer>.overlaps: two polygons of one layer sharing more than OVERLAP_M2 in a Package

A check passes for a Package when no feature of the Package fails it, and applies only where the Package has
features to check (a Package with no range has no range checks). Each check also reports its features checked and
failed, so a fix shows up before a check turns green. The checks are findings: they never drop or change a feature,
and only the `gate` group fails a job (build.gate). The score is what Self-Improvement Memory attempts record
(sim/problems/ng911-thin-validation-gate): `before` is the gate group alone, `after` every check.
"""
from . import boundaries, nena, ranges, roads

SNAP_M = 1.0  # segment ends closer than this but not on each other are an unsnapped node
SHORT_M = 1.0  # a segment shorter than this is a sliver
OVERLAP_M2 = 10.0  # shared area that counts as two polygons overlapping
GATE = ("required_fields", "nguid_unique")


def _flag(table, bad, join=""):
    """(geoid, checked, failed) for every feature of a table."""
    return f"SELECT t.geoid, count(*), count(*) FILTER (WHERE {bad}) FROM {table} t {join} GROUP BY 1"


def _in(table, uid, failing):
    """(geoid, checked, failed) where `failing` is a query of the failing features' `uid`s."""
    return _flag(table, f"t.{uid} IN (SELECT uid FROM ({failing}))")


def _domain_values(f, country):
    """The values a coded text field may hold: NENA's list, with CLDXF-CA's words added in Canada."""
    name = f.get("domain") or ""
    d = nena.domains().get(name)
    if not isinstance(d, list) or not d or f["type"] in ("INTEGER", "REAL", "DATETIME"):
        return None
    if name == "StreetNameType":
        d = nena.street_types(country)
    if country == "CA":
        ca = nena.cldxf_ca()["domains"]
        extra = ca.get(name, []) + (ca["StreetNamePreTypeFrench"] if f["name"] == "st_pretyp" else [])
        d = d + [w for w in extra if w not in d]
    return d


def _domains(layer, country):
    bad = []
    for f in nena.layer_fields(layer, country):
        values = _domain_values(f, country)
        if values:
            listed = ", ".join("'" + str(v).replace("'", "''") + "'" for v in values)
            bad.append(f"(t.{f['name']} IS NOT NULL AND t.{f['name']}::VARCHAR NOT IN ({listed}))")
    return " OR ".join(bad) or "false"


# A full address, for duplicates: the number, the street and the unit (CLDXF-US UnitPreTyp + UnitValue, CLDXF-CA Unit)
ADDRESS = ("addnum_pre", "add_number", "addnum_suf", "st_premod", "st_predir", "st_pretyp", "st_presep", "st_name",
           "st_postyp", "st_posdir", "st_posmod", "unit", "unitpretyp", "unitvalue", "building", "floor", "room", "seat")


def _ssap_checks(country):
    t = "ssap"
    have = {f["name"] for f in nena.layer_fields("SiteStructureAddressPoint", country)}
    street = ", ".join(n for n in ADDRESS if n in have)
    return {
        "single_part": _flag(t, "ST_GeometryType(t.geom) <> 'POINT'"),
        "inside_package": _flag(t, "p.geoid IS NULL", f"""LEFT JOIN (
            SELECT s.uid, p.geoid FROM {t} s JOIN package_area p ON ST_Intersects(p.geom, s.geom)
            WHERE p.geoid = s.geoid) p ON p.uid = t.uid"""),
        "a3_matches_polygon": _flag(t, f"""CASE WHEN h.uid IS NULL THEN t.a3 IS DISTINCT FROM '{boundaries.UNINCORPORATED}'
                                           ELSE NOT list_contains(h.a3s, t.a3) END""", f"""LEFT JOIN (
            SELECT s.uid, list(q.a3) AS a3s FROM {t} s JOIN a3_polygon q ON ST_Intersects(q.geom, s.geom)
            WHERE q.geoid = s.geoid GROUP BY 1) h ON h.uid = t.uid"""),
        "duplicate_address": _in(t, "uid", f"""SELECT uid FROM {t} WHERE add_number IS NOT NULL
            QUALIFY count(*) OVER (PARTITION BY geoid, a3, {street}) > 1"""),
        "rcl_agreement": "SELECT geoid, count(*), count(*) FILTER (WHERE result <> 'in_range') FROM address_range_check "
                         "WHERE result IN ('in_range', 'wrong_side', 'outside_range', 'wrong_parity') GROUP BY 1",
        "on_named_road": "SELECT geoid, count(*), count(*) FILTER (WHERE result = 'no_matching_road') "
                         "FROM address_range_check GROUP BY 1",
    }


def _side_ok(s):
    """A side's Parity agrees with its numbers (0-0 is no range, NENA's Z)."""
    f, e, p = f"t.fromaddr_{s}", f"t.toaddr_{s}", f"t.parity_{s}"
    return f"""CASE {p} WHEN 'Z' THEN {f} = 0 AND {e} = 0
                        WHEN 'O' THEN {f} % 2 = 1 AND {e} % 2 = 1
                        WHEN 'E' THEN {f} % 2 = 0 AND {e} % 2 = 0 AND {f} > 0 AND {e} > 0
                        WHEN 'B' THEN {f} > 0 AND {e} > 0
                        ELSE {p} IS NULL END"""


def _rcl_checks(epsg):
    t = "rcl"
    sides = " UNION ALL ".join(
        f"""SELECT uid, geoid, {ranges._key('r')} AS skey, a3_{s} AS a3, least(fromaddr_{s}, toaddr_{s}) AS lo,
                   greatest(fromaddr_{s}, toaddr_{s}) AS hi, parity_{s} AS par
            FROM {t} r WHERE parity_{s} IN ('O', 'E', 'B') AND fromaddr_{s} > 0 AND toaddr_{s} > 0"""
        for s in ranges.SIDES)
    ends = " UNION ALL ".join(
        f"SELECT uid, ST_Transform(ST_{p}Point(g), 'EPSG:4326', '{epsg}') AS p FROM _rcl_lines" for p in ("Start", "End"))
    return {
        "single_part": _flag(t, "ST_NumGeometries(ST_LineMerge(t.geom)) > 1"),
        "self_intersection": _flag(t, "NOT ST_IsSimple(t.geom)"),
        "short_segment": _flag(t, f"ST_Length(ST_Transform(t.geom, 'EPSG:4326', '{epsg}')) < {SHORT_M}"),
        "range_parity": _flag(t, f"NOT ({_side_ok('l')}) OR NOT ({_side_ok('r')})"),
        "range_direction": _flag(t, """t.parity_l <> 'Z' AND t.parity_r <> 'Z' AND t.fromaddr_l <> t.toaddr_l
            AND t.fromaddr_r <> t.toaddr_r AND sign(t.toaddr_l - t.fromaddr_l) <> sign(t.toaddr_r - t.fromaddr_r)"""),
        "range_overlap": _in(t, "uid", f"""WITH s AS ({sides})
            SELECT DISTINCT a.uid FROM s a JOIN s b
              ON a.geoid = b.geoid AND a.skey = b.skey AND a.a3 IS NOT DISTINCT FROM b.a3 AND a.uid <> b.uid
            WHERE a.lo <= b.hi AND b.lo <= a.hi AND (a.par = 'B' OR b.par = 'B' OR a.par = b.par)"""),
        # ends hashed into SNAP_M cells and compared with the 3 x 3 cells around them, so no spatial join is needed
        "connectivity": _in(t, "uid", f"""WITH e AS (SELECT uid, p, floor(ST_X(p) / {SNAP_M})::BIGINT AS cx,
                                                            floor(ST_Y(p) / {SNAP_M})::BIGINT AS cy FROM ({ends})),
            n AS (SELECT e.*, e.cx + dx AS nx, e.cy + dy AS ny
                  FROM e, (VALUES (-1), (0), (1)) x(dx), (VALUES (-1), (0), (1)) y(dy))
            SELECT DISTINCT n.uid FROM n JOIN e ON e.cx = n.nx AND e.cy = n.ny AND e.uid <> n.uid
            WHERE ST_Distance(n.p, e.p) > 0 AND ST_Distance(n.p, e.p) < {SNAP_M}"""),
    }


def _overlaps(table, epsg):
    return _in(table, "nguid", f"""SELECT DISTINCT a.nguid AS uid FROM {table} a JOIN {table} b
        ON a.geoid = b.geoid AND a.nguid <> b.nguid AND ST_Intersects(a.geom, b.geom)
        WHERE ST_Area(ST_Transform(ST_Intersection(ST_MakeValid(a.geom), ST_MakeValid(b.geom)), 'EPSG:4326', '{epsg}'))
              > {OVERLAP_M2}""")


def checks(c, job, spec):
    """{check name: SQL of (geoid, checked, failed)} for every built layer. spec: build.coverage_spec."""
    epsg = roads.utm_epsg(c)
    c.execute("""CREATE OR REPLACE TEMP TABLE _rcl_lines AS
                 SELECT uid, ST_LineMerge(geom) AS g FROM rcl WHERE ST_GeometryType(ST_LineMerge(geom)) = 'LINESTRING'""")
    out = {}
    for layer, kw in spec.items():
        t = kw["table"]
        if not t:
            continue
        nguid = "rcl_nguid" if layer == roads.RCL else "nguid"
        bad = " OR ".join(f"t.{f} IS NULL" for f in nena.gated(layer, job.country)) or "false"
        out[f"{layer}.required_fields"] = _flag(t, bad)
        out[f"{layer}.nguid_unique"] = _flag(t, f"t.{nguid} IN (SELECT {nguid} FROM {t} GROUP BY 1 HAVING count(*) > 1)")
        out[f"{layer}.valid_geometry"] = _flag(t, "t.geom IS NULL OR NOT ST_IsValid(t.geom)")
        out[f"{layer}.domains"] = _flag(t, _domains(layer, job.country))
        if t == "ssap":
            out.update({f"{layer}.{k}": v for k, v in _ssap_checks(job.country).items()})
        elif t == "rcl":
            out.update({f"{layer}.{k}": v for k, v in _rcl_checks(epsg).items()})
        elif nena.layer(layer)["geometry"] == "polygon" and layer != "A2Polygon":
            out[f"{layer}.overlaps"] = _overlaps(t, epsg)
    return out


def run(c, job, spec):
    """{geoid: {score, passed, applicable, before, checks: {name: {checked, failed, pass}}}} for every Package."""
    results = {}
    for name, sql in checks(c, job, spec).items():
        for geoid, checked, failed in c.execute(sql).fetchall():
            if checked:
                results.setdefault(geoid, {})[name] = {"checked": int(checked), "failed": int(failed),
                                                       "pass": not failed}
    out = {}
    for geoid, in c.execute("SELECT geoid FROM package_area ORDER BY 1").fetchall():
        ch = dict(sorted(results.get(geoid, {}).items()))
        gate = [v for k, v in ch.items() if k.rsplit(".", 1)[1] in GATE]
        passed = sum(v["pass"] for v in ch.values())
        out[geoid] = {"score": f"{passed}/{len(ch)}", "passed": passed, "applicable": len(ch),
                      "before": f"{sum(v['pass'] for v in gate)}/{len(gate)}",
                      "failing": [k for k, v in ch.items() if not v["pass"]], "checks": ch}
    return out


def job_totals(by_package):
    """job.json `validation`: each Package's score, the job's, and how many Packages fail each check."""
    passed = sum(v["passed"] for v in by_package.values())
    total = sum(v["applicable"] for v in by_package.values())
    gate = [v["before"].split("/") for v in by_package.values()]
    failing = {}
    for v in by_package.values():
        for k in v["failing"]:
            failing[k] = failing.get(k, 0) + 1
    return {"score": f"{passed}/{total}",
            "before": f"{sum(int(p) for p, _ in gate)}/{sum(int(t) for _, t in gate)}",
            "by_package": {g: {"score": v["score"], "before": v["before"]} for g, v in by_package.items()},
            "packages_failing": dict(sorted(failing.items(), key=lambda kv: (-kv[1], kv[0])))}
