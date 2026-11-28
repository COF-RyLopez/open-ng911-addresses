"""story/extract.py on a fixture build: it must keep reading the current manifest (a manifest rename broke it once
and only showed up in the Story map data workflow)."""
import json
import os
import subprocess
import sys

from pe_fixtures import fixture_loaders

from open_ng911 import build

RELEASE = "2026-11-18.0"
EXTRACT = os.path.join(os.path.dirname(__file__), "..", "story", "extract.py")


def test_story_extract_reads_current_manifest(tmp_path, conn):
    out, dest = str(tmp_path / "out"), str(tmp_path / "story")
    build.run("ca-pe", out, loaders=fixture_loaders(tmp_path), release=RELEASE, c=conn)
    subprocess.run([sys.executable, EXTRACT, "--out", out, "--job", "ca-pe", "--dest", dest], check=True)
    with open(os.path.join(dest, "ca-pe.json"), encoding="utf-8") as f:
        d = json.load(f)
    assert d["job"]["rows"] == 5 and d["job"]["records"] == 4
    p = {x["package"]: x for x in d["packages"]}["ca-pe-1102"]
    assert p["rows"] == 3 and p["field_fill"]["nguid"] == 1.0
    assert p["roads"] == {"rows": 0, "with_gers_id": 0, "road_source": None, "field_fill": {}}
    assert len(d["points"]["dx"]) == 5  # PEI is open-licensed, so its points are embedded
