"""
Rebuild what an OpenAddresses change touches (docs/openaddresses-upstream.md).

The build reads OpenAddresses' source files at the commit pinned in registry/openaddresses.toml. Moving the pin
is how a new or fixed OpenAddresses source reaches our Packages, and only the jobs that read a changed file
need rebuilding:

    python -m open_ng911.oa_sync bump --oa <bare clone>      move the pin to OpenAddresses' newest commit and
                                                            print the changed sources and jobs (markdown)
    python -m open_ng911.oa_sync plan --base <git ref>      the CI build matrix: when the only change since
                                                            <ref> is the pin, the enabled jobs it affects;
                                                            otherwise every enabled job (as open_ng911.jobs)

A job is affected when a source file it reads at the old or the new commit was added, changed or removed
between them (sources.openaddresses.source_paths), so a job whose state gains a county source is rebuilt too.
Changes to our own registry rebuild everything, as before: this narrows only pin-only changes.
"""
import argparse
import datetime
import json
import os
import subprocess
import tomllib

from . import registry
from .sources import openaddresses

PIN_FILE = os.path.join(registry.REGISTRY_DIR, "openaddresses.toml")
PIN_PATH = "registry/openaddresses.toml"  # as git names it, from the repository root
OA_GIT = "https://github.com/openaddresses/openaddresses.git"


def pinned(pin_file=PIN_FILE):
    """The commit registry/openaddresses.toml pins, or None."""
    if not os.path.exists(pin_file):
        return None
    with open(pin_file) as fh:
        return read_pin(fh.read())


def read_pin(text):
    """The pinned commit in an openaddresses.toml's text, or None (no file yet, or no pin)."""
    if not text:
        return None
    return (tomllib.loads(text).get("openaddresses") or {}).get("commit")


def pin_text(commit, date):
    return ("# The OpenAddresses commit the build reads source files at (docs/openaddresses-upstream.md). Moved by\n"
            "# the scheduled OpenAddresses sync (oa_sync.py bump); the jobs that read a changed source rebuild.\n"
            f'[openaddresses]\ncommit = "{commit}"\ndate = "{date}"\n')


def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def changed_paths(oa_git, old, new):
    """OpenAddresses source paths ('us/vt/statewide') added, changed or removed between two commits."""
    out = _git("diff", "--name-only", f"{old}..{new}", "--", "sources/", cwd=oa_git)
    return sorted(p[len("sources/"):-len(".json")] for p in out.split() if p.endswith(".json"))


def _registry_paths(job, commit=None):
    """Stand-in for openaddresses.source_paths until the per-state listing lands: the registry Sources'
    OpenAddresses paths (the same set for today's one-source jobs)."""
    try:
        jur = registry.jurisdiction(job)
    except SystemExit:  # no registry file yet: the job reads nothing
        return []
    return sorted({s.openaddresses for s in jur.sources if s.openaddresses})


def source_paths(job, commit=None):
    return getattr(openaddresses, "source_paths", _registry_paths)(job, commit)


def affected_jobs(changed, old, new, jobs=None):
    """Every job (enabled or not) that reads one of the changed paths at either commit, with the paths."""
    changed = set(changed)
    out = []
    for j in jobs if jobs is not None else registry.jobs():
        hit = sorted(changed & (set(source_paths(j, old)) | set(source_paths(j, new))))
        if hit:
            out.append((j, hit))
    return out


def summary(changed, affected, old, new):
    """The pin-bump pull request's body."""
    lines = [(f"Moves the OpenAddresses pin from `{(old or 'master')[:10]}` to `{new[:10]}` "
              f"([compare](https://github.com/openaddresses/openaddresses/compare/{old}...{new}))."), "",
             f"**{len(changed)} OpenAddresses source files changed.** Jobs that read one of them:", ""]
    if not affected:
        lines.append("- none: no Package rebuilds")
    for j, paths in affected:
        state = "rebuilt by this PR's CI" if j.enabled else "not enabled, nothing to rebuild"
        lines.append(f"- `{j.id}` ({j.name}, {state}): " + ", ".join(f"`{p}`" for p in paths))
    return "\n".join(lines) + "\n"


def bump(oa_git, pin_file=PIN_FILE):
    """Move the pin to the clone's newest master commit. Returns (old, new, changed, affected)."""
    old = pinned(pin_file)
    new = _git("rev-parse", "master", cwd=oa_git).strip()
    if old == new:
        return old, new, [], []
    date = _git("log", "-1", "--format=%cs", new, cwd=oa_git).strip() or datetime.datetime.now(datetime.UTC).date().isoformat()
    # no pin yet: treat every source as changed, so every job that reads one is listed
    changed = changed_paths(oa_git, old, new) if old else sorted(
        p[len("sources/"):-len(".json")] for p in _git("ls-tree", "-r", "--name-only", new, "sources/",
                                                       cwd=oa_git).split() if p.endswith(".json"))
    affected = affected_jobs(changed, old, new)
    with open(pin_file, "w") as fh:
        fh.write(pin_text(new, date))
    return old, new, changed, affected


def plan(base, oa_git=None):
    """The CI build matrix since `base`: the enabled jobs a pin-only change affects, else every enabled job."""
    enabled = [j for j in registry.jobs() if j.enabled]
    try:
        files = set(_git("diff", "--name-only", f"{base}...HEAD").split())
        old = read_pin(subprocess.run(["git", "show", f"{base}:{PIN_PATH}"], capture_output=True, text=True,
                                      check=False).stdout)
    except subprocess.CalledProcessError:
        return [j.id for j in enabled]
    new = pinned()
    if files != {PIN_PATH} or not (old and new and oa_git):
        return [j.id for j in enabled]
    changed = changed_paths(oa_git, old, new)
    return [j.id for j, _ in affected_jobs(changed, old, new, enabled)]


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bump")
    b.add_argument("--oa", required=True, help="a clone of openaddresses (a blobless bare clone is enough)")
    b.add_argument("--summary", help="write the pull request body here")
    p = sub.add_parser("plan")
    p.add_argument("--base", required=True, help="the git ref the change is compared with (main, a push's before)")
    p.add_argument("--oa", help="a clone of openaddresses holding both pinned commits")
    a = ap.parse_args()
    if a.cmd == "bump":
        old, new, changed, affected = bump(a.oa)
        text = summary(changed, affected, old, new) if old != new else "The pin is already OpenAddresses' newest.\n"
        if a.summary:
            with open(a.summary, "w") as fh:
                fh.write(text)
        print(text)
    else:
        print(json.dumps(plan(a.base, a.oa)))


if __name__ == "__main__":
    main()
