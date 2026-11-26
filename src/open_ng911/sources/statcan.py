"""
Package areas and municipalities for a Canadian job, from Statistics Canada's 2021 Census digital boundary files
(Statistics Canada Open Licence), read from StatCan's own ArcGIS service (ADR 0006). The digital files, not the
cartographic ones: they run out into the water rather than stopping at the shoreline, so a civic address on a
wharf or a small island still falls inside its census division.

    package_area   one row per census division (CDUID, e.g. '1102' Queens): the Package
    municipality   one row per census subdivision (CSDUID, e.g. '1102075' Charlottetown): the A3 unit

The service stores Statistics Canada Lambert (EPSG:3347); arcgis.fetch asks for WGS84.
"""
import os

from . import arcgis

SERVICE = "https://geo.statcan.gc.ca/geo_wa/rest/services/2021/Digital_boundary_files/MapServer"
CENSUS_DIVISIONS = f"{SERVICE}/4"     # lcd_000a21s_e: CDUID, CDNAME, CDTYPE, PRUID
CENSUS_SUBDIVISIONS = f"{SERVICE}/9"  # lcsd000a21s_e: CSDUID, CSDNAME, CSDTYPE, PRUID

# Census subdivision types (StatCan, Census of Population 2021, "CSD type"). False: not a local government,
# so its addresses get A3 = 'Unincorporated' (unorganized areas, reserves, settlements, PEI fire districts).
CSD_TYPES = {
    "C": ("City / Cité", True), "CC": ("Chartered community", True), "CG": ("Community government", True),
    "CN": ("Crown colony / Colonie de la couronne", False), "COM": ("Community", True), "CT": ("Canton", True),
    "CU": ("Cantons unis", True), "CV": ("City / Ville", True), "CY": ("City", True), "DM": ("District municipality", True),
    "FD": ("Fire district", False), "HAM": ("Hamlet", True), "ID": ("Improvement district", True),
    "IGD": ("Indian government district", True), "IM": ("Island municipality", True),
    "IRI": ("Indian reserve / Réserve indienne", False), "LGD": ("Local government district", True),
    "LOT": ("Township and royalty", False), "M": ("Municipality / Municipalité", True), "MD": ("Municipal district", True),
    "MÉ": ("Municipalité", True), "MU": ("Municipality", True), "NH": ("Northern hamlet", True),
    "NL": ("Nisga'a land", False), "NO": ("Unorganized / Non organisé", False), "NV": ("Northern village", True),
    "P": ("Parish / Paroisse (municipalité de)", True), "PE": ("Paroisse (municipalité de)", True),
    "RCR": ("Rural community / Communauté rurale", True), "RDA": ("Regional district electoral area", False),
    "RG": ("Region", True), "RGM": ("Regional municipality", True), "RM": ("Rural municipality", True),
    "RMU": ("Resort municipality", True), "RV": ("Resort village", True), "S-É": ("Indian settlement", False),
    "SA": ("Special area", False), "SC": ("Subdivision of county municipality", False),
    "SÉ": ("Settlement / Établissement", False), "SET": ("Settlement", False), "SG": ("Self-government", True),
    "SM": ("Specialized municipality", True), "SNO": ("Subdivision of unorganized", False),
    "SV": ("Summer village", True), "T": ("Town", True), "TC": ("Terres réservées aux Cris", False),
    "TI": ("Terre inuite", False), "TK": ("Terres réservées aux Naskapis", False), "TL": ("Teslin land", False),
    "TP": ("Township", True), "TV": ("Town / Ville", True), "V": ("Ville", True), "VC": ("Village cri", True),
    "VK": ("Village naskapi", True), "VL": ("Village", True), "VN": ("Village nordique", True),
}


def load_package_area(c, job, work_dir):
    """package_area(geoid, name, geom): the province's census divisions, geoid = CDUID."""
    path = os.path.join(work_dir, f"statcan_cd_{job.fips}.ndjson")
    arcgis.fetch(CENSUS_DIVISIONS, path, where=f"PRUID='{job.fips}'", out_fields="CDUID,CDNAME,CDTYPE",
                 extra={"maxAllowableOffset": "0.00001"})
    c.execute(f"""CREATE OR REPLACE TABLE package_area AS
        SELECT p->>'CDUID' AS geoid, p->>'CDNAME' AS name,  -- 'Queens' (CTY), 'Halifax' (CTY), 'Ottawa' (CDR)
               ST_MakeValid(ST_GeomFromGeoJSON(g)) AS geom
        FROM read_json('{path}', columns = {{p: 'JSON', g: 'VARCHAR'}})""")


def create_municipality(c, path):
    """municipality(geoid, name, kind, incorporated, geom) from an NDJSON of CSD features (arcgis.fetch's format)."""
    incorporated = ", ".join(f"'{k}'" for k, (_, inc) in CSD_TYPES.items() if inc)
    c.execute(f"""CREATE OR REPLACE TABLE municipality AS
        SELECT p->>'CSDUID' AS geoid, p->>'CSDNAME' AS name, p->>'CSDTYPE' AS kind,
               (p->>'CSDTYPE') IN ({incorporated}) AS incorporated,
               ST_MakeValid(ST_GeomFromGeoJSON(g)) AS geom
        FROM read_json('{path}', columns = {{p: 'JSON', g: 'VARCHAR'}})""")


def load_municipality(c, job, work_dir):
    """The province's census subdivisions (each CSD is a municipality in CLDXF-CA's A3)."""
    path = os.path.join(work_dir, f"statcan_csd_{job.fips}.ndjson")
    arcgis.fetch(CENSUS_SUBDIVISIONS, path, where=f"PRUID='{job.fips}'", out_fields="CSDUID,CSDNAME,CSDTYPE",
                 extra={"maxAllowableOffset": "0.00001"})
    create_municipality(c, path)
