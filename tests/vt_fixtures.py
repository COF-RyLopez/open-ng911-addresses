"""Offline fixtures: two small Vermont-shaped Packages, a few agency points (tests/fixtures/) and Overture
addresses written to a local parquet in Overture's schema, so the whole job runs without the network."""
import os

from open_ng911.sources import centerlines, openaddresses, overture

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

# Two square Packages: Addison (around Middlebury) and Bennington
PACKAGES = [("50001", "Addison County", (-73.2, 44.0, -73.0, 44.2)),
            ("50003", "Bennington County", (-73.2, 42.8, -73.0, 43.0))]

# Overture addresses: (id, number, street, lon, lat, source record id)
OVERTURE = [
    ("o1", "12", "MAIN STREET", -73.10003, 44.1, "r1"),       # Record 1001, 3 m
    ("o2", "14", "NORTH 8TH ST", -73.10106, 44.1, "r2"),      # Record 1002, 5 m, same street key
    ("o3", "20", "OAK AVE", -73.10202, 44.1, "r3"),           # nearer to Record 1003 but another street
    ("o4", "20", "ELM ST", -73.10212, 44.1, "r4"),            # Record 1003, 10 m, same street: wins
    ("o5", "40", "BIRCH LN", -73.11, 44.11, "r5"),            # no Record: gap-fill candidate
    ("o6", "5", "VT ROUTE 9", -73.10002, 42.9, "r6"),         # Record 2001
    ("o7", "77", "FAR AWAY RD", -71.0, 41.0, "r7"),           # outside every Package
]


def write_overture_parquet(c, rows, path):
    values = ", ".join(
        f"('{i}', '{n}', '{s}', NULL, '05753', 'MIDDLEBURY', [{{'value': 'VT'}}], "
        f"[{{'dataset': 'National Address Database', 'record_id': '{r}', 'license': 'Public Domain'}}], "
        f"ST_Point({x}, {y}), {{'xmin': {x}, 'xmax': {x}, 'ymin': {y}, 'ymax': {y}}})"
        for i, n, s, x, y, r in rows)
    c.execute(f"""COPY (SELECT * FROM (VALUES {values})
                  t(id, number, street, unit, postcode, postal_city, address_levels, sources, geometry, bbox))
                  TO '{path}' (FORMAT parquet)""")


def fixture_loaders(tmp_path, overture_rows=OVERTURE):
    def package_area(c, job, jur, work):
        c.execute("CREATE OR REPLACE TABLE package_area AS SELECT * FROM (VALUES "
                  + ", ".join(f"('{g}', '{n}', ST_MakeEnvelope({b[0]}, {b[1]}, {b[2]}, {b[3]}))" for g, n, b in PACKAGES)
                  + ") t(geoid, name, geom)")

    def agency_addr(c, job, jur, work):
        source = jur.sources[0]
        entry = {"number": "HOUSE_NUMBER", "street": ["PD", "PT", "SN", "ST", "SD"], "city": "TOWNNAME",
                 "postcode": "ZIP", "addrtype": "SITETYPE"}  # the conform in us/vt/statewide.json
        openaddresses.create_agency_addr(c, source, os.path.join(FIXTURES, "vt_agency_points.ndjson"), entry, True)

    def overture_addr(c, job, jur, work):
        path = str(tmp_path / "overture.parquet")
        write_overture_parquet(c, overture_rows, path)
        overture.create_overture_addr(c, path)

    return {"package_area": package_area, "agency_addr": agency_addr, "overture_addr": overture_addr,
            **road_loaders(tmp_path)}


# Overture road segments (GERS ID, subtype, name, class, WKT). Only their IDs, and counts, may reach a Package.
SEGMENTS = [
    ("s1", "road", "Main Street", "secondary", "LINESTRING (-73.1062 44.10024, -73.0995 44.10024)"),  # MAIN ST 5001, west
    ("s2", "road", "Main Street", "secondary", "LINESTRING (-73.0995 44.10024, -73.0938 44.10024)"),  # MAIN ST 5001, east
    ("s3", "road", "Cross Street", "residential", "LINESTRING (-73.098 44.099, -73.098 44.101)"),     # crosses: no link
    # along N EIGHTH ST 5002, under another name and as a highway: one name and one class disagreement
    ("s4", "road", "Seminary Street", "trunk", "LINESTRING (-73.10104 44.1003, -73.10104 44.1081)"),
    ("s5", "rail", None, "standard_gauge", "LINESTRING (-73.106 44.1002, -73.094 44.1002)"),          # railway
    ("s7", "road", "Vermont Route 9", "secondary", "LINESTRING (-73.15 42.90003, -73.05 42.90003)"),  # Bennington TIGER
]

