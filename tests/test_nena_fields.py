"""Each Source's own fields into NENA fields (fieldmap.py), the other NENA layers (layers.py) and the coverage
report (coverage.py), on the offline Vermont and PEI fixtures."""
import dataclasses
import json
import os

import duckdb
import pe_fixtures
import pytest
from vt_fixtures import fixture_loaders

from open_ng911 import build, fieldmap, nena, registry, street

RELEASE = "2026-11-18.0"


def read(out, job, geoid, name):
    path = os.path.join(out, f"release={RELEASE}", job, geoid, name + ".parquet")
    if not os.path.exists(path):
        return []
    res = duckdb.connect().execute(f"SELECT * EXCLUDE (geom) FROM read_parquet('{path}')")
    cols = [d[0] for d in res.description]
    return [dict(zip(cols, v)) for v in res.fetchall()]


def manifest(out, job, geoid):
    with open(os.path.join(out, f"release={RELEASE}", job, geoid, "manifest.json")) as f:
        return json.load(f)


@pytest.fixture
def vt_build(tmp_path, conn):
    out = str(tmp_path / "out")
    return out, build.run("us-vt", out, loaders=fixture_loaders(tmp_path), release=RELEASE, c=conn)


@pytest.mark.parametrize("field, message", [("nguid", "opts in"), ("discrpagid", "opts in"),
                                            ("a2", "boundary layers"), ("esn_l", "isn't a")])
def test_registry_refuses_fields_that_are_ours(vt, field, message):
    job, jur = vt
    s = jur.sources[0]
    jur.sources[0] = dataclasses.replace(s, nena={**s.nena, field: "ESN"})
    with pytest.raises(AssertionError, match=message):
        registry.validate(jur, job)


def test_values_are_checked_against_the_field(conn):
    street.install(conn)
    nena.install(conn)
    fieldmap.install(conn)
    fields = {f["name"]: f for f in nena.layer_fields("SiteStructureAddressPoint", "US")}

    def norm(field, raw):
        return conn.execute(f"SELECT {fieldmap.normalize_sql(raw, fields[field])}").fetchall()[0][0]

    assert norm("st_postyp", "'RD'") == "Road" and norm("st_predir", "'N'") == "North"
    assert norm("placement", "'GEOCODING'") == "Geocoding", "coded domains match without regard to case"
    assert norm("placement", "'GUESSED'") is None, "a value outside the domain is left empty"
    assert norm("add_number", "'30B'") == 30
    assert norm("dateupdate", "'1700000000000'") == "2023-11-14T22:13:20Z"
    assert norm("dateupdate", "'-2209161600000'") is None, "1899-12-30 is a placeholder"
    assert norm("unitpretyp", "'APT'") == "Apartment"
    assert norm("esn", "'" + "9" * 6 + "'") is None, "longer than NENA's ESN"


def test_vermont_points_carry_the_source_fields(vt_build):
    out, s = vt_build
    pts = {r["source_id"]: r for r in read(out, "us-vt", "50001", "site_structure_address_point")}
    assert pts["1001"]["esn"] == "101" and pts["1001"]["dateupdate"] == "2023-11-14T22:13:20Z"
    assert pts["1003"]["esn"] is None, "never invented where the Source has none"
    assert pts["1004"]["addnum_suf"] == "B"
    cov = s["nena_coverage"]["SiteStructureAddressPoint"]
    assert cov["fields"]["esn"]["status"] == "partial" and cov["fields"]["esn"]["before"] == 0.0
    assert cov["fields"]["esn"]["source"] == ["us-vt-e911-esite: ESN"]
    assert "rejected" not in cov["fields"]["place_type"], "a site type the map leaves blank is no value, not a rejection"
    assert cov["fields"]["nguid"]["derived"] and cov["fields"]["nguid"]["required"]
    assert cov["before"]["partial"] < cov["partial"] or cov["before"]["no_source"] > cov["no_source"]


def test_zones_merge_into_service_layers(vt_build):
    out, s = vt_build
    fire = read(out, "us-vt", "50001", "fire_polygon")
    assert [r["dsplayname"] for r in fire] == ["Middlebury FD"], "two zones, one department: one polygon"
    assert fire[0]["serviceurn"] == "urn:emergency:service:responder.fire"
    assert fire[0]["nguid"].endswith(":us-vt-50001.unclaimed.invalid")
    assert fire[0]["agency_id"] is None and fire[0]["serviceuri"] is None, "the agency's, never ours"
    assert sorted(r["dsplayname"] for r in read(out, "us-vt", "50001", "police_polygon")) == [
        "Middlebury PD", "VSP New Haven"]
    assert read(out, "us-vt", "50003", "ems_polygon") == [], "a zone with no EMS name feeds no EMS polygon"
    assert s["features_dropped"]["EmsPolygon"] == {"no_dissolve_value": 1}, "and is counted"
    psap = read(out, "us-vt", "50003", "psap_polygon")
    assert psap[0]["dsplayname"] == "Rutland PSAP" and psap[0]["dateupdate"] != "1899-12-30T00:00:00Z"
    assert psap[0]["source_license"] == "unknown"

    m = manifest(out, "us-vt", "50001")
    assert "FirePolygon" in m["nena"]["layers"]
    assert m["nena_layers"]["FirePolygon"]["sources"][0]["source_key"] == "us-vt-e911-esz-fire"
    assert m["nena_coverage"]["FirePolygon"]["fields"]["dsplayname"]["status"] == "filled"


def test_provisioning_falls_back_to_the_package_area(vt_build):
    out, s = vt_build
    for geoid in ("50001", "50003"):
        (p,) = read(out, "us-vt", geoid, "provisioning_polygon")
        assert p["source"] == "package-area" and p["source_id"] == geoid
        assert p["nguid"].startswith("urn:emergency:uid:gis:Provisioning:")
    assert s["nena_coverage"]["ProvisioningPolygon"]["features"] == 2


def test_pei_zones_only_where_they_reach(tmp_path, conn):
    out = str(tmp_path / "out")
    s = build.run("ca-pe", out, loaders=pe_fixtures.fixture_loaders(tmp_path), release=RELEASE, c=conn)
    assert [r["dsplayname"] for r in read(out, "ca-pe", "1102", "psap_polygon")] == ["Charlottetown PSAP"]
    assert read(out, "ca-pe", "1103", "psap_polygon") == []
    assert s["nena_coverage"]["EmsPolygon"]["built"]
    assert "unitpretyp" not in s["nena_coverage"]["SiteStructureAddressPoint"]["fields"], "CLDXF-CA keeps Unit"
