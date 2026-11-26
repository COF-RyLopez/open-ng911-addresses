# AGENTS.md

Guidance for coding agents working in this repo. Keep it short and true; update it when something here
stops being right. Terms are defined in `GLOSSARY.md`; decisions are in `docs/adr/`. Read both first.
What the NENA standards ask of each layer and field, and the ranked gaps: `docs/standards/`.

## What this is

The national (US + Canada) open-data NG9-1-1 address pipeline. Each build job covers one state or province
(`registry/jobs.toml`, 65 jobs) and writes one **Package** per county or census division. The California
prototype is `COF-RyLopez/ng911-pipeline` (ADR 0008).

## Layout

- `registry/jobs.toml` every job; `enabled = true` jobs run in CI. `registry/<country>/<code>.toml` a job's
  911 authorities (opt-in, domain) and Source agencies (OpenAddresses source, ID field, license status,
  sharing-path status). Edited by hand, and statuses change only after the agency confirms (ADR 0004, 0005).
- `src/open_ng911/build.py` one job end to end; `python -m open_ng911.build --job us-vt`. `LIVE_LOADERS` maps
  each input table to `loader(c, job, jurisdiction, work_dir)`; tests pass fixture loaders instead.
- `registry.py` jobs, jurisdictions and `COUNTRIES`: everything that differs between the US and Canada.
- `sources/` one table each (the table list is in `sources/__init__.py`): boundaries from `tiger.py` or
  `statcan.py`, agency points through the OpenAddresses registry (`openaddresses.py`, `arcgis.py`), government
  roads and TIGER ADDRFEAT (`centerlines.py`), Overture addresses and road-segment IDs (`overture.py`).
- `boundaries.py` the A2Polygon and A3Polygon layers and every address point's A3 (ADR 0009).
- `roads.py` the RoadCenterline layer: Package assignment, TIGER fallback, GERS crosswalk, NENA fields (ADR 0010).
- `upstream.py` where government roads and Overture / TIGER disagree; `odbl_inventory.py` which government
  sources could stand in for Overture's ODbL themes (docs/standards/upstream-path.md).
- `street.py` street parse + `street_key` (both sides of every match use it), `nena/` registry words and the
  vendored NENA-STA-006.3 and CLDXF-CA domains, `matcher.py` Record ↔ Overture pairing, `ids.py` Address UID
  and NGUID, `lineage.py` the ledger that carries UIDs across Overture releases, `package.py` writes every
  Package and its manifest (each layer module returns its section), `db.py` the connection and shared SQL
  helpers (`case`, `quote`, `rows`, `gate`).
- `tests/` run offline on fixtures (`tests/vt_fixtures.py`, `tests/pe_fixtures.py`); only `-m live` tests
  touch the network.

## Rules

- **One pipeline.** This is meant to be a reference pipeline others (Overture) can adopt, so keep it one code
  path: a new state is a registry file, a new country is a `registry.COUNTRIES` row plus a boundary module, a
  new layer is one module that returns its manifest section to `package.write`. No per-state or per-country
  copies of a step, no second helper for something `db.py` or `arcgis.py` already does.
- **Keep every addressed site.** A NENA SSAP is any addressed site: public phones, call boxes, towers and
  un-numbered sites on a named road all stay. A point is dropped only for a reason `openaddresses.create_agency_addr`
  names (no geometry, not a point, no street, a true duplicate, outside every Package, or the registry's
  `exclude_site_types`), and every drop is counted in job.json `agency_points_dropped`.
- **Records win** (ADR 0001): an agency point is a Record; Overture fills in only as `gap_fill_candidate`.
- **NGUIDs come from the Address UID, never a GERS ID** (ADR 0002). Changing `ids.NAMESPACE` or the UID
  recipe changes every published NGUID: don't.
- **No real agency domain until opt-in** (ADR 0003, 0004). Non-opted-in Packages use
  `<package>.unclaimed.invalid`. Never invent ESN, MSAG names or an agency domain.
- **No OSM geometry or names in core layers.** Read only Overture's addresses theme here; Overture
  transportation, buildings, divisions and base are ODbL. The one exception is `overture_segment`, read only to
  attach GERS IDs to government roads (ADR 0010): nothing but the ID and overlap numbers leaves that table. The Review layer is private per opted-in agency (ADR 0007).
- **Unclear licences go in the tracker** (`registry/remediation/requests.toml`, `docs/license-remediation.md`),
  never into a guess. Agents don't contact agencies; a person does.
- **Licenses**: a source with `license_status = "unknown"` never goes into anything public, including CI
  artifacts (CI uploads only `job.json` and manifests).
- **Fix open data on our side**: OpenAddresses conform maps fields, it doesn't rewrite values; value fixes go
  in `street.py`.
- NENA output is NENA-STA-006.3-2026: lower-cased field names, registry words ("Avenue", "North").
  Canada uses the same fields with CLDXF-CA values (ADR 0006): `nena.install(c, "CA")` adds Canada's English and
  French street types (`nena/cldxf_ca_domains.json`) and French pre types ('Rue', 'Chemin'), and every Canadian
  Package's `domains.json` carries CLDXF-CA's domains beside NENA's. The CLDXF-CA lists were compiled by hand:
  check them against the published text before an opted-in hand-off.

## Running things

- Python 3.12+, `uv pip install -e ".[dev]"`, then `ruff check src tests && pytest -q -m "not live"`.
  `pytest -m live` checks outside sources (CI's build job runs it).
- A centerline layer OpenAddresses doesn't list yet goes in the registry as `oa_entry`, in OpenAddresses' own
  schema, so it can be proposed upstream unchanged.
- Overture release: `$OVERTURE_RELEASE` or the newest (STAC, then the S3 listing). Pin one to reproduce a
  build. Overture is read anonymously (`db.connect` sets an empty S3 secret, so AWS credentials in the
  environment don't break it).
- Government endpoints (TIGERweb, state ArcGIS services) are sometimes down for minutes; `sources/arcgis.py`
  retries with backoff. A second CI failure naming the same outside host is real.

## DuckDB 2.0 gotchas

- `SET geometry_always_xy = true` (done in `db.connect`). Relations have no `fetchone()`: use
  `.fetchall()[0]`. Lambdas are `lambda x: ...`. `ST_MakeValid` before unions of nested polygons.
- No pandas: read results with `cursor.description` + `fetchall()`.
- Macros expand inline: nest `nena_pretype_raw(parse_street(...))` in one expression and the query can take
  minutes to bind. Compute one step per CTE or table, as `build.assemble_ssap` does.
