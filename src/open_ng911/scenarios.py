"""
Source-data scenarios: why the validation checks (validate.py) fail, read back against the Source's own published
fields, so a jurisdiction's patterns (a unit or building field we don't map, a point type, a second Source, an
Overture copy) can be named, logged and pushed into the right NENA field. Findings only: nothing here changes or
drops a feature.

    duplicates    SiteStructureAddressPoint.duplicate_address groups, by what they are made of (Records only,
                  a Record and an Overture gap-fill candidate, candidates only) and how far apart their points are;
                  for Record groups, the Source fields whose values differ inside a group (the field that would tell
                  the points apart), and whether a subaddress field the duplicate key reads already does
    rcl_agreement Records against the range on their side of the road (ranges.py): the failure rate by result,
                  road source, distance, the Source's point type and placement, and every low-cardinality Source
                  field whose values split the failure rate (a hidden subtype or status); for points on no named
                  road, whether their street exists in the Package's roads at all (a name mismatch) or only farther
                  than ranges.MAX_M
    range_overlap segment pairs of one street and community claiming the same number, by kind

The Source's fields come from the features the build fetched (work_dir/<source key>.ndjson, arcgis.fetch), joined
on the registry's id_field; a Source without one is reported without its fields. job.json `scenarios`; the CI build
log prints it (`python -m open_ng911.scenarios <job.json>`). Each finding is logged once per jurisdiction in
docs/standards/source-scenarios.md and gbrain (sim/problems/, domain ng911-pipeline).
"""
import json
import os
import sys

from . import db, ranges, validate

SAMPLE = 5           # example groups or values reported per finding
MAX_CARDINALITY = 40  # a Source field with more distinct values than this is not a type or status
MIN_N = 100          # values with fewer points than this don't count toward a field's spread
SPREAD = 0.10        # a field whose values' failure rates differ by more than this is reported
ID_LIKE = 0.5        # a field with more distinct values than this share of its rows is an ID, never a reason
STATS_ROWS = 50_000  # raw rows sampled per Source for field statistics (a field's cardinality, not its count)
SPLIT_ROWS = 200_000  # range-checked points sampled for the fail-rate splits; MIN_N still applies per value


def _raw(c, jurisdiction, work_dir):
    """_raw_fields(source_key, source_id, p JSON): every address Source's fetched features with an id_field, one row
    per ID; returns the {source key: id_field} it read."""
    c.execute("CREATE OR REPLACE TEMP TABLE _raw_fields (source_key VARCHAR, source_id VARCHAR, p JSON)")
    read = {}
    for s in jurisdiction.sources_for("addresses"):
        path = os.path.join(work_dir, f"{s.key}.ndjson")
        if not s.id_field or not os.path.exists(path):
            continue
        c.execute(f"""INSERT INTO _raw_fields
            SELECT '{s.key}', nullif(trim(p->>{db.quote(s.id_field)}), ''), any_value(p)
            FROM read_json({db.quote(path)}, columns = {{p: 'JSON', g: 'VARCHAR'}}) GROUP BY 2""")
        read[s.key] = s.id_field
    return read


def _mapped(jurisdiction):
    """{source key: the Source fields its registry `nena` table reads}."""
    def fields(spec):
        if isinstance(spec, str):
            yield spec
        elif isinstance(spec, list):
            for x in spec:
                yield from fields(x)
        elif isinstance(spec, dict):
            for k, v in spec.items():
                if k in ("field", "fields") or k not in ("function", "mapping", "else", "value", "format",
                                                          "pattern", "replace", "separator", "variable"):
                    yield from fields(v)
    return {s.key: sorted(set(fields(s.nena))) for s in jurisdiction.sources_for("addresses")}


def _field_stats(c):
    """{(source key, field): (distinct values, rows)} of every Source field, over a repeatable sample of STATS_ROWS
    features per Source (cardinality and ID-likeness, not counts)."""
    return {(k, f): (d, n) for k, f, d, n in c.execute(f"""
        WITH r AS (SELECT * FROM _raw_fields
                   QUALIFY row_number() OVER (PARTITION BY source_key ORDER BY hash(source_id)) <= {STATS_ROWS})
        SELECT source_key, k, approx_count_distinct(p->>k), count(*) FROM r, unnest(json_keys(p)) u(k)
        GROUP BY 1, 2""").fetchall()}


def _have(c, table):
    return {r[0] for r in c.execute(f"DESCRIBE {table}").fetchall()}


