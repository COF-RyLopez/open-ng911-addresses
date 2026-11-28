"""
The Portolan catalog: one build's Packages as a static STAC 1.1 catalog that conforms to the Portolan spec
(https://github.com/portolan-sdi/portolan-spec), ready to push to Source Cooperative or any S3-compatible bucket.

    python -m open_ng911.catalog --release 2026-11-18.0 [--out data/output] [--catalog data/catalog]

It reads what the build jobs wrote under <out>/release=<release>/ (each Package's manifest.json and layer files)
and writes:

    <catalog>/report.json            every Package: published or withheld, and why. Not pushed.
    <catalog>/public/                the tree to push; nothing else under <catalog> goes out
        catalog.json README.md AGENTS.md
        scorecard/                   Collection: one row per Package, published or not (ADR 0003's public
                                     scorecard): counts, coverage, licence and opt-in state on the A2 outline
        us/  ca/                     Catalog per country
            us-me/                   Catalog per job (state or province)
                us-me-23001/         Collection per published Package: manifest.json and domains.json as
                                     metadata assets, a thumbnail, one Item per NENA layer
                    us-me-23001-site-structure-address-point/   Item: the layer's GeoParquet

A Package goes public when its address Sources are openly licensed (an `unknown` or `share-alike` address
Source keeps it out) and its job passed the gate (ADR 0011). Any other layer with a closed source is left out of
it on its own, and so is every Gap-fill candidate whose Overture source licence isn't open: the public copy of the
address points is written without those rows (ng911:withheld_gap_fill counts them). Opting in isn't required: a Package whose 911 authority hasn't opted in is published as
*unclaimed*, under its `.unclaimed.invalid` placeholder domain and labelled as not issued by that authority
(ADR 0003 as amended). A withheld Package is still a scorecard row and a
report.json entry, never a data file in public/. Layer files are hard-linked from the build output where the
filesystem allows it, so the public tree costs no extra disk.
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import struct
import zlib

import manby
import numpy as np

from . import db, registry

PORTOLAN = "https://schemas.portolan-sdi.org/portolan/v0.2.0/schema.json"
TABLE = "https://stac-extensions.github.io/table/v1.2.0/schema.json"
FILE = "https://stac-extensions.github.io/file/v2.1.0/schema.json"
WEB_MAP_LINKS = "https://stac-extensions.github.io/web-map-links/v1.3.0/schema.json"
STAC = "1.1.0"
PARQUET = "application/vnd.apache.parquet"
HOST = {"name": "open-ng911-addresses", "roles": ["processor", "host"],
        "url": "https://github.com/COF-RyLopez/open-ng911-addresses"}
COUNTRY_NAMES = {"US": "United States", "CA": "Canada"}

# The Package's layer files that become Items, in order: (file stem, NENA layer, what it is)
LAYERS = (
    ("site_structure_address_point", "SiteStructureAddressPoint",
     ("Every addressed site the Source agency publishes (Records), plus Overture addresses no Record matched "
     "(Gap-fill candidates, status = 'gap_fill_candidate').")),
    ("road_centerline", "RoadCenterline",
     ("The Source agency's own road centerlines, else Census TIGER address-range roads, each carrying the GERS "
     "IDs of the Overture road segments along it. No Overture geometry or names (ODbL) are in it.")),
    ("a2_polygon", "A2Polygon", "The county or census division the Package covers."),
    ("a3_polygon", "A3Polygon", "The municipalities in the Package, clipped to it."),
    # layers.py: written only where a Source publishes them (a missing file gets no Item)
    ("psap_polygon", "PsapPolygon", "PSAP service boundaries from the Source agency, cut to the Package."),
    ("police_polygon", "PolicePolygon", "Law enforcement service boundaries, cut to the Package."),
    ("fire_polygon", "FirePolygon", "Fire service boundaries, cut to the Package."),
    ("ems_polygon", "EmsPolygon", "EMS service boundaries, cut to the Package."),
    ("provisioning_polygon", "ProvisioningPolygon",
     "The area this Package's data is provisioned for: the Source's provisioning boundary, else the Package area."),
    ("distance_marker_point", "DistanceMarkerPoint", "Distance markers (mile or kilometre posts) along roads."),
    ("location_marker_point", "LocationMarkerPoint", "Location markers from the Source agency."),
)
CROSSWALK = "road_gers_crosswalk"

# Our own words for every column (NENA's field descriptions aren't copied; see scripts/nena_layer_reference.py)
COLUMNS = {
    "discrpagid": "Agency responsible for the row: the NGUID domain, a .invalid placeholder until the 911 "
                  "authority opts in",
    "dateupdate": "When the build last wrote or changed the row (UTC)",
    "effective": "When the boundary takes effect; empty when the source gives no date",
    "expire": "When the boundary stops applying; empty when the source gives no date",
    "nguid": "NENA globally unique ID, built from the row's own UID under discrpagid's domain (never a GERS ID)",
    "rcl_nguid": "NENA globally unique ID of the road segment, built from its UID under discrpagid's domain",
    "country": "Country code: US or CA",
    "a1": "State or province code",
    "a2": "County or census division name",
    "a3": "Municipality name, or 'Unincorporated' outside every municipality",
    "source_code": "The boundary's identifier in its source (Census GEOID or StatCan code)",
    "geom": "Geometry, WGS 84 longitude/latitude",
    "uid": "The project's stable ID: the Address UID for an address point, the segment UID for a road",
    "gers_id": "Overture GERS ID linked to this row (a reference that can change between Overture releases)",
    "gers_rcl_share": "Share of the segment's length its primary Overture segment runs along (0 to 1)",
    "road_source": "Where the segment came from: 'government' (the Source agency) or 'tiger' (Census TIGER)",
    "source": "Source key: the registry's Source agency layer, or 'overture' for a Gap-fill candidate",
    "source_id": "The row's own ID in its source",
    "source_license": "Licence of the row's source: the registry's status for agency data, Overture's "
                      "per-source licence for a Gap-fill candidate",
    "status": "'record' (the Source agency's own point) or 'gap_fill_candidate' (an Overture address to check)",
    "link_method": "How the Address UID was found: agency_record, minted, or carried over by the lineage ledger",
    "match_distance_m": "Distance in metres to the Overture address the Record matched",
    "street_key_match": "Whether the matched Overture address has the same parsed street",
    "source_site_type": "The source's own site type (e.g. PUBLIC TELEPHONE), kept as published",
    "add_number": "Address number",
    "addnum_suf": "Address number suffix (e.g. 'B' in 30B)",
    "st_predir": "Street name pre-directional, NENA registry word (e.g. North)",
    "st_pretyp": "Street name pre-type, NENA registry word (e.g. State Route; Rue in Canada)",
    "st_name": "Street name",
    "st_postyp": "Street name post-type, NENA registry word (e.g. Street)",
    "st_posdir": "Street name post-directional, NENA registry word",
    "unit": "Unit, suite or apartment",
    "post_comm": "Postal community name",
    "post_code": "Postal code or ZIP code",
    "placement": "How the point was placed on the site; 'Unknown' where the source doesn't say",
    "fromaddr_l": "First address number on the left side", "toaddr_l": "Last address number on the left side",
    "fromaddr_r": "First address number on the right side", "toaddr_r": "Last address number on the right side",
    "parity_l": "Parity of the left side's numbers (Odd, Even, Both, Zero)",
    "parity_r": "Parity of the right side's numbers (Odd, Even, Both, Zero)",
    "country_l": "Country code on the left side", "country_r": "Country code on the right side",
    "a1_l": "State or province code on the left side", "a1_r": "State or province code on the right side",
    "a2_l": "County or census division on the left side", "a2_r": "County or census division on the right side",
    "a3_l": "Municipality on the left side", "a3_r": "Municipality on the right side",
    "postcode_l": "Postal code on the left side", "postcode_r": "Postal code on the right side",
    "roadclass": "Road class, NENA registry word", "oneway": "One-way direction: B (both), FT or TF",
    "speedlimit": "Posted speed limit",
    **{f"derived_{f}_{side}": f"{what} on the {name} side, derived from the address points along it where the "
                             "agency publishes no range (ranges.py); not the agency's own value"
       for side, name in (("l", "left"), ("r", "right"))
       for f, what in (("fromaddr", "First address number"), ("toaddr", "Last address number"),
                       ("parity", "Parity of the address numbers"))},
    "range_points_l": "Address points checked against the left side's range",
    "range_points_r": "Address points checked against the right side's range",
    "overlap_m": "Length in metres along which the Overture segment runs with the road segment",
    "rcl_share": "Share of the road segment's length the overlap covers (0 to 1)",
    "segment_share": "Share of the Overture segment's length the overlap covers (0 to 1)",
    "is_primary": "Whether this is the Overture segment carried in road_centerline.gers_id",
    "overture_release": "The Overture release the GERS IDs come from",
}

# Licence names a Gap-fill candidate can carry from Overture's per-source licences that are open (no
# share-alike, no non-commercial); a row with any other licence, 'unstated' included, is left out of public/.
OPEN_LICENSE_PREFIXES = ("cc0", "cc-by", "cc by", "public domain", "pddl", "odc-by", "ogl", "open government",
                         "cdla-permissive", "us government", "u.s. government",
                         # Overture's SPDX-style tag for US government address data (NAD and state sources)
                         "licenseref-public-domain")
NON_COMMERCIAL = ("-nc", " nc", "noncommercial", "non-commercial")


def open_license(name):
    n = (name or "").strip().lower()
    if not n or "odbl" in n or "-sa" in n or " sa" in n or "share" in n or any(w in n for w in NON_COMMERCIAL):
        return False
    return n.startswith(OPEN_LICENSE_PREFIXES)


def held_gap_fill(m):
    """{licence: rows} of the Package's Gap-fill candidates whose Overture licence isn't open. Those rows are left
    out of the public copy of the address points (write_package); they never withhold the Package itself."""
    return {n: k for n, k in m["gap_fill_licenses"].items() if not open_license(n)}


def layer_reasons(m):
    """{layer file stem: why that layer can't go public} for every layer with a source that isn't open. The
    address points answer for their address Sources and the Overture licences of their Gap-fill candidates; the
    roads for the Sources the Package's roads came from; every other layer for its own Sources (layers.py). The
    boundaries are Census / StatCan, open by construction (registry.COUNTRIES)."""
    def closed(sources):
        return [f"source_license:{s['source_key']}={s['license_status']}"
                for s in sources if "license_status" in s and s["license_status"] != "open"]
    # Gap-fill rows with a closed licence don't close the layer: they are filtered out of it (held_gap_fill)
    out = {"site_structure_address_point": closed(s for s in m["sources"] if s["layer"] == "addresses"),
           "road_centerline": closed(m["road_centerline"]["sources"])}
    for stem, layer, _ in LAYERS:
        if layer in m.get("nena_layers", {}):
            out[stem] = closed(m["nena_layers"][layer]["sources"])
    return {k: sorted(set(v), key=v.index) for k, v in out.items() if v}


def withheld_reasons(m, job_summary, require_opt_in=False):
    """Why a Package can't go public at all; empty when it can. Its address points are its core: if they can't go,
    nothing does. Any other layer with a closed source is left out of a published Package on its own
    (layer_reasons). require_opt_in: also hold back a Package whose 911 authority hasn't opted in (ADR 0003
    before its 2026-11-26 amendment); off by default."""
    reasons = ["job_gate_failed"] if job_summary.get("gate_failures") else []
    reasons += layer_reasons(m).get("site_structure_address_point", [])
    if require_opt_in and not m["opted_in"]:
        reasons.append("not_opted_in")
    return reasons


# ---- files -------------------------------------------------------------------------------------------------

def checksum(path):
    """file:checksum as a multihash: 0x12 (sha2-256), 0x20 (32 bytes), then the digest."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "1220" + h.hexdigest()


