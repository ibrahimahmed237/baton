"""Cursor app capabilities measured in docs/SPIKE-M0.md."""
from ...domain.capabilities import Capabilities, HookNeed, Visibility, WriteWindow

FACTS = Capabilities(WriteWindow.APP_CLOSED, Visibility.AFTER_RELAUNCH,
                     Visibility.AFTER_RELAUNCH, False, True, False, False,
                     False, True, HookNeed.NONE, ('18',), False)
