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
    for name in ("CC0-1.0", "CC-BY-4.0", "Public Domain", "OGL-CA", "PDDL-1.0", "ODC-By-1.0"):
        assert catalog.open_license(name), name
    for name in ("ODbL-1.0", "CC-BY-SA-4.0", "unstated", "", None, "proprietary"):
        assert not catalog.open_license(name), name


def test_default_withholds_every_pilot(builds):
    """As registered today: Vermont's licence is unknown and no authority has opted in (ADR 0003), so only the
    scorecard is public and no Package file is in the public tree."""
    tmp, out, _ = builds
    cat = str(tmp / "cat_default")
    r = catalog.build(RELEASE, out, cat)
    assert r["published"] == []
    reasons = {w["package"]: w["reasons"] for w in r["withheld"]}
    assert reasons["ca-pe-1102"] == ["not_opted_in"]
    assert reasons["us-vt-50001"] == ["source_license:us-vt-e911-esite=unknown",
                                      "source_license:us-vt-e911-rds=unknown", "not_opted_in"]
    pub = os.path.join(cat, "public")
    assert sorted(os.listdir(pub)) == ["AGENTS.md", "README.md", "catalog.json", "scorecard"]
    files = [os.path.basename(p) for p in glob.glob(os.path.join(pub, "**", "*.parquet"), recursive=True)]
    assert files == ["scorecard.parquet"]
    res = duckdb.connect().execute(f"SELECT package, published, withheld_reasons, records FROM "
                                   f"read_parquet('{pub}/scorecard/scorecard.parquet') ORDER BY package").fetchall()
    assert [(p, pub_) for p, pub_, _, _ in res] == [("ca-pe-1102", False), ("ca-pe-1103", False),
                                                    ("us-vt-50001", False), ("us-vt-50003", False)]
    assert res[2][3] == 9


def test_published_packages(builds):
    """With open sources and the opt-in gate lifted, every Package is a Collection with an Item per non-empty
    layer, its files hard-linked, checksums right, every relative link resolving."""
    tmp, _, out_open = builds
    cat = str(tmp / "cat_open")
    r = catalog.build(RELEASE, out_open, cat, unclaimed=True)
    assert [p["package"] for p in r["published"]] == ["ca-pe-1102", "ca-pe-1103", "us-vt-50001", "us-vt-50003"]
    pub = os.path.join(cat, "public")

    coll_path = os.path.join(pub, "us", "us-vt", "us-vt-50001", "collection.json")
    with open(coll_path) as f:
        coll = json.load(f)
    assert coll["id"] == "us-vt-50001" and coll["license"] == "other"
    assert coll["providers"][-1]["roles"] == ["processor", "host"] and coll["providers"][-1]["url"]
    assert coll["ng911:nguid_domain"] == "us-vt-50001.unclaimed.invalid" and coll["ng911:records"] == 9
    items = [lk["href"] for lk in coll["links"] if lk["rel"] == "item"]
    assert [h.split("/")[2] for h in items] == [
        "us-vt-50001-site-structure-address-point.json", "us-vt-50001-road-centerline.json",
        "us-vt-50001-a2-polygon.json", "us-vt-50001-a3-polygon.json"]
    with open(os.path.join(pub, "us", "us-vt", "us-vt-50001", "us-vt-50001-road-centerline",
                           "us-vt-50001-road-centerline.json")) as f:
        rcl = json.load(f)
    assert set(rcl["assets"]) == {"road_centerline", "road_gers_crosswalk"}
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


@pytest.mark.skipif(shutil.which("portolan") is None, reason="portolan-cli not installed (pip install .[publish])")
def test_portolan_check(builds):
    tmp, _, out_open = builds
    cat = str(tmp / "cat_check")
    catalog.build(RELEASE, out_open, cat, unclaimed=True)
    res = subprocess.run(["portolan", "--format", "json", "check"], check=False, cwd=os.path.join(cat, "public"),
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
