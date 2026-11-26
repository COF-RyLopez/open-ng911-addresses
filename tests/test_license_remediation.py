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
