"""The Vermont job end to end on fixtures: matching, statuses, UIDs, NGUIDs, packages and the ledger."""
import dataclasses
import json
import os

import duckdb
from vt_fixtures import FIXTURES, OVERTURE, fixture_loaders

from open_ng911 import build, fieldmap, ids, nena, registry, street, validate
from open_ng911.sources import openaddresses

RELEASE = "2026-11-18.0"


def rows(out, geoid):
    path = os.path.join(out, f"release={RELEASE}", "us-vt", geoid, "site_structure_address_point.parquet")
    c = duckdb.connect()
    res = c.execute(f"SELECT * FROM read_parquet('{path}')")
    cols = [d[0] for d in res.description]
    return {r["source_id"]: r for r in (dict(zip(cols, v)) for v in res.fetchall())}


def test_vermont_job(tmp_path, conn):
    out = str(tmp_path / "out")
    s = build.run("us-vt", out, loaders=fixture_loaders(tmp_path), release=RELEASE, c=conn)
    assert s["gate_failures"] == []
    assert s["packages"] == 2
    assert s["agency_points_excluded"] == {}
    # kept: the public phone and the un-numbered call box (addressed sites), both points sharing ID 1008;
    # and the point 40 m outside Addison's edge (nearest Package);
    # dropped: the point with no street, the exact duplicate of 1003, the point far outside every Package
    assert s["records"] == 10
    assert s["agency_points_dropped"] == {"no_street": 1, "duplicate": 1, "outside_packages": 1}
    assert s["agency_points_id_shared"] == 2
    assert s["gap_fill_candidates"] == 2  # o3 (lost to o4 on street key) and o5; o7 is outside

    addison = rows(out, "50001")
    assert addison["1001"]["gers_id"] == "o1" and addison["1001"]["status"] == "record"
    assert addison["1002"]["gers_id"] == "o2" and addison["1002"]["street_key_match"]
    assert addison["1003"]["gers_id"] == "o4", "a same-street pair beats a nearer pair on another street"
    assert addison["1004"]["gers_id"] is None
    assert addison["1005"]["source_site_type"] == "PUBLIC TELEPHONE" and addison["1005"]["status"] == "record"
    assert addison["1009"]["status"] == "record"
    box = addison["1006"]
    assert box["add_number"] is None and box["st_pretyp"] == "Interstate" and box["st_name"] == "89"
    assert addison["1004"]["add_number"] == 30 and addison["1004"]["addnum_suf"] == "B"
    assert addison["r5"]["status"] == "gap_fill_candidate" and addison["r5"]["link_method"] == "minted"
    assert addison["r5"]["source_license"] == "Public Domain"

    # Address UID from the agency's own ID; NGUID from the UID, under the placeholder domain (not opted in)
    uid = ids.agency_uid("us-vt-e911-esite", "1001")
    assert addison["1001"]["uid"] == uid
    assert addison["1001"]["nguid"] == f"urn:emergency:uid:gis:SSAP:{uid}:us-vt-50001.unclaimed.invalid"
    assert addison["1001"]["discrpagid"] == "us-vt-50001.unclaimed.invalid"
    assert "o1" not in addison["1001"]["nguid"], "an NGUID never carries a GERS ID (ADR 0002)"

    # NENA registry words
    r = addison["1002"]
    assert (r["st_predir"], r["st_name"], r["st_postyp"], r["a1"], r["a2"]) == ("North", "EIGHTH", "Street", "VT", "Addison County")
    route = rows(out, "50003")["2001"]
    assert (route["st_pretyp"], route["st_name"], route["gers_id"]) == ("State Route", "9", "o6")

    with open(os.path.join(out, f"release={RELEASE}", "us-vt", "50001", "manifest.json")) as f:
        m = json.load(f)
    assert m["opted_in"] is False and m["recipient"] == "Vermont Enhanced 9-1-1 Board"
    assert m["records"] == 9 and m["records_with_gers_id"] == 3
    assert m["manifest_version"] == 2 and "field_fill" not in m
    assert m["openaddresses_commit"] == openaddresses.pin()["commit"], "the OpenAddresses commit the sources came from"
    assert m["nena_coverage"]["SiteStructureAddressPoint"]["fields"]["nguid"]["fill"] == 1.0
    assert m["sources"][0]["license_status"] == "unknown"


