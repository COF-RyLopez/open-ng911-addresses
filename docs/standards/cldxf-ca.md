# CLDXF-CA (NENA-STA-029.1-2025), in brief

Our summary. The standard:
[NENA-STA-029.1-2025 PDF](https://cdn.ymaws.com/www.nena.org/resource/resmgr/standards/NENA-STA-029.1-2025_CLDXF-CA.pdf)
(NENA Board approved 2025-04-28, next review 2028-04-28; © NENA, no redistribution grant). Esri Canada's
[FAQ](https://resources.esri.ca/ng911/the-a-b-cs-of-c-l-d-x-f-ca-a-faq-for-the-newly-published-cldxf-ca-standard)
is a readable companion. ADR 0006 adopts it for Canadian Packages.

> Source note: we read the front matter and section 2 up to Distance Marker verbatim; later sections (named
> locations, Place Type, PIDF-LO construction, Appendix A by province) only in summary. Check those against the
> PDF before relying on details.

## What differs from the US

- **Same field set, different rules.** STA-006.3 uses one schema for both countries; CLDXF-CA decides the
  Canadian business rules. Canada adds **Additional Code** (`AddCode`) and uses a single **Unit**; it has no
  `AddNum_Cmp`, `PostCodeEx`, `Dir_Travel`, `UnitPreTyp` or `UnitValue`.
- **A1–A5 are country-agnostic levels.** A1 is the province or territory (ISO 3166-2 code, upper case). A2 is the
  primary subdivision where one exists (county, regional district, regional county municipality); A3 the
  municipality or unincorporated community; A4 a part of A3 (hamlet, former municipality); A5 a part of A4
  (neighbourhood). Which real unit sits at each level varies by province (the standard's tables and Appendix A).
  Where a popular and a legal name both exist ("Montréal" / "Ville de Montréal"), the local authority picks one
  and keeps it consistent with its GIS.
- **Additional Code**: up to six case-sensitive characters, unique in the province, tied to one A2, A3 or A4,
  used when A2 + A3 + A4 + street name still isn't unique. It is assigned by the authority; we never mint one.
- **English and French.** Directionals are the full English or French words (`North`, `nord-est`, `ouest`).
  Street types come from the same NENA registry as the US, spelled out (`Rue`, `Chemin`, `Montée` as pre types).
  Accented characters are allowed in printable fields; Canadian spelling ("centre", "neighbourhood").
- **Postal Community Name and Postal Code** are optional; official names, not alternates.
- **Unofficial place names** (hamlets, neighbourhoods, subdivisions) may be included when they help locate an
  address; they have no official list.
- **Place Type** has no fixed domain in Canada (examples are free text such as `aéroport`, `usine`).
- At the XML level every element is optional; the business rules make Country and A1 mandatory and the others
  conditional.

## For our Packages

- `nena/cldxf_ca_domains.json` (PR #4) was compiled by hand from Canada Post lists; check it against the NENA
  registry and the CLDXF-CA tables before a hand-off.
- A2 for PEI is the StatCan census division name; confirm the A-level mapping per province with Appendix A.
- `AddCode` stays empty until an authority gives it to us.
