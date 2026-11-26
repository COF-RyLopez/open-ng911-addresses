"""
The one-page story sheet: what the pipeline builds, with the pilots' real numbers.

    python story/onepager.py                 # writes story/onepager.html from story/pilots/*.json
    (then print it to PDF; story/README.md has the one-liner)

Every number comes from the build extracts in story/pilots/ (story/extract.py), so the sheet is rebuilt, not
retyped, when the pilots are.
"""
import html
import json
import os

HERE = os.path.dirname(__file__)
PILOTS = [("us-vt", "Vermont", "county"), ("us-me", "Maine", "county"), ("us-ut", "Utah", "county"),
          ("us-nd", "North Dakota", "county"), ("ca-pe", "Prince Edward Island", "census division")]

# NENA-STA-006.3 layers and what a Phase 1 Package carries (docs/standards/gap-review.md)
LAYERS = [
    ("SiteStructureAddressPoint", "Required", "filled"), ("RoadCenterLine", "Required", "roads"),
    ("A2Polygon · county / CD", "Strongly rec.", "filled"), ("A3Polygon · municipality", "Strongly rec.", "filled"),
    ("A1Polygon · state / province", "Strongly rec.", "gap"), ("ProvisioningPolygon", "Required", "gap"),
    ("PSAP, Police, Fire, EMS", "Required", "agency"), ("A4 / A5 Polygons", "Strongly rec.", "gap"),
    ("SiteStructureAddressPolygon", "Recommended", "gap"), ("Location / Distance markers", "Recommended", "gap"),
    ("Rail, Hydrology", "Recommended", "gap"),
]
SSAP_US = 56   # NENA-STA-006.3 SSAP fields used in the US (58 less AddCode and Unit)


def fmt(n):
    return f"{n:,}" if isinstance(n, int) else str(n)


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "–"


def load():
    out = {}
    for job, name, unit in PILOTS:
        path = os.path.join(HERE, "pilots", f"{job}.json")
        with open(path, encoding="utf-8") as f:
            out[job] = json.load(f)
    return out


def fill_stats(d):
    rows = sum(p["rows"] for p in d["packages"])
    ff = {}
    for p in d["packages"]:
        for k, v in p["field_fill"].items():
            if v is not None:
                ff[k] = ff.get(k, 0) + v * p["rows"]
    return {k: v / rows for k, v in ff.items()} if rows else {}