def place(src, dst):
    """Hard-link the build's file into the public tree (copy across filesystems)."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        os.remove(dst)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def asset(path, href, roles, title, description, media_type):
    return {"href": href, "type": media_type, "roles": roles, "title": title, "description": description,
            "file:size": os.path.getsize(path), "file:checksum": checksum(path)}


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")


def write_md(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.strip() + "\n")


def doc_links():
    return [{"rel": "agents", "href": "./AGENTS.md", "type": "text/markdown", "title": "Agent/LLM usage guide"},
            {"rel": "describedby", "href": "./README.md", "type": "text/markdown",
             "title": "Human-readable documentation"}]


def nav(depth, parent="catalog.json"):
    """root and parent links from an object `depth` folders below the public root."""
    up = "../" * depth
    links = [{"rel": "root", "href": f"{up}catalog.json" if depth else "./catalog.json", "type": "application/json"}]
    if depth:
        links.append({"rel": "parent", "href": f"../{parent}", "type": "application/json"})
    return links


# ---- reading the parquet -------------------------------------------------------------------------------------

def columns(c, path):
    res = c.execute(f"DESCRIBE SELECT * FROM read_parquet({db.quote(path)})").fetchall()
    return [{"name": n, "type": t.lower(), **({"description": COLUMNS[n]} if n in COLUMNS else {})}
            for n, t, *_ in res]


def bbox(c, paths):
    """[xmin, ymin, xmax, ymax] over the files' geometries, or None when they hold no rows."""
    union = " UNION ALL ".join(f"SELECT geom FROM read_parquet({db.quote(p)})" for p in paths)
    r = c.execute(f"SELECT min(ST_XMin(geom)), min(ST_YMin(geom)), max(ST_XMax(geom)), max(ST_YMax(geom)) "
                  f"FROM ({union})").fetchall()[0]
    return None if r[0] is None else [round(float(v), 6) for v in r]


