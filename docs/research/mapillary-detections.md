# Mapillary detections as road attributes: design note

Status: research, November 2026. Not legal advice. Nothing here is built yet.

**Question.** Can Mapillary's machine-detected traffic signs and map features (stop, speed limit, one-way,
turn-restriction signs, hydrants and so on) become attributes on our government road centerlines (speed
limits, turn restrictions, stop control), and what else in that data helps NG911?

**Answer in one paragraph.** Not in anything we publish. Mapillary's imagery is CC BY-SA 4.0, but its
detections have no open licence at all; the only ways Mapillary allows derived data to be published are into
OpenStreetMap or Overture, or elsewhere under ODbL. Using them would put share-alike (or no licence) into the
very layer we want to offer Overture as its non-ODbL road source, and the API terms forbid the bulk
extraction and redistribution a national pipeline needs. The idea is still good: build the "signs to road
rules" engine now against government sign and speed inventories, which several pilot states publish, and
keep Mapillary as a later input only if Meta grants written permission.

## 1. Licensing fit

| What | Terms (as published, read 2026-11-26) | Fit for public Packages |
|---|---|---|
| Imagery | CC BY-SA 4.0 (Terms 3(b); Help "Licenses"). Changed from CC BY-NC in 2014. | Share-alike. Fine to look at; republishing needs SA and the Mapillary logo + link (Terms 11). |
| Detections, map features, traffic signs | No licence named anywhere. Terms 3(a): data in the service is "owned by Mapillary or our licensors"; users get a limited, revocable, non-sublicensable licence to *use the service*. | No. No grant to redistribute. |
| Data derived from imagery or detections | Free for OSM (mapillary.com/osm) and, since the Feb 2024 Terms (s.13), for contributing to OSM **or Overture**. Elsewhere only "if it is publicly accessible and licensed under" **ODbL** (Help 115001777705). | No: the one route off-platform is ODbL, which is the licence we are trying to remove. |
| API use | Registered client_id; apps must "materially supplement" Mapillary; no data mining or extraction "not approved by Mapillary"; no merely redistributing content; no resale; Mapillary may throttle or revoke (Terms 5, 11). Feature queries cap at 2,000 per bounding box. | Bulk national pulls are not an approved use without a written agreement. |
| Navigation | Terms 5 bars use "in connection with real-time navigation or route guidance". | CAD routing and AVL are close to this line; another reason not to ship it to PSAPs. |
| Mapillary Traffic Sign Dataset (training data) | "Freely available for academic research". | Can't train a production model on it. |

What this means against our existing decisions:

- **Licensing stance** (government open sources, no ODbL): detections fail it, and our own model run over
  Mapillary images would fall under the same "derived metadata → ODbL" reading, on top of the scraping ban.
- **ADR 0007** (review layer private, flags carry no copyable content): the closest legitimate use would be a
  private flag such as "check the posted speed on this segment", with the agency verifying against its own
  records. Even that is "derived metadata" by Mapillary's wording, so it needs Mapillary's say-so first.