def test_ledger_carries_uids_across_releases(tmp_path, conn):
    out1 = str(tmp_path / "r1")
    build.run("us-vt", out1, loaders=fixture_loaders(tmp_path), release=RELEASE, c=conn)
    ledger = os.path.join(out1, f"release={RELEASE}", "us-vt", "address_lineage.parquet")
    first = rows(out1, "50001")["r5"]["uid"]

    # Next release: Overture re-issues o5 as o5b (an attribute changed); same upstream record r5
    nxt = [r if r[0] != "o5" else ("o5b", "40", "BIRCH LANE", -73.11, 44.11, "r5") for r in OVERTURE]
    out2 = str(tmp_path / "r2")
    s = build.run("us-vt", out2, loaders=fixture_loaders(tmp_path, nxt), release="2026-12-16.0",
                  ledger_path=ledger, c=duckdb_conn())
    assert s["overture_link_methods"].get("source_record") == 1
    path = os.path.join(out2, "release=2026-12-16.0", "us-vt", "50001", "site_structure_address_point.parquet")
    uid, gers = duckdb.connect().execute(f"SELECT uid, gers_id FROM read_parquet('{path}') WHERE source_id = 'r5'").fetchall()[0]
    assert (uid, gers) == (first, "o5b"), "the UID, and so the NGUID, survives the GERS ID changing"
    hist = duckdb.connect().execute(
        f"SELECT gers_id, last_release FROM read_parquet('{os.path.join(out2, 'release=2026-12-16.0', 'us-vt', 'address_lineage.parquet')}') "
        f"WHERE address_uid = '{first}' ORDER BY gers_id").fetchall()
    assert hist == [("o5", RELEASE), ("o5b", "2026-12-16.0")]


def duckdb_conn():
    from open_ng911 import db
    return db.connect(s3=False)


def test_exclude_site_types_drops_and_counts(conn, vt):
    _, jur = vt
    street.install(conn)
    nena.install(conn)
    fieldmap.install(conn)
    source = dataclasses.replace(jur.sources[0], exclude_site_types=["PUBLIC TELEPHONE"])
    conform = {"number": "HOUSE_NUMBER", "street": ["PD", "PT", "SN", "ST", "SD"], "addrtype": "SITETYPE"}
    openaddresses.create_agency_addr(conn, source, os.path.join(FIXTURES, "vt_agency_points.ndjson"), conform, True)
    assert conn.execute("SELECT site_type, n FROM agency_excluded").fetchall() == [("PUBLIC TELEPHONE", 1)]
    assert conn.execute("SELECT count(*) FROM agency_addr WHERE source_id = '1005'").fetchall()[0][0] == 0


def test_address_sources_combined(conn, vt):
    """Several address Sources in one job: all their points, a site both publish kept once (the earlier Source's)
    and the other counted."""
    _, jur = vt
    street.install(conn)
    nena.install(conn)
    fieldmap.install(conn)
    conform = {"number": "HOUSE_NUMBER", "street": ["PD", "PT", "SN", "ST", "SD"], "addrtype": "SITETYPE"}
    path = os.path.join(FIXTURES, "vt_agency_points.ndjson")
    county = jur.sources[0]
    city = dataclasses.replace(county, key="us-vt-city-points")
    openaddresses.create_agency_addr(conn, county, path, conform, True)
    n = conn.execute("SELECT count(*) FROM agency_addr").fetchall()[0][0]
    openaddresses.stash(conn, 0)
    openaddresses.create_agency_addr(conn, city, path, conform, True)
    conn.execute("DELETE FROM agency_addr WHERE source_id = '1001'")  # one point only the county publishes
    openaddresses.stash(conn, 1)
    openaddresses.combine(conn, 2)
    assert conn.execute("SELECT source_key, count(*) FROM agency_addr GROUP BY 1").fetchall() == [(county.key, n)]
    dup = conn.execute("SELECT sum(n) FROM agency_dropped WHERE reason = 'duplicate_across_sources' "
                       "AND source_key = 'us-vt-city-points'").fetchall()[0][0]
    assert dup == n - 1
    assert conn.execute("SELECT count(*) FROM agency_excluded").fetchall()[0][0] >= 0


