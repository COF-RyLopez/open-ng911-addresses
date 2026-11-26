"""The build jobs CI runs, as a JSON list for a GitHub Actions matrix.

    python -m open_ng911.jobs            ["us-vt"]   (enabled jobs)
    python -m open_ng911.jobs --all      every job id
"""
import json
import sys

from . import registry

if __name__ == "__main__":
    print(json.dumps([j.id for j in registry.jobs() if j.enabled or "--all" in sys.argv]))
