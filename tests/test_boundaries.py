"""A2 and A3 boundary layers and every address point's A3 (boundaries.py, ADR 0009), on the Vermont fixtures."""
import json
import os

import duckdb
from vt_fixtures import fixture_loaders

from open_ng911 import boundaries, build, registry
from open_ng911.sources import tiger

RELEASE = "2026-11-18.0"


def read(out, geoid, layer):
    path = os.path.join(out, f"release={RELEASE}", "us-vt", geoid, f"{layer}.parquet")
    res = duckdb.connect().execute(f"SELECT * EXCLUDE (geom) FROM read_parquet('{path}', hive_partitioning = false)")
    cols = [d[0] for d in res.description]
    return [dict(zip(cols, v)) for v in res.fetchall()]


def test_vermont_boundaries(tmp_path, conn):
    out = str(tmp_path / "out")
    s = build.run("us-vt", out, loaders=fixture_loaders(tmp_path), release=RELEASE, c=conn)
    assert s["gate_failures"] == []
    assert s["a3"] == {"addresses_in_municipality": 6, "addresses_unincorporated": 1, "addresses_without_a3": 0,
                       "a3_polygons": 1}

    a3 = {r["source_id"]: r["a3"] for r in read(out, "50001", "site_structure_address_point")}
    assert a3["1002"] == "Middlebury", "the town's plain name, not 'Middlebury town'"
    assert a3["1001"] == "Middlebury", "1 m outside the generalized edge, inside the gore: snaps to the town"
    assert a3["r5"] == "Middlebury", "Gap-fill candidates get an A3 too"
    route = read(out, "50003", "site_structure_address_point")[0]
    assert route["a3"] == "Unincorporated"

    (county,) = read(out, "50001", "a2_polygon")
    assert (county["country"], county["a1"], county["a2"], county["source_code"]) == ("US", "VT", "Addison County", "50001")
    uid = boundaries.boundary_uid("us-a2", "50001")
    assert county["nguid"] == f"urn:emergency:uid:gis:A2:{uid}:us-vt-50001.unclaimed.invalid"
    assert county["discrpagid"] == "us-vt-50001.unclaimed.invalid"

    towns = read(out, "50001", "a3_polygon")
    assert [(t["a3"], t["a2"], t["source_code"]) for t in towns] == [("Middlebury", "Addison County", "5000144350")], (
        "the gore isn't a government and Ripton's 1 m sliver isn't in Addison")
    assert towns[0]["nguid"].startswith("urn:emergency:uid:gis:A3:")
    assert read(out, "50003", "a3_polygon") == []

    with open(os.path.join(out, f"release={RELEASE}", "us-vt", "50001", "manifest.json")) as f:
        m = json.load(f)
    assert m["nena"]["layers"] == ["SiteStructureAddressPoint", "A2Polygon", "A3Polygon"]
    assert m["boundaries"]["A3Polygon"]["features"] == 1
    assert m["boundaries"]["A3Polygon"]["record_community_agrees_with_a3"] == 1.0
    assert m["boundaries"]["A2Polygon"]["license"] == "public domain"
    assert m["field_fill"]["a3"] == 1.0


def test_no_municipalities_leaves_a3_empty(conn):
    """A job whose country has no municipality loader yet: A3 stays empty rather than 'Unincorporated'."""
    conn.execute("CREATE TABLE ssap AS SELECT 'u1' AS uid, NULL::VARCHAR AS a3, '50001' AS geoid, ST_Point(-73, 44) AS geom")
    conn.execute("CREATE TABLE municipality (geoid VARCHAR, name VARCHAR, kind VARCHAR, incorporated BOOLEAN, geom GEOMETRY)")
    boundaries.assign_a3(conn)
    assert conn.execute("SELECT a3 FROM ssap").fetchall() == [(None,)]


def test_municipality_layer_by_state():
    jobs = {j.code: j for j in registry.jobs()}
    assert tiger.municipality_layer(jobs["VT"]) == tiger.COUSUB_LAYER  # strong MCD: towns
    assert tiger.municipality_layer(jobs["CA"]) == tiger.PLACE_LAYER   # California's code, not Canada
    assert boundaries.boundary_uid("us-a3", "x") == boundaries.boundary_uid("us-a3", "x")


def test_strong_mcd_state_adds_independent_cities(tmp_path, conn):
    """Vermont: a city whose county subdivision is fictitious is A3 as a place; a village inside a town isn't."""
    def write(name, rows):
        path = tmp_path / f"{name}.ndjson"
        with open(path, "w") as f:
            for geoid, nm, base, funcstat, (x0, y0, x1, y1) in rows:
                ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
                f.write(json.dumps({"p": {"GEOID": geoid, "NAME": nm, "BASENAME": base, "FUNCSTAT": funcstat},
                                    "g": json.dumps({"type": "Polygon", "coordinates": [ring]})}) + "\n")
        return str(path)

    tiger.create_municipality(conn, write("cousub", [
        ("5000710675", "Burlington city", "Burlington", "F", (0, 0, 1, 1)),
        ("5000724175", "Essex town", "Essex", "A", (1, 0, 3, 1))]), "county subdivision")
    tiger.add_independent_places(conn, write("places", [
        ("5010675", "Burlington city", "Burlington", "A", (0, 0, 1, 1)),
        ("5024400", "Village of Somewhere village", "Village of Somewhere", "A", (1.5, 0.2, 1.8, 0.8))]))
    got = conn.execute("SELECT geoid, name, kind, incorporated FROM municipality ORDER BY 1").fetchall()
    assert got == [("5000710675", "Burlington", "city", False), ("5000724175", "Essex", "town", True),
                   ("5010675", "Burlington", "city", True)]
