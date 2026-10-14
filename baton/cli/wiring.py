"""The single place where concrete classes are chosen and handed to the services."""
from __future__ import annotations

import importlib
import inspect
import logging
import os
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Callable, Mapping, Sequence

from ..domain.errors import NotAvailable
from ..ledger.sqlite_store import Ledger
from ..ports.clock import Clock, SystemClock
from ..ports.store import RecordStore
from ..ports.tool import ToolAdapter, WriteReceipt
from ..services.applier import Applier
from ..services.brief import BriefService
from ..services.linker import Linker
from ..services.merger import Merger
from ..services.undo import Undo
from ..services.read_views import ReadViews
from ..services.setup_read import SetupRead
from ..services.settings_read import SettingsRead
from ..services.transcripts import FolderTranscripts
from .plans import FilePlanStore, PlanBook
from .tools import TOOLS, ToolEntry, label, installed, installed_in
from .storage import command_lock, private_directory, private_file

logger = logging.getLogger(__name__)

HOME_VARIABLE = "BATON_HOME"
TOOLS_HOME_VARIABLE = "BATON_TOOLS_HOME"
STORE_FILE = "baton.sqlite"
PLANS_FOLDER = "plans"


def default_root(home: Path | None = None) -> Path:
    """Return where Baton keeps its record on a Mac."""
    return (home or Path.home()) / "Library" / "Application Support" / "Baton"


def resolve_root(root: Path | str | None = None, environ: Mapping[str, str] | None = None,
                 home: Path | None = None) -> tuple[Path, bool]:
    """Return Baton's folder and whether it was chosen explicitly (an argument or BATON_HOME)."""
    environ = os.environ if environ is None else environ
    if root is not None:
        return Path(root), True
    if environ.get(HOME_VARIABLE):
        return Path(environ[HOME_VARIABLE]), True
    return default_root(home), False


