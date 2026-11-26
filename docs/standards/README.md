# Standards reference

What the NG9-1-1 standards ask of a Package, in our own words, with links to the official documents. Read this
before adding a layer or a field. The same pages are published to GBrain (`standards/*`), so agents outside
this repo see the same text.

| Page | What it covers |
|---|---|
| [nena-sta-006.3.md](nena-sta-006.3.md) | The NG9-1-1 GIS Data Model: layers, requirement levels, the rules that matter to us |
| [nena-sta-006.3-layers.md](nena-sta-006.3-layers.md) | Every layer and field, generated from NENA's machine-readable schema |
| [cldxf-us.md](cldxf-us.md) | CLDXF-US (NENA-STA-004): how US civic address elements are split and spelled |
| [cldxf-ca.md](cldxf-ca.md) | CLDXF-CA (NENA-STA-029): the Canadian rules, A1–A5 and Additional Code |
| [help-docs.md](help-docs.md) | Supporting documents: SSAP development, data stewardship, NSGIC validations, registries |
| [gap-review.md](gap-review.md) | What the pipeline is missing against the standard, ranked, and where the data could come from |
| [nena-coverage.md](nena-coverage.md) | Per job and layer: the NENA fields each build fills, before and after mapping the Sources' own fields |
| [government-layers.md](government-layers.md) | The layers to look for on government endpoints, per NENA layer |
| [upstream-path.md](upstream-path.md) | Where local data could update state, federal and Overture layers (the move off ODbL), and the per-Package ODbL replacement inventory |

## The documents and their licenses

NENA standards are free to download but copyrighted ("© National Emergency Number Association, Inc.") and carry
no reproduction or redistribution grant. So we **link** to them and **summarize** them; we don't copy their
text or PDFs into this repo or into GBrain. Field names, requirement flags and domain values are facts we
need to interoperate and are listed. NENA's template repository is different: it is Apache-2.0, so its
schema can be vendored with attribution (we already vendor its domains in `src/open_ng911/nena/`).

| Document | Version used | Where | License / what we keep |
|---|---|---|---|
| NENA-STA-006.3-2026, NG9-1-1 GIS Data Model | Board approved 2026-03-11, next review 2029-03-11 | [nena.org](https://www.nena.org/page/NG911GISDataModel); PDF in [NENA911/NG911GISDataModel/docs](https://github.com/NENA911/NG911GISDataModel/tree/main/docs) | © NENA, no redistribution grant: summary + link |
| NENA NG911GISDataModel templates v3.0 (flat-file YAML schema, GeoPackage, FGDB, relational schema) | commit `30a42bf` (2026-04-02) | [github.com/NENA911/NG911GISDataModel](https://github.com/NENA911/NG911GISDataModel) | Apache-2.0: domains vendored, layer/field tables generated |
| NENA-STA-004.2-2024, CLDXF-US | Approved 2024-02-25 (the version STA-006.3 cites). We have not read the 2024 PDF itself; the summary rests on STA-006.3's business rules, the NENA KB entry and the 2014 first edition | [nena.org standards](https://www.nena.org/page/standards), [NENA KB entry](https://kb.nena.org/wiki/CLDXF_(Civic_Location_Data_Exchange_Format)) | © NENA, no redistribution grant: summary + link |
| NENA-STA-029.1-2025, CLDXF-CA | Board approved 2025-04-28, next review 2028-04-28 | [PDF on nena.org](https://cdn.ymaws.com/www.nena.org/resource/resmgr/standards/NENA-STA-029.1-2025_CLDXF-CA.pdf) | © NENA 2025, no redistribution grant: summary + link |
| NENA-INF-014.1.1-2026, Site/Structure Address Point development | Reaffirmed 2026-03-24 (first issued 2015) | [PDF on nena.org](https://cdn.ymaws.com/www.nena.org/resource/resmgr/standards/standards1/nena-inf-014.1.1-2026_ssap_r.pdf) | © NENA: summary + link |
| NENA-INF-028.1-2020, GIS Data Stewardship for NG9-1-1 | 2020 | [PDF on nena.org](https://cdn.ymaws.com/www.nena.org/resource/resmgr/standards/NENA_INF_028.1_2020_GISDataS.pdf) | © NENA: link only (not yet summarized) |
| NSGIC Recommended Validations for NG9-1-1 GIS Data | May 2026 | [PDF on nsgic.org](https://nsgic.org/wp-content/uploads/2026/06/NSGICRecommendedValidationsforNG911Data.pdf) | No license stated: summary of check names + link |
| NENA Registry System (street types, pre-type separators, placement methods) | live | [technet.nena.org/nrs](http://technet.nena.org/nrs/registry/_registries.xml) | Registry values are vendored as domains |
| IANA Location Types registry (Place_Type values for the US) | live | [iana.org](https://www.iana.org/assignments/location-type-registry/location-type-registry.xml) | IANA registries are freely reusable |

The cloud sandbox can't reach nena.org; the PDFs above were read through a fetch tool or from NENA's GitHub
repository. If a newer revision appears, update the table, then the summary, then the gap review.
