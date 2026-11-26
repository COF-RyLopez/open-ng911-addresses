# Queens, Prince Edward Island: NG9-1-1 Package (unclaimed)

The NENA NG9-1-1 GIS dataset for Queens (Prince Edward Island), built from the Source agencies' own layers and reshaped to NENA-STA-006.3-2026: 2 Records and 1 Gap-fill candidates, 0 road segments. Recipient: Prince Edward Island 911 Administration (Department of Justice and Public Safety). Unclaimed: built from open government sources, not issued or checked by Prince Edward Island 911 Administration (Department of Justice and Public Safety); its NGUIDs use the placeholder domain ca-pe-1102.unclaimed.invalid until the authority opts in. Left out because a source's licence isn't open yet: PsapPolygon, PolicePolygon, FirePolygon, EmsPolygon (ng911:withheld_layers says which source).

## Layers

- [Queens: SiteStructureAddressPoint](./ca-pe-1102-site-structure-address-point/ca-pe-1102-site-structure-address-point.json)
- [Queens: A2Polygon](./ca-pe-1102-a2-polygon/ca-pe-1102-a2-polygon.json)
- [Queens: A3Polygon](./ca-pe-1102-a3-polygon/ca-pe-1102-a3-polygon.json)
- [Queens: ProvisioningPolygon](./ca-pe-1102-provisioning-polygon/ca-pe-1102-provisioning-polygon.json)

`manifest.json` holds the full numbers: NENA field coverage per layer, sources with dates, the GERS release, the
upstream counts and which government sources could stand in for Overture's ODbL themes here.

## Licence

Each layer keeps its sources' licences; no OpenStreetMap-derived geometry or names are in any layer.

- Government of Prince Edward Island, Civic Addressing (addresses): licence open, https://www.princeedwardisland.ca/en/information/finance/open-government-licence-prince-edward-island
- Government of Prince Edward Island (road centreline) (centerlines): licence unknown, https://www.princeedwardisland.ca/en/information/finance/open-government-licence-prince-edward-island
- Prince Edward Island 911 Administration (Emergency Service Zones) (psap): licence unknown, https://www.princeedwardisland.ca/en/information/finance/open-government-licence-prince-edward-island
- Prince Edward Island 911 Administration (Emergency Service Zones) (police): licence unknown, https://www.princeedwardisland.ca/en/information/finance/open-government-licence-prince-edward-island
- Prince Edward Island 911 Administration (Emergency Service Zones) (fire): licence unknown, https://www.princeedwardisland.ca/en/information/finance/open-government-licence-prince-edward-island
- Prince Edward Island 911 Administration (Emergency Service Zones) (ems): licence unknown, https://www.princeedwardisland.ca/en/information/finance/open-government-licence-prince-edward-island
- A2Polygon: Statistics Canada census divisions (Statistics Canada Open Licence), https://www.statcan.gc.ca/en/terms-conditions/open-licence
- A3Polygon: Statistics Canada census subdivisions (Statistics Canada Open Licence), https://www.statcan.gc.ca/en/terms-conditions/open-licence
- Gap-fill candidates: Overture's per-source licences: OGL-CA (1)

## Provenance

Built by [open-ng911-addresses](https://github.com/COF-RyLopez/open-ng911-addresses) from the Source agencies' layers, read through the OpenAddresses
source registry, and Overture release 2026-11-18.0. NGUIDs are under `ca-pe-1102.unclaimed.invalid`.
This is a processed copy: the agencies' own services are the authoritative data (see the `via` links).
