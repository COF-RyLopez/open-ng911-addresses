"""The Portolan catalog on the pilot fixtures: what goes public and what is withheld, the STAC tree, checksums,
links, and (when portolan-cli is installed) the Portolan validator."""
import glob
import json
import os
import shutil
import subprocess

import duckdb
import pyarrow.parquet as pq
import pytest
from pe_fixtures import fixture_loaders as pe_loaders
from vt_fixtures import fixture_loaders as vt_loaders

from open_ng911 import build, catalog, db, registry

RELEASE = "2026-11-18.0"


@pytest.fixture(scope="module")
def builds(tmp_path_factory):
    """Vermont and PEI built on fixtures. Vermont twice: as registered (licence unknown) and from a registry
    copy that calls its sources open, so a published Package with roads can be checked too."""
    tmp = tmp_path_factory.mktemp("catalog")
    open_reg = tmp / "registry"
    shutil.copytree(registry.REGISTRY_DIR, open_reg)
    vt = (open_reg / "us" / "vt.toml").read_text().replace('license_status = "unknown"', 'license_status = "open"')
    (open_reg / "us" / "vt.toml").write_text(vt)
    out, out_open = str(tmp / "out"), str(tmp / "out_open")
    for o, reg in ((out, registry.REGISTRY_DIR), (out_open, str(open_reg))):
        for job, loaders in (("us-vt", vt_loaders), ("ca-pe", pe_loaders)):
            work = tmp / f"{os.path.basename(o)}-{job}"
            work.mkdir()
            build.run(job, o, loaders=loaders(work), release=RELEASE, c=db.connect(s3=False), registry_dir=reg)
    return tmp, out, out_open


def test_open_license():
    for name in ("CC0-1.0", "CC-BY-4.0", "Public Domain", "OGL-CA", "PDDL-1.0", "ODC-By-1.0",
                 "LicenseRef-Public-Domain-US"):  # Overture's tag on US government addresses (ME, UT, VT, ND)
        assert catalog.open_license(name), name
    for name in ("ODbL-1.0", "CC-BY-SA-4.0", "unstated", "", None, "proprietary", "LicenseRef-Proprietary",
                 "CC-BY-NC-4.0", "CC BY-NC-SA 4.0"):
        assert not catalog.open_license(name), name


def test_closed_gap_fill_rows_left_out(tmp_path):
    """Overture labels its Canadian addresses LicenseRef-Proprietary: a Package whose Gap-fill candidates carry a
    closed licence is still published, its public address points without those rows, and the report and the
    collection count them. The build's own file keeps every row."""
    out = str(tmp_path / "out")
    build.run("ca-pe", out, loaders=pe_loaders(tmp_path, overture_licence="LicenseRef-Proprietary"), release=RELEASE,
              c=db.connect(s3=False))
    r = catalog.build(RELEASE, out, str(tmp_path / "cat"))
    assert [p["package"] for p in r["published"]] == ["ca-pe-1102", "ca-pe-1103"] and r["withheld"] == []
    pe = {p["package"]: p for p in r["published"]}
    assert pe["ca-pe-1102"]["withheld_gap_fill"] == {"LicenseRef-Proprietary": 1}
    assert "site_structure_address_point" not in pe["ca-pe-1102"]["withheld_layers"]
    d = os.path.join(tmp_path, "cat", "public", "ca", "ca-pe", "ca-pe-1102")
    pub = os.path.join(d, "ca-pe-1102-site-structure-address-point", "site_structure_address_point.parquet")
    src = os.path.join(out, f"release={RELEASE}", "ca-pe", "1102", "site_structure_address_point.parquet")
    q = "SELECT count(*) FILTER (status = 'gap_fill_candidate'), count(*) FROM read_parquet('{}')"
    built, public = (duckdb.connect().execute(q.format(p)).fetchall()[0] for p in (src, pub))
    assert built[0] == 1 and public == (0, built[1] - 1)
    assert json.loads(pq.read_metadata(pub).metadata[b"geo"])["version"] == "2.0.0"
    with open(os.path.join(d, "collection.json")) as f:
        coll = json.load(f)
    assert coll["ng911:withheld_gap_fill"] == {"LicenseRef-Proprietary": 1} and "left out" in coll["description"]
    with open(os.path.join(d, "ca-pe-1102-site-structure-address-point",
                           "ca-pe-1102-site-structure-address-point.json")) as f:
        item = json.load(f)
    a = item["assets"]["site_structure_address_point"]
    assert item["properties"]["table:row_count"] == public[1] and a["file:checksum"] == catalog.checksum(pub)


