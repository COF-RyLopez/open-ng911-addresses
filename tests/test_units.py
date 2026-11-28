import json

import pytest

from open_ng911 import ids, matcher, overture_release, registry, street
from open_ng911.sources.openaddresses import conform_sql


@pytest.mark.parametrize("raw, parsed, key", [
    ("N EIGHTH STREET W", ("N", "EIGHTH", "ST", "W"), " N 8TH ST W "),
    ("E ST", (None, "E", "ST", None), " E ST "),                      # E Street keeps its name
    ("AVENUE N", (None, "AVENUE N", None, None), " AVENUE N "),       # a street named for its letter
    ("05TH ST.", (None, "5TH", "ST", None), " 5TH ST "),              # zero padding and trailing period
    ("  north  main   rd ", ("N", "MAIN", "RD", None), " N MAIN RD "),
    ("SAINT FRANCIS AVENUE", (None, "SAINT FRANCIS", "AVE", None), " ST FRANCIS AVE "),
])
def test_parse_street(conn, raw, parsed, key):
    street.install(conn)
    p, k = conn.execute("SELECT parse_street(?), parsed_street_key(parse_street(?))", [raw, raw]).fetchall()[0]
    assert (p["predir"], p["name"], p["type"], p["posdir"]) == parsed
    assert k == key


def test_release_id_parsing(monkeypatch):
    assert overture_release.newest('"./2026-10-21.0/catalog.json", "./2026-11-18.0/catalog.json"') == "2026-11-18.0"
    assert overture_release.newest("<Prefix>release/2026-09-23.10/</Prefix><Prefix>release/2026-09-23.9/</Prefix>") == "2026-09-23.10"
    assert overture_release.newest("nothing here") is None
    monkeypatch.setenv("OVERTURE_RELEASE", "2026-11-18.0")
    assert overture_release.release_path() == "s3://overturemaps-us-west-2/release/2026-11-18.0"
    monkeypatch.setenv("OVERTURE_RELEASE", "latest")
    with pytest.raises(SystemExit):
        overture_release.release_id()


def test_ids_are_stable_and_never_gers():
    assert ids.agency_uid("us-vt-e911-esite", "1001") == ids.agency_uid("us-vt-e911-esite", "1001")
    assert ids.agency_uid("a", "1") != ids.agency_uid("b", "1")
    assert ids.minted_uid("g1") != ids.agency_uid("gers", "g1")
    assert ids.placeholder_domain("us-vt-50001").endswith(".invalid")
    assert ids.nguid("SSAP", "u", "d.gov") == "urn:emergency:uid:gis:SSAP:u:d.gov"


def test_registry_jobs():
    jobs = registry.jobs()
    assert len(jobs) == 65  # 50 states, DC, Puerto Rico, 13 provinces and territories
    assert len({j.id for j in jobs}) == 65
    # the pilots (other jobs turn on as their registries are written)
    assert {"us-vt", "us-me", "us-ut", "us-nd", "ca-pe"} <= {j.id for j in jobs if j.enabled}
    for j in jobs:
        if j.enabled:
            registry.jurisdiction(j)  # every enabled job has a valid jurisdiction registry


def test_registry_refuses_a_domain_without_opt_in(vt):
    job, jur = vt
    jur.authorities[0].domain = "example.gov"
    with pytest.raises(AssertionError, match="opts in"):
        registry.validate(jur, job)


def test_conform_sql():
    assert conform_sql("A") == "nullif(trim(coalesce(p->>'A', '')), '')"
    assert "concat_ws" in conform_sql(["A", "B"])
    assert conform_sql({"function": "regexp"}) == "NULL"


