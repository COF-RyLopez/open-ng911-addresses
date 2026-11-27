# Source data scenarios

A running catalog of the patterns found in each Source agency's data that hide information a NENA field should
carry, or that make a validation check fail for a reason other than a real error. One row per scenario, per
jurisdiction. Add rows as new jurisdictions are built; never delete one (mark it resolved and say how).

How rows are found: every build runs `scenarios.py` after the validation score and prints its findings as the last
step of the CI build job (`[job] scenarios: {...}`, also in job.json). It compares duplicate groups and range
failures with every raw field of the Source layer, mapped or not. The same scenarios are tracked in gbrain at
`standards/source-data-scenarios`, and each fix is an attempt under `sim/problems/` (domain ng911-pipeline).

Columns:
- **Scenario**: what the data does.
- **Evidence**: counts from the scenarios report, with the CI run.
- **NENA home**: the NENA-STA-006.3 / CLDXF field the information belongs in, or the check it affects.
- **Action**: `pipeline` (fixed in code for every jurisdiction), `registry` (a mapping in registry/*.toml),
  `agency` (only the Source agency can fix it; goes in their Package report), `upstream` (OpenAddresses or a state
  or federal source), `log` (understood, nothing to change yet).

First pass: PR #25, CI run 45945329812 (2026-11-27), Overture release resolved at run time.

## Every jurisdiction

| Scenario | Evidence | NENA home | Action | Status |
|---|---|---|---|---|
| Duplicate key missed CLDXF subaddress elements (`building` was not a NENA field; no site, subsite, wing, section, row) | Fixed keys tell apart ND structure 145, ME site 229, UT structure 229 groups | duplicate_address key = number + street + Site..Seat | pipeline | fixed in PR #25 |
| Same number and street in two communities of one A3 | PEI 29/29 Record dup groups differ in COMM_NM (GEORGETOWN vs MONTAGUE); ND Post_Comm, MSAGComm | A4, MSAGComm, Post_Comm in the duplicate key | pipeline | PR #25 (A2, A3: compared only between two Records) |
| Overture's own copy of a Record left as a gap-fill candidate on top of it, because the one-round matcher pairs only one of several stacked Records | Record + gap-fill stacked groups: ND 3398, UT 3545, PE 1017, VT 754, ME 376. ND candidate source_record_id = the Record's Site_NGUID without braces | Not a gap (ADR 0001); the Record should carry the GERS ID | pipeline | PR #25 (matcher rounds + unit ranking) |
| A point farther than 150 m (ranges.MAX_M) from any segment of its street | VT 21,108 of 21,423 no_matching_road; ND 37,032 of 38,126; ME 62,389; UT 72,811 | on_named_road; rural driveways and setbacks | pipeline: consider a longer reach for on_named_road | open |
| The `mapped` flag in the report reads only registry `nena` tables, so fields mapped by the OpenAddresses conform (city, unit, postcode) show as unmapped | PEI COMM_NM (OA city -> Post_Comm) flagged unmapped | reporting | pipeline | open |

## Vermont (us-vt, VCGI E911 ESITE)

| Scenario | Evidence | NENA home | Action | Status |
|---|---|---|---|---|
| Outbuildings carry the primary structure's address (SITETYPE ACCESSORY BUILDING, ACCESSORY BARN) | 2250 + 466 of 3176 Record dup groups, all > 25 m apart; ACCESSORY BUILDING fails rcl_agreement 91.8% (n 13,615) | Structure / Site (CLDXF) or Place_Type; agency decides if they are separate addressable sites | agency + log | open |
| UNITCOUNT 0 vs 1 marks accessory vs primary | Differs inside Record dup groups | Place_Type / Placement hint | log | open |
| SUBTYPE field (unmapped): '0' (30,719 points) fails rcl_agreement 45%, empty 4.3% | Many fields split the same way on "" vs null: a second population of points | Ask VCGI what SUBTYPE means before mapping | agency | open |
| HOUSE_NUMBERPREFIX letters always fail the range check | rcl_agreement split | AddNum_Pre (ranges ignore prefixes) | log | open |
| SITETYPE_MULTI1..5 list several uses of one site | Differs in dup groups | Place_Type (one value) | log | open |

## North Dakota (us-nd, NDGISHub NG911)

| Scenario | Evidence | NENA home | Action | Status |
|---|---|---|---|---|
| Distinguishers kept in Addtl_Loc (CHURCH / PARSONAGE, TWR 1..4, CP 1..12) | Differs inside Record dup groups | Addtl_Loc is the NENA field, but TWR n / CP n are Structure or Unit | agency | open |
| Same address in two Post_Comm / MSAGComm / Post_Code within one A3 | Differs inside Record dup groups | Post_Comm, MSAGComm | pipeline | PR #25 (A2, A3: compared only between two Records) |
| Number suffixes C, D, E fail the range check far more often | rcl_agreement split | AddNum_Suf | log | open |
| ACCURACY and NOTES unmapped | Differs in dup groups | none in NENA (agency notes) | log | open |
| range_overlap: one segment's range contains another's | one_contains_other 822, same_range 136 | RoadCenterLine.range_overlap | agency | open |

## Maine (us-me, Maine E911 address points; roads from TIGER)

| Scenario | Evidence | NENA home | Action | Status |
|---|---|---|---|---|
| E911 route names don't match TIGER's (US Route 2 vs US Hwy 2, street "1") | 69,908 of 132,297 no_matching_road are name mismatches; top street "1" (1,446) | St_PreTyp / St_Name per CLDXF; roads need the state E911 centerlines (restricted) | upstream + pipeline (route alias in street.py) | open |
| TIGER range overlap is an artifact of TIGER, not of the agency | one_contains_other 74,531, partial 23,032, same_range 7,973 | RoadCenterLine.range_overlap | log; replace roads when the E911 centerlines open | open |
| PLACE_TYPE (Apartment vs Single Family) and MAP_BK_LOT / STATE_ID (parcels) differ inside dup groups | Record dup groups | Place_Type; parcel ID has no NENA field | registry (Place_Type) | open |
| GC_EXCEPTION (geocode exception codes 300/402) and MAO_EXCEPTION ("USPS County Project") | Record dup groups | none; agency QA flags | log | open |
| "Structure - Interior Unit" placement fails rcl_agreement 17% | by_placement | Placement | log | open |

## Utah (us-ut, UGRC address points)

| Scenario | Evidence | NENA home | Action | Status |
|---|---|---|---|---|
| UTAddPtID is a concatenated address ("LOGAN \| 230 W 100 N"), not a unique ID | Record dup groups share it | Site_NGUID must come from somewhere else | registry (id_field) | open |
| Unmapped Structure flag (Yes / YES / Y / Unknown) | Differs in dup groups | Placement or a Structure hint, not CLDXF Structure (a name) | log | open |
| UnitType TRLR, SPC, UNIT fail rcl_agreement 35%, 32%, 24% | rcl_agreement split | UnitPreTyp; mobile home parks addressed off the park road | log | open |
| CountyID splits the rcl_agreement fail rate by 0.22 | source_fields_splitting | county-by-county range quality | agency | open |
| Ogden-style numbered and president streets unmatched (GRANT, 25TH, ADAMS, JEFFERSON) | 67,034 name mismatches | St_PreDir / St_PosDir or alias names | pipeline (alias) | open |

## Prince Edward Island (ca-pe, PEI civic address)

| Scenario | Evidence | NENA home | Action | Status |
|---|---|---|---|---|
| Road centreline has names but no ranges | 82,867 no_range | RoadCenterLine ranges | upstream (find a ranged layer) | open |
| COMM_NM is the civic community; the same number and road recur in neighbouring communities | 29 Record dup groups, all differ in COMM_NM | Post_Comm (via OpenAddresses city); CLDXF-CA community | pipeline | PR #25 (A2, A3: compared only between two Records) |
| INFO carries the site use (MULTI BLDG, SFD, DUPLEX, SUMMER COTTAGE, GOVERNMENT WHARF, NESTED PID) | Differs in dup groups | Place_Type | registry | open |
| LOC_CODE (DT, DS, BT) and FIRE_COV differ in dup groups | Record dup groups | ESN / service zones | log | open |
