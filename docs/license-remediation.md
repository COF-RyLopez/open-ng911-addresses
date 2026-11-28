# License remediation tracker

Where we record sources whose licence is missing or unclear, and jurisdictions with no usable source at all, so
the agencies can be asked later. Nothing here is a claim about what an agency allows.

## Rules

- **We never speak for an agency** (ADR 0004). The tracker says what *we* found on a public page and what we would
  like to ask. It never says an agency "allows" or "approved" anything until the agency has written so.
- **A person sends every request**, from the project's own identity, to the agency's published contact (an open
  data page, a GIS contact form, a 9-1-1 program address). No agent emails, posts or files a request on its own.
- **Only a written answer changes anything.** When an agency answers, record the date, who answered (role, not a
  personal address), and a link or archived copy. Then, and only then, change that source's `license_status` in
  `registry/<country>/<code>.toml`.
- No personal emails or phone numbers in the repo: link the public contact page.

## Files

| File | Edited | What |
|---|---|---|
| `registry/remediation/requests.toml` | by hand | The worklist: one entry per source or jurisdiction we want to ask about, with its status |
| `registry/remediation/oa_sources.csv` | generated | Every US/CA OpenAddresses source layer (addresses, centerlines, parcels, buildings) with the licence OA records and our first-read class |
| `registry/remediation/oa_coverage.csv` | generated | Per state/province and layer: sources, statewide sources, counties with their own source, counts per class |
| `registry/remediation/county_gaps.csv` | generated with `--counties` | US counties with no OA address source, or only unclear ones |
| `registry/remediation/oa_proposals.csv` | generated | Endpoints our registry reads through an `oa_entry`, and whether OpenAddresses lists them (`new`, `fix`, `listed`) |

Regenerate with `python scripts/license_remediation.py` (downloads OpenAddresses master) or
`--oa <checkout>`. Add `--counties <geoid,name csv>` (the Census Gazetteer counties file works) for the county
gaps; CI or a machine that can reach census.gov can produce it.

## Licence classes (first read, not legal advice)

| Class | Meaning | Usable in a public Package? |
|---|---|---|
| `open` | Public domain, CC0, CC BY, ODC-By, an Open Government Licence | Yes, with attribution |
| `share-alike` | ODbL, CC BY-SA | No (project stance) |
| `restricted` | Non-commercial, reference only, signed or end-user agreements | No |
| `presumed` | OpenAddresses marked the licence as presumed, not stated by the publisher | Ask first |
| `stated-unreviewed` | A licence URL or text we don't recognise | Someone reads it, then reclassify |
| `unstated` | Nothing recorded | Ask |

Snapshot of 2026-11-26 (OpenAddresses `1d9762c`, 3,991 US + Canada source layers):

| Layer | open | presumed | stated-unreviewed | unstated | share-alike | restricted |
|---|---|---|---|---|---|---|
| addresses | 198 | 238 | 143 | 1,548 | 13 | 3 |
| centerlines | 9 | 11 | 4 | 187 | 0 | 0 |
| parcels | 77 | 130 | 69 | 929 | 4 | 1 |
| buildings | 51 | 40 | 38 | 294 | 3 | 1 |

So 87% of the centerline sources (187 of 211) state no licence. Canada has no OA centerline source at all
(NRN is the fallback). Nunavut has no territorial OA address source; only the countrywide StatCan National Address Register reaches it.

## Proposing endpoints to OpenAddresses

When a job finds a government layer OpenAddresses doesn't list (addresses, centerlines, parcels or buildings),
write it in the job's registry as an `oa_entry` in OpenAddresses' own schema (endpoint, protocol, licence,
attribution, conform), so the build reads it and the entry can go upstream unchanged. `oa_proposals.csv` lists
every one with `status` `new` (OpenAddresses doesn't list it) or `fix` (it lists the layer differently) until the
OpenAddresses source file has the same entry, then `listed` (and the `oa_entry` can be dropped from the registry).
`scripts/oa_upstream.py` drafts each pull request; a person opens it (docs/openaddresses-upstream.md).
OpenAddresses takes sources with no stated licence, so a proposal doesn't wait on the licence ask; the licence
travels in the entry as found.

## Request status

`found` (in the tracker, nobody has looked closely) → `ready` (we know what to ask and whom) → `asked` (a person
sent it; date recorded) → `answered` (the agency wrote back; link recorded) → `resolved` (registry updated) or
`declined` (the agency said no; the source stays out). `no_source` entries move to `resolved` when a usable
source appears.
