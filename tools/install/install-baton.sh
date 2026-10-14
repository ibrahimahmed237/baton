#!/bin/sh
# Install only the repository launcher; never invoke any coding tool.
set -eu
BATON_REPO=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
BATON_PYTHON=$(command -v python3)
export BATON_REPO BATON_PYTHON
"$BATON_PYTHON" - <<'PY'
import os
from pathlib import Path
import shlex
import sys
sys.path.insert(0, os.environ['BATON_REPO'])
from baton.notes.catalogue import get
repo = os.environ['BATON_REPO']
python = os.environ['BATON_PYTHON']
path = Path.home() / '.local/bin/baton'
launcher = '#!/bin/sh\n# Baton repository launcher\nexport BATON_COMMAND=' + shlex.quote(str(path)) + '\nexport PYTHONPATH=' + shlex.quote(repo) + '${PYTHONPATH:+:"$PYTHONPATH"}\nexec ' + shlex.quote(python) + ' -m baton.cli.main "$@"\n'
if any(parent.is_symlink() for parent in (path, *path.parents)) or (path.exists() and (not path.is_file() or path.stat().st_nlink != 1 or path.read_text() != launcher)):
    print(get('setup.launcher_conflict').to_dict({'path': str(path)})['text'])
    sys.exit(1)
path.parent.mkdir(parents=True, exist_ok=True)
if not path.exists():
    with path.open('x') as stream:
        stream.write(launcher)
path.chmod(0o755)
print(get('setup.launcher_installed').to_dict({'path': str(path)})['text'])
PY