def read(path, where="true"):
    res = duckdb.connect().execute(f"SELECT * FROM read_parquet('{path}', hive_partitioning = false) WHERE {where}")
    cols = [d[0] for d in res.description]
    return [dict(zip(cols, v)) for v in res.fetchall()]


def test_road_centerlines(tmp_path, conn):
    out = str(tmp_path / "out")
    s = build.run("us-vt", out, loaders=fixture_loaders(tmp_path), release=RELEASE, c=conn)
    assert s["gate_failures"] == []
    assert s["road_sources"] == {"government": 3, "tiger": 2}
    assert s["road_segments"] == 5 and s["road_segments_with_gers_id"] == 3
    # every segment left out is counted: the "not a road" class and the segment far outside every Package
    assert s["features_dropped"]["RoadCenterLine"] == {"excluded_by_registry": 1, "outside_packages": 1}
    root = os.path.join(out, f"release={RELEASE}", "us-vt")

    # Addison: the E911 Board's own roads; the "not a road" segment (AOTCLASS 98) is left out
    addison = {r["source_id"]: r for r in read(os.path.join(root, "50001", "road_centerline.parquet"))}
    assert set(addison) == {"5001", "5002", "5004"}
    main = addison["5001"]
    assert main["road_source"] == "government" and main["source_license"] == "unknown"
    assert main["uid"] == ids.agency_uid("us-vt-e911-rds", "5001")
    assert main["rcl_nguid"] == f"urn:emergency:uid:gis:RCL:{main['uid']}:us-vt-50001.unclaimed.invalid"
    assert (main["fromaddr_l"], main["toaddr_l"], main["parity_l"], main["parity_r"]) == (1, 99, "O", "E")
    assert (main["st_name"], main["st_postyp"], main["roadclass"], main["oneway"], main["speedlimit"]) == (
        "MAIN", "Street", "Secondary", "B", 25)
    eighth = addison["5002"]
    # no range on a side: 0 (NENA's convention), its parity still 'Z', and counted
    assert (eighth["fromaddr_l"], eighth["toaddr_l"], eighth["fromaddr_r"]) == (0, 0, 3)
    assert s["road_segments_without_range"] == {"left": 2, "right": 2}
    assert (eighth["st_predir"], eighth["oneway"], eighth["parity_l"], eighth["speedlimit"]) == ("North", "FT", "Z", None)
    ramp = addison["5004"]
    assert (ramp["st_pretyp"], ramp["st_name"], ramp["roadclass"], ramp["parity_l"]) == ("State Route", "125", "Ramp", "B")

    # GERS IDs: MAIN ST is cut in two on Overture's side, the primary one runs along most of it; the crossing
    # segment and the railway on top of it don't link
    assert main["gers_id"] == "s1" and eighth["gers_id"] == "s4" and ramp["gers_id"] is None
    cw = read(os.path.join(root, "50001", "road_gers_crosswalk.parquet"))
    assert {(r["uid"], r["gers_id"], r["is_primary"]) for r in cw} == {
        (main["uid"], "s1", True), (main["uid"], "s2", False), (eighth["uid"], "s4", True)}
    assert all(r["overture_release"] == RELEASE for r in cw)

    # Bennington has no government centerlines: TIGER ADDRFEAT, a road feature only (the rail spur is dropped)
    benn = {r["source_id"]: r for r in read(os.path.join(root, "50003", "road_centerline.parquet"))}
    assert set(benn) == {"618001:A1:A2", "618002:A3"}
    vt9 = benn["618001:A1:A2"]
    assert (vt9["road_source"], vt9["source_license"], vt9["st_pretyp"], vt9["st_name"], vt9["gers_id"]) == (
        "tiger", "open", "State Route", "9", "s7")

    # nothing of Overture's but its IDs: no Overture geometry or names in either file
    assert not {"subtype", "names", "class"} & set(main) and not {"geom", "geometry"} & set(cw[0])

    with open(os.path.join(root, "50001", "manifest.json")) as f:
        m = json.load(f)
    assert m["nena"]["layers"][:4] == ["SiteStructureAddressPoint", "A2Polygon", "A3Polygon", "RoadCenterline"]
    rc = m["road_centerline"]
    assert rc["features"] == 3 and rc["road_source"] == "government" and rc["gers_coverage"] == round(2 / 3, 4)
    (src,) = rc["sources"]
    assert (src["source_key"], src["license_status"], src["source_date"]) == ("us-vt-e911-rds", "unknown", "2026-02-19")
    with open(os.path.join(root, "50003", "manifest.json")) as f:
        rc = json.load(f)["road_centerline"]
    assert rc["road_source"] == "tiger"
    assert [(x["source_key"], x["license_status"], x["source_date"]) for x in rc["sources"]] == [
        ("tiger-addrfeat-2025", "open", "TIGER/Line 2025")]
    assert s["by_package"]["us-vt-50003"]["road_source"] == "tiger"


