"""
The jurisdiction registry: build jobs (registry/jobs.toml) and, per job, its 911 authorities and Source
agencies (registry/<country>/<code>.toml). Plain TOML, edited by hand.
"""
import os
import tomllib
from dataclasses import dataclass, field

REGISTRY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "registry")
LICENSE_STATUSES = ("open", "share-alike", "unknown")
# What a Source can be: a registry layer key -> the NENA layer it feeds. 'addresses' and 'centerlines' are
# OpenAddresses layer names, read through its source registry (or an `oa_entry`); the others are read from the
# Source's own `endpoint` (layers.py), since OpenAddresses doesn't catalogue them.
NENA_LAYER = {"addresses": "SiteStructureAddressPoint", "centerlines": "RoadCenterLine",
              "psap": "PsapPolygon", "police": "PolicePolygon", "fire": "FirePolygon", "ems": "EmsPolygon",
              "provisioning": "ProvisioningPolygon", "distance_markers": "DistanceMarkerPoint",
              "location_markers": "LocationMarkerPoint"}
OA_LAYERS = ("addresses", "centerlines")
LAYERS = tuple(NENA_LAYER)
SHARING_STATUSES = ("not_started", "offered", "in_progress", "done", "not_applicable")


@dataclass(frozen=True)
class Country:
    """What differs between the US and Canada, in one place (ADR 0006): a new country is a row here, a boundary
    module in sources/, and its value domains in nena/ (nena.install(c, country))."""
    packages: str              # what one Package is: the registry's `packages` value
    boundaries: str            # module in sources/ with load_package_area and load_municipality
    a2_source: str
    a3_source: str
    boundary_license: str
    boundary_license_url: str
    boundary_key: str          # the boundary source's key in the ODbL inventory
    values: str                # the value domains the layers use (NENA's; Canada adds CLDXF-CA's)
    tiger_roads: bool          # TIGER ADDRFEAT is the road fallback and the national road layer


COUNTRIES = {
    "US": Country("county", "tiger", "Census TIGER counties",
                  "Census TIGER county subdivisions or incorporated places", "public domain",
                  "https://www.census.gov/data/developers/about/terms-of-service.html", "tiger-counties",
                  "NENA-STA-006.3", tiger_roads=True),
    "CA": Country("census_division", "statcan", "Statistics Canada census divisions",
                  "Statistics Canada census subdivisions", "Statistics Canada Open Licence",
                  "https://www.statcan.gc.ca/en/terms-conditions/open-licence", "statcan-census-divisions",
                  "CLDXF-CA", tiger_roads=False),
}


def country(j):
    return COUNTRIES[j.country]


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
    license_status: str
    openaddresses: str = ""
    oa_layer: str = ""
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
    # NENA field (lower-cased) -> the Source's own field, in the conform language (fieldmap.py)
    nena: dict = field(default_factory=dict)
    # Where a layer OpenAddresses doesn't catalogue is read: {data = "<ArcGIS layer URL>", protocol = "ESRI",
    # where = "<optional filter>"}
    endpoint: dict = field(default_factory=dict)
    # Polygons merged into one per value of this field (a zone layer naming each zone's fire, law and EMS
    # agency feeds the fire, police and EMS layers this way); the value is the feature's ID
    dissolve: str = ""

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

    def sources_for(self, layer):
        """The Source agencies of one OpenAddresses layer ('addresses', 'centerlines')."""
        return [s for s in self.sources if s.layer == layer]


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
    assert r.packages == country(j).packages, (
        f"{j.id}: packages are per county in the US and per census division in Canada (ADR 0006)")
    for a in r.authorities:
        assert not (a.opted_in and not a.domain), f"{a.key}: opted in without a confirmed domain (ADR 0004)"
        assert a.opted_in or not a.domain, f"{a.key}: a domain is set only once the authority opts in (ADR 0003)"
    from . import fieldmap
    for s in r.sources:
        assert s.license_status in LICENSE_STATUSES, f"{s.key}: license_status {s.license_status!r}"
        assert s.layer in LAYERS, f"{s.key}: layer {s.layer!r} (one of {LAYERS})"
        if s.layer in OA_LAYERS:
            assert s.openaddresses or s.oa_entry, f"{s.key}: an {s.layer} Source names its OpenAddresses source"
        else:
            assert s.endpoint.get("data"), f"{s.key}: a {s.layer} Source needs endpoint.data (OpenAddresses has none)"
        errors = fieldmap.check(s, NENA_LAYER[s.layer], j.country)
        assert not errors, "; ".join(errors)
        assert not s.exclude or set(s.exclude) == {"field", "values"}, f"{s.key}: exclude needs field and values"
        for path, status in s.sharing.items():
            assert status in SHARING_STATUSES, f"{s.key}: sharing.{path} = {status!r}"
