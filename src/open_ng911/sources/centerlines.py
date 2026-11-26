"""
Road centerlines into one table, road_seg, from two kinds of source (roads.py decides which Package gets which):

    government  a Source agency's own centerlines, read from its endpoint through the OpenAddresses source
                registry (`centerlines` layers, CC0 catalogue) or a registry `oa_entry` written in the same
                schema where OpenAddresses doesn't list the endpoint yet
    tiger       Census TIGER/Line address-range features (ADDRFEAT, public domain), one county at a time, for
                Packages no government source covers

No Overture or OpenStreetMap geometry or names come in here: Overture's transportation theme is ODbL, and roads.py
reads it only to attach GERS IDs.

Table road_seg(source_key, road_source, source_id, uid, street, from_l, to_l, from_r, to_r, zip_l, zip_r,
road_class, oneway, speed_mph, geom, geoid). road_class and oneway are NENA values (RoadClass, OneWay); street is the
full name as published, parsed later by street.py the same way as the addresses.

road_source_meta(source_key, road_source, agency, license_status, license_url, attribution, source_date, fetched,
data_url): one row per source read, for the manifests.
"""
import datetime
import os
import time
import urllib.request
import zipfile

from .. import ids
from . import arcgis, openaddresses

ROAD_SEG_COLUMNS = ("source_key VARCHAR, road_source VARCHAR, source_id VARCHAR, uid VARCHAR, street VARCHAR, "
                    "from_l INTEGER, to_l INTEGER, from_r INTEGER, to_r INTEGER, zip_l VARCHAR, zip_r VARCHAR, "
                    "road_class VARCHAR, oneway VARCHAR, speed_mph INTEGER, geom GEOMETRY, geoid VARCHAR")
INSERT = ("INSERT INTO road_seg (source_key, road_source, source_id, uid, street, from_l, to_l, from_r, to_r, zip_l, "
          "zip_r, road_class, oneway, speed_mph, geom)")
META_COLUMNS = ("source_key VARCHAR, road_source VARCHAR, agency VARCHAR, license_status VARCHAR, "
                "license_url VARCHAR, attribution VARCHAR, source_date VARCHAR, fetched VARCHAR, data_url VARCHAR")

# OpenAddresses centerline `classification` (OSM-style words) -> NENA RoadClass
OA_CLASS = {"motorway": "Primary", "trunk": "Primary", "primary": "Secondary", "secondary": "Secondary",
            "tertiary": "Local", "residential": "Local", "unclassified": "Local", "service": "Local",
            "living_street": "Local", "track": "Vehicular Trail", "path": "Walkway/Pedestrian Trail",
            "footway": "Walkway/Pedestrian Trail", "pedestrian": "Walkway/Pedestrian Trail", "steps": "Stairway"}
# TIGER MAF/TIGER Feature Class Codes -> NENA RoadClass (NENA's domain follows MTFCC)
MTFCC_CLASS = {"S1100": "Primary", "S1200": "Secondary", "S1400": "Local", "S1500": "Vehicular Trail",
               "S1630": "Ramp", "S1640": "Service Drive", "S1710": "Walkway/Pedestrian Trail", "S1720": "Stairway",
               "S1730": "Local", "S1740": "Local", "S1750": "Local", "S1780": "Local",
               "S1820": "Walkway/Pedestrian Trail", "S1830": "Walkway/Pedestrian Trail"}

TIGER_ADDRFEAT = "https://www2.census.gov/geo/tiger/TIGER{year}/ADDRFEAT/tl_{year}_{county}_addrfeat.zip"


def _now():
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _case(expr, mapping, default="NULL"):
    return f"CASE {expr} " + " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in mapping.items()) + f" ELSE {default} END"


def create_tables(c):
    c.execute(f"CREATE OR REPLACE TABLE road_seg ({ROAD_SEG_COLUMNS})")
    c.execute(f"CREATE OR REPLACE TABLE road_source_meta ({META_COLUMNS})")


def add_meta(c, row):
    c.execute("INSERT INTO road_source_meta VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
              [row.get(k) for k in ("source_key", "road_source", "agency", "license_status", "license_url",
                                    "attribution", "source_date", "fetched", "data_url")])


def _int(expr):
    """An address range end: whole numbers only, 0 meaning 'no range' as most publishers use it."""
    return f"nullif(try_cast(regexp_extract({expr}, '^[0-9]+') AS INTEGER), 0)"