def test_government_roads_only_where_their_source_covers(tmp_path, conn, monkeypatch):
    from open_ng911 import registry
    real = registry.jurisdiction

    def narrowed(j, d=registry.REGISTRY_DIR):
        jur = real(j, d)
        next(s for s in jur.sources if s.layer == "centerlines").covers = ["50003"]
        return jur

    monkeypatch.setattr(registry, "jurisdiction", narrowed)
    loaders = fixture_loaders(tmp_path)
    loaders["tiger_roads"] = lambda c, job, jur, work: None  # both Packages would fall back; none read here
    s = build.run("us-vt", str(tmp_path / "out"), loaders=loaders, release=RELEASE, c=conn)
    assert s["road_sources"] == {}, "Addison's E911 roads are dropped where the source doesn't cover it"
    assert s["features_dropped"]["RoadCenterLine"]["outside_source_coverage"] == 3


def test_upstream_counts(tmp_path, conn):
    """Where the government roads and Overture / TIGER disagree: counts only, nothing of Overture's written."""
    out = str(tmp_path / "out")
    s = build.run("us-vt", out, loaders=fixture_loaders(tmp_path), release=RELEASE, c=conn)
    root = os.path.join(out, f"release={RELEASE}", "us-vt")
    with open(os.path.join(root, "50001", "manifest.json")) as f:
        up = json.load(f)["upstream"]
    # MAIN ST agrees with Overture's "Main Street"; N EIGHTH ST is "Seminary Street" and a trunk road there;
    # the VT 125 ramp has no Overture segment
    o = up["overture"]
    assert (o["segments"], o["not_in_overture"], o["name_agrees"], o["name_differs"]) == (3, 1, 1, 1)
    assert (o["class_agrees"], o["class_differs"]) == (1, 1)
    # TIGER has MAIN ST and a road the E911 layer lacks, and lacks N EIGHTH ST and the ramp
    n = up["national"]
    assert n["measured"] and n["date"] == "TIGER/Line 2025"
    assert (n["government_segments"], n["not_in_national"], n["national_segments"],
            n["national_not_in_government"]) == (3, 2, 2, 1)
    assert n["not_in_national_km"] > 0 and n["national_not_in_government_km"] > 0
    assert up["upstream_eligible"] is False, "the E911 roads' licence is unknown"
    with open(os.path.join(root, "50003", "manifest.json")) as f:
        benn = json.load(f)["upstream"]
    assert benn["national"] == {"measured": False, "why": "no government roads in this Package"}
    assert benn["overture"]["name_agrees"] == 1
    assert s["upstream"]["overture"]["segments"] == 5 and s["upstream"]["national"]["not_in_national"] == 2
    # counts only: no names anywhere in the section
    assert "Seminary" not in json.dumps(up)


def test_odbl_replacement_inventory(tmp_path, conn):
    """Which government sources could replace Overture's ODbL themes, per Package."""
    out = str(tmp_path / "out")
    s = build.run("us-vt", out, loaders=fixture_loaders(tmp_path), release=RELEASE, c=conn)
    root = os.path.join(out, f"release={RELEASE}", "us-vt")
    with open(os.path.join(root, "50001", "manifest.json")) as f:
        addison = json.load(f)["odbl_replacement"]
    with open(os.path.join(root, "50003", "manifest.json")) as f:
        benn = json.load(f)["odbl_replacement"]
    # Addison reads the E911 roads, whose licence isn't open yet; Bennington falls back to TIGER (public domain)
    assert addison["transportation"]["status"] == "government_unclear"
    assert addison["transportation"]["read"][0]["license_status"] != "open"
    assert benn["transportation"]["status"] == "government_open"
    assert addison["divisions"]["status"] == "government_open"
    # nothing read for water; the national layer is a candidate
    assert addison["base_water"]["status"] == "candidate" and "USGS" in addison["base_water"]["national"]
    assert s["odbl_replacement"]["divisions"] == {"government_open": len(s["by_package"])}


