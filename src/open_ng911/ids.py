"""
Address UID and NGUID (ADR 0002).

Every real-world address gets one Address UID: derived from the Source agency's own ID where it has one,
otherwise minted the first time we see the address (from the Overture GERS ID it carried then) and carried
forward by the lineage ledger when Overture re-issues the ID. NGUIDs are built from the Address UID, never
from a GERS ID, which changes whenever any attribute or location changes.

The UIDs are UUIDv5s, so a rebuild of the same inputs gives the same UIDs:

    agency_uid('us-vt-e911', '123456')      -> uuid5(NS, 'record:us-vt-e911:123456')
    minted_uid('<gers id>')                  -> uuid5(NS, 'gers:<gers id>')   (first sighting only)

NGUID (NENA-STA-006.3):  urn:emergency:uid:gis:<layer>:<Address UID>:<agency domain>

The agency domain is the opted-in agency's own domain (ADR 0003, 0004). Until someone confirms from an address
on that domain, a package is built under a placeholder in the reserved `.invalid` TLD, so nothing we publish
can be mistaken for an agency's own identifier.
"""
import contextlib
import uuid

import duckdb

# Fixed namespace for this project's UUIDv5s. Changing it changes every Address UID and every NGUID.
NAMESPACE = uuid.UUID("6f1d7a3e-9b0c-5d2a-8e4f-0a6b1c2d3e4f")
PLACEHOLDER_TLD = "invalid"


def agency_uid(source_key, source_id):
    return str(uuid.uuid5(NAMESPACE, f"record:{source_key}:{source_id}"))


def minted_uid(gers_id):
    return str(uuid.uuid5(NAMESPACE, f"gers:{gers_id}"))


def placeholder_domain(package_key):
    """'us-vt-50007' -> 'us-vt-50007.unclaimed.invalid'"""
    return f"{package_key}.unclaimed.{PLACEHOLDER_TLD}"


def nguid(layer, address_uid, domain):
    return f"urn:emergency:uid:gis:{layer}:{address_uid}:{domain}"


def install(c):
    """The same functions as SQL, so a whole table gets its UIDs in one statement."""
    for name, fn in (("agency_uid", agency_uid), ("minted_uid", minted_uid)):
        with contextlib.suppress(duckdb.Error):  # not registered yet
            c.remove_function(name)
        args = ["VARCHAR", "VARCHAR"] if name == "agency_uid" else ["VARCHAR"]
        c.create_function(name, fn, args, "VARCHAR", side_effects=False)
    c.execute("""CREATE OR REPLACE MACRO build_nguid(layer, address_uid, domain) AS
                     'urn:emergency:uid:gis:' || layer || ':' || address_uid || ':' || domain""")
