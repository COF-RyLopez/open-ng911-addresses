"""
The lineage ledger (ng911_address_lineage): one row per Address UID per GERS ID it has carried, so the UID
(and the NGUID built from it) survives Overture re-issuing an address ID, which it does on any attribute or
location change (plan, "GERS churn").

Each Overture address in this release gets its Address UID by the first rule that applies:

    agency_record   it matched a Source agency Record: the Record's UID (matcher.py)
    same_id         its GERS ID is already in the ledger
    source_record   a GERS ID retired since the last release came from the same upstream record
                    (Overture sources[1].dataset + record_id): that one's UID
    minted          first sighting: ids.minted_uid(gers_id)

Phase 2 adds exact_rematch / near_rematch from Overture's changelog (removed and added IDs in the same
county, same street key and number) and the churn table.

Columns: address_uid, gers_id, first_release, last_release, link_method, source_dataset, source_record_id.
"""
LEDGER_COLUMNS = ("address_uid VARCHAR, gers_id VARCHAR, first_release VARCHAR, last_release VARCHAR, "
                  "link_method VARCHAR, source_dataset VARCHAR, source_record_id VARCHAR")


def load_previous(c, path=None):
    if path:
        c.execute(f"CREATE OR REPLACE TABLE prev_ledger AS SELECT * FROM read_parquet('{path}')")
    else:
        c.execute(f"CREATE OR REPLACE TABLE prev_ledger ({LEDGER_COLUMNS})")


def link(c, release):
    """overture_uid(gers_id, address_uid, link_method) for this release, and the updated ledger table."""
    c.execute("""CREATE OR REPLACE TABLE overture_uid AS
        WITH retired AS (  -- ledger rows whose GERS ID is gone this release, keyed by upstream record
            SELECT source_dataset, source_record_id, arg_max(address_uid, last_release) AS address_uid
            FROM prev_ledger WHERE gers_id NOT IN (SELECT gers_id FROM overture_addr)
              AND source_record_id IS NOT NULL
            GROUP BY ALL HAVING count(DISTINCT address_uid) = 1),
        known AS (SELECT gers_id, arg_max(address_uid, last_release) AS address_uid FROM prev_ledger GROUP BY 1)
        SELECT o.gers_id,
               coalesce(m.address_uid, k.address_uid, r.address_uid, minted_uid(o.gers_id)) AS address_uid,
               CASE WHEN m.address_uid IS NOT NULL THEN 'agency_record'
                    WHEN k.address_uid IS NOT NULL THEN 'same_id'
                    WHEN r.address_uid IS NOT NULL THEN 'source_record'
                    ELSE 'minted' END AS link_method,
               o.source_dataset, o.source_record_id
        FROM overture_addr o
        LEFT JOIN address_match m USING (gers_id)
        LEFT JOIN known k USING (gers_id)
        LEFT JOIN retired r ON r.source_dataset = o.source_dataset AND r.source_record_id = o.source_record_id""")
    c.execute(f"""CREATE OR REPLACE TABLE ledger AS
        SELECT u.address_uid, u.gers_id, coalesce(p.first_release, '{release}') AS first_release,
               '{release}' AS last_release,
               -- a pair keeps the method that first linked it
               coalesce(p.link_method, u.link_method) AS link_method, u.source_dataset, u.source_record_id
        FROM overture_uid u LEFT JOIN prev_ledger p USING (address_uid, gers_id)
        UNION ALL BY NAME
        SELECT * FROM prev_ledger p  -- retired pairs stay, with the last release they were live in
        WHERE NOT EXISTS (SELECT 1 FROM overture_uid u WHERE u.address_uid = p.address_uid AND u.gers_id = p.gers_id)""")
    return dict(c.execute("SELECT link_method, count(*) FROM overture_uid GROUP BY 1").fetchall())