def test_gate_covers_every_built_layer(tmp_path, conn):
    """Every layer is gated on the Required fields the build always fills; the agency's own fields and the ones
    only the data has are reported instead (ADR 0004)."""
    out = str(tmp_path / "out")
    s = build.run("us-vt", out, loaders=fixture_loaders(tmp_path), release=RELEASE, c=conn)
    assert s["gate_failures"] == []
    assert set(s["nena_required_gaps"]["PsapPolygon"]) == {"agency_id", "serviceuri", "avcard_uri"}
    assert s["nena_required_gaps"]["PsapPolygon"]["agency_id"] == {"fill": 0.0, "owner": "agency"}
    assert nena.gated("PsapPolygon") == ["discrpagid", "dateupdate", "nguid", "serviceurn"]
    assert {"fromaddr_l", "st_name"} <= set(nena.required("RoadCenterLine"))
    assert "fromaddr_l" in nena.gated("RoadCenterLine") and "st_name" not in nena.gated("RoadCenterLine")

    # a service layer with an empty gated field and a repeated NGUID now fails the job
    conn.execute("UPDATE fire_polygon SET dateupdate = NULL")
    conn.execute("INSERT INTO fire_polygon SELECT * FROM fire_polygon")
    fails = build.gate(conn, registry.job("us-vt"), build.coverage_spec(conn, registry.job("us-vt"),
                                                                         registry.jurisdiction(registry.job("us-vt"))))
    assert "FirePolygon.dateupdate: 4 rows empty" in fails and "FirePolygon.nguid: 2 duplicates" in fails


def test_address_ranges_against_records(tmp_path, conn):
    """Records against the road range on their side of their street; a side with no range gets one derived from
    its Records, in its own columns (the agency's FromAddr/ToAddr stay as published)."""
    out = str(tmp_path / "out")
    s = build.run("us-vt", out, loaders=fixture_loaders(tmp_path), release=RELEASE, c=conn)
    r = s["address_ranges"]
    # 12 MAIN ST on the even side inside 2-98; 1 MAIN ST on the even side, which the odd side's 1-99 holds;
    # 14 N EIGHTH ST on the left, which has no range; 5 VT ROUTE 9, which the road names Vermont Route 9 (one
    # street: both are NENA's State Route 9), on the even side, which the odd side's 1-99 holds; the Records on streets with no segment nearby
    assert (r["in_range"], r["wrong_side"], r["no_range"], r["wrong_parity"]) == (1, 2, 1, 0)
    assert r["no_matching_road"] == 5 and r["segment_sides_with_derived_range"] == {"left": 1, "right": 0}
    root = os.path.join(out, f"release={RELEASE}", "us-vt", "50001")
    eighth = next(x for x in read(os.path.join(root, "road_centerline.parquet")) if x["source_id"] == "5002")
    assert (eighth["fromaddr_l"], eighth["toaddr_l"], eighth["parity_l"]) == (0, 0, "Z"), "the agency's, unchanged"
    assert (eighth["derived_fromaddr_l"], eighth["derived_toaddr_l"], eighth["derived_parity_l"]) == (14, 14, "E")
    assert eighth["derived_fromaddr_r"] is None, "the right side has the agency's own range"
    checks = read(os.path.join(root, "address_range_check.parquet"))
    assert {x["result"] for x in checks} >= {"in_range", "wrong_side", "no_range"}
    with open(os.path.join(root, "manifest.json")) as f:
        assert json.load(f)["address_ranges"]["wrong_side"] == 1, "Bennington's Route 9 is in another Package"