- **Overture pitch**: Terms s.13 already lets anyone use Mapillary to contribute to Overture. So Overture can
  use Mapillary itself (Meta is a founding member; a Mapillary staffer said in May 2026 there is "no
  production ready workflow" yet). Our value to Overture is the part Mapillary can't give them: government
  geometry, names, ranges and authoritative rules under open terms.

Verdict: the licence rules Mapillary out for Packages, tiles and anything sent upstream. It does not rule out
the engineering, which works on any point inventory of signs.

## 2. Coverage in the pilot states

Mapillary coverage was not measured: counts need an API token, and this sandbox can't reach
graph.mapillary.com. If we ever get permission, the measure is map-feature counts per county for
`regulatory--stop--*` and `regulatory--maximum-speed-limit-*`, divided by road km, plus last-seen dates.
From the public map it is densest along interstates and in cities and thin on rural local roads, which is
where most NG911 segments are.

The government alternatives matter more, so these were checked instead:

| Pilot | Speed limits | Signs / signals / control | Mile markers | Licence | Gap |
|---|---|---|---|---|---|
| VT | VTrans `Speed Limits` (layer 32: SPEED_LIMIT, SPEED_LIMIT_SOURCE, MODIFIED_DATE), `Speed Zones`, `No Passing Zones` | No sign or signal layer found | Mile-point fields on road-width layers | Not stated | Town roads; no turn rules |
| ME | MaineDOT OpenData `Posted Speed Limits` (34) | `Traffic Signals` (signal, beacon), `Railroad Crossings` | None found | Not stated | No sign inventory |
| UT | UDOT Speed Limits 2021, state routes, built from the Mandli sign inventory; "approximation only" | Sign Faces and Sign Assemblies with MUTCD codes (Mandli 2015; the service now needs a token); pavement messages | UDOT Mile Points (monthly) | No licence; "informational, field verify" disclaimer | State routes only; local roads in UGRC roads (check SPEED_LMT / ONEWAY in the build) |
| ND | No NDDOT speed layer found; NDDOT holds speed in its LRS | None found | NDDOT reference points (to look for) | Unknown | Ask the GIS Hub |
| PEI | NRN road segments (check SPEED and traffic-direction attributes) | None found | None found | OGL-Canada | Not checked in depth |

Everywhere: FHWA HPMS (US government work, annual) carries speed limit on sampled and federal-aid roads, the
FRA Highway-Rail Crossing Inventory (public domain) has every grade crossing, and many agency NG911 road
layers already fill the NENA RCL `SpeedLimit` and `OneWay` fields. The agency's own values win (ADR 0001).

Most of these state layers carry no stated licence. Under our rules they go into builds and the review
layer, and into public Packages and upstream offers only once the licence is confirmed (the same
`unclear` status the manifests already use).

## 3. Other detections useful for NG911

| Feature | NG911 use | Mapillary class exists? | Government / open alternative |
|---|---|---|---|
| Fire hydrants | Fire response, CAD premise info | Yes (`object--fire-hydrant`) | Water utility or fire department GIS, submitted by the agency |
| Emergency call boxes, phones | Site/structure points we must never drop | Phone booths, yes; call boxes, no distinct class found | DOT call-box inventories; agency SSAP `source_site_type` |
| Mile markers / reference posts | NENA Mile Marker layer; highway caller location | No class found | DOT LRS mile points (UDOT monthly, VTrans) |
| Traffic signals, stop lines, crosswalks | Intersection control, signal preemption | Yes (traffic lights, stop line, crosswalk markings) | DOT signal layers (MaineDOT); city signal GIS; stop bars and crosswalks from public aerials |
| Gates and barriers | Responder access, gated communities | Barriers partly; gates not a reliable class | Agency data; parcels |
| Railroad crossings | Blocked-route routing, caller location | Crossing signs | FRA crossing inventory (best source) |
| Street-name signs | Validate road names | Sign detected, text not read | Agency centerlines already hold names |
| Address-number signs, building entrances | Address point placement at the entrance | No | Agency submissions; open-imagery review by the agency |

## 4. Engineering approach

The engine takes a point table of signs from any source and turns it into road rules. It is the same whether
the input is UDOT's sign inventory, an agency's sign file, or (with permission) Mapillary.

**Input.** One row per sign: point, MUTCD code (Mapillary already publishes a value to MUTCD table, so its
input would map cleanly), facing bearing when known, source, source date, confidence.

**Snapping** (DuckDB spatial, in the job's UTM zone, as the road crosswalk already does):

1. Candidates are road segments within 20 m of the sign.
2. A sign faces the traffic it governs, so the travel bearing is the facing bearing + 180°. Keep candidates
   whose bearing at the nearest point is within 30° of that travel bearing (either digitised direction), and
   record the direction as FT or TF.
3. Without a facing bearing, use side of road: in the US and Canada a right-side sign governs traffic whose
   right side it is on.
4. Within 30 m of an intersection, assign the sign to the approach segment whose end bearing matches, and
   tag the sign as `at_node`.
5. Pick the nearest surviving candidate; ties or none go to an `unsnapped` count in job.json, by reason.

**Inference.**

- **Speed limit** (R2-1): per segment and direction, carry the last posted value downstream along the route
  until the next speed sign, a route or class change, or an intersection with a higher-class road. Write
  `SpeedLimit` (mph to kph via the existing conform) with source and date.
- **Stop control** (R1-1, R1-3P "all way", R1-2 yield): at the node, mark each approach stop or yield; all
  approaches stopped, or an all-way plaque, makes it all-way. NENA RCL has no field for this, so it goes in a
  separate `intersection_control(node, approach_uid, control)` table. Overture's schema lacks it too.
- **One-way** (R6-1/R6-2, R5-1 do not enter at a segment end): set `OneWay` FT or TF, and flag a segment
  whose two ends disagree.
- **Turn restrictions** (R3-1 no right, R3-2 no left, R3-4 no U-turn, R3-5 lane use): the from-segment is the
  approach; the to-segment is chosen by turn angle at the node. Output in the shape of Overture's
  `prohibited_transitions` (sequence of segment IDs plus heading) so it maps across. Time-of-day plaques can't
  be read from a sign code, so those are `conditional: unknown` and never published as absolute.

**Quality gates.** A rule needs either an authoritative inventory or two independent sightings; a source
date older than five years is marked stale; anything that disagrees with the agency's own value becomes a
review flag, never an overwrite. Each Package reports counts of rules inferred, by type and source.

**Output.** Rules from open-licensed government data go into the public Package next to the centerline, with
`source` and `source_license` like every other field. Rules from unclear-licence sources stay in the build
and the private review layer until the licence is settled.

## 5. Recommendation

1. **Do not ingest Mapillary detections** into Packages, tiles, the upstream path or the public scorecard.
2. **Build the sign-to-rules engine against government data first**: UDOT signs and speed limits, VTrans and
   MaineDOT speed layers, MaineDOT signals, FRA crossings, DOT mile points, and agency RCL `SpeedLimit` and
   `OneWay`. Start with speed limits and one-way in Utah, where both a sign inventory and a speed layer exist.
   This is new road content Overture can't get from OSM under open terms, which strengthens the pitch.
3. **Ask Meta in writing** (decided 2026-11-26; Ryan sends it person to person, not on an agency's behalf):
   permission to pull map features and traffic signs in bulk and to publish rules derived from them
   (attributes only, never imagery) in public Packages under CC BY 4.0 or CDLA-Permissive-2.0. Meta co-founded
   Overture and the Packages feed back into Overture's transportation theme. Until a written grant exists,
   Mapillary stays out, including the private review layer. With a grant, Mapillary has two jobs in the same
   engine, always behind agency and DOT values:
   - **Fill gaps** where a government publishes no sign inventory (most local roads, North Dakota, PEI):
     detections become candidate rules, needing two sightings, flagged as Mapillary-sourced.
   - **Check government inventories** where they exist (UDOT, future agency sign files): snap both to the
     same segments and compare. Signs Mapillary sees that the inventory lacks, inventory signs not seen in
     recent imagery, and changed values (a 45 now read as 35) become a maintenance report offered to that
     agency, the same opt-in, never-speak-for-them path as the rest of the upstream work. This is also the
     easiest use for Meta to say yes to, since it improves the government data Overture draws on.
4. **Open models on open imagery** later, for markings rather than signs: stop bars, crosswalks and turn
   arrows are visible in public-domain aerials (NAIP, and the states' open orthoimagery). Use models whose
   weights and training data both allow production use, which rules out the Mapillary Traffic Sign Dataset.
   Agencies that own street-level imagery can run detection themselves and submit the result as their data
   (ADR 0005). Panoramax, the open alternative to Mapillary, is CC BY-SA too (OSM France's instance also
   grants CC BY or ODbL for non-photo derivatives) and has almost no North American coverage, with one
   community instance for the north-western US.

## Sources

- Mapillary Terms of Use, effective 15 Feb 2024: <https://mapillary.com/legal>
- Mapillary Help, licences: <https://help.mapillary.com/hc/en-us/articles/115001770409>
- Mapillary Help, derived metadata and ODbL: <https://help.mapillary.com/hc/en-us/articles/115001777705>
- Mapillary for OSM: <https://mapillary.com/osm>
- OSM wiki, Mapillary: <https://wiki.openstreetmap.org/wiki/Mapillary>
- Mapillary forum, Overture thread (Apr–May 2026): <https://forum.mapillary.com/t/mapillary-data-and-the-overture-foundation/10350>
- Mapillary API FAQ: <https://www.mapillary.com/developer/api-documentation/faq>
- Mapillary signs to MUTCD: <https://www.mapillary.com/developer/api-documentation/mutcd>
- Mapillary Traffic Sign Dataset paper: <https://arxiv.org/abs/1909.04422v2>
- Panoramax (imagery licences per instance): <https://wiki.openstreetmap.org/wiki/Panoramax>
- UDOT Speed Limits: <https://maps.udot.utah.gov/central/rest/services/TrafficAndSafety/UDOT_Speed_Limits/MapServer>
- UDOT Open Data Guide (2017): <https://maps.udot.utah.gov/uplan_data/documents/DataGuide/OpenDataGuide.pdf>
- VTrans layers: <https://maps.vtrans.vermont.gov/arcgis/rest/services/Master/VTrans2/FeatureServer/layers>
- MaineDOT OpenData: <https://gis.maine.gov/arcgis/rest/services/dot/MaineDOT_OpenData/MapServer/legend>
- Overture transportation guide: <https://docs.overturemaps.org/guides/transportation>
