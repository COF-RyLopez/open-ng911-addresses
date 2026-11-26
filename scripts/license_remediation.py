"""
Build the license-remediation snapshot from the OpenAddresses source registry (docs/license-remediation.md).

    python scripts/license_remediation.py --oa <openaddresses checkout>   # or no flag: downloads master

Writes, for the US and Canada:
    registry/remediation/oa_sources.csv     every OA source layer: its license as OA records it, and our class
    registry/remediation/oa_coverage.csv    per state/province and layer: statewide source?, counties covered, classes
    registry/remediation/oa_proposals.csv   endpoints our registry reads (`oa_entry`) that OpenAddresses doesn't list
                                            yet: each one is an entry to propose upstream

The class is a first read of what OpenAddresses records, not a legal opinion, and it never changes a job's
`license_status` by itself: that changes by hand, only after the agency confirms (ADR 0004, 0005).
"""
import argparse
import collections
import csv
import io
import json
import os
import re
import tarfile
import tomllib
import urllib.request

OA_TARBALL = "https://github.com/openaddresses/openaddresses/archive/refs/heads/master.tar.gz"
LAYERS = ("addresses", "centerlines", "parcels", "buildings")
REGISTRY = os.path.join(os.path.dirname(__file__), "..", "registry")
OUT = os.path.join(REGISTRY, "remediation")

OPEN = re.compile(r"public domain|\bpd\b|pddl|\bcc[ -]?0\b|cc0|cc[ -]by(?![ -]?(sa|nc))|creative commons attribution(?!.*(share|non))"
                  r"|open government licen[cs]e|odc[ -]by|open data commons attribution|\bmit\b|us government work"
                  r"|no restrictions", re.IGNORECASE)
SHARE_ALIKE = re.compile(r"odbl|open database licen|share[ -]?alike|cc[ -]by[ -]sa", re.IGNORECASE)
OPEN_URL = re.compile(r"creativecommons\.org/(licenses/by/|publicdomain/)|opendatacommons\.org/licenses/(pddl|by)"
                      r"|open\.canada\.ca/en/open-government-licence|statcan\.gc\.ca/.*/?licen[cs]e"
                      r"|/open-government-licen[cs]e", re.IGNORECASE)
RESTRICTED = re.compile(r"non[ -]?commercial|cc[ -]by[ -]nc|not for (re)?distribution|for reference use only"
                        r"|permission (is )?required|copyright licen[cs]e agreement|end user licen", re.IGNORECASE)


def classify(lic):
    """(class, text, url, attribution) for an OA `license` value.

    open            a recognised open licence or public-domain statement, not marked presumed
    share-alike     share-alike (ODbL, CC BY-SA): kept out under the project's licensing stance
    restricted      non-commercial, reference-only, end-user or signed agreements
    presumed        OA marked the licence as presumed, not stated by the publisher
    stated-unreviewed  a licence URL or text we don't recognise: someone has to read it
    unstated        no licence recorded at all
    """
    if not lic or (isinstance(lic, str) and lic.strip().lower() in ("unknown", "none", "")):
        return "unstated", "", "", ""
    if isinstance(lic, str):
        text, url, attr, presumed, sa = ("", lic, "", False, False) if lic.startswith("http") else (lic, "", "", False, False)
    else:
        text, url = lic.get("text") or "", lic.get("url") or ""
        attr = lic.get("attribution name") or ""
        presumed, sa = bool(lic.get("presumed")), bool(lic.get("share-alike"))
    if sa or SHARE_ALIKE.search(text):
        cls = "share-alike"
    elif RESTRICTED.search(text):
        cls = "restricted"
    elif presumed:
        cls = "presumed"
    elif (text and OPEN.search(text)) or (url and not text and OPEN_URL.search(url)):
        cls = "open"
    else:
        cls = "stated-unreviewed"
    return cls, " ".join(text.split())[:300], url, attr


def read_sources(oa_dir):
    for country in ("us", "ca"):
        root = os.path.join(oa_dir, "sources", country)
        for dirpath, _, files in os.walk(root):
            for f in sorted(files):
                if f.endswith(".json"):
                    path = os.path.join(dirpath, f)
                    with open(path) as fh:
                        yield os.path.relpath(path, os.path.join(oa_dir, "sources"))[:-5], json.load(fh)


def download(dest):
    with urllib.request.urlopen(OA_TARBALL, timeout=300) as r:
        data = r.read()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
        members = [m for m in t.getmembers() if re.search(r"/sources/(us|ca)/", m.name)]
        t.extractall(dest, members=members, filter="data")
    return os.path.join(dest, os.listdir(dest)[0])


def write_county_gaps(counties_csv, rows, out):
    """Counties with no OA address source of their own and no statewide one; usable = an open class."""
    by_state = collections.defaultdict(list)
    for r in rows:
        if r["layer"] == "addresses" and r["country"] == "us":
            by_state[r["region"]].append(r)
    with open(counties_csv, newline="") as f, open(out, "w", newline="") as o:
        w = csv.writer(o)
        w.writerow(["geoid", "name", "state", "own_sources", "statewide_sources", "best_class", "gap"])
        rank = ["open", "stated-unreviewed", "presumed", "unstated", "restricted", "share-alike"]
        for c in csv.DictReader(f):
            geoid = c["geoid"].zfill(5)
            state = next((r["region"] for rs in by_state.values() for r in rs if r["geoid"][:2] == geoid[:2]), "")
            rs = by_state.get(state, [])
            own = [r for r in rs if r["geoid"] == geoid]
            sw = [r for r in rs if r["statewide"] == 1]
            classes = sorted({r["license_class"] for r in own + sw}, key=rank.index)
            best = classes[0] if classes else ""
            gap = "no_source" if not classes else ("ok" if best == "open" else "license_unclear")
            w.writerow([geoid, c.get("name", ""), state, len(own), len(sw), best, gap])