def box_polygon(b):
    x0, y0, x1, y1 = b
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def thumbnail(c, layers, path, size=256):
    """A PNG drawn from the layers' vertices with the default styling (outline, roads, points), so a client has
    a preview without reading the data. layers: [(parquet path, RGB)], drawn in order."""
    b = bbox(c, [p for p, _ in layers])
    img = np.full((size, size, 3), 255, dtype=np.uint8)
    if b:
        x0, y0, x1, y1 = b
        span = max(x1 - x0, y1 - y0) or 1e-6
        pad = (size - 1) * 0.05
        scale = (size - 1 - 2 * pad) / span
        for p, rgb in layers:
            # every geometry's parts as vertex lists: a point is a one-vertex part
            parts = c.execute(f"""SELECT list_transform(range(1, ST_NPoints(g) + 1),
                        lambda i: [ST_X(ST_PointN(g, i::INTEGER)), ST_Y(ST_PointN(g, i::INTEGER))]) FROM (
                    SELECT CASE WHEN ST_GeometryType(d) = 'POINT' THEN ST_MakeLine([d, d])
                                WHEN ST_GeometryType(d) = 'POLYGON' THEN ST_ExteriorRing(d) ELSE d END AS g
                    FROM (SELECT unnest(ST_Dump(geom)).geom AS d FROM read_parquet({db.quote(p)})))""").fetchall()
            for (verts,) in parts:
                v = np.array(verts, dtype=float)
                v = v.reshape(-1, 2)
                px = pad + (v[:, 0] - x0) * scale + (size - 1 - 2 * pad - (x1 - x0) * scale) / 2
                py = size - 1 - (pad + (v[:, 1] - y0) * scale + (size - 1 - 2 * pad - (y1 - y0) * scale) / 2)
                pts = [np.stack([px, py], 1)]
                for (ax, ay), (bx, by) in zip(pts[0][:-1], pts[0][1:]):
                    n = int(max(abs(bx - ax), abs(by - ay))) + 1
                    pts.append(np.stack([np.linspace(ax, bx, n), np.linspace(ay, by, n)], 1))
                q = np.clip(np.rint(np.concatenate(pts)).astype(int), 0, size - 1)
                img[q[:, 1], q[:, 0]] = rgb
                if len(v) == 2 and (v[0] == v[1]).all():  # a point: a 3x3 dot
                    cx, cy = q[0]
                    img[max(cy - 1, 0):cy + 2, max(cx - 1, 0):cx + 2] = rgb
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(size))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def visual(c, d, name, layers, title):
    """The PMTiles rendering derivative Portolan asks for, made with manby (tippecanoe's tiling, BSD-2-Clause),
    and its default MapLibre style. layers: [(layer name, parquet path, kind, colour)], kind one of fill, line,
    circle, drawn in order; empty layers are left out. Returns (links, assets) for the collection."""
    layers = [x for x in layers if c.execute(f"SELECT count(*) FROM read_parquet({db.quote(x[1])})").fetchall()[0][0]]
    pm = os.path.join(d, f"{name}.pmtiles")
    manby.tile({n: p for n, p, _, _ in layers}, pm, maximum_zoom="g", largest_maximum_zoom_guess=14,
               drop_densest_as_needed=True, quiet=True)
    paint = {"fill": lambda col: {"fill-color": col, "fill-opacity": 0.08, "fill-outline-color": col},
             "line": lambda col: {"line-color": col, "line-width": 1.5},
             "circle": lambda col: {"circle-color": col, "circle-radius": 3, "circle-stroke-color": "#ffffff",
                                    "circle-stroke-width": 0.5}}
    style = {"version": 8, "name": f"{title}: default", "sources": {"data": {"type": "vector",
                                                                             "url": f"pmtiles://../{name}.pmtiles"}},
             "layers": [{"id": "background", "type": "background", "paint": {"background-color": "#ffffff"}}]
             + [{"id": n, "type": kind, "source": "data", "source-layer": n, "paint": paint[kind](col)}
                for n, _, kind, col in layers]}
    write_json(os.path.join(d, "styles", "default.json"), style)
    names = [n for n, *_ in layers]
    link = {"rel": "pmtiles", "href": f"./{name}.pmtiles", "type": "application/vnd.pmtiles",
            "title": f"{title} (vector tiles)", "pmtiles:layers": names}
    return [link], {
        "pmtiles": asset(pm, f"./{name}.pmtiles", ["visual"], "Vector tiles",
                         f"PMTiles of {', '.join(names)} for web maps, made with manby.", "application/vnd.pmtiles"),
        "style-default": asset(os.path.join(d, "styles", "default.json"), "./styles/default.json", ["style", "default"],
                               "Default style", "MapLibre GL style for the vector tiles.",
                               "application/vnd.mapbox.style+json")}


