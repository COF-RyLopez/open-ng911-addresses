"""
Overture addresses inside the job's Packages, read anonymously from Overture's S3 bucket for the release
overture_release.py resolves. Only the addresses theme: Overture's transportation, buildings, divisions and base
themes are ODbL and stay out of a Package's core layers.

Table overture_addr(gers_id, number, street, unit, postcode, postal_city, source_dataset, source_record_id, source_license,
geom, geoid).
"""
from .. import overture_release


def create_overture_addr(c, parquet):
    """overture_addr from Overture address parquet (S3 glob or a local fixture) and the package_area table."""
    xmin, ymin, xmax, ymax = c.execute(
        "SELECT min(ST_XMin(geom)), min(ST_YMin(geom)), max(ST_XMax(geom)), max(ST_YMax(geom)) FROM package_area"
    ).fetchall()[0]
    c.execute(f"""CREATE OR REPLACE TABLE overture_addr AS
        WITH o AS (
            SELECT id AS gers_id, nullif(trim(number), '') AS number, nullif(trim(street), '') AS street,
                   nullif(trim(unit), '') AS unit, nullif(trim(postcode), '') AS postcode,
                   coalesce(nullif(trim(postal_city), ''), address_levels[2].value) AS postal_city,
                   sources[1].dataset AS source_dataset, sources[1].record_id AS source_record_id,
                   sources[1].license AS source_license,
                   geometry AS geom
            FROM read_parquet('{parquet}', hive_partitioning = 1)
            WHERE bbox.xmin >= {xmin} AND bbox.xmax <= {xmax} AND bbox.ymin >= {ymin} AND bbox.ymax <= {ymax})
        SELECT o.*, a.geoid FROM o JOIN package_area a ON ST_Intersects(a.geom, o.geom)
        WHERE o.number IS NOT NULL
        QUALIFY row_number() OVER (PARTITION BY o.gers_id ORDER BY a.geoid) = 1""")
    print(f"  [overture] {c.execute('SELECT count(*) FROM overture_addr').fetchall()[0][0]:,} addresses in the job's packages")


def load_overture_addr(c, jurisdiction, work_dir):
    create_overture_addr(c, overture_release.addresses_glob())


def create_overture_segment(c, parquet):
    """overture_segment(gers_id, name, class, subclass, geom): Overture road segments over the job's Packages, read
    only to attach their GERS IDs to government geometry (roads.py) and to count where the two disagree
    (upstream.py). Their geometry and names are ODbL (OpenStreetMap): nothing from this table but the ID and counts
    goes into a Package, and the table isn't written anywhere."""
    xmin, ymin, xmax, ymax = c.execute(
        "SELECT min(ST_XMin(geom)), min(ST_YMin(geom)), max(ST_XMax(geom)), max(ST_YMax(geom)) FROM package_area"
    ).fetchall()[0]
    c.execute(f"""CREATE OR REPLACE TABLE overture_segment AS
        SELECT id AS gers_id, names.primary AS name, class, subclass, geometry AS geom
        FROM read_parquet('{parquet}', hive_partitioning = 1)
        WHERE subtype = 'road'
          AND bbox.xmax >= {xmin} AND bbox.xmin <= {xmax} AND bbox.ymax >= {ymin} AND bbox.ymin <= {ymax}""")
    print(f"  [overture] {c.execute('SELECT count(*) FROM overture_segment').fetchall()[0][0]:,} road segments "
          "(GERS IDs only)")


def load_overture_segment(c, jurisdiction, work_dir):
    create_overture_segment(c, overture_release.segments_glob())
