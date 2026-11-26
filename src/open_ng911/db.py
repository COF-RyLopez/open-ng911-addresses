"""One DuckDB connection per build job, set up the same way everywhere (see AGENTS.md for DuckDB 2.0 gotchas)."""
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
