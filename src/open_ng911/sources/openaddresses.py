"""
A Source agency's address points, read straight from its own endpoint through the OpenAddresses source
registry (sources/<country>/<state>/<name>.json, CC0). We use OpenAddresses' catalogue of government endpoints
and its field mappings; we don't use its processed output, which is redundant with Overture.

OpenAddresses conform steps map fields, they don't rewrite values (openaddresses/openaddresses#10085): value
fixes belong in our parse (street.py), upstream PRs are for wrong field mappings or filters.

Table agency_addr(source_key, source_id, address_uid, number, street, unit, city, postcode, site_type, id_shared,
geom, n_<field> ...), and agency_dropped(source_key, reason, site_type, n): every point left out, counted by reason.
The n_ columns are the Source's own fields mapped straight to NENA fields by its registry `nena` table
(fieldmap.py); the OpenAddresses columns feed the street match and the fields a Source doesn't map.
"""
import json
import os

from .. import db, fieldmap, ids
from . import arcgis

OA_RAW = "https://raw.githubusercontent.com/openaddresses/openaddresses/master/sources/{path}.json"


def source_definition(path):
    return json.loads(arcgis.get(OA_RAW.format(path=path), timeout=60, tries=1))


def layer_entry(definition, layer, name):
    for entry in definition.get("layers", {}).get(layer, []):
        if entry.get("name") == name:
            return entry
    raise SystemExit(f"OpenAddresses source has no {layer} layer named {name!r}")


def entry_for(source):
    """The OpenAddresses layer entry a registry Source reads: its own `oa_entry` where OpenAddresses doesn't list
    the endpoint yet, else the entry named `oa_layer` in the OpenAddresses source `openaddresses`."""
    if source.oa_entry:
        return source.oa_entry
    return layer_entry(source_definition(source.openaddresses), source.layer, source.oa_layer)


def conform_sql(spec):
    """An OpenAddresses conform value as SQL over the JSON properties column p: a field name, a list of fields
    joined with spaces, or the functions `join` (fields + separator), `map` (field + mapping + else, as
    centerline conforms use for classification and oneway) and `mph_to_kph`. Anything else (regexp, prefixed
    number, ...) isn't supported yet: NULL."""
    if spec is None:
        return "NULL"
    if isinstance(spec, str):
        return f"nullif(trim(p->>{db.quote(spec)}), '')"
    if isinstance(spec, list) and all(isinstance(s, str) for s in spec):
        return "nullif(trim(concat_ws(' ', " + ", ".join(conform_sql(s) for s in spec) + ")), '')"
    fn = spec.get("function") if isinstance(spec, dict) else None
    if fn == "join" and all(isinstance(s, str) for s in spec.get("fields", [])):
        sep = db.quote(spec.get("separator", " "))
        return f"nullif(trim(concat_ws({sep}, " + ", ".join(conform_sql(s) for s in spec["fields"]) + ")), '')"
    if fn == "map" and isinstance(spec.get("field"), str):
        whens = " ".join(f"WHEN {db.quote(k)} THEN {db.quote(v)}" for k, v in spec.get("mapping", {}).items())
        default = db.quote(spec["else"]) if "else" in spec else conform_sql(spec["field"])
        return f"CASE {conform_sql(spec['field'])} {whens} ELSE {default} END" if whens else default
    if fn == "mph_to_kph" and isinstance(spec.get("field"), str):
        return f"round(try_cast({conform_sql(spec['field'])} AS DOUBLE) * 1.609344)::INTEGER::VARCHAR"
    print(f"  [openaddresses] conform {spec!r} isn't supported yet; left empty")
    return "NULL"


