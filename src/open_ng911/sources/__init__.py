"""Readers that each create or fill one table on the build's DuckDB connection.

    package_area      one row per Package: geoid, name, geom            (tiger.py; statcan.py in Canada)
    municipality      A3 units: geoid, name, kind, incorporated, geom   (tiger.py; statcan.py in Canada)
    agency_addr       a Source agency's address points, plus agency_dropped (every point left out, by reason)
                                                                        (openaddresses.py)
    overture_addr     Overture addresses inside the job's Packages      (overture.py)
    road_seg          government centerlines, then TIGER ADDRFEAT where a Package has none, with
                      road_source_meta (one row per road source)        (centerlines.py)
    overture_segment  Overture road segments, for GERS IDs and counts only (ODbL, never written)  (overture.py)
    national_seg      the national road layer, compared with the government roads (centerlines.py)

Every loader is loader(c, job, jurisdiction, work_dir) (build.LIVE_LOADERS), so tests swap in fixtures
(tests/vt_fixtures.py, tests/pe_fixtures.py). What differs by country is in registry.COUNTRIES.
"""