def insert_government(c, source, path, conform, has_id):
    """road_seg rows from an NDJSON of features (arcgis.fetch's format) and the layer's centerline conform."""
    ids.install(c)
    cls = openaddresses.conform_sql(conform.get("classification"))
    oneway = openaddresses.conform_sql(conform.get("oneway"))
    sid = openaddresses.conform_sql(conform.get("id")) if has_id else "NULL"
    ex = source.exclude
    keep = (f"coalesce(p->>'{ex['field']}', '') NOT IN ("
            + ", ".join("'" + str(v).replace("'", "''") + "'" for v in ex["values"]) + ")") if ex else "true"
    c.execute(f"""{INSERT}
        WITH f AS (
            SELECT {sid} AS source_id,
                   {openaddresses.conform_sql(conform.get('name'))} AS street,
                   {_int(openaddresses.conform_sql(conform.get('addr_from_left')))} AS from_l,
                   {_int(openaddresses.conform_sql(conform.get('addr_to_left')))} AS to_l,
                   {_int(openaddresses.conform_sql(conform.get('addr_from_right')))} AS from_r,
                   {_int(openaddresses.conform_sql(conform.get('addr_to_right')))} AS to_r,
                   {openaddresses.conform_sql(conform.get('zip_left'))} AS zip_l,
                   {openaddresses.conform_sql(conform.get('zip_right'))} AS zip_r,
                   lower({cls}) AS cls, lower({oneway}) AS ow,
                   try_cast({openaddresses.conform_sql(conform.get('speed'))} AS DOUBLE) AS kph,
                   ST_Force2D(ST_GeomFromGeoJSON(g)) AS geom
            FROM read_json('{path}', columns = {{p: 'JSON', g: 'VARCHAR'}})
            WHERE {keep})
        SELECT '{source.key}', 'government', source_id,
               -- the agency's own segment ID makes the UID; without one, the segment's own geometry (stable
               -- only while the segment is unedited)
               agency_uid('{source.key}', coalesce(source_id, md5(ST_AsWKB(geom)::VARCHAR))),
               street, from_l, to_l, from_r, to_r, zip_l, zip_r,
               {_case('cls', OA_CLASS, "CASE WHEN cls LIKE '%\\_link' ESCAPE '\\' THEN 'Ramp' ELSE 'Local' END")},
               CASE ow WHEN 'yes' THEN 'FT' WHEN 'reverse' THEN 'TF' WHEN 'no' THEN 'B' END,
               nullif(round(kph / 1.609344), 0)::INTEGER,
               geom
        FROM f
        WHERE ST_GeometryType(geom) IN ('LINESTRING', 'MULTILINESTRING') AND NOT ST_IsEmpty(geom)""")


def load_government(c, job, jurisdiction, work_dir):
    """Every `centerlines` Source in the job's registry, from its endpoint."""
    for s in (s for s in jurisdiction.sources if s.layer == "centerlines"):
        entry = openaddresses.entry_for(s)
        if entry.get("protocol") != "ESRI":
            raise SystemExit(f"{s.key}: protocol {entry.get('protocol')!r} isn't supported yet (ESRI only)")
        conform = entry.get("conform", {})
        info = arcgis.layer_info(entry["data"])
        fields = {f["name"] for f in info.get("fields", [])}
        id_field = conform.get("id") if isinstance(conform.get("id"), str) else None
        has_id = bool(id_field) and id_field in fields
        if id_field and not has_id:
            print(f"  [WARNING] {s.key}: id field {id_field!r} isn't in the layer; UIDs from geometry instead")
        path = os.path.join(work_dir, f"{s.key}.ndjson")
        fetched = _now()
        arcgis.fetch(entry["data"], path)
        insert_government(c, s, path, conform, has_id)
        edit = (info.get("editingInfo") or {}).get("lastEditDate") or (info.get("editingInfo") or {}).get("dataLastEditDate")
        add_meta(c, {"source_key": s.key, "road_source": "government", "agency": s.agency,
                     "license_status": s.license_status, "license_url": s.license_url, "attribution": s.attribution,
                     "source_date": (datetime.datetime.fromtimestamp(edit / 1000, datetime.UTC).strftime("%Y-%m-%d")
                                     if edit else None),
                     "fetched": fetched, "data_url": entry["data"]})
        n = c.execute(f"SELECT count(*) FROM road_seg WHERE source_key = '{s.key}'").fetchall()[0][0]
        print(f"  [centerlines] {s.key}: {n:,} segments")


