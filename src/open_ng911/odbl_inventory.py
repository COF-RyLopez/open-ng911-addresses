"""
The ODbL replacement inventory (docs/standards/upstream-path.md): for each Overture theme that is ODbL
(transportation, buildings, divisions, base), which government sources could stand in for it in each Package,
and how far along they are.

Per theme and Package:

    read        government sources this build actually read for the Package, with their licence status
    catalogued  layers the OpenAddresses catalogue lists for the Package's county or the whole state/province
                (registry/remediation/oa_sources.csv), with our first-read licence class; not read yet
    national    the open national layer that covers it anyway (TIGER, StatCan, USGS, NRCan), when there is one
    status      government_open      an open government source was read and covers the Package
                government_unclear   a government source was read, but its licence isn't open (yet)
                candidate            nothing read, but a catalogued or national open source exists
                none                 nothing known

It is an inventory, not a claim: whether a source could replace Overture's data is for the agency and Overture to
decide, and only open-licensed sources count (ADR 0004).
"""
import csv
import os

from . import registry

OA_SOURCES = os.path.join(os.path.dirname(__file__), "..", "..", "registry", "remediation", "oa_sources.csv")

# Overture theme -> (OpenAddresses layer that could replace it, national open layer by country)
THEMES = {
    "transportation": ("centerlines", {"US": "Census TIGER/Line ADDRFEAT (public domain)",
                                       "CA": "NRCan/StatCan National Road Network (OGL-Canada; loader to come)"}),
    "buildings": ("buildings", {}),  # no open national government footprints (Microsoft's are ODbL)
    "divisions": (None, {"US": "Census TIGER/Line boundaries (public domain)",
                         "CA": "Statistics Canada boundary files (Statistics Canada Open Licence)"}),
    "base_water": (None, {"US": "USGS NHD / 3D Hydrography Program (public domain; loader to come)",
                          "CA": "NRCan National Hydro Network (OGL-Canada; loader to come)"}),
}


def catalogue(path=OA_SOURCES):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def catalogued_for(rows, job, geoid, layer):
    """OA layers for this Package's county (US geoid) or the whole state/province."""
    region = job.code.lower()
    country = job.country.lower()
    return [{"oa_source": r["oa_source"], "oa_layer": r["oa_layer"], "license_class": r["license_class"]}
            for r in rows if r["country"] == country and r["region"] == region and r["layer"] == layer
            and (r["statewide"] == "1" or (country == "us" and r["geoid"] == geoid))]


def _status(read, catalogued, national):
    if any(r["license_status"] == "open" and r.get("covers") for r in read):
        return "government_open"
    if read:
        return "government_unclear"
    if national or catalogued:
        return "candidate"
    return "none"


def package_section(c, job, geoid, catalogue):
    out = {}
    roads = [{"source_key": k, "road_source": rs, "license_status": lic, "segments": int(n), "covers": True}
             for k, rs, lic, n in c.execute(f"""SELECT s.source_key, s.road_source, m.license_status, count(*)
                 FROM road_seg s LEFT JOIN road_source_meta m USING (source_key)
                 WHERE s.geoid = '{geoid}' GROUP BY ALL ORDER BY 1""").fetchall()]
    a3 = c.execute(f"SELECT count(*) FROM a3_polygon WHERE geoid = '{geoid}'").fetchall()[0][0]
    division = [{"source_key": registry.country(job).boundary_key,
                 "license_status": "open", "covers": True,
                 "what": "A2 / Package area" + (f", A3 ({a3} municipalities)" if a3 else "")}]
    read_by_theme = {"transportation": roads, "buildings": [], "divisions": division, "base_water": []}
    for theme, (oa_layer, national_by_country) in THEMES.items():
        read = read_by_theme[theme]
        cat = catalogued_for(catalogue, job, geoid, oa_layer) if oa_layer else []
        national = national_by_country.get(job.country)
        out[theme] = {"status": _status(read, cat, national),
                      "read": [{k: v for k, v in r.items() if k != "covers"} for r in read],
                      "catalogued": cat, "national": national}
    return out


def manifest_section(c, job, geoid, catalogue):
    """The `odbl_replacement` section of one Package's manifest. catalogue: catalogue() once per job."""
    return {**package_section(c, job, geoid, catalogue),
            "note": "Which government sources could stand in for Overture's ODbL themes here. An inventory, not a "
                    "claim; only open-licensed sources count, and a person proposes them (ADR 0004)."}


def job_totals(sections):
    """Packages per theme and status."""
    tot = {}
    for s in sections:
        for theme, v in s.items():
            if theme == "note":
                continue
            tot.setdefault(theme, {})
            tot[theme][v["status"]] = tot[theme].get(v["status"], 0) + 1
    return tot
