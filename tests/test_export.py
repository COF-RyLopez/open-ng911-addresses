"""The statewide GeoPackage: NENA's template, every Package's layers, fields checked, agency-owned fields owed."""
import os
import sqlite3

import pytest
from test_pipeline import RELEASE, fixture_loaders
from vt_fixtures import ESZ, zone_loader

from open_ng911 import build, export

pyogrio = pytest.importorskip("pyogrio")


def test_statewide_geopackage(tmp_path, conn):
    out = str(tmp_path / "out")
    # a fire district across both counties: the build clips it into each Package
    state = ({"PSAP_DisplayName": "Williston PSAP", "LAW_DisplayName": "VSP", "FIRE_DisplayName": "Valley Fire District",
              "EMS_DisplayName": None, "UPDATEDATE": 1700000000000}, (-73.2, 42.9, -73.19, 44.1))
    loaders = {**fixture_loaders(tmp_path), "nena_layers": zone_loader(tmp_path, [*ESZ, state])}
    build.run("us-vt", out, loaders=loaders, release=RELEASE, c=conn)
    gpkg = str(tmp_path / "us-vt.gpkg")
    r = export.export(os.path.join(out, f"release={RELEASE}", "us-vt"), gpkg)
    assert r["packages"] == ["50001", "50003"]
    layers = {name for name, _ in pyogrio.list_layers(gpkg)}
    assert {"SiteStructureAddressPoint", "RoadCenterLine", "FirePolygon"} <= layers, "NENA's own layer names"
    assert r["layers"]["SiteStructureAddressPoint"] == pyogrio.read_info(gpkg, layer="SiteStructureAddressPoint")["features"]
    fields = pyogrio.read_info(gpkg, layer="RoadCenterLine")["fields"]
    assert "NGUID" in fields and "FromAddr_L" in fields, "NENA's field names"
    # the agency's fields: empty, owed, and allowed empty in this copy only
    assert r["agency_owed"]["FirePolygon"] == {f: r["layers"]["FirePolygon"] for f in ("Agency_ID", "ServiceURI", "AVcard_URI")}
    con = sqlite3.connect(gpkg)
    ddl = con.execute("SELECT sql FROM sqlite_master WHERE name = 'FirePolygon'").fetchone()[0]
    assert "[Agency_ID] TEXT(100) check([Agency_ID] is null or (typeof([Agency_ID]) = 'text'" in ddl
    assert "[DsplayName] TEXT(60) check(typeof([DsplayName]) = 'text' and not length([DsplayName]) > 60) not null" in ddl
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert os.path.exists(gpkg + ".report.json")
    # a zone the build clipped at the county seam is one feature again
    fires = os.path.join(out, f"release={RELEASE}", "us-vt", "*", "fire_polygon.parquet")
    pieces, zones = conn.execute(f"SELECT count(*), count(DISTINCT (source, source_id)) FROM read_parquet('{fires}')").fetchall()[0]
    assert r["layers"]["FirePolygon"] == zones and pieces > zones, (pieces, zones)


def test_missing_required_value_is_left_empty_and_reported(tmp_path, conn):
    """A road a source left unnamed is still written, St_Name empty, and counted; nothing is filled in."""
    out = str(tmp_path / "out")
    build.run("us-vt", out, loaders=fixture_loaders(tmp_path), release=RELEASE, c=conn)
    job = os.path.join(out, f"release={RELEASE}", "us-vt")
    roads = os.path.join(job, "50001", "road_centerline.parquet")
    conn.execute(f"COPY (SELECT * REPLACE (CASE WHEN row_number() OVER () = 1 THEN NULL ELSE st_name END AS st_name) "
                 f"FROM read_parquet('{roads}')) TO '{tmp_path}/r.parquet' (FORMAT parquet)")
    os.replace(tmp_path / "r.parquet", roads)
    gpkg = str(tmp_path / "us-vt.gpkg")
    r = export.export(job, gpkg)
    assert r["problems"]["RoadCenterLine"]["St_Name"] == {"missing_required": 1}
    assert r["layers"]["RoadCenterLine"] == pyogrio.read_info(gpkg, layer="RoadCenterLine")["features"], "every road"
    assert set(export.required(gpkg, "RoadCenterLine")) == set(export.required(export.TEMPLATE, "RoadCenterLine")) - {"St_Name"}
    assert "DiscrpAgID" in export.required(gpkg, "RoadCenterLine"), "complete fields stay NOT NULL"