def resolve_tools_home(root: Path, explicit_root: bool, tools_home: Path | str | None = None,
                       environ: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    """Return the folder the tool adapters look inside.

    A Baton folder chosen explicitly (tests, BATON_HOME) gets a folder of its own
    for the tools, so a test or a trial run can never read the real chats.
    BATON_TOOLS_HOME points a trial run at a different set of tool files.
    """
    environ = os.environ if environ is None else environ
    if tools_home is not None:
        return Path(tools_home)
    if environ.get(TOOLS_HOME_VARIABLE):
        return Path(environ[TOOLS_HOME_VARIABLE])
    return root / "tools" if explicit_root else (home or Path.home())


def is_sandboxed(explicit_root: bool, tools_home: Path | str | None = None,
                 adapter_roots: Mapping[str, Path | str] | None = None,
                 environ: Mapping[str, str] | None = None) -> bool:
    """Whether any root was injected (an argument, BATON_HOME, BATON_TOOLS_HOME or per-tool roots).

    This is the one decision about the real machine. Only the default home, where
    nothing was injected, may use real process launchers, real runners, real
    open/quit and the real installation probe; every injected root gets inert ones.
    """
    environ = os.environ if environ is None else environ
    return bool(explicit_root or tools_home is not None or adapter_roots is not None
                or environ.get(TOOLS_HOME_VARIABLE))


def root_probe(entries: Sequence[ToolEntry], tools_home: Path,
               roots: Mapping[str, Path | str] | None = None) -> Callable[[str], bool]:
    """An installation probe that answers only from what is inside each tool's root."""
    roots = roots or {}
    where = {entry.id: (entry, Path(roots[entry.id]) if entry.id in roots else tools_home / entry.home)
             for entry in entries}

    def probe(tool: str) -> bool:
        found = where.get(tool)
        return found is not None and installed_in(*found)
    return probe


@dataclass
class Engine:
    """The store, the adapters and the services, built once per command.

    main() holds command_lock throughout dispatch. Direct callers must hold
    `with engine.command_lock():` before first service access (which can recover
    writes), and retain it through planning/applying. Never nest these locks.
    """
    root: Path
    store: RecordStore
    clock: Clock
    adapters: dict[str, ToolAdapter]
    plans: PlanBook
    tools_home: Path
    unavailable: dict[str, str] = field(default_factory=dict)
    installation_probe: Callable[[str], bool] = installed
    tool_ids: tuple[str, ...] = tuple(entry.id for entry in TOOLS)
    sandboxed: bool = False

    def command_lock(self):
        """Exclude other CLI commands before interpreting pending writes as abandoned."""
        return command_lock(self.root)

    def adapter(self, tool: str) -> ToolAdapter:
        """Return the adapter of a tool, or raise NotAvailable when it is not wired."""
        try:
            return self.adapters[tool]
        except KeyError:
            raise NotAvailable(tool) from None

    @cached_property
    def settings_read(self):
        """Validated defaults and stored choices, without recovery."""
        return SettingsRead(self.store, {
            'notice_on_attach': True, 'offer_relaunch': True, 'add_to_idle_claude': 'on_button',
            'offer_switch_at_limit': True, 'merge': 'ask', 'brief_threshold_tokens': 150000,
            'hide_script_chats': True, 'title_tag': True, 'theme': 'system', 'glass': 62},
            choices={'add_to_idle_claude': ('on_button', 'automatic'), 'merge': ('ask', 'by_time'),
                     'theme': ('system', 'light', 'graphite')},
            bounds={'glass': (40, 95), 'brief_threshold_tokens': (1, None)})

    @cached_property
    def reads(self):
        """Recovery-free projections for the read commands."""
        return ReadViews(self.store, self.adapters, self.clock, self.settings_read, label,
                         lambda: tuple(s for s, a in self.adapters.items() if a.facts.can_release_chat
                                       and self.settings_read.get()['add_to_idle_claude'] == 'automatic'))

    @cached_property
    def setup_read(self):
        """Independent installation and read-only setup observations."""
        return SetupRead(self.adapters, self.tool_ids, self.installation_probe)

    @cached_property
    def setup_install(self):
        from shutil import which
        from ..services.setup_install import SetupInstall
        from ..adapters.setup_files import SetupFiles
        executable = os.environ.get('BATON_COMMAND') or which('baton') or str(Path.home() / '.local/bin/baton')
        return SetupInstall({tool: adapter.hooks for tool, adapter in self.adapters.items()},
                            SetupFiles(self.root), str(Path(executable).absolute()),
                            app_running={tool: adapter.process.running for tool, adapter in self.adapters.items()})

    # Services are built on first use: building one runs the recovery of
    # unfinished writes, which a read command has no business doing.
    @cached_property
    def applier(self) -> Applier:
        """Delivery, refresh and confirmation of waiting turns."""
        return Applier(self.store, self.adapters, self.clock)

    @cached_property
    def briefs(self) -> BriefService:
        """Consented brief generation and creation with private immutable transcripts."""
        return BriefService(self.store, self.adapters, self.clock,
                            FolderTranscripts(self.root / "transcripts"), label)

    @cached_property
    def linker(self) -> Linker:
        """Linking, copying, changing and removing links."""
        return Linker(self.store, self.adapters, self.clock, brief_service=self.briefs)

    @cached_property
    def merger(self) -> Merger:
        """Merge decisions."""
        return Merger(self.store, self.adapters, self.clock)

    @cached_property
    def undo(self) -> Undo:
        """Going back to before an event."""
        return Undo(self.store, self.adapters, self.clock)

    def clear_verified_intents(self) -> None:
        """Only durable committed receipts can replace private crash intents."""
        for entry in self.store.journal_entries():
            adapter = self.adapters.get(entry['tool'])
            verified = getattr(adapter.writer, 'verified', None) if adapter is not None else None
            if entry['state'] == 'committed' and entry.get('post_receipt') and verified:
                try:
                    verified(WriteReceipt(**entry['post_receipt']))
                except Exception:
                    logger.exception('rollback_intent_cleanup_failed')

    def close(self) -> None:
        """Close the store."""
        with self.command_lock():
            self.clear_verified_intents()
        self.store.close()


def load_adapters(entries: Sequence[ToolEntry], tools_home: Path,
                  roots: Mapping[str, Path | str] | None = None, *,
                  sandboxed: bool = True, store_root: Path | None = None) -> tuple[dict[str, ToolAdapter], dict[str, str]]:
    """Build the adapter of every listed tool that exists, and say why the others do not.

    `sandboxed` (the safe default) builds each adapter with only its root, which leaves it
    inert. Only `sandboxed=False` asks the adapter class for its `on_this_machine` form,
    with the real process control and launchers.

    A tool whose module is missing, does not import or does not construct is
    left out rather than failing every command.
    """
    roots = roots or {}
    store_root = Path(store_root).resolve() if store_root is not None else None
    adapters: dict[str, ToolAdapter] = {}
    unavailable: dict[str, str] = {}
    for entry in entries:
        root = Path(roots[entry.id]) if entry.id in roots else tools_home / entry.home
        try:
            factory = getattr(importlib.import_module(entry.module), entry.adapter)
            options = ({'rollback_root': store_root / 'rollback' / entry.id}
                       if store_root is not None and 'rollback_root' in inspect.signature(factory).parameters else {})
            if 'hook_entrypoints_available' in inspect.signature(factory).parameters:
                from .tools import hook_entrypoints_available
                options['hook_entrypoints_available'] = hook_entrypoints_available
            if 'project_root' in inspect.signature(factory).parameters:
                options['project_root'] = root if sandboxed else Path.cwd().resolve()
            if 'plugin_folder' in inspect.signature(factory).parameters:
                options['plugin_folder'] = root if sandboxed else Path.cwd().resolve()
            adapter = (factory if sandboxed else getattr(factory, "on_this_machine", factory))(root, **options)
            from ..adapters.setup_files import SetupFiles
            record = SetupFiles(store_root).recorded(entry.id) if store_root is not None else None
            if record and hasattr(adapter.hooks, 'use_installed_command'):
                if sandboxed and not Path(record['path']).is_relative_to(Path(root).resolve()):
                    raise NotAvailable()
                if hasattr(adapter.hooks, 'use_install_path'):
                    adapter.hooks.use_install_path(record['path'])
                adapter.hooks.use_installed_command(record['executable'])
            if getattr(adapter, "name", None) != entry.id:
                raise LookupError("%s reports the name %r" % (entry.adapter, getattr(adapter, "name", None)))
        except ModuleNotFoundError as error:
            missing = error.name or ""
            elsewhere = not (entry.module == missing or entry.module.startswith(missing + "."))
            unavailable[entry.id] = str(error) if elsewhere else "not built yet"
        except Exception as error:
            logger.warning("the %s adapter is not wired: %s", entry.id, error)
            unavailable[entry.id] = "%s: %s" % (type(error).__name__, error)
        else:
            adapters[entry.id] = adapter
    return adapters, unavailable


def build(root: Path | str | None = None, *, clock: Clock | None = None,
          adapters: Mapping[str, ToolAdapter] | None = None,
          adapter_roots: Mapping[str, Path | str] | None = None,
          tools_home: Path | str | None = None,
          environ: Mapping[str, str] | None = None,
          entries: Sequence[ToolEntry] = TOOLS,
          installation_probe: Callable[[str], bool] | None = None) -> Engine:
    """Create the store, the adapters and the services.

    `root` is Baton's folder; without it BATON_HOME, then the Application Support
    folder. Tests pass a temporary `root`, which also moves the tools home inside
    it. `adapter_roots` sets one tool's root, `tools_home` the common one, and
    `adapters` replaces the adapter list altogether (fakes).

    Any injected root makes the engine sandboxed (see `is_sandboxed`): inert adapters
    and an installation probe that looks only inside the roots, unless a probe is passed.
    """
    folder, explicit = resolve_root(root, environ)
    folder = folder.resolve()
    private_directory(folder)
    clock = clock or SystemClock()
    # A folder passed in code is a deliberate isolation (tests): an inherited
    # BATON_TOOLS_HOME must not point the adapters back at other files.
    tools_environ = {} if root is not None else environ
    home = resolve_tools_home(folder, explicit, tools_home, tools_environ)
    sandboxed = is_sandboxed(explicit, tools_home, adapter_roots, tools_environ)
    if installation_probe is None:
        installation_probe = root_probe(entries, home, adapter_roots) if sandboxed else installed
    if adapters is None:
        loaded, unavailable = load_adapters(entries, home, adapter_roots, sandboxed=sandboxed, store_root=folder)
    else:
        loaded, unavailable = dict(adapters), {}
    with command_lock(folder) as directory:
        descriptor = private_file(directory, STORE_FILE)
        os.close(descriptor)
        store = Ledger(str(folder / STORE_FILE))
        try:
            plans = PlanBook(FilePlanStore(folder / PLANS_FOLDER), clock)
        except BaseException:
            store.close()
            raise
    engine = Engine(folder, store, clock, loaded, plans, home, unavailable, installation_probe,
                    tuple(dict.fromkeys([entry.id for entry in entries] + list(loaded))), sandboxed)
    with engine.command_lock():
        engine.clear_verified_intents()
    return engine
