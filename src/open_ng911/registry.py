"""
The jurisdiction registry: build jobs (registry/jobs.toml) and, per job, its 911 authorities and Source
agencies (registry/<country>/<code>.toml). Plain TOML, edited by hand.
"""
import os
import tomllib
from dataclasses import dataclass, field

REGISTRY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "registry")
LICENSE_STATUSES = ("open", "share-alike", "unknown")
LAYERS = ("addresses", "centerlines")  # OpenAddresses layer names
SHARING_STATUSES = ("not_started", "offered", "in_progress", "done", "not_applicable")


@dataclass
class Job:
    id: str
    country: str
    code: str
    fips: str
    name: str
    enabled: bool


@dataclass
class Authority:
    key: str
    name: str
    covers: str | list
    opted_in: bool = False
    domain: str = ""

    def covers_package(self, geoid):
        return self.covers == "*" or geoid in self.covers


@dataclass
class Source:
    key: str
    agency: str
    layer: str
    covers: str | list
    openaddresses: str
    oa_layer: str
    license_status: str
    id_field: str = ""
    exclude_site_types: list = field(default_factory=list)
    license_url: str = ""
    attribution: str = ""
    sharing: dict = field(default_factory=dict)
    # A layer entry in OpenAddresses' own schema, for an endpoint OpenAddresses doesn't list yet. It is used
    # in place of the registry's entry and is written so it can go upstream as is (sources/openaddresses.py).
    oa_entry: dict = field(default_factory=dict)
    # Features to leave out, by the raw value of one field: {field = "AOTCLASS", values = ["98"]}
    exclude: dict = field(default_factory=dict)

    def covers_package(self, geoid):
        return self.covers == "*" or geoid in self.covers


@dataclass
class Jurisdiction:
    job: str
    packages: str
    authorities: list
    sources: list

    def authority_for(self, geoid):
        return next((a for a in self.authorities if a.covers_package(geoid)), None)


def jobs(registry_dir=REGISTRY_DIR):
    with open(os.path.join(registry_dir, "jobs.toml"), "rb") as f:
        return [Job(**j) for j in tomllib.load(f)["job"]]


def job(job_id, registry_dir=REGISTRY_DIR):
    for j in jobs(registry_dir):
        if j.id == job_id:
            return j
    raise SystemExit(f"No job {job_id!r} in registry/jobs.toml")


def jurisdiction(j, registry_dir=REGISTRY_DIR):
    path = os.path.join(registry_dir, j.country.lower(), f"{j.code.lower()}.toml")
    if not os.path.exists(path):
        raise SystemExit(f"Job {j.id} has no jurisdiction registry yet ({os.path.relpath(path, registry_dir)})")
    with open(path, "rb") as f:
        d = tomllib.load(f)
    r = Jurisdiction(job=d["job"], packages=d["packages"],
                     authorities=[Authority(**a) for a in d.get("authority", [])],
                     sources=[Source(**s) for s in d.get("source", [])])
    validate(r, j)
    return r


def validate(r, j):
    assert r.job == j.id, f"{j.id}: registry says job {r.job!r}"
    assert r.packages == ("county" if j.country == "US" else "census_division"), (
        f"{j.id}: packages are per county in the US and per census division in Canada (ADR 0006)")
    for a in r.authorities:
        assert not (a.opted_in and not a.domain), f"{a.key}: opted in without a confirmed domain (ADR 0004)"
        assert a.opted_in or not a.domain, f"{a.key}: a domain is set only once the authority opts in (ADR 0003)"
    for s in r.sources:
        assert s.license_status in LICENSE_STATUSES, f"{s.key}: license_status {s.license_status!r}"
        assert s.layer in LAYERS, f"{s.key}: layer {s.layer!r} (one of {LAYERS})"
        assert not s.exclude or set(s.exclude) == {"field", "values"}, f"{s.key}: exclude needs field and values"
        for path, status in s.sharing.items():
            assert status in SHARING_STATUSES, f"{s.key}: sharing.{path} = {status!r}"
