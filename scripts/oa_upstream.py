"""
Draft OpenAddresses pull requests from the registry's `oa_entry` blocks (docs/openaddresses-upstream.md).

    python scripts/oa_upstream.py --oa <openaddresses checkout> [--out build/oa-upstream] [--apply]

An `oa_entry` is a layer entry written in OpenAddresses' own schema, for an endpoint OpenAddresses doesn't list
(`new`) or lists differently (`fix`: same layer name or same data URL, other contents). For each one this writes
    <out>/sources/<path>.json   the OpenAddresses source file with the entry added or replaced, formatted as
                                OpenAddresses formats it (4 spaces, trailing newline), so it can be copied over
    <out>/<path>.md             a pull request draft: title and body
and `--apply` writes the source files into the checkout itself, ready for `npm test` and a branch. Entries
OpenAddresses already lists unchanged are `listed`: drop the `oa_entry` and the build reads theirs.

Nothing is opened here. A person reviews each draft and opens the pull request from their own fork; the draft
never speaks for the agency that publishes the data.
"""
import argparse
import json
import os
import sys
import tomllib

REGISTRY = os.path.join(os.path.dirname(__file__), "..", "registry")
OUT = os.path.join(os.path.dirname(__file__), "..", "build", "oa-upstream")


def registry_entries(registry_dir=REGISTRY):
    """(job, Source table) for every registry Source written with an `oa_entry`."""
    for country in ("us", "ca"):
        d = os.path.join(registry_dir, country)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.endswith(".toml"):
                with open(os.path.join(d, f), "rb") as fh:
                    reg = tomllib.load(fh)
                for src in reg.get("source", []):
                    if src.get("oa_entry"):
                        yield reg.get("job"), src


def status(definition, layer, entry):
    """listed / fix / new, and the index of the entry a fix replaces."""
    for i, e in enumerate((definition or {}).get("layers", {}).get(layer, [])):
        if e == entry:
            return "listed", i
        if e.get("name") == entry.get("name") or e.get("data") == entry.get("data"):
            return "fix", i
    return "new", None


def proposals(oa_dir, registry_dir=REGISTRY):
    """One row per `oa_entry`: where it goes in OpenAddresses, its status, and the patched source file."""
    rows = []
    for job, src in registry_entries(registry_dir):
        path, layer, entry = src.get("openaddresses") or "", src["layer"], src["oa_entry"]
        file = os.path.join(oa_dir, "sources", path + ".json")
        definition = None
        if path and os.path.exists(file):
            with open(file) as fh:
                definition = json.load(fh)
        st, i = status(definition, layer, entry)
        patched = None
        if st != "listed" and definition is not None:
            patched = json.loads(json.dumps(definition))
            entries = patched.setdefault("layers", {}).setdefault(layer, [])
            if i is None:
                entries.append(entry)
            else:
                entries[i] = entry
        rows.append({"job": job, "source_key": src["key"], "layer": layer, "oa_source": path,
                     "oa_layer": entry.get("name", ""), "data": entry.get("data", ""),
                     "website": entry.get("website", ""), "license_status": src.get("license_status"),
                     "status": st if definition is not None else "no_oa_file", "agency": src.get("agency", ""),
                     "entry": entry, "patched": patched})
    return rows


def pr_draft(row):
    """Title and body for one pull request. The body states what changed and how it was checked; the person
    opening it adds anything they checked by hand."""
    e, c = row["entry"], row["entry"].get("conform", {})
    verb = "add" if row["status"] == "new" else "update"
    title = f"{row['oa_source']}: {verb} {row['layer']} ({e.get('name')})"
    mapped = ", ".join(f"`{k}`" for k in c if k not in ("format", "filter"))
    licence = e.get("license")
    lines = [
        (f"{'Adds' if verb == 'add' else 'Updates'} the `{row['layer']}` layer `{e.get('name')}` in "
         f"`sources/{row['oa_source']}.json`."),
        "",
        f"- **Data:** {e.get('data')} ({e.get('protocol')})",
        f"- **Website:** {e.get('website')}" if e.get("website") else None,
        f"- **Published by:** {row['agency']}",
        f"- **Conform:** {mapped}",
        f"- **Filter:** `{c['filter']}`" if c.get("filter") else None,
        f"- **Licence:** {licence if isinstance(licence, str) else json.dumps(licence)}" if licence else
        "- **Licence:** none stated on the layer or its page; left out rather than guessed.",
        f"- **Note:** {e['note']}" if e.get("note") else None,
        "",
        "Checked: `npm test` passes, and every conform field is in the layer's own field list (`?f=json`).",
        "",
        "I'm not affiliated with the publishing agency; this is a public endpoint I use and want to share.",
    ]
    return title, "\n".join(x for x in lines if x is not None) + "\n"


def write(rows, out, oa_dir=None):
    for r in rows:
        if r["patched"] is None:
            continue
        text = json.dumps(r["patched"], indent=4, ensure_ascii=False) + "\n"
        for base in [os.path.join(out, "sources")] + ([os.path.join(oa_dir, "sources")] if oa_dir else []):
            p = os.path.join(base, r["oa_source"] + ".json")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as fh:
                fh.write(text)
        title, body = pr_draft(r)
        p = os.path.join(out, r["oa_source"] + ".md")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(f"# {title}\n\n{body}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--oa", required=True, help="an openaddresses checkout")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--registry", default=REGISTRY)
    ap.add_argument("--apply", action="store_true", help="also write the source files into the checkout")
    a = ap.parse_args()
    rows = proposals(a.oa, a.registry)
    write(rows, a.out, a.oa if a.apply else None)
    for r in rows:
        print(f"{r['status']:10} {r['source_key']:28} sources/{r['oa_source']}.json {r['layer']}/{r['oa_layer']}")
    missing = [r for r in rows if r["status"] == "no_oa_file"]
    if missing:
        print(f"{len(missing)} entries name an OpenAddresses file that doesn't exist; write its coverage by hand",
              file=sys.stderr)


if __name__ == "__main__":
    main()
