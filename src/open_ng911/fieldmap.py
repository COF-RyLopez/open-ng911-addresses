"""
Each Source's own fields straight into NENA fields: the registry's `[source.nena]` table.

OpenAddresses' schema carries a number, street, unit, city and postcode, so a Package built from it alone leaves
most of NENA-STA-006.3 empty even where the agency publishes the field (Maine and North Dakota publish NENA's own
schema; Vermont publishes ESN and street parts). A Source's `nena` table maps a NENA field (lower-cased, as the
Packages write it) to a value spec in the OpenAddresses conform language (a field name, a list of fields joined
with spaces, `join`, `map`; see openaddresses.conform_sql), or `{value = "..."}` for a constant that the registry
justifies in a comment. The OpenAddresses conform stays as it is: it still feeds the street match and is what we
propose upstream.

Every mapped value is checked against the NENA field on the way in (`normalize_sql`): registry words for street
types and directionals ('RD' -> 'Road', 'N' -> 'North'), coded domains matched without regard to case
('RESIDENCE' -> 'residence'), whole numbers, reals, dates (ArcGIS epoch milliseconds or ISO text; placeholders
before 1990 or after 2100 are dropped) and text no longer than NENA's length. A value that fails is left empty,
never guessed, and counted as `rejected` in the coverage report (coverage.py).

Never mapped (registry.validate refuses them): NGUIDs and DiscrpAgID, which are ours until the authority opts in
(ADR 0002-0004), and the fields our boundary layers own (`BOUNDARY_OWNED`), which must agree with the A2/A3
polygons in the same Package. The agency's own NGUID is still its ID: name it as the Source's `id_field`.

Per layer the loader adds one column per NENA field, `n_<field>` (NULL where the Source maps nothing), and
`native_fields` records, per Source and field, how many features had a value and how many values were rejected.
"""
from . import db, nena

PREFIX = "n_"
# ours, never the agency's published value (ADR 0002, 0003, 0004)
WITHHELD = ("nguid", "rcl_nguid", "discrpagid")
# owned by the boundary layers (boundaries.py) or the geometry, so they always agree with them
BOUNDARY_OWNED = {
    "SiteStructureAddressPoint": ("country", "a1", "a2", "a3", "longitude", "latitude"),
    "RoadCenterLine": ("country_l", "country_r", "a1_l", "a1_r", "a2_l", "a2_r"),
}
# accepted as input though the country's template drops the field: a US Source's single unit field is split into
# UnitPreTyp + UnitValue (nena_unit_type / nena_unit_value)
INPUT_ONLY = {("SiteStructureAddressPoint", "US"): ("unit",)}
STREET_PARTS = ("st_premod", "st_predir", "st_pretyp", "st_presep", "st_name", "st_postyp", "st_posdir", "st_posmod")
SQL_TYPE = {"INTEGER": "INTEGER", "REAL": "DOUBLE"}

NATIVE_COLUMNS = "layer VARCHAR, source_key VARCHAR, field VARCHAR, native VARCHAR, with_value BIGINT, rejected BIGINT"


def fields(layer, country):
    """{name: field} a Source may map for this layer and country (input-only fields included)."""
    out = {f["name"]: f for f in nena.layer_fields(layer, country)}
    for name in INPUT_ONLY.get((layer, country), ()):
        out[name] = next(f for f in nena.layer(layer)["fields"] if f["name"] == name)
    return out


def check(source, layer, country):
    """What is wrong with a Source's `nena` table, as messages (registry.validate asserts there are none)."""
    allowed = fields(layer, country)
    errors = []
    for name, spec in source.nena.items():
        if name in WITHHELD:
            errors.append(f"{source.key}: nena.{name} is ours until the authority opts in (ADR 0002-0004); "
                          "name the agency's own ID as id_field instead")
        elif name in BOUNDARY_OWNED.get(layer, ()):
            errors.append(f"{source.key}: nena.{name} comes from the boundary layers, so it agrees with them")
        elif name not in allowed:
            errors.append(f"{source.key}: nena.{name} isn't a {layer} field in {country}")
        elif not (isinstance(spec, (str, list)) or (isinstance(spec, dict) and ("function" in spec or "value" in spec))):
            errors.append(f"{source.key}: nena.{name} = {spec!r} isn't a field, a list of fields, a function or a value")
    return errors


