# Story map and one-pager

A guided map and a one-page sheet that show what the pipeline delivers, built from the Phase 1 pilot builds.

- `index.html`: the story map (MapLibre, no server). Nine chapters walk through the NENA layers a Package carries
  (sources, A2, A3, SSAP, IDs, gap-fill, RCL, upstream, delivery), with a pilot switcher. It reads
  `pilots/<job>.json`.
- `extract.py`: writes `pilots/<job>.json` from a build: manifest counts and field fill, simplified A2/A3
  outlines (TIGER / StatCan), and address points only when every address source is open-licensed and the job has
  at most 150,000 Records (PEI today). Vermont and North Dakota (licence not stated) and Maine and Utah (too big
  to embed) show counts per county instead. No road geometry is embedded.
- `onepager.py`: writes `onepager.html` (letter landscape) from the same extracts. Print it to PDF, e.g. with
  Playwright: `page.pdf({ width: "11in", height: "8.5in", printBackground: true })`.

Refresh the data: Actions > **Story map data** > Run workflow. It builds the five pilots, runs the extractor and
commits `story/pilots/` to the branch it ran on.
