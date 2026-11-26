# Using the scorecard

One row per Package. `published` says whether its data is in this catalog (then `collection` is the path to
its collection.json); `withheld_reasons` says why not. Counts only: no address or road data is in this file.

```sql
INSTALL spatial; LOAD spatial;
SELECT job, count(*) packages, count(*) FILTER (published) published, sum(records) records
FROM read_parquet('scorecard.parquet') GROUP BY 1 ORDER BY 1;
```
