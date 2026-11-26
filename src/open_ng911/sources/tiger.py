"""
Census TIGERweb boundaries for a US job (public domain, a work of the US Government): the state's counties
as Package areas, and its municipalities for A3.

Table package_area(geoid, name, geom): counties, 'Chittenden County'.
Table municipality(geoid, name, kind, incorporated, geom): the A3 units (boundaries.py reads it).

Which TIGER unit is A3 depends on the state. In the 12 "strong MCD" states, the county subdivision (town,
township) is the general-purpose local government and covers the whole state, so it is A3: Vermont's towns,
not the villages inside them. A city there that is independent of any town is an incorporated place whose
county subdivision is only a fictitious stand-in (FUNCSTAT F), so places outside every active county
subdivision are A3 too (Burlington, Rutland). Everywhere else A3 is the incorporated place; an address in no
place is 'Unincorporated'. Census designated places are statistical (they're A4 material), never A3.
"""
import os

from . import arcgis

TIGERWEB = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb"
TIGER_COUNTIES = f"{TIGERWEB}/State_County/MapServer/1"
TIGER_SUBDIVISIONS = f"{TIGERWEB}/Places_CouSub_ConCity_SubMCD/MapServer"
# Layer names in TIGER_SUBDIVISIONS; looked up by name, since the layer ids have moved between vintages
COUSUB_LAYER, PLACE_LAYER = "County Subdivisions", "Incorporated Places"

# States where county subdivisions are functioning general-purpose governments (Census, "strong MCD" states)
STRONG_MCD_STATES = {"CT", "ME", "MA", "MI", "MN", "NH", "NJ", "NY", "PA", "RI", "VT", "WI"}
# Census FUNCSTAT codes for an active government: A active, B partially consolidated, C consolidated,
# G subordinate to another unit. F fictitious, I inactive, N nonfunctioning and S statistical are not.
ACTIVE_FUNCSTAT = ("A", "B", "C", "G")

# Boundaries are fetched generalized to about 1 m, so counties and the municipalities inside them line up
GENERALIZE = {"maxAllowableOffset": "0.00001"}


def load_package_area(c, job, work_dir):
    path = os.path.join(work_dir, f"tiger_counties_{job.fips}.ndjson")
    arcgis.fetch(TIGER_COUNTIES, path, where=f"STATE='{job.fips}'", out_fields="GEOID,NAME", extra=GENERALIZE)
    c.execute(f"""CREATE OR REPLACE TABLE package_area AS
        SELECT p->>'GEOID' AS geoid, p->>'NAME' AS name,  -- 'Chittenden County', 'Orleans Parish'
               ST_MakeValid(ST_GeomFromGeoJSON(g)) AS geom
        FROM read_json('{path}', columns = {{p: 'JSON', g: 'VARCHAR'}})""")


def municipality_layer(job):
    return COUSUB_LAYER if job.code in STRONG_MCD_STATES else PLACE_LAYER


def layer_url(name):
    for layer in arcgis.layer_info(TIGER_SUBDIVISIONS).get("layers", []):
        if layer.get("name") == name:
            return f"{TIGER_SUBDIVISIONS}/{layer['id']}"
    raise SystemExit(f"TIGERweb has no layer named {name!r} in {TIGER_SUBDIVISIONS}")


def create_municipality(c, path, kind_layer):
    """municipality from TIGERweb features (one {"p", "g"} per line, as arcgis.fetch writes them)."""
    active = ", ".join(f"'{s}'" for s in ACTIVE_FUNCSTAT)
    c.execute(f"""CREATE OR REPLACE TABLE municipality AS
        SELECT p->>'GEOID' AS geoid,
               coalesce(p->>'BASENAME', p->>'NAME') AS name,  -- 'Burlington'; NAME is 'Burlington city'
               coalesce(nullif(trim(replace(p->>'NAME', coalesce(p->>'BASENAME', ''), '')), ''),
                        '{kind_layer}') AS kind,             -- 'city', 'town', 'village', 'borough'
               coalesce(p->>'FUNCSTAT' IN ({active}), false) AS incorporated,
               ST_MakeValid(ST_GeomFromGeoJSON(g)) AS geom
        FROM read_json('{path}', columns = {{p: 'JSON', g: 'VARCHAR'}})""")


def fetch_layer(name, job, work_dir):
    path = os.path.join(work_dir, f"tiger_{name.lower().replace(' ', '_')}_{job.fips}.ndjson")
    arcgis.fetch(layer_url(name), path, where=f"STATE='{job.fips}'", out_fields="GEOID,NAME,BASENAME,FUNCSTAT",
                 extra=GENERALIZE)
    return path


def add_independent_places(c, places_path):
    """Strong MCD states: add the active incorporated places that lie in no active county subdivision
    (independent cities); villages and boroughs inside an active town stay out."""
    c.execute("ALTER TABLE municipality RENAME TO cousub")
    create_municipality(c, places_path, "place")
    c.execute("""CREATE OR REPLACE TABLE municipality AS
        SELECT * FROM cousub
        UNION ALL
        SELECT p.* FROM municipality p
        WHERE p.incorporated AND NOT EXISTS (
            SELECT 1 FROM cousub m WHERE m.incorporated AND ST_Intersects(m.geom, ST_PointOnSurface(p.geom)))""")
    c.execute("DROP TABLE cousub")


def load_municipality(c, job, work_dir):
    name = municipality_layer(job)
    create_municipality(c, fetch_layer(name, job, work_dir), "county subdivision" if name == COUSUB_LAYER else "place")
    if name == COUSUB_LAYER:
        add_independent_places(c, fetch_layer(PLACE_LAYER, job, work_dir))
    for kind, incorporated, n, names in c.execute("""SELECT kind, incorporated, count(*), string_agg(name, ', ' ORDER BY name)
            FROM municipality GROUP BY ALL ORDER BY 2 DESC, 3 DESC""").fetchall():
        print(f"  [tiger] municipalities: {n:,} {kind}{'' if incorporated else ' (not a government)'}"
              + ("" if incorporated and n > 20 else f": {names}"))
