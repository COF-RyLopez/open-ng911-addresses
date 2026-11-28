"""Offline fixtures for the Prince Edward Island job: two census divisions, PEI civic address points
(tests/fixtures/pe_agency_points.ndjson, in the provincial layer's fields) and Overture addresses written the
way Overture writes Canadian ones (spelled-out types, accents), so the whole job runs without the network."""
import json
import os

from vt_fixtures import write_segment_parquet, zone_loader

from open_ng911.sources import centerlines, openaddresses, overture, statcan

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

# StatCan census divisions (CDUID, CDNAME) as squares: Queens around Charlottetown, Prince around Wellington
PACKAGES = [("1102", "Queens", (-63.4, 46.1, -63.0, 46.4)),
            ("1103", "Prince", (-64.2, 46.4, -63.6, 46.9))]

# StatCan census subdivisions (CSDUID, CSDNAME, CSDTYPE, bbox): Charlottetown is a city (A3); the fire district
# west of it isn't a local government, so its addresses are 'Unincorporated'
MUNICIPALITIES = [("1102075", "Charlottetown", "CY", (-63.14, 46.22, -63.10, 46.26)),
                  ("1102071", "New London", "FD", (-63.20, 46.22, -63.14, 46.30))]

# (id, number, street, lon, lat, source record id)
OVERTURE = [
    ("c1", "427", "Queens Road", -63.13006, 46.24, "s1"),       # PEI writes 'QUEENS RD - RTE 210'
    ("c2", "9617", "Route 11", -63.90004, 46.5, "s2"),          # PEI writes 'RTE 11'
    ("c3", "12", "Rue de l'Église", -63.91003, 46.51, "s3"),    # PEI writes it without the accent
    ("c4", "88", "Grafton Street", -63.12, 46.23, "s4"),        # no Record: gap-fill candidate
]

# Emergency service zones in the province's fields: one in Queens only, so Prince gets no service polygons
ESZ = [({"PSAP": "Charlottetown PSAP", "POLICE": "Charlottetown Police", "FIRE": "Charlottetown Fire",
         "EMS": "Island EMS"}, (-63.3, 46.15, -63.05, 46.35))]


def _q(v):
    return "'" + str(v).replace("'", "''") + "'"


def write_overture_parquet(c, rows, path, licence="OGL-CA"):
    values = ", ".join(
        f"({_q(i)}, {_q(n)}, {_q(s)}, NULL, NULL, 'Charlottetown', [{{'value': 'PE'}}], "
        f"[{{'dataset': 'OpenAddresses/Statistics Canada', 'record_id': {_q(r)}, 'license': {_q(licence)}}}], "
        f"ST_Point({x}, {y}), {{'xmin': {x}, 'xmax': {x}, 'ymin': {y}, 'ymax': {y}}})"
        for i, n, s, x, y, r in rows)
    c.execute(f"""COPY (SELECT * FROM (VALUES {values})
                  t(id, number, street, unit, postcode, postal_city, address_levels, sources, geometry, bbox))
                  TO '{path}' (FORMAT parquet)""")


def fixture_loaders(tmp_path, overture_rows=OVERTURE, overture_licence="OGL-CA"):
    def package_area(c, job, jur, work):
        c.execute("CREATE OR REPLACE TABLE package_area AS SELECT * FROM (VALUES "
                  + ", ".join(f"('{g}', '{n}', ST_MakeEnvelope({b[0]}, {b[1]}, {b[2]}, {b[3]}))" for g, n, b in PACKAGES)
                  + ") t(geoid, name, geom)")

    def municipality(c, job, jur, work):
        path = tmp_path / "csd.ndjson"
        with open(path, "w") as f:
            for geoid, name, kind, (x0, y0, x1, y1) in MUNICIPALITIES:
                ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
                f.write(json.dumps({"p": {"CSDUID": geoid, "CSDNAME": name, "CSDTYPE": kind},
                                    "g": json.dumps({"type": "Polygon", "coordinates": [ring]})}) + "\n")
        statcan.create_municipality(c, str(path))

    def agency_addr(c, job, jur, work):
        entry = {"number": "STREET_NO", "street": "STREET_NM", "unit": "APT_NO", "city": "COMM_NM",
                 "district": "COUNTY"}  # the conform in ca/pe/province.json
        openaddresses.create_agency_addr(c, jur.sources[0], os.path.join(FIXTURES, "pe_agency_points.ndjson"), entry, True)

    def overture_addr(c, job, jur, work):
        path = str(tmp_path / "overture_pe.parquet")
        write_overture_parquet(c, overture_rows, path, overture_licence)
        overture.create_overture_addr(c, path)

    def overture_segment(c, job, jur, work):
        path = str(tmp_path / "segments_pe.parquet")
        write_segment_parquet(c, [("p1", "road", "Queens Road", "secondary", "LINESTRING (-63.135 46.24, -63.125 46.24)")], path)
        overture.create_overture_segment(c, path)

    # The fixture has no PEI road centrelines and TIGER doesn't cover Canada: every Package has an empty RoadCenterline
    return {"nena_layers": zone_loader(tmp_path, ESZ), "package_area": package_area, "municipality": municipality, "agency_addr": agency_addr,
            "overture_addr": overture_addr, "gov_roads": lambda c, job, jur, work: None,
            "tiger_roads": centerlines.load_tiger, "overture_segment": overture_segment,
            "national_roads": centerlines.load_national_reference}