def test_validation_scored_per_package(tmp_path, conn):
    """Every Package is scored on the NSGIC checks that need no agency data (validate.py): the gate checks alone
    (`before`) and every check; a check fails the Package only where one of its features fails it."""
    out = str(tmp_path / "out")
    s = build.run("us-vt", out, loaders=fixture_loaders(tmp_path), release=RELEASE, c=conn)
    v = s["validation"]
    assert set(v["by_package"]) == set(s["by_package"])
    job = registry.job("us-vt")
    scores = validate.run(conn, job, build.coverage_spec(conn, job, registry.jurisdiction(job)))
    for geoid, p in scores.items():
        gate = {k: c for k, c in p["checks"].items() if k.rsplit(".", 1)[1] in validate.GATE}
        assert gate and all(c["pass"] for c in gate.values())  # the job passed its gate
        assert p["before"] == f"{len(gate)}/{len(gate)}" and p["score"] == f"{p['passed']}/{p['applicable']}"
        assert {"SiteStructureAddressPoint.domains", "RoadCenterLine.range_parity"} <= set(p["checks"])
        with open(os.path.join(out, f"release={RELEASE}", "us-vt", geoid, "manifest.json")) as f:
            assert json.load(f)["validation"]["score"] == p["score"]

    # a parity that disagrees with its numbers ('Z', no range, on a ranged side) fails range_parity in that
    # segment's Package
    geoid, uid = conn.execute("SELECT geoid, uid FROM rcl WHERE fromaddr_l > 0 AND parity_l <> 'Z' "
                              "ORDER BY uid LIMIT 1").fetchall()[0]
    conn.execute(f"UPDATE rcl SET parity_l = 'Z' WHERE uid = '{uid}'")
    after = validate.run(conn, job, build.coverage_spec(conn, job, registry.jurisdiction(job)))
    assert not after[geoid]["checks"]["RoadCenterLine.range_parity"]["pass"]
    assert after[geoid]["checks"]["RoadCenterLine.range_parity"]["failed"] == \
        scores[geoid]["checks"]["RoadCenterLine.range_parity"]["failed"] + 1


def test_scenarios_read_failures_against_source_fields(tmp_path, conn):
    """scenarios.py reads the duplicate and road-range failures back against the Source's own fields (the features
    the build fetched, joined on id_field), and the duplicate key holds every CLDXF subaddress element."""
    import shutil

    out = str(tmp_path / "out")
    work = os.path.join(out, "_work", "us-vt")
    os.makedirs(work)
    shutil.copy(os.path.join(FIXTURES, "vt_agency_points.ndjson"), os.path.join(work, "us-vt-e911-esite.ndjson"))
    s = build.run("us-vt", out, loaders=fixture_loaders(tmp_path), release=RELEASE, c=conn)
    sc = s["scenarios"]
    assert "error" not in sc
    assert sc["source_fields_read"] == {"us-vt-e911-esite": "ESITEID"}
    assert {"structure", "site", "wing", "unitvalue"} <= set(sc["duplicates"]["key"])
    assert set(sc["rcl_agreement"]["results"]) <= set(build.ranges.RESULTS)
    assert sum(sc["rcl_agreement"]["results"].values()) == conn.execute(
        "SELECT count(*) FROM address_range_check").fetchall()[0][0]

    # two Records that differ only in their Building are two sites, not a duplicate
    conn.execute("INSERT INTO ssap BY NAME (SELECT * REPLACE ('dup' AS uid, 'dup' AS nguid, 'B' AS structure) "
                 "FROM ssap WHERE status = 'record' AND add_number IS NOT NULL ORDER BY uid LIMIT 1)")
    job = registry.job("us-vt")
    v = validate.run(conn, job, build.coverage_spec(conn, job, registry.jurisdiction(job)))
    before = {g: p["checks"]["SiteStructureAddressPoint.duplicate_address"]["failed"] for g, p in v.items()
              if "SiteStructureAddressPoint.duplicate_address" in p["checks"]}
    conn.execute("UPDATE ssap SET structure = NULL WHERE uid = 'dup'")
    v = validate.run(conn, job, build.coverage_spec(conn, job, registry.jurisdiction(job)))
    after = {g: p["checks"]["SiteStructureAddressPoint.duplicate_address"]["failed"] for g, p in v.items()
             if "SiteStructureAddressPoint.duplicate_address" in p["checks"]}
    assert sum(after.values()) >= sum(before.values()) + 2