def test_pilots_as_registered(builds):
    """As registered today: PEI's sources are open, so its Packages are published, marked unclaimed (no authority
    has opted in; ADR 0003 as amended, 0011). Vermont's licence is unknown, so it is a scorecard row only and none
    of its files are in the public tree. require_opt_in=True restores the stricter gate."""
    tmp, out, _ = builds
    cat = str(tmp / "cat_default")
    r = catalog.build(RELEASE, out, cat)
    assert [p["package"] for p in r["published"]] == ["ca-pe-1102", "ca-pe-1103"]
    reasons = {w["package"]: w["reasons"] for w in r["withheld"]}
    assert reasons == {p: ["source_license:us-vt-e911-esite=unknown"] for p in ("us-vt-50001", "us-vt-50003")}
    # a published Package leaves out only the layers whose own source is closed: PEI's emergency service zones
    pe = {p["package"]: p["withheld_layers"] for p in r["published"]}
    assert pe["ca-pe-1102"] == {s: [f"source_license:ca-pe-esz-{k}=unknown"]
                                for s, k in (("psap_polygon", "psap"), ("police_polygon", "police"),
                                             ("fire_polygon", "fire"), ("ems_polygon", "ems"))}
    pub = os.path.join(cat, "public")
    assert sorted(os.listdir(pub)) == ["AGENTS.md", "README.md", "ca", "catalog.json", "scorecard"]
    assert not glob.glob(os.path.join(pub, "**", "*50001*"), recursive=True)
    assert not glob.glob(os.path.join(pub, "**", "*psap_polygon.parquet"), recursive=True)
    with open(os.path.join(pub, "ca", "ca-pe", "ca-pe-1102", "collection.json")) as f:
        coll = json.load(f)
    assert coll["title"].endswith("(unclaimed)") and "unclaimed" in coll["keywords"]
    assert "not issued or checked by" in coll["description"] and coll["ng911:opted_in"] is False
    res = duckdb.connect().execute(f"SELECT package, published, records FROM "
                                   f"read_parquet('{pub}/scorecard/scorecard.parquet') ORDER BY package").fetchall()
    assert [(p, pub_) for p, pub_, _ in res] == [("ca-pe-1102", True), ("ca-pe-1103", True),
                                                 ("us-vt-50001", False), ("us-vt-50003", False)]
    assert res[2][2] == 9

    strict = catalog.build(RELEASE, out, str(tmp / "cat_strict"), require_opt_in=True)
    assert strict["published"] == []
    assert {w["package"]: w["reasons"] for w in strict["withheld"]}["ca-pe-1102"] == ["not_opted_in"]


