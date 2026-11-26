# open-ng911-addresses

Open-data NENA NG9-1-1 address datasets for the 911 authorities of the US and Canada, built mostly from each
area's own government sources and handed back NENA-ready to the agencies that opt in.

**Status: Phase 1 scaffold.** Four pilot states (Vermont, Maine, Utah, North Dakota) and Prince Edward Island run end to end in CI. The plan behind it, with its 25 settled
decisions, is the "NG911 Address Pipeline: US + Canada Infrastructure Plan"; the terms are in
[GLOSSARY.md](GLOSSARY.md) and the decisions in [docs/adr](docs/adr). The California prototype is
[ng911-pipeline](https://github.com/COF-RyLopez/ng911-pipeline).

## How a build works

One DuckDB job per state or province (`registry/jobs.toml`, 65 jobs), each writing one **Package** per county
or census division:

1. Resolve the Overture release (`$OVERTURE_RELEASE`, else the newest on STAC or S3).
2. Read the Package areas (Census TIGER counties; StatCan census divisions for Canada), their
   municipalities (TIGER towns or incorporated places; StatCan census subdivisions), the Source
   agency's own address points through the [OpenAddresses](https://github.com/openaddresses/openaddresses)
   source registry, and Overture's addresses.
3. Parse every street the same way and match agency Records to Overture one to one (same number, within
   15 m, a same-street pair ahead of a nearer one).
4. Give each address its **Address UID**: from the agency's own ID where it has one, else minted at first
   sight and carried across Overture releases by the lineage ledger when Overture re-issues the GERS ID.
5. Write the SiteStructureAddressPoint layer: every Record (with the GERS ID it matched, published alongside
   the UID) plus unmatched Overture addresses as Gap-fill candidates. NGUIDs are built from the Address UID,
   under the agency's own domain once it opts in and a `.invalid` placeholder until then. Each point gets
   its A3 from the municipality it falls in ('Unincorporated' outside them, ADR 0009).
6. Write the A2Polygon (the county itself) and A3Polygon (its municipalities, clipped to it) layers.
7. Write the RoadCenterline layer: the Source agency's own centerlines (through the OpenAddresses registry), else
   Census TIGER address-range roads for that Package, each segment carrying the GERS IDs of the Overture road
   segments that run along it. Overture's road geometry and names (ODbL) never go in (ADR 0010).
8. Count where the government roads and Overture / TIGER disagree, and which government sources could stand in
   for Overture's ODbL themes in each Package (the `upstream` and `odbl_replacement` manifest sections).
9. Write the other NENA layers a Source agency publishes on its own endpoint: PSAP, police, fire and EMS
   boundaries (cut to each Package), ProvisioningPolygon (the Package area where no Source covers it), distance
   and location markers. Every layer carries every NENA field, mapped from the Source's own fields where it
   publishes them (the registry's `nena` tables) and empty where it doesn't; nothing is invented.
10. Report NENA field coverage per layer (filled, partial, no source; before and after the Sources' own fields)
    in job.json and each manifest.
11. Gate: every NENA mandatory field filled and every NGUID unique, on every layer, or the job fails.

```
data/output/release=<overture release>/<job>/
    job.json                     summary: counts, link methods, gate result, per-package numbers, and every
                                 point or feature left out, by layer and reason (agency_points_dropped,
                                 features_dropped)
    address_lineage.parquet      the ledger: address_uid × gers_id, first/last release, link method
    <geoid>/site_structure_address_point.parquet   GeoParquet
    <geoid>/a2_polygon.parquet   A2Polygon, the county or census division
    <geoid>/a3_polygon.parquet   A3Polygon, its municipalities
    <geoid>/road_centerline.parquet                GeoParquet: NENA RCL fields + uid, gers_id, road_source
    <geoid>/road_gers_crosswalk.parquet            segment UID x GERS ID, overlap, primary flag
    <geoid>/psap_polygon.parquet, police_polygon.parquet, fire_polygon.parquet, ems_polygon.parquet,
            provisioning_polygon.parquet, distance_marker_point.parquet, location_marker_point.parquet
                                 the other NENA layers, only where they have features
    <geoid>/manifest.json        recipient, opt-in state, field fill, sources with license status and date,
                                 upstream counts, ODbL replacement inventory, NENA field coverage
    <geoid>/domains.json         the value domains used: NENA-STA-006.3, plus CLDXF-CA in a Canadian Package
```

Layer files are GeoParquet 2.0, rows in Hilbert order, so they can be published as they are.

## Publishing: the Portolan catalog

`python -m open_ng911.catalog` turns a release's Packages into a static STAC catalog that conforms to the
[Portolan](https://github.com/portolan-sdi/portolan-spec) spec, ready to push to Source Cooperative or any
S3-compatible bucket (ADR 0011):

```
data/catalog/
    report.json                  every Package: published, or withheld and why (not pushed)
    public/                      the tree to push
        catalog.json README.md AGENTS.md
        scorecard/               one GeoParquet row per Package, published or not: counts, coverage, licence,
                                 opt-in state, on the county / census division outline
        us/<job>/<package>/      a Collection per published Package: manifest.json, domains.json, a thumbnail,
                                 PMTiles of its layers with a MapLibre style (made with manby), and one Item
                                 per NENA layer with its GeoParquet
```

A Package's data goes public only when every source in it is openly licensed (no `unknown` or `share-alike`
source, no Gap-fill candidate whose Overture source licence isn't open) and its job passed the gate. A Package
whose 911 authority hasn't opted in is published as *unclaimed*, under its placeholder domain (ADR 0003 as
amended, ADR 0011). [examples/catalog](examples/catalog) is the catalog built from the test fixtures
(`python scripts/sample_catalog.py`). To check and upload one:

```sh
uv tool install portolan-cli                # its own env: it pins an older DuckDB
(cd data/catalog/public && portolan check)
```

## Run it

```sh
uv pip install -e ".[dev]"
pytest -q -m "not live"                     # offline, on fixtures
python -m open_ng911.build --job us-vt      # live: TIGERweb, Vermont's E911 service, Overture on S3
python -m open_ng911.build --job ca-pe      # live: StatCan boundaries, PEI civic addresses, Overture on S3
python -m open_ng911.catalog                # the Portolan catalog over everything under data/output
OVERTURE_RELEASE=2026-11-18.0 python -m open_ng911.build --job us-vt --ledger <previous address_lineage.parquet>
```

## Adding a state or province

1. Write `registry/<country>/<code>.toml`: its 911 authorities and Source agencies (see `registry/us/vt.toml`).
2. Set `enabled = true` for the job in `registry/jobs.toml`. CI builds every enabled job in a matrix.

## What's next (Phase 1)

- A4 (unincorporated communities) once there's an open source that isn't the statistical CDPs.
- More provinces: Nova Scotia (NSCAF, open) and New Brunswick (GeoNB, open, bilingual) are the next candidates.
- Several address sources per job, parcels for Placement, and pilot states whose statewide source is a
  file download rather than an ArcGIS service.
- Phase 2: changelog-driven reruns, `exact_rematch` / `near_rematch` in the ledger, the churn table.

## Standards

`docs/standards/` summarizes NENA-STA-006.3 (GIS Data Model), CLDXF-US and CLDXF-CA with links to the official
documents, lists every NENA layer and field, and ranks what Packages still miss ([gap review](docs/standards/gap-review.md)).

## Licensing

Code: MIT. Data keeps its sources' licenses: each manifest lists every source with its license status, and a
source marked `unknown` stays out of anything published openly. Overture addresses carry their per-source
licenses (not ODbL); no OpenStreetMap-derived geometry goes into a Package's core layers.

Sources with a missing or unclear licence, and areas with no usable source, are tracked in
[docs/license-remediation.md](docs/license-remediation.md) so the agencies can be asked.