# ---- the catalog ---------------------------------------------------------------------------------------------

def license_links(m):
    seen, links = set(), []
    for title, url in ([(s["agency"], s["license_url"]) for s in m["sources"] + m["road_centerline"]["sources"]]
                       + [(b["agency"], b["license_url"]) for b in m["boundaries"].values()]):
        if url and url not in seen:
            seen.add(url)
            links.append({"rel": "license", "href": url, "type": "text/html", "title": f"Licence: {title}"})
    return links


def providers(m, country):
    agencies = dict.fromkeys(s["agency"] for s in m["sources"] + m["road_centerline"]["sources"])
    out = [{"name": a, "roles": ["producer", "licensor"]} for a in agencies]
    out.append({"name": "U.S. Census Bureau" if country == "US" else "Statistics Canada", "roles": ["producer"],
                "url": "https://www.census.gov/geographies/mapping-files.html" if country == "US"
                else "https://www.statcan.gc.ca/en/census/geography"})
    if m["gap_fill_candidates"]:
        out.append({"name": "Overture Maps Foundation", "roles": ["producer"], "url": "https://overturemaps.org",
                    "description": "Addresses theme, for the Gap-fill candidates (per-source licences, not ODbL)"})
    return out + [HOST]


def via_links(m):
    links = []
    for s in m["sources"]:
        if s.get("openaddresses"):
            links.append({"rel": "via", "type": "text/html", "title": f"Source: {s['agency']} ({s['layer']})",
                          "href": f"https://github.com/openaddresses/openaddresses/blob/master/sources/"
                                  f"{s['openaddresses']}.json"})
    for s in m["road_centerline"]["sources"]:
        if s.get("data_url"):
            links.append({"rel": "via", "type": "text/html", "title": f"Service: {s['agency']}",
                          "href": s["data_url"]})
    return links