def insert_tiger(c, shp, vintage, into="road_seg"):
    """road_seg rows (or rows of another table with road_seg's columns) from one county's ADDRFEAT shapefile (a path
    GDAL reads: a .shp or /vsizip/...)."""
    ids.install(c)
    key = f"tiger-addrfeat-{vintage}"
    mtfcc = "coalesce(nullif(ROAD_MTFCC, ''), EDGE_MTFCC)"
    c.execute(f"""{INSERT.replace('INTO road_seg', f'INTO {into}')}
        SELECT '{key}', 'tiger', concat_ws(':', TLID, ARIDL, ARIDR),
               -- TLID (the edge) plus the address-range IDs on each side: one ADDRFEAT row each
               agency_uid('tiger-addrfeat', concat_ws(':', TLID, ARIDL, ARIDR)),
               nullif(trim(FULLNAME), ''),
               {_int('LFROMHN')}, {_int('LTOHN')}, {_int('RFROMHN')}, {_int('RTOHN')},
               nullif(ZIPL, ''), nullif(ZIPR, ''),
               {_case(mtfcc, MTFCC_CLASS, "'Local'")}, NULL, NULL,
               ST_Force2D(geom)
        FROM ST_Read('{shp}')
        WHERE {mtfcc} LIKE 'S%'""")


def _download(url, path, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": arcgis.USER_AGENT})
            with urllib.request.urlopen(req, timeout=180) as r, open(path, "wb") as f:
                f.write(r.read())
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            if i == tries - 1:
                raise
        except OSError:
            if i == tries - 1:
                raise
        time.sleep(5 * 2 ** i)


def tiger_vintages(today=None):
    """TIGER/Line years to try, newest first: this year's appears in the autumn."""
    y = (today or datetime.datetime.now(datetime.UTC).date()).year
    return [y, y - 1, y - 2]


def _tiger_vintage(counties, work_dir):
    for vintage in tiger_vintages():
        z = os.path.join(work_dir, f"tl_{vintage}_{counties[0]}_addrfeat.zip")
        if os.path.exists(z) or _download(TIGER_ADDRFEAT.format(year=vintage, county=counties[0]), z):
            return vintage
    raise SystemExit(f"No TIGER ADDRFEAT found for {counties[0]} in {tiger_vintages()}")


def _insert_counties(c, counties, vintage, work_dir, into):
    for county in counties:
        z = os.path.join(work_dir, f"tl_{vintage}_{county}_addrfeat.zip")
        if not os.path.exists(z) and not _download(TIGER_ADDRFEAT.format(year=vintage, county=county), z):
            print(f"  [WARNING] no TIGER {vintage} ADDRFEAT for {county}")
            continue
        with zipfile.ZipFile(z) as zf:
            shp = next(n for n in zf.namelist() if n.endswith(".shp"))
        insert_tiger(c, f"/vsizip/{z}/{shp}", vintage, into)


def load_tiger(c, job, jurisdiction, work_dir):
    """ADDRFEAT for every Package roads.py marked as needing the fallback (table road_fallback)."""
    counties = [g for g, in c.execute("SELECT geoid FROM road_fallback ORDER BY 1").fetchall()]
    if not counties:
        return
    vintage = _tiger_vintage(counties, work_dir)
    fetched = _now()
    _insert_counties(c, counties, vintage, work_dir, "road_seg")
    add_meta(c, {"source_key": f"tiger-addrfeat-{vintage}", "road_source": "tiger",
                 "agency": "U.S. Census Bureau (TIGER/Line address range features)", "license_status": "open",
                 "license_url": "https://www.census.gov/data/developers/about/terms-of-service.html",
                 "attribution": "U.S. Census Bureau, TIGER/Line Shapefiles", "source_date": f"TIGER/Line {vintage}",
                 "fetched": fetched, "data_url": TIGER_ADDRFEAT.format(year=vintage, county="<county>")})
    n = c.execute(f"SELECT count(*) FROM road_seg WHERE source_key = 'tiger-addrfeat-{vintage}'").fetchall()[0][0]
    print(f"  [tiger] {n:,} ADDRFEAT segments for {len(counties)} Package(s) with no government centerlines")


def create_national_table(c):
    c.execute(f"CREATE OR REPLACE TABLE national_seg ({ROAD_SEG_COLUMNS})")


def load_national_reference(c, job, jurisdiction, work_dir):
    """national_seg: the national road layer for every Package that has government roads, to count where the
    agency's network and the national one differ (upstream.py). US: TIGER ADDRFEAT. Canada: none yet (the National
    Road Network loader is still to come). Returns the layer's name and date, or None when there isn't one."""
    create_national_table(c)
    if job.country != "US":
        return None
    counties = [g for g, in c.execute("SELECT DISTINCT geoid FROM road_seg WHERE road_source = 'government' "
                                      "ORDER BY 1").fetchall()]
    if not counties:
        return None
    vintage = _tiger_vintage(counties, work_dir)
    _insert_counties(c, counties, vintage, work_dir, "national_seg")
    n = c.execute("SELECT count(*) FROM national_seg").fetchall()[0][0]
    print(f"  [tiger] {n:,} ADDRFEAT segments read to compare with {len(counties)} Package(s) of government roads")
    return {"layer": "TIGER/Line ADDRFEAT", "date": f"TIGER/Line {vintage}"}