def test_published_packages(builds):
    """With every source open, every Package is a Collection with an Item per non-empty
    layer, its files hard-linked, checksums right, every relative link resolving."""
    tmp, _, out_open = builds
    cat = str(tmp / "cat_open")
    r = catalog.build(RELEASE, out_open, cat)
    assert [p["package"] for p in r["published"]] == ["ca-pe-1102", "ca-pe-1103", "us-vt-50001", "us-vt-50003"]
    pub = os.path.join(cat, "public")

    coll_path = os.path.join(pub, "us", "us-vt", "us-vt-50001", "collection.json")
    with open(coll_path) as f:
        coll = json.load(f)
    assert coll["id"] == "us-vt-50001" and coll["license"] == "other"
    assert coll["providers"][-1]["roles"] == ["processor", "host"] and coll["providers"][-1]["url"]
    assert coll["ng911:nguid_domain"] == "us-vt-50001.unclaimed.invalid" and coll["ng911:records"] == 9
    items = [lk["href"] for lk in coll["links"] if lk["rel"] == "item"]
    names = [h.split("/")[2] for h in items]
    assert names[:4] == ["us-vt-50001-site-structure-address-point.json", "us-vt-50001-road-centerline.json",
                         "us-vt-50001-a2-polygon.json", "us-vt-50001-a3-polygon.json"]
    assert "us-vt-50001-provisioning-polygon.json" in names  # layers.py's layers are Items too
    with open(os.path.join(pub, "us", "us-vt", "us-vt-50001", "us-vt-50001-road-centerline",
                           "us-vt-50001-road-centerline.json")) as f:
        rcl = json.load(f)
    assert set(rcl["assets"]) == {"road_centerline", "road_gers_crosswalk"}

    # The PMTiles derivative (manby) and its MapLibre style, as Portolan registers them
    pm = next(lk for lk in coll["links"] if lk["rel"] == "pmtiles")
    assert pm["href"] == "./us-vt-50001.pmtiles" and pm["pmtiles:layers"] == [
        "a2_polygon", "a3_polygon", "road_centerline", "site_structure_address_point"]
    assert coll["assets"]["pmtiles"]["roles"] == ["visual"]
    assert coll["assets"]["style-default"]["roles"] == ["style", "default"]
    with open(os.path.join(os.path.dirname(coll_path), "styles", "default.json")) as f:
        style = json.load(f)
    assert style["sources"]["data"]["url"] == "pmtiles://../us-vt-50001.pmtiles"
    assert {lyr["source-layer"] for lyr in style["layers"][1:]} == set(pm["pmtiles:layers"])
    assert rcl["properties"]["table:row_count"] == 3
    cols = {c["name"]: c for c in rcl["properties"]["table:columns"]}
    assert cols["gers_id"]["description"] and cols["geom"]["type"].startswith("geometry")

    # PEI has no centerline source yet: no RoadCenterline Item, nothing empty published
    with open(os.path.join(pub, "ca", "ca-pe", "ca-pe-1102", "collection.json")) as f:
        pe = json.load(f)
    assert not any("road-centerline" in lk["href"] for lk in pe["links"] if lk["rel"] == "item")

    # Every relative link resolves, and every asset's size and checksum match its bytes
    for path in glob.glob(os.path.join(pub, "**", "*.json"), recursive=True):
        with open(path) as f:
            obj = json.load(f)
        if "links" not in obj:
            continue  # manifest.json, domains.json
        for lk in obj["links"]:
            if not lk["href"].startswith("http"):
                assert os.path.exists(os.path.join(os.path.dirname(path), lk["href"])), (path, lk)
        for a in obj.get("assets", {}).values():
            f = os.path.join(os.path.dirname(path), a["href"])
            assert a["file:size"] == os.path.getsize(f) and a["file:checksum"] == catalog.checksum(f)

    # Layer files are GeoParquet 2.0 and the public copies are the build's files
    ssap = os.path.join(pub, "us", "us-vt", "us-vt-50001", "us-vt-50001-site-structure-address-point",
                        "site_structure_address_point.parquet")
    assert json.loads(pq.read_metadata(ssap).metadata[b"geo"])["version"] == "2.0.0"
    src = os.path.join(out_open, f"release={RELEASE}", "us-vt", "50001", "site_structure_address_point.parquet")
    assert catalog.checksum(ssap) == catalog.checksum(src)

    # report.json sits beside the public tree, never in it
    assert os.path.exists(os.path.join(cat, "report.json")) and not os.path.exists(os.path.join(pub, "report.json"))


@pytest.mark.skipif(shutil.which("portolan") is None, reason="portolan-cli not installed (uv tool install portolan-cli)")
def test_portolan_check(builds):
    tmp, _, out_open = builds
    cat = str(tmp / "cat_check")
    catalog.build(RELEASE, out_open, cat)
    res = subprocess.run(["portolan", "--format", "json", "check"], check=False, cwd=os.path.join(cat, "public"),
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