def test_conform_functions(conn):
    """The centerline conform functions, as OpenAddresses' centerline sources write them."""
    oneway = conform_sql({"function": "map", "field": "ONEWAY", "mapping": {"Y": "yes", "X": "reverse"}, "else": "no"})
    cls = conform_sql({"function": "map", "field": "C", "mapping": {"1": "motorway"}})  # unmapped values pass through
    kph = conform_sql({"function": "mph_to_kph", "field": "S"})
    name = conform_sql({"function": "join", "fields": ["A", "B"], "separator": "-"})
    got = conn.execute(f"SELECT {oneway}, {cls}, {kph}, {name} FROM (SELECT ?::JSON AS p)",
                       ['{"ONEWAY": "X", "C": "7", "S": 25, "A": "x", "B": "y"}']).fetchall()[0]
    assert got == ("reverse", "7", "40", "x-y")


def test_oa_address_functions(conn):
    """OpenAddresses' address functions give what its batch-machine conform gives on the same row."""
    row = {"ADDR": "123 Maple St Apt 4", "N": "12.0", "D": "N", "S": "Main", "T": "", "FULL": "12 N Main St",
           "PRE": "12", "CODE": "A-77", "E": "  "}
    cases = [
        ({"function": "prefixed_number", "field": "ADDR"}, "123"),
        ({"function": "prefixed_number", "field": "S"}, None),
        ({"function": "postfixed_street", "field": "ADDR"}, "Maple St Apt 4"),
        ({"function": "postfixed_street", "field": "ADDR", "may_contain_units": True}, "Maple St"),
        ({"function": "postfixed_unit", "field": "ADDR"}, "Apt 4"),
        ({"function": "regexp", "field": "CODE", "pattern": "^([A-Z])-(\\d+)$"}, "A77"),
        ({"function": "regexp", "field": "CODE", "pattern": "^Z"}, None),
        ({"function": "regexp", "field": "ADDR", "pattern": "(\\d+)", "replace": "#$1"}, "#123 Maple St Apt #4"),
        ({"function": "regexp", "field": "ADDR", "pattern": "^(?=1)"}, None),  # lookahead: RE2 can't
        ({"function": "remove_prefix", "field": "FULL", "field_to_remove": "PRE"}, "N Main St"),
        ({"function": "remove_postfix", "field": "FULL", "field_to_remove": "T"}, "12 N Main St"),
        ({"function": "format", "fields": ["N", "D", "S"], "format": "$1 $2 $3"}, "12 N Main"),
        ({"function": "format", "fields": ["T", "S"], "format": "$1-$2"}, "Main"),
        ({"function": "format", "fields": ["T", "E"], "format": "x$1-$2"}, None),
        ({"function": "first_non_empty", "fields": ["T", "E", "S"]}, "Main"),
        ({"function": "constant", "value": "VT"}, "VT"),
        ({"function": "chain", "variable": "st", "functions": [
            {"function": "postfixed_street", "field": "ADDR", "may_contain_units": True},
            {"function": "regexp", "field": "st", "pattern": " St$", "replace": " Street"}]}, "Maple Street"),
    ]
    sql = ", ".join(conform_sql(spec) for spec, _ in cases)
    got = conn.execute(f"SELECT {sql} FROM (SELECT ?::JSON AS p)", [json.dumps(row)]).fetchall()[0]
    assert list(got) == [want for _, want in cases]


def test_road_helpers(conn):
    import datetime

    from open_ng911 import roads
    from open_ng911.sources import centerlines
    conn.execute("CREATE TABLE package_area AS SELECT ST_MakeEnvelope(-73.4, 42.7, -71.5, 45.0) AS geom")
    assert roads.utm_epsg(conn) == "EPSG:32618"  # Vermont
    assert centerlines.tiger_vintages(datetime.date(2026, 11, 26)) == [2026, 2025, 2024]


def test_every_country_has_one_row_and_its_boundary_loaders():
    """What differs by country lives in registry.COUNTRIES: every job's country has a row, and its boundary
    module has the two loaders boundaries.py dispatches to."""
    import importlib
    for j in registry.jobs():
        k = registry.country(j)
        module = importlib.import_module(f"open_ng911.sources.{k.boundaries}")
        assert callable(module.load_package_area) and callable(module.load_municipality)


