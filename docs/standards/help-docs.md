# Supporting documents

Help for specific elements and checks. Summaries in our words; follow the link for the text.

## NENA-INF-014.1.1-2026: developing Site/Structure Address Points

[PDF](https://cdn.ymaws.com/www.nena.org/resource/resmgr/standards/standards1/nena-inf-014.1.1-2026_ssap_r.pdf)
(reaffirmed 2026-03-24; © NENA). The how-to for SSAP.

- **What gets a point** (its scenario list): multiple structures on one property, mobile home parks, apartments,
  business parks, malls, campgrounds, marina slips, vacant lots, landmarks (monuments, statues, traffic circles,
  bridges), recreation areas without structures, **phone booths and roadside phones**, **utility nodes** (phone
  poles, substations), oil and gas wells, mines, borrow pits, wind turbines, **cell towers**, temporary
  addresses, cemetery plots, airfields, railroad crossings, gate phones, train control boxes. It is desirable
  for every structure to have an address even when it can't be separately addressed.
- **Placement methods**: geocoded from centerlines, parcel, site, structure (polygon centroid by default),
  property access (on the driveway, not on the centerline). Record the method in `Placement`.
- **Sub-addresses**: one point per unique address; units may share a point at a shared entrance or sit in a
  related table. Common area names ("Softball Field") are valid sub-address values.
- **Primary point**: no rule when a site has several entrances; don't guess a primary structure from imagery.

## NENA-INF-028.1-2020: GIS data stewardship for NG9-1-1

[PDF](https://cdn.ymaws.com/www.nena.org/resource/resmgr/standards/NENA_INF_028.1_2020_GISDataS.pdf) (© NENA).
Roles (9-1-1 Authority, GIS Data Provider, addressing authority), discrepancy reporting, update cycles. Not yet
summarized here; read it before designing the discrepancy-report path for opted-in agencies.

## NSGIC Recommended Validations for NG9-1-1 GIS Data (May 2026)

[PDF](https://nsgic.org/wp-content/uploads/2026/06/NSGICRecommendedValidationsforNG911Data.pdf) (no license
stated: we list check names only). The checks states and NGCS providers run. Our gate covers only the first few.

- **Both layers**: valid geometry, known CRS, no duplicates, parsed components, persistent unique ID, required
  fields present, true nulls not blanks, domain values, A1/A2/A3 match the polygon the feature is in, inside all
  required service boundaries, no multipart features, SSAP ↔ RCL attribute consistency, postal fields.
- **RoadCenterLine**: connected to another segment, split and snapped at boundaries, no range gaps or overlaps,
  ranges increase in digitized direction, parity consistent, no overshoots/undershoots, self-intersections,
  kickbacks, duplicate vertices, very short segments, ALI and MSAG to RCL (agency-side).
- **SSAP**: on the correct side of the road, in order along the road, matches exactly one segment, ALI to SSAP
  (agency-side), fill non-required attributes where known.
- **Service boundaries**: no gaps, overlaps or slivers, plus the common checks.

## Registries the fields point to

- NENA Registry System: [street pre/post types](http://technet.nena.org/nrs/registry/StreetNamePreTypesAndStreetNamePostTypes.xml),
  [pre-type separators](http://technet.nena.org/nrs/registry/StreetNamePreTypeSeparators.xml),
  [SSAP placement methods](http://technet.nena.org/nrs/registry/SiteStructureAddressPointPlacementMethod.xml),
  [SSAPoly extent methods](http://technet.nena.org/nrs/registry/SiteStructureAddressPolygonExtentMethod.xml).
- IANA [Location Types](https://www.iana.org/assignments/location-type-registry/location-type-registry.xml)
  (US Place_Type) and the GIS Data Layers / `urn:emergency:uid` registries named in STA-006.3 section 7.
- NENA [Knowledge Base glossary](https://kb.nena.org/wiki/Category:Glossary) (Agency Identifier, DiscrpAgID terms).

## Crosswalks inside STA-006.3

Appendices A–D map national datasets onto NENA layers: **FRA rail lines** and **Canada's National Railway
Network** to RailroadCenterLine; **USGS NHD** and **Canada's National Hydrographic Network** to HydrologyLine and
HydrologyPolygon. Use them as the field mapping when we add those layers.

## Other NENA documents worth knowing

From NENA's template README: NENA-STA-008 (Registry System), NENA-STA-010 (i3, the NG9-1-1 architecture),
NENA-STA-015 (E9-1-1 data exchange), NENA-REQ-003 (3D GIS), NENA-INF-046 (GIS data transition). All on
[nena.org/page/standards](https://www.nena.org/page/standards).
