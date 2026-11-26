# Examples

`catalog/` is the Portolan catalog `catalog.py` writes, built from the test fixtures by
`python scripts/sample_catalog.py`. The points, roads and outlines are synthetic test data, not agency data.
The sample lifts the opt-in gate so Prince Edward Island's open-licensed Packages show what a published Package
looks like (with the `.unclaimed.invalid` placeholder domain); a real build keeps the gate (ADR 0003, 0011).
Vermont is withheld for its unknown licence, and `catalog/report.json` says so. Open
`catalog/public/catalog.json` in STAC Browser, or `portolan check` it from `catalog/public/`.
