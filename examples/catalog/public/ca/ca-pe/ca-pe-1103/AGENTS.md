# Using ca-pe-1103

- One Item per NENA layer; each Item's data asset is GeoParquet 2.0 (WGS 84, `geom`), rows in Hilbert order.
- Address points: `status = 'record'` rows are the agency's own; `gap_fill_candidate` rows are Overture
  addresses for the agency to check, not facts. Never treat a candidate as authoritative.
- `uid` is the stable key. `gers_id` is a link to Overture and can change between releases; NGUIDs are built
  from `uid`, never from a GERS ID.
- Roads: join `road_gers_crosswalk.parquet` on `uid` for every Overture segment along a road segment.
- `discrpagid` / NGUID domain `ca-pe-1103.unclaimed.invalid`.

```sql
-- DuckDB, from this collection's folder (or its https URL)
INSTALL spatial; LOAD spatial;
SELECT status, count(*) FROM read_parquet('ca-pe-1103-site-structure-address-point/site_structure_address_point.parquet') GROUP BY 1;
```
