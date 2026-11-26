"""The DuckDB connection every build job uses (see AGENTS.md for DuckDB 2.0 gotchas), and the few SQL helpers
every module shares."""
import datetime
import os

import duckdb


def connect(path=":memory:", s3=True):
    c = duckdb.connect(path)
    for ext in ("spatial", "httpfs") if s3 else ("spatial",):
        try:
            c.execute(f"LOAD {ext}")
        except duckdb.Error:
            c.execute(f"INSTALL {ext}")
            c.execute(f"LOAD {ext}")
    c.execute("SET geometry_always_xy = true")  # lon/lat order
    c.execute(f"SET max_temp_directory_size = '{os.environ.get('DUCKDB_MAX_TEMP', '40GiB')}'")
    if s3:
        # Overture's bucket is public: read it anonymously, even where AWS credentials are in the environment
        c.execute("CREATE OR REPLACE SECRET overture (TYPE s3, KEY_ID '', SECRET '', REGION 'us-west-2')")
    return c


def now():
    """UTC now in the form every dateupdate and fetched field uses."""
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def quote(v):
    """A SQL string literal."""
    return "'" + str(v).replace("'", "''") + "'"


def case(expr, mapping, default="NULL"):
    """CASE expr WHEN 'k' THEN 'v' ... ELSE default END."""
    whens = " ".join(f"WHEN {quote(k)} THEN {quote(v)}" for k, v in mapping.items())
    return f"CASE {expr} {whens} ELSE {default} END"


def rows(c, sql):
    """A query's rows as dicts (DuckDB 2.0 relations have no fetchone, and there's no pandas here)."""
    res = c.execute(sql)
    cols = [d[0] for d in res.description]
    return [dict(zip(cols, r)) for r in res.fetchall()]


def one(c, sql):
    return rows(c, sql)[0]


def gate(c, table, required, nguid, label="", nguid_label=None):
    """NENA mandatory fields filled on every row of a layer, and one NGUID per row; returns the failures as
    '<label><field>: N rows empty' and '<nguid_label or label><nguid>: N duplicates'."""
    fails = []
    for f in required:
        missing = c.execute(f"SELECT count(*) FROM {table} WHERE {f} IS NULL").fetchall()[0][0]
        if missing:
            fails.append(f"{label}{f}: {missing:,} rows empty")
    dup = c.execute(f"SELECT count(*) - count(DISTINCT {nguid}) FROM {table}").fetchall()[0][0]
    if dup:
        fails.append(f"{label if nguid_label is None else nguid_label}{nguid}: {dup:,} duplicates")
    return fails


# Every feature a build leaves out of a layer, counted by layer, Source and reason (AGENTS.md: nothing is dropped
# uncounted). job.json reports it as `features_dropped`; the address points keep their own, finer
# `agency_points_dropped` (by site type too, sources/openaddresses.py).
DROPPED = "feature_dropped"


DROPPED_COLUMNS = "layer VARCHAR, source_key VARCHAR, reason VARCHAR, n BIGINT"


def create_dropped(c, replace=True):
    """An empty feature_dropped (replace) or the one already there; build.run starts every job with an empty one."""
    c.execute(f"CREATE {'OR REPLACE TABLE' if replace else 'TABLE IF NOT EXISTS'} {DROPPED} ({DROPPED_COLUMNS})")


def drop(c, table, where, layer, reason, source_key="source_key"):
    """Delete the rows of `table` matching `where`, counting them in feature_dropped first, by Source
    (`source_key`: a column or a SQL literal) and reason. Returns how many went."""
    create_dropped(c, replace=False)
    n = c.execute(f"SELECT count(*) FROM {table} WHERE {where}").fetchall()[0][0]
    if n:
        c.execute(f"""INSERT INTO {DROPPED} SELECT {quote(layer)}, {source_key}, {quote(reason)}, count(*)
                      FROM {table} WHERE {where} GROUP BY ALL""")
        c.execute(f"DELETE FROM {table} WHERE {where}")
    return n


def dropped(c):
    """{layer: {reason: n}} for job.json."""
    out = {}
    for layer, reason, n in c.execute(f"SELECT layer, reason, sum(n)::BIGINT FROM {DROPPED} GROUP BY 1, 2 "
                                      "ORDER BY 1, 3 DESC, 2").fetchall():
        out.setdefault(layer, {})[reason] = n
    return out
