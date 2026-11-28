"""
A Source agency's address points, read straight from its own endpoint through the OpenAddresses source
registry (sources/<country>/<state>/<name>.json, CC0). We use OpenAddresses' catalogue of government endpoints
and its field mappings; we don't use its processed output, which is redundant with Overture.

OpenAddresses conform steps map fields, they don't rewrite values (openaddresses/openaddresses#10085): value
fixes belong in our parse (street.py), upstream PRs are for wrong field mappings or filters.

Table agency_addr(source_key, source_id, address_uid, number, street, unit, city, postcode, site_type, id_shared,
geom, n_<field> ...), and agency_dropped(source_key, reason, site_type, n): every point left out, counted by reason.
The n_ columns are the Source's own fields mapped straight to NENA fields by its registry `nena` table
(fieldmap.py); the OpenAddresses columns feed the street match and the fields a Source doesn't map.
"""
import json
import os
import re
import tomllib

from .. import db, fieldmap, ids, registry
from . import arcgis

OA_RAW = "https://raw.githubusercontent.com/openaddresses/openaddresses/{commit}/sources/{path}.json"


def pin(registry_dir=registry.REGISTRY_DIR):
    """The OpenAddresses commit builds read at: registry/openaddresses.toml, or OPENADDRESSES_COMMIT for one run.
    {commit, date}; date is None for an override."""
    if os.environ.get("OPENADDRESSES_COMMIT"):
        return {"commit": os.environ["OPENADDRESSES_COMMIT"], "date": None}
    with open(os.path.join(registry_dir, "openaddresses.toml"), "rb") as f:
        p = tomllib.load(f)["openaddresses"]
    return {"commit": p["commit"], "date": str(p["date"])}


def source_definition(path, commit=None):
    url = OA_RAW.format(commit=commit or pin()["commit"], path=path)
    return json.loads(arcgis.get(url, timeout=60, tries=1))


OA_TREE = "https://api.github.com/repos/openaddresses/openaddresses/git/trees/{commit}?recursive=1"
# OpenAddresses licence text or URL -> our licence status: open (attribution at most), share-alike, else unknown
OPEN_LICENCES = ("cc0", "publicdomain", "public domain", "pddl", "creativecommons.org/licenses/by/", "cc-by", "cc by",
                 "cc-by-4.0", "odc-by", "open government licence", "open government license", "ogl")
SHARE_ALIKE = ("odbl", "by-sa", "share-alike", "sharealike")
NON_COMMERCIAL = ("by-nc", "-nc-", "noncommercial", "non-commercial")


def source_paths(job, commit=None, registry_dir=registry.REGISTRY_DIR):
    """The OpenAddresses sources a job reads at a commit (the pin by default), as paths under sources/ without
    .json ('us/vt/statewide'), sorted: those its registry Sources name and those discover() finds."""
    j = registry.job(job, registry_dir) if isinstance(job, str) else job
    jur = registry.jurisdiction(j, registry_dir)
    found = discover(j, jur, commit) if jur.discover else []
    return sorted({s.openaddresses for s in jur.sources + found if s.openaddresses})


def tree(commit=None):
    """Every source path in OpenAddresses' registry at a commit (one GitHub API call; GITHUB_TOKEN if set)."""
    import urllib.request
    url = OA_TREE.format(commit=commit or pin()["commit"])
    headers = {"Accept": "application/vnd.github+json", "User-Agent": arcgis.USER_AGENT}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as r:
        t = json.loads(r.read())
    assert not t.get("truncated"), "OpenAddresses' tree came back truncated"
    return [e["path"][len("sources/"):-len(".json")] for e in t["tree"]
            if e["type"] == "blob" and e["path"].startswith("sources/") and e["path"].endswith(".json")]


