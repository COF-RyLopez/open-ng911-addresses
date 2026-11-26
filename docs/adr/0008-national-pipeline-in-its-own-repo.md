# The national pipeline lives in its own repo; ng911-pipeline stays the California prototype

The US + Canada build starts clean in open-ng911-addresses (Ryan, 2026-11-26) rather than growing out of
ng911-pipeline, which keeps running California's published apps. Much of the prototype's shape is what ADRs
0001, 0002 and 0007 changed: Overture as the base, NGUIDs built on GERS IDs, OSM-derived road fixes beside
county data. What already works is ported, not shared: the Overture release resolver, the street parse and
match key, the NENA registry mapping and the address matcher, each noting where it came from. The glossary
and ADRs 0001–0007 are copied here and continue here. The trade-off: a fix in one copy of the ported code
doesn't reach the other, so while both are maintained a fix is ported by hand.
