# CLDXF-US (NENA-STA-004.2-2024), in brief

Our summary. The standard: [nena.org standards](https://www.nena.org/page/standards) (NENA-STA-004.2-2024,
approved 2024-02-25; © NENA, no redistribution grant). Background: the
[NENA KB entry](https://kb.nena.org/wiki/CLDXF_(Civic_Location_Data_Exchange_Format)).

> Source note: we have not read the 2024 PDF itself. This page rests on NENA-STA-006.3-2026 (which carries the
> CLDXF-US business rule of every field), the KB element list, and the 2014 first edition. Re-check against the
> 2024 text before a hand-off to an opted-in authority.

## What it does

CLDXF-US defines how a US civic location is broken into elements to travel in a PIDF-LO (the location object
of an NG9-1-1 call) and to match the GIS layers. STA-006.3 takes its field set and business rules for US data
from it. Two ideas matter most:

1. **Every part is its own element, spelled out.** "North Main Street" is Pre Directional `North` + Street
   Name `Main` + Post Type `Street`. Abbreviations are not used unless they are part of the official name.
2. **The address authority's official form is the one that goes in.** Alternates are aliases.

## Elements (STA-006.3 field in brackets)

- **Place names**: Country [Country], State [A1], County [A2], Incorporated Municipality [A3], Unincorporated
  Community [A4], Neighborhood Community [A5], Postal Community Name [Post_Comm], Postal Code [Post_Code],
  ZIP+4 [PostCodeEx].
- **Street name**: Pre Modifier [St_PreMod], Pre Directional [St_PreDir], Pre Type [St_PreTyp], Pre Type
  Separator [St_PreSep], Street Name [St_Name], Post Type [St_PosTyp], Post Directional [St_PosDir], Post
  Modifier [St_PosMod], Direction of Travel [Dir_Travel] (US only).
- **Address number**: Prefix [AddNum_Pre], Number [Add_Number], Suffix [AddNum_Suf], Complete [AddNum_Cmp]
  (US only: the display form, e.g. `N89W16758`, `194-03½`), Distance Marker [DistMarker].
- **Named and sub-address elements**: Site, SubSite, Structure, Wing, Floor, Unit Pre Type [UnitPreTyp] +
  Unit Value [UnitValue] (US only; Canada uses a single Unit), Room, Section, Row, Seat, Location Marker
  [LocMarker], Additional Location Information [Addtl_Loc].
- **Place Type** [Place_Type]: values from IANA's Location Types registry.

## Values

- Street pre/post types and pre-type separators: NENA Registry System lists (vendored in
  `src/open_ng911/nena/nena_sta006_3_domains.json`).
- Directionals: the eight full English words.
- A1: USPS two-letter code, upper case.
- Mixed case otherwise ("Main", not "MAIN").

## For our Packages

- US Packages must emit `unitpretyp` + `unitvalue` (e.g. `Apartment` + `4B`), not `unit` (the US template
  removes `Unit`). See [gap-review.md](gap-review.md).
- `addnum_cmp` and `st_premod`/`st_posmod` exist for Wisconsin/Illinois grid addresses, Queens hyphenated
  numbers, "Old"/"Business" modifiers; our parse doesn't fill them yet.
