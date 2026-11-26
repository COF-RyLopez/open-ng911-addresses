"""Offline fixtures: two small Vermont-shaped Packages, a few agency points (tests/fixtures/) and Overture
addresses written to a local parquet in Overture's schema, so the whole job runs without the network."""
import os

from open_ng911.sources import openaddresses, overture

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

    return {"package_area": package_area, "agency_addr": agency_addr, "overture_addr": overture_addr}
