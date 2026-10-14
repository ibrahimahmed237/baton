"""OpenCode facts measured in the M0b spike."""
from ...domain.capabilities import Capabilities, HookNeed, Visibility, WriteWindow

SCHEMA_VERSION = "session-message-part"
FACTS = Capabilities(WriteWindow.ANY_TIME, Visibility.AT_ONCE, Visibility.ON_REOPEN_CHAT,
                     True, True, False, False, False, False, HookNeed.RESTART_ONCE,
                     (SCHEMA_VERSION,), True)