def describe(spec):
    """A spec as the coverage report shows it: 'ESN', 'PD + SN', 'map(SITETYPE)', '= P'."""
    if isinstance(spec, str):
        return spec
    if isinstance(spec, list):
        return " + ".join(spec)
    if "value" in spec:
        return f"= {spec['value']}"
    f = spec.get("field") or "+".join(spec.get("fields", []))
    return f"{spec['function']}({f})"


def value_sql(spec):
    from .sources import openaddresses
    if isinstance(spec, dict) and "value" in spec:
        return db.quote(spec["value"])
    return openaddresses.conform_sql(spec)


def install(c, country="US"):
    """The coded domains as a table, and the value checks the field maps use (nena.install first)."""
    rows = [(d, v) for d, vals in nena.domains().items() if isinstance(vals, list) for v in vals]
    if country == "CA":
        rows += [("StreetNameType", w) for w in nena.street_types("CA")]
    c.execute("CREATE OR REPLACE TABLE nena_domain (domain VARCHAR, value VARCHAR)")
    c.executemany("INSERT INTO nena_domain VALUES (?, ?)", rows)
    c.execute("""CREATE OR REPLACE MACRO nena_domain_value(d, x) AS
                 (SELECT min(value) FROM nena_domain WHERE domain = d AND lower(value) = lower(trim(x)))""")
    # ArcGIS writes dates as epoch milliseconds; others as text. 1899-12-30 and 3000-01-01 are placeholders.
    c.execute(r"""CREATE OR REPLACE MACRO nena_datetime(x) AS (
        SELECT CASE WHEN year(t) BETWEEN 1990 AND 2100 THEN strftime(t, '%Y-%m-%dT%H:%M:%SZ') END
        FROM (SELECT CASE WHEN regexp_matches(trim(x), '^-?[0-9]{9,}$') THEN make_timestamp(trim(x)::BIGINT * 1000)
                          ELSE try_cast(trim(x) AS TIMESTAMP) END AS t))""")
    c.execute("CREATE TABLE IF NOT EXISTS native_fields (" + NATIVE_COLUMNS + ")")
    c.execute(f"SET VARIABLE nena_country = '{country}'")


def country_of(c):
    """The job's country, as install set it (loaders get it without another argument)."""
    return c.execute("SELECT coalesce(getvariable('nena_country'), 'US')").fetchall()[0][0]


def normalize_sql(raw, f):
    """SQL for the NENA value of one raw value (text), or NULL where it doesn't fit the field."""
    name, typ, dom = f["name"], f["type"], f["domain"]
    if name == "st_pretyp":
        return f"coalesce(nena_pretype_word(upper(trim({raw}))), nena_type_word(normalize_street_type({raw})))"
    if name == "unitpretyp":  # 'APT' -> 'Apartment'; a word we don't know is kept as published
        return f"coalesce(nena_unit_type({raw}), CASE WHEN length(trim({raw})) <= 75 THEN nullif(trim({raw}), '') END)"
    if dom == "StreetNameType":
        return f"nena_type_word(normalize_street_type({raw}))"
    if dom == "StreetNameDirectional":
        return f"nena_dir_word(normalize_direction({raw}))"
    if dom == "LegacyStreetNameDirectional":
        return f"nena_domain_value('{dom}', normalize_direction({raw}))"
    if dom and isinstance(nena.domains().get(dom), list):
        return f"nena_domain_value('{dom}', {raw})"
    if typ == "INTEGER":
        return f"try_cast(nullif(regexp_extract(trim({raw}), '^-?[0-9]+'), '') AS INTEGER)"
    if typ == "REAL":
        return f"try_cast(trim({raw}) AS DOUBLE)"
    if typ == "DATETIME":
        return f"nena_datetime({raw})"
    length = f.get("length") or 254
    return f"CASE WHEN length(trim({raw})) <= {int(length)} THEN nullif(trim({raw}), '') END"


