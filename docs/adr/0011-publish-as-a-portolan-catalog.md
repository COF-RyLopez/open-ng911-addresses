# Packages are published as a Portolan catalog, and only open, opted-in Packages carry data

Each release's Packages are published as a static STAC catalog that follows the Portolan spec (GeoParquet
assets, STAC metadata, README and AGENTS files, checksums), so it can sit on Source Cooperative or any bucket
with no server and be read with DuckDB over range requests. `catalog.py` writes it from the manifests the jobs
already produce, as one more step after the builds rather than a separate system; portolan-cli is used only to
validate and push. The tree is a catalog per country and job, a Collection per Package (manifest.json and
domains.json as metadata assets) and an Item per NENA layer, because a Package is several distinct files and
Portolan models those as Items.

A Package's data is public only when every source in it is openly licensed (ADR 0004), including the Overture
licences of its Gap-fill candidates, and its 911 authority has opted in (ADR 0003): until then the catalog
would be publishing it under a placeholder domain. Every Package, withheld or not, is a row in the public
scorecard collection (counts, coverage, licence and opt-in state on its outline, no address data), and
`report.json`, which is not pushed, lists why each withheld Package is out. The trade-off: until an authority
opts in, the public catalog holds only the scorecard.
