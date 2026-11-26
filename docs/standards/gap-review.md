# Gap review: the pipeline against NENA-STA-006.3 (2026-11-26)

What a Package has today (main + open PRs #2–#5) against what the standard asks, ranked by what it costs a
9-1-1 Authority to be missing it, then by how cheap it is for us to close. Sources for each layer:
[government-layers.md](government-layers.md). Licensing stance unchanged: government open sources first, no
ODbL or OSM content in core layers, Overture only where its licence is not ODbL.

## Where we are

| NENA layer | Level | Package today |
|---|---|---|
| SiteStructureAddressPoint | Required | Yes (main). 18 of the 57 US fields (`unit` among them, wrongly: see 1). |
| RoadCenterLine | Required | PR #5: government centerlines, TIGER fallback, GERS crosswalk |
| A2Polygon, A3Polygon | Strongly rec. | PR #3 (US), PR #4 adds StatCan CSDs |
| ProvisioningPolygon | **Required** | No |
| PsapPolygon, Police/Fire/EMS | **Required** | No |
| A1Polygon, A4Polygon, A5Polygon | Strongly rec. | No |
| SiteStructureAddressPolygon | Recommended | No |
| RailroadCenterLine, HydrologyLine/Polygon | Recommended | No |
| LocationMarkerPoint, DistanceMarkerPoint | Recommended | No |
| Street name / address aliases (Appendix E) | Required where they exist | No |

## Ranked gaps

1. **US units use the wrong field.** We write `unit`; the US template removes `Unit` and uses
   `UnitPreTyp` + `UnitValue` (`Apartment` + `4B`). Canada keeps `Unit`. A conformance bug that every US Package
   has today, and a small parse change. *Fix next.*
2. **ProvisioningPolygon is missing (Required).** For an unclaimed Package it is simply the Package area (TIGER
   county / StatCan CD), which tiles with its neighbours; an opted-in authority replaces it with its own. Cheap.
3. **Service boundaries are missing (Required: PSAP, police, fire, EMS).** The ECRF can't route without a PSAP
   layer. But every required attribute (Agency_ID, ServiceURI, ServiceURN, AVcard_URI, DsplayName) is the
   agency's own value. Plan: pull geometry from state NG911 programs where published openly, ship it only to the
   opted-in authority with those fields left for them, and never put an invented URI in a public Package.
   Highest impact, mostly blocked on agencies.
4. **Location markers and addressed equipment.** Call boxes, roadside phones, poles, cell towers, mile markers
   are SSAP cases (INF-014; PR #2 now keeps them). Fill `LocMarker` / `DistMarker` and `Place_Type` from the
   agency's site type (`source_site_type`), and add LocationMarkerPoint / DistanceMarkerPoint from DOT and park
   layers. Safety-relevant, moderate work.
5. **Named places: Site, SubSite, Structure, Place_Type are empty.** This is where landmarks and common place
   names go in v3. First from the agency's own fields (many E911 layers carry a site or building name), then
   Overture Places as *review candidates* (below). Moderate work, high value to call takers.
6. **Validation gate is thin.** It checks mandatory fill and NGUID uniqueness. Add the NSGIC checks that need no
   agency data: SSAP A-levels match their polygon, SSAP inside the Package, SSAP ↔ RCL name/range/side agreement,
   RCL connectivity, range overlaps and parity, duplicate features. Report them per Package rather than failing.
7. **Other SSAP fields we could fill from data we already read**: `Longitude`/`Latitude` (from geometry),
   `AddNum_Pre`, `AddNum_Cmp` (grid and hyphenated numbers), `St_PreMod`/`St_PosMod`, `St_PreSep` ("Avenue **of
   the** Americas"), `PostCodeEx`, `Placement` (from the source's method where it states one; INF-014 values),
   `Effective`/`Expire` where the agency carries them. `A4`/`A5` once their polygons exist.
8. **A1Polygon** (TIGER state / StatCan province, public domain / OGL). Trivial.
9. **Aliases.** Alternate street names from the agency's centerlines and TIGER ADDRFEAT/FEATNAMES; address aliases
   from agency alias tables. Needs the Appendix E alias tables (`Alias`, `AliasSet`) as a side table.
10. **A4 (unincorporated communities) and A5 (neighbourhoods).** No national authoritative polygon set; TIGER
    CDPs are statistical, not A4. Agency or county layers only; skip until a source exists.
11. **SiteStructureAddressPolygon.** From government building footprints (first) and parcels (OA lists 1,152 US
    parcel sources, mostly without a stated licence). Recommended only.
12. **Rail and hydrology.** FRA North American Rail Network and USGS NHD / 3DHP (US, public domain); Canada's
    National Railway Network and National Hydro Network (Open Government Licence – Canada). STA-006.3
    Appendices A–D give the field crosswalks. Cheap, recommended, mostly for display.
13. **3D** (`Elevation`, `Height`, `FloorIndex`, Z geometry). Optional today.

Never ours to fill: ESN, MSAGComm, LCountyID, AddCode, agency domains, service URIs (ADR 0004).

## Overture: what more could help

| Theme | Licence | Use |
|---|---|---|
| addresses | per source (no ODbL) | In use: Gap-fill candidates and GERS IDs |
| **places** | CDLA-Permissive-2.0 (some rows Apache-2.0 or CC0; checked on release 2026-11-18.0) | **Yes, as candidates** |
| transportation, buildings, divisions, base | ODbL (OSM) | No content. GERS IDs only, via our crosswalks |

**Places is the one theme that fits the stance.** In a Middlebury VT sample (release 2026-11-18.0), 2,878 place
source records came from Overture, Meta, BrightQuery, Microsoft, Foursquare, Uberall and AllThePlaces, all permissive, none OSM.
Each has a name, `basic_category`, confidence, and often an address. Uses, all as review candidates under
ADR 0001 (Records win):

- **Site / Structure names for Records.** Pair a place to a Record by number + street key, else nearest within
  the Record's parcel or a few metres; propose its name as `site` or `structure` for the agency to accept. Fire
  and police stations, schools, colleges, hospitals, parks, campgrounds, malls and airports are the call-taker
  wins.
- **Place_Type.** Map `basic_category` to the IANA Location Types (`hospital`, `school`, `airport`,
  `place-of-worship`, `restaurant`, `store`, `hotel`, `stadium`, `library`, `government`, `prison`, `bank`,
  `parking`, `train-station`, `bus-station` ...). Unmapped categories stay empty.
- **Aliases.** A place name that differs from the agency's site name becomes an alias suggestion, never a
  replacement.
- **Gap-finding.** A high-confidence place with an address that matches no Record or Overture address is a
  Gap-fill lead for the agency.
- **Sanity checks for service boundaries** (a fire station outside every fire polygon), not boundaries
  themselves.

Cautions: places are commercial-grade and not authoritative; use a confidence floor (start at 0.7) and keep them
out of the core layers until an agency accepts them. CDLA-Permissive-2.0 asks that the licence text travel with
shared data, so a Package that carries any Places-derived value must include it and list Overture Places as a
source in the manifest.
