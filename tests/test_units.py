import pytest

from open_ng911 import ids, overture_release, registry, street
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
    assert [j.id for j in jobs if j.enabled] == ["us-vt"]
    for j in jobs:
        if j.enabled:
            registry.jurisdiction(j)  # every enabled job has a valid jurisdiction registry


def test_registry_refuses_a_domain_without_opt_in(vt):
    job, jur = vt
    jur.authorities[0].domain = "example.gov"
    with pytest.raises(AssertionError, match="opts in"):
        registry.validate(jur, job)


def test_conform_sql():
    assert conform_sql("A") == "nullif(trim(p->>'A'), '')"
    assert "concat_ws" in conform_sql(["A", "B"])
    assert conform_sql({"function": "regexp"}) == "NULL"
