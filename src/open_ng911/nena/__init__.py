"""
NENA-STA-006.3-2026 output: registry words for street types and directionals, and NGUIDs.

Output fields are lower-cased NENA names (st_postyp, a1, ...) with the NENA registry words ('Avenue', 'North').
Matching keys use abbreviations; the published NENA fields can't. Ported from ng911-pipeline
scripts/build_ng911_extension.py (nena_setup, NENA_TYPE, NENA_DIR, NENA_PRETYPE).
"""
import json
import os
import unicodedata

from .. import db

DOMAINS_FILE = os.path.join(os.path.dirname(__file__), "nena_sta006_3_domains.json")
# Canada's values for the same fields (ADR 0006): street types in English and French, provinces, A2 kinds
CLDXF_CA_FILE = os.path.join(os.path.dirname(__file__), "cldxf_ca_domains.json")

# Abbreviations the parse emits -> registry word; anything else is looked up in the registry itself, and a
# value in neither is left empty (and counted in the manifest) rather than guessed.
NENA_TYPE = {"ST": "Street", "AVE": "Avenue", "BLVD": "Boulevard", "RD": "Road", "DR": "Drive", "LN": "Lane",
             "WAY": "Way", "CT": "Court", "PL": "Place", "CIR": "Circle", "CV": "Cove", "HWY": "Highway",
             "PKWY": "Parkway", "TRL": "Trail", "LOOP": "Loop", "TER": "Terrace", "ALY": "Alley", "PLZ": "Plaza",
             "CRES": "Crescent", "CMN": "Common", "GLN": "Glen", "SQ": "Square", "PT": "Point", "WALK": "Walk",
             "RDG": "Ridge", "XING": "Crossing", "EXPY": "Expressway", "FWY": "Freeway", "PATH": "Path",
             "EXT": "Extension", "HL": "Hill", "HTS": "Heights", "GDNS": "Gardens", "CIRCT": "Circuit",
             "PVT": "Private"}
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
# French generics come before the name ('RUE PRINCIPALE', 'CH DU LAC'), Canadian jobs only and only when there's
# no post type, like the Spanish ones. Abbreviations are Canada Post's; the words are CLDXF-CA's (cldxf_ca_domains.json).
FRENCH_PRETYPE_ABBR = {"CH": "Chemin", "BOUL": "Boulevard", "CROIS": "Croissant", "MONTEE": "Montée", "PROM": "Promenade",
                       "TSSE": "Terrasse", "IMP": "Impasse", "RLE": "Ruelle"}

# NENA-STA-006.3 mandatory SiteStructureAddressPoint fields (the build gates on 100% fill)
SSAP_REQUIRED = ("discrpagid", "dateupdate", "nguid", "country", "a1")

# RoadCenterline: the NENA fields the build writes, and the mandatory ones it gates on (100% fill)
RCL_FIELDS = ("discrpagid", "dateupdate", "rcl_nguid", "fromaddr_l", "toaddr_l", "fromaddr_r", "toaddr_r",
              "parity_l", "parity_r", "st_predir", "st_pretyp", "st_name", "st_postyp", "st_posdir",
              "country_l", "country_r", "a1_l", "a1_r", "a2_l", "a2_r", "a3_l", "a3_r", "postcode_l",
              "postcode_r", "roadclass", "oneway", "speedlimit")
RCL_REQUIRED = ("discrpagid", "dateupdate", "rcl_nguid", "parity_l", "parity_r", "country_l", "country_r",
                "a1_l", "a1_r", "a2_l", "a2_r")


def domains():
    with open(DOMAINS_FILE) as f:
        return json.load(f)["domains"]


def cldxf_ca():
    with open(CLDXF_CA_FILE, encoding="utf-8") as f:
        return json.load(f)


def street_types(country="US"):
    """The street type registry words a job's Packages may use: NENA's, plus CLDXF-CA's in Canada."""
    words = list(domains()["StreetNameType"])
    if country == "CA":
        ca = cldxf_ca()["domains"]
        words += [w for w in ca["StreetNameTypeEnglish"] + ca["StreetNameTypeFrench"] if w not in words]
    return words


def french_pretypes():
    """Raw French pre type (upper case, with or without accents: agencies write both) -> CLDXF-CA word."""
    def plain(w):
        return "".join(ch for ch in unicodedata.normalize("NFD", w.upper()) if unicodedata.category(ch) != "Mn")
    words = {}
    for w in cldxf_ca()["domains"]["StreetNamePreTypeFrench"]:
        words[w.upper()] = words[plain(w)] = w
    return {**words, **FRENCH_PRETYPE_ABBR}


def install(c, country="US"):
    """Registry tables and macros the package layers map through (with Canada's values for a Canadian job)."""
    c.execute("CREATE OR REPLACE TABLE nena_type AS SELECT unnest(?::VARCHAR[]) AS word", [street_types(country)])
    c.execute("CREATE OR REPLACE TABLE nena_type_abbr AS SELECT * FROM (VALUES "
              + ", ".join(f"('{k}', '{v}')" for k, v in NENA_TYPE.items()) + ") t(abbr, word)")
    c.execute("""CREATE OR REPLACE MACRO nena_type_word(t) AS coalesce(
                     (SELECT word FROM nena_type_abbr WHERE abbr = upper(t)),
                     (SELECT word FROM nena_type WHERE upper(word) = upper(t)))""")
    c.execute(f"CREATE OR REPLACE MACRO nena_dir_word(d) AS {db.case('upper(d)', NENA_DIR)}")
    english = "|".join(k for k in sorted(NENA_PRETYPE, key=len, reverse=True) if k not in SPANISH_PRETYPES)
    spanish = "|".join(SPANISH_PRETYPES)
    pretypes = dict(NENA_PRETYPE)
    french_when = ""
    if country == "CA":
        fr = french_pretypes()
        french = "|".join(k for k in sorted(fr, key=len, reverse=True))
        pretypes = {**fr, **pretypes}  # 'AVENUE', 'ROUTE' keep their English reading before a number
        french_when = (f"WHEN postyp IS NULL AND regexp_matches(n, '^({french}) +[A-Z0-9]') "
                       f"THEN regexp_extract(n, '^({french}) +', 1)")
    # the pre type found at the start of a parsed street name (raw), given its post type
    c.execute(f"""CREATE OR REPLACE MACRO nena_pretype_raw(n, postyp) AS CASE
                     WHEN regexp_matches(n, '^({english}) +([0-9][0-9A-Z]*|[A-Z])$') THEN regexp_extract(n, '^({english}) +', 1)
                     WHEN postyp IS NULL AND regexp_matches(n, '^({spanish}) +[A-Z0-9]') THEN regexp_extract(n, '^({spanish}) +', 1)
                     {french_when}
                  END""")
    c.execute(f"CREATE OR REPLACE MACRO nena_pretype_word(raw) AS {db.case('upper(raw)', pretypes)}")
    c.execute("""CREATE OR REPLACE MACRO nena_st_name(n, pre_raw) AS
                     CASE WHEN pre_raw IS NULL THEN n ELSE trim(n[length(pre_raw) + 1:]) END""")
