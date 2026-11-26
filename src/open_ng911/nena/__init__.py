"""
NENA-STA-006.3-2026 output: registry words for street types and directionals, and NGUIDs.

Output fields are lower-cased NENA names (st_postyp, a1, ...) with the NENA registry words ('Avenue', 'North').
Matching keys use abbreviations; the published NENA fields can't. Ported from ng911-pipeline
scripts/build_ng911_extension.py (nena_setup, NENA_TYPE, NENA_DIR, NENA_PRETYPE).
"""
import json
import os

DOMAINS_FILE = os.path.join(os.path.dirname(__file__), "nena_sta006_3_domains.json")

# Abbreviations the parse emits -> registry word; anything else is looked up in the registry itself, and a
# value in neither is left empty (and counted in the manifest) rather than guessed.
NENA_TYPE = {"ST": "Street", "AVE": "Avenue", "BLVD": "Boulevard", "RD": "Road", "DR": "Drive", "LN": "Lane",
             "WAY": "Way", "CT": "Court", "PL": "Place", "CIR": "Circle", "CV": "Cove", "HWY": "Highway",
             "PKWY": "Parkway", "TRL": "Trail", "LOOP": "Loop", "TER": "Terrace", "ALY": "Alley", "PLZ": "Plaza",
             "CRES": "Crescent", "CMN": "Common", "GLN": "Glen", "SQ": "Square", "PT": "Point", "WALK": "Walk",
             "RDG": "Ridge", "XING": "Crossing", "EXPY": "Expressway", "FWY": "Freeway", "PATH": "Path",
             "EXT": "Extension", "HL": "Hill", "HTS": "Heights"}
NENA_DIR = {"N": "North", "S": "South", "E": "East", "W": "West",
            "NE": "Northeast", "NW": "Northwest", "SE": "Southeast", "SW": "Southwest"}
# Street name pre types ('Highway' in 'Highway 41', 'Via' in 'Via Mariposa'). The English ones only before a
# number or single letter ('AVENUE 12', 'AVENUE N'), the Spanish ones only when there's no post type, so a
# name like 'CORTE MADERA AVE' keeps its name.
NENA_PRETYPE = {"UNITED STATES HIGHWAY": "United States Highway", "US HIGHWAY": "United States Highway",
                "US HWY": "United States Highway", "US": "United States Highway", "STATE HIGHWAY": "State Highway",
                "STATE HWY": "State Highway", "STATE ROUTE": "State Route", "SR": "State Route",
                "VERMONT ROUTE": "State Route", "VT ROUTE": "State Route", "VT": "State Route",
                "COUNTY ROAD": "County Road", "CR": "County Road", "INTERSTATE": "Interstate", "I": "Interstate",
                "HIGHWAY": "Highway", "HWY": "Highway", "AVENUE": "Avenue", "AVE": "Avenue", "ROUTE": "Route",
                "RTE": "Route", "CALLE": "Calle", "CAMINO": "Camino", "VIA": "Via", "PASEO": "Paseo",
                "AVENIDA": "Avenida", "CORTE": "Corte"}
SPANISH_PRETYPES = ("CALLE", "CAMINO", "VIA", "PASEO", "AVENIDA", "CORTE")

# NENA-STA-006.3 mandatory SiteStructureAddressPoint fields (the build gates on 100% fill)
SSAP_REQUIRED = ("discrpagid", "dateupdate", "nguid", "country", "a1")


def domains():
    with open(DOMAINS_FILE) as f:
        return json.load(f)["domains"]


def _case(col, mapping):
    return "CASE upper(" + col + ") " + " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in mapping.items()) + " END"


def install(c):
    """Registry tables and macros the package layers map through."""
    c.execute("CREATE OR REPLACE TABLE nena_type AS SELECT unnest(?::VARCHAR[]) AS word", [domains()["StreetNameType"]])
    c.execute("CREATE OR REPLACE TABLE nena_type_abbr AS SELECT * FROM (VALUES "
              + ", ".join(f"('{k}', '{v}')" for k, v in NENA_TYPE.items()) + ") t(abbr, word)")
    c.execute("""CREATE OR REPLACE MACRO nena_type_word(t) AS coalesce(
                     (SELECT word FROM nena_type_abbr WHERE abbr = upper(t)),
                     (SELECT word FROM nena_type WHERE upper(word) = upper(t)))""")
    c.execute(f"CREATE OR REPLACE MACRO nena_dir_word(d) AS {_case('d', NENA_DIR)}")
    english = "|".join(k for k in sorted(NENA_PRETYPE, key=len, reverse=True) if k not in SPANISH_PRETYPES)
    spanish = "|".join(SPANISH_PRETYPES)
    # the pre type found at the start of a parsed street name (raw), given its post type
    c.execute(f"""CREATE OR REPLACE MACRO nena_pretype_raw(n, postyp) AS CASE
                     WHEN regexp_matches(n, '^({english}) +([0-9][0-9A-Z]*|[A-Z])$') THEN regexp_extract(n, '^({english}) +', 1)
                     WHEN postyp IS NULL AND regexp_matches(n, '^({spanish}) +[A-Z0-9]') THEN regexp_extract(n, '^({spanish}) +', 1)
                  END""")
    c.execute(f"CREATE OR REPLACE MACRO nena_pretype_word(raw) AS {_case('raw', NENA_PRETYPE)}")
    c.execute("""CREATE OR REPLACE MACRO nena_st_name(n, pre_raw) AS
                     CASE WHEN pre_raw IS NULL THEN n ELSE trim(n[length(pre_raw) + 1:]) END""")