def write_package(c, m, job, built, src_dir, coll_dir):
    """One published Package: its Collection, an Item per non-empty NENA layer, and the metadata assets.
    Returns the collection's bbox."""
    key, country = m["package"], job.country
    items, extents, held, gap_held = [], [], layer_reasons(m), held_gap_fill(m)
    filtered = {}  # stem -> the public copy written in place of the build's file (thumbnail and tiles read it)
    for stem, layer, what in LAYERS:
        src = os.path.join(src_dir, f"{stem}.parquet")
        if not os.path.exists(src) or stem in held:
            continue  # not built here, or a closed source: left out (ng911:withheld_layers says which)
        b = bbox(c, [src])
        if b is None:
            continue  # an empty layer (no centerlines here yet) gets no Item; the manifest says why
        item_id = f"{key}-{stem.replace('_', '-')}"
        d = os.path.join(coll_dir, item_id)
        dst = os.path.join(d, f"{stem}.parquet")
        if stem == "site_structure_address_point" and gap_held:
            # a copy without the Gap-fill rows whose licence isn't open, never the build's own file
            os.makedirs(d, exist_ok=True)
            closed = ", ".join(db.quote(n) for n in gap_held)
            db.write_geoparquet(c, f"SELECT * FROM read_parquet({db.quote(src)}) WHERE NOT (status = "
                                   f"'gap_fill_candidate' AND coalesce(source_license, 'unstated') IN ({closed}))",
                                dst, "uid")
            filtered[stem] = dst
            b = bbox(c, [dst])
            if b is None:  # only closed Gap-fill rows here: no Item, like an empty layer
                shutil.rmtree(d)
                continue
        else:
            place(src, dst)
        extents.append(b)
        assets = {stem: asset(dst, f"./{stem}.parquet", ["data"], f"{layer} GeoParquet", what, PARQUET)}
        if stem == "road_centerline":
            xw = os.path.join(src_dir, f"{CROSSWALK}.parquet")
            place(xw, os.path.join(d, f"{CROSSWALK}.parquet"))
            assets[CROSSWALK] = asset(xw, f"./{CROSSWALK}.parquet", ["metadata"], "Road segment to GERS ID crosswalk",
                                      "Every road segment x Overture segment link with its overlap; join on uid.",
                                      PARQUET)
        n = c.execute(f"SELECT count(*) FROM read_parquet({db.quote(dst)})").fetchall()[0][0]
        write_json(os.path.join(d, f"{item_id}.json"), {
            "type": "Feature", "stac_version": STAC, "stac_extensions": [TABLE, FILE], "id": item_id,
            "collection": key, "geometry": box_polygon(b), "bbox": b,
            "properties": {"title": f"{m['name']}: {layer}", "description": what, "datetime": built,
                           "ng911:layer": layer, "table:row_count": n, "table:primary_geometry": "geom",
                           "table:columns": columns(c, src)},
            "links": nav(4, "collection.json") + [{"rel": "collection", "href": "../collection.json",
                                                   "type": "application/json"}],
            "assets": assets})
        items.append((item_id, f"{m['name']}: {layer}"))
    for name in ("manifest.json", "domains.json"):
        place(os.path.join(src_dir, name), os.path.join(coll_dir, name))
    def public(s):
        return filtered.get(s, os.path.join(src_dir, f"{s}.parquet"))
    shown = [s for s in ("a2_polygon", "a3_polygon", "road_centerline", "site_structure_address_point")
             if s not in held and os.path.exists(public(s))]
    colours = {"a2_polygon": ((60, 60, 60), "fill", "#3c3c3c"), "a3_polygon": ((200, 200, 200), "line", "#a0a0a0"),
               "road_centerline": ((230, 140, 40), "line", "#e68c28"),
               "site_structure_address_point": ((30, 90, 200), "circle", "#1e5ac8")}
    thumbnail(c, [(public(s), colours[s][0]) for s in shown],
              os.path.join(coll_dir, "thumbnail.png"))
    ext = [min(e[0] for e in extents), min(e[1] for e in extents), max(e[2] for e in extents),
           max(e[3] for e in extents)]
    vis_links, vis_assets = visual(c, coll_dir, key, [
        (s, public(s), colours[s][1], colours[s][2]) for s in shown], m["name"])
    rcl = m["road_centerline"]
    title = f"{m['name']}, {job.name}: NG9-1-1 Package" + ("" if m["opted_in"] else " (unclaimed)")
    desc = (f"The NENA NG9-1-1 GIS dataset for {m['name']} ({job.name}), built from the Source agencies' own "
            f"layers and reshaped to {m['nena']['standard']}: {m['records']:,} Records and "
            f"{m['gap_fill_candidates']:,} Gap-fill candidates, {rcl['features']:,} road segments. Recipient: "
            f"{m['recipient'] or 'no 911 authority in the registry yet'}."
            + ("" if m["opted_in"] else
               f" Unclaimed: built from open government sources, not issued or checked by "
               f"{m['recipient'] or 'a 911 authority'}; its NGUIDs use the placeholder domain {m['nguid_domain']} "
               "until the authority opts in."))
    if held:
        names = {s: n for s, n, _ in LAYERS}
        desc += (" Left out because a source's licence isn't open yet: "
                 + ", ".join(names[s] for s in held) + " (ng911:withheld_layers says which source).")
    if gap_held:
        desc += (f" {sum(gap_held.values()):,} Gap-fill candidates are left out of the address points because "
                 "their Overture source licence isn't open (ng911:withheld_gap_fill gives rows by licence).")
    coll = {
        "type": "Collection", "stac_version": STAC, "stac_extensions": [PORTOLAN, TABLE, FILE, WEB_MAP_LINKS],
        "id": key,
        "title": title, "description": desc, "license": "other", "updated": built,
        "keywords": ["NG9-1-1", "NENA", "addresses", "road centerlines", job.name, m["name"],
                     *([] if m["opted_in"] else ["unclaimed"])],
        "providers": providers(m, country),
        "extent": {"spatial": {"bbox": [ext]}, "temporal": {"interval": [[built, built]]}},
        "ng911:package": key, "ng911:job": m["job"], "ng911:recipient": m["recipient"],
        "ng911:opted_in": m["opted_in"], "ng911:nguid_domain": m["nguid_domain"],
        "ng911:nena_standard": m["nena"]["standard"], "ng911:value_domains": m["nena"]["values"],
        "ng911:overture_release": m["overture_release"],
        **({"ng911:openaddresses_commit": m["openaddresses_commit"]} if m.get("openaddresses_commit") else {}),
        "ng911:records": m["records"],
        "ng911:gap_fill_candidates": m["gap_fill_candidates"], "ng911:record_gers_coverage": m["record_gers_coverage"],
        "ng911:road_segments": rcl["features"], "ng911:road_gers_coverage": rcl["gers_coverage"],
        "ng911:road_source": rcl["road_source"] if "road_centerline" not in held else None,
        "ng911:withheld_layers": held,
        "ng911:withheld_gap_fill": gap_held,
        "links": nav(3) + [{"rel": "item", "href": f"./{i}/{i}.json", "type": "application/geo+json", "title": t}
                           for i, t in items] + vis_links + license_links(m) + via_links(m) + doc_links(),
        "assets": {
            "manifest": asset(os.path.join(coll_dir, "manifest.json"), "./manifest.json", ["metadata"],
                              "Package manifest", "Counts, NENA field coverage, every source with its licence and date, "
                              "opt-in state, upstream counts and the ODbL replacement inventory.", "application/json"),
            "domains": asset(os.path.join(coll_dir, "domains.json"), "./domains.json", ["metadata"],
                             "Value domains", f"The value domains the layers use ({m['nena']['values']}).",
                             "application/json"),
            "thumbnail": asset(os.path.join(coll_dir, "thumbnail.png"), "./thumbnail.png", ["thumbnail"],
                               "Thumbnail", "Outline, municipalities, roads and address points.", "image/png"),
            **vis_assets,
        },
    }
    write_json(os.path.join(coll_dir, "collection.json"), coll)
    write_md(os.path.join(coll_dir, "README.md"), package_readme(m, coll, items))
    write_md(os.path.join(coll_dir, "AGENTS.md"), package_agents(m, items))
    return ext