def duplicates(c, mapped, stats):
    """The duplicate_address groups (validate.ADDRESS, per Package and A3)."""
    have = _have(c, "ssap")
    key = [n for n in validate.ADDRESS if n in have]
    extra = validate.SUBADDRESS + validate.COMMUNITY
    narrow = [n for n in key if n not in extra]
    c.execute(f"""CREATE OR REPLACE TEMP TABLE _dup AS
        SELECT s.uid, s.status, s.source AS source_key, s.source_id, s.source_site_type, s.geoid, s.latitude,
               s.longitude, d.grp
        FROM ssap s JOIN ({validate.duplicate_rows("ssap", have)}) d USING (uid)""")
    groups = db.rows(c, """
        WITH g AS (
            SELECT grp, count(*) FILTER (WHERE status = 'record') AS rec, count(*) FILTER (WHERE status <> 'record') AS gap,
                   -- the farthest two points of a group, by their bounding box diagonal
                   111320 * sqrt(power((max(longitude) - min(longitude)) * cos(radians(avg(latitude))), 2)
                                 + power(max(latitude) - min(latitude), 2)) AS spread_m
            FROM _dup GROUP BY 1)
        SELECT CASE WHEN gap = 0 THEN 'records_only' WHEN rec = 0 THEN 'gap_fill_only' ELSE 'record_and_gap_fill' END
                   AS kind,
               CASE WHEN spread_m < 0.5 THEN 'stacked (<0.5 m)' WHEN spread_m < 25 THEN 'near (<25 m)'
                    ELSE 'apart (>=25 m)' END AS spread,
               count(*) AS groups, sum(rec + gap) AS points
        FROM g GROUP BY ALL ORDER BY groups DESC""")
    # groups under the key without its subaddress and community fields that each of those fields tells apart
    told_apart = {}
    if narrow != key:
        for n in [n for n in key if n in extra]:
            told_apart[n] = db.one(c, f"""SELECT count(*) AS g FROM (
                SELECT 1 FROM ssap WHERE add_number IS NOT NULL GROUP BY geoid, a3, {", ".join(narrow)}
                HAVING count(*) > 1 AND count(DISTINCT {n}) > 1)""")["g"]
    out = {"key": key, "groups": groups, "told_apart_by_subaddress": told_apart}
    # Record groups: the Source fields whose values differ inside a group
    c.execute("""CREATE OR REPLACE TEMP TABLE _dup_rec AS SELECT d.* FROM _dup d
                 WHERE status = 'record' AND grp IN (SELECT grp FROM _dup WHERE status = 'record'
                                                     GROUP BY 1 HAVING count(*) > 1)""")
    rec_groups = db.one(c, "SELECT count(DISTINCT grp) AS g FROM _dup_rec")["g"]
    differ = db.rows(c, """
        WITH kv AS (SELECT d.grp, d.source_key, k, r.p->>k AS v FROM _dup_rec d
                    JOIN _raw_fields r USING (source_key, source_id), unnest(json_keys(r.p)) u(k)),
             g AS (SELECT grp, source_key, k, count(DISTINCT coalesce(v, '<empty>')) AS nv,
                          list(DISTINCT coalesce(v, '<empty>') ORDER BY coalesce(v, '<empty>'))[:4] AS vals
                   FROM kv GROUP BY ALL)
        SELECT source_key, k AS field, count(*) FILTER (WHERE nv > 1) AS groups_differ,
               (list(vals ORDER BY grp) FILTER (WHERE nv > 1))[:5] AS examples
        FROM g GROUP BY ALL HAVING groups_differ > 0 ORDER BY groups_differ DESC""")
    for r in differ:
        d, n = stats.get((r["source_key"], r["field"]), (0, 1))
        r["id_like"] = d / max(n, 1) > ID_LIKE
        r["mapped"] = r["field"] in mapped.get(r["source_key"], [])
        r["share_of_record_groups"] = round(r["groups_differ"] / max(rec_groups, 1), 3)
    out["record_groups"] = rec_groups
    out["record_groups_by_site_type"] = db.rows(c, """SELECT source_site_type AS site_type, count(DISTINCT grp) AS groups
        FROM _dup_rec GROUP BY 1 ORDER BY 2 DESC LIMIT 10""")
    out["source_fields_differing"] = [r for r in differ if not r["id_like"]][:15]
    out["id_like_fields_differing"] = [r["field"] for r in differ if r["id_like"]][:10]
    out["samples"] = db.rows(c, f"""SELECT grp, list(struct_pack(status, source_id, source_site_type,
            lat := round(latitude, 6), lon := round(longitude, 6)) ORDER BY uid) AS points
        FROM _dup WHERE grp IN (SELECT DISTINCT grp FROM _dup ORDER BY hash(grp) LIMIT {SAMPLE}) GROUP BY 1""")
    for s in out["samples"]:
        s.pop("grp")
    c.execute("DROP TABLE _dup")
    c.execute("DROP TABLE _dup_rec")
    return out


