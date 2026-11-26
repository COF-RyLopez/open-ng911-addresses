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
| Name / class disagreements on linked segments | Not yet | Official names and classes Overture could take from government data |
| Agency edit dates newer than the national layer (TIGER vintage, NRN date) | Partly (`source_date`) | Where state/federal layers lag local ones: evidence for faster refresh |
| Agency segments not in TIGER ADDRFEAT / NRN | Not yet | Local change the federal layers haven't caught |
| Licence class of each source | Yes (tracker) | Only `open` sources can go upstream |

## Who would receive what

- **Overture**: addresses through OpenAddresses (already its path); roads as an authoritative source beside
  TomTom (contact via community@overturemaps.org; the Transportation working group). Overture's transportation
  theme today is OSM + TomTom + "other local and regional authoritative sources", ODbL.
- **State NG911 programs**: county edits they haven't absorbed (only where the state aggregates).
- **Census (TIGER)**: through the agency's own channels (Census GUPS/BAS, LUCA); we only show the gap.
- **USDOT NAD / StatCan NAR**: through each state or province's submission.

## Next steps (not built yet)

1. Add name/class disagreement and "not in TIGER/NRN" counts to `job.json` and the manifests.
2. A per-job `upstream.json`: open-licensed segments and addresses that Overture or the national layer lacks,
   with counts only in public artifacts.
3. A one-page Overture pitch from the Vermont and PEI numbers.
