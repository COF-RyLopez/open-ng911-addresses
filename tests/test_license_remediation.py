"""scripts/license_remediation.py: the first-read license classes (offline)."""
import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "license_remediation", os.path.join(os.path.dirname(__file__), "..", "scripts", "license_remediation.py"))
lr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lr)


def cls(lic):
    return lr.classify(lic)[0]


def test_unstated():
    assert cls(None) == "unstated"
    assert cls("Unknown") == "unstated"
    assert cls({}) == "unstated"


def test_open():
    assert cls({"text": "Public Domain"}) == "open"
    assert cls({"text": "CC BY 4.0", "attribution": True}) == "open"
    assert cls("CC0") == "open"
    assert cls({"text": "Open Government Licence – Prince Edward Island"}) == "open"
    assert cls({"url": "https://open.canada.ca/en/open-government-licence-canada"}) == "open"


def test_share_alike_and_restricted_are_not_open():
    assert cls({"text": "CC BY-SA 4.0"}) == "share-alike"
    assert cls({"text": "ODbL"}) == "share-alike"
    assert cls({"text": "Public Domain", "share-alike": True}) == "share-alike"
    assert cls({"text": "CC BY-NC 4.0"}) == "restricted"
    assert cls({"text": "For reference use only. No warranty."}) == "restricted"


def test_presumed_and_unreviewed_need_a_person():
    assert cls({"text": "Public Domain", "presumed": True}) == "presumed"
    assert cls("https://vcgi.vermont.gov/sites/vcgi/files/warehouse/VCGI_Warranty_Copyright_Notice_2013.pdf") \
        == "stated-unreviewed"
    assert cls({"text": "Indemnification: the user agrees ..."}) == "stated-unreviewed"


# scripts/oa_upstream.py: an `oa_entry` is new, a fix, or already listed upstream
_up = importlib.util.spec_from_file_location(
    "oa_upstream", os.path.join(os.path.dirname(__file__), "..", "scripts", "oa_upstream.py"))
up = importlib.util.module_from_spec(_up)
_up.loader.exec_module(up)


def _oa_checkout(tmp_path, centerlines=None):
    import json
    d = tmp_path / "oa" / "sources" / "us" / "vt"
    d.mkdir(parents=True)
    layers = {"addresses": [{"name": "state", "data": "https://example.com/a", "protocol": "ESRI"}]}
    if centerlines is not None:
        layers["centerlines"] = centerlines
    (d / "statewide.json").write_text(json.dumps({"schema": 2, "coverage": {"country": "us"}, "layers": layers}))
    return str(tmp_path / "oa")


ENTRY = {"name": "state", "data": "https://example.com/roads/0", "protocol": "ESRI",
         "conform": {"format": "geojson", "id": "SEGMENTID", "name": "SN"}}


def _registry(tmp_path):
    """A registry with one Source written as an `oa_entry` (Vermont-shaped)."""
    d = tmp_path / "registry" / "us"
    d.mkdir(parents=True)
    (d / "vt.toml").write_text(
        'job = "us-vt"\n\n[[source]]\nkey = "us-vt-e911-rds"\nlayer = "centerlines"\nagency = "Example"\n'
        'openaddresses = "us/vt/statewide"\noa_layer = "state"\nlicense_status = "unknown"\n\n[source.oa_entry]\n'
        'name = "state"\ndata = "https://example.com/roads/0"\nprotocol = "ESRI"\n\n[source.oa_entry.conform]\n'
        'format = "geojson"\nid = "SEGMENTID"\nname = "SN"\n')
    return str(tmp_path / "registry")


def test_oa_upstream_status(tmp_path):
    registry, entry = _registry(tmp_path), ENTRY
    row = lambda oa: next(r for r in up.proposals(oa, registry) if r["source_key"] == "us-vt-e911-rds")
    new = row(_oa_checkout(tmp_path / "new"))
    assert new["status"] == "new" and new["patched"]["layers"]["centerlines"] == [entry]
    assert new["patched"]["layers"]["addresses"][0]["data"] == "https://example.com/a"  # the rest untouched
    old = {**entry, "conform": {"format": "geojson", "name": "SN"}}
    fix = row(_oa_checkout(tmp_path / "fix", [old]))
    assert fix["status"] == "fix" and fix["patched"]["layers"]["centerlines"] == [entry]
    listed = row(_oa_checkout(tmp_path / "listed", [entry]))
    assert listed["status"] == "listed" and listed["patched"] is None


def test_oa_upstream_draft_never_speaks_for_the_agency(tmp_path):
    registry = _registry(tmp_path)
    rows = up.proposals(_oa_checkout(tmp_path), registry)
    up.write(rows, str(tmp_path / "out"))
    body = (tmp_path / "out" / "us" / "vt" / "statewide.md").read_text()
    assert "not affiliated" in body and "npm test" in body
    assert (tmp_path / "out" / "sources" / "us" / "vt" / "statewide.json").read_text().endswith("}\n")