def test_openaddresses_pin(monkeypatch):
    from open_ng911.sources import openaddresses
    p = openaddresses.pin()
    assert len(p["commit"]) == 40 and p["date"]
    assert openaddresses.source_paths("us-vt") == ["us/vt/statewide"]
    assert openaddresses.source_paths("ca-pe") == ["ca/pe/province"]
    monkeypatch.setenv("OPENADDRESSES_COMMIT", "abc123")
    assert openaddresses.pin() == {"commit": "abc123", "date": None}


def test_discover_openaddresses_sources():
    """A state's address sources from OpenAddresses' registry: the statewide one where it exists, else counties
    before cities; a path the registry names is left to the registry, and licences map to our statuses."""
    from open_ng911 import registry
    from open_ng911.sources import openaddresses

    def layer(name, lic=None, ident="ID"):
        return {"name": name, "data": "https://x/FeatureServer/0", "protocol": "ESRI", "license": lic,
                "attribution": f"{name} agency", "conform": {"number": "N", "street": "S", "id": ident}}

    defs = {
        "us/zz/alpha": {"coverage": {"US Census": {"geoid": "99001", "name": "Alpha County"}},
                        "layers": {"addresses": [layer("county", "https://creativecommons.org/licenses/by/4.0/")]}},
        "us/zz/city_of_beta": {"coverage": {"city": "Beta"}, "layers": {"addresses": [layer("city")]}},
        "us/zz/gamma": {"coverage": {"US Census": {"geoid": "99005"}},
                        "layers": {"addresses": [layer("county", {"text": "ODbL"})]}},
        "us/zz/named": {"coverage": {}, "layers": {"addresses": [layer("county")]}},
    }
    job = registry.Job(id="us-zz", country="US", code="ZZ", fips="99", name="Z", enabled=False)
    named = registry.Source(key="mine", agency="A", layer="addresses", covers="*", license_status="open",
                            openaddresses="us/zz/named", oa_layer="county")
    jur = registry.Jurisdiction(job="us-zz", packages="county", authorities=[], sources=[named], discover=["addresses"])
    found = openaddresses.discover(job, jur, paths=[*defs, "us/zy/other"], definition=defs.__getitem__)
    assert [s.openaddresses for s in found] == ["us/zz/alpha", "us/zz/gamma", "us/zz/city_of_beta"]
    assert [s.license_status for s in found] == ["open", "share-alike", "unknown"]
    assert found[0].key == "oa-us-zz-alpha-county" and found[0].id_field == "ID"
    whole = {**defs, "us/zz/statewide": {"coverage": {}, "layers": {"addresses": [layer("state")]}}}
    found = openaddresses.discover(job, jur, paths=list(whole), definition=whole.__getitem__)
    assert [s.openaddresses for s in found] == ["us/zz/statewide"]


def test_licence_status_non_commercial():
    """A non-commercial licence isn't open, though its text starts like CC BY."""
    from open_ng911.sources import openaddresses
    st = openaddresses.licence_status
    assert st({"license": "CC-BY-4.0"}) == "open"
    assert st({"license": "CC-BY-NC-4.0"}) == "unknown"
    assert st({"license": {"text": "CC BY-NC 4.0", "url": "https://creativecommons.org/licenses/by-nc/4.0/"}}) == "unknown"
    assert st({"license": "CC BY-NC-SA 4.0"}) != "open"


