"""The Vermont job end to end on fixtures: matching, statuses, UIDs, NGUIDs, packages and the ledger."""
import json
import os

import duckdb
from vt_fixtures import OVERTURE, fixture_loaders

from open_ng911 import build, ids

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
    assert s["agency_points_excluded"] == {"PUBLIC TELEPHONE": 1}
    assert s["records"] == 5  # the public phone and the point outside every Package are dropped
    assert s["gap_fill_candidates"] == 2  # o3 (lost to o4 on street key) and o5; o7 is outside

    addison = rows(out, "50001")
    assert addison["1001"]["gers_id"] == "o1" and addison["1001"]["status"] == "record"
    assert addison["1002"]["gers_id"] == "o2" and addison["1002"]["street_key_match"]
    assert addison["1003"]["gers_id"] == "o4", "a same-street pair beats a nearer pair on another street"
    assert addison["1004"]["gers_id"] is None
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
    assert m["records"] == 4 and m["records_with_gers_id"] == 3
    assert m["field_fill"]["nguid"] == 1.0
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
