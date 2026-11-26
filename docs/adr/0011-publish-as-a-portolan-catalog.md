# Packages are published as a Portolan catalog, and every openly licensed Package carries data

Each release's Packages are published as a static STAC catalog that follows the Portolan spec (GeoParquet
assets, STAC metadata, README and AGENTS files, checksums), so it can sit on Source Cooperative or any bucket
with no server and be read with DuckDB over range requests. `catalog.py` writes it from the manifests the jobs
already produce, as one more step after the builds rather than a separate system; portolan-cli is used only to
validate and push. The tree is a catalog per country and job, a Collection per Package (manifest.json and
domains.json as metadata assets) and an Item per NENA layer, because a Package is several distinct files and
Portolan models those as Items. Each collection's vector tiles (PMTiles, with a MapLibre style) come from manby, which makes
tippecanoe's tiles from GeoParquet or a DuckDB query in one pip-installable binary (BSD-2-Clause), so the
build needs no tippecanoe toolchain.

A Package's data is public when every source in it is openly licensed (ADR 0004), including the Overture
licences of its Gap-fill candidates, and its job passed the gate. The address points are the core: if their Sources aren't open the whole Package is held back,
while any other layer with a closed Source (a PSAP or fire boundary, the roads) is left out of a published
Package on its own and named in `ng911:withheld_layers`. Opting in is not required (Ryan, 2026-11-26,
amending ADR 0003): a Package whose authority hasn't opted in is published as *unclaimed*, under the
`.unclaimed.invalid` placeholder domain, with its title, description and AGENTS.md saying it isn't the
authority's dataset. Every Package, withheld or not, is a row in the public scorecard collection (counts,
coverage, licence and opt-in state on its outline, no address data), and `report.json`, which is not pushed,
lists why each withheld Package is out. The trade-off: open data reaches people before the agency has looked at
it, so the unclaimed label has to stay prominent; `catalog.build(require_opt_in=True)` restores the stricter
gate if an agency objects.