def package_readme(m, coll, items):
    srcs = "\n".join(f"- {s['agency']} ({s['layer']}): licence {s['license_status']}, {s['license_url']}"
                     for s in m["sources"])
    bnd = "\n".join(f"- {k}: {b['agency']} ({b['license']}), {b['license_url']}" for k, b in m["boundaries"].items())
    gap = ", ".join(f"{k} ({v:,})" for k, v in m["gap_fill_licenses"].items()) or "none"
    layers = "\n".join(f"- [{t}](./{i}/{i}.json)" for i, t in items)
    return f"""
# {coll['title']}

{coll['description']}

## Layers

{layers}

`manifest.json` holds the full numbers: NENA field coverage per layer, sources with dates, the GERS release, the
upstream counts and which government sources could stand in for Overture's ODbL themes here.

## Licence

Each layer keeps its sources' licences; no OpenStreetMap-derived geometry or names are in any layer.

{srcs}
{bnd}
- Gap-fill candidates: Overture's per-source licences: {gap}

## Provenance

Built by [open-ng911-addresses]({HOST['url']}) from the Source agencies' layers, read through the OpenAddresses
source registry{f" at commit `{m['openaddresses_commit'][:12]}`" if m.get('openaddresses_commit') else ''}, and Overture
release {m['overture_release']}. NGUIDs are under `{m['nguid_domain']}`.
This is a processed copy: the agencies' own services are the authoritative data (see the `via` links).
"""


def package_agents(m, items):
    ssap = next((i for i, _ in items if i.endswith("site-structure-address-point")), None)
    q = (f"SELECT status, count(*) FROM read_parquet('{ssap}/site_structure_address_point.parquet') GROUP BY 1;"
         if ssap else "-- no address points in this Package")
    return f"""
# Using {m['package']}

- One Item per NENA layer; each Item's data asset is GeoParquet 2.0 (WGS 84, `geom`), rows in Hilbert order.
- Address points: `status = 'record'` rows are the agency's own; `gap_fill_candidate` rows are Overture
  addresses for the agency to check, not facts. Never treat a candidate as authoritative.
- `uid` is the stable key. `gers_id` is a link to Overture and can change between releases; NGUIDs are built
  from `uid`, never from a GERS ID.
- Roads: join `road_gers_crosswalk.parquet` on `uid` for every Overture segment along a road segment.
- `discrpagid` / NGUID domain `{m['nguid_domain']}`.{"" if m["opted_in"] else " Unclaimed: the 911 authority hasn't "
  "opted in, so this is not its dataset and the domain is a placeholder; don't present it as the authority's."}

```sql
-- DuckDB, from this collection's folder (or its https URL)
INSTALL spatial; LOAD spatial;
{q}
```
"""


def scorecard(c, rows, d):
    """The public scorecard collection: one GeoParquet row per Package on its A2 outline."""
    os.makedirs(d, exist_ok=True)
    c.execute("""CREATE OR REPLACE TEMP TABLE scorecard (package VARCHAR, name VARCHAR, job VARCHAR,
        country VARCHAR, recipient VARCHAR, opted_in BOOLEAN, published BOOLEAN, withheld_reasons VARCHAR[],
        overture_release VARCHAR, records BIGINT, gap_fill_candidates BIGINT, record_gers_coverage DOUBLE,
        road_segments BIGINT, road_gers_coverage DOUBLE, road_source VARCHAR, collection VARCHAR, a2 VARCHAR)""")
    c.executemany("INSERT INTO scorecard VALUES (" + ", ".join("?" * 17) + ")", rows)
    path = os.path.join(d, "scorecard.parquet")
    files = "[" + ", ".join(db.quote(r[-1]) for r in rows) + "]"
    db.write_geoparquet(c, f"""SELECT s.* EXCLUDE (a2), a.geom FROM scorecard s JOIN (
            SELECT filename, ST_Union_Agg(geom) AS geom FROM read_parquet({files}, filename = true) GROUP BY 1) a
        ON a.filename = s.a2""", path, "package")
    return path


