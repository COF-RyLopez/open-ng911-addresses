"""
Street parsing and the street match key, as DuckDB macros, so every source (agency records and Overture)
parses the same way and both sides of a match go through the same key.

Ported from ng911-pipeline: macros/geometry_helpers.sql (normalize_direction, normalize_street_type,
street_type_suffix_regex, street_match_key) and models/staging/stg_overture_addresses.sql (the parse).

    install(c)
    SELECT parse_street('N EIGHTH STREET W')
      -> {predir: N, name: EIGHTH, type: ST, posdir: W}
    SELECT street_key('N EIGHTH ST')  -> ' N 8TH ST '
"""

DIRECTIONS = {
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
    "NORTHEAST": "NE", "NORTHWEST": "NW", "SOUTHEAST": "SE", "SOUTHWEST": "SW",
    **{d: d for d in ("N", "S", "E", "W", "NE", "NW", "SE", "SW")},
}

# Street types as written -> USPS-style abbreviation (the matching form). Comments name the source that
# taught us the variant.
STREET_TYPES = {
    "STREET": "ST", "STR": "ST", "AVENUE": "AVE", "AV": "AVE",  # Kern: 'CHESTER AV'
    "BOULEVARD": "BLVD", "BL": "BLVD",  # Alameda: 'FREMONT BL'
    "ROAD": "RD", "DRIVE": "DR", "LANE": "LN", "WY": "WAY",  # Alameda: 'DWIGHT WY'
    "COURT": "CT", "CRT": "CT", "PLACE": "PL", "CIRCLE": "CIR", "CIRC": "CIR", "CI": "CIR",  # Placer: 'DANTE CI'
    "COVE": "CV", "HIGHWAY": "HWY", "PARKWAY": "PKWY", "PW": "PKWY", "PKY": "PKWY",  # Alameda: 'PASEO PADRE PW'
    "TRAIL": "TRL", "TR": "TRL", "TL": "TRL",  # Placer, Calaveras
    "TERRACE": "TER", "TE": "TER", "CRESCENT": "CRES", "COMMON": "CMN", "CM": "CMN", "GLEN": "GLN",
    "SQUARE": "SQ", "CR": "CIR",  # Calaveras: 'HOKAN CR'
    "ALLEY": "ALY", "PLAZA": "PLZ", "LP": "LOOP",  # Placer: 'IMPRESSIONIST LP'
    "EXTENSION": "EXT", "RIDGE": "RDG", "CROSSING": "XING", "HILL": "HL", "HEIGHTS": "HTS",
}

# Type suffixes recognised at the end of a street, abbreviated or spelled out (31% of California streets spell
# it out: 'PARK AVENUE'). Order doesn't matter: the regex is anchored at the end.
SUFFIXES = sorted(set(STREET_TYPES) | set(STREET_TYPES.values()) | {"WAY", "LOOP", "PT", "WALK", "PATH", "EXPY", "FWY"})
SUFFIX_RE = " +(" + "|".join(SUFFIXES) + ")$"
DIR_ALT = "N|S|E|W|NE|NW|SE|SW|NORTH|SOUTH|EAST|WEST"

ORDINALS = ["FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH", "SIXTH", "SEVENTH", "EIGHTH", "NINTH", "TENTH",
            "ELEVENTH", "TWELFTH", "THIRTEENTH", "FOURTEENTH", "FIFTEENTH", "SIXTEENTH", "SEVENTEENTH",
            "EIGHTEENTH", "NINETEENTH", "TWENTIETH"]
# ST FRANCIS (address) vs SAINT FRANCIS (another source), VIA MARIPOSA W vs VIA MARIPOSA WEST
KEY_WORDS = [("SAINT", "ST"), ("MOUNT", "MT"), ("FORT", "FT"), ("NORTHEAST", "NE"), ("NORTHWEST", "NW"),
             ("SOUTHEAST", "SE"), ("SOUTHWEST", "SW"), ("NORTH", "N"), ("SOUTH", "S"), ("EAST", "E"), ("WEST", "W")]