def test_matcher_pairs_stacked_units(conn):
    """Records for units 1 and 2 at one spot, and Overture's two copies there: both pair, each with its own unit.
    One round of best mutual pairs left the second Record unpaired and its copy a gap-fill candidate."""
    pt = "ST_Point(-72.5, 44.2)"
    conn.execute(f"""CREATE TABLE agency_addr AS SELECT * FROM (VALUES
        ('r1', '10', 'MAIN', '1', 'g'), ('r2', '10', 'MAIN', '2', 'g'), ('r3', '12', 'MAIN', NULL, 'g'))
        t(address_uid, number, skey, unit, geoid), (SELECT {pt} AS geom)""")
    conn.execute(f"""CREATE TABLE overture_addr AS SELECT * FROM (VALUES
        ('o-a', '10', 'MAIN', '2', 'g'), ('o-b', '10', 'MAIN', '1', 'g'), ('o-c', '12', 'MAIN', NULL, 'g'))
        t(gers_id, number, skey, unit, geoid), (SELECT {pt} AS geom)""")
    assert matcher.match(conn) == 3
    assert dict(conn.execute("SELECT address_uid, gers_id FROM address_match").fetchall()) == {
        "r1": "o-b", "r2": "o-a", "r3": "o-c"}
    # without the unit ranking the rounds still pair them all
    conn.execute("UPDATE overture_addr SET unit = NULL")
    assert matcher.match(conn) == 3


def test_matcher_links_overture_double_copies(conn):
    """Overture holds some agency points twice: one copy pairs, the other is a copy of the Record, not a gap.
    A different number, street or unit, or a copy farther than COPY_M, stays unpaired."""
    conn.execute("""CREATE TABLE agency_addr AS SELECT *, skey AS street, ST_Point(-72.5, 44.2) AS geom
        FROM (VALUES ('r1', '10', 'MAIN', NULL::VARCHAR, 'g')) t(address_uid, number, skey, unit, geoid)""")
    conn.execute("""CREATE TABLE overture_addr AS SELECT gers_id, number, skey, skey AS street, unit, geoid,
               ST_Point(x, 44.2) AS geom
        FROM (VALUES ('o-a', '10', 'MAIN', NULL::VARCHAR, 'g', -72.5), ('o-b', '10', 'MAIN', NULL, 'g', -72.5),
                     ('o-c', '10', 'MAIN', '2', 'g', -72.5), ('o-d', '10', 'OAK', NULL, 'g', -72.5),
                     ('o-e', '10', 'MAIN', NULL, 'g', -72.49)) t(gers_id, number, skey, unit, geoid, x)""")
    assert matcher.match(conn) == 1
    assert matcher.copies(conn) == 1
    paired = conn.execute("SELECT gers_id FROM address_match").fetchall()[0][0]
    other = ({"o-a", "o-b"} - {paired}).pop()
    assert conn.execute("SELECT gers_id, address_uid FROM address_copy").fetchall() == [(other, "r1")]
    misses = matcher.copy_misses(conn)["by_difference"]
    assert sorted((m["same_number"], m["same_street"], m["same_unit"], m["n"]) for m in misses) == [
        (True, False, True, 1), (True, True, False, 1)]


def test_matcher_compares_the_full_number(conn):
    """A Source that keeps the suffix in its own field (VT HOUSE_NUMBERSUFFIX) gives OpenAddresses number '95';
    Overture holds '95 1/2'. They pair; plain '95' on Overture does not pair with 95 1/2."""
    conn.execute("""CREATE TABLE agency_addr AS SELECT *, skey AS street, ST_Point(-72.5, 44.2) AS geom
        FROM (VALUES ('r1', '95', 95, '1/2', NULL::VARCHAR, 'MAIN', NULL::VARCHAR, 'g'))
             t(address_uid, number, n_add_number, n_addnum_suf, n_addnum_pre, skey, unit, geoid)""")
    conn.execute("""CREATE TABLE overture_addr AS SELECT *, skey AS street, ST_Point(-72.5, 44.2) AS geom
        FROM (VALUES ('o-half', '95 1/2', 'MAIN', NULL::VARCHAR, 'g'), ('o-plain', '95', 'MAIN', NULL, 'g'))
             t(gers_id, number, skey, unit, geoid)""")
    assert matcher.match(conn) == 1
    assert conn.execute("SELECT address_uid, gers_id FROM address_match").fetchall() == [("r1", "o-half")]
    assert matcher.copies(conn) == 0
