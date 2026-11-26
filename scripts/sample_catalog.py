"""
Write examples/catalog/: the Portolan catalog built from the pilot test fixtures (synthetic points, not agency
data), so the layout can be read without running a build.

    python scripts/sample_catalog.py

Vermont and Prince Edward Island are built on tests/vt_fixtures.py and tests/pe_fixtures.py with the registry as
it stands. The opt-in gate is lifted for the sample only (catalog.build(unclaimed=True)), so PEI's open-licensed
Packages show what a published Package looks like; Vermont stays withheld for its unknown licence. A real build
keeps the gate (ADR 0003).
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from pe_fixtures import fixture_loaders as pe_loaders
from vt_fixtures import fixture_loaders as vt_loaders

from open_ng911 import build, catalog, db

RELEASE = "2026-11-18.0"
OUT = os.path.join(ROOT, "examples", "catalog")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "output")
        for job, loaders in (("us-vt", vt_loaders), ("ca-pe", pe_loaders)):
            work = os.path.join(tmp, job)
            os.makedirs(work)
            build.run(job, out, loaders=loaders(Path(work)), release=RELEASE, c=db.connect(s3=False))
        if os.path.exists(OUT):
            shutil.rmtree(OUT)
        r = catalog.build(RELEASE, out, OUT, unclaimed=True)
    print(f"{len(r['published'])} published, {len(r['withheld'])} withheld -> {os.path.relpath(OUT, ROOT)}")


if __name__ == "__main__":
    main()
