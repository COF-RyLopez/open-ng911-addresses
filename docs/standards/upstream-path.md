# The upstream path: local data → state, federal and Overture

Direction (Ryan, 2026-11-26): government sources are more authoritative than OSM but refresh less often. Local
agencies' data is the freshest government data there is. Every job should therefore also find **where local data
could update the layers above it** (state NG911 programs, TIGER, StatCan NRN / Road Network File, USDOT NAD,
StatCan NAR) **and Overture**, so Overture can slowly move off ODbL datasets onto authoritative ones.

We still never speak for an agency (ADR 0004): we measure and record; a person proposes, and only with the
agency's own data and its licence.

## What each job should record

For every Package, beside the NENA layers:

| Signal | Already measured? | Meaning for upstream |
|---|---|---|
| Records with no Overture match (`records` − `records_with_gers_id`) | Yes (manifest) | Local addresses Overture lacks: offer via OpenAddresses once the licence is open |
| Gap-fill candidates | Yes | Overture addresses the agency lacks: review leads *for the agency*, not upstream |
| RCL segments with no GERS link | Yes (PR #5 crosswalk) | Roads in the agency's network that Overture (OSM/TomTom) lacks, or places they disagree |
| Name / class disagreements on linked segments | Yes (`upstream.overture` in the manifest) | Official names and classes Overture could take from government data |
| Agency edit dates newer than the national layer (TIGER vintage, NRN date) | Partly (`source_date`) | Where state/federal layers lag local ones: evidence for faster refresh |
| Agency segments not in TIGER ADDRFEAT / NRN, and the reverse | Yes for TIGER (`upstream.national`); NRN once its loader exists | Local change the federal layers haven't caught |
| Licence class of each source | Yes (tracker) | Only `open` sources can go upstream |

## Who would receive what

- **Overture**: addresses through OpenAddresses (already its path); roads as an authoritative source beside
  TomTom (contact via community@overturemaps.org; the Transportation working group). Overture's transportation
  theme today is OSM + TomTom + "other local and regional authoritative sources", ODbL.
- **State NG911 programs**: county edits they haven't absorbed (only where the state aggregates).
- **Census (TIGER)**: through the agency's own channels (Census GUPS/BAS, LUCA); we only show the gap.
- **USDOT NAD / StatCan NAR**: through each state or province's submission.

Endpoints the national registries don't list yet go upstream too: see "Proposing endpoints to OpenAddresses" in
[../license-remediation.md](../license-remediation.md).

## The counts (`upstream` in every manifest, totals in job.json)

- `overture`: per RoadCenterline segment, its primary GERS link: `not_in_overture`, `name_agrees` / `name_differs`
  (both names parsed to the published NENA form, then keyed the same way as the address match),
  `overture_unnamed`, `source_unnamed`, `class_agrees` / `class_differs` (NENA RoadClass and Overture class in
  coarse groups: highway, arterial, local, ramp, trail). Overture's names and classes stay in memory.
- `national` (Packages with government roads; US only for now): `not_in_national` (+ km), agency segments TIGER
  ADDRFEAT lacks; `national_not_in_government` (+ km), TIGER segments the agency's network lacks (a road gone, or
  one the agency hasn't mapped). Same geometric test as the GERS crosswalk. `date` is the TIGER vintage; the
  agency's own date is in `road_centerline.sources`.
- `upstream_eligible`: every government road source in the Package has an open licence.

## The ODbL replacement inventory (`odbl_replacement` in every manifest, totals in job.json)

Direction (Ryan, 2026-11-26): as jobs find government sources, record which of Overture's ODbL datasets each one
could replace. For every Package and each ODbL theme:

| Theme | Government sources we look for | National open fallback |
|---|---|---|
| `transportation` | the agency's E911 / county centerlines (OA `centerlines` layer) | US: TIGER/Line ADDRFEAT (public domain); CA: NRCan/StatCan NRN (OGL-Canada, loader to come) |
| `buildings` | county / state footprints (OA `buildings` layer) | none open (Microsoft footprints are ODbL) |
| `divisions` | the boundary layers we build Packages from | US: TIGER boundaries; CA: StatCan boundary files |
| `base_water` | none read yet | US: USGS NHD / 3DHP; CA: NRCan National Hydro Network (loaders to come) |

Each theme records `read` (sources this build used, with licence status), `catalogued` (layers the OpenAddresses
catalogue lists for that county or the whole state, with our first-read licence class, from
`registry/remediation/oa_sources.csv`), `national`, and a `status`:

- `government_open`: an open government source was read and covers the Package.
- `government_unclear`: one was read but its licence isn't open yet (a remediation request is the next step).
- `candidate`: nothing read, but a catalogued or national open source exists.
- `none`: nothing known.

job.json counts Packages per theme and status, so the Overture pitch can say "in N Packages an open government
source already covers transportation". It is an inventory, not a claim: whether a source replaces Overture's data
is for the agency and Overture, only open-licensed sources count, and a person proposes it (ADR 0004).

## Next steps

1. A Canadian national layer (NRN) loader, so `national` is measured for provinces.
2. A per-job `upstream.json`: open-licensed segments and addresses that Overture or the national layer lacks,
   with counts only in public artifacts.
3. Loaders for building footprints and USGS / NRCan hydrography, so `buildings` and `base_water` can reach
   `government_open`.
4. A one-page Overture pitch from the Vermont and PEI numbers and the inventory totals.