def _case(expr, mapping, default="NULL"):
    whens = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in mapping.items())
    return f"CASE {expr} {whens} ELSE {default} END"


def _ordinal(n):
    return f"{n}{'TH' if n in (11, 12, 13) else {1: 'ST', 2: 'ND', 3: 'RD'}.get(n % 10, 'TH')}"


def key_sql(expr):
    """Street name padded with spaces, with direction words abbreviated and ordinal words as numbers
    ('N EIGHTH' -> ' N 8TH '), for whole-word matching where one source spells numbered streets out."""
    sql = f"(' ' || upper(trim({expr})) || ' ')"
    for full, abbr in KEY_WORDS:
        sql = f"replace({sql}, ' {full} ', ' {abbr} ')"
    for i, w in enumerate(ORDINALS, 1):
        sql = f"replace({sql}, ' {w} ', ' {_ordinal(i)} ')"
    return sql


def install(c):
    """Create the street macros on a connection."""
    c.execute(f"CREATE OR REPLACE MACRO normalize_direction(d) AS {_case('upper(trim(d))', DIRECTIONS)}")
    c.execute("CREATE OR REPLACE MACRO normalize_street_type(t) AS "
              + _case("rtrim(upper(trim(t)), '.')", STREET_TYPES, "rtrim(upper(trim(t)), '.')"))
    # s0: upper case, single spaces, trailing periods dropped ('SHASTA ST.'), zero-padded ordinals unpadded
    # ('05TH ST' -> '5TH ST', San Francisco and San Diego)
    c.execute(r"""CREATE OR REPLACE MACRO street_s0(s) AS
        regexp_replace(regexp_replace(regexp_replace(upper(trim(s)), '\s+', ' ', 'g'), '[.]+$', ''),
                       '\b0+([1-9][0-9]*(ST|ND|RD|TH))\b', '\1', 'g')""")
    # a direction after the street type ('TERRA VISTA PKWY W') is the post-directional. Only after a recognised
    # type, so a street named for its letter ('AVENUE N', Lancaster) keeps it.
    c.execute(f"""CREATE OR REPLACE MACRO street_postdir_raw(s0) AS
        CASE WHEN regexp_matches(s0, '{SUFFIX_RE[:-1]} +({DIR_ALT})$') THEN regexp_extract(s0, ' +({DIR_ALT})$', 1) END""")
    c.execute(f"""CREATE OR REPLACE MACRO street_core(s0) AS
        CASE WHEN street_postdir_raw(s0) IS NOT NULL THEN regexp_replace(s0, ' +({DIR_ALT})$', '') ELSE s0 END""")
    # the type suffix comes off first, so 'E ST' (E Street) keeps 'E' as its name rather than 'ST'
    c.execute(f"""CREATE OR REPLACE MACRO parse_street(s) AS struct_pack(
        predir := normalize_direction(nullif(regexp_extract(
                      regexp_replace(street_core(street_s0(s)), '{SUFFIX_RE}', ''), '^({DIR_ALT}) +', 1), '')),
        name := nullif(trim(regexp_replace(regexp_replace(street_core(street_s0(s)), '{SUFFIX_RE}', ''),
                                           '^({DIR_ALT}) +', '')), ''),
        type := normalize_street_type(nullif(regexp_extract(street_core(street_s0(s)), '{SUFFIX_RE}', 1), '')),
        posdir := normalize_direction(street_postdir_raw(street_s0(s))))""")
    c.execute(f"CREATE OR REPLACE MACRO street_key(s) AS {key_sql('s')}")
    # the key of a parsed street: both sides of an address match go through this
    c.execute("""CREATE OR REPLACE MACRO parsed_street_key(p) AS
        street_key(concat_ws(' ', p.predir, p.name, p.type, p.posdir))""")
