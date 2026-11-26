# NENA-STA-006.3-2026: the NG9-1-1 GIS Data Model, in brief

Our summary, not NENA's text. The standard itself: [nena.org](https://www.nena.org/page/NG911GISDataModel) or the
[PDF in NENA's template repo](https://github.com/NENA911/NG911GISDataModel/blob/main/docs/nena-sta-006.3-2026_ng9-1-1.pdf).
Every layer and field: [nena-sta-006.3-layers.md](nena-sta-006.3-layers.md).

## What it is for

The model defines the GIS layers that NG9-1-1 Core Services load: the **ECRF** (routes a call by location),
the **LVF** (validates a civic address before a call is made), and the map and dispatch systems. Data reaches
them through the **Spatial Interface (SI)**. NENA's templates (GeoPackage, File Geodatabase, a relational schema
in Appendix E) are an *exchange* format between a GIS Data Provider and the SI, not a prescribed way to manage
data. That is exactly what a Package is.

## Layers and how much they matter

| Level | Layers |
|---|---|
| **Required** | RoadCenterLine, SiteStructureAddressPoint, PsapPolygon, Police / Fire / EMS service boundaries, ProvisioningPolygon |
| **Strongly recommended** | A1–A5 polygons (state/province, county or equivalent, municipality, unincorporated community, neighbourhood); other service boundaries (poison control, forest service, coast guard, animal control) |
| **Recommended** | SiteStructureAddressPolygon, RailroadCenterLine, HydrologyLine, HydrologyPolygon, DistanceMarkerPoint, LocationMarkerPoint |

Layer names and indicators (`SSAP`, `RCL`, `Psap` ...) come from the GIS Data Layers registry (IANA-hosted); the
indicator is the layer part of every NGUID.

## Rules that shape our Packages

- **SSAP covers any addressed location, and completeness isn't required.** The point layer can mark a site, a
  structure, an interior space, or the access to one. NENA-INF-014 lists phone booths and roadside phones, utility
  nodes, cell towers, wind turbines, wells, marina slips, campsites, gate phones and train control boxes as SSAP
  cases. Call boxes and phones stay in (see Vermont, PR #2).
- **Location markers and distance markers go into SSAP when the LVF needs them.** The LocationMarkerPoint and
  DistanceMarkerPoint layers are mainly for display. If a callbox, pole or mile marker must validate as a
  location, it MUST also be an SSAP, with `LocMarker` or `DistMarker` filled.
- **SSAP and RCL should agree.** Address number, street name and A1–A5 on a point SHOULD fit the range, name
  and left/right A-levels of the road it sits on.
- **The local addressing authority's name wins.** The official street name goes in RCL; others are aliases,
  kept compatible with the Appendix E relational model (alias tables keyed by NGUID).
- **NGUID** = `urn:emergency:uid:gis:<layer indicator>:<local id>:<agency domain>`, unique across every agency
  coalesced into the same ECRF/LVF. That is why ours are built from the Address UID and wait for the agency's
  own domain (ADR 0002, 0003).
- **DiscrpAgID** is the agency that receives discrepancy reports, written as its Agency Identifier (a domain).
  It is the agency's to name, never ours (ADR 0004).
- **DateUpdate** is a W3C dateTime and changes whenever attributes or geometry change.
- **ProvisioningPolygon** is the area a provider is responsible for. Data sent to the SI MUST stay inside it
  and MUST cover all of it, with no gaps or overlaps against neighbours. The 9-1-1 Authority is ultimately
  responsible for the data inside it.
- **Service boundaries** (PSAP, police, fire, EMS ...) share one structure: `Agency_ID`, `ServiceURI`,
  `ServiceURN`, `AVcard_URI`, `DsplayName` are all required and all agency-owned values. Every PsapPolygon
  feature has the Service URN `urn:service:sos`. A layer may hold several polygons per agency (beats, stations).
- **Legacy fields** (ESN, MSAGComm, LSt_*, LCountyID) exist for E9-1-1 transition only. We never invent them.
- **Domains**: street pre/post types, pre-type separators and placement methods come from the NENA Registry
  System; Place_Type (US) from IANA's Location Types registry; Country and A1 are ISO 3166 upper-case codes.
- **Country differences** follow CLDXF: the US uses `UnitPreTyp` + `UnitValue`, `AddNum_Cmp`, `PostCodeEx`,
  `Dir_Travel`; Canada uses `Unit` and `AddCode` instead ([cldxf-us.md](cldxf-us.md), [cldxf-ca.md](cldxf-ca.md)).

## Named places: Site, SubSite, Structure, Place_Type

Version 3 dropped the old landmark-name fields and the landmark part table. Named places now live in:

- **Site**: a publicly known exterior area, unique in its place (a campus, a park, an airport, an outlet mall).
- **SubSite**: a part of a site or of an addressed property (a parking lot, the tennis courts).
- **Structure**: a built thing with height: a building, a tower, a bridge, a fuel tank.
- **Place_Type**: what the addressed feature is. US values come from the IANA Location Types registry
  (`airport`, `hospital`, `school` ...); Canada has no fixed list.
- Other names a site is known by (sponsor names, older names) are **aliases**, not replacements.

This is where common place names and landmarks belong, and where Overture Places can help (see the gap review).

## 3D

SSAP and RCL support Z. `Elevation`, `Altitude`, `Height`, `FloorIndex` let a provider place a unit in 3D
(NENA-REQ-003). Optional for now.
