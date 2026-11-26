"""
NENA field coverage: for every NENA layer, how much of each field a build filled and where the value came from.

Every field of every NENA-STA-006.3 layer (in the job's country) gets one of three statuses:

    filled      every feature of the layer has it
    partial     some features have it
    no_source   none do: no Source maps it, the Source's field is empty, or the layer wasn't built

and a basis: `source` (the registry's `nena` table names the Source field, fieldmap.py), `derived` (the pipeline
fills it: the Package's boundary, the geometry, the OpenAddresses fields, a placeholder), or neither. Values the
field map rejected (outside the domain, too long, a placeholder date) are counted beside the field.

Each Package's manifest has a `nena_coverage` section, and job.json has the job's, with `before`: the same layer
built from the OpenAddresses schema alone, so each build shows what mapping the Source's own fields added. The
no_source fields feed the gap review and the agency request tracker (scripts/nena_coverage.py).
"""
from . import fieldmap, nena, registry

STATUSES = ("filled", "partial", "no_source")


def status(fill):
    if not fill:
        return "no_source"
    return "filled" if fill >= 1 else "partial"


def fills(c, table, names, where="true"):
    """(rows, {field: share of rows with a value}) for the columns of `table` that exist."""
    cols = {r[0] for r in c.execute(f"DESCRIBE {table}").fetchall()}
    have = [n for n in names if n in cols]
    sql = ", ".join(["count(*)"] + [f"count({n})" for n in have])
    res = c.execute(f"SELECT {sql} FROM {table} WHERE {where}").fetchall()[0]
    rows = int(res[0])
    out = {n: 0.0 for n in names}
    for n, v in zip(have, res[1:]):
        out[n] = round(int(v) / rows, 4) if rows else 0.0
    return rows, out


def section(c, layer, country, table, where="true", sources=None, derived=None, rejected=None, before=None):
    """One layer's coverage. table None: the layer wasn't built. sources: fieldmap.mapped(); derived: {field:
    how the pipeline fills it}; before: {field: fill} of the OpenAddresses-only build."""
    names = [f["name"] for f in nena.layer_fields(layer, country)]
    required = {f["name"] for f in nena.layer_fields(layer, country) if f["required"]}
    rows, fill = fills(c, table, names, where) if table else (0, {n: 0.0 for n in names})
    sources, derived, rejected = sources or {}, derived or {}, rejected or {}
    fields = {}
    for n in names:
        f = {"fill": fill[n], "status": status(fill[n])}
        if n in sources:
            f["source"] = sources[n]
        elif n in derived:
            f["derived"] = derived[n]
        if n in rejected:
            f["rejected"] = rejected[n]
        if before is not None:
            f["before"] = before.get(n, 0.0)
        if n in required:
            f["required"] = True
        fields[n] = f
    out = {"built": rows > 0, "features": rows,
           **{s: sum(1 for f in fields.values() if f["status"] == s) for s in STATUSES}}
    if before is not None:
        out["before"] = {s: sum(1 for n in names if status(before.get(n, 0.0)) == s) for s in STATUSES}
    out["fields"] = fields
    return out


def layer_sources(jurisdiction, layer):
    """{field: ['<source>: <native field>']} for every registry layer key feeding one NENA layer."""
    out = {}
    for key, name in registry.NENA_LAYER.items():
        if name == layer:
            for f, specs in fieldmap.mapped(jurisdiction, key).items():
                out.setdefault(f, []).extend(specs)
    return out


def brief(cov):
    """The log line: per layer, filled / partial / no_source, after (and before where known)."""
    parts = []
    for layer, s in cov.items():
        now = f"{s['filled']}/{s['partial']}/{s['no_source']}"
        was = f"{s['before']['filled']}/{s['before']['partial']}/{s['before']['no_source']} -> " if "before" in s else ""
        parts.append(f"{layer} {was}{now}" + ("" if s["built"] else " (not built)"))
    return "; ".join(parts)
