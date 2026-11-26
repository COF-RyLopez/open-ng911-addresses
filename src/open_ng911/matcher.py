"""
The address matcher: pairs each Source agency Record with the Overture address for the same place, one to
one, so the Record keeps its own Address UID and gains the GERS ID (ADR 0001, 0002).

Ported from ng911-pipeline models/intermediate/int_address_conflation.sql: same house number, within a
distance, best mutual nearest pair wins. One change: a pair whose street keys agree (street.py, the same key the
road check uses) ranks ahead of a nearer pair whose streets differ, and the pair records whether they agreed,
so a corner lot with the same number on two streets pairs with the right one.

Inputs: agency_addr and overture_addr, each with columns address number `number`, parsed street key `skey`,
geom, geoid. Output table address_match(address_uid, gers_id, distance_m, street_key_match).
Statuses that follow from it:
    record             an agency Record (matched or not); the truth wherever it exists
    gap_fill_candidate an Overture address no Record matched, offered for the agency to accept or reject
"""

DEFAULT_MAX_M = 15.0  # the prototype's 0.00015 degrees, about 15 m in California


def match(c, max_m=DEFAULT_MAX_M):
    # ST_DWithin in degrees is the index-friendly prefilter (generous at high latitudes: 1 degree of longitude
    # shrinks with cos(latitude)); ST_Distance_Sphere decides in metres.
    deg = max_m / 111_320.0 * 2
    c.execute(f"""CREATE OR REPLACE TABLE address_match AS
        WITH pairs AS (
            SELECT a.address_uid, o.gers_id, ST_Distance_Sphere(a.geom, o.geom) AS distance_m,
                   a.skey = o.skey AS street_key_match
            FROM agency_addr a JOIN overture_addr o
              ON a.geoid = o.geoid AND upper(a.number) = upper(o.number) AND ST_DWithin(a.geom, o.geom, {deg})),
        ranked AS (
            SELECT *,
                   row_number() OVER (PARTITION BY address_uid ORDER BY street_key_match DESC, distance_m, gers_id) AS a_rn,
                   row_number() OVER (PARTITION BY gers_id ORDER BY street_key_match DESC, distance_m, address_uid) AS o_rn
            FROM pairs WHERE distance_m <= {max_m})
        SELECT address_uid, gers_id, round(distance_m, 2) AS distance_m, street_key_match
        FROM ranked WHERE a_rn = 1 AND o_rn = 1""")
    return c.execute("SELECT count(*) FROM address_match").fetchall()[0][0]