def licence_status(layer):
    """Our licence status of an OpenAddresses layer from its `license` (text, URL or {text, url}): most state none,
    and those stay unknown (kept out of public artifacts)."""
    lic = layer.get("license")
    if isinstance(lic, dict):
        lic = " ".join(str(v) for v in lic.values())
    lic = str(lic or "").lower()
    if any(w in lic for w in SHARE_ALIKE):
        return "share-alike"
    if any(w in lic for w in NON_COMMERCIAL):
        return "unknown"  # non-commercial isn't open; someone has to read the terms
    return "open" if any(w in lic for w in OPEN_LICENCES) else "unknown"


def discover(job, jur, commit=None, paths=None, definition=None):
    """Address Sources for the OpenAddresses address sources of the job's state at a commit (the pin), after the
    registry's own: the statewide (or province) source where there is one, else every county source and then the
    city and other ones (an earlier Source wins a site two publish, combine()). A path a registry Source already
    names is left to it: the registry is the overlay on OpenAddresses. paths and definition are for tests."""
    prefix = f"{job.country.lower()}/{job.code.lower()}/"
    paths = sorted(p for p in (paths if paths is not None else tree(commit)) if p.startswith(prefix))
    definition = definition or (lambda p: source_definition(p, commit))
    named = {s.openaddresses for s in jur.sources if s.openaddresses}
    whole = [p for p in paths if p.rsplit("/", 1)[1] in ("statewide", "province")]
    defs = {p: definition(p) for p in (whole or paths) if p not in named}
    if whole and any(p in named for p in whole):
        return []

    def county_first(p):
        cov = defs[p].get("coverage", {})
        return (0 if ("county" in cov or "US Census" in cov) and "city" not in cov else 1, p)

    found = []
    for p in sorted(defs, key=county_first):
        cov = defs[p].get("coverage", {})
        for layer in defs[p].get("layers", {}).get("addresses", []):
            ident = layer.get("conform", {}).get("id")
            lic = layer.get("license")
            found.append(registry.Source(
                key=f"oa-{p.replace('/', '-')}-{layer.get('name', 'addresses')}", layer="addresses", covers="*",
                agency=layer.get("attribution") or cov.get("US Census", {}).get("name") or cov.get("city")
                or cov.get("county") or p,
                license_status=licence_status(layer), openaddresses=p, oa_layer=layer.get("name", ""),
                id_field=ident if isinstance(ident, str) else "",
                license_url=lic if isinstance(lic, str) and lic.startswith("http") else "",
                attribution=layer.get("attribution", "")))
    return found


def layer_entry(definition, layer, name):
    for entry in definition.get("layers", {}).get(layer, []):
        if entry.get("name") == name:
            return entry
    raise SystemExit(f"OpenAddresses source has no {layer} layer named {name!r}")


def entry_for(source):
    """The OpenAddresses layer entry a registry Source reads: its own `oa_entry` where OpenAddresses doesn't list
    the endpoint yet, else the entry named `oa_layer` in the OpenAddresses source `openaddresses`."""
    if source.oa_entry:
        return source.oa_entry
    return layer_entry(source_definition(source.openaddresses), source.layer, source.oa_layer)


# OpenAddresses' own patterns for its address functions (openaddresses/batch-machine openaddr/conform.py, ISC)
_NUMBER = r"\d+(?:[ -]\d/\d)?|\d+-\d+|\d+-?[A-Z]"
PREFIXED_NUMBER = rf"^\s*({_NUMBER})\s+"
POSTFIXED_STREET = rf"^(?:\s*(?:{_NUMBER})\s+)?(.*)"
_UNIT_WORDS = r"(?:(?:UNIT|APARTMENT|APT\.?|SUITE|STE\.?|BUILDING|BLDG\.?|LOT)\s+|#)"
POSTFIXED_STREET_UNITS = rf"^(?:\s*(?:{_NUMBER})\s+)?(.+?)(?:\s+{_UNIT_WORDS}.+)?$"
POSTFIXED_UNIT = rf"\s({_UNIT_WORDS}.+)$"


def _groups(pattern):
    try:
        return re.compile(pattern).groups
    except re.error:
        return None


