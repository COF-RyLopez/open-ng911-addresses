"""Package areas for a US job: the state's counties from Census TIGERweb (public domain)."""
import os

from . import arcgis

TIGER_COUNTIES = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1"


def load_package_area(c, job, work_dir):
    path = os.path.join(work_dir, f"tiger_counties_{job.fips}.ndjson")
    arcgis.fetch(TIGER_COUNTIES, path, where=f"STATE='{job.fips}'", out_fields="GEOID,NAME",
                 extra={"maxAllowableOffset": "0.0001"})
    c.execute(f"""CREATE OR REPLACE TABLE package_area AS
        SELECT p->>'GEOID' AS geoid, p->>'NAME' AS name,  -- 'Chittenden County', 'Orleans Parish'
               ST_MakeValid(ST_GeomFromGeoJSON(g)) AS geom
        FROM read_json('{path}', columns = {{p: 'JSON', g: 'VARCHAR'}})""")
