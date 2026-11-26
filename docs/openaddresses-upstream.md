# OpenAddresses, both ways

The build reads OpenAddresses' source files (CC0) for every address and centerline Source: endpoint, protocol
and field mapping. What we find goes back to them, and what they change comes back to us:

```
  our job finds a layer          oa_entry in the registry        OpenAddresses pull request
  OA doesn't list (or lists  ->  (OA's own schema; the build ->  (scripts/oa_upstream.py drafts it,
  wrongly)                        reads it meanwhile)              a person opens it)
                                                                         |
                                                                         v  merged; OA maintains it
  the affected jobs rebuild  <-  CI on that pull request     <-  weekly pin bump PR
  (only those)                    (oa_sync.py plan)               (oa-sync.yml, oa_sync.py bump)
```

## 1. Upstream: every new source or fix is drafted as an OpenAddresses pull request

1. **Write it as an `oa_entry`** in the job's registry, exactly as it should read in OpenAddresses
   (`sources/<country>/<state>/<name>.json`, layer `addresses`, `centerlines`, `parcels` or `buildings`):
   - only keys their schema has (`schema/layers/*_conform.json`; it rejects unknown ones), ESRI sources with
     `"format": "geojson"`, field names copied from the layer's `?f=json`;
   - their `map` function needs `else`; centerline `classification` uses their words (motorway, trunk, primary,
     secondary, tertiary, residential, service, unclassified; `motorway_link` has precedent), chosen by the
     road's role in the network;
   - a `filter` for features that aren't the layer's subject (ferries, proposed roads). Our reader ignores
     `filter`: the registry's `exclude` drops the same features and counts them (AGENTS.md);
   - licence and attribution as the publisher states them, or left out. Never a guessed licence.
   NENA detail their vocabulary can't hold (NENA RoadClass 'Ramp', 'Private') goes in `[source.nena]`.
2. **Draft it:** `python scripts/oa_upstream.py --oa <openaddresses checkout> --apply` writes each `new` or
   `fix` entry into the checkout and a pull request draft to `build/oa-upstream/<path>.md`. Then run
   `npm ci && npm test` in the checkout.
3. **A person opens it** from their own fork of openaddresses/openaddresses, one pull request per source file,
   after reviewing the draft. The draft says the opener isn't affiliated with the publisher; nobody opens one in
   an agency's name, and agents don't open them unprompted (ADR 0004).
4. **Once it merges**, the next pin bump lists the entry as `listed`. Drop the `oa_entry` (keep `openaddresses`
   and `oa_layer`): from then on OpenAddresses maintains it and their fixes reach us through the pin.

`registry/remediation/oa_proposals.csv` (from `scripts/license_remediation.py`) lists every `oa_entry` with
its status: `new`, `fix` or `listed`.

## 2. Downstream: an OpenAddresses change rebuilds the jurisdictions it touches

- `registry/openaddresses.toml` pins the OpenAddresses commit the build reads, and every manifest records it.
- `.github/workflows/oa-sync.yml` runs every Monday (or by hand): `oa_sync.py bump` moves the pin to their
  newest commit, and a draft pull request names each changed source file and the jobs that read it, plus our
  `oa_entry` blocks' status against the new pin. It then starts CI on that branch.
- CI's plan step (`oa_sync.py plan`) sees that the pin is the only change and builds just the affected
  enabled jobs. A job is affected when a source file it reads at the old or the new commit
  (`sources.openaddresses.source_paths`) was added, changed or removed, so a state that gains a county source
  rebuilds too. Any other change still builds every enabled job.
- Merging the pull request is the rebuild: the merge's push builds the same jobs on `main`.
