"""The single place where concrete classes are chosen and handed to the services."""
from __future__ import annotations

import importlib
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
from ..ports.tool import ToolAdapter
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
from .tools import TOOLS, ToolEntry, label, installed
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

    def close(self) -> None:
        """Close the store."""
        self.store.close()


def load_adapters(entries: Sequence[ToolEntry], tools_home: Path,
                  roots: Mapping[str, Path | str] | None = None) -> tuple[dict[str, ToolAdapter], dict[str, str]]:
    """Build the adapter of every listed tool that exists, and say why the others do not.

    A tool whose module is missing, does not import or does not construct is
    left out rather than failing every command.
    """
    roots = roots or {}
    adapters: dict[str, ToolAdapter] = {}
    unavailable: dict[str, str] = {}
    for entry in entries:
        root = Path(roots[entry.id]) if entry.id in roots else tools_home / entry.home
        try:
            adapter = getattr(importlib.import_module(entry.module), entry.adapter)(root)
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
          installation_probe: Callable[[str], bool] = installed) -> Engine:
    """Create the store, the adapters and the services.

    `root` is Baton's folder; without it BATON_HOME, then the Application Support
    folder. Tests pass a temporary `root`, which also moves the tools home inside
    it. `adapter_roots` sets one tool's root, `tools_home` the common one, and
    `adapters` replaces the adapter list altogether (fakes).
    """
    folder, explicit = resolve_root(root, environ)
    private_directory(folder)
    clock = clock or SystemClock()
    # A folder passed in code is a deliberate isolation (tests): an inherited
    # BATON_TOOLS_HOME must not point the adapters back at other files.
    home = resolve_tools_home(folder, explicit, tools_home, {} if root is not None else environ)
    if adapters is None:
        loaded, unavailable = load_adapters(entries, home, adapter_roots)
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
    return Engine(folder, store, clock, loaded, plans, home, unavailable, installation_probe,
                  tuple(dict.fromkeys([entry.id for entry in entries] + list(loaded))))
