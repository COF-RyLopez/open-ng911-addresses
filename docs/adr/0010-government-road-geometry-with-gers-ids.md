# Road centerlines are government geometry with GERS IDs attached

A Package's RoadCenterline layer is the Source agency's own centerlines, read from its endpoint through the
OpenAddresses source registry (or a registry entry written in OpenAddresses' schema until it is upstream), and
Census TIGER address-range features (ADDRFEAT, public domain) for a Package no government source covers.
Overture's road segments are read only to find which run along each of our segments; their GERS IDs go into the
Package (`gers_id` and a crosswalk file), their geometry and names do not, because Overture's transportation
theme is ODbL (OpenStreetMap). Overture's counsel told Ryan that GERS IDs aren't derivative and may be attached
to our own geometry (2026-11-26). The alternative, Overture's segments with agency attributes copied on, would
have been one join instead of a geometric crosswalk, but would have made every Package share-alike. Fallback is
by Package, not by road: a Package with any government centerlines uses only those, so a city-only source in a
county leaves the rest of that county without roads until its county source is found or a road-level TIGER fill
is built.