def _splits(c, table, mapped, stats):
    """Low-cardinality Source fields whose values' failure rates differ by more than SPREAD. table: (source_key,
    source_id, failed BOOLEAN)."""
    # only the fields that can be a type or status, on a repeatable sample of the points
    fields = [(key, f) for (key, f), (d, n) in stats.items()
              if 2 <= d <= MAX_CARDINALITY and d / max(n, 1) <= ID_LIKE]
    if not fields:
        return []
    c.execute("CREATE OR REPLACE TEMP TABLE _split_fields (source_key VARCHAR, k VARCHAR)")
    c.executemany("INSERT INTO _split_fields VALUES (?, ?)", fields)
    by = db.rows(c, f"""
        WITH t AS (SELECT * FROM {table} ORDER BY hash(source_key, source_id) LIMIT {SPLIT_ROWS})
        SELECT r.source_key, f.k AS field, coalesce(r.p->>f.k, '<empty>') AS value, count(*) AS n,
               round(avg(t.failed::INTEGER), 3) AS fail_rate
        FROM t JOIN _raw_fields r USING (source_key, source_id) JOIN _split_fields f USING (source_key)
        GROUP BY ALL""")
    out = []
    for key, f in fields:
        vals = sorted((v for v in by if v["source_key"] == key and v["field"] == f), key=lambda v: -v["n"])
        big = [v for v in vals if v["n"] >= MIN_N]
        if len(big) < 2:
            continue
        spread = max(v["fail_rate"] for v in big) - min(v["fail_rate"] for v in big)
        if spread > SPREAD:
            out.append({"source_key": key, "field": f, "mapped": f in mapped.get(key, []), "spread": round(spread, 3),
                        "values": [{k: v[k] for k in ("value", "n", "fail_rate")} for v in vals[:8]]})
    return sorted(out, key=lambda r: -r["spread"])[:10]


def rcl_agreement(c, mapped, stats):
    """Records against their side's range, and Records on no named road."""
    failing = "('wrong_side', 'outside_range', 'wrong_parity')"
    c.execute(f"""CREATE OR REPLACE TEMP TABLE _arc AS
        SELECT a.*, s.source AS source_key, s.source_id, s.source_site_type, s.placement,
               r.road_source, a.result IN {failing} AS failed,
               CASE WHEN a.side = 'l' THEN least(r.fromaddr_l, r.toaddr_l) ELSE least(r.fromaddr_r, r.toaddr_r) END AS lo,
               CASE WHEN a.side = 'l' THEN greatest(r.fromaddr_l, r.toaddr_l)
                    ELSE greatest(r.fromaddr_r, r.toaddr_r) END AS hi
        FROM address_range_check a JOIN ssap s USING (uid) LEFT JOIN rcl r ON r.uid = a.rcl_uid""")
    checked = f"result IN ('in_range', {failing[1:-1]})"
    out = {"results": dict(c.execute("SELECT result, count(*) FROM _arc GROUP BY 1 ORDER BY 2 DESC").fetchall())}
    rate = lambda by: db.rows(c, f"""SELECT {by} AS value, count(*) AS n, round(avg(failed::INTEGER), 3) AS fail_rate
        FROM _arc WHERE {checked} GROUP BY 1 ORDER BY n DESC LIMIT 10""")
    out["by_road_source"] = rate("road_source")
    out["by_distance"] = rate("""CASE WHEN distance_m < 15 THEN '<15 m' WHEN distance_m < 50 THEN '15-50 m'
                                      WHEN distance_m < 100 THEN '50-100 m' ELSE '100-150 m' END""")
    out["by_site_type"] = rate("source_site_type")
    out["by_placement"] = rate("placement")
    # how far outside its side's range a number is: a near miss is a range that ends short, a far one another
    # segment's number (or a block-numbering scheme the range doesn't follow)
    out["outside_by"] = db.rows(c, """SELECT CASE WHEN d <= 10 THEN '<=10' WHEN d <= 100 THEN '11-100'
                                                 WHEN d <= 1000 THEN '101-1000' ELSE '>1000' END AS numbers_outside,
                                            count(*) AS n
        FROM (SELECT least(abs(add_number - lo), abs(add_number - hi)) AS d FROM _arc WHERE result = 'outside_range')
        GROUP BY 1 ORDER BY 2 DESC""")
    c.execute(f"CREATE OR REPLACE TEMP TABLE _arc_checked AS SELECT source_key, source_id, failed FROM _arc WHERE {checked}")
    out["source_fields_splitting"] = _splits(c, "_arc_checked", mapped, stats)
    # points on no named road: is their street in the Package's roads at all?
    c.execute(f"""CREATE OR REPLACE TEMP TABLE _nmr AS
        SELECT a.uid, a.geoid, s.st_name, {ranges._key('s')} AS skey FROM _arc a JOIN ssap s USING (uid)
        WHERE a.result = 'no_matching_road'""")
    c.execute(f"CREATE OR REPLACE TEMP TABLE _rkeys AS SELECT DISTINCT geoid, {ranges._key('r')} AS skey FROM rcl r")
    out["no_matching_road"] = db.rows(c, """SELECT CASE WHEN k.skey IS NULL THEN 'street_not_in_package_roads'
                                                       ELSE 'street_farther_than_max_m' END AS why, count(*) AS n
        FROM _nmr n LEFT JOIN _rkeys k USING (geoid, skey) GROUP BY 1 ORDER BY 2 DESC""")
    out["no_matching_road_top_streets"] = db.rows(c, f"""SELECT st_name, count(*) AS n FROM _nmr n
        WHERE NOT EXISTS (SELECT 1 FROM _rkeys k WHERE k.geoid = n.geoid AND k.skey = n.skey)
        GROUP BY 1 ORDER BY 2 DESC LIMIT {2 * SAMPLE}""")
    for t in ("_arc", "_arc_checked", "_nmr", "_rkeys"):
        c.execute(f"DROP TABLE {t}")
    return out


