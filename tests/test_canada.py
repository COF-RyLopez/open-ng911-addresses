"""The Prince Edward Island job end to end on fixtures: census-division Packages, CLDXF-CA values, Canada's
domains beside NENA's, and the PEI civic address quirks (house numbers as doubles, route numbers after names)."""
import json
import os

import duckdb
from pe_fixtures import fixture_loaders

from open_ng911 import build, ids, nena, registry, street
from open_ng911.sources import statcan

RELEASE = "2026-11-18.0"


def rows(out, geoid):
    path = os.path.join(out, f"release={RELEASE}", "ca-pe", geoid, "site_structure_address_point.parquet")
    res = duckdb.connect().execute(f"SELECT * FROM read_parquet('{path}')")
    cols = [d[0] for d in res.description]
    return {r["source_id"]: r for r in (dict(zip(cols, v)) for v in res.fetchall())}


def test_pei_job(tmp_path, conn):
    out = str(tmp_path / "out")
    s = build.run("ca-pe", out, loaders=fixture_loaders(tmp_path), release=RELEASE, c=conn)
    assert s["gate_failures"] == []
    assert s["packages"] == 2
    assert s["records"] == 4  # the point outside every census division is dropped
    assert s["records_with_gers_id"] == 3
    assert s["gap_fill_candidates"] == 1

    queens, prince = rows(out, "1102"), rows(out, "1103")
    q = queens["5753470"]
    assert q["gers_id"] == "c1" and q["street_key_match"], "'QUEENS RD - RTE 210' is Queens Road"
    assert (q["add_number"], q["addnum_suf"]) == (427, None), "'427.0' is house number 427"
    assert (q["country"], q["a1"], q["a2"], q["st_name"], q["st_postyp"]) == ("CA", "PE", "Queens", "QUEENS", "Road")

    r = prince["5753488"]
    assert r["gers_id"] == "c2" and r["street_key_match"], "'RTE 11' is Route 11"
    assert (r["st_pretyp"], r["st_name"]) == ("Route", "11")

    e = prince["5753496"]
    assert e["gers_id"] == "c3" and e["street_key_match"], "accents don't split a street"
    assert (e["st_pretyp"], e["st_name"], e["st_postyp"]) == ("Rue", "DE L'EGLISE", None), "French generic is a pre type"

    t = queens["5753504"]
    assert t["gers_id"] is None and t["st_postyp"] == "Avenue" and t["unit"] == "2"
    assert queens["s4"]["status"] == "gap_fill_candidate"

    uid = ids.agency_uid("ca-pe-civic-address", "5753470")
    assert q["uid"] == uid
    assert q["nguid"] == f"urn:emergency:uid:gis:SSAP:{uid}:ca-pe-1102.unclaimed.invalid"

    d = os.path.join(out, f"release={RELEASE}", "ca-pe", "1102")
    with open(os.path.join(d, "manifest.json")) as f:
        m = json.load(f)
    assert m["nena"]["values"] == "CLDXF-CA" and m["opted_in"] is False
    assert m["recipient"].startswith("Prince Edward Island 911")
    assert m["sources"][0]["license_status"] == "open"
    with open(os.path.join(d, "domains.json"), encoding="utf-8") as f:
        dom = json.load(f)
    assert "Rue" in dom["CLDXF-CA"]["StreetNameTypeFrench"] and "Street" in dom["NENA-STA-006.3"]["StreetNameType"]
    assert "PE" in dom["CLDXF-CA"]["AdministrativeLevels1"]


def test_registry_ca_pe():
    j = registry.job("ca-pe")
    jur = registry.jurisdiction(j)
    assert j.enabled and jur.packages == "census_division" and j.fips == "11"


def test_french_pretypes_only_in_canada(conn):
    street.install(conn)

    def pre(country, s):
        nena.install(conn, country)
        # one step per CTE, as build.assemble_ssap does: nested macros expand inline
        conn.execute("CREATE OR REPLACE TABLE t AS SELECT parse_street(?) AS ps", [s])
        conn.execute("CREATE OR REPLACE TABLE t AS SELECT *, nena_type_word(ps.type) AS postyp FROM t")
        conn.execute("CREATE OR REPLACE TABLE t AS SELECT *, nena_pretype_raw(ps.name, postyp) AS raw FROM t")
        return conn.execute("SELECT nena_pretype_word(raw), nena_st_name(ps.name, raw) FROM t").fetchall()[0]
    assert pre("CA", "CH DU LAC") == ("Chemin", "DU LAC")
    assert pre("CA", "MONTÉE SAINT-PIERRE") == ("Montée", "SAINT-PIERRE")
    assert pre("US", "RUE DE LA PAIX") == (None, "RUE DE LA PAIX")
    assert pre("CA", "ROUTE 2") == ("Route", "2")


def test_canadian_street_types_are_registry_words():
    words = set(nena.street_types("CA"))
    assert {"Croissant", "Terrasse", "Chemin", "Rang", "Private"} <= words
    assert "Croissant" not in nena.street_types("US")


def test_census_subdivisions(tmp_path, conn):
    p = tmp_path / "csd.ndjson"
    sq = '{\\"type\\": \\"Polygon\\", \\"coordinates\\": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}'
    p.write_text(f'{{"p": {{"CSDUID": "1102075", "CSDNAME": "Charlottetown", "CSDTYPE": "CY"}}, "g": "{sq}"}}\n'
                 f'{{"p": {{"CSDUID": "1102071", "CSDNAME": "New London", "CSDTYPE": "FD"}}, "g": "{sq}"}}\n')
    statcan.create_municipality(conn, str(p))
    got = conn.execute("SELECT geoid, name, kind, incorporated FROM municipality ORDER BY 1").fetchall()
    assert got == [("1102071", "New London", "FD", False), ("1102075", "Charlottetown", "CY", True)]
