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
# Every layer's fields and the coded domains, from NENA's schema (scripts/nena_layer_reference.py writes it)
FIELDS_FILE = os.path.join(os.path.dirname(__file__), "nena_sta006_3_fields.json")
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

# US secondary unit designators (USPS Publication 28) -> the word CLDXF-US writes in UnitPreTyp ('APT 4B' ->
# 'Apartment' + '4B'). A unit with no designator ('4B', '#4') keeps an empty UnitPreTyp rather than a guessed one.
UNIT_TYPES = {"APT": "Apartment", "APARTMENT": "Apartment", "STE": "Suite", "SUITE": "Suite", "UNIT": "Unit",
              "RM": "Room", "ROOM": "Room", "FL": "Floor", "FLR": "Floor", "FLOOR": "Floor", "BLDG": "Building",
              "BUILDING": "Building", "LOT": "Lot", "SPC": "Space", "SPACE": "Space", "TRLR": "Trailer",
              "TRAILER": "Trailer", "DEPT": "Department", "OFC": "Office", "OFFICE": "Office", "HNGR": "Hangar",
              "PH": "Penthouse", "SLIP": "Slip", "PIER": "Pier", "BSMT": "Basement", "FRNT": "Front",
              "LBBY": "Lobby", "LOWR": "Lower", "UPPR": "Upper", "REAR": "Rear", "SIDE": "Side"}

# The gate (build.gate): every NENA-STA-006.3 Required field of every built layer, from the schema's own flags,
# except the two kinds no build can promise. Those are reported, never gated (job.json `nena_required_gaps`):
#   AGENCY_OWNED  only the 911 authority can fill them; never ours to make up (ADR 0004)
#   FROM_DATA     only the Source's data has them: an unnamed road, a zone with no display name, a marker with
#                 no route; left empty and counted, never guessed (AGENTS.md)
AGENCY_OWNED = ("agency_id", "serviceuri", "avcard_uri")
FROM_DATA = ("st_name", "dsplayname", "dm_unit", "dm_value", "dm_rte", "dm_ind", "lm_label", "lm_ind")


def domains():
    """NENA's value domains: the registry lists (street types, directionals ...) and the schema's coded domains
    (Place_Type, service URNs, marker indicators ...)."""
    with open(DOMAINS_FILE) as f:
        d = json.load(f)["domains"]
    return {**schema()["domains"], **d}


_SCHEMA = {}


def schema():
    if not _SCHEMA:
        with open(FIELDS_FILE) as f:
            _SCHEMA.update(json.load(f))
    return _SCHEMA


def layer(name):
    """One NENA layer from the schema: indicator, level, geometry, removed fields per country, fields."""
    return schema()["layers"][name]


def layer_fields(name, country="US"):
    """The fields a layer has in one country (CLDXF-US drops Unit and AddCode, CLDXF-CA drops UnitPreTyp,
    UnitValue and PostCodeEx), each {name, nena, type, length, required, domain}, in NENA's order. The
    RoadCenterline NGUID is written as rcl_nguid."""
    lyr = layer(name)
    removed = set(lyr["removed"].get(country, []))
    out = []
    for f in lyr["fields"]:
        if f["name"] in removed:
            continue
        if name == "RoadCenterLine" and f["name"] == "nguid":
            f = {**f, "name": "rcl_nguid"}
        out.append(f)
    return out


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
    # a US unit as UnitPreTyp + UnitValue: 'APT 4B', 'Apt. 4B', 'Apartment #4B' -> Apartment, 4B; '#4' -> NULL, 4
    units = "|".join(sorted(UNIT_TYPES, key=len, reverse=True))
    c.execute(f"""CREATE OR REPLACE MACRO nena_unit_type(u) AS
                     {db.case(f"regexp_extract(upper(trim(u)), '^({units})\\b', 1)", UNIT_TYPES)}""")
    c.execute(f"""CREATE OR REPLACE MACRO nena_unit_value(u) AS nullif(trim(regexp_replace(
                     regexp_replace(upper(trim(u)), '^({units})\\b[.]?', ''), '^ *#? *', '')), '')""")
    c.execute("""CREATE OR REPLACE MACRO nena_st_name(n, pre_raw) AS
                     CASE WHEN pre_raw IS NULL THEN n ELSE trim(n[length(pre_raw) + 1:]) END""")


def required(name, country="US"):
    """A layer's Required fields, in NENA's order."""
    return [f["name"] for f in layer_fields(name, country) if f["required"]]


def gated(name, country="US"):
    """The Required fields the build fills on every feature, so the gate holds it to 100%."""
    return [n for n in required(name, country) if n not in AGENCY_OWNED + FROM_DATA]


# What a manifest lists as the layers' mandatory fields (the same in both countries)
SSAP_REQUIRED = tuple(gated("SiteStructureAddressPoint"))
RCL_REQUIRED = tuple(gated("RoadCenterLine"))