def range_overlap(c):
    """Segment pairs of one street and community whose ranges claim the same number (validate.py's check), by kind."""
    sides = " UNION ALL ".join(
        f"""SELECT uid, geoid, {ranges._key('r')} AS skey, a3_{s} AS a3, least(fromaddr_{s}, toaddr_{s}) AS lo,
                   greatest(fromaddr_{s}, toaddr_{s}) AS hi, parity_{s} AS par, road_source
            FROM rcl r WHERE parity_{s} IN ('O', 'E', 'B') AND fromaddr_{s} > 0 AND toaddr_{s} > 0"""
        for s in ranges.SIDES)
    return db.rows(c, f"""WITH s AS ({sides}),
        p AS (SELECT a.*, b.uid AS buid, b.lo AS blo, b.hi AS bhi, b.par AS bpar, b.road_source AS bsrc
              FROM s a JOIN s b ON a.geoid = b.geoid AND a.skey = b.skey AND a.a3 IS NOT DISTINCT FROM b.a3
               AND a.uid < b.uid
              WHERE a.lo <= b.hi AND b.lo <= a.hi AND (a.par = 'B' OR b.par = 'B' OR a.par = b.par))
        SELECT CASE WHEN lo = blo AND hi = bhi THEN 'same_range'
                    WHEN (lo <= blo AND hi >= bhi) OR (blo <= lo AND bhi >= hi) THEN 'one_contains_other'
                    WHEN least(hi, bhi) = greatest(lo, blo) THEN 'shared_end_number'
                    ELSE 'partial' END AS kind,
               (par = 'B' OR bpar = 'B') AS either_both_parity, road_source = bsrc AS same_road_source,
               count(*) AS pairs
        FROM p GROUP BY ALL ORDER BY pairs DESC LIMIT 12""")


def run(c, job, jurisdiction, work_dir):
    """job.json `scenarios`."""
    read = _raw(c, jurisdiction, work_dir)
    mapped, stats = _mapped(jurisdiction), _field_stats(c)
    out = {"source_fields_read": read, "duplicates": duplicates(c, mapped, stats),
           "rcl_agreement": rcl_agreement(c, mapped, stats),
           "range_overlap": range_overlap(c)}
    c.execute("DROP TABLE _raw_fields")
    return out


def main(argv=None):
    """Print the `scenarios` of one or more job.json files, one line each, for reading out of a CI log."""
    for path in argv if argv is not None else sys.argv[1:]:
        with open(path) as f:
            s = json.load(f)
        print(f"[{s['job']}] scenarios: " + json.dumps(s.get("scenarios"), separators=(",", ":"), default=str))
        # the score again, so the log's last lines carry it next to the findings
        v = s.get("validation") or {}
        print(f"[{s['job']}] validation score: {v.get('before')} -> {v.get('score')}; Packages failing each check: "
              + json.dumps(v.get("packages_failing"), separators=(",", ":")))


if __name__ == "__main__":
    main()