def page(data):
    e = html.escape
    tot = {k: sum(d["job"].get(k) or 0 for d in data.values())
           for k in ("records", "records_with_gers_id", "gap_fill_candidates", "rows", "packages", "road_segments")}
    a3 = sum((d["job"].get("a3") or {}).get("a3_polygons", 0) for d in data.values())
    vt = data["us-vt"]["job"]
    vt_nat, vt_ov = vt["upstream"]["national"], vt["upstream"]["overture"]
    release = data["us-vt"]["job"]["overture_release"]

    rows = []
    for job, name, unit in PILOTS:
        j = data[job]["job"]
        addr = [s for s in data[job]["sources"] if s["layer"] == "addresses"]
        lic = "open" if all(s["license_status"] == "open" for s in addr) else "not stated"
        roads = j.get("road_segments") or 0
        rows.append(f"""<tr><th>{e(name)}</th><td>{fmt(j['packages'])}</td><td>{fmt(j['records'])}</td>
            <td>{pct(j['records_with_gers_id'], j['records'])}</td><td>{fmt(j['gap_fill_candidates'])}</td>
            <td>{fmt((j.get('a3') or {}).get('a3_polygons', 0))}</td>
            <td>{fmt(roads) if roads else '<span class="gapt">none yet</span>'}</td>
            <td>{pct(j.get('road_segments_with_gers_id') or 0, roads) if roads else '–'}</td>
            <td><span class="lic {'open' if lic == 'open' else 'unk'}">{lic}</span></td></tr>""")

    us_fill = fill_stats(data["us-vt"])
    filled = sum(1 for v in us_fill.values() if v >= 0.995)
    partial = sum(1 for v in us_fill.values() if 0 < v < 0.995)
    roads_any = any((d["job"].get("road_segments") or 0) for d in data.values())
    layer_rows = []
    for name, lvl, st in LAYERS:
        if st == "roads":
            st = "partial" if roads_any else "gap"
            note = "US pilots: agency roads, GERS IDs; Canada: next"
        else:
            note = {"filled": "every Package", "gap": "planned", "agency": "authority supplies"}[st]
        if name.startswith("SiteStructure") and st == "filled":
            note = f"{filled} of {SSAP_US} US fields filled, {partial} partly"
        if name.startswith("A1"):
            note = "next: cheapest gap"
        if name.startswith("Provisioning"):
            note = "next: the Package area"
        label = {"filled": "Filled", "partial": "Partial", "gap": "Gap", "agency": "Authority"}[st]
        layer_rows.append(f"""<tr><th>{e(name)}<small>{e(lvl)}</small></th><td><span class="st {st}">{label}</span></td>
            <td class="note">{e(note)}</td></tr>""")

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Open NG9-1-1 Addresses: what the pipeline builds</title>
<style>
@page {{ size: 11in 8.5in; margin: 0; }}
:root {{ --ink: #0f1d21; --muted: #5d6f74; --line: #d5dee0; --paper: #ffffff; --wash: #f2f6f6;
  --ssap: #c98a12; --gers: #138f89; --gap: #c2457b; --a2: #4659b8; --up: #d4561f; --ok: #2f9a68; --part: #c98a12; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--paper); color: var(--ink); font: 9.2pt/1.38 "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif; }}
.sheet {{ width: 11in; height: 8.5in; padding: .42in .5in .36in; display: grid; grid-template-rows: auto auto 1fr auto; gap: .17in; }}
header {{ display: flex; justify-content: space-between; align-items: flex-end; gap: .3in; border-bottom: 2px solid var(--ink); padding-bottom: .1in; }}
.eyebrow {{ font: 500 7.4pt/1 "IBM Plex Mono", Menlo, monospace; letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }}
h1 {{ margin: .05in 0 0; font: 800 21pt/1.05 "Archivo", "Helvetica Neue", Arial, sans-serif; letter-spacing: -.01em; }}
.lede {{ max-width: 4.6in; color: #33474c; font-size: 9pt; }}
.big {{ display: flex; gap: .26in; }}
.big div {{ text-align: right; }}
.big b {{ display: block; font: 800 17pt/1 "Archivo", Arial, sans-serif; font-variant-numeric: tabular-nums; }}
.big span {{ font-size: 7.4pt; color: var(--muted); }}
svg text {{ font-family: "IBM Plex Sans", Arial, sans-serif; }}
.flow {{ width: 100%; height: auto; }}
.cols {{ display: grid; grid-template-columns: 1.3fr 1fr; gap: .28in; min-height: 0; }}
h2 {{ margin: 0 0 .06in; font: 700 10.5pt/1.2 "Archivo", Arial, sans-serif; display: flex; justify-content: space-between; align-items: baseline; }}
h2 small {{ font: 400 7.4pt "IBM Plex Mono", monospace; color: var(--muted); }}
table {{ border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }}
.pilots th, .pilots td {{ padding: 3.5px 5px; border-bottom: 1px solid var(--line); text-align: right; font-size: 8.4pt; white-space: nowrap; }}
.pilots thead th {{ font: 500 6.8pt/1.2 "IBM Plex Mono", monospace; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; vertical-align: bottom; white-space: normal; }}
.pilots tbody th, .pilots thead th:first-child {{ text-align: left; font-weight: 600; }}
.pilots tfoot th, .pilots tfoot td {{ font-weight: 700; border-bottom: 0; border-top: 1.5px solid var(--ink); }}
.gapt {{ color: var(--muted); font-style: italic; }}
.lic {{ font: 500 7pt "IBM Plex Mono", monospace; padding: 1px 4px; border-radius: 2px; }}
.lic.open {{ background: #dff1e8; color: #1d6e47; }}
.lic.unk {{ background: #f6ecd7; color: #7d5a0c; }}
.up {{ margin-top: .14in; display: grid; grid-template-columns: repeat(4, 1fr); gap: .1in; }}
.up div {{ border-left: 3px solid var(--up); padding: 2px 0 2px 7px; }}
.up b {{ display: block; font: 800 13pt/1.05 "Archivo", Arial, sans-serif; font-variant-numeric: tabular-nums; }}
.up span {{ font-size: 7.4pt; color: var(--muted); line-height: 1.25; display: block; }}
.upnote {{ font-size: 7.6pt; color: var(--muted); margin-top: .06in; }}
.grid th, .grid td {{ padding: 2.6px 5px; border-bottom: 1px solid var(--line); text-align: left; font-size: 8.2pt; vertical-align: middle; }}
.grid th small {{ display: block; font: 400 6.8pt "IBM Plex Mono", monospace; color: var(--muted); }}
.grid .note {{ color: #3d5156; font-size: 7.6pt; }}
.st {{ display: inline-block; min-width: .62in; text-align: center; font: 500 7pt/1 "IBM Plex Mono", monospace; padding: 3px 4px; border-radius: 2px; border: 1px solid; }}
.st.filled {{ background: var(--ok); border-color: var(--ok); color: #fff; }}
.st.partial {{ background: #f6ecd7; border-color: var(--part); color: #7d5a0c; }}
.st.gap {{ border-color: #b8c4c7; color: var(--muted); }}
.st.agency {{ border-style: dashed; border-color: var(--a2); color: var(--a2); }}
footer {{ display: flex; justify-content: space-between; gap: .3in; font-size: 7pt; color: var(--muted); border-top: 1px solid var(--line); padding-top: .06in; }}
</style></head><body><div class="sheet">
<header>
  <div><div class="eyebrow">open-ng911-addresses · Phase 1 · Overture {e(release)}</div>
    <h1>One open pipeline, a NENA-ready dataset for every county</h1>
    <p class="lede">It reads what agencies already publish, builds the NG9-1-1 GIS layers for each county or census division, and hands each 9-1-1 authority its own data back NENA-ready. Where local data is newer than the national maps, it shows where.</p></div>
  <div class="big">
    <div><b>{fmt(tot['records'])}</b><span>agency address Records</span></div>
    <div><b>{pct(tot['records_with_gers_id'], tot['records'])}</b><span>carry an Overture GERS ID</span></div>
    <div><b>{fmt(tot['packages'])}</b><span>county Packages built</span></div>
  </div>
</header>
{flow_svg(tot, a3)}
<div class="cols">
  <section>
    <h2>Five pilots, built end to end <small>real build counts</small></h2>
    <table class="pilots"><thead><tr><th>Pilot</th><th>Packages</th><th>Records</th><th>with GERS ID</th><th>Gap-fill leads</th><th>A3 polygons</th><th>Road segments</th><th>Roads with GERS ID</th><th>Address licence</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
    <tfoot><tr><th>All five</th><td>{fmt(tot['packages'])}</td><td>{fmt(tot['records'])}</td><td>{pct(tot['records_with_gers_id'], tot['records'])}</td><td>{fmt(tot['gap_fill_candidates'])}</td><td>{fmt(a3)}</td><td>{fmt(tot['road_segments'])}</td><td></td><td></td></tr></tfoot></table>
    <h2 style="margin-top:.16in">Upstream: what Vermont's local roads add <small>VT E911 centerlines vs TIGER and Overture</small></h2>
    <div class="up">
      <div><b>{fmt(vt_nat['not_in_national'])}</b><span>local road segments not in TIGER</span></div>
      <div><b>{fmt(round(vt_nat['not_in_national_km']))} km</b><span>of local road TIGER doesn't have</span></div>
      <div><b>{fmt(vt_ov['not_in_overture'])}</b><span>segments not in Overture</span></div>
      <div><b>{fmt(vt_ov['name_differs'])}</b><span>street names that disagree with Overture</span></div>
    </div>
    <p class="upnote">Counts only, compared at 20 m. Not yet sampled, so some differences will be alias or format noise. Only an open-licensed source goes upstream, and a person proposes it.</p>
  </section>
  <section>
    <h2>NENA GIS Data Model coverage <small>NENA-STA-006.3</small></h2>
    <table class="grid"><tbody>{''.join(layer_rows)}</tbody></table>
  </section>
</div>
<footer><span>Records are the agency's own points and always win; Overture fills in only as review leads. NGUIDs come from a stable Address UID and stay <i>&lt;package&gt;.unclaimed.invalid</i> until the authority opts in. No OSM geometry or names in any core layer.</span>
<span>github.com/COF-RyLopez/open-ng911-addresses</span></footer>
</div></body></html>"""


def flow_svg(tot, a3):
    """Sources → pipeline → Package → back to the authority, with the upstream branch."""
    def box(x, y, w, h, title, lines, color, fill="#fff"):
        t = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="{fill}" stroke="{color}" stroke-width="1.4"/>',
             f'<rect x="{x}" y="{y}" width="4" height="{h}" fill="{color}"/>',
             f'<text x="{x + 12}" y="{y + 16}" font-size="10.5" font-weight="700" fill="#0f1d21">{html.escape(title)}</text>']
        for i, ln in enumerate(lines):
            t.append(f'<text x="{x + 12}" y="{y + 31 + i * 12.5}" font-size="8.4" fill="#33474c">{html.escape(ln)}</text>')
        return "".join(t)

    def arrow(x1, y1, x2, y2, color="#0f1d21", dash=False):
        d = ' stroke-dasharray="4 3"' if dash else ""
        return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="1.5"{d} marker-end="url(#ah)"/>')

    src = [("Agency address points", ["via the OpenAddresses registry"], "#c98a12"),
           ("Agency road centerlines", ["state E911; TIGER where none"], "#5d6f74"),
           ("Boundaries", ["TIGER (US), StatCan (Canada)"], "#4659b8"),
           ("Overture addresses + GERS IDs", ["matching and gap-fill leads"], "#138f89")]
    parts = ['<svg class="flow" viewBox="0 0 1000 190" xmlns="http://www.w3.org/2000/svg">',
             '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#0f1d21"/></marker></defs>']
    for i, (t, ls, c) in enumerate(src):
        y = 4 + i * 46
        parts.append(box(0, y, 196, 40, t, ls, c))
        parts.append(arrow(197, y + 20, 246, 95))
    parts.append(box(250, 18, 230, 154, "Pipeline · one job per state / province", [
        "Parse streets to registry words (CLDXF)", "Match each Record to an Overture address",
        "Address UID from the agency's own ID", "NGUID from the UID, never a GERS ID",
        "Stamp A2 / A3 on every point", "Attach GERS IDs to government roads",
        "Count where local data beats national", "Gate: NENA mandatory fields, unique IDs",
        "Every dropped point counted by reason"], "#0f1d21", "#f2f6f6"))
    parts.append(arrow(481, 95, 528, 95))
    parts.append(box(532, 18, 206, 154, "Package · one per county / CD", [
        "SiteStructureAddressPoint", "RoadCenterLine + GERS crosswalk", "A2Polygon, A3Polygon",
        "manifest: counts, field fill, licences", "NENA + CLDXF domains", "GeoParquet",
        f"{fmt(tot['packages'])} built · {fmt(tot['rows'])} points", f"{fmt(a3)} A3 polygons"], "#2f9a68"))
    parts.append(arrow(739, 60, 790, 40))
    parts.append(arrow(739, 130, 790, 150, "#d4561f", True))
    parts.append(box(794, 4, 206, 76, "Back to the 9-1-1 authority", [
        "Opt-in: it claims its Package", "sets its NGUID domain, adds ESN,", "MSAG and service URIs"], "#2f9a68"))
    parts.append(box(794, 104, 206, 82, "Upstream (a person proposes)", [
        "OpenAddresses: source entries", "Overture: gap-fill, missing roads",
        "TIGER / NRN / NAD: newer local data", "no ODbL in any core layer"], "#d4561f"))
    parts.append("</svg>")
    return "".join(parts)


if __name__ == "__main__":
    out = os.path.join(HERE, "onepager.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page(load()))
    print(out)
