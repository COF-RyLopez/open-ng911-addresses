"""
The address matcher: pairs each Source agency Record with the Overture address for the same place, one to
one, so the Record keeps its own Address UID and gains the GERS ID (ADR 0001, 0002).

Ported from ng911-pipeline models/intermediate/int_address_conflation.sql: same house number, within a
distance, best mutual nearest pair wins, in rounds (match()). One change: a pair whose street keys agree (street.py, the same key the
road check uses) ranks ahead of a nearer pair whose streets differ, and the pair records whether they agreed,
so a corner lot with the same number on two streets pairs with the right one.

Inputs: agency_addr and overture_addr, each with columns address number `number`, parsed street key `skey`,
geom, geoid. Output table address_match(address_uid, gers_id, distance_m, street_key_match).
After the pairs, copies(): an Overture address no Record paired that has a Record's number, street key and unit
within COPY_M is a second copy of that Record (Overture holds some agency points twice), linked to the Record's
Address UID (lineage link_method 'record_copy'), never a gap-fill candidate.
Statuses that follow from it:
    record             an agency Record (matched or not); the truth wherever it exists
    gap_fill_candidate an Overture address no Record matched, offered for the agency to accept or reject
"""

DEFAULT_MAX_M = 15.0  # the prototype's 0.00015 degrees, about 15 m in California
COPY_M = 25.0  # an unpaired Overture address this near a Record of the same full address is a copy of it
ROUNDS = 3  # rounds of best mutual pairs; each pairs what the round before left (stacked units, sim/problems/ng911-matcher-stacked-pairs)


def match(c, max_m=DEFAULT_MAX_M, rounds=ROUNDS):
    """Best mutual nearest pairs, in rounds. A pair whose street keys agree ranks first, then one whose units agree
    (blank = blank), then the nearer. One round alone leaves stacked points unpaired: Records for units 1 and 2 at
    one spot both rank the same Overture address first, so only one pair is mutual and the second Record's own copy
    became a gap-fill candidate. Later rounds pair what is left."""
    # ST_DWithin in degrees is the index-friendly prefilter (generous at high latitudes: 1 degree of longitude
    # shrinks with cos(latitude)); ST_Distance_Sphere decides in metres.
    deg = max_m / 111_320.0 * 2
    c.execute(f"""CREATE OR REPLACE TEMP TABLE _match_pairs AS
        SELECT a.address_uid, o.gers_id, ST_Distance_Sphere(a.geom, o.geom) AS distance_m,
               a.skey = o.skey AS street_key_match,
               upper(trim(coalesce(a.unit, ''))) = upper(trim(coalesce(o.unit, ''))) AS unit_match
        FROM agency_addr a JOIN overture_addr o
          ON a.geoid = o.geoid AND upper(a.number) = upper(o.number) AND ST_DWithin(a.geom, o.geom, {deg})""")
    c.execute("DELETE FROM _match_pairs WHERE distance_m > ?", [max_m])
    c.execute("""CREATE OR REPLACE TABLE address_match (address_uid VARCHAR, gers_id VARCHAR, distance_m DOUBLE,
                                                         street_key_match BOOLEAN)""")
    for _ in range(rounds):
        added = c.execute("""INSERT INTO address_match
            WITH open AS (
                SELECT * FROM _match_pairs
                WHERE address_uid NOT IN (SELECT address_uid FROM address_match)
                  AND gers_id NOT IN (SELECT gers_id FROM address_match)),
            ranked AS (
                SELECT *,
                       row_number() OVER (PARTITION BY address_uid
                                          ORDER BY street_key_match DESC, unit_match DESC, distance_m, gers_id) AS a_rn,
                       row_number() OVER (PARTITION BY gers_id
                                          ORDER BY street_key_match DESC, unit_match DESC, distance_m, address_uid) AS o_rn
                FROM open)
            SELECT address_uid, gers_id, round(distance_m, 2), street_key_match
            FROM ranked WHERE a_rn = 1 AND o_rn = 1""").fetchall()[0][0]
        if not added:
            break
    return c.execute("SELECT count(*) FROM address_match").fetchall()[0][0]


def copies(c, max_m=COPY_M):
    """address_copy(gers_id, address_uid, distance_m): each Overture address left unpaired by match() that has a
    Record of the same number, street key and unit (blank = blank) within max_m, with its nearest such Record.
    sim/problems/ng911-matcher-stacked-pairs A2."""
    deg = max_m / 111_320.0 * 2
    c.execute(f"""CREATE OR REPLACE TABLE address_copy AS
        SELECT o.gers_id, arg_min(a.address_uid, ST_Distance_Sphere(a.geom, o.geom)) AS address_uid,
               round(min(ST_Distance_Sphere(a.geom, o.geom)), 2) AS distance_m
        FROM overture_addr o JOIN agency_addr a
          ON a.geoid = o.geoid AND upper(a.number) = upper(o.number) AND a.skey = o.skey
         AND upper(trim(coalesce(a.unit, ''))) = upper(trim(coalesce(o.unit, '')))
         AND ST_DWithin(a.geom, o.geom, {deg})
        WHERE o.gers_id NOT IN (SELECT gers_id FROM address_match)
          AND ST_Distance_Sphere(a.geom, o.geom) <= {max_m}
        GROUP BY 1""")
    return c.execute("SELECT count(*) FROM address_copy").fetchall()[0][0]