def conform_sql(spec, env=None):
    """An OpenAddresses conform value as SQL over the JSON properties column p, as OpenAddresses' own conform
    (batch-machine) resolves it: a field name, a list of fields joined with spaces, or one of its functions:
    join, regexp (groups or replace), prefixed_number, postfixed_street (may_contain_units), postfixed_unit,
    remove_prefix, remove_postfix, format, chain (with its variable), first_non_empty, constant, map and
    mph_to_kph. A pattern our regex engine (RE2) can't run, or an unknown function, is left empty and named in the
    build log."""
    sql = _conform(spec, env or {})
    return "NULL" if sql is None else f"nullif(trim({sql}), '')"


def _raw(name, env):
    """A field's text as OpenAddresses reads it: '' where missing; a chain's variable where one is named."""
    return env[name] if name in env else f"coalesce(p->>{db.quote(name)}, '')"


def _conform(spec, env):
    if spec is None:
        return None
    if isinstance(spec, str):
        return _raw(spec, env)
    if isinstance(spec, list) and all(isinstance(s, str) for s in spec):
        return "concat_ws(' ', " + ", ".join(f"nullif(trim({_raw(s, env)}), '')" for s in spec) + ")"
    fn = spec.get("function") if isinstance(spec, dict) else None
    field = spec.get("field") if isinstance(spec, dict) else None
    v = _raw(field, env) if isinstance(field, str) else None
    ci = "'i'"
    if fn == "join" and all(isinstance(s, str) for s in spec.get("fields", [])):
        sep = db.quote(spec.get("separator", " "))
        return f"concat_ws({sep}, " + ", ".join(f"nullif(trim({_raw(s, env)}), '')" for s in spec["fields"]) + ")"
    if fn == "prefixed_number" and v:
        return f"regexp_extract({v}, {db.quote(PREFIXED_NUMBER)}, 1, {ci})"
    if fn == "postfixed_street" and v:
        pat = POSTFIXED_STREET_UNITS if spec.get("may_contain_units") else POSTFIXED_STREET
        return f"regexp_extract({v}, {db.quote(pat)}, 1, {ci})"
    if fn == "postfixed_unit" and v:
        return f"regexp_extract({v}, {db.quote(POSTFIXED_UNIT)}, 1, {ci})"
    if fn == "regexp" and v and isinstance(spec.get("pattern"), str):
        pat, n = spec["pattern"], _groups(spec["pattern"])
        if n is None or "(?=" in pat or "(?!" in pat or "(?<" in pat.replace("(?P<", ""):
            print(f"  [openaddresses] regexp {pat!r} can't run here; left empty")
            return None
        q = db.quote(pat)
        if spec.get("replace"):
            # OpenAddresses' $1 is RE2's \1; Python's re.sub replaces every match
            repl = db.quote(re.sub(r"\$(\d+)", r"\\\1", spec["replace"]))
            return f"CASE WHEN regexp_matches({v}, {q}) THEN regexp_replace({v}, {q}, {repl}, 'g') ELSE '' END"
        # the match's groups joined, '' without a match (or without groups)
        parts = ", ".join(f"regexp_extract({v}, {q}, {g})" for g in range(1, n + 1))
        return f"concat_ws('', {parts})" if n else "''"
    if fn in ("remove_prefix", "remove_postfix") and v and isinstance(spec.get("field_to_remove"), str):
        r = _raw(spec["field_to_remove"], env)
        if fn == "remove_prefix":
            return f"CASE WHEN starts_with({v}, {r}) THEN ltrim({v}[length({r}) + 1:], ' ') ELSE {v} END"
        return (f"CASE WHEN {r} <> '' AND ends_with({v}, {r}) THEN rtrim({v}[:length({v}) - length({r})], ' ') "
                f"ELSE {v} END")
    if fn == "format" and isinstance(spec.get("format"), str):
        return _format(spec, env)
    if fn == "first_non_empty":
        fields = [f for f in spec.get("fields", []) if isinstance(f, str)]
        return "coalesce(" + ", ".join(f"nullif(trim({_raw(f, env)}), '')" for f in fields) + ", '')" if fields else "''"
    if fn == "constant" and "value" in spec:
        return db.quote(spec["value"])
    if fn == "chain" and isinstance(spec.get("functions"), list):
        var, cur, out = spec.get("variable"), None, None
        for f in spec["functions"]:
            step = _conform(f, {**env, var: cur} if var and cur is not None else env)
            if step is None:
                return None
            # the chain's value is its last step's; each non-empty step becomes the variable the next one reads
            out = step
            cur = step if cur is None else f"coalesce(nullif({step}, ''), {cur})"
        return out
    if fn == "map" and isinstance(field, str):
        whens = " ".join(f"WHEN {db.quote(k)} THEN {db.quote(x)}" for k, x in spec.get("mapping", {}).items())
        default = db.quote(spec["else"]) if "else" in spec else f"trim({v})"
        return f"CASE {v} {whens} ELSE {default} END" if whens else default
    if fn == "mph_to_kph" and isinstance(field, str):
        return f"coalesce(round(try_cast({v} AS DOUBLE) * 1.609344)::INTEGER::VARCHAR, '')"
    print(f"  [openaddresses] conform {spec!r} isn't supported yet; left empty")
    return None


