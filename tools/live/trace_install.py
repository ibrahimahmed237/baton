"""Run `baton setup install --tool claude` for this repository and print where a refusal comes from.

Developer tool for the CP3 live check: same preview and confirm as the command, plus the
location of the check that refused. Writes nothing unless every check passes.
"""
import io
import json
import sys
import traceback
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import baton.ports.setup_install as port  # noqa: E402

_init = port.InstallRefused.__init__


import baton.adapters.setup_files as files  # noqa: E402

_attributes = files.attributes


def _shown_attributes(descriptor, name):
    found = _attributes(descriptor, name)
    print("attributes of", name, "->", [n for n, _ in found], file=sys.stderr)
    return found


files.attributes = _shown_attributes


def _traced(self, *args, **kwargs):
    print("REFUSED AT:", file=sys.stderr)
    traceback.print_stack(limit=5, file=sys.stderr)
    _init(self, *args, **kwargs)


port.InstallRefused.__init__ = _traced

from baton.cli.main import main  # noqa: E402

base = ["setup", "install", "--tool", "claude", "--project", str(REPO), "--json"]
out = io.StringIO()
with redirect_stdout(out):
    main(base)
plan = json.loads(out.getvalue()).get("plan_id")
print("preview plan:", (plan or "none")[:12])
if plan:
    out = io.StringIO()
    with redirect_stdout(out):
        main(base[:-1] + ["--confirm", plan, "--json"])
    result = json.loads(out.getvalue())
    print("applied:", result.get("applied"), "| error:", result.get("error", {}).get("kind"))
