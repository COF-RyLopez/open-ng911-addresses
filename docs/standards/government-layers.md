# What to look for on government endpoints

A checklist for whoever writes a `registry/<country>/<code>.toml`: per NENA layer, what to search the state or
province NG9-1-1 program, the state GIS hub and the county ArcGIS sites for, and the national open fallback when
nothing local exists. Record every source with its licence status; if the licence is missing or unclear, add it
to the remediation tracker ([../license-remediation.md](../license-remediation.md)) instead of guessing.

Search terms that find NG9-1-1 layers on ArcGIS Hub / REST directories: `NG911`, `NG9-1-1`, `E911`, `SSAP`,
`SiteStructureAddressPoint`, `RCL`, `RoadCenterline`, `PSAP`, `ESZ`, `ESB`, `Provisioning`, `NENA`.

| NENA layer | Look for (state / county) | National open fallback |
|---|---|---|
| SiteStructureAddressPoint | E911 / NG911 address points, "site" or "structure" points; also call boxes, roadside phones, cell towers, utility poles with numbers, trailheads | OpenAddresses entry; USDOT National Address Database (licence per contributing state: check); StatCan National Address Register (`ca/countrywide` in OA, Statistics Canada Open Licence) |
| RoadCenterLine | NG911 / E911 road centerlines with address ranges; DOT road inventory (LRS) | TIGER ADDRFEAT (public domain); Canada National Road Network, NRN (Open Government Licence – Canada, has address ranges: the Canadian TIGER) |
| Street name aliases | Alias / alternate-name tables beside the centerlines, honorary names | TIGER FEATNAMES |
| ProvisioningPolygon | State NG911 GIS program "provisioning boundaries" | The Package area |
| PsapPolygon | PSAP boundaries from the state 9-1-1 board / NG911 program | None that is authoritative; the FCC PSAP Registry has no geometry |
| Police / Fire / EMS | Law, fire and EMS response areas, ESZ / ESN polygons, fire districts, ambulance districts (often special-district layers) | None authoritative. Station points only for sanity checks |
| Other service boundaries | Forest fire protection areas, poison control regions, coast guard sectors | USFS / state forestry protection areas (check licence) |
| A1Polygon | (state) | TIGER states; StatCan provinces/territories |
| A2Polygon | County boundaries if the state's differ from TIGER | TIGER counties; StatCan census divisions |
| A3Polygon | Municipal boundaries (often more current than TIGER) | TIGER places / county subdivisions (ADR 0009); StatCan census subdivisions |
| A4Polygon | Unincorporated community / hamlet polygons | None (CDPs are statistical) |
| A5Polygon | Neighbourhood polygons (cities) | None |
| SiteStructureAddressPolygon | Building footprints, parcels, campus / site polygons | Government footprints only; no Microsoft or OSM footprints (ODbL) |
| RailroadCenterLine | State DOT rail | FRA North American Rail Network (public domain); Canada National Railway Network (OGL – Canada) |
| HydrologyLine / Polygon | State hydrography | USGS NHD / 3DHP (public domain); Canada National Hydro Network (OGL – Canada) |
| DistanceMarkerPoint | DOT mile / reference markers, kilometre posts, trail markers | None national |
| LocationMarkerPoint | Call boxes, emergency phones, alarm boxes, numbered poles, river access points, trail junction markers, low-water crossings | None national |
| Named places (Site, Structure, Place_Type) | Schools, hospitals, fire and police stations, parks, campgrounds, airports, government buildings | Overture Places as review candidates (CDLA-Permissive-2.0); federal facility lists where public domain |

Notes:

- HIFLD Open (US critical infrastructure points) was shut down in 2025; some layers moved elsewhere with their own
  terms. Check each before use.
- NAD and NAR aggregate other agencies' data. Prefer the agency's own endpoint (it carries the agency's IDs and is
  what we hand back), and use the aggregate only where no direct source exists.
- A layer we find but can't use (no licence, share-alike, restricted) still goes in the tracker, so the agency can
  be asked.