def raw_columns(source, layer, country):
    """`r_<field>` select items: each mapped field's raw value as text (to count rejections)."""
    # a blank value ('' or spaces, or a map's else = "") is no value, not a rejected one
    return [f"nullif(trim(({value_sql(spec)})::VARCHAR), '') AS r_{name}" for name, spec in source.nena.items()
            if name in fields(layer, country)]


def native_columns(source, layer, country, alias=""):
    """`n_<field>` select items for every field of the layer: the checked value where the Source maps the field
    (from its r_ column), NULL of the field's type where it doesn't. With source None, all NULL (Overture rows,
    TIGER roads)."""
    out = []
    mapped = source.nena if source else {}
    for name, f in fields(layer, country).items():
        typ = SQL_TYPE.get(f["type"], "VARCHAR")
        if name in mapped:
            out.append(f"({normalize_sql(f'{alias}r_{name}', f)})::{typ} AS {PREFIX}{name}")
        else:
            out.append(f"NULL::{typ} AS {PREFIX}{name}")
    return out


def column_names(layer, country):
    return [PREFIX + name for name in fields(layer, country)]


def record(c, table, source, layer, country, where="true"):
    """native_fields rows for one Source from a table that still has its r_ and n_ columns."""
    names = [n for n in source.nena if n in fields(layer, country)]
    if not names:
        return
    counts = ", ".join(f"count(r_{n}), count(r_{n}) - count({PREFIX}{n})" for n in names)
    res = c.execute(f"SELECT {counts} FROM {table} WHERE {where}").fetchall()[0]
    rows = [(layer, source.key, n, describe(source.nena[n]), int(res[2 * i]), int(res[2 * i + 1]))
            for i, n in enumerate(names)]
    c.executemany("INSERT INTO native_fields VALUES (?, ?, ?, ?, ?, ?)", rows)
    bad = [f"{n} {r:,}" for _, _, n, _, _, r in rows if r]
    if bad:
        print(f"  [fieldmap] {source.key}: values that don't fit the NENA field, left empty: " + ", ".join(bad))


def native_street(n, parsed):
    """Street-part select items: the Source's own parts where it maps st_name (n: the alias carrying n_ columns
    and `npre_raw`, the pre type found at the start of a native name no pre type was mapped for), else the parse
    (parsed: {part: sql})."""
    native = {
        "st_premod": f"{n}.n_st_premod", "st_predir": f"{n}.n_st_predir",
        "st_pretyp": f"coalesce({n}.n_st_pretyp, nena_pretype_word({n}.npre_raw))",
        "st_presep": f"{n}.n_st_presep",
        "st_name": f"CASE WHEN {n}.npre_raw IS NULL THEN {n}.n_st_name ELSE nena_st_name({n}.n_st_name, {n}.npre_raw) END",
        "st_postyp": f"{n}.n_st_postyp", "st_posdir": f"{n}.n_st_posdir", "st_posmod": f"{n}.n_st_posmod",
    }
    return [f"CASE WHEN {n}.n_st_name IS NOT NULL THEN {native[p]} ELSE {parsed.get(p, 'NULL')} END AS {p}"
            for p in STREET_PARTS]


def npre_raw_sql(n):
    """The pre type at the start of a Source's own street name ('ROUTE 7', 'CHEMIN DU LAC') where the Source maps
    no pre type: one step of its own, since the macros expand inline (AGENTS.md)."""
    return (f"CASE WHEN {n}.n_st_pretyp IS NULL AND {n}.n_st_name IS NOT NULL "
            f"THEN nena_pretype_raw(upper({n}.n_st_name), {n}.n_st_postyp) END AS npre_raw")


def mapped(jurisdiction, layer_key):
    """{field: ['<source key>: <spec>', ...]} for one registry layer: the report's 'source' basis."""
    out = {}
    for s in jurisdiction.sources_for(layer_key):
        for name, spec in s.nena.items():
            out.setdefault(name, []).append(f"{s.key}: {describe(spec)}")
    return out


def rejected(c, layer):
    """{field: rejected values} from native_fields."""
    return {f: int(n) for f, n in c.execute(
        f"SELECT field, sum(rejected) FROM native_fields WHERE layer = '{layer}' GROUP BY 1 HAVING sum(rejected) > 0"
    ).fetchall()}

