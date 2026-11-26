"""
The other NENA layers, read straight from a Source agency's own endpoint (the registry's `endpoint`: OpenAddresses
doesn't catalogue these layers):

    psap, police, fire, ems   PsapPolygon, PolicePolygon, FirePolygon, EmsPolygon (Required)
    provisioning              ProvisioningPolygon (Required). A Package no provisioning Source covers gets its own
                              area: it is what the Package's data covers, and the Packages tile the job
    distance_markers          DistanceMarkerPoint
    location_markers          LocationMarkerPoint

A Source keeps its own fields through its registry `nena` table (fieldmap.py), like every layer. Polygons are cut
to each Package they reach (a fire district across a county line is in both Packages, one feature in each), and a
Source with `dissolve` is first merged into one polygon per value of that field: Vermont's emergency service zones
name each zone's fire, law and EMS agency, so one zone layer feeds three layers. Every feature's NGUID is built
from its UID under the Package's domain, like the other layers (ADR 0002, 0003).

What stays the agency's (ADR 0004): Agency_ID, ServiceURI and AVcard_URI are filled only where the Source publishes
them; a service layer's ServiceURN, where the Source has none, is the one NENA's domain gives that layer.

Package files, only for layers with features: psap_polygon.parquet, police_polygon.parquet, fire_polygon.parquet,
ems_polygon.parquet, provisioning_polygon.parquet, distance_marker_point.parquet, location_marker_point.parquet, and
a `nena_layers` manifest section.
"""
import os

from . import db, fieldmap, ids, nena, registry
from .sources import arcgis

# registry layer key -> table / file name
TABLE = {"psap": "psap_polygon", "police": "police_polygon", "fire": "fire_polygon", "ems": "ems_polygon",
         "provisioning": "provisioning_polygon", "distance_markers": "distance_marker_point",
         "location_markers": "location_marker_point"}
POINTS = ("distance_markers", "location_markers")
# NENA's ServiceURN domains (ServiceURNSOS, ServiceURNResponder) for each service layer
SERVICE_URN = {"psap": "urn:emergency:service:sos.psap", "police": "urn:emergency:service:responder.police",
               "fire": "urn:emergency:service:responder.fire", "ems": "urn:emergency:service:responder.ems"}
COMMON_DERIVED = {
    "discrpagid": "the Package's NGUID domain (a placeholder until the authority opts in, ADR 0003)",
    "dateupdate": "build time, where the Source maps no edit date",
    "nguid": "feature UID under the Package's domain (ADR 0002)",
}


def derived(key):
    """How the pipeline fills a field of this layer no Source maps (the coverage report's `derived`)."""
    out = dict(COMMON_DERIVED)
    if key in SERVICE_URN:
        out["serviceurn"] = f"NENA's URN for the layer ({SERVICE_URN[key]})"
    return out


def nena_layer(key):
    return registry.NENA_LAYER[key]


def _native_defs(key, country):
    return ", ".join(f"{fieldmap.PREFIX}{n} {fieldmap.SQL_TYPE.get(f['type'], 'VARCHAR')}"
                     for n, f in fieldmap.fields(nena_layer(key), country).items())


def create_tables(c):
    """lf_<key>(source_key, source_id, geom, n_<field> ...): every Source's features, before Packages."""
    country = fieldmap.country_of(c)
    for key in TABLE:
        c.execute(f"CREATE OR REPLACE TABLE lf_{key} (source_key VARCHAR, source_id VARCHAR, geom GEOMETRY, "
                  f"{_native_defs(key, country)})")