def create_agency_addr(c, source, path, conform, has_id, no_geometry=0):
    """agency_addr from an NDJSON of features (arcgis.fetch's format) and the layer's conform mapping.

    Every point the source publishes is kept unless it can't be an addressed site; each drop is counted by
    reason and site type in agency_dropped (job.json `agency_points_dropped`):
        no_geometry        the feature has no location (counted by the fetch)
        not_point          the geometry isn't a point
        no_street          no street name: a NENA SSAP needs at least the street (a number is optional, so
                           un-numbered sites such as call boxes on a named road stay)
        excluded_site_type the registry's exclude_site_types (only for points that aren't addressed sites)
        duplicate          the same ID, address and location published twice
    Rows that share an ID but differ (another unit, another point) are all kept; their Address UID is made
    from the ID plus the address so each stays distinct (`id_shared` in job.json).
    """
    ids.install(c)
    country = fieldmap.country_of(c)
    layer = "SiteStructureAddressPoint"
    raw = "".join(f",\n                   {r}" for r in fieldmap.raw_columns(source, layer, country))
    native = ", ".join(fieldmap.native_columns(source, layer, country))
    excluded = ", ".join(db.quote(t) for t in source.exclude_site_types) or "NULL"
    site_type = conform_sql(conform.get("addrtype"))
    sid = f"nullif(trim(p->>'{source.id_field}'), '')" if has_id else "NULL"
    c.execute(f"""CREATE OR REPLACE TABLE agency_raw AS
            SELECT {sid} AS source_id,
                   -- a house number stored as a double ('427.0', PEI) is the integer it holds
                   regexp_replace({conform_sql(conform.get('number'))}, '^([0-9]+)[.]0+$', '\\1') AS number,
                   {conform_sql(conform.get('street'))} AS street,
                   {conform_sql(conform.get('unit'))} AS unit,
                   {conform_sql(conform.get('city'))} AS city,
                   {conform_sql(conform.get('postcode'))} AS postcode,
                   upper({site_type}) AS site_type,
                   ST_GeomFromGeoJSON(g) AS geom{raw}
            FROM read_json('{path}', columns = {{p: 'JSON', g: 'VARCHAR'}})""")
    c.execute(f"""CREATE OR REPLACE TABLE agency_raw AS SELECT *, {native},
            CASE WHEN ST_GeometryType(geom) <> 'POINT' THEN 'not_point'
                 WHEN street IS NULL THEN 'no_street'
                 WHEN site_type IN ({excluded}) THEN 'excluded_site_type' END AS drop_reason,
            concat_ws('|', number, upper(street), upper(unit), round(ST_X(geom), 6), round(ST_Y(geom), 6)) AS addr_key
        FROM agency_raw""")
    c.execute(f"""CREATE OR REPLACE TABLE agency_addr AS
        WITH k AS (
            SELECT *, count(DISTINCT addr_key) OVER (PARTITION BY source_id) AS keys_per_id
            FROM agency_raw WHERE drop_reason IS NULL)
        SELECT '{source.key}' AS source_key, source_id,
               -- the agency's own ID makes the Address UID (ADR 0002); an ID shared by different addresses gets
               -- the address added; no ID, a UID from the address itself (stable only while the address is
               -- unedited) until the lineage ledger carries it
               CASE WHEN source_id IS NOT NULL AND keys_per_id = 1 THEN agency_uid('{source.key}', source_id)
                    WHEN source_id IS NOT NULL THEN agency_uid('{source.key}', source_id || '|' || addr_key)
                    ELSE agency_uid('{source.key}', addr_key) END AS address_uid,
               source_id IS NOT NULL AND keys_per_id > 1 AS id_shared,
               number, street, unit, city, postcode, site_type, geom, {", ".join(fieldmap.column_names(layer, country))}
        FROM k""")
    fieldmap.record(c, "agency_raw", source, layer, country, "drop_reason IS NULL")
    dupes = c.execute("SELECT count(*) - count(DISTINCT address_uid) FROM agency_addr").fetchall()[0][0]
    c.execute(f"""CREATE OR REPLACE TABLE agency_dropped AS
        SELECT '{source.key}' AS source_key, drop_reason AS reason, site_type, count(*) AS n
        FROM agency_raw WHERE drop_reason IS NOT NULL GROUP BY ALL""")
    if dupes:
        c.execute(f"""INSERT INTO agency_dropped
            SELECT '{source.key}', 'duplicate', site_type, count(*) FROM (SELECT site_type FROM agency_addr
                QUALIFY row_number() OVER (PARTITION BY address_uid ORDER BY source_id) > 1) GROUP BY ALL""")
        c.execute("CREATE OR REPLACE TABLE agency_addr AS SELECT * FROM agency_addr "
                  "QUALIFY row_number() OVER (PARTITION BY address_uid ORDER BY source_id) = 1")
    if no_geometry:
        c.execute(f"INSERT INTO agency_dropped VALUES ('{source.key}', 'no_geometry', NULL, {int(no_geometry)})")
    # kept for the build summary's excluded-site-type view
    c.execute("CREATE OR REPLACE TABLE agency_excluded AS SELECT source_key, site_type, n FROM agency_dropped "
              "WHERE reason = 'excluded_site_type'")
    c.execute("DROP TABLE agency_raw")
    for key, reason, st, n in c.execute("SELECT * FROM agency_dropped ORDER BY n DESC").fetchall():
        print(f"  [openaddresses] {key}: dropped {n:,} points, {reason}" + (f" ({st})" if st else ""))
    shared = c.execute("SELECT count(*) FROM agency_addr WHERE id_shared").fetchall()[0][0]
    if shared:
        print(f"  [openaddresses] {source.key}: {shared:,} points share an ID with another address; all kept")
    print(f"  [openaddresses] {source.key}: {c.execute('SELECT count(*) FROM agency_addr').fetchall()[0][0]:,} address points")


def load_agency_addr(c, job, jurisdiction, work_dir):
    sources = jurisdiction.sources_for("addresses")
    assert len(sources) == 1, "Phase 1 scaffold reads one address source per job"  # several: union per package
    s = sources[0]
    entry = entry_for(s)
    if entry.get("protocol") != "ESRI":
        raise SystemExit(f"{s.key}: protocol {entry.get('protocol')!r} isn't supported yet (ESRI only)")
    fields = {f["name"] for f in arcgis.layer_info(entry["data"]).get("fields", [])}
    has_id = bool(s.id_field) and s.id_field in fields
    if s.id_field and not has_id:
        print(f"  [WARNING] {s.key}: id_field {s.id_field!r} isn't in the layer ({sorted(fields)}); minting UIDs")
    path = os.path.join(work_dir, f"{s.key}.ndjson")
    n, total = arcgis.fetch(entry["data"], path)
    create_agency_addr(c, s, path, entry.get("conform", {}), has_id, no_geometry=total - n)
