#!/bin/sh
# Install only the repository launcher; never invoke any coding tool.
set -eu
BATON_REPO=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
BATON_PYTHON=$(command -v python3)
export BATON_REPO BATON_PYTHON
"$BATON_PYTHON" -B - <<'PY'
import os
from pathlib import Path
import shlex
import sys
import stat
sys.path.insert(0, os.environ['BATON_REPO'])
from baton.notes.catalogue import get
from baton.adapters.setup_files import directory
from baton.ports.setup_install import InstallRefused
repo = os.environ['BATON_REPO']
python = os.environ['BATON_PYTHON']
path = Path.home() / '.local/bin/baton'
launcher = '#!/bin/sh\n# Baton repository launcher\nexport BATON_COMMAND=' + shlex.quote(str(path)) + '\nexport PYTHONPATH=' + shlex.quote(repo) + '${PYTHONPATH:+:"$PYTHONPATH"}\nexport PYTHONDONTWRITEBYTECODE=1\nexec ' + shlex.quote(python) + ' -B -m baton.cli.main "$@"\n'
try:
    with directory(path.parent, create=True) as descriptor:
        try:
            handle = os.open(path.name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
            created = True
        except FileExistsError:
            handle = os.open(path.name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
            created = False
        try:
            info = os.fstat(handle)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1: raise InstallRefused()
            with os.fdopen(os.dup(handle), 'r+' if not created else 'w') as stream:
                if created:
                    stream.write(launcher)
                    stream.flush()
                elif stream.read() != launcher: raise InstallRefused()
            # Permissions apply to the pinned inode, never a substituted symlink.
            os.fchmod(handle, 0o755)
            os.fsync(handle)
            with directory(path.parent) as fresh:
                if (os.fstat(fresh).st_dev, os.fstat(fresh).st_ino) != (os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino):
                    raise InstallRefused()
            current = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino): raise InstallRefused()
            os.fsync(descriptor)
        finally: os.close(handle)
except (OSError, UnicodeError, InstallRefused):
    print(get('setup.launcher_conflict').to_dict({'path': str(path)})['text'])
    sys.exit(1)
print(get('setup.launcher_installed').to_dict({'path': str(path)})['text'])
PY
