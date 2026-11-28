"""
The address matcher: pairs each Source agency Record with the Overture address for the same place, one to
one, so the Record keeps its own Address UID and gains the GERS ID (ADR 0001, 0002).

Ported from ng911-pipeline models/intermediate/int_address_conflation.sql: same house number, within a
distance, best mutual nearest pair wins, in rounds (match()). "Same number" is the full number the SSAP layer
writes (prefix + number + suffix, _number_keys), so a Source that keeps the suffix in its own field still pairs. One change: a pair whose street keys agree (street.py, the same key the
road check uses) ranks ahead of a nearer pair whose streets differ, and the pair records whether they agreed,
so a corner lot with the same number on two streets pairs with the right one.

Inputs: agency_addr and overture_addr, each with columns address number `number`, parsed street key `skey`,
geom, geoid (copies() also reads `street` and `unit`). Output table address_match(address_uid, gers_id, distance_m, street_key_match).
After the pairs, copies(): an Overture address no Record paired that has a Record's number, street key and unit
within COPY_M is a second copy of that Record (the number compared in full, suffix included: _number_keys) (Overture holds some agency points twice), linked to the Record's
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
    record_num, overture_num = _number_keys(c)  # the full number: '95' + suffix '1/2' pairs with Overture '95 1/2'
    c.execute(f"""CREATE OR REPLACE TEMP TABLE _match_pairs AS
        WITH a AS (SELECT a.*, {record_num} AS num FROM agency_addr a),
             o AS (SELECT o.*, {overture_num} AS num FROM overture_addr o)
        SELECT a.address_uid, o.gers_id, ST_Distance_Sphere(a.geom, o.geom) AS distance_m,
               a.skey = o.skey AS street_key_match,
               upper(trim(coalesce(a.unit, ''))) = upper(trim(coalesce(o.unit, ''))) AS unit_match
        FROM a JOIN o
          ON a.geoid = o.geoid AND a.num = o.num AND ST_DWithin(a.geom, o.geom, {deg})""")
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


def _number_keys(c):
    """SQL for the full house number on each side, as the SSAP layer writes it (AddNum_Pre + Add_Number +
    AddNum_Suf), with spaces dropped and upper-cased: a Record whose Source maps the suffix to its own field
    (VT HOUSE_NUMBERSUFFIX '1/2') has OpenAddresses number '95', while Overture holds '95 1/2'."""
    cols = {r[0] for r in c.execute("DESCRIBE agency_addr").fetchall()}
    pre = "coalesce(a.n_addnum_pre, '')" if "n_addnum_pre" in cols else "''"
    num = ("coalesce(CAST(a.n_add_number AS VARCHAR), regexp_extract(a.number, '^[0-9]+'))"
           if "n_add_number" in cols else "regexp_extract(a.number, '^[0-9]+')")
    rest = "trim(regexp_replace(a.number, '^[0-9]+', ''))"
    suf = f"coalesce(a.n_addnum_suf, {rest})" if "n_addnum_suf" in cols else rest
    record = f"upper(regexp_replace(concat({pre}, {num}, {suf}), '\\s', '', 'g'))"
    overture = "upper(regexp_replace(o.number, '\\s', '', 'g'))"
    return record, overture


def copies(c, max_m=COPY_M):
    """address_copy(gers_id, address_uid, distance_m): each Overture address left unpaired by match() that has a
    Record of the same number, street key and unit (blank = blank) within max_m, with its nearest such Record.
    The unpaired set is small, so it is cut first and joined on geoid + number (a hash join), not spatially.
    copy_misses() says why stacked ones are not copies. sim/problems/ng911-matcher-stacked-pairs A2-A5."""
    record_num, overture_num = _number_keys(c)
    c.execute(f"""CREATE OR REPLACE TABLE address_copy_pairs AS
        WITH o AS (SELECT gers_id, geoid, {overture_num} AS num, skey, upper(trim(coalesce(unit, ''))) AS unit,
                          street, geom
                   FROM overture_addr o WHERE gers_id NOT IN (SELECT gers_id FROM address_match)),
             a AS (SELECT a.*, {record_num} AS num FROM agency_addr a)
        SELECT o.gers_id, a.address_uid, round(ST_Distance_Sphere(a.geom, o.geom), 2) AS distance_m,
               a.skey = o.skey AS same_street, upper(trim(coalesce(a.unit, ''))) = o.unit AS same_unit,
               a.street AS record_street, o.street AS overture_street, a.unit AS record_unit, o.unit AS overture_unit
        FROM o JOIN a ON a.geoid = o.geoid AND a.num = o.num
        WHERE ST_Distance_Sphere(a.geom, o.geom) <= {max_m}""")
    c.execute("""CREATE OR REPLACE TABLE address_copy AS
        SELECT gers_id, arg_min(address_uid, distance_m) AS address_uid, min(distance_m) AS distance_m
        FROM address_copy_pairs WHERE same_street AND same_unit GROUP BY 1""")
    return c.execute("SELECT count(*) FROM address_copy").fetchall()[0][0]


def copy_misses(c, examples=5):
    """Why unpaired Overture addresses that sit on a Record's exact spot (same geoid, coordinates equal to 5
    decimals, about 1 m) are not copies: counts by which of number / street key / unit differ, and a few
    examples, for the scenario catalog."""
    record_num, overture_num = _number_keys(c)
    c.execute(f"""CREATE OR REPLACE TEMP TABLE address_copy_misses AS
        WITH o AS (SELECT gers_id, geoid, number, {overture_num} AS num, skey, street, unit,
                          round(ST_X(geom), 5) AS x, round(ST_Y(geom), 5) AS y
                   FROM overture_addr o WHERE gers_id NOT IN (SELECT gers_id FROM address_match)
                     AND gers_id NOT IN (SELECT gers_id FROM address_copy)),
             a AS (SELECT address_uid, geoid, number, {record_num} AS num, skey, street, unit,
                          round(ST_X(geom), 5) AS x, round(ST_Y(geom), 5) AS y
                   FROM agency_addr a)
        SELECT o.gers_id, a.num = o.num AS same_number, a.skey = o.skey AS same_street,
               upper(trim(coalesce(a.unit, ''))) = upper(trim(coalesce(o.unit, ''))) AS same_unit,
               a.number AS record_number, o.number AS overture_number, a.street AS record_street,
               o.street AS overture_street, a.unit AS record_unit, o.unit AS overture_unit
        FROM o JOIN a USING (geoid, x, y)""")
    rows = c.execute("""SELECT same_number, same_street, same_unit, count(DISTINCT gers_id) FROM address_copy_misses
        GROUP BY ALL ORDER BY 4 DESC""").fetchall()
    ex = c.execute(f"""SELECT * EXCLUDE (gers_id, same_number, same_street, same_unit) FROM address_copy_misses
        WHERE same_number ORDER BY gers_id LIMIT {examples}""").fetchall()
    ex_other = c.execute(f"""SELECT * EXCLUDE (gers_id, same_number, same_street, same_unit) FROM address_copy_misses
        WHERE NOT same_number ORDER BY gers_id LIMIT {examples}""").fetchall()
    return {"by_difference": [{"same_number": n, "same_street": s, "same_unit": u, "n": k} for n, s, u, k in rows],
            "examples_same_number": ex, "examples_other_number": ex_other}
