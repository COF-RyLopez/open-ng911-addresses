"""
A Source agency's address points, read straight from its own endpoint through the OpenAddresses source
registry (sources/<country>/<state>/<name>.json, CC0). We use OpenAddresses' catalogue of government endpoints
and its field mappings; we don't use its processed output, which is redundant with Overture.

OpenAddresses conform steps map fields, they don't rewrite values (openaddresses/openaddresses#10085): value
fixes belong in our parse (street.py), upstream PRs are for wrong field mappings or filters.

Table agency_addr(source_key, source_id, address_uid, number, street, unit, city, postcode, geom).
"""
import json
import os
import urllib.request

from .. import ids
from . import arcgis

OA_RAW = "https://raw.githubusercontent.com/openaddresses/openaddresses/master/sources/{path}.json"


def source_definition(path):
    req = urllib.request.Request(OA_RAW.format(path=path), headers={"User-Agent": arcgis.USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def layer_entry(definition, layer, name):
    for entry in definition.get("layers", {}).get(layer, []):
        if entry.get("name") == name:
            return entry
    raise SystemExit(f"OpenAddresses source has no {layer} layer named {name!r}")


def conform_sql(spec):
    """An OpenAddresses conform value (a field name, or a list of fields joined with spaces) as SQL over the
    JSON properties column p. Anything else (functions like regexp or join) isn't supported yet: NULL."""
    if spec is None:
        return "NULL"
    if isinstance(spec, str):
        return f"nullif(trim(p->>'{spec}'), '')"
    if isinstance(spec, list) and all(isinstance(s, str) for s in spec):
        return "nullif(trim(concat_ws(' ', " + ", ".join(f"nullif(trim(p->>'{s}'), '')" for s in spec) + ")), '')"
    print(f"  [openaddresses] conform {spec!r} isn't supported yet; left empty")
    return "NULL"


def create_agency_addr(c, source, path, conform, has_id):
    """agency_addr from an NDJSON of features (arcgis.fetch's format) and the layer's conform mapping."""
    ids.install(c)
    excluded = ", ".join("'" + t.replace("'", "''") + "'" for t in source.exclude_site_types) or "NULL"
    site_type = conform_sql(conform.get("addrtype"))
    sid = f"nullif(trim(p->>'{source.id_field}'), '')" if has_id else "NULL"
    c.execute(f"""CREATE OR REPLACE TABLE agency_raw AS
            SELECT {sid} AS source_id,
                   {conform_sql(conform.get('number'))} AS number,
                   {conform_sql(conform.get('street'))} AS street,
                   {conform_sql(conform.get('unit'))} AS unit,
                   {conform_sql(conform.get('city'))} AS city,
                   {conform_sql(conform.get('postcode'))} AS postcode,
                   upper({site_type}) AS site_type,
                   ST_GeomFromGeoJSON(g) AS geom
            FROM read_json('{path}', columns = {{p: 'JSON', g: 'VARCHAR'}})""")
    # Points the registry's exclude_site_types drops (public phones, call boxes...), counted for job.json
    c.execute(f"""CREATE OR REPLACE TABLE agency_excluded AS
        SELECT '{source.key}' AS source_key, site_type, count(*) AS n FROM agency_raw
        WHERE site_type IN ({excluded}) GROUP BY ALL""")
    c.execute(f"""CREATE OR REPLACE TABLE agency_addr AS
        SELECT '{source.key}' AS source_key, source_id,
               -- the agency's own ID makes the Address UID (ADR 0002); without one, a UID from the address
               -- itself (stable only while the address is unedited) until the lineage ledger carries it
               CASE WHEN source_id IS NOT NULL THEN agency_uid('{source.key}', source_id)
                    ELSE agency_uid('{source.key}', concat_ws('|', number, upper(street), upper(unit),
                                    round(ST_X(geom), 6), round(ST_Y(geom), 6))) END AS address_uid,
               number, street, unit, city, postcode, site_type, geom
        FROM agency_raw
        WHERE number IS NOT NULL AND street IS NOT NULL AND ST_GeometryType(geom) = 'POINT'
          AND (site_type IS NULL OR site_type NOT IN ({excluded}))""")
    c.execute("DROP TABLE agency_raw")
    for key, site_type, n in c.execute("SELECT * FROM agency_excluded ORDER BY n DESC").fetchall():
        print(f"  [openaddresses] {key}: dropped {n:,} {site_type} points (exclude_site_types)")
    n, distinct_ids = c.execute("SELECT count(*), count(DISTINCT address_uid) FROM agency_addr").fetchall()[0]
    if n != distinct_ids:
        print(f"  [openaddresses] {source.key}: {n - distinct_ids:,} rows share an Address UID; keeping one each")
        c.execute("CREATE OR REPLACE TABLE agency_addr AS SELECT * FROM agency_addr "
                  "QUALIFY row_number() OVER (PARTITION BY address_uid ORDER BY source_id) = 1")
    print(f"  [openaddresses] {source.key}: {c.execute('SELECT count(*) FROM agency_addr').fetchall()[0][0]:,} address points")


def load_agency_addr(c, jurisdiction, work_dir):
    sources = [s for s in jurisdiction.sources if s.layer == "addresses"]
    assert len(sources) == 1, "Phase 1 scaffold reads one address source per job"  # several: union per package
    s = sources[0]
    entry = layer_entry(source_definition(s.openaddresses), "addresses", s.oa_layer)
    if entry.get("protocol") != "ESRI":
        raise SystemExit(f"{s.key}: protocol {entry.get('protocol')!r} isn't supported yet (ESRI only)")
    fields = {f["name"] for f in arcgis.layer_info(entry["data"]).get("fields", [])}
    has_id = bool(s.id_field) and s.id_field in fields
    if s.id_field and not has_id:
        print(f"  [WARNING] {s.key}: id_field {s.id_field!r} isn't in the layer ({sorted(fields)}); minting UIDs")
    path = os.path.join(work_dir, f"{s.key}.ndjson")
    arcgis.fetch(entry["data"], path)
    create_agency_addr(c, s, path, entry.get("conform", {}), has_id)