SCORECARD_COLUMNS = {
    "package": "Package key: <job>-<county or census division code>", "name": "County or census division",
    "job": "Build job (state or province)", "country": "US or CA", "recipient": "The 911 authority it is built for",
    "opted_in": "Whether the 911 authority has opted in; a published Package that hasn't is unclaimed",
    "published": "Whether the Package's data is in this catalog",
    "withheld_reasons": "Why its data isn't: an address Source licence that isn't open, or a "
                        "failed gate",
    "overture_release": "Overture release the build used", "records": "The Source agency's address points",
    "gap_fill_candidates": "Overture addresses no Record matched",
    "record_gers_coverage": "Share of Records with a GERS ID", "road_segments": "Road centerline segments",
    "road_gers_coverage": "Share of road segments with a GERS ID",
    "road_source": "government (the agency's own) or tiger", "collection": "Path of its collection.json, if published",
    "geom": "The county or census division outline (A2Polygon), WGS 84",
}


def build(release, out_dir="data/output", catalog_dir="data/catalog", registry_dir=registry.REGISTRY_DIR,
          require_opt_in=False, c=None):
    """Write the catalog for one release; returns report.json's content."""
    rel_dir = os.path.join(out_dir, f"release={release}")
    pub = os.path.join(catalog_dir, "public")
    if os.path.exists(pub):
        shutil.rmtree(pub)  # rebuilt whole each time: a withdrawn Package must not linger
    c = c or db.connect(s3=False)
    jobs = {j.id: j for j in registry.jobs(registry_dir)}
    report, cards, tree, built = {"release": release, "published": [], "withheld": []}, [], {}, []
    for job_json in sorted(glob.glob(os.path.join(rel_dir, "*", "job.json"))):
        with open(job_json) as f:
            summary = json.load(f)
        job = jobs[summary["job"]]
        built.append(summary["built"])
        for mpath in sorted(glob.glob(os.path.join(os.path.dirname(job_json), "*", "manifest.json"))):
            with open(mpath) as f:
                m = json.load(f)
            src = os.path.dirname(mpath)
            reasons = withheld_reasons(m, summary, require_opt_in)
            href = None
            if not reasons:
                coll_dir = os.path.join(pub, job.country.lower(), job.id, m["package"])
                ext = write_package(c, m, job, summary["built"], src, coll_dir)
                held = layer_reasons(m)
                tree.setdefault(job.country, {}).setdefault(job.id, []).append((m["package"], m["name"], ext))
                href = f"{job.country.lower()}/{job.id}/{m['package']}/collection.json"
                report["published"].append({"package": m["package"], "collection": href, "withheld_layers": held,
                                            "withheld_gap_fill": held_gap_fill(m)})
            else:
                report["withheld"].append({"package": m["package"], "reasons": reasons})
            cards.append((m["package"], m["name"], m["job"], job.country, m["recipient"], m["opted_in"], not reasons,
                          reasons, m["overture_release"], m["records"], m["gap_fill_candidates"],
                          m["record_gers_coverage"], m["road_centerline"]["features"],
                          m["road_centerline"]["gers_coverage"], m["road_centerline"]["road_source"], href,
                          os.path.join(src, "a2_polygon.parquet")))
    write_tree(c, pub, release, tree, cards, jobs, max(built) if built else db.now())
    write_json(os.path.join(catalog_dir, "report.json"), report)
    return report


