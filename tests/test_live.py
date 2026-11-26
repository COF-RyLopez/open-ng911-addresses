"""Checks against the real outside sources, run only in CI's build job (`pytest -m live`): they need the network."""
import os

import pytest

from open_ng911 import db, registry
from open_ng911.sources import centerlines

pytestmark = pytest.mark.live


def test_tiger_addrfeat_reads(tmp_path):
    """The TIGER fallback (which no enabled job reaches yet) still finds and reads a county: Grand Isle, VT."""
    c = db.connect(s3=False)
    centerlines.create_tables(c)
    c.execute("CREATE TABLE road_fallback AS SELECT '50013' AS geoid")
    centerlines.load_tiger(c, registry.job("us-vt"), None, str(tmp_path))
    n, ranged, classes = c.execute("""SELECT count(*), count(*) FILTER (from_l IS NOT NULL OR from_r IS NOT NULL),
                                             list(DISTINCT road_class) FROM road_seg""").fetchall()[0]
    assert n > 100 and ranged > 0.5 * n and "Local" in classes
    (meta,) = c.execute("SELECT license_status, source_date FROM road_source_meta").fetchall()
    assert meta[0] == "open" and meta[1].startswith("TIGER/Line ")
    assert os.listdir(tmp_path)