def insert_source(c, source, path, has_id):
    """lf_<layer> rows from an NDJSON of features (arcgis.fetch's format), merged by `dissolve` where set."""
    ids.install(c)
    key, country = source.layer, fieldmap.country_of(c)
    layer = nena_layer(key)
    raw = "".join(f", {r}" for r in fieldmap.raw_columns(source, layer, country))
    native = ", ".join(fieldmap.native_columns(source, layer, country))
    ncols = fieldmap.column_names(layer, country)
    sid = f"nullif(trim(p->>{db.quote(source.id_field)}), '')" if has_id else "NULL"
    if source.dissolve:
        sid = f"nullif(trim(p->>{db.quote(source.dissolve)}), '')"
    kinds = "('POINT')" if key in POINTS else "('POLYGON', 'MULTIPOLYGON')"
    c.execute(f"""CREATE OR REPLACE TEMP TABLE _lf AS
        WITH f AS (
            SELECT {sid} AS source_id, ST_Force2D(ST_GeomFromGeoJSON(g)) AS geom{raw}
            FROM read_json('{path}', columns = {{p: 'JSON', g: 'VARCHAR'}}))
        SELECT *, {native} FROM f WHERE ST_GeometryType(geom) IN {kinds} AND NOT ST_IsEmpty(geom)""")
    fieldmap.record(c, "_lf", source, layer, country)
    total = c.execute(f"SELECT count(*) FROM read_json('{path}', columns = {{p: 'JSON', g: 'VARCHAR'}})").fetchall()[0][0]
    if source.dissolve:
        # one polygon per value; a field that differs between the merged zones keeps its largest value
        aggs = ", ".join(f"max({n}) AS {n}" for n in ncols)
        c.execute(f"""INSERT INTO lf_{key} SELECT '{source.key}', source_id,
                          ST_Union_Agg(ST_MakeValid(geom)), {aggs}
                      FROM _lf WHERE source_id IS NOT NULL GROUP BY source_id""")
    else:
        c.execute(f"""INSERT INTO lf_{key} SELECT '{source.key}',
                          -- no ID: the feature's own geometry (stable only while it is unedited)
                          coalesce(source_id, md5(ST_AsWKB(geom)::VARCHAR)), geom, {", ".join(ncols)} FROM _lf""")
    kept = c.execute(f"SELECT count(*) FROM lf_{key} WHERE source_key = '{source.key}'").fetchall()[0][0]
    c.execute("DROP TABLE _lf")
    print(f"  [layers] {source.key}: {kept:,} {layer} features from {total:,} read"
          + (f", merged by {source.dissolve}" if source.dissolve else ""))


def load_sources(c, job, jurisdiction, work_dir):
    """Every Source of these layers in the job's registry, from its endpoint (ESRI only, like the others)."""
    create_tables(c)
    for s in jurisdiction.sources:
        if s.layer not in TABLE:
            continue
        if s.endpoint.get("protocol", "ESRI") != "ESRI":
            raise SystemExit(f"{s.key}: protocol {s.endpoint.get('protocol')!r} isn't supported yet (ESRI only)")
        url = s.endpoint["data"]
        fields = {f["name"] for f in arcgis.layer_info(url).get("fields", [])}
        has_id = bool(s.id_field) and s.id_field in fields
        if s.id_field and not has_id:
            print(f"  [WARNING] {s.key}: id_field {s.id_field!r} isn't in the layer; UIDs from geometry instead")
        path = os.path.join(work_dir, f"{s.key}.ndjson")
        arcgis.fetch(url, path, where=s.endpoint.get("where", "1=1"))
        insert_source(c, s, path, has_id)


