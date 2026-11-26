"""Readers that each create one table on the build's DuckDB connection.

    package_area    one row per Package: geoid, name, geom             (tiger.py; statcan.py census divisions for Canada)
    agency_addr     a Source agency's address points                   (openaddresses.py)
    overture_addr   Overture addresses inside the job's Packages       (overture.py)

The build takes them as a mapping of loaders, so tests swap in fixtures (tests/fixtures/).
"""