def _any(vals):
    return " OR ".join(f"{v} <> ''" for v in vals)


def _format(spec, env):
    """OpenAddresses' format: $1, $2 ... are the fields. The text before the first $n is always kept; text before a
    later one only where an earlier field was added and this one isn't empty; nothing at all when no field is added."""
    fields = [f"regexp_replace(trim({_raw(f, env)}), '[.]0$', '')" for f in spec.get("fields", [])]
    fmt, pieces, added, idx = spec["format"], [], [], 0
    for m in re.finditer(r"\$([0-9]+)", fmt):
        k = int(m.group(1))
        if 0 < k <= len(fields):
            val, lit = fields[k - 1], db.quote(fmt[idx:m.start()])
            if idx == 0:
                pieces.append(lit)
            elif added:
                pieces.append(f"CASE WHEN {val} <> '' AND ({_any(added)}) THEN {lit} ELSE '' END")
            pieces.append(val)
            added.append(val)
        idx = m.end()
    if not added:
        return "''"
    return f"CASE WHEN {_any(added)} THEN concat({', '.join(pieces)}, {db.quote(fmt[idx:])}) ELSE '' END"


def create_agency_addr(c, source, path, conform, has_id, no_geometry=0):
    """agency_addr from an NDJSON of features (arcgis.fetch's format) and the layer's conform mapping.

    Every point the source publishes is kept unless it can't be an addressed site; each drop is counted by
    reason and site type in agency_dropped (job.json `agency_points_dropped`):
        no_geometry        the feature has no location (counted by the fetch)
        not_point          the geometry isn't a point
        no_street          no street name: a NENA SSAP needs at least the street (a number is optional, so
                           un-numbered sites such as call boxes on a named road stay)
        excluded_site_type the registry's exclude_site_types (only for points that aren't addressed sites)
        duplicate          the same ID, address and location published twice
    Rows that share an ID but differ (another unit, another point) are all kept; their Address UID is made
    from the ID plus the address so each stays distinct (`id_shared` in job.json).
    """
    ids.install(c)
    country = fieldmap.country_of(c)
    layer = "SiteStructureAddressPoint"
    raw = "".join(f",\n                   {r}" for r in fieldmap.raw_columns(source, layer, country))
    native = ", ".join(fieldmap.native_columns(source, layer, country))
    excluded = ", ".join(db.quote(t) for t in source.exclude_site_types) or "NULL"
    site_type = conform_sql(conform.get("addrtype"))
    sid = f"nullif(trim(p->>'{source.id_field}'), '')" if has_id else "NULL"
    c.execute(f"""CREATE OR REPLACE TABLE agency_raw AS
            SELECT {sid} AS source_id,
                   -- a house number stored as a double ('427.0', PEI) is the integer it holds
                   regexp_replace({conform_sql(conform.get('number'))}, '^([0-9]+)[.]0+$', '\\1') AS number,
                   {conform_sql(conform.get('street'))} AS street,
                   {conform_sql(conform.get('unit'))} AS unit,
                   {conform_sql(conform.get('city'))} AS city,
                   {conform_sql(conform.get('postcode'))} AS postcode,
                   upper({site_type}) AS site_type,
                   ST_GeomFromGeoJSON(g) AS geom{raw}
            FROM read_json('{path}', columns = {{p: 'JSON', g: 'VARCHAR'}})""")
    c.execute(f"""CREATE OR REPLACE TABLE agency_raw AS SELECT *, {native},
            CASE WHEN ST_GeometryType(geom) <> 'POINT' THEN 'not_point'
                 WHEN street IS NULL THEN 'no_street'
                 WHEN site_type IN ({excluded}) THEN 'excluded_site_type' END AS drop_reason,
            concat_ws('|', number, upper(street), upper(unit), round(ST_X(geom), 6), round(ST_Y(geom), 6)) AS addr_key
        FROM agency_raw""")
    c.execute(f"""CREATE OR REPLACE TABLE agency_addr AS
        WITH k AS (
            SELECT *, count(DISTINCT addr_key) OVER (PARTITION BY source_id) AS keys_per_id
            FROM agency_raw WHERE drop_reason IS NULL)
        SELECT '{source.key}' AS source_key, source_id,
               -- the agency's own ID makes the Address UID (ADR 0002); an ID shared by different addresses gets
               -- the address added; no ID, a UID from the address itself (stable only while the address is
               -- unedited) until the lineage ledger carries it
               CASE WHEN source_id IS NOT NULL AND keys_per_id = 1 THEN agency_uid('{source.key}', source_id)
                    WHEN source_id IS NOT NULL THEN agency_uid('{source.key}', source_id || '|' || addr_key)
                    ELSE agency_uid('{source.key}', addr_key) END AS address_uid,
               source_id IS NOT NULL AND keys_per_id > 1 AS id_shared,
               number, street, unit, city, postcode, site_type, geom, {", ".join(fieldmap.column_names(layer, country))}
        FROM k""")
    fieldmap.record(c, "agency_raw", source, layer, country, "drop_reason IS NULL")
    dupes = c.execute("SELECT count(*) - count(DISTINCT address_uid) FROM agency_addr").fetchall()[0][0]
    c.execute(f"""CREATE OR REPLACE TABLE agency_dropped AS
        SELECT '{source.key}' AS source_key, drop_reason AS reason, site_type, count(*) AS n
        FROM agency_raw WHERE drop_reason IS NOT NULL GROUP BY ALL""")
    if dupes:
        c.execute(f"""INSERT INTO agency_dropped
            SELECT '{source.key}', 'duplicate', site_type, count(*) FROM (SELECT site_type FROM agency_addr
                QUALIFY row_number() OVER (PARTITION BY address_uid ORDER BY source_id) > 1) GROUP BY ALL""")
        c.execute("CREATE OR REPLACE TABLE agency_addr AS SELECT * FROM agency_addr "
                  "QUALIFY row_number() OVER (PARTITION BY address_uid ORDER BY source_id) = 1")
    if no_geometry:
        c.execute(f"INSERT INTO agency_dropped VALUES ('{source.key}', 'no_geometry', NULL, {int(no_geometry)})")
    # kept for the build summary's excluded-site-type view
    c.execute("CREATE OR REPLACE TABLE agency_excluded AS SELECT source_key, site_type, n FROM agency_dropped "
              "WHERE reason = 'excluded_site_type'")
    c.execute("DROP TABLE agency_raw")
    for key, reason, st, n in c.execute("SELECT * FROM agency_dropped ORDER BY n DESC").fetchall():
        print(f"  [openaddresses] {key}: dropped {n:,} points, {reason}" + (f" ({st})" if st else ""))
    shared = c.execute("SELECT count(*) FROM agency_addr WHERE id_shared").fetchall()[0][0]
    if shared:
        print(f"  [openaddresses] {source.key}: {shared:,} points share an ID with another address; all kept")
    print(f"  [openaddresses] {source.key}: {c.execute('SELECT count(*) FROM agency_addr').fetchall()[0][0]:,} address points")