# TIGER ADDRFEAT for the Bennington fixture Package, which has no government centerlines
ADDRFEAT = [  # TLID, ARIDL, ARIDR, FULLNAME, LFROMHN, LTOHN, RFROMHN, RTOHN, ZIPL, ZIPR, ROAD_MTFCC, EDGE_MTFCC, WKT
    (618001, "A1", "A2", "Vermont Route 9", "1", "99", "2", "98", "05201", "05201", "S1200", "S1200",
     "LINESTRING (-73.15 42.9, -73.05 42.9)"),
    (618002, "A3", "", "Hidden Ln", "", "", "", "", "", "", "S1400", "S1400",
     "LINESTRING (-73.12 42.95, -73.119 42.951)"),
    (618003, "", "", "Rail Spur", "", "", "", "", "", "", "", "R1011", "LINESTRING (-73.12 42.96, -73.11 42.96)"),
]


def write_segment_parquet(c, rows, path):
    values = ", ".join(f"('{i}', '{t}', {{'primary': {repr(n) if n else 'NULL::VARCHAR'}}}, '{k}', NULL::VARCHAR, "
                       f"ST_GeomFromText('{w}'))" for i, t, n, k, w in rows)
    c.execute(f"""COPY (SELECT id, subtype, names, class, subclass, geometry,
                         {{'xmin': ST_XMin(geometry), 'xmax': ST_XMax(geometry),
                           'ymin': ST_YMin(geometry), 'ymax': ST_YMax(geometry)}} AS bbox
                  FROM (VALUES {values}) t(id, subtype, names, class, subclass, geometry)) TO '{path}' (FORMAT parquet)""")


def write_addrfeat(c, rows, path):
    values = ", ".join(
        "(" + ", ".join([str(r[0])] + [f"'{v}'" for v in r[1:-1]]) + f", ST_GeomFromText('{r[-1]}'))" for r in rows)
    c.execute(f"""COPY (SELECT * FROM (VALUES {values}) t(TLID, ARIDL, ARIDR, FULLNAME, LFROMHN, LTOHN, RFROMHN,
                                                          RTOHN, ZIPL, ZIPR, ROAD_MTFCC, EDGE_MTFCC, geom))
                  TO '{path}' (FORMAT GDAL, DRIVER 'ESRI Shapefile')""")


# TIGER ADDRFEAT for Addison, read only to compare with the E911 roads (upstream.py): it has MAIN ST and a road the
# E911 layer doesn't, and lacks N EIGHTH ST and the VT 125 ramp
ADDISON_ADDRFEAT = [
    (700001, "B1", "B2", "Main St", "1", "99", "2", "98", "05753", "05753", "S1200", "S1200",
     "LINESTRING (-73.106 44.10022, -73.094 44.10022)"),
    (700002, "B3", "", "Gone Rd", "", "", "", "", "", "", "S1400", "S1400",
     "LINESTRING (-73.05 44.05, -73.04 44.05)"),
]


def road_loaders(tmp_path, segments=SEGMENTS):
    def gov_roads(c, job, jur, work):
        source = next(s for s in jur.sources if s.layer == "centerlines")
        centerlines.insert_government(c, source, os.path.join(FIXTURES, "vt_e911_rds.ndjson"),
                                      source.oa_entry["conform"], True)
        centerlines.add_meta(c, {"source_key": source.key, "road_source": "government", "agency": source.agency,
                                 "license_status": source.license_status, "license_url": source.license_url,
                                 "attribution": source.attribution, "source_date": "2026-02-19",
                                 "fetched": "2026-11-26T00:00:00Z", "data_url": source.oa_entry["data"]})

    def tiger_roads(c, job, jur, work):
        assert [g for g, in c.execute("SELECT geoid FROM road_fallback").fetchall()] == ["50003"]
        path = str(tmp_path / "tl_2025_50003_addrfeat.shp")
        write_addrfeat(c, ADDRFEAT, path)
        centerlines.insert_tiger(c, path, 2025)
        centerlines.add_meta(c, {"source_key": "tiger-addrfeat-2025", "road_source": "tiger",
                                 "agency": "U.S. Census Bureau", "license_status": "open",
                                 "source_date": "TIGER/Line 2025"})

    def overture_segment(c, job, jur, work):
        path = str(tmp_path / "segments.parquet")
        write_segment_parquet(c, segments, path)
        overture.create_overture_segment(c, path)

    def national_roads(c, job, jur, work):
        centerlines.create_national_table(c)
        path = str(tmp_path / "tl_2025_50001_addrfeat.shp")
        write_addrfeat(c, ADDISON_ADDRFEAT, path)
        centerlines.insert_tiger(c, path, 2025, "national_seg")
        return {"layer": "TIGER/Line ADDRFEAT", "date": "TIGER/Line 2025"}

    return {"gov_roads": gov_roads, "tiger_roads": tiger_roads, "overture_segment": overture_segment,
            "national_roads": national_roads}
