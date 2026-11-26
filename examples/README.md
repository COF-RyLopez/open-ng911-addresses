# Examples

`catalog/` is the Portolan catalog `catalog.py` writes, built from the test fixtures by
`python scripts/sample_catalog.py`. The points, roads and outlines are synthetic test data, not agency data.
Prince Edward Island's open-licensed Packages are published, marked unclaimed (no authority has opted in, so
they carry the `.unclaimed.invalid` placeholder domain); Vermont is withheld for its unknown licence, and
`catalog/report.json` says so (ADR 0003 as amended, ADR 0011). Open `catalog/public/catalog.json` in STAC
Browser, or `portolan check` it from `catalog/public/`.
