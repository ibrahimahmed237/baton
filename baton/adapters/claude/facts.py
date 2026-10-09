"""Capabilities measured by M0; native schema plus checked CLI version."""
from ...domain.capabilities import Capabilities, HookNeed, Visibility, WriteWindow
FACTS = Capabilities(WriteWindow.CLOSED_OR_RELEASED, Visibility.AFTER_RELAUNCH,
 Visibility.AFTER_RELAUNCH, True, False, True, True, True, True, HookNeed.NONE,
 ("2.1.284",), True)
