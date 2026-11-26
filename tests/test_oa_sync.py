"""oa_sync.py: an OpenAddresses pin bump rebuilds only the jobs that read a changed source file (offline)."""
import subprocess

from open_ng911 import oa_sync, registry


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def fake_oa(tmp_path):
    """A two-commit OpenAddresses: the second changes Vermont's statewide file and adds an Ohio county."""
    oa = tmp_path / "oa"
    (oa / "sources" / "us" / "vt").mkdir(parents=True)
    (oa / "sources" / "us" / "nd").mkdir(parents=True)
    git(tmp_path, "init", "-q", "-b", "master", str(oa))
    for k, v in (("user.email", "t@example.com"), ("user.name", "t")):
        git(oa, "config", k, v)
    (oa / "sources" / "us" / "vt" / "statewide.json").write_text("{}\n")
    (oa / "sources" / "us" / "nd" / "statewide.json").write_text("{}\n")
    git(oa, "add", "-A")
    git(oa, "commit", "-q", "-m", "one")
    old = git(oa, "rev-parse", "HEAD")
    (oa / "sources" / "us" / "vt" / "statewide.json").write_text('{"layers": {}}\n')
    (oa / "sources" / "us" / "oh").mkdir(parents=True)
    (oa / "sources" / "us" / "oh" / "franklin.json").write_text("{}\n")
    git(oa, "add", "-A")
    git(oa, "commit", "-q", "-m", "two")
    return oa, old, git(oa, "rev-parse", "HEAD")


def test_changed_paths_and_affected_jobs(tmp_path):
    oa, old, new = fake_oa(tmp_path)
    changed = oa_sync.changed_paths(str(oa), old, new)
    assert changed == ["us/oh/franklin", "us/vt/statewide"]
    affected = {j.id: paths for j, paths in oa_sync.affected_jobs(changed, old, new)}
    # Vermont reads its statewide file; North Dakota's didn't change; Ohio has no registry file, so nothing yet
    assert affected == {"us-vt": ["us/vt/statewide"]}


def test_bump_moves_the_pin_and_lists_jobs(tmp_path):
    oa, old, new = fake_oa(tmp_path)
    pin = tmp_path / "openaddresses.toml"
    pin.write_text(oa_sync.pin_text(old, "2026-11-01"))
    was, now, changed, affected = oa_sync.bump(str(oa), str(pin))
    assert (was, now) == (old, new) and oa_sync.read_pin(pin.read_text()) == new
    body = oa_sync.summary(changed, affected, was, now)
    assert "`us-vt`" in body and "`us/vt/statewide`" in body and "us-nd" not in body
    assert oa_sync.bump(str(oa), str(pin))[2:] == ([], [])  # already newest: nothing changes


def test_read_pin():
    assert oa_sync.read_pin(None) is None and oa_sync.read_pin("") is None
    assert oa_sync.read_pin(oa_sync.pin_text("abc", "2026-11-26")) == "abc"


def test_registry_paths_stand_in():
    vt = registry.job("us-vt")
    assert "us/vt/statewide" in oa_sync._registry_paths(vt)
    assert oa_sync._registry_paths(registry.job("us-oh")) == []