def write_tree(c, pub, release, tree, cards, jobs, updated):
    children = []
    if cards:
        d = os.path.join(pub, "scorecard")
        path = scorecard(c, cards, d)
        ext = bbox(c, [path])
        thumbnail(c, [(path, (60, 60, 60))], os.path.join(d, "thumbnail.png"))
        vis_links, vis_assets = visual(c, d, "scorecard", [("scorecard", path, "fill", "#3c3c3c")], "Package scorecard")
        n_pub = sum(1 for r in cards if r[6])
        countries = sorted({r[3] for r in cards})
        boundary_links = [{"rel": "license", "type": "text/html", "href": registry.COUNTRIES[k].boundary_license_url,
                           "title": f"Licence: {registry.COUNTRIES[k].a2_source}"} for k in countries]
        coll = {
            "type": "Collection", "stac_version": STAC, "stac_extensions": [PORTOLAN, TABLE, FILE, WEB_MAP_LINKS],
            "id": "scorecard",
            "title": "Package scorecard",
            "description": f"Every Package built for Overture release {release}, {len(cards):,} in all and "
                           f"{n_pub:,} published here: counts, GERS coverage, licence and opt-in state, on each "
                           "county or census division outline. Withheld Packages appear here with their reasons "
                           "and no address data.",
            "license": "other", "updated": updated, "keywords": ["NG9-1-1", "scorecard", "coverage"],
            "providers": [{"name": registry.COUNTRIES[k].a2_source, "roles": ["producer"],
                           "url": registry.COUNTRIES[k].boundary_license_url} for k in countries] + [HOST],
            "extent": {"spatial": {"bbox": [ext]}, "temporal": {"interval": [[None, None]]}},
            "table:columns": [{**col, **({"description": SCORECARD_COLUMNS[col["name"]]}
                                          if col["name"] in SCORECARD_COLUMNS else {})} for col in columns(c, path)],
            "table:row_count": len(cards), "table:primary_geometry": "geom",
            "links": nav(1) + vis_links + boundary_links + [
                {"rel": "via", "type": "text/html", "href": registry.COUNTRIES[k].boundary_license_url,
                 "title": f"Outlines: {registry.COUNTRIES[k].a2_source}"} for k in countries] + doc_links(),
            "assets": {"data": asset(path, "./scorecard.parquet", ["data"], "Scorecard GeoParquet",
                                     "One row per Package.", PARQUET),
                       "thumbnail": asset(os.path.join(d, "thumbnail.png"), "./thumbnail.png", ["thumbnail"],
                                          "Thumbnail", "Package outlines.", "image/png"), **vis_assets}}
        write_json(os.path.join(d, "collection.json"), coll)
        write_md(os.path.join(d, "README.md"), f"""
# Package scorecard

{coll['description']}

Licence: the outlines are {', '.join(f"{registry.COUNTRIES[k].a2_source} ({registry.COUNTRIES[k].boundary_license})"
                                    for k in countries)}; the counts are the project's own.
Provenance: each build job's manifest.json, from [open-ng911-addresses]({HOST['url']}).
""")
        write_md(os.path.join(d, "AGENTS.md"), """
# Using the scorecard

One row per Package. `published` says whether its data is in this catalog (then `collection` is the path to
its collection.json); `withheld_reasons` says why not. Counts only: no address or road data is in this file.

```sql
INSTALL spatial; LOAD spatial;
SELECT job, count(*) packages, count(*) FILTER (published) published, sum(records) records
FROM read_parquet('scorecard.parquet') GROUP BY 1 ORDER BY 1;
```
""")
        children.append(("scorecard/collection.json", "Package scorecard"))
    for country, by_job in sorted(tree.items()):
        cdir = os.path.join(pub, country.lower())
        for job_id, colls in sorted(by_job.items()):
            name = jobs[job_id].name
            sub_catalog(os.path.join(cdir, job_id), job_id, f"{name}: NG9-1-1 Packages", 2, updated,
                        f"Published Packages for {name}, one collection per "
                        f"{registry.COUNTRIES[country].packages.replace('_', ' ')}.",
                        [(f"{p}/collection.json", f"{n}, {name}") for p, n, _ in colls])
        sub_catalog(cdir, country.lower(), f"{COUNTRY_NAMES[country]}: NG9-1-1 Packages", 1, updated,
                    f"Published Packages in {COUNTRY_NAMES[country]}, by state or province.",
                    [(f"{j}/catalog.json", f"{jobs[j].name}: NG9-1-1 Packages") for j in sorted(by_job)])
        children.append((f"{country.lower()}/catalog.json", f"{COUNTRY_NAMES[country]}: NG9-1-1 Packages"))
    sub_catalog(pub, "open-ng911-addresses", "Open NG9-1-1 address packages", 0, updated,
                f"Open-data NENA NG9-1-1 address packages for the 911 authorities of the US and Canada, Overture "
                f"release {release}. Only Packages whose every source is openly licensed carry data here; one whose "
                "911 authority hasn't opted in is marked unclaimed. The scorecard lists every Package.", children)


def sub_catalog(d, cat_id, title, depth, updated, description, children):
    links = nav(depth) + [{"rel": "child", "href": f"./{h}", "type": "application/json", "title": t}
                          for h, t in children] + doc_links()
    write_json(os.path.join(d, "catalog.json"), {"type": "Catalog", "stac_version": STAC,
                                                 "stac_extensions": [PORTOLAN], "id": cat_id, "title": title,
                                                 "description": description, "updated": updated,
                                                 "links": links})
    listing = "\n".join(f"- [{t}](./{h})" for h, t in children) or "- (nothing published yet)"
    write_md(os.path.join(d, "README.md"), f"""
# {title}

{description}

{listing}

Licence: each collection states its own; data keeps its sources' licences (README of each collection).
Provenance: built by [open-ng911-addresses]({HOST['url']}) from government sources and Overture addresses.
""")
    write_md(os.path.join(d, "AGENTS.md"), f"""
# {title}

A static STAC 1.1 catalog (Portolan). Follow `child` links to collections; each Package collection has one Item
per NENA layer, with GeoParquet 2.0 data assets readable over HTTP range requests (DuckDB `read_parquet`).
Start with `scorecard/` for what exists and what is withheld.
""")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[0])
    p.add_argument("--release", help="the Overture release the builds used; default: the newest under --out")
    p.add_argument("--out", default="data/output", help="the build output folder")
    p.add_argument("--catalog", default="data/catalog")
    a = p.parse_args(argv)
    found = sorted(d.split("=", 1)[1] for d in os.listdir(a.out) if d.startswith("release="))
    if not (a.release or found):
        raise SystemExit(f"No release=* folder under {a.out}: run a build first")
    r = build(a.release or found[-1], a.out, a.catalog)
    print(json.dumps({"release": r["release"], "published": len(r["published"]), "withheld": len(r["withheld"])}))


if __name__ == "__main__":
    main()