DUPLICATE_M = 5.0  # the same number and street this close to a point from an earlier Source is one site


def load_agency_addr(c, job, jurisdiction, work_dir):
    """agency_addr from every address Source of the job, in registry order (an earlier Source wins a duplicate)."""
    sources = jurisdiction.sources_for("addresses")
    for i, s in enumerate(sources):
        entry = entry_for(s)
        if entry.get("protocol") != "ESRI":
            raise SystemExit(f"{s.key}: protocol {entry.get('protocol')!r} isn't supported yet (ESRI only)")
        fields = {f["name"] for f in arcgis.layer_info(entry["data"]).get("fields", [])}
        has_id = bool(s.id_field) and s.id_field in fields
        if s.id_field and not has_id:
            print(f"  [WARNING] {s.key}: id_field {s.id_field!r} isn't in the layer ({sorted(fields)}); minting UIDs")
        path = os.path.join(work_dir, f"{s.key}.ndjson")
        n, total = arcgis.fetch(entry["data"], path)
        create_agency_addr(c, s, path, entry.get("conform", {}), has_id, no_geometry=total - n)
        stash(c, i)
    combine(c, len(sources))


def stash(c, i):
    """Keep one Source's agency_addr and agency_dropped aside while the next Source is read."""
    c.execute(f"ALTER TABLE agency_addr RENAME TO _agency_addr_{i}")
    c.execute(f"ALTER TABLE agency_dropped RENAME TO _agency_dropped_{i}")


