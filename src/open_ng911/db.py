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
