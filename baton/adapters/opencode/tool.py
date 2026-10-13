"""Compose OpenCode ports under an explicit injectable root."""
from datetime import datetime, timezone
from pathlib import Path
import subprocess

from .app import InertProcess, OpenCodeApp, SystemProcess
from .facts import FACTS
from .hooks import OpenCodeHooks
from .locator import OpenCodeLocator
from .reader import OpenCodeReader
from .runner import OpenCodeRunner
from .state import OpenCodeState
from .writer import OpenCodeWriter


class OpenCodeAdapter:
    """Default construction never observes or launches real apps or commands."""

    name = "opencode"
    facts = FACTS

    def __init__(self, root, *, process=None, command=None, binary=None, now=None,
                 allowed_chat_ids=(), project_for_folder=None, model=None, chat_status=None,
                 hook_entrypoints_available=None, plugin_loaded=None, hook_executable="baton", rollback_root=None,
                 plugin_folder=None, unfinished_timeout=600, close_timeout=10,
                 monotonic=None, sleep=None):
        self.root = Path(root).resolve()
        self.allowed_chat_ids = frozenset(allowed_chat_ids)
        self.process = process if process is not None else InertProcess()
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.model = model
        self.chat_status = chat_status
        self.unfinished_timeout = unfinished_timeout
        self.locator = OpenCodeLocator(self.root, self.require_chat)
        default_rollback = self.locator.inside(self.root / ".baton-rollback/opencode")
        self.rollback_root = Path(rollback_root).absolute() if rollback_root is not None else default_rollback
        self.receipt_locator = OpenCodeLocator(self.rollback_root)
        self.project_for_folder = project_for_folder or self._existing_project
        self.hooks = OpenCodeHooks(self, hook_entrypoints_available, plugin_loaded, hook_executable, plugin_folder)
        self.reader = OpenCodeReader(self)
        self.state = OpenCodeState(self)
        self.writer = OpenCodeWriter(self)
        self.runner = OpenCodeRunner(command, binary, self.root)
        self.app = OpenCodeApp(self, close_timeout, monotonic, sleep)

    def require_chat(self, chat_id):
        from ...domain.errors import NotAvailable
        created = self.writer.created if hasattr(self, "writer") else set()
        if chat_id not in self.allowed_chat_ids | created:
            raise NotAvailable()

    def _existing_project(self, folder):
        with self.locator.connect() as db:
            row = db.execute("SELECT id FROM project WHERE worktree=?", (folder,)).fetchone()
        return row[0] if row else None

    @classmethod
    def on_this_machine(cls, root, **options):
        """Opt into real desktop controls; writes still require explicitly scoped IDs."""
        if options.get("rollback_root") is None:
            raise ValueError("rollback_root_required")
        def first_commit(folder):
            result = subprocess.run(["git", "-C", folder, "rev-list", "--max-parents=0", "HEAD"],
                                    capture_output=True, text=True, timeout=5)
            return result.stdout.splitlines()[0] if result.returncode == 0 and result.stdout.strip() else None
        adapter = cls(root, **{"process": SystemProcess(), "command": subprocess.run,
                              "project_for_folder": first_commit, **options})
        adapter.runner.root = None
        adapter.runner.machine_environment = True
        return adapter