def build(c, job, jurisdiction, updated):
    """One table per layer (TABLE), Package by Package, in NENA fields + uid, source, source_license, geoid."""
    country = job.country
    lic = {s.key: s.license_status for s in jurisdiction.sources}
    lic_case = db.case("f.source_key", lic, "NULL")
    for key, table in TABLE.items():
        layer = nena_layer(key)
        ind = nena.layer(layer)["indicator"]
        value = {"discrpagid": "d.domain", "dateupdate": f"coalesce(f.n_dateupdate, '{updated}')",
                 "nguid": f"build_nguid('{ind}', f.uid, d.domain)"}
        if key in SERVICE_URN:
            value["serviceurn"] = f"coalesce(f.n_serviceurn, '{SERVICE_URN[key]}')"
        cols = ", ".join(f"{value.get(f['name'], 'f.n_' + f['name'])} AS {f['name']}"
                         for f in nena.layer_fields(layer, country))
        if key in POINTS:
            placed = f"""SELECT l.*, p.geoid, agency_uid(l.source_key, l.source_id) AS uid, l.geom AS g
                FROM lf_{key} l JOIN package_area p ON ST_Intersects(p.geom, l.geom)
                QUALIFY row_number() OVER (PARTITION BY l.source_key, l.source_id ORDER BY p.geoid) = 1"""
        else:
            # cut to each Package; the UID names the Package too, since one source polygon can be in several
            placed = f"""SELECT * FROM (
                SELECT l.*, p.geoid, agency_uid(l.source_key, l.source_id || '|' || p.geoid) AS uid,
                       ST_CollectionExtract(ST_Intersection(ST_MakeValid(l.geom), p.geom), 3) AS g
                FROM lf_{key} l JOIN package_area p ON ST_Intersects(p.geom, l.geom)) WHERE NOT ST_IsEmpty(g)"""
        c.execute(f"""CREATE OR REPLACE TABLE {table} AS
            WITH f AS ({placed})
            SELECT f.uid, f.source_key AS source, f.source_id, {lic_case} AS source_license, {cols}, f.geoid,
                   f.g AS geom
            FROM f JOIN package_domain d USING (geoid)""")
        if key == "provisioning":
            fallback(c, job, updated, table, country)
    counts = {k: c.execute(f"SELECT count(*) FROM {t}").fetchall()[0][0] for k, t in TABLE.items()}
    print(f"[{job.id}] other NENA layers: " + ", ".join(f"{nena_layer(k)} {n:,}" for k, n in counts.items()))


def fallback(c, job, updated, table, country):
    """A provisioning polygon for every Package no provisioning Source reached: the Package's own area."""
    cols = []
    for f in nena.layer_fields("ProvisioningPolygon", country):
        n = f["name"]
        cols.append({"discrpagid": "d.domain", "dateupdate": f"'{updated}'",
                     "nguid": "build_nguid('Provisioning', agency_uid('package-area', p.geoid), d.domain)"}.get(n, "NULL")
                    + f" AS {n}")
    c.execute(f"""INSERT INTO {table} BY NAME
        SELECT agency_uid('package-area', p.geoid) AS uid, 'package-area' AS source, p.geoid AS source_id,
               'open' AS source_license, {", ".join(cols)}, p.geoid, p.geom
        FROM package_area p JOIN package_domain d USING (geoid)
        WHERE p.geoid NOT IN (SELECT geoid FROM {table})""")


def write_package(c, jurisdiction, geoid, d):
    """The layer files with features in Package folder d, and the manifest's `nena_layers` section."""
    out = {}
    for key, table in TABLE.items():
        n = c.execute(f"SELECT count(*) FROM {table} WHERE geoid = '{geoid}'").fetchall()[0][0]
        if n:
            c.execute(f"COPY (SELECT * EXCLUDE (geoid) FROM {table} WHERE geoid = '{geoid}' ORDER BY uid) TO "
                      f"'{os.path.join(d, table + '.parquet')}' (FORMAT parquet, COMPRESSION zstd)")
        srcs = [r[0] for r in c.execute(f"SELECT DISTINCT source FROM {table} WHERE geoid = '{geoid}' ORDER BY 1").fetchall()]
        by_key = {s.key: s for s in jurisdiction.sources}
        out[nena_layer(key)] = {
            "features": int(n),
            "sources": [{"key": k, "agency": by_key[k].agency, "license_status": by_key[k].license_status,
                         "attribution": by_key[k].attribution} if k in by_key else
                        {"key": k, "note": "the Package's own area: no provisioning Source covers it"} for k in srcs]}
    return out