def combine(c, n):
    """agency_addr and agency_dropped of n stashed Sources. A point with the same number and street as one from an
    earlier Source within DUPLICATE_M is the same site published twice (a county and a city both publishing it):
    the earlier Source's is kept and the other counted as duplicate_across_sources."""
    union = lambda t: " UNION ALL BY NAME ".join(f"SELECT {i} AS _rank, * FROM _{t}_{i}" for i in range(n))
    c.execute(f"CREATE OR REPLACE TABLE agency_addr AS {union('agency_addr')}")
    c.execute(f"CREATE OR REPLACE TABLE agency_dropped AS SELECT * EXCLUDE (_rank) FROM ({union('agency_dropped')})")
    if n > 1:
        c.execute(f"""CREATE OR REPLACE TEMP TABLE _cross AS
            SELECT DISTINCT b.address_uid, b.source_key, b.site_type FROM agency_addr a JOIN agency_addr b
              ON a._rank < b._rank AND a.number IS NOT DISTINCT FROM b.number AND upper(a.street) = upper(b.street)
             AND ST_Distance_Sphere(a.geom, b.geom) < {DUPLICATE_M}""")
        c.execute("""INSERT INTO agency_dropped SELECT source_key, 'duplicate_across_sources', site_type, count(*)
                     FROM _cross GROUP BY ALL""")
        c.execute("DELETE FROM agency_addr WHERE address_uid IN (SELECT address_uid FROM _cross)")
        dup = c.execute("SELECT count(*) FROM _cross").fetchall()[0][0]
        c.execute("DROP TABLE _cross")
        if dup:
            print(f"  [openaddresses] {dup:,} points published by an earlier Source too; the earlier one kept")
    c.execute("ALTER TABLE agency_addr DROP COLUMN _rank")
    for i in range(n):
        c.execute(f"DROP TABLE _agency_addr_{i}")
        c.execute(f"DROP TABLE _agency_dropped_{i}")
    c.execute("CREATE OR REPLACE TABLE agency_excluded AS SELECT source_key, site_type, n FROM agency_dropped "
              "WHERE reason = 'excluded_site_type'")