def write_oa_proposals(oa_dir, registry_dir, out):
    """Every registry source written as an `oa_entry` (OpenAddresses' schema), and whether OA lists it yet."""
    rows = []
    for country in ("us", "ca"):
        d = os.path.join(registry_dir, country)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.endswith(".toml"):
                continue
            with open(os.path.join(d, f), "rb") as fh:
                reg = tomllib.load(fh)
            for src in reg.get("source", []):
                entry = src.get("oa_entry")
                if not entry:
                    continue
                target = src.get("openaddresses") or ""
                listed = False
                path = os.path.join(oa_dir, "sources", target + ".json")
                if target and os.path.exists(path):
                    with open(path) as fh:
                        layers = json.load(fh).get("layers", {})
                    listed = any(e.get("data") == entry.get("data") for e in layers.get(src.get("layer"), []))
                rows.append({"job": reg.get("job"), "source_key": src.get("key"), "layer": src.get("layer"),
                             "oa_source": target, "oa_layer": entry.get("name", ""), "data": entry.get("data", ""),
                             "website": entry.get("website", ""), "license_status": src.get("license_status"),
                             "status": "listed" if listed else "to_propose",
                             "note": "" if src.get("license_status") == "open" else
                             "OpenAddresses accepts it without a licence; the licence ask is tracked separately"})
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["job", "source_key", "layer", "oa_source", "oa_layer", "data", "website",
                                           "license_status", "status", "note"])
        w.writeheader()
        w.writerows(rows)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--oa", help="an openaddresses checkout (default: download master)")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--registry", default=REGISTRY)
    ap.add_argument("--counties", help="optional CSV of geoid,name (e.g. the Census gazetteer counties file): "
                                       "also writes county_gaps.csv, the counties no OA address source reaches")
    a = ap.parse_args()
    oa_dir = a.oa or download(os.path.join("/tmp", "oa-sources"))
    rows, cov = [], collections.defaultdict(lambda: {"statewide": 0, "counties": set(), "sources": 0,
                                                     **{c: 0 for c in ("open", "share-alike", "restricted",
                                                                       "presumed", "stated-unreviewed", "unstated")}})
    for path, d in read_sources(oa_dir):
        parts = path.split("/")
        country, region = parts[0], parts[1] if len(parts) > 2 else ""
        geoid = str(((d.get("coverage") or {}).get("US Census") or {}).get("geoid") or "")
        statewide = len(parts) == 3 and parts[2] in ("statewide", "province", "territory", "statewide-partial") \
            or len(geoid) == 2
        for layer in LAYERS:
            for e in d.get("layers", {}).get(layer, []):
                cls, text, url, attr = classify(e.get("license"))
                host = re.sub(r"^https?://([^/]+).*", r"\1", e.get("data") or "")
                rows.append({"country": country, "region": region, "oa_source": path, "layer": layer,
                             "oa_layer": e.get("name", ""), "geoid": geoid, "statewide": int(statewide),
                             "license_class": cls, "license_text": text, "license_url": url,
                             "attribution": attr or e.get("attribution", ""), "data_host": host,
                             "website": e.get("website", ""), "protocol": e.get("protocol", "")})
                k = cov[(country, region, layer)]
                k["sources"] += 1
                k[cls] += 1
                k["statewide"] += int(statewide)
                if len(geoid) == 5:
                    k["counties"].add(geoid)
    os.makedirs(a.out, exist_ok=True)
    rows.sort(key=lambda r: (r["country"], r["region"], r["layer"], r["oa_source"], r["oa_layer"]))
    with open(os.path.join(a.out, "oa_sources.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(a.out, "oa_coverage.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["country", "region", "layer", "sources", "statewide_sources", "counties_with_own_source",
                    "open", "share-alike", "restricted", "presumed", "stated-unreviewed", "unstated"])
        for (country, region, layer), k in sorted(cov.items()):
            w.writerow([country, region, layer, k["sources"], k["statewide"], len(k["counties"]), k["open"],
                        k["share-alike"], k["restricted"], k["presumed"], k["stated-unreviewed"], k["unstated"]])
    props = write_oa_proposals(oa_dir, a.registry, os.path.join(a.out, "oa_proposals.csv"))
    print(f"oa_entry proposals: {sum(p['status'] == 'to_propose' for p in props)} to propose, "
          f"{sum(p['status'] == 'listed' for p in props)} already listed")
    if a.counties:
        write_county_gaps(a.counties, rows, os.path.join(a.out, "county_gaps.csv"))
    tally = collections.Counter((r["layer"], r["license_class"]) for r in rows)
    for (layer, cls), n in sorted(tally.items()):
        print(f"{layer:12} {cls:18} {n:5}")


if __name__ == "__main__":
    main()
